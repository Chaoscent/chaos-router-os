import subprocess
import socket

from services.config import (
    load_json,
    save_json,
    CONFIG_DIR
)

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

DEVICE_ALIASES_FILE = f"{CONFIG_DIR}/device_aliases.json"

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
# Device aliases
# -------------------------------------------------------------------

def load_device_aliases():
    return load_json(DEVICE_ALIASES_FILE, {})


def save_device_aliases(data):
    save_json(DEVICE_ALIASES_FILE, data)


def lookup_alias(mac):
    return load_device_aliases().get(mac.upper())


def set_device_alias(mac, name):

    aliases = load_device_aliases()

    mac = mac.upper()

    if name:
        aliases[mac] = name.strip()
    else:
        aliases.pop(mac, None)

    save_device_aliases(aliases)

    return True

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def run(cmd):
    try:
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return None


def has_networkmanager():
    return run(["which", "nmcli"]) is not None

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
            return line.split("inet ")[1].split("/")[0]

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

        cidr = int(line.split("/")[1].split()[0])

        mask = (0xffffffff << (32 - cidr)) & 0xffffffff

        return socket.inet_ntoa(mask.to_bytes(4, "big"))

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
            return line.split()[2]

    return "Unknown"


def get_connection_dns(connection):

    if not connection:
        return "Unknown"

    output = run([
        "nmcli",
        "-g",
        "ipv4.dns",
        "connection",
        "show",
        connection
    ])

    if output:
        return output.split()[0]

    return "Unknown"

def get_dns():
    return get_connection_dns(
        get_connection_for_interface(get_default_interface())
    )

def get_default_interface():

    output = run([
        "ip",
        "route",
        "show",
        "default"
    ])

    if not output:
        return "Unknown"

    return output.split("dev")[1].split()[0]


def get_connection_type(interface):

    if interface.startswith(("wwan", "cdc", "usb")):
        return "5G"

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

        if run(["ip", "link", "show", interface]) is None:
            continue

        connection = get_connection_for_interface(interface)

        if interface == "wwan0":
            mode = "DHCP"
        else:
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

# Compatibility with current frontend

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
        "dns": get_connection_dns(get_connection_for_interface("eth0"))
    }

# -------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------

def validate_lan_config(config):

    try:
        socket.inet_aton(config["dns"])

        if config["interface"] == "eth0" and config.get("mode") == "Static":
            socket.inet_aton(config["ip"])
            socket.inet_aton(config["subnet"])
            socket.inet_aton(config["gateway"])

    except OSError:
        return False, "Invalid network configuration."

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


def apply_interface_config(config, dry_run=True):

    valid, message = validate_lan_config(config)

    if not valid:
        return False, message

    connection = get_connection_for_interface(config["interface"])

    if not connection:
        return False, "No active NetworkManager connection."

    commands = []

    if config["interface"] == "wwan0":

        commands += [
            [
                "nmcli",
                "connection",
                "modify",
                connection,
                "ipv4.dns",
                config["dns"]
            ],
            [
                "nmcli",
                "connection",
                "up",
                connection
            ]
        ]

    else:

        if config.get("mode") == "DHCP Client":

            commands += [
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.method",
                    "auto"
                ],
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.ignore-auto-dns",
                    "yes"
                ],
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.dns",
                    config["dns"]
                ]
            ]

        else:

            cidr = mask_to_cidr(config["subnet"])

            commands += [
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.addresses",
                    f"{config['ip']}/{cidr}"
                ],
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.gateway",
                    config["gateway"]
                ],
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.dns",
                    config["dns"]
                ],
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.method",
                    "manual"
                ]
            ]

        commands.append([
            "nmcli",
            "connection",
            "up",
            connection
        ])

    if dry_run:
        return True, {
            "connection": connection,
            "commands": commands
        }

    try:

        for cmd in commands:
            subprocess.check_call(cmd)

        return True, "Applied."

    except subprocess.CalledProcessError as e:
        return False, str(e)

# Compatibility wrapper

def apply_lan_config(config, dry_run=True):
    return apply_interface_config(config, dry_run)

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
    return OUI_DB.get(mac.upper()[:8], "Unknown")

# -------------------------------------------------------------------
# Clients
# -------------------------------------------------------------------

def get_clients():

    clients = []

    output = run(["ip", "neigh"])

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
            "hostname": alias or lookup_hostname(ip),
            "ip": ip,
            "interface": interface,
            "mac": mac,
            "state": status,
            "vendor": lookup_vendor(mac),
            "traffic": "--"
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
    return len(get_clients())