"""
WireGuard server: lets remote devices (peers) dial into the router.
"""

import ipaddress
import re
import subprocess
import time

from services.config import (
    load_defaults,
    load_running
)

from services import transaction

from services.network import run_command, privileged

from services.vpn_common import (
    which,
    valid_name,
    write_root_file,
    unit_active,
    start_unit,
    stop_unit,
    get_wan_interface,
    get_lan_networks,
    firewall_rules_for,
    sync_firewall
)

from services.network import unit_stays_active

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# wireguard.json: server defaults in /etc/chaos-router-os,
# settings, keys and peers in /var/lib/chaos-router-os.
WIREGUARD_SETTINGS = "wireguard"

SERVER_INTERFACE = "wg0"
SERVER_CONF = f"/etc/wireguard/{SERVER_INTERFACE}.conf"
SERVER_UNIT = f"wg-quick@{SERVER_INTERFACE}"

DEFAULT_SERVER = {
    "enabled": False,
    "listen_port": 51820,
    "address": "10.8.0.1/24",
    "endpoint": "",
    "dns": "1.1.1.1",
    # full: all peer traffic through the router; lan: only the LAN.
    "routing": "full",
    "private_key": "",
    "public_key": ""
}

KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw480]=$")

ENDPOINT_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


# -------------------------------------------------------------------
# Keys
# -------------------------------------------------------------------

def has_wireguard():

    return which("wg") is not None and which("wg-quick") is not None


def _wg(args, stdin=None):

    try:

        result = subprocess.run(
            [which("wg") or "wg"] + args,
            input=stdin,
            text=True,
            capture_output=True,
            check=True
        )

        return result.stdout.strip()

    except Exception:
        return None


def generate_keypair():

    private = _wg(["genkey"])
    public = _wg(["pubkey"], stdin=private) if private else None

    if not private or not public:
        return None, None

    return private, public


def generate_psk():

    return _wg(["genpsk"])


def valid_key(key):

    return bool(KEY_RE.fullmatch(str(key or "")))


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def load_wireguard():

    data = load_running(WIREGUARD_SETTINGS, {})

    server = dict(DEFAULT_SERVER)
    server.update(load_defaults(WIREGUARD_SETTINGS).get("server", {}))
    server.update(data.get("server", {}))

    return {
        "server": server,
        "peers": data.get("peers", [])
    }


def save_wireguard(data, confirm=None):
    """
    Applies the data through safe apply; returns a result dict.
    """

    return transaction.change(WIREGUARD_SETTINGS, data, confirm=confirm)


def public_view(data):
    """
    Settings for the UI, without private keys.
    """

    server = {
        k: v for k, v in data["server"].items()
        if k != "private_key"
    }

    peers = [
        {
            "id": p["id"],
            "name": p["name"],
            "address": p["address"],
            "public_key": p["public_key"],
            "has_config": bool(p.get("private_key")),
            "created": p.get("created")
        }
        for p in data["peers"]
    ]

    return {"server": server, "peers": peers}


def validate_server(server):

    try:
        port = int(server.get("listen_port"))
    except (TypeError, ValueError):
        return False, "Invalid listen port."

    if not 1 <= port <= 65535:
        return False, "Invalid listen port."

    try:
        address = ipaddress.IPv4Interface(str(server.get("address")))
    except ValueError:
        return False, "Invalid tunnel address. Use CIDR, e.g. 10.8.0.1/24."

    if not 16 <= address.network.prefixlen <= 30:
        return False, "Tunnel subnet must be between /16 and /30."

    if address.ip in (
        address.network.network_address,
        address.network.broadcast_address
    ):
        return False, "Tunnel address must be a host address."

    for lan in get_lan_networks():

        if address.network.overlaps(ipaddress.IPv4Network(lan)):
            return False, f"Tunnel subnet overlaps the LAN ({lan})."

    endpoint = str(server.get("endpoint") or "").strip()

    if endpoint and not ENDPOINT_RE.fullmatch(endpoint):
        return False, "Invalid public address. Use a hostname or IP."

    dns = [d.strip() for d in str(server.get("dns") or "").split(",") if d.strip()]

    for entry in dns:
        try:
            ipaddress.ip_address(entry)
        except ValueError:
            return False, f"Invalid DNS server: {entry}"

    if server.get("routing") not in ("full", "lan"):
        return False, "Invalid routing mode."

    return True, {
        "enabled": server.get("enabled") is True,
        "listen_port": port,
        "address": str(address),
        "endpoint": endpoint,
        "dns": ", ".join(dns),
        "routing": server["routing"]
    }


# -------------------------------------------------------------------
# Config files
# -------------------------------------------------------------------

def render_server_config(data):

    server = data["server"]

    network = ipaddress.IPv4Interface(server["address"]).network
    wan = get_wan_interface()

    nat = (
        f"iptables -t nat %s POSTROUTING "
        f"-s {network} -o {wan} -j MASQUERADE"
    )

    lines = [
        "# Generated by Chardsoft Router OS. Do not edit by hand.",
        "# Changes are overwritten from the VPN page.",
        "",
        "[Interface]",
        f"Address = {server['address']}",
        f"ListenPort = {server['listen_port']}",
        f"PrivateKey = {server['private_key']}",
        # Peers reach the internet through the router's WAN.
        f"PostUp = {nat % '-A'}",
        f"PostDown = {nat % '-D'}"
    ]

    for peer in data["peers"]:

        lines += [
            "",
            f"# {peer['name']}",
            "[Peer]",
            f"PublicKey = {peer['public_key']}"
        ]

        if peer.get("preshared_key"):
            lines.append(f"PresharedKey = {peer['preshared_key']}")

        lines.append(f"AllowedIPs = {peer['address']}")

    return "\n".join(lines) + "\n"


def render_peer_config(data, peer):

    server = data["server"]

    if server["routing"] == "full":
        allowed = "0.0.0.0/0, ::/0"
    else:
        tunnel = str(ipaddress.IPv4Interface(server["address"]).network)
        allowed = ", ".join([tunnel] + get_lan_networks())

    endpoint = server["endpoint"] or "YOUR_PUBLIC_ADDRESS"

    lines = [
        f"# {peer['name']} - generated by Chardsoft Router OS",
        "",
        "[Interface]",
        f"PrivateKey = {peer['private_key']}",
        f"Address = {peer['address']}"
    ]

    if server["dns"]:
        lines.append(f"DNS = {server['dns']}")

    lines += [
        "",
        "[Peer]",
        f"PublicKey = {server['public_key']}"
    ]

    if peer.get("preshared_key"):
        lines.append(f"PresharedKey = {peer['preshared_key']}")

    lines += [
        f"Endpoint = {endpoint}:{server['listen_port']}",
        f"AllowedIPs = {allowed}",
        # Keeps the tunnel open through NAT on the client's side.
        "PersistentKeepalive = 25"
    ]

    return "\n".join(lines) + "\n"


def server_firewall_rules(server):

    return firewall_rules_for("WireGuard", [
        ["allow", "in", "from", "any", "to", "any",
         "port", str(server["listen_port"]), "proto", "udp"],
        ["allow", "in", "on", SERVER_INTERFACE],
        ["route", "allow", "in", "on", SERVER_INTERFACE]
    ])


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def apply_server():
    """
    Applies the running WireGuard config.
    """

    data = load_wireguard()
    server = data["server"]

    if not has_wireguard():

        if not server["enabled"]:
            return True, "WireGuard server stopped."

        return False, "WireGuard is not available."

    if not server["enabled"]:

        stop_unit(SERVER_UNIT)

        return True, sync_firewall("wireguard", []) or "WireGuard server stopped."

    ok, result = write_root_file(
        SERVER_CONF,
        render_server_config(data)
    )

    if not ok:
        return False, f"WireGuard config could not be written: {result}"

    warning = sync_firewall("wireguard", server_firewall_rules(server))

    ok, result = start_unit(SERVER_UNIT)

    if not ok:
        return False, f"WireGuard failed to start: {result}"

    return True, warning or "WireGuard server running."


def verify_server():

    if not load_wireguard()["server"]["enabled"]:
        return True, "OK"

    return unit_stays_active(SERVER_UNIT)


def save_server(settings):
    """
    Validates server settings and applies them through safe apply.
    """

    data = load_wireguard()

    merged = dict(data["server"])
    merged.update(settings or {})

    ok, result = validate_server(merged)

    if not ok:
        return transaction.result(False, result)

    data["server"].update(result)

    if not data["server"]["private_key"]:

        private, public = generate_keypair()

        if not private:
            return transaction.result(False, "Could not generate keys.")

        data["server"]["private_key"] = private
        data["server"]["public_key"] = public

    # Peers must stay inside the (possibly changed) tunnel subnet.
    network = ipaddress.IPv4Interface(data["server"]["address"]).network

    for peer in data["peers"]:

        if ipaddress.IPv4Interface(peer["address"]).ip not in network:
            return transaction.result(False, (
                f"Peer {peer['name']} ({peer['address']}) is outside "
                f"the new subnet. Remove it first."
            ))

    return save_wireguard(data)


# -------------------------------------------------------------------
# Peers
# -------------------------------------------------------------------

def next_peer_address(data):

    server = ipaddress.IPv4Interface(data["server"]["address"])

    used = {server.ip} | {
        ipaddress.IPv4Interface(p["address"]).ip
        for p in data["peers"]
    }

    for host in server.network.hosts():

        if host not in used:
            return f"{host}/32"

    return None


def add_peer(name, public_key=""):
    """
    Adds a peer. Without a public key, keys are generated so the
    full client config can be downloaded. Returns a result dict.
    """

    data = load_wireguard()

    name = str(name or "").strip()
    public_key = str(public_key or "").strip()

    if not valid_name(name):
        return transaction.result(False, (
            "Name must be 1-32 letters, numbers, - or _."
        ))

    if any(p["name"] == name for p in data["peers"]):
        return transaction.result(False, f"A peer named {name} already exists.")

    if not data["server"]["public_key"]:
        return transaction.result(False, "Save the server settings first.")

    address = next_peer_address(data)

    if not address:
        return transaction.result(False, "No free addresses left in the tunnel subnet.")

    private_key = ""

    if public_key:

        if not valid_key(public_key):
            return transaction.result(False, "Invalid public key.")

        if any(p["public_key"] == public_key for p in data["peers"]):
            return transaction.result(False, "That public key is already in use.")

    else:

        private_key, public_key = generate_keypair()

        if not private_key:
            return transaction.result(False, "Could not generate keys.")

    peer = {
        "id": max([p["id"] for p in data["peers"]] + [0]) + 1,
        "name": name,
        "address": address,
        "public_key": public_key,
        "private_key": private_key,
        "preshared_key": generate_psk() or "",
        "created": int(time.time())
    }

    data["peers"].append(peer)

    # Adding a peer cannot cut off the user; no confirmation needed.
    outcome = save_wireguard(data, confirm=False)

    if outcome["success"]:
        outcome["message"] = "Peer added."
        outcome["peer_id"] = peer["id"]

    return outcome


def remove_peer(peer_id):

    data = load_wireguard()

    peers = [p for p in data["peers"] if p["id"] != peer_id]

    if len(peers) == len(data["peers"]):
        return transaction.result(False, "Peer not found.")

    data["peers"] = peers

    outcome = save_wireguard(data, confirm=False)

    if outcome["success"]:
        outcome["message"] = "Peer removed."

    return outcome


def get_peer_config(peer_id):
    """
    Returns (ok, filename or message, config text).
    """

    data = load_wireguard()

    peer = next((p for p in data["peers"] if p["id"] == peer_id), None)

    if not peer:
        return False, "Peer not found.", None

    if not peer.get("private_key"):
        return False, (
            "This peer brought its own key. "
            "Configure it on the device itself."
        ), None

    return True, f"{peer['name']}.conf", render_peer_config(data, peer)


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def get_live_peers():
    """
    Parses `wg show wg0 dump`:
    pubkey psk endpoint allowed-ips latest-handshake rx tx keepalive
    """

    if not has_wireguard():
        return {}

    ok, output = run_command(privileged([
        which("wg"),
        "show",
        SERVER_INTERFACE,
        "dump"
    ]))

    if not ok or not output:
        return {}

    live = {}

    # First line describes the interface itself.
    for line in output.splitlines()[1:]:

        parts = line.split("\t")

        if len(parts) < 8:
            continue

        try:

            handshake = int(parts[4])

            live[parts[0]] = {
                "endpoint": "" if parts[2] == "(none)" else parts[2],
                "handshake": handshake or None,
                "rx_bytes": int(parts[5]),
                "tx_bytes": int(parts[6])
            }

        except ValueError:
            pass

    return live


def get_wireguard_status():

    data = load_wireguard()
    view = public_view(data)

    running = has_wireguard() and unit_active(SERVER_UNIT)
    live = get_live_peers() if running else {}

    now = int(time.time())

    for peer in view["peers"]:

        info = live.get(peer["public_key"], {})

        handshake = info.get("handshake")

        peer["endpoint"] = info.get("endpoint", "")
        peer["rx_bytes"] = info.get("rx_bytes", 0)
        peer["tx_bytes"] = info.get("tx_bytes", 0)
        peer["last_handshake"] = now - handshake if handshake else None

        # WireGuard re-handshakes every 2 minutes on active tunnels.
        peer["connected"] = bool(handshake and now - handshake < 180)

    view["installed"] = has_wireguard()
    view["running"] = running

    return view
