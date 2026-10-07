import ipaddress
import os
import subprocess
import socket
import re
import time

from services.config import (
    load_running,
    load_settings
)

from services import transaction

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

DEVICE_ALIASES = "device_aliases"


# -------------------------------------------------------------------
# Offline OUI Database
# -------------------------------------------------------------------

OUI_DB = {
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "3C:5A:B4": "Google",
    "F4:F5:D8": "Google",
    "28:CF:E9": "Apple",
    "A4:83:E7": "Apple",
    "F0:18:98": "Apple",
    "00:1A:11": "Google Nest",
    "44:65:0D": "Amazon",
    "18:74:2E": "Samsung",
    "AC:37:43": "Samsung",
    "B0:BE:76": "Intel",
    "D8:BB:2C": "Intel",
    "7C:10:C9": "Intel",
    "24:0A:C4": "Espressif",
    "84:F3:EB": "Espressif",
    "30:AE:A4": "Espressif",
    "00:15:5D": "Microsoft Hyper-V",
    "00:50:56": "VMware",
    "08:00:27": "VirtualBox",
    "52:54:00": "QEMU/KVM"
}


# -------------------------------------------------------------------
# Device Aliases
# -------------------------------------------------------------------

def load_device_aliases():
    return load_running(DEVICE_ALIASES, {})


def save_device_aliases(data):
    return transaction.change(DEVICE_ALIASES, data)


def lookup_alias(mac):
    return load_device_aliases().get(mac.upper())


def set_device_alias(mac, name):

    aliases = load_device_aliases()

    mac = mac.upper()

    if name:
        aliases[mac] = name.strip()
    else:
        aliases.pop(mac, None)

    return save_device_aliases(aliases)["success"]


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def run(cmd):

    try:

        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )

        return result.stdout.strip()

    except Exception:
        return None


def privileged(cmd):

    if os.geteuid() == 0:
        return cmd

    return ["sudo", "-n"] + cmd


def run_command(cmd):

    try:

        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:

            return False, (
                stderr
                or stdout
                or f"Command failed with exit status {result.returncode}."
            )

        return True, stdout

    except FileNotFoundError:

        return False, f"Command not found: {cmd[0]}"

    except Exception as e:

        return False, str(e)


# -------------------------------------------------------------------
# NetworkManager
# -------------------------------------------------------------------

# Seconds a service must stay up after a restart to count as working.
SETTLE_SECONDS = float(os.getenv("CHAOS_SETTLE_SECONDS", "2"))


def unit_stays_active(unit):
    """
    Verifies a restarted service did not crash right after starting
    (systemctl restart succeeds before e.g. hostapd gives up).
    """

    time.sleep(SETTLE_SECONDS)

    if run(["systemctl", "is-active", unit]) == "active":
        return True, "OK"

    return False, f"{unit} stopped right after starting."


def has_networkmanager():

    return run(["which", "nmcli"]) is not None


def require_networkmanager():

    if not has_networkmanager():

        return False, "NetworkManager is not available."

    return True, "OK"


# -------------------------------------------------------------------
# Interface helpers
# -------------------------------------------------------------------

def get_connection_for_interface(interface):

    if not has_networkmanager():
        return None

    output = run([
        "nmcli",
        "-t",
        "-f",
        "NAME,DEVICE",
        "connection",
        "show",
        "--active"
    ])

    if not output:
        return None

    for line in output.splitlines():

        if ":" not in line:
            continue

        name, device = line.split(":", 1)

        if device == interface:
            return name

    return None


def get_connection_mode(connection):

    if not connection or not has_networkmanager():
        return "Unknown"

    ok, output = run_command([
        "nmcli",
        "-g",
        "ipv4.method",
        "connection",
        "show",
        connection
    ])

    if not ok or not output:
        return "Unknown"

    method = output.strip().lower()

    if method == "auto":
        return "DHCP Client"

    if method == "manual":
        return "Static"

    return method


# -------------------------------------------------------------------
# Live interface information
# -------------------------------------------------------------------

def get_ip(interface):

    output = run([
        "ip",
        "-4",
        "-o",
        "addr",
        "show",
        interface
    ])

    if not output:
        return "Unknown"

    for line in output.splitlines():

        if "inet " in line:

            return (
                line
                .split("inet ", 1)[1]
                .split("/", 1)[0]
            )

    return "Unknown"


def get_subnet_mask(interface):

    output = run([
        "ip",
        "-4",
        "-o",
        "addr",
        "show",
        interface
    ])

    if not output:
        return "255.255.255.0"

    for line in output.splitlines():

        if "inet " not in line:
            continue

        try:

            cidr = int(
                line
                .split("inet ", 1)[1]
                .split("/", 1)[1]
                .split()[0]
            )

            mask = (
                (0xffffffff << (32 - cidr))
                & 0xffffffff
            )

            return socket.inet_ntoa(
                mask.to_bytes(4, "big")
            )

        except (ValueError, OSError):
            pass

    return "255.255.255.0"


def get_gateway(interface):

    output = run([
        "ip",
        "route",
        "show",
        "dev",
        interface
    ])

    if not output:
        return "Unknown"

    for line in output.splitlines():

        if line.startswith("default via"):

            parts = line.split()

            if len(parts) >= 3:
                return parts[2]

    return "Unknown"


def get_connection_dns(connection):

    if not connection or not has_networkmanager():
        return "Unknown"

    ok, output = run_command([
        "nmcli",
        "-g",
        "ipv4.dns",
        "connection",
        "show",
        connection
    ])

    if not ok or not output:
        return "Unknown"

    for value in output.replace(",", " ").split():

        if value:
            return value

    return "Unknown"


def get_dns():

    interface = get_default_interface()

    connection = get_connection_for_interface(interface)

    return get_connection_dns(connection)


def get_default_interface():

    output = run([
        "ip",
        "route",
        "show",
        "default"
    ])

    if not output:
        return "Unknown"

    for line in output.splitlines():

        parts = line.split()

        if "dev" in parts:

            try:

                return parts[
                    parts.index("dev") + 1
                ]

            except (ValueError, IndexError):
                pass

    return "Unknown"


def get_connection_type(interface):

    # LTE or 5G: the header shows which, from the modem itself.
    if interface.startswith(("wwan", "cdc", "usb")):
        return "Cellular"

    if interface.startswith("eth"):
        return "Ethernet"

    if interface.startswith("wl"):
        return "Wi-Fi"

    return "Unknown"


# -------------------------------------------------------------------
# Interface API
# -------------------------------------------------------------------

def get_interfaces():

    interfaces = []

    for interface in ("wwan0", "eth0"):

        if run([
            "ip",
            "link",
            "show",
            interface
        ]) is None:

            continue

        connection = get_connection_for_interface(interface)

        # wwan0 is controlled by the modem.
        if interface == "wwan0":

            mode = "Modem managed"

        else:

            mode = get_connection_mode(connection)

            if mode == "Unknown":
                mode = "DHCP Client"

        interfaces.append({

            "name": interface,

            "connection": connection,

            "type": get_connection_type(interface),

            "mode": mode,

            "ip": get_ip(interface),

            "subnet": get_subnet_mask(interface),

            "gateway": get_gateway(interface),

            "dns": get_connection_dns(connection)

        })

    return interfaces


# -------------------------------------------------------------------
# Compatibility
# -------------------------------------------------------------------

def get_lan_config():

    for interface in get_interfaces():

        if interface["name"] == "eth0":

            return interface

    return {

        "interface": "eth0",

        "connection": None,

        "ip": "Unknown",

        "subnet": "255.255.255.0",

        "gateway": "Unknown",

        "dns": get_connection_dns(
            get_connection_for_interface("eth0")
        )

    }


# -------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------

def _valid_ipv4(value):

    try:

        socket.inet_aton(value)

        return True

    except (OSError, TypeError):

        return False


def validate_lan_config(config):

    interface = config.get(
        "interface",
        "eth0"
    )

    mode = config.get(
        "mode",
        "Static"
    )

    # wwan0 is modem controlled.
    if interface == "wwan0":

        return (
            False,
            "wwan0 is modem-managed and cannot be configured here."
        )

    if interface != "eth0":

        return (
            False,
            "Unsupported network interface."
        )

    if mode not in (
        "DHCP Client",
        "Static"
    ):

        return (
            False,
            "Invalid network mode."
        )

    # DHCP gets everything automatically.
    if mode == "DHCP Client":

        return True, "OK"

    # Static requires all values.
    for field in (
        "ip",
        "subnet",
        "gateway",
        "dns"
    ):

        if not _valid_ipv4(
            config.get(field)
        ):

            return (
                False,
                f"Invalid {field}."
            )

    # Validate contiguous subnet mask.
    try:

        bits = "".join(
            bin(int(o))[2:].zfill(8)
            for o in config["subnet"].split(".")
        )

        if not re.match(
            r"^1*0*$",
            bits
        ):

            return (
                False,
                "Invalid subnet mask."
            )

    except Exception:

        return (
            False,
            "Invalid subnet mask."
        )

    return True, "OK"


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def mask_to_cidr(mask):

    bits = "".join(
        bin(int(o))[2:].zfill(8)
        for o in mask.split(".")
    )

    return bits.count("1")


def apply_interface_config(
    config,
    dry_run=True,
    role="lan"
):

    valid, message = validate_lan_config(
        config
    )

    if not valid:
        return False, message

    ok, message = require_networkmanager()

    if not ok:
        return False, message

    interface = config["interface"]

    connection = get_connection_for_interface(
        interface
    )

    if not connection:

        return False, (
            f"No active NetworkManager connection "
            f"for {interface}."
        )

    mode = config.get(
        "mode",
        "DHCP Client"
    )

    # ---------------------------------------------------------------
    # DHCP
    # ---------------------------------------------------------------

    if mode == "DHCP Client":

        commands = [

            [
                "nmcli",
                "connection",
                "modify",
                connection,

                "ipv4.method",
                "auto",

                "ipv4.addresses",
                "",

                "ipv4.gateway",
                "",

                "ipv4.dns",
                "",

                "ipv4.ignore-auto-dns",
                "no"
            ]

        ]

    # ---------------------------------------------------------------
    # Static
    # ---------------------------------------------------------------

    else:

        cidr = mask_to_cidr(
            config["subnet"]
        )

        address = (
            f"{config['ip']}/{cidr}"
        )

        commands = [

            [
                "nmcli",
                "connection",
                "modify",
                connection,

                "ipv4.method",
                "manual",

                "ipv4.addresses",
                address,

                "ipv4.gateway",
                config["gateway"],

                "ipv4.dns",
                config["dns"],

                "ipv4.ignore-auto-dns",
                "yes"
            ]

        ]

    # Only the WAN may carry the default route. On the LAN a gateway
    # would otherwise pull the internet away from the modem.
    if role == "wan":
        commands[0] += [
            "ipv4.never-default", "no",
            "ipv4.route-metric", WAN_ROUTE_METRIC
        ]
    else:
        commands[0] += [
            "ipv4.never-default", "yes",
            "ipv4.route-metric", "-1"
        ]

    # Apply the connection.
    commands.append([
        "nmcli",
        "connection",
        "up",
        connection
    ])

    if dry_run:

        return True, {

            "mode": "dry-run",

            "interface": interface,

            "connection": connection,

            "commands": commands

        }

    # ---------------------------------------------------------------
    # Execute
    # ---------------------------------------------------------------

    for cmd in commands:

        ok, result = run_command(cmd)

        if not ok:

            command_text = " ".join(
                f'"{x}"' if " " in x else x
                for x in cmd
            )

            return False, (
                f"{result}\n\n"
                f"Command: {command_text}"
            )

    return True, (
        "Network configuration applied."
    )


# -------------------------------------------------------------------
# Network settings (network.json)
# -------------------------------------------------------------------

NETWORK = "network"

INTERFACE_FIELDS = ("interface", "mode", "ip", "subnet", "gateway", "dns")


# eth0 is the LAN port by default. In WAN mode it is the internet
# uplink instead of the modem.
ETH0 = "eth0"

ETH0_ROLES = ("lan", "wan")

MODEM_INTERFACE = "wwan0"

# Below the modem's route metric, so eth0 wins while it is the WAN.
WAN_ROUTE_METRIC = "50"

# eth0's LAN address when no earlier LAN config is known.
DEFAULT_LAN_CONFIG = {
    "interface": ETH0,
    "mode": "Static",
    "ip": "192.168.1.1",
    "subnet": "255.255.255.0",
    "gateway": "192.168.1.1",
    "dns": "192.168.1.1"
}


def get_network_settings():
    """
    {"interfaces": {"eth0": {...}}, "eth0_role": "lan" | "wan",
    "lan_config": {...}, "lan": {...}} from the running config.
    lan_config keeps eth0's LAN settings while it is the WAN; lan is
    the LAN bridge (see LAN bridge below).
    """

    settings = load_settings(NETWORK, {"interfaces": {}})

    role = settings.get("eth0_role")

    result = {
        "interfaces": dict(settings.get("interfaces") or {}),
        "eth0_role": role if role in ETH0_ROLES else "lan",
        "lan_config": settings.get("lan_config") or None
    }

    result["lan"] = _lan_settings(settings.get("lan"), result)

    return result


def _lan_settings(lan, settings):
    """
    The LAN bridge settings. Off until switched on from the Network
    page; the address is prefilled from eth0's LAN settings.
    """

    lan = lan if isinstance(lan, dict) else {}

    eth0 = settings["interfaces"].get(ETH0) or {}

    source = (
        settings["lan_config"]
        or (eth0 if settings["eth0_role"] == "lan" and eth0.get("mode") == "Static" else None)
        or DEFAULT_LAN_CONFIG
    )

    return {
        "bridge": lan.get("bridge") is True,
        "ip": lan.get("ip") or source["ip"],
        "subnet": lan.get("subnet") or source["subnet"]
    }


def get_eth0_role():

    return get_network_settings()["eth0_role"]


def get_wan_interface():
    """
    The internet uplink: eth0 in WAN mode, otherwise the modem.
    """

    return ETH0 if get_eth0_role() == "wan" else MODEM_INTERFACE


def is_wan_interface(name):

    return name == get_wan_interface()


# Interfaces that can serve the LAN: Ethernet (eth0, enx... USB
# adapters), Wi-Fi (wlan0, wlan1, ...) and bridges. The modem (wwan*),
# VPN tunnels and loopback never do.
LAN_PREFIXES = ("eth", "en", "wlan", "wl", "br")

INTERFACE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def is_lan_capable(name):
    """
    Whether this kind of interface can serve a LAN at all, by name
    (it does not have to exist right now, e.g. an unplugged USB Wi-Fi
    adapter). eth0 counts even while it is the WAN.
    """

    name = str(name or "")

    return bool(INTERFACE_NAME_RE.fullmatch(name)) and name.startswith(LAN_PREFIXES)


def is_lan_name(name):
    """
    Whether this interface serves the LAN right now: LAN-capable and
    not the WAN.
    """

    return is_lan_capable(name) and not is_wan_interface(name)


def get_lan_interface_names():
    """
    LAN interfaces that exist now, e.g. ["eth0", "wlan0", "wlan1"].
    eth0 drops out while it is the WAN.
    """

    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return []

    # Bridge ports are served through their bridge (br0).
    return [
        name for name in names
        if is_lan_name(name) and not get_bridge_master(name)
    ]


def get_network_baseline():
    """
    The interface config NetworkManager runs now, before the first
    change made from the dashboard.
    """

    interfaces = {}

    for iface in get_interfaces():

        if iface["name"] == "wwan0":
            continue

        config = {
            "interface": iface["name"],
            "mode": "Static" if iface["mode"] == "Static" else "DHCP Client"
        }

        if config["mode"] == "Static":
            config.update({
                "ip": iface["ip"],
                "subnet": iface["subnet"],
                "gateway": iface["gateway"],
                "dns": iface["dns"]
            })

        interfaces[iface["name"]] = config

    return {"interfaces": interfaces, "eth0_role": "lan"}


def apply_network_settings():

    settings = get_network_settings()

    bridged = settings["lan"]["bridge"]

    # eth0 is a bridge port while it is a LAN port and the bridge is on;
    # then it has no address of its own.
    eth0_in_bridge = bridged and settings["eth0_role"] == "lan"

    if bridged:

        ok, result = apply_lan_bridge(settings["lan"])

        if not ok:
            return False, f"LAN bridge: {result}"

    if eth0_in_bridge:

        ok, result = add_bridge_port(ETH0)

        if not ok:
            return False, f"{ETH0}: {result}"

    else:

        # Back to eth0's own connection (WAN, or LAN without bridge).
        ok, result = remove_bridge_port(ETH0)

        if not ok:
            return False, f"{ETH0}: {result}"

    if not bridged:

        ok, result = remove_lan_bridge()

        if not ok:
            return False, f"LAN bridge: {result}"

    for name, config in settings["interfaces"].items():

        if name == ETH0 and eth0_in_bridge:
            continue

        role = settings["eth0_role"] if name == ETH0 else "lan"

        ok, result = apply_interface_config(config, dry_run=False, role=role)

        if not ok:
            return False, f"{name}: {result}"

    return True, "Network configuration applied."


# -------------------------------------------------------------------
# LAN bridge (br0)
#
# One LAN for all ports: br0 holds the router's LAN address; eth0 (in
# LAN mode) is a port through NetworkManager, Wi-Fi access points
# join through hostapd (bridge=br0). DHCP, DNS and the firewall then
# serve br0. Off by default: switching it on moves eth0's address.
# -------------------------------------------------------------------

BRIDGE = "br0"

BRIDGE_CONNECTION = "chaos-lan"

PORT_CONNECTION_PREFIX = "chaos-lan-"


def _connection_names():

    output = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])

    return set((output or "").splitlines())


def _nmcli(*args):

    return run_command(["nmcli", *args])


def apply_lan_bridge(lan):
    """
    Creates or updates the br0 connection with the LAN address and
    brings it up.
    """

    ok, message = require_networkmanager()

    if not ok:
        return False, message

    address = f"{lan['ip']}/{mask_to_cidr(lan['subnet'])}"

    properties = [
        "ipv4.method", "manual",
        "ipv4.addresses", address,
        "ipv4.gateway", "",
        # The LAN never carries the internet route.
        "ipv4.never-default", "yes",
        "ipv6.method", "link-local",
        "bridge.stp", "no",
        "connection.autoconnect", "yes"
    ]

    if BRIDGE_CONNECTION in _connection_names():
        ok, result = _nmcli("connection", "modify", BRIDGE_CONNECTION, *properties)
    else:
        ok, result = _nmcli(
            "connection", "add", "type", "bridge",
            "ifname", BRIDGE, "con-name", BRIDGE_CONNECTION, *properties
        )

    if not ok:
        return False, result

    return _nmcli("connection", "up", BRIDGE_CONNECTION)


def remove_lan_bridge():

    if not has_networkmanager() or BRIDGE_CONNECTION not in _connection_names():
        return True, "OK"

    return _nmcli("connection", "delete", BRIDGE_CONNECTION)


def add_bridge_port(interface):
    """
    Makes an Ethernet interface a port of br0. Activating the port
    connection takes the interface's own connection down.
    """

    name = PORT_CONNECTION_PREFIX + interface

    if name not in _connection_names():

        ok, result = _nmcli(
            "connection", "add", "type", "ethernet",
            "ifname", interface, "con-name", name,
            "master", BRIDGE, "slave-type", "bridge",
            "connection.autoconnect", "yes",
            # Preferred over the interface's own connection at boot.
            "connection.autoconnect-priority", "50"
        )

        if not ok:
            return False, result

    return _nmcli("connection", "up", name)


def remove_bridge_port(interface):
    """
    Takes an interface out of br0 and brings its own connection back.
    """

    name = PORT_CONNECTION_PREFIX + interface

    if not has_networkmanager() or name not in _connection_names():
        return True, "OK"

    ok, result = _nmcli("connection", "delete", name)

    if not ok:
        return False, result

    # NetworkManager picks the interface's own connection again.
    return _nmcli("device", "connect", interface)


def get_bridge_master(interface):
    """
    The bridge an interface is a port of (e.g. "br0"), or None.
    """

    try:
        return os.path.basename(os.readlink(f"/sys/class/net/{interface}/master"))
    except OSError:
        return None


def effective_interface(interface):
    """
    Where an interface's traffic is actually seen: a bridge port's
    traffic arrives on the bridge, so DHCP and DNS must serve that.
    """

    return get_bridge_master(interface) or interface


def get_bridge_ports(bridge=BRIDGE):

    try:
        return sorted(os.listdir(f"/sys/class/net/{bridge}/brif"))
    except OSError:
        return []


def validate_lan_bridge(data):
    """
    Returns (True, lan settings) or (False, message).
    """

    lan = dict(get_network_settings()["lan"])
    lan.update(data or {})

    if not isinstance(lan.get("bridge"), bool):
        return False, "Invalid bridge setting."

    if not _valid_ipv4(lan.get("ip")):
        return False, "Invalid IP address."

    if not _valid_ipv4(lan.get("subnet")):
        return False, "Invalid subnet mask."

    try:

        bits = "".join(bin(int(o))[2:].zfill(8) for o in lan["subnet"].split("."))

        if not re.match(r"^1*0*$", bits):
            raise ValueError

        prefix = bits.count("1")

    except ValueError:
        return False, "Invalid subnet mask."

    if not 8 <= prefix <= 30:
        return False, "Subnet mask must be between /8 and /30."

    network = ipaddress.IPv4Interface(f"{lan['ip']}/{prefix}").network

    if lan["ip"] in (str(network.network_address), str(network.broadcast_address)):
        return False, f"{lan['ip']} is the network or broadcast address of {network}."

    return True, {"bridge": lan["bridge"], "ip": lan["ip"], "subnet": lan["subnet"]}


def set_lan_bridge(data):

    ok, result = validate_lan_bridge(data)

    if not ok:
        return transaction.result(False, result)

    settings = get_network_settings()
    settings["lan"] = result

    return transaction.change(
        NETWORK, settings,
        hint=f"If this page stops responding, open http://{result['ip']}/ to confirm."
    )


def get_lan_bridge_status():

    settings = get_network_settings()

    return {
        "settings": settings["lan"],
        "eth0_role": settings["eth0_role"],
        "active": os.path.exists(f"/sys/class/net/{BRIDGE}"),
        "ports": get_bridge_ports(),
        "address": get_ip(BRIDGE),
        "eth0_address": get_ip(ETH0)
    }


def change_interface(config):
    """
    Applies one interface's settings through safe apply.
    """

    ok, message = validate_lan_config(config)

    if not ok:
        return transaction.result(False, message)

    config = {k: config[k] for k in INTERFACE_FIELDS if k in config}

    settings = get_network_settings()
    settings["interfaces"][config["interface"]] = config

    hint = None

    if config.get("mode") == "Static":
        hint = f"If this page stops responding, open http://{config['ip']}/ to confirm."

    return transaction.change(NETWORK, settings, hint=hint)


def set_eth0_role(role):
    """
    Switches eth0 between LAN port and internet uplink. WAN mode makes
    it a DHCP client with the default route; LAN mode restores its
    previous LAN settings.
    """

    if role not in ETH0_ROLES:
        return transaction.result(False, "Invalid mode.")

    settings = get_network_settings()

    if settings["eth0_role"] == role:
        return transaction.result(False, f"eth0 is already in {role.upper()} mode.")

    current = (
        settings["interfaces"].get(ETH0)
        or get_network_baseline()["interfaces"].get(ETH0)
    )

    if not current:
        return transaction.result(False, "eth0 was not found.")

    if role == "wan":

        # Kept for switching back.
        if current.get("mode") == "Static":
            settings["lan_config"] = current

        settings["interfaces"][ETH0] = {
            "interface": ETH0,
            "mode": "DHCP Client"
        }

        hint = (
            "If you are connected through eth0, reconnect over Wi-Fi "
            "to confirm."
        )

    else:

        lan = settings["lan_config"] or DEFAULT_LAN_CONFIG

        settings["interfaces"][ETH0] = dict(lan)

        hint = f"If this page stops responding, open http://{lan['ip']}/ to confirm."

    settings["eth0_role"] = role

    return transaction.change(NETWORK, settings, hint=hint)


# -------------------------------------------------------------------
# Compatibility wrapper
# -------------------------------------------------------------------

def apply_lan_config(
    config,
    dry_run=True
):

    return apply_interface_config(
        config,
        dry_run
    )


# -------------------------------------------------------------------
# Client intelligence
# -------------------------------------------------------------------

def lookup_hostname(ip):

    output = run([
        "getent",
        "hosts",
        ip
    ])

    if output:

        parts = output.split()

        if len(parts) >= 2:
            return parts[1]

    return "Unknown"


def lookup_vendor(mac):

    return OUI_DB.get(
        mac.upper()[:8],
        "Unknown"
    )


# -------------------------------------------------------------------
# Clients
# -------------------------------------------------------------------

def get_clients():

    clients = []

    output = run([
        "ip",
        "neigh"
    ])

    if not output:
        return clients

    for line in output.splitlines():

        parts = line.split()

        if len(parts) < 5:
            continue

        ip = parts[0]

        try:

            socket.inet_aton(ip)

        except Exception:

            continue

        interface = parts[2]
        mac = parts[4]
        state = parts[-1]

        if state == "REACHABLE":

            status = "Online"

        elif state == "STALE":

            status = "Idle"

        else:

            status = state.title()

        alias = lookup_alias(mac)

        clients.append({

            "hostname":
                alias or lookup_hostname(ip),

            "ip":
                ip,

            "interface":
                interface,

            "mac":
                mac,

            "state":
                status,

            "vendor":
                lookup_vendor(mac),

            "traffic":
                "--"

        })

    clients.sort(
        key=lambda c: (
            c["state"] != "Online",
            c["hostname"] == "Unknown",
            c["ip"]
        )
    )

    return clients


def get_connected_clients():

    return len(
        get_clients()
    )