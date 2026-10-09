import ipaddress
import os
import re
import tempfile
import time

from services.config import load_defaults, load_running

from services import transaction

from services.network import (
    run,
    run_command,
    privileged,
    unit_stays_active,
    is_wan_interface,
    is_lan_capable,
    get_lan_interface_names,
    effective_interface
)

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# dhcp.json in /etc/chaos-router-os (defaults) and /var/lib/chaos-router-os.
DHCP_SETTINGS = "dhcp"

# dnsmasq drop-in owned by Chardsoft Router OS.
# Debian / Raspberry Pi OS load /etc/dnsmasq.d by default.
DNSMASQ_CONF_FILE = "/etc/dnsmasq.d/chaos-router-dhcp.conf"

DNSMASQ_LEASE_FILES = (
    "/var/lib/misc/dnsmasq.leases",
    "/var/lib/dnsmasq/dnsmasq.leases"
)

LEASE_TIMES = (
    "1h",
    "12h",
    "24h",
    "7d"
)

LEASE_SECONDS = {
    "1h": 3600,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400
}

# dhcp.json: one scope per interface DHCP serves, with its own range,
# gateway and DNS; the domain and the reservations are shared:
#
#   {"interfaces": {"eth0": {...}, "wlan1": {...}},
#    "domain": "", "reservations": [...]}
#
# Older versions stored a single scope ({"enabled", "interface",
# "range_start", ...}); it is read as the scope of that interface.
DEFAULT_SETTINGS = {
    "interfaces": {},
    "domain": "",
    "reservations": []
}

DEFAULT_SCOPE = {
    "enabled": False,
    "range_start": "",
    "range_end": "",
    "lease_time": "12h",
    "gateway": "",
    "dns": []
}

SCOPE_FIELDS = tuple(DEFAULT_SCOPE)

MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")

HOSTNAME_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)

DOMAIN_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def has_dnsmasq():

    return run(["which", "dnsmasq"]) is not None


def is_dnsmasq_running():

    return run([
        "systemctl",
        "is-active",
        "dnsmasq"
    ]) == "active"


def get_interface_network(interface):
    """
    Returns the IPv4Interface (address + subnet) of an interface,
    or None when it has no IPv4 address.
    """

    output = run([
        "ip",
        "-4",
        "-o",
        "addr",
        "show",
        interface
    ])

    if not output:
        return None

    for line in output.splitlines():

        if "inet " not in line:
            continue

        try:

            return ipaddress.IPv4Interface(
                line
                .split("inet ", 1)[1]
                .split()[0]
            )

        except ValueError:
            pass

    return None


def get_lan_interfaces():

    interfaces = []

    # Every LAN-capable interface that exists, including extra Wi-Fi
    # adapters (wlan1) and USB Ethernet. Never the WAN.
    for name in get_lan_interface_names():

        network = get_interface_network(name)

        interfaces.append({

            "name": name,

            "ip": str(network.ip) if network else None,

            "subnet": (
                str(network.network.netmask)
                if network else None
            )

        })

    return interfaces


def _ipv4(value):

    try:
        return ipaddress.IPv4Address(value)
    except Exception:
        return None


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def normalize(data):
    """
    {"interfaces", "domain", "reservations"} from stored settings, in
    the current or the old single-scope format.
    """

    data = data if isinstance(data, dict) else {}

    scopes = data.get("interfaces")

    if isinstance(scopes, dict):
        scopes = {
            name: {**DEFAULT_SCOPE, **{k: v for k, v in scope.items() if k in SCOPE_FIELDS}}
            for name, scope in scopes.items()
            if isinstance(scope, dict) and is_lan_capable(name)
        }
    elif data.get("interface"):
        # Old format: one scope, flat.
        scopes = {
            str(data["interface"]): {
                **DEFAULT_SCOPE,
                **{k: data[k] for k in SCOPE_FIELDS if k in data}
            }
        }
    else:
        scopes = {}

    reservations = data.get("reservations")

    return {
        "interfaces": scopes,
        "domain": str(data.get("domain") or ""),
        "reservations": reservations if isinstance(reservations, list) else []
    }


def get_dhcp_settings():

    # Each layer on its own: the two formats cannot be merged key by key.
    running = load_running(DHCP_SETTINGS, None)

    if isinstance(running, dict):
        return normalize(running)

    return normalize(load_defaults(DHCP_SETTINGS, DEFAULT_SETTINGS))


def off_settings():
    """
    DHCP off everywhere (factory reset, uninstall).
    """

    return {"interfaces": {}, "domain": "", "reservations": []}


def is_enabled(settings=None):
    """
    Whether DHCP serves at least one interface.
    """

    settings = settings or get_dhcp_settings()

    return any(scope["enabled"] for scope in settings["interfaces"].values())


def suggest_range(network):
    """
    A range for a subnet: .100-.200 in a /24, the upper half of
    smaller ones, the router's address left out.
    """

    hosts = network.network.num_addresses - 2

    if hosts >= 254:
        start, end = network.network.network_address + 100, network.network.network_address + 200
    else:
        start = network.network.network_address + max(2, hosts // 2)
        end = network.network.broadcast_address - 1

    if start <= network.ip <= end:
        start = network.ip + 1

    return str(start), str(end)


def get_scope(interface, settings=None):
    """
    One interface's DHCP, flat as the DHCP page edits it. An interface
    without settings gets a range from its subnet.
    """

    settings = settings or get_dhcp_settings()

    scope = settings["interfaces"].get(interface)

    if scope is None:

        scope = dict(DEFAULT_SCOPE)

        network = get_interface_network(effective_interface(interface))

        if network and network.network.num_addresses > 4:
            scope["range_start"], scope["range_end"] = suggest_range(network)

    return {**scope, "interface": interface}


def served_scopes(settings=None):
    """
    The scopes dnsmasq serves now: on, not the WAN, one per actual
    interface (bridge ports are served through their bridge).
    """

    settings = settings or get_dhcp_settings()

    scopes = {}

    for name, scope in sorted(settings["interfaces"].items()):

        if not scope["enabled"] or is_wan_interface(name):
            continue

        served = effective_interface(name)

        # Two ports of one bridge: the bridge is served once.
        if served not in scopes:
            scopes[served] = {**scope, "interface": name, "served": served}

    return list(scopes.values())


def validate_reservation(reservation, network=None):

    mac = str(reservation.get("mac", "")).strip().upper()
    ip = str(reservation.get("ip", "")).strip()
    hostname = str(reservation.get("hostname", "")).strip()

    if not MAC_RE.fullmatch(mac):
        return False, "Invalid MAC address."

    address = _ipv4(ip)

    if not address:
        return False, "Invalid reservation IP."

    if network:

        if address not in network.network:
            return False, (
                f"Reservation {ip} is outside "
                f"{network.network}."
            )

        if address == network.ip:
            return False, (
                f"{ip} is the router's own address."
            )

    if hostname and not HOSTNAME_RE.fullmatch(hostname):
        return False, "Invalid reservation hostname."

    return True, {
        "mac": mac,
        "ip": ip,
        "hostname": hostname
    }


def validate_scope(data, settings=None, strict=True):
    """
    Validates and normalises one interface's DHCP (flat, with
    "interface"). Returns (True, scope) or (False, message).

    strict=False (the other scopes, a backup): a scope whose interface
    has no address now (radio off, adapter unplugged) or is the WAN is
    only checked for valid values, not against the live subnet.
    """

    settings = settings or get_dhcp_settings()

    interface = str((data or {}).get("interface") or "")

    # eth0 is accepted while it is the WAN: DHCP is paused at apply
    # time, so the settings survive switching eth0 back and forth.
    if not is_lan_capable(interface):
        return False, "Unsupported DHCP interface."

    scope = get_scope(interface, settings)
    scope.update({k: v for k, v in (data or {}).items() if k in SCOPE_FIELDS})

    enabled = scope.get("enabled") is True

    lease_time = scope.get("lease_time")

    if lease_time not in LEASE_TIMES:
        return False, "Invalid lease time."

    dns = scope.get("dns") or []

    if isinstance(dns, str):
        dns = [dns]

    dns = [str(d).strip() for d in dns if str(d).strip()]

    if len(dns) > 2:
        return False, "At most two DNS servers are supported."

    for server in dns:

        if not _ipv4(server):
            return False, f"Invalid DNS server: {server}"

    gateway = str(scope.get("gateway") or "").strip()

    if gateway and not _ipv4(gateway):
        return False, "Invalid gateway."

    range_start = str(scope.get("range_start") or "").strip()
    range_end = str(scope.get("range_end") or "").strip()

    # Only check the address range against the live interface when
    # the server is enabled. Disabled settings may be incomplete.
    network = get_interface_network(effective_interface(interface))

    live = strict or (network is not None and not is_wan_interface(interface))

    if enabled and live:

        if not network:
            return False, (
                f"{interface} has no IPv4 address. "
                f"Give it one first (Network page, or the WiFi page for an access point)."
            )

        start = _ipv4(range_start)
        end = _ipv4(range_end)

        if not start:
            return False, "Invalid range start."

        if not end:
            return False, "Invalid range end."

        if start > end:
            return False, "Range start must be before range end."

        for address in (start, end):

            if address not in network.network:
                return False, (
                    f"{address} is outside {network.network}."
                )

        if start <= network.ip <= end:
            return False, (
                f"Range includes the router's own "
                f"address ({network.ip})."
            )

    else:

        for value, name in (
            (range_start, "range start"),
            (range_end, "range end")
        ):

            if value and not _ipv4(value):
                return False, f"Invalid {name}."

    return True, {
        "interface": interface,
        "enabled": enabled,
        "range_start": range_start,
        "range_end": range_end,
        "lease_time": lease_time,
        "gateway": gateway,
        "dns": dns
    }


def validate_dhcp_settings(data):
    """
    Validates the whole DHCP settings (e.g. from a backup, or a scope
    merged into the current ones), in the current or the old format.

    Returns (True, settings) or (False, message).
    """

    data = normalize(data)

    scopes = {}

    for name, scope in sorted(data["interfaces"].items()):

        ok, result = validate_scope({**scope, "interface": name}, data, strict=False)

        if not ok:
            return False, f"{name}: {result}"

        scopes[name] = {k: result[k] for k in SCOPE_FIELDS}

    domain = str(data.get("domain") or "").strip()

    if domain and not DOMAIN_RE.fullmatch(domain):
        return False, "Invalid domain."

    # Reservations must be in a subnet DHCP serves (when it serves any).
    networks = [
        get_interface_network(effective_interface(name))
        for name, scope in scopes.items() if scope["enabled"]
    ]
    networks = [n for n in networks if n]

    reservations = []
    seen_macs = set()
    seen_ips = set()

    for reservation in data.get("reservations") or []:

        ok, result = validate_reservation(reservation)

        if not ok:
            return False, result

        address = ipaddress.IPv4Address(result["ip"])

        if networks:

            inside = [n for n in networks if address in n.network]

            if not inside:
                return False, (
                    f"Reservation {result['ip']} is outside every network DHCP serves "
                    f"({', '.join(str(n.network) for n in networks)})."
                )

            if any(address == n.ip for n in inside):
                return False, f"{result['ip']} is the router's own address."

        if result["mac"] in seen_macs:
            return False, f"Duplicate reservation for {result['mac']}."

        if result["ip"] in seen_ips:
            return False, f"Duplicate reservation for {result['ip']}."

        seen_macs.add(result["mac"])
        seen_ips.add(result["ip"])

        reservations.append(result)

    return True, {
        "interfaces": scopes,
        "domain": domain,
        "reservations": reservations
    }


# -------------------------------------------------------------------
# dnsmasq config
# -------------------------------------------------------------------

def render_dnsmasq_config(settings):

    lines = [
        "# Generated by Chardsoft Router OS. Do not edit by hand.",
        "# Changes are overwritten from the DHCP page.",
        "",
        "dhcp-authoritative"
    ]

    for scope in served_scopes(settings):

        # A bridge port (eth0 in br0) is served on its bridge.
        interface = scope["served"]

        network = get_interface_network(interface)

        if not network:
            lines += ["", f"# {interface}: no IPv4 address yet, not served."]
            continue

        # Each interface's options go to its own clients only.
        tag = f"chaos-{interface}"

        gateway = scope["gateway"] or str(network.ip)

        lines += [
            "",
            f"# {scope['interface']}" + (f" (through {interface})" if interface != scope["interface"] else ""),
            f"interface={interface}",
            (
                f"dhcp-range=set:{tag},"
                f"{scope['range_start']},"
                f"{scope['range_end']},"
                f"{network.network.netmask},"
                f"{scope['lease_time']}"
            ),
            f"dhcp-option=tag:{tag},option:router,{gateway}"
        ]

        # Without explicit servers dnsmasq advertises itself as DNS.
        if scope["dns"]:
            lines.append(
                f"dhcp-option=tag:{tag},option:dns-server,"
                + ",".join(scope["dns"])
            )

    if settings["domain"]:
        lines += ["", f"domain={settings['domain']}"]

    if settings["reservations"]:
        lines.append("")
        lines.append("# Static leases")

    for reservation in settings["reservations"]:

        parts = [reservation["mac"]]

        if reservation["hostname"]:
            parts.append(reservation["hostname"])

        parts.append(reservation["ip"])

        lines.append("dhcp-host=" + ",".join(parts))

    return "\n".join(lines) + "\n"


def install_dnsmasq_config(content, path=DNSMASQ_CONF_FILE):
    """
    Tests the config with dnsmasq, then installs it.
    Shared with the DNS settings, which have their own file.
    """

    fd, tmp = tempfile.mkstemp(
        prefix="chaos-dnsmasq-",
        suffix=".conf"
    )

    try:

        with os.fdopen(fd, "w") as f:
            f.write(content)

        ok, result = run_command([
            "dnsmasq",
            "--test",
            f"--conf-file={tmp}"
        ])

        if not ok:
            return False, f"dnsmasq rejected the config: {result}"

        return run_command(privileged([
            "install",
            "-m",
            "644",
            tmp,
            path
        ]))

    finally:

        os.unlink(tmp)


def remove_dnsmasq_config(path=DNSMASQ_CONF_FILE):

    if not os.path.exists(path):
        return True, "OK"

    return run_command(privileged([
        "rm",
        "-f",
        path
    ]))


def restart_dnsmasq():
    """
    Restarts dnsmasq; on failure the message is dnsmasq's own reason
    from the journal (e.g. "address already in use").
    """

    ok, result = run_command(privileged([
        "systemctl",
        "restart",
        "dnsmasq"
    ]))

    return (True, result) if ok else (False, get_dnsmasq_error() or result)


def get_dnsmasq_error():

    ok, output = run_command(privileged([
        "journalctl",
        "-u",
        "dnsmasq",
        "-n",
        "6",
        "--no-pager",
        "-o",
        "cat"
    ]))

    return output if ok and output else None


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def prepare_change(data):
    """
    The whole DHCP settings with a change merged in. data: one
    interface's scope (with "interface"), and/or "domain" and
    "reservations". Returns (True, settings) or (False, message).
    """

    data = data or {}

    settings = get_dhcp_settings()

    if "interface" in data:

        ok, scope = validate_scope(data, settings)

        if not ok:
            return False, scope

        settings["interfaces"][scope["interface"]] = {k: scope[k] for k in SCOPE_FIELDS}

    for key in ("domain", "reservations"):
        if key in data:
            settings[key] = data[key]

    return validate_dhcp_settings(settings)


def save_dhcp_settings(data, confirm=None):
    """
    Validates the change, then applies it through safe apply.
    Returns a transaction result dict with the new settings.
    """

    ok, result = prepare_change(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(DHCP_SETTINGS, result, confirm=confirm)
    outcome["settings"] = get_dhcp_settings()

    return outcome


def get_scopes(settings=None):
    """
    {interface: scope} for every LAN interface there is, and every
    interface with DHCP settings.
    """

    settings = settings or get_dhcp_settings()

    names = sorted(set(get_lan_interface_names()) | set(settings["interfaces"]))

    return {name: get_scope(name, settings) for name in names}


def follow_wifi(interface, address, prefix, confirm=None):
    """
    After an access point started on a radio with its own subnet: DHCP
    serves that radio in that subnet. Nothing changes when it already
    does. Returns a transaction result, or None for no change.
    """

    try:
        network = ipaddress.IPv4Interface(f"{address}/{prefix}")
    except ValueError:
        return None

    settings = get_dhcp_settings()

    scope = settings["interfaces"].get(interface)

    if scope and scope["enabled"]:

        start, end = _ipv4(scope["range_start"]), _ipv4(scope["range_end"])

        if start and end and start in network.network and end in network.network \
                and not start <= network.ip <= end:
            return None

    range_start, range_end = suggest_range(network)

    return save_dhcp_settings({
        **DEFAULT_SCOPE,
        **(scope or {}),
        "interface": interface,
        "enabled": True,
        "range_start": range_start,
        "range_end": range_end,
        # The router itself, in the new subnet.
        "gateway": ""
    }, confirm=confirm)


def is_paused(interface):
    """
    DHCP never serves the internet uplink: while its interface is the
    WAN (eth0 in WAN mode) the scope is paused, not removed.
    """

    scope = get_dhcp_settings()["interfaces"].get(interface)

    return bool(scope) and scope["enabled"] and is_wan_interface(interface)


def apply_dhcp_settings():
    """
    Applies the running DHCP settings to dnsmasq.
    """

    settings = get_dhcp_settings()

    served = served_scopes(settings)

    if not has_dnsmasq():

        if not served:
            return True, "DHCP server disabled."

        return False, "dnsmasq is not available."

    if served:
        ok, result = install_dnsmasq_config(
            render_dnsmasq_config(settings)
        )
    else:
        ok, result = remove_dnsmasq_config()

    if not ok:
        return False, f"DHCP settings could not be applied: {result}"

    ok, result = restart_dnsmasq()

    if not ok:
        return False, f"dnsmasq failed to restart: {result}"

    paused = [name for name in settings["interfaces"] if is_paused(name)]

    if served:
        message = "DHCP server applied: " + ", ".join(s["interface"] for s in served) + "."
    else:
        message = "DHCP server disabled."

    if paused:
        message += f" Paused on {', '.join(paused)} (WAN)."

    return True, message


def verify_dhcp_settings():

    if not served_scopes():
        return True, "OK"

    ok, message = unit_stays_active("dnsmasq")

    if not ok:
        return False, f"{message} {get_dnsmasq_error() or ''}".strip()

    return True, "OK"


# -------------------------------------------------------------------
# Reservations
# -------------------------------------------------------------------

def add_reservation(reservation):

    settings = get_dhcp_settings()

    mac = str(reservation.get("mac", "")).strip().upper()

    # Re-reserving a MAC replaces its previous entry.
    reservations = [
        r for r in settings["reservations"]
        if r["mac"] != mac
    ]

    reservations.append(reservation)

    return save_dhcp_settings(
        {"reservations": reservations},
        confirm=False
    )


def remove_reservation(mac):

    settings = get_dhcp_settings()

    mac = mac.strip().upper()

    reservations = [
        r for r in settings["reservations"]
        if r["mac"] != mac
    ]

    if len(reservations) == len(settings["reservations"]):
        return transaction.result(False, "Reservation not found.")

    return save_dhcp_settings(
        {"reservations": reservations},
        confirm=False
    )


# -------------------------------------------------------------------
# Leases
# -------------------------------------------------------------------

def get_dhcp_leases():
    """
    Parses the dnsmasq lease file:
    <expiry> <mac> <ip> <hostname> <client-id>
    """

    leases = []

    path = next(
        (p for p in DNSMASQ_LEASE_FILES if os.path.exists(p)),
        None
    )

    if not path:
        return leases

    reserved = {
        r["mac"]
        for r in get_dhcp_settings()["reservations"]
    }

    try:

        with open(path, "r") as f:
            lines = f.read().splitlines()

    except Exception:
        return leases

    now = int(time.time())

    # dnsmasq only stores the expiry: the lease time of the subnet the
    # address is in tells when it was handed out.
    lease_times = []

    for scope in served_scopes():
        network = get_interface_network(scope["served"])
        if network:
            lease_times.append((network.network, LEASE_SECONDS.get(scope["lease_time"])))

    for line in lines:

        parts = line.split()

        if len(parts) < 4:
            continue

        try:
            expiry = int(parts[0])
        except ValueError:
            continue

        mac = parts[1].upper()

        address = _ipv4(parts[2])

        lease_seconds = next(
            (seconds for network, seconds in lease_times if address and address in network),
            None
        )

        leases.append({

            "mac": mac,

            "ip": parts[2],

            "hostname": "" if parts[3] == "*" else parts[3],

            # 0 means the lease never expires.
            "expires_in": (
                None if expiry == 0
                else max(expiry - now, 0)
            ),

            "expires_at": expiry or None,

            # dnsmasq only stores the expiry; the lease was handed out
            # (or last renewed) one lease time before it.
            "renewed_at": (
                expiry - lease_seconds
                if expiry and lease_seconds else None
            ),

            "reserved": mac in reserved

        })

    leases.sort(
        key=lambda l: ipaddress.IPv4Address(l["ip"])
        if _ipv4(l["ip"]) else ipaddress.IPv4Address(0)
    )

    return leases


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def get_dhcp_status():

    installed = has_dnsmasq()

    settings = get_dhcp_settings()

    paused = [name for name in settings["interfaces"] if is_paused(name)]

    return {
        "installed": installed,
        "running": installed and is_dnsmasq_running(),
        "config_file": DNSMASQ_CONF_FILE,
        "served": [scope["interface"] for scope in served_scopes(settings)],
        "paused": (
            f"Paused on {', '.join(paused)}: in WAN mode. Switch it back to LAN "
            f"on the Network page, or serve DHCP on another interface."
            if paused else None
        )
    }
