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
        return subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


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
            return line.split("inet ", 1)[1].split("/", 1)[0]

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
            cidr = int(line.split("inet ", 1)[1].split("/", 1)[1].split()[0])
            mask = (0xffffffff << (32 - cidr)) & 0xffffffff
            return socket.inet_ntoa(mask.to_bytes(4, "big"))
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

    output = run([
        "nmcli",
        "-g",
        "ipv4.dns",
        "connection",
        "show",
        connection
    ])

    if not output:
        return "Unknown"

    # nmcli can return multiple DNS servers separated by spaces/newlines.
    for value in output.replace(",", " ").split():

        if value:
            return value

    return "Unknown"


def get_dns():

    return get_connection_dns(
        get_connection_for_interface(
            get_default_interface()
        )
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

    for line in output.splitlines():

        parts = line.split()

        if "dev" in parts:

            try:
                return parts[parts.index("dev") + 1]
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


# Compatibility with the current frontend/backend.
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

    interface = config.get("interface", "eth0")
    mode = config.get("mode", "Static")

    # Only eth0 is configurable from this page.
    # wwan0 is modem-managed and must not be changed here.
    if interface == "wwan0":
        return False, "wwan0 is modem-managed and cannot be configured here."

    if interface != "eth0":
        return False, "Unsupported network interface."

    if mode not in ("DHCP Client", "Static"):
        return False, "Invalid network mode."

    # DHCP Client receives IP/subnet/gateway/DNS from DHCP.
    # Do not require or modify those values.
    if mode == "DHCP Client":
        return True, "OK"

    for field in ("ip", "subnet", "gateway", "dns"):

        if not _valid_ipv4(config.get(field)):
            return False, f"Invalid {field}."

    # Verify that the subnet mask is contiguous.
    try:
        bits = "".join(
            bin(int(o))[2:].zfill(8)
            for o in config["subnet"].split(".")
        )

        if not __import__("re").match(r"^1*0*$", bits):
            return False, "Invalid subnet mask."

    except Exception:
        return False, "Invalid subnet mask."

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

    ok, message = require_networkmanager()

    if not ok:
        return False, message

    interface = config["interface"]
    connection = get_connection_for_interface(interface)

    if not connection:
        return False, (
            f"No active NetworkManager connection for {interface}."
        )

    commands = []

    # ----------------------------------------------------------------
    # eth0 DHCP Client
    #
    # DHCP owns IP/subnet/gateway/DNS. We deliberately do not write
    # DNS here. Switching to DHCP also restores automatic DNS.
    # ----------------------------------------------------------------

    if config.get("mode") == "DHCP Client":

        commands.extend([
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
                "no"
            ],
            [
                "nmcli",
                "connection",
                "modify",
                connection,
                "ipv4.dns",
                ""
            ]
        ])

    # ----------------------------------------------------------------
    # eth0 Static
    #
    # Explicitly set all four values. DNS is therefore persisted in
    # NetworkManager instead of only changing the frontend.
    # ----------------------------------------------------------------

    else:

        cidr = mask_to_cidr(config["subnet"])

        commands.extend([
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
        ])

    # Reactivate the connection so the new configuration becomes live.
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

    try:

        for cmd in commands:
            subprocess.check_call(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )

        return True, "Network configuration applied."

    except subprocess.CalledProcessError as e:

        error = (e.stderr or str(e)).strip()

        return False, error or "NetworkManager failed to apply the configuration."

    except FileNotFoundError:

        return False, (
            "nmcli was not found. Install/enable NetworkManager "
            "on the router."
        )


# Compatibility wrapper.
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