"""
Config backup and restore.

A backup is one JSON file with every persistent setting
(/var/lib/chaos-router-os) and the OpenVPN certificate authority.
It is uploaded again as-is: nothing to unpack or edit.

Restoring never trusts the file: every area is validated again with
the same rules as the dashboard (an edited backup must not be able to
run commands as root), then applied through safe apply, so a backup
that does not work on this router is rolled back like any change.
"""

import hashlib
import ipaddress
import json
import re
import time

from services.config import (
    load_persistent,
    has_persistent,
    load_system,
    save_system
)

from services import transaction

from services.logs import log_event

# -------------------------------------------------------------------
# Format
# -------------------------------------------------------------------

FORMAT = "chaos-router-os-backup"
VERSION = 1

MAX_BACKUP_SIZE = 10 * 1024 * 1024

PKI_SNAPSHOT = "openvpn_pki"

SAFE_PATH = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
PASSWORD_HASH = re.compile(r"^(scrypt|pbkdf2):\S+$")
RULE_TOKEN = re.compile(r"^[A-Za-z0-9 _.:/,()+@'-]{1,128}$")


def checksum(content):

    raw = json.dumps(content, sort_keys=True, separators=(",", ":"))

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def area_names():

    from services.areas import AREAS

    return list(AREAS)


def area_label(name):

    from services.areas import AREAS

    return AREAS[name].label


# -------------------------------------------------------------------
# Export
# -------------------------------------------------------------------

def create_backup():
    """
    Returns (filename, backup dict).
    """

    from services.system import get_hostname

    config = {
        name: load_persistent(name)
        for name in area_names()
        if has_persistent(name)
    }

    system = {}

    pki = load_system(PKI_SNAPSHOT, None)

    if pki:
        system[PKI_SNAPSHOT] = pki

    content = {"config": config, "system": system}

    hostname = get_hostname()
    created = int(time.time())

    backup = {
        "format": FORMAT,
        "version": VERSION,
        "created": created,
        "hostname": hostname,
        **content,
        "checksum": checksum(content)
    }

    stamp = time.strftime("%Y-%m-%d_%H-%M", time.localtime(created))
    safe_host = re.sub(r"[^A-Za-z0-9-]", "-", hostname)[:32] or "router"

    log_event("backup", f"Config backup downloaded ({len(config)} areas).")

    return f"chaos-router-backup_{safe_host}_{stamp}.json", backup


# -------------------------------------------------------------------
# Validation per area
# -------------------------------------------------------------------

def _require(condition, message):

    if not condition:
        raise ValueError(message)


def _single_line(value, limit=256):

    return isinstance(value, str) and "\n" not in value and "\r" not in value \
        and len(value) <= limit


def _validate_with(validator):
    """
    Wraps a page validator returning (ok, cleaned or message).
    """

    def run(data):

        _require(isinstance(data, dict), "Not a settings object.")

        ok, result = validator(data)

        _require(ok, result)

        return result

    return run


def _validate_network(data):

    from services.network import validate_lan_config, INTERFACE_FIELDS

    interfaces = data.get("interfaces")

    _require(isinstance(interfaces, dict), "Missing interfaces.")

    cleaned = {}

    for name, config in interfaces.items():

        _require(isinstance(config, dict), f"Invalid settings for {name}.")

        ok, message = validate_lan_config(config)

        _require(ok, f"{name}: {message}")

        cleaned[name] = {k: config[k] for k in INTERFACE_FIELDS if k in config}

    role = data.get("eth0_role", "lan")

    _require(role in ("lan", "wan"), "Invalid eth0 mode.")

    result = {"interfaces": cleaned, "eth0_role": role}

    lan = data.get("lan_config")

    if lan:

        _require(isinstance(lan, dict), "Invalid eth0 LAN settings.")

        ok, message = validate_lan_config(lan)

        _require(ok, f"eth0 LAN settings: {message}")

        result["lan_config"] = {k: lan[k] for k in INTERFACE_FIELDS if k in lan}

    return result


def _validate_firewall(data):

    from services.firewall import (
        ACTIONS, POLICIES, POLICY_DIRECTIONS, LOG_LEVELS
    )

    _require(isinstance(data.get("enabled"), bool), "Missing on/off setting.")

    policies = data.get("policies") or {}

    for direction in POLICY_DIRECTIONS:
        _require(policies.get(direction) in POLICIES, f"Invalid {direction} policy.")

    _require(data.get("logging") in LOG_LEVELS, "Invalid logging level.")

    _require(isinstance(data.get("essentials", False), bool), "Invalid essential rules setting.")

    rules = []

    for rule in data.get("rules") or []:

        args = rule.get("args") if isinstance(rule, dict) else None

        _require(
            isinstance(args, list) and args
            and all(isinstance(a, str) and RULE_TOKEN.fullmatch(a) for a in args),
            "Invalid firewall rule."
        )

        action = args[1] if args[0] == "route" and len(args) > 1 else args[0]

        _require(action in ACTIONS, f"Invalid firewall action: {action}")

        rules.append({"id": int(rule.get("id", len(rules) + 1)), "args": args})

    return {
        "enabled": data["enabled"],
        "policies": {d: policies[d] for d in POLICY_DIRECTIONS},
        "logging": data["logging"],
        "essentials": data.get("essentials", False),
        "rules": rules
    }


def _validate_blocked(data):

    from services.clients import normalize_mac

    devices = []

    for device in data.get("devices") or []:

        mac = normalize_mac(device.get("mac") if isinstance(device, dict) else None)

        _require(mac, "Invalid MAC address in the block list.")

        name = device.get("name", "")

        _require(_single_line(name, 64), "Invalid device name.")

        devices.append({
            "mac": mac,
            "name": name,
            "blocked_at": int(device.get("blocked_at", 0))
        })

    return {"devices": devices}


def _validate_wireguard(data):

    from services.wireguard import validate_server, valid_key, DEFAULT_SERVER
    from services.vpn_common import valid_name

    server = data.get("server")

    _require(isinstance(server, dict), "Missing server settings.")

    merged = {**DEFAULT_SERVER, **server}

    ok, result = validate_server(merged)

    _require(ok, result)

    for key in ("private_key", "public_key"):
        _require(not merged.get(key) or valid_key(merged[key]), "Invalid server key.")

    result["private_key"] = merged.get("private_key", "")
    result["public_key"] = merged.get("public_key", "")

    network = ipaddress.IPv4Interface(result["address"]).network

    peers = []

    for peer in data.get("peers") or []:

        _require(isinstance(peer, dict), "Invalid peer.")

        # Names end up in wg0.conf comments: no line breaks allowed.
        _require(valid_name(peer.get("name")), "Invalid peer name.")
        _require(valid_key(peer.get("public_key")), f"Invalid key for {peer['name']}.")

        for key in ("private_key", "preshared_key"):
            _require(not peer.get(key) or valid_key(peer[key]), f"Invalid key for {peer['name']}.")

        address = ipaddress.IPv4Interface(peer.get("address"))

        _require(address.ip in network, f"{peer['name']} is outside the tunnel subnet.")

        peers.append({
            "id": int(peer["id"]),
            "name": peer["name"],
            "address": f"{address.ip}/32",
            "public_key": peer["public_key"],
            "private_key": peer.get("private_key", ""),
            "preshared_key": peer.get("preshared_key", ""),
            "created": int(peer.get("created", 0))
        })

    return {"server": result, "peers": peers}


def _validate_openvpn(data):

    from services.openvpn import validate_server, DEFAULT_SERVER
    from services.vpn_common import valid_name

    server = data.get("server")

    _require(isinstance(server, dict), "Missing server settings.")

    ok, result = validate_server({**DEFAULT_SERVER, **server})

    _require(ok, result)

    clients = []

    for client in data.get("clients") or []:

        name = client.get("name") if isinstance(client, dict) else None

        _require(valid_name(name) and name != "server", "Invalid client name.")

        clients.append({"name": name, "created": int(client.get("created", 0))})

    return {"server": result, "clients": clients}


def _validate_profiles(data):

    from services import vpn_profiles as vp
    from services.vpn_common import valid_name

    profiles = []

    for profile in data.get("profiles") or []:

        _require(isinstance(profile, dict), "Invalid VPN profile.")
        _require(valid_name(profile.get("name")), "Invalid VPN profile name.")
        _require(profile.get("type") in vp.TYPES, "Invalid VPN profile type.")

        username = profile.get("username", "")
        password = profile.get("password", "")

        _require(_single_line(username) and _single_line(password),
                 f"Invalid credentials in {profile['name']}.")

        cleaned = {
            "id": int(profile["id"]),
            "name": profile["name"],
            "type": profile["type"],
            "autostart": profile.get("autostart") is True,
            "created": int(profile.get("created", 0)),
            "username": username,
            "password": password
        }

        text = profile.get("config")

        _require(isinstance(text, str), f"Missing config in {profile['name']}.")

        # Sanitised again: an edited backup must not smuggle in
        # commands (PostUp, up, plugin, ...).
        if cleaned["type"] == "wireguard":

            ok, sections, _ = vp.sanitize_wireguard(text)
            _require(ok, f"{profile['name']}: {sections}")

            cleaned["config"] = vp.render_wireguard(sections)

        else:

            ok, config, _ = vp.sanitize_openvpn(
                text,
                vp.interface_name(cleaned),
                bool(username),
                vp.auth_path(cleaned)
            )
            _require(ok, f"{profile['name']}: {config}")

            cleaned["config"] = config

        profiles.append(cleaned)

    _require(sum(p["autostart"] for p in profiles) <= 1,
             "Only one VPN profile may connect at boot.")

    return {"profiles": profiles}


def _validate_aliases(data):

    from services.clients import normalize_mac

    aliases = {}

    for mac, name in data.items():

        mac = normalize_mac(mac)

        _require(mac and _single_line(name, 64), "Invalid device name.")

        aliases[mac] = name

    return aliases


def _validate_dashboard(data):

    _require(isinstance(data.get("ping_enabled", False), bool), "Invalid ping setting.")
    _require(data.get("ping_interval", 5) in (5, 10, 30, 60), "Invalid ping interval.")
    _require(_single_line(data.get("ping_destination", ""), 253), "Invalid ping destination.")

    return {
        k: data[k] for k in ("ping_enabled", "ping_interval", "ping_destination")
        if k in data
    }


def _validate_security(data):

    cleaned = {}

    for key in ("idle_timeout", "absolute_timeout"):

        if key in data:

            _require(isinstance(data[key], int) and data[key] > 0, "Invalid timeout.")

            cleaned[key] = data[key]

    return cleaned


def _validate_users(data):

    _require(isinstance(data, dict) and data, "No login users.")

    users = {}

    for username, entry in data.items():

        _require(USERNAME.fullmatch(username or ""), "Invalid username.")

        password = entry.get("password") if isinstance(entry, dict) else None

        _require(isinstance(password, str) and PASSWORD_HASH.fullmatch(password),
                 "Invalid password entry.")

        users[username] = {"password": password}

    return users


def _validate_pki(snapshot):

    _require(isinstance(snapshot, dict), "Invalid certificate backup.")

    files = snapshot.get("files")

    _require(isinstance(files, dict) and "ca.crt" in files, "Certificate backup has no CA.")

    for path in list(files) + list(snapshot.get("dirs") or []):

        # Written as root: never outside the PKI folder.
        _require(
            isinstance(path, str) and SAFE_PATH.fullmatch(path)
            and ".." not in path.split("/"),
            "Invalid path in the certificate backup."
        )

    _require(all(isinstance(c, str) for c in files.values()), "Invalid certificate file.")
    _require(isinstance(snapshot.get("tls_crypt_key", ""), str), "Invalid tls-crypt key.")

    return snapshot


def get_validators():

    from services.dhcp import validate_dhcp_settings
    from services.wifi import validate_wifi_settings
    from services.dns import validate_dns_settings
    from services.routing import validate_routing_settings

    return {
        "network": _validate_network,
        "firewall": _validate_firewall,
        "routing": _validate_with(validate_routing_settings),
        "blocked_devices": _validate_blocked,
        "dhcp": _validate_with(validate_dhcp_settings),
        "dns": _validate_with(validate_dns_settings),
        "wifi": _validate_with(validate_wifi_settings),
        "wireguard": _validate_wireguard,
        "openvpn": _validate_openvpn,
        "vpn_profiles": _validate_profiles,
        "device_aliases": _validate_aliases,
        "dashboard": _validate_dashboard,
        "security": _validate_security,
        "users": _validate_users
    }


# -------------------------------------------------------------------
# Inspect / restore
# -------------------------------------------------------------------

def parse_backup(raw):
    """
    Checks the file itself. Returns (True, backup) or (False, message).
    """

    if isinstance(raw, (bytes, bytearray)):

        if len(raw) > MAX_BACKUP_SIZE:
            return False, "The file is too large to be a backup."

        raw = raw.decode("utf-8", "replace")

    if isinstance(raw, str):

        if len(raw) > MAX_BACKUP_SIZE:
            return False, "The file is too large to be a backup."

        try:
            raw = json.loads(raw)
        except ValueError:
            return False, "This is not a Chaos Router OS backup (not JSON)."

    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        return False, "This is not a Chaos Router OS backup."

    if raw.get("version") != VERSION:
        return False, (
            f"This backup uses format version {raw.get('version')}; "
            f"this router reads version {VERSION}."
        )

    content = {"config": raw.get("config"), "system": raw.get("system")}

    if not isinstance(content["config"], dict) or not isinstance(content["system"], dict):
        return False, "The backup is incomplete."

    if raw.get("checksum") != checksum(content):
        return False, "The backup file was changed or damaged (checksum mismatch)."

    return True, raw


def inspect_backup(backup):
    """
    Validates every area. Returns a summary for the restore dialog and
    the cleaned settings per area.
    """

    validators = get_validators()

    areas = []
    cleaned = {}

    for name in area_names():

        if name not in backup["config"]:
            continue

        entry = {"name": name, "label": area_label(name)}

        validator = validators.get(name)

        try:

            if not validator:
                raise ValueError("Not supported by this version.")

            cleaned[name] = validator(backup["config"][name])

            entry["status"] = (
                "unchanged"
                if cleaned[name] == load_persistent(name, None)
                else "ok"
            )

        except (ValueError, TypeError, KeyError, AttributeError) as e:

            entry["status"] = "invalid"
            entry["message"] = str(e) or "Invalid settings."

        areas.append(entry)

    pki = backup["system"].get(PKI_SNAPSHOT)
    pki_status = None

    if pki is not None:

        try:
            cleaned["_pki"] = _validate_pki(pki)
            pki_status = "ok"
        except (ValueError, TypeError, AttributeError) as e:
            pki_status = f"invalid: {e}"

    summary = {
        "created": backup.get("created"),
        "hostname": backup.get("hostname"),
        "areas": areas,
        "certificates": pki_status
    }

    return summary, cleaned


def restore_pki(snapshot):
    """
    Replaces this router's OpenVPN CA with the one from the backup.
    """

    from services import openvpn
    from services.network import run_command, privileged

    def install(data):

        run_command(privileged(["rm", "-rf", openvpn.PKI_DIR]))

        save_system(PKI_SNAPSHOT, data, secret=True)

        return openvpn.restore_pki()

    # This router's current CA, to put back if the backup's fails.
    previous = load_system(PKI_SNAPSHOT, None)

    if install(snapshot):
        return True, "OK"

    if previous:
        install(previous)
    else:
        save_system(PKI_SNAPSHOT, {}, secret=True)

    return False, (
        "The OpenVPN certificates could not be restored; "
        "this router's certificates were kept."
    )


def restore_backup(raw, selected=None):
    """
    Restores the selected areas (all valid ones by default) through
    safe apply, in boot order. Returns a result dict with per-area
    outcomes; risky areas end up pending confirmation.
    """

    ok, backup = parse_backup(raw)

    if not ok:
        return transaction.result(False, backup)

    summary, cleaned = inspect_backup(backup)

    valid = [a["name"] for a in summary["areas"] if a["status"] != "invalid"]

    chosen = [n for n in valid if selected is None or n in selected]

    if not chosen:
        return transaction.result(False, "Nothing to restore.")

    results = []

    for name in chosen:

        if name == "openvpn" and "_pki" in cleaned:

            done, message = restore_pki(cleaned["_pki"])

            if not done:
                results.append({"name": name, "label": area_label(name),
                                "success": False, "message": message})
                continue

        if cleaned[name] == load_persistent(name, None):

            results.append({"name": name, "label": area_label(name),
                            "success": True, "message": "Unchanged."})
            continue

        outcome = transaction.change(name, cleaned[name])

        results.append({
            "name": name,
            "label": area_label(name),
            "success": outcome["success"],
            "message": outcome["message"]
        })

    restored = [r["label"] for r in results if r["success"]]
    failed = [r["label"] for r in results if not r["success"]]

    log_event(
        "backup",
        f"Backup from {backup.get('hostname')} restored: "
        f"{', '.join(restored) or 'nothing'}"
        + (f"; failed: {', '.join(failed)}" if failed else "."),
        "warning" if failed else "info"
    )

    message = (
        f"Restored {len(restored)} of {len(results)} areas."
        + (f" Failed: {', '.join(failed)}." if failed else "")
    )

    return transaction.result(
        bool(restored),
        message,
        pending=transaction.get_pending(),
        areas=results
    )
