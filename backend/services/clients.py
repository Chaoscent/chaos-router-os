"""
Client actions: blocking, ping and Wake-on-LAN.

Blocked devices (blocked_devices.json) are dropped by MAC address in
a dedicated iptables chain, hooked first into INPUT and FORWARD. That
covers the router itself and the internet, works for any IP the device
picks, and leaves ufw's own chains alone.
"""

import ipaddress
import re
import socket
import time

from services.config import load_running

from services import transaction

from services.network import (
    run,
    run_command,
    privileged,
    get_clients
)

from services.vpn_common import which

from services.dhcp import (
    get_dhcp_settings,
    get_dhcp_leases
)

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

BLOCKED = "blocked_devices"

CHAIN = "CHAOS-BLOCK"

MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def normalize_mac(mac):

    mac = str(mac or "").strip().upper().replace("-", ":")

    return mac if MAC_RE.fullmatch(mac) else None


# -------------------------------------------------------------------
# Blocked devices
# -------------------------------------------------------------------

def get_blocked():

    return load_running(BLOCKED, {"devices": []}).get("devices", [])


def save_blocked(devices):

    return transaction.change(BLOCKED, {"devices": devices})


def block_device(mac, name=""):

    mac = normalize_mac(mac)

    if not mac:
        return transaction.result(False, "Invalid MAC address.")

    devices = get_blocked()

    if any(d["mac"] == mac for d in devices):
        return transaction.result(False, "This device is already blocked.")

    devices.append({
        "mac": mac,
        "name": str(name or "").strip()[:64],
        "blocked_at": int(time.time())
    })

    return save_blocked(devices)


def unblock_device(mac):

    mac = normalize_mac(mac)

    devices = get_blocked()
    remaining = [d for d in devices if d["mac"] != mac]

    if len(remaining) == len(devices):
        return transaction.result(False, "This device is not blocked.")

    return save_blocked(remaining)


def iptables_tools():

    return [t for t in (which("iptables"), which("ip6tables")) if t]


def apply_blocked():
    """
    Rebuilds the block chain from the running list.
    """

    devices = get_blocked()
    tools = iptables_tools()

    if not tools:

        if not devices:
            return True, "No devices blocked."

        return False, "iptables is not installed."

    for tool in tools:

        def ipt(*args):
            return run_command(privileged([tool, *args]))

        # Creating fails harmlessly when the chain exists.
        ipt("-N", CHAIN)

        ok, result = ipt("-F", CHAIN)

        if not ok:
            return False, f"Could not reset the block list: {result}"

        for device in devices:

            ok, result = ipt(
                "-A", CHAIN,
                "-m", "mac", "--mac-source", device["mac"],
                "-j", "DROP"
            )

            if not ok:
                return False, f"Could not block {device['mac']}: {result}"

        # First in line, before ufw lets established traffic through.
        for parent in ("INPUT", "FORWARD"):

            exists, _ = ipt("-C", parent, "-j", CHAIN)

            if not exists:

                ok, result = ipt("-I", parent, "1", "-j", CHAIN)

                if not ok:
                    return False, f"Could not activate the block list: {result}"

    count = len(devices)

    return True, (
        f"{count} device{'s' if count != 1 else ''} blocked."
        if count else "No devices blocked."
    )


def verify_blocked():

    devices = get_blocked()
    tools = iptables_tools()

    if not tools:
        return True, "OK"

    ok, output = run_command(privileged([tools[0], "-S", CHAIN]))

    if not ok:
        return False, "The block list is not active."

    active = output.upper()

    for device in devices:

        if device["mac"] not in active:
            return False, f"{device['mac']} is not blocked."

    return True, "OK"


# -------------------------------------------------------------------
# Client list
# -------------------------------------------------------------------

def get_client_list(viewer_ip=None):
    """
    Connected devices with DHCP and block details. Blocked devices
    stay listed even when they are gone, so they can be unblocked.
    """

    dhcp = get_dhcp_settings()

    reservations = {r["mac"]: r for r in dhcp["reservations"]}
    leases = {l["mac"]: l for l in get_dhcp_leases()}
    blocked = {d["mac"]: d for d in get_blocked()}

    clients = []
    seen = set()

    for client in get_clients():

        mac = normalize_mac(client["mac"])

        if not mac or mac in seen:
            continue

        seen.add(mac)

        clients.append(client)

    for mac, device in blocked.items():

        if mac in seen:
            continue

        clients.append({
            "hostname": device["name"] or "Unknown",
            "ip": "",
            "interface": "",
            "mac": mac,
            "state": "Blocked",
            "vendor": "Unknown",
            "traffic": "--"
        })

    for client in clients:

        mac = normalize_mac(client["mac"])
        lease = leases.get(mac)
        reservation = reservations.get(mac)

        client["mac"] = mac
        client["blocked"] = mac in blocked
        client["reservation"] = reservation
        client["lease_expires_in"] = lease["expires_in"] if lease else None
        client["dhcp"] = bool(lease or reservation)
        client["is_you"] = bool(viewer_ip) and client["ip"] == viewer_ip

        if client["blocked"]:
            client["state"] = "Blocked"

    return {
        "clients": clients,
        "dhcp_enabled": dhcp["enabled"]
    }


def known_client(ip):

    return any(c["ip"] == ip for c in get_clients())


# -------------------------------------------------------------------
# Ping
# -------------------------------------------------------------------

def ping_device(ip):

    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        return False, "Invalid IP address."

    # Only devices on the network, never arbitrary targets.
    if not known_client(ip):
        return False, "That device is not on the network."

    output = run(["ping", "-c", "3", "-W", "1", ip])

    if not output:
        return False, "No reply."

    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    rtt = re.search(r"= [\d.]+/([\d.]+)/", output)

    if rtt:
        return True, (
            f"Reachable: {float(rtt.group(1)):.1f} ms average, "
            f"{loss.group(1) if loss else '0'}% loss."
        )

    return False, "No reply."


# -------------------------------------------------------------------
# Wake-on-LAN
# -------------------------------------------------------------------

def broadcast_address(interface):

    output = run(["ip", "-4", "-o", "addr", "show", interface])

    for line in (output or "").splitlines():

        if "inet " not in line:
            continue

        try:
            return str(ipaddress.IPv4Interface(
                line.split("inet ", 1)[1].split()[0]
            ).network.broadcast_address)
        except ValueError:
            pass

    return None


def wake_device(mac, interface=""):
    """
    Sends a Wake-on-LAN magic packet to the device's network.
    """

    mac = normalize_mac(mac)

    if not mac:
        return False, "Invalid MAC address."

    # Directed broadcast, so the packet leaves on the LAN and not on
    # the default route (the modem).
    target = broadcast_address(interface) if interface else None

    if not target:
        return False, "The device's network is unknown; it must have been online recently."

    packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16

    try:

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (target, 9))

    except OSError as e:
        return False, f"Could not send the wake-up packet: {e}"

    return True, f"Wake-up packet sent to {mac}."
