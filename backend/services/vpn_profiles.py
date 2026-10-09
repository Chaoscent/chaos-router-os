"""
VPN client profiles: connect the router (and its LAN) to a remote
WireGuard or OpenVPN server, e.g. a VPN provider.

Imported configs are sanitised: anything that could run commands
as root is removed, and NAT is added by our own hooks instead.

"full_tunnel" routes all internet traffic of the router and its LAN
through the VPN, whatever the profile itself says. It is applied when
the files are written; the stored config stays as imported.
"""

import re
import time

from services.config import load_running

from services import transaction

from services.vpn_common import (
    which,
    valid_name,
    write_root_file,
    remove_root_file,
    unit_active,
    systemctl,
    start_unit,
    stop_unit,
    get_lan_interfaces,
    firewall_rules_for,
    sync_firewall
)

from services.wireguard import valid_key, has_wireguard
from services.openvpn import has_openvpn, ensure_nat_script, NAT_SCRIPT

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# vpn_profiles.json in /var/lib/chaos-router-os (holds keys and passwords).
PROFILES_SETTINGS = "vpn_profiles"

TYPES = ("wireguard", "openvpn")

MAX_CONFIG_SIZE = 64 * 1024

# WireGuard keys we keep, by section. Everything else is dropped,
# notably PreUp/PostUp/PreDown/PostDown (shell commands as root).
WIREGUARD_KEYS = {
    "interface": {
        k.lower(): k for k in (
            "PrivateKey", "Address", "DNS", "MTU",
            "ListenPort", "Table", "FwMark"
        )
    },
    "peer": {
        k.lower(): k for k in (
            "PublicKey", "PresharedKey", "AllowedIPs",
            "Endpoint", "PersistentKeepalive"
        )
    }
}

# OpenVPN directives that run programs, load code or write files.
# dev, dev-type and auth-user-pass are replaced by our own values.
OPENVPN_BLOCKED = {
    "up", "down", "route-up", "route-pre-down", "ipchange",
    "tls-verify", "auth-user-pass-verify", "client-connect",
    "client-disconnect", "learn-address", "plugin", "script-security",
    "config", "cd", "chroot", "writepid", "log", "log-append", "status",
    "daemon", "tmp-dir", "iproute", "askpass", "dev-node", "syslog",
    "machine-readable-output"
}

# Directives that point at files; only inline blocks are supported.
OPENVPN_FILE_DIRECTIVES = {
    "ca", "cert", "key", "tls-auth", "tls-crypt", "tls-crypt-v2",
    "pkcs12", "secret", "extra-certs", "dh", "crl-verify",
    "http-proxy-user-pass"
}

CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


# -------------------------------------------------------------------
# Storage
# -------------------------------------------------------------------

def load_profiles():

    return load_running(PROFILES_SETTINGS, {"profiles": []}).get("profiles", [])


def save_profiles(profiles):
    """
    Applies the profile list through safe apply. Profiles cannot cut
    off the router's LAN, so no confirmation is needed.
    """

    return transaction.change(
        PROFILES_SETTINGS,
        {"profiles": profiles},
        confirm=False
    )


def find_profile(profiles, profile_id):

    return next((p for p in profiles if p["id"] == profile_id), None)


def interface_name(profile):

    prefix = "wgc" if profile["type"] == "wireguard" else "ovpnc"

    return f"{prefix}{profile['id']}"


def unit_name(profile):

    if profile["type"] == "wireguard":
        return f"wg-quick@{interface_name(profile)}"

    return f"openvpn-client@{interface_name(profile)}"


def config_path(profile):

    if profile["type"] == "wireguard":
        return f"/etc/wireguard/{interface_name(profile)}.conf"

    return f"/etc/openvpn/client/{interface_name(profile)}.conf"


def auth_path(profile):

    return f"/etc/openvpn/client/{interface_name(profile)}.auth"


# -------------------------------------------------------------------
# WireGuard import
# -------------------------------------------------------------------

def sanitize_wireguard(text):
    """
    Returns (True, sections, dropped) or (False, message, None).
    sections: [{"type": "interface"|"peer", "items": [(key, value)]}]
    """

    sections = []
    current = None
    dropped = []

    for raw in text.splitlines():

        line = raw.strip()

        if not line or line.startswith(("#", ";")):
            continue

        match = re.fullmatch(r"\[(\w+)\]", line)

        if match:

            kind = match.group(1).lower()

            if kind not in WIREGUARD_KEYS:
                return False, f"Unknown section [{match.group(1)}].", None

            current = {"type": kind, "items": []}
            sections.append(current)
            continue

        if current is None or "=" not in line:
            return False, f"Unrecognised line: {line[:40]}", None

        key, value = [x.strip() for x in line.split("=", 1)]

        canonical = WIREGUARD_KEYS[current["type"]].get(key.lower())

        if not canonical:
            dropped.append(key)
            continue

        if CONTROL_RE.search(value):
            return False, f"Invalid value for {canonical}.", None

        if canonical in ("PrivateKey", "PublicKey", "PresharedKey") \
                and not valid_key(value):
            return False, f"Invalid {canonical}.", None

        current["items"].append((canonical, value))

    interfaces = [s for s in sections if s["type"] == "interface"]
    peers = [s for s in sections if s["type"] == "peer"]

    if len(interfaces) != 1:
        return False, "Config must have exactly one [Interface] section.", None

    keys = dict(interfaces[0]["items"])

    if "PrivateKey" not in keys or "Address" not in keys:
        return False, "[Interface] needs PrivateKey and Address.", None

    if not peers:
        return False, "Config needs at least one [Peer] section.", None

    for peer in peers:

        keys = dict(peer["items"])

        if "PublicKey" not in keys or "AllowedIPs" not in keys:
            return False, "Every [Peer] needs PublicKey and AllowedIPs.", None

    if not any("Endpoint" in dict(p["items"]) for p in peers):
        return False, "No [Peer] has an Endpoint to connect to.", None

    return True, sections, dropped


def render_wireguard(sections):

    lines = [
        "# Imported by Chardsoft Router OS. Do not edit by hand.",
        ""
    ]

    # wg-quick needs resolvconf to apply DNS; without it, it fails.
    has_resolvconf = which("resolvconf") is not None

    for section in sections:

        lines.append(f"[{section['type'].capitalize()}]")

        for key, value in section["items"]:

            if key == "DNS" and not has_resolvconf:
                continue

            lines.append(f"{key} = {value}")

        if section["type"] == "interface":

            # LAN devices reach the tunnel through the router.
            nat = "iptables -t nat %s POSTROUTING -o %%i -j MASQUERADE"

            lines.append(f"PostUp = {nat % '-A'}")
            lines.append(f"PostDown = {nat % '-D'}")

        lines.append("")

    return "\n".join(lines)


# -------------------------------------------------------------------
# OpenVPN import
# -------------------------------------------------------------------

def sanitize_openvpn(text, interface, has_credentials, auth_file):
    """
    Returns (True, config, dropped) or (False, message, None).
    """

    output = []
    dropped = []

    block = None
    dev_type = "tun"
    needs_auth = False
    has_remote = False
    is_client = False

    for raw in text.splitlines():

        line = raw.strip()

        # Inline blocks (<ca> ... </ca>) are copied verbatim.
        if block:

            output.append(line)

            if line.lower() == f"</{block}>":
                block = None

            continue

        match = re.fullmatch(r"<([A-Za-z0-9-]+)>", line)

        if match:
            block = match.group(1).lower()
            output.append(line)
            continue

        if not line or line.startswith(("#", ";")):
            continue

        if CONTROL_RE.search(line):
            return False, "Profile contains invalid characters.", None

        parts = line.split()
        directive = parts[0].lower().lstrip("-")
        args = parts[1:]

        if directive == "dev" and args:
            if args[0].startswith("tap"):
                dev_type = "tap"
            continue

        if directive == "dev-type" and args:
            if args[0] in ("tun", "tap"):
                dev_type = args[0]
            continue

        if directive == "auth-user-pass":
            needs_auth = True
            continue

        if directive.startswith("management") or directive in OPENVPN_BLOCKED:
            dropped.append(directive)
            continue

        if directive in OPENVPN_FILE_DIRECTIVES and args \
                and args[0] != "[inline]" and not args[0].isdigit():
            return False, (
                f"The profile loads {directive} from a file. "
                f"Use a profile with inline certificates (<{directive}> blocks)."
            ), None

        if directive == "remote":
            has_remote = True

        if directive in ("client", "tls-client", "pull"):
            is_client = True

        output.append(line)

    if block:
        return False, f"Unclosed <{block}> block.", None

    if not is_client:
        return False, "This is not a client profile (missing 'client').", None

    if not has_remote:
        return False, "The profile has no 'remote' server.", None

    if needs_auth and not has_credentials:
        return False, "This profile needs a username and password.", None

    header = [
        "# Imported by Chardsoft Router OS. Do not edit by hand.",
        f"dev {interface}",
        f"dev-type {dev_type}"
    ]

    if has_credentials:
        header.append(f"auth-user-pass {auth_file}")

    footer = [
        "",
        "# NAT for LAN devices using the tunnel.",
        "script-security 2",
        f"up {NAT_SCRIPT}",
        f"down {NAT_SCRIPT}"
    ]

    return True, "\n".join(header + output + footer) + "\n", dropped


# -------------------------------------------------------------------
# Import / delete
# -------------------------------------------------------------------

def import_profile(data):
    """
    Returns (ok, message, profile_view).
    """

    name = str(data.get("name") or "").strip()
    kind = data.get("type")
    text = str(data.get("config") or "")
    username = str(data.get("username") or "")
    password = str(data.get("password") or "")

    if not valid_name(name):
        return False, "Name must be 1-32 letters, numbers, - or _.", None

    if kind not in TYPES:
        return False, "Type must be WireGuard or OpenVPN.", None

    if not text.strip():
        return False, "Paste or upload a config file.", None

    if len(text) > MAX_CONFIG_SIZE:
        return False, "Config file is too large.", None

    if bool(username) != bool(password):
        return False, "Enter both username and password, or neither.", None

    if "\n" in username or "\n" in password:
        return False, "Username and password must be a single line.", None

    profiles = load_profiles()

    if any(p["name"] == name for p in profiles):
        return False, f"A profile named {name} already exists.", None

    profile = {
        "id": max([p["id"] for p in profiles] + [0]) + 1,
        "name": name,
        "type": kind,
        "autostart": False,
        "full_tunnel": data.get("full_tunnel") is True,
        "created": int(time.time()),
        "username": username,
        "password": password
    }

    notes = []

    if kind == "wireguard":

        ok, result, dropped = sanitize_wireguard(text)

        if not ok:
            return False, result, None

        profile["config"] = render_wireguard(result)

        if "DNS" in [k for sec in result for k, _ in sec["items"]] \
                and "DNS =" not in profile["config"]:
            notes.append(
                "DNS was skipped because resolvconf is not available."
            )

    else:

        ok, result, dropped = sanitize_openvpn(
            text,
            interface_name(profile),
            bool(username),
            auth_path(profile)
        )

        if not ok:
            return False, result, None

        profile["config"] = result

    profiles.append(profile)

    outcome = save_profiles(profiles)

    if not outcome["success"]:
        return False, outcome["message"], None

    message = "Profile imported."

    if dropped:
        message += (
            " Removed for safety: "
            + ", ".join(sorted(set(dropped))) + "."
        )

    if notes:
        message += " " + " ".join(notes)

    return True, message, profile_view(profile)


# -------------------------------------------------------------------
# All traffic through the VPN
# -------------------------------------------------------------------

def _wireguard_sections(config):
    """
    [(type, [line indexes])] of a rendered WireGuard config.
    """

    sections = []

    for index, line in enumerate(config.splitlines()):

        match = re.fullmatch(r"\[(\w+)\]", line.strip())

        if match:
            sections.append((match.group(1).lower(), [index]))
        elif sections:
            sections[-1][1].append(index)

    return sections


def _key_value(line):

    key, _, value = line.partition("=")

    return key.strip(), value.strip()


def wireguard_full_tunnel(config):
    """
    AllowedIPs of the peer(s) with an Endpoint become 0.0.0.0/0 (and
    ::/0 when the tunnel has an IPv6 address), so wg-quick routes all
    traffic through it.
    """

    lines = config.splitlines()
    sections = _wireguard_sections(config)

    ipv6 = any(
        key == "Address" and ":" in value
        for kind, indexes in sections if kind == "interface"
        for key, value in (_key_value(lines[i]) for i in indexes)
    )

    everything = "0.0.0.0/0, ::/0" if ipv6 else "0.0.0.0/0"

    for kind, indexes in sections:

        keys = [_key_value(lines[i])[0] for i in indexes]

        if kind != "peer" or "Endpoint" not in keys:
            continue

        for i in indexes:
            if _key_value(lines[i])[0] == "AllowedIPs":
                lines[i] = f"AllowedIPs = {everything}"

    return "\n".join(lines) + "\n"


def routes_all_by_profile(profile):
    """
    Whether the imported profile itself already sends all traffic
    through the tunnel (an OpenVPN server may also push this).
    """

    config = profile["config"]

    if profile["type"] == "wireguard":
        return bool(re.search(r"^AllowedIPs\s*=.*\b0\.0\.0\.0/0", config, re.MULTILINE))

    return bool(re.search(r"^redirect-gateway\b", config, re.MULTILINE))


def effective_config(profile):

    config = profile["config"]

    if not profile.get("full_tunnel"):
        return config

    if profile["type"] == "wireguard":
        return wireguard_full_tunnel(config)

    return config.rstrip("\n") + (
        "\n\n# All traffic through the VPN (Chardsoft Router OS).\n"
        "redirect-gateway def1\n"
    )


def write_profile_files(profile):

    ok, result = write_root_file(config_path(profile), effective_config(profile))

    if not ok:
        return False, result

    if profile["type"] == "openvpn":

        ok, result = ensure_nat_script()

        if not ok:
            return False, result

        if profile.get("username"):

            ok, result = write_root_file(
                auth_path(profile),
                f"{profile['username']}\n{profile['password']}\n"
            )

            if not ok:
                return False, result

    return True, "OK"


def delete_profile(profile_id):

    profiles = load_profiles()
    profile = find_profile(profiles, profile_id)

    if not profile:
        return False, "Profile not found."

    outcome = save_profiles([p for p in profiles if p["id"] != profile_id])

    if not outcome["success"]:
        return False, outcome["message"]

    stop_unit(unit_name(profile))
    sync_firewall(firewall_owner(profile), [])

    remove_root_file(config_path(profile))

    if profile["type"] == "openvpn":
        remove_root_file(auth_path(profile))

    return True, "Profile deleted."


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def firewall_owner(profile):

    return f"vpn-profile-{profile['id']}"


def profile_firewall_rules(profile):

    return firewall_rules_for(f"VPN client {profile['name']}", [
        ["route", "allow", "in", "on", lan,
         "out", "on", interface_name(profile)]
        for lan in get_lan_interfaces()
    ])


def apply_profiles():
    """
    Writes every running profile to disk, its firewall rules to ufw,
    and enables only the autostart profile at boot.
    """

    warnings = []

    for profile in load_profiles():

        ok, result = write_profile_files(profile)

        if not ok:
            return False, f"Could not write profile {profile['name']}: {result}"

        warning = sync_firewall(
            firewall_owner(profile),
            profile_firewall_rules(profile)
        )

        if warning:
            warnings.append(warning)

        if tool_missing(profile):
            continue

        ok, result = systemctl(
            "enable" if profile["autostart"] else "disable",
            unit_name(profile)
        )

        if not ok:
            return False, result

    return True, warnings[0] if warnings else "VPN profiles applied."


# -------------------------------------------------------------------
# Connect / disconnect
# -------------------------------------------------------------------

def tool_missing(profile):

    if profile["type"] == "wireguard" and not has_wireguard():
        return "WireGuard is not available."

    if profile["type"] == "openvpn" and not has_openvpn():
        return "OpenVPN is not available."

    return None


def connect_profile(profile_id):

    profiles = load_profiles()
    profile = find_profile(profiles, profile_id)

    if not profile:
        return False, "Profile not found."

    missing = tool_missing(profile)

    if missing:
        return False, missing

    # Two tunnels fighting over the default route breaks both.
    for other in profiles:

        if other["id"] != profile_id and unit_active(unit_name(other)):
            systemctl("stop", unit_name(other))

    ok, result = write_profile_files(profile)

    if not ok:
        return False, f"Could not write the profile: {result}"

    warning = sync_firewall(
        firewall_owner(profile),
        profile_firewall_rules(profile)
    )

    ok, result = start_unit(unit_name(profile), enable=profile["autostart"])

    if not ok:
        return False, f"Could not connect: {result}"

    return True, warning or f"Connected to {profile['name']}."


def disconnect_profile(profile_id):

    profile = find_profile(load_profiles(), profile_id)

    if not profile:
        return False, "Profile not found."

    ok, result = systemctl("stop", unit_name(profile))

    if not ok:
        return False, result

    return True, f"Disconnected from {profile['name']}."


def set_full_tunnel(profile_id, enabled):
    """
    Routes all internet traffic through this profile (or back to the
    profile's own routing). A connected profile reconnects.
    """

    profiles = load_profiles()
    profile = find_profile(profiles, profile_id)

    if not profile:
        return False, "Profile not found."

    profile["full_tunnel"] = enabled

    outcome = save_profiles(profiles)

    if not outcome["success"]:
        return False, outcome["message"]

    message = (
        f"All traffic now goes through {profile['name']}."
        if enabled else f"{profile['name']} uses its own routing."
    )

    if unit_active(unit_name(profile)):

        ok, result = start_unit(unit_name(profile), enable=profile["autostart"])

        if not ok:
            return False, f"Saved, but reconnecting failed: {result}"

        message += " Reconnected."

    return True, message


def set_autostart(profile_id, enabled):
    """
    Only one profile may connect at boot.
    """

    profiles = load_profiles()
    profile = find_profile(profiles, profile_id)

    if not profile:
        return False, "Profile not found."

    for other in profiles:
        other["autostart"] = enabled and other["id"] == profile_id

    outcome = save_profiles(profiles)

    if not outcome["success"]:
        return False, outcome["message"]

    return True, (
        f"{profile['name']} connects at boot."
        if enabled else "Autostart turned off."
    )


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def profile_view(profile):

    return {
        "id": profile["id"],
        "name": profile["name"],
        "type": profile["type"],
        "autostart": profile["autostart"],
        "full_tunnel": profile.get("full_tunnel") is True,
        "routes_all_by_profile": routes_all_by_profile(profile),
        "created": profile.get("created"),
        "interface": interface_name(profile),
        "has_credentials": bool(profile.get("username"))
    }


def get_profiles_status():

    views = []

    for profile in load_profiles():

        view = profile_view(profile)
        view["connected"] = unit_active(unit_name(profile))

        views.append(view)

    return views
