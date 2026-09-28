import subprocess
import socket

from services.config import (
    load_json,
    save_json,
    CONFIG_DIR
)

# -------------------------------------------------------------------
# Configuration Paths
# -------------------------------------------------------------------

DEVICE_ALIASES_FILE = f"{CONFIG_DIR}/device_aliases.json"

# -------------------------------------------------------------------
# Offline MAC Vendor Database
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
    return load_json(DEVICE_ALIASES_FILE, {})


def save_device_aliases(aliases):
    save_json(DEVICE_ALIASES_FILE, aliases)


def lookup_alias(mac):

    aliases = load_device_aliases()

    return aliases.get(mac.upper())


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

# -------------------------------------------------------------------
# NetworkManager
# -------------------------------------------------------------------

def has_networkmanager():
    return run(["which", "nmcli"]) is not None


def get_active_connection():

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
        if ":" in line:
            return line.split(":", 1)[0]

    return None

# -------------------------------------------------------------------
# Live Network Status
# -------------------------------------------------------------------

def get_default_interface():
    try:
        output = subprocess.check_output(
            ["ip", "route", "show", "default"],
            text=True
        )
        return output.split("dev")[1].split()[0]
    except Exception:
        return "Unknown"


def get_gateway():
    try:
        output = subprocess.check_output(
            ["ip", "route", "show", "default"],
            text=True
        )
        return output.split("via")[1].split()[0]
    except Exception:
        return "Unknown"


def get_dns():
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    return line.split()[1]
    except Exception:
        pass

    return "Unknown"


def get_connection_type(interface):

    if interface.startswith(("wwan", "cdc", "usb")):
        return "5G"

    if interface.startswith("wl"):
        return "Wi-Fi"

    if interface.startswith("eth"):
        return "Ethernet"

    return "Unknown"


def get_ip(interface):
    try:
        return subprocess.check_output(
            ["hostname", "-I"],
            text=True
        ).split()[0]
    except Exception:
        return "Unknown"

# -------------------------------------------------------------------
# LAN Configuration
# -------------------------------------------------------------------

def get_subnet_mask(interface):

    try:

        output = subprocess.check_output(
            ["ip", "-4", "addr", "show", interface],
            text=True
        )

        for line in output.splitlines():

            line = line.strip()

            if line.startswith("inet "):

                cidr = int(line.split("/")[1].split()[0])

                mask = (0xffffffff << (32 - cidr)) & 0xffffffff

                return socket.inet_ntoa(mask.to_bytes(4, "big"))

    except Exception:
        pass

    return "255.255.255.0"


def get_lan_config():

    interface = get_default_interface()

    return {
        "interface": interface,
        "connection": get_active_connection(),
        "ip": get_ip(interface),
        "subnet": get_subnet_mask(interface),
        "gateway": get_gateway(),
        "dns": get_dns()
    }


def validate_lan_config(config):

    try:
        socket.inet_aton(config["ip"])
        socket.inet_aton(config["subnet"])
        socket.inet_aton(config["gateway"])
        socket.inet_aton(config["dns"])
    except OSError:
        return False, "One or more addresses are invalid."

    return True, "OK"

# -------------------------------------------------------------------
# Apply Engine
# -------------------------------------------------------------------

def mask_to_cidr(mask):

    bits = "".join(
        bin(int(octet))[2:].zfill(8)
        for octet in mask.split(".")
    )

    return bits.count("1")


def apply_lan_config(config, dry_run=True):

    valid, message = validate_lan_config(config)

    if not valid:
        return False, message

    connection = get_active_connection()

    if connection is None:
        return False, "No active NetworkManager connection."

    cidr = mask_to_cidr(config["subnet"])

    commands = [
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
        ],
        [
            "nmcli",
            "connection",
            "up",
            connection
        ]
    ]

    if dry_run:
        return True, {
            "mode": "dry-run",
            "connection": connection,
            "commands": commands
        }

    try:

        for cmd in commands:
            subprocess.check_call(cmd)

        return True, "Network configuration applied."

    except subprocess.CalledProcessError as e:
        return False, str(e)

# -------------------------------------------------------------------
# Client Intelligence
# -------------------------------------------------------------------

def lookup_hostname(ip):

    try:
        output = subprocess.check_output(
            ["getent", "hosts", ip],
            text=True,
            timeout=0.25
        ).strip()

        if output:
            return output.split()[1]

    except Exception:
        pass

    return "Unknown"


def lookup_vendor(mac):
    return OUI_DB.get(mac.upper()[:8], "Unknown")

# -------------------------------------------------------------------
# Connected Clients
# -------------------------------------------------------------------

def get_clients():

    clients = []

    try:

        output = subprocess.check_output(
            ["ip", "neigh"],
            text=True
        )

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
            hostname = alias or lookup_hostname(ip)

            clients.append({
                "hostname": hostname,
                "ip": ip,
                "interface": interface,
                "mac": mac,
                "state": status,
                "vendor": lookup_vendor(mac),
                "traffic": "--"
            })

    except Exception:
        pass

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