"""
The setup Wi-Fi: a WPA2 network with a captive portal that runs while
the router is not set up (fresh install, factory reset).

- Name "ChaosRouter-Setup-XXXX" and a random password, stored in
  /var/lib/chaos-router-os/system/setup_wifi.json (mode 600). They
  survive reboots during setup; a factory reset creates new ones.
  `python backend/setup_wifi.py` prints them with a QR code.
- 2.4 GHz WPA2 on the built-in radio, so every phone can join.
- The router is 10.42.0.1/24 on it; dnsmasq hands out .100-.200 and
  answers every DNS name with 10.42.0.1 (captive portal).
- Port 80 on the setup network is redirected to the app, which sends
  every request to /setup, so phones open the setup page by itself.

Nothing here is saved as router settings: once setup is complete the
setup network is replaced by the real Wi-Fi (same 10.42.0.0/24) or
turned off.
"""

import ipaddress
import os
import secrets
import time

from services.config import load_system, save_system, system_path

from services.network import run_command, privileged

from services import wifi, dhcp

from services.caddy import APP_PORT, BEHIND_CADDY

from services.logs import log_event

SETUP_WIFI = "setup_wifi"

ADDRESS = "10.42.0.1"
PREFIX = 24
NETWORK = ipaddress.IPv4Network(f"{ADDRESS}/{PREFIX}", strict=False)

DHCP_RANGE = ("10.42.0.100", "10.42.0.200")

# Separate from the DHCP and DNS drop-ins; removed after setup.
DNSMASQ_FILE = "/etc/dnsmasq.d/chaos-router-setup.conf"

NAT_CHAIN = "CHAOS-SETUP"


# Easy to read and type: no 0/O, 1/l/I.
PASSWORD_CHARS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# -------------------------------------------------------------------
# Credentials
# -------------------------------------------------------------------

def get_credentials():
    """
    {"ssid", "password"}, created once per setup.
    """

    stored = load_system(SETUP_WIFI, None)

    if isinstance(stored, dict) and stored.get("ssid") and stored.get("password"):
        return stored

    credentials = {
        "ssid": f"ChaosRouter-Setup-{secrets.token_hex(2).upper()}",
        "password": "".join(secrets.choice(PASSWORD_CHARS) for _ in range(12)),
        "created": int(time.time())
    }

    save_system(SETUP_WIFI, credentials, secret=True)

    return credentials


def forget_credentials():

    try:
        os.remove(system_path(SETUP_WIFI))
    except OSError:
        pass


def qr_payload(credentials):
    """
    The standard Wi-Fi QR text phones understand (special characters
    escaped as the format requires).
    """

    def escape(value):
        return "".join("\\" + c if c in '\\;,:"' else c for c in value)

    return f"WIFI:S:{escape(credentials['ssid'])};T:WPA;P:{escape(credentials['password'])};;"


def is_on_setup_network(address):

    try:
        return ipaddress.IPv4Address(address) in NETWORK
    except ValueError:
        return False


# -------------------------------------------------------------------
# Interface
# -------------------------------------------------------------------

def pick_interface():
    """
    The radio for the setup Wi-Fi (and the Wi-Fi set up in the
    wizard): the configured one if present, otherwise the first that
    can do 2.4 GHz, preferring the built-in wlan0.
    """

    interfaces = wifi.get_wireless_interfaces()

    if not interfaces:
        return None

    # A radio that already has a Wi-Fi network (e.g. after a factory
    # reset kept the settings file) comes first.
    configured = [n["interface"] for n in wifi.enabled_networks()]

    candidates = [n for n in configured if n in interfaces] + sorted(interfaces)

    for name in candidates:

        support = wifi.get_band_support(name)

        if support is None or support.get("2.4"):
            return name

    return candidates[0]


def access_point_settings(interface, credentials):

    return {
        **wifi.get_network(interface),
        "enabled": True,
        "interface": interface,
        "ssid": credentials["ssid"],
        "password": credentials["password"],
        "security": "wpa2",
        "band": "2.4",
        "channel": wifi.BANDS["2.4"]["default"],
        "hidden": False,
        "isolate_clients": False,
        "address": ADDRESS,
        "prefix": PREFIX
    }


# -------------------------------------------------------------------
# Captive portal
# -------------------------------------------------------------------

def render_dnsmasq(interface):

    return "\n".join([
        "# Chaos Router OS setup Wi-Fi (captive portal). Removed after setup.",
        "",
        f"interface={interface}",
        f"dhcp-range={DHCP_RANGE[0]},{DHCP_RANGE[1]},{NETWORK.netmask},1h",
        f"dhcp-option=option:router,{ADDRESS}",
        f"dhcp-option=option:dns-server,{ADDRESS}",
        # RFC 8910: tells newer phones where the portal is.
        f"dhcp-option=114,http://{ADDRESS}/setup",
        # Every name points at the router, so any page opens setup.
        f"address=/#/{ADDRESS}",
        ""
    ])


def iptables(*args):

    tool = wifi.which("iptables")

    if not tool:
        return False, "iptables is not available."

    return run_command(privileged([tool, "-t", "nat", *args]))


def redirect_web(interface):
    """
    Port 80 on the setup network -> the app's port.
    """

    iptables("-N", NAT_CHAIN)
    iptables("-F", NAT_CHAIN)

    ok, result = iptables(
        "-A", NAT_CHAIN, "-i", interface, "-p", "tcp", "--dport", "80",
        "-j", "REDIRECT", "--to-ports", APP_PORT
    )

    if not ok:
        return False, result

    hooked, _ = iptables("-C", "PREROUTING", "-j", NAT_CHAIN)

    if not hooked:
        return iptables("-I", "PREROUTING", "1", "-j", NAT_CHAIN)

    return True, "OK"


def remove_redirect():

    iptables("-D", "PREROUTING", "-j", NAT_CHAIN)
    iptables("-F", NAT_CHAIN)
    iptables("-X", NAT_CHAIN)


# -------------------------------------------------------------------
# Start / stop
# -------------------------------------------------------------------

def start():
    """
    Starts the setup Wi-Fi with its captive portal.
    Returns (success, message).
    """

    if os.getenv("CHAOS_SETUP_WIFI") == "0":
        return False, "The setup Wi-Fi is turned off (CHAOS_SETUP_WIFI=0)."

    if not wifi.has_hostapd():
        return False, "hostapd is not available."

    interface = pick_interface()

    if not interface:
        return False, "No Wi-Fi radio found."

    credentials = get_credentials()

    ok, result = wifi.start_access_point(access_point_settings(interface, credentials))

    if not ok:
        return False, result

    ok, result = dhcp.install_dnsmasq_config(render_dnsmasq(interface), path=DNSMASQ_FILE)

    if ok:
        ok, result = dhcp.restart_dnsmasq()

    if not ok:
        return False, f"DHCP for the setup Wi-Fi failed: {result}"

    # Caddy serves port 80 itself; without it, port 80 is redirected to
    # the app's own port.
    if BEHIND_CADDY:
        remove_redirect()
    else:
        ok, result = redirect_web(interface)

        if not ok:
            return False, f"The captive portal could not be set up: {result}"

    log_event(
        "setup",
        f"Setup Wi-Fi '{credentials['ssid']}' started on {interface} ({ADDRESS}/{PREFIX})."
    )

    return True, credentials["ssid"]


def stop(keep_access_point=False):
    """
    Removes the captive portal. keep_access_point: the real Wi-Fi has
    already replaced the setup network on the same radio.
    """

    remove_redirect()

    dhcp.remove_dnsmasq_config(path=DNSMASQ_FILE)
    dhcp.restart_dnsmasq()

    if not keep_access_point:

        interface = pick_interface()

        if interface and wifi.has_hostapd():
            wifi.stop_access_point(interface)

    forget_credentials()

    log_event("setup", "Setup Wi-Fi stopped.")
