import subprocess
import socket


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
    except:
        return "Unknown"


def get_gateway():
    try:
        output = subprocess.check_output(
            ["ip", "route", "show", "default"],
            text=True
        )
        return output.split("via")[1].split()[0]
    except:
        return "Unknown"


def get_dns():
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    return line.split()[1]
    except:
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
    except:
        return "Unknown"


# -------------------------------------------------------------------
# LAN Configuration
# -------------------------------------------------------------------

def get_lan_config():
    """
    Returns the current LAN configuration.
    This becomes the single source of truth for the Network workspace.
    """

    interface = get_default_interface()

    return {
        "interface": interface,
        "ip": get_ip(interface),
        "subnet": get_subnet_mask(interface),
        "gateway": get_gateway(),
        "dns": get_dns()
    }


def get_subnet_mask(interface):
    """
    Convert CIDR (/24) into a dotted subnet mask.
    """

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

    except:
        pass

    return "255.255.255.0"


def validate_lan_config(config):
    """
    Validation only.
    Applying comes in the next milestone.
    """

    try:
        socket.inet_aton(config["ip"])
        socket.inet_aton(config["subnet"])
        socket.inet_aton(config["gateway"])
        socket.inet_aton(config["dns"])
    except OSError:
        return False, "One or more addresses are invalid."

    return True, "OK"


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
            except:
                continue

            interface = parts[2]
            mac = parts[4]
            state = parts[-1]

            clients.append({
                "hostname": "Unknown",
                "ip": ip,
                "interface": interface,
                "mac": mac,
                "state": state,
                "vendor": "Unknown",
                "traffic": "--"
            })

    except:
        pass

    return clients


def get_connected_clients():
    return len(get_clients())