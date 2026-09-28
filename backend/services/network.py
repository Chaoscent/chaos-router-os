import subprocess
import socket
import re

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
# Device Aliases
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

def has_networkmanager():

    return run(["which", "nmcli"]) is not None


def require_networkmanager():

    if not has_networkmanager():

        return False, (
            "NetworkManager/nmcli is not installed. "
            "Network configuration requires NetworkManager."
        )

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
    dry_run=True
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