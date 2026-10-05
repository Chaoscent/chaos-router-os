import ipaddress
import os
import re
import tempfile
import time

from services.config import load_settings

from services import transaction

from services.network import (
    run,
    run_command,
    privileged,
    unit_stays_active,
    is_wan_interface
)

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# dhcp.json in /etc/chaos-router-os (defaults) and /var/lib/chaos-router-os.
DHCP_SETTINGS = "dhcp"

# dnsmasq drop-in owned by Chaos Router OS.
# Debian / Raspberry Pi OS load /etc/dnsmasq.d by default.
DNSMASQ_CONF_FILE = "/etc/dnsmasq.d/chaos-router-dhcp.conf"

DNSMASQ_LEASE_FILES = (
    "/var/lib/misc/dnsmasq.leases",
    "/var/lib/dnsmasq/dnsmasq.leases"
)

# Interfaces that may serve DHCP. wwan0 is the uplink and never does.
LAN_INTERFACES = (
    "eth0",
    "wlan0",
    "br0"
)

LEASE_TIMES = (
    "1h",
    "12h",
    "24h",
    "7d"
)

DEFAULT_SETTINGS = {
    "enabled": False,
    "interface": "eth0",
    "range_start": "",
    "range_end": "",
    "lease_time": "12h",
    "gateway": "",
    "dns": [],
    "domain": "",
    "reservations": []
}

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

    for name in LAN_INTERFACES:

        if run(["ip", "link", "show", name]) is None:
            continue

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

def get_dhcp_settings():

    return load_settings(DHCP_SETTINGS, DEFAULT_SETTINGS)


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


def validate_dhcp_settings(data):
    """
    Validates and normalises DHCP settings.

    Returns (True, settings) or (False, message).
    """

    settings = get_dhcp_settings()
    settings.update(data or {})

    enabled = settings.get("enabled") is True

    interface = settings.get("interface")

    if interface not in LAN_INTERFACES:
        return False, "Unsupported DHCP interface."

    lease_time = settings.get("lease_time")

    if lease_time not in LEASE_TIMES:
        return False, "Invalid lease time."

    domain = str(settings.get("domain") or "").strip()

    if domain and not DOMAIN_RE.fullmatch(domain):
        return False, "Invalid domain."

    dns = settings.get("dns") or []

    if isinstance(dns, str):
        dns = [dns]

    dns = [str(d).strip() for d in dns if str(d).strip()]

    if len(dns) > 2:
        return False, "At most two DNS servers are supported."

    for server in dns:

        if not _ipv4(server):
            return False, f"Invalid DNS server: {server}"

    gateway = str(settings.get("gateway") or "").strip()

    if gateway and not _ipv4(gateway):
        return False, "Invalid gateway."

    range_start = str(settings.get("range_start") or "").strip()
    range_end = str(settings.get("range_end") or "").strip()

    # Only check the address range against the live interface when
    # the server is enabled. Disabled settings may be incomplete.
    network = get_interface_network(interface)

    if enabled:

        if not network:
            return False, (
                f"{interface} has no IPv4 address. "
                f"Assign a static IP first."
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

    reservations = []
    seen_macs = set()
    seen_ips = set()

    for reservation in settings.get("reservations") or []:

        ok, result = validate_reservation(
            reservation,
            network if enabled else None
        )

        if not ok:
            return False, result

        if result["mac"] in seen_macs:
            return False, f"Duplicate reservation for {result['mac']}."

        if result["ip"] in seen_ips:
            return False, f"Duplicate reservation for {result['ip']}."

        seen_macs.add(result["mac"])
        seen_ips.add(result["ip"])

        reservations.append(result)

    return True, {
        "enabled": enabled,
        "interface": interface,
        "range_start": range_start,
        "range_end": range_end,
        "lease_time": lease_time,
        "gateway": gateway,
        "dns": dns,
        "domain": domain,
        "reservations": reservations
    }


# -------------------------------------------------------------------
# dnsmasq config
# -------------------------------------------------------------------

def render_dnsmasq_config(settings):

    interface = settings["interface"]

    network = get_interface_network(interface)

    netmask = (
        str(network.network.netmask)
        if network else "255.255.255.0"
    )

    gateway = settings["gateway"] or (
        str(network.ip) if network else ""
    )

    lines = [
        "# Generated by Chaos Router OS. Do not edit by hand.",
        "# Changes are overwritten from the DHCP page.",
        "",
        f"interface={interface}",
        "dhcp-authoritative",
        (
            f"dhcp-range={settings['range_start']},"
            f"{settings['range_end']},"
            f"{netmask},"
            f"{settings['lease_time']}"
        )
    ]

    if gateway:
        lines.append(f"dhcp-option=option:router,{gateway}")

    # Without explicit servers dnsmasq advertises itself as DNS.
    if settings["dns"]:
        lines.append(
            "dhcp-option=option:dns-server,"
            + ",".join(settings["dns"])
        )

    if settings["domain"]:
        lines.append(f"domain={settings['domain']}")

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

    return run_command(privileged([
        "systemctl",
        "restart",
        "dnsmasq"
    ]))


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def save_dhcp_settings(data, confirm=None):
    """
    Validates the settings, then applies them through safe apply.
    Returns a transaction result dict with the new settings.
    """

    ok, result = validate_dhcp_settings(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(DHCP_SETTINGS, result, confirm=confirm)
    outcome["settings"] = get_dhcp_settings()

    return outcome


def is_paused(settings=None):
    """
    DHCP never serves the internet uplink: while its interface is the
    WAN (eth0 in WAN mode) the server is paused, not removed.
    """

    settings = settings or get_dhcp_settings()

    return settings["enabled"] and is_wan_interface(settings["interface"])


def apply_dhcp_settings():
    """
    Applies the running DHCP settings to dnsmasq.
    """

    settings = dict(get_dhcp_settings())

    if is_paused(settings):
        settings["enabled"] = False

    if not has_dnsmasq():

        if not settings["enabled"]:
            return True, "DHCP server disabled."

        return False, "dnsmasq is not available."

    if settings["enabled"]:
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

    if settings["enabled"]:
        return True, "DHCP server applied."

    if is_paused():
        return True, f"DHCP server paused: {settings['interface']} is the WAN."

    return True, "DHCP server disabled."


def verify_dhcp_settings():

    if not get_dhcp_settings()["enabled"] or is_paused():
        return True, "OK"

    return unit_stays_active("dnsmasq")


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

    for line in lines:

        parts = line.split()

        if len(parts) < 4:
            continue

        try:
            expiry = int(parts[0])
        except ValueError:
            continue

        mac = parts[1].upper()

        leases.append({

            "mac": mac,

            "ip": parts[2],

            "hostname": "" if parts[3] == "*" else parts[3],

            # 0 means the lease never expires.
            "expires_in": (
                None if expiry == 0
                else max(expiry - now, 0)
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

    return {
        "installed": installed,
        "running": installed and is_dnsmasq_running(),
        "config_file": DNSMASQ_CONF_FILE,
        "paused": (
            f"Paused: {settings['interface']} is in WAN mode. Switch it back "
            f"to LAN on the Network page, or serve DHCP on another interface."
            if is_paused(settings) else None
        )
    }
