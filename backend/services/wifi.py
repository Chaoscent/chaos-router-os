import os
import re
import shutil
import tempfile

from services.config import load_settings

from services import transaction

from services.network import (
    run,
    run_command,
    privileged,
    unit_stays_active,
    get_network_settings,
    BRIDGE
)

from services.dhcp import get_dhcp_leases

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# wifi.json in /etc/chaos-router-os (defaults) and /var/lib/chaos-router-os.
WIFI_SETTINGS = "wifi"

# Path the Debian hostapd.service reads by default.
HOSTAPD_CONF_FILE = "/etc/hostapd/hostapd.conf"

# hostapd lives in /usr/sbin, which is often missing from a user's PATH.
SBIN_PATH = os.pathsep.join([
    os.environ.get("PATH", ""),
    "/usr/sbin",
    "/sbin"
])

BANDS = {
    "2.4": {
        "hw_mode": "g",
        "channels": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
        "default": 6
    },
    # Non-DFS channels only; the Pi cannot do radar detection as an AP.
    "5": {
        "hw_mode": "a",
        "channels": [36, 40, 44, 48, 149, 153, 157, 161],
        "default": 36
    },
    # Wi-Fi 6E: 20 MHz channels 1-233. No DFS on 6 GHz.
    "6": {
        "hw_mode": "a",
        "channels": list(range(1, 234, 4)),
        "default": 37
    }
}

# Preferred Scanning Channels: 6 GHz clients find these fastest.
PSC_CHANNELS = list(range(5, 234, 16))

# Frequency ranges (MHz) used to sort `iw phy` channels into bands.
BAND_FREQUENCIES = {
    "2.4": (2400, 2500),
    "5": (5150, 5900),
    "6": (5925, 7125)
}

SECURITY_MODES = (
    "wpa2",
    "wpa2-wpa3",
    "wpa3",
    "open"
)

DEFAULT_SETTINGS = {
    "enabled": False,
    "interface": "wlan0",
    "ssid": "Chaos Router",
    "password": "",
    "security": "wpa2",
    "band": "2.4",
    "channel": 6,
    "country": "DE",
    "hidden": False,
    "isolate_clients": False
}

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

# WPA passphrases are 8-63 printable ASCII characters.
PASSPHRASE_RE = re.compile(r"^[\x20-\x7e]{8,63}$")


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def which(name):

    return shutil.which(name, path=SBIN_PATH)


def has_hostapd():

    return which("hostapd") is not None


def is_hostapd_running():

    return run([
        "systemctl",
        "is-active",
        "hostapd"
    ]) == "active"


def get_wireless_interfaces():

    interfaces = []

    try:
        names = sorted(os.listdir("/sys/class/net"))
    except Exception:
        return interfaces

    for name in names:

        if os.path.exists(f"/sys/class/net/{name}/wireless"):
            interfaces.append(name)

    return interfaces


def get_band_support(interface):
    """
    Channels the interface's radio supports per band, from
    `iw phy <phy> info`. Returns None when it cannot be detected
    (no iw, no such interface), so callers fall back to BANDS.
    """

    iw = which("iw")

    try:
        with open(f"/sys/class/net/{interface}/phy80211/name") as f:
            phy = f.read().strip()
    except Exception:
        return None

    if not iw or not phy:
        return None

    output = run([iw, "phy", phy, "info"])

    if not output:
        return None

    support = {band: [] for band in BANDS}

    # e.g. "* 5955.0 MHz [1] (23.0 dBm)" or "* 6435 MHz [97] (disabled)"
    pattern = re.compile(r"\*\s+(\d+)(?:\.\d+)?\s+MHz\s+\[(\d+)\](.*)")

    for line in output.splitlines():

        match = pattern.search(line)

        if not match:
            continue

        freq = int(match.group(1))
        channel = int(match.group(2))

        # "no IR" can lift once hostapd sets the country, so only
        # channels the hardware disables outright are skipped.
        if "disabled" in match.group(3):
            continue

        for band, (low, high) in BAND_FREQUENCIES.items():

            if low <= freq <= high and channel in BANDS[band]["channels"]:
                support[band].append(channel)

    return support


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def get_wifi_settings():

    return load_settings(WIFI_SETTINGS, DEFAULT_SETTINGS)


def validate_wifi_settings(data):
    """
    Validates and normalises Wi-Fi settings.

    Returns (True, settings) or (False, message).
    """

    settings = get_wifi_settings()
    settings.update(data or {})

    enabled = settings.get("enabled") is True

    interface = str(settings.get("interface") or "").strip()

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
        return False, "Invalid interface."

    if enabled and interface not in get_wireless_interfaces():
        return False, f"{interface} is not a wireless interface."

    ssid = str(settings.get("ssid") or "")

    if not ssid.strip():
        return False, "Network name cannot be empty."

    if len(ssid.encode("utf-8")) > 32:
        return False, "Network name is too long (max 32 bytes)."

    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in ssid):
        return False, "Network name contains invalid characters."

    security = settings.get("security")

    if security not in SECURITY_MODES:
        return False, "Invalid security mode."

    password = str(settings.get("password") or "")

    if security != "open" and not PASSPHRASE_RE.fullmatch(password):
        return False, (
            "Password must be 8-63 characters "
            "(letters, numbers, symbols and spaces)."
        )

    band = str(settings.get("band"))

    if band not in BANDS:
        return False, "Invalid band."

    try:
        channel = int(settings.get("channel"))
    except (TypeError, ValueError):
        return False, "Invalid channel."

    if channel not in BANDS[band]["channels"]:
        return False, f"Channel {channel} is not available on {band} GHz."

    # 6 GHz only allows WPA3-SAE (open networks would need OWE).
    if band == "6" and security != "wpa3":
        return False, "6 GHz requires WPA3 Personal."

    if enabled:

        support = get_band_support(interface)

        if support is not None:

            if not support[band]:
                return False, f"{interface} does not support {band} GHz."

            if channel not in support[band]:
                return False, (
                    f"{interface} does not support channel "
                    f"{channel} on {band} GHz."
                )

    country = str(settings.get("country") or "").strip().upper()

    if not COUNTRY_RE.fullmatch(country):
        return False, "Country must be a two-letter code, e.g. DE or US."

    return True, {
        "enabled": enabled,
        "interface": interface,
        "ssid": ssid,
        "password": password if security != "open" else "",
        "security": security,
        "band": band,
        "channel": channel,
        "country": country,
        "hidden": settings.get("hidden") is True,
        "isolate_clients": settings.get("isolate_clients") is True
    }


# -------------------------------------------------------------------
# hostapd config
# -------------------------------------------------------------------

def render_hostapd_config(settings):

    band = BANDS[settings["band"]]

    lines = [
        "# Generated by Chaos Router OS. Do not edit by hand.",
        "# Changes are overwritten from the WiFi page.",
        "",
        f"interface={settings['interface']}",
        # One LAN: the access point joins the LAN bridge.
        *([f"bridge={BRIDGE}"] if get_network_settings()["lan"]["bridge"] else []),
        "driver=nl80211",
        "ctrl_interface=/var/run/hostapd",
        "ctrl_interface_group=0",
        "",
        # Hex form needs no escaping for any SSID characters.
        f"ssid2={settings['ssid'].encode('utf-8').hex()}",
        "utf8_ssid=1",
        f"ignore_broadcast_ssid={1 if settings['hidden'] else 0}",
        "",
        f"country_code={settings['country']}",
        "ieee80211d=1",
        f"hw_mode={band['hw_mode']}",
        f"channel={settings['channel']}",
        "wmm_enabled=1"
    ]

    if settings["band"] == "6":

        # 6 GHz is HE (802.11ax) only; HT/VHT are not used there.
        # Operating class 131 is 20 MHz.
        lines += [
            "op_class=131",
            "ieee80211ax=1"
        ]

    else:

        lines.append("ieee80211n=1")

        if settings["band"] == "5":
            lines.append("ieee80211ac=1")

    lines.append(f"ap_isolate={1 if settings['isolate_clients'] else 0}")

    security = settings["security"]

    if security != "open":

        key_mgmt = {
            "wpa2": "WPA-PSK",
            "wpa2-wpa3": "WPA-PSK SAE",
            "wpa3": "SAE"
        }[security]

        lines += [
            "",
            "auth_algs=1",
            "wpa=2",
            f"wpa_key_mgmt={key_mgmt}",
            "rsn_pairwise=CCMP",
            f"wpa_passphrase={settings['password']}"
        ]

        # WPA3 requires protected management frames.
        if security == "wpa3":
            lines.append("ieee80211w=2")
        elif security == "wpa2-wpa3":
            lines.append("ieee80211w=1")

        if security != "wpa2":
            lines.append(f"sae_password={settings['password']}")

        # 6 GHz only allows hash-to-element SAE.
        if settings["band"] == "6":
            lines.append("sae_pwe=1")

    return "\n".join(lines) + "\n"


def install_hostapd_config(content):

    fd, tmp = tempfile.mkstemp(
        prefix="chaos-hostapd-",
        suffix=".conf"
    )

    try:

        with os.fdopen(fd, "w") as f:
            f.write(content)

        ok, result = run_command(privileged([
            "mkdir",
            "-p",
            os.path.dirname(HOSTAPD_CONF_FILE)
        ]))

        if not ok:
            return False, result

        # 600: the file contains the Wi-Fi password.
        return run_command(privileged([
            "install",
            "-m",
            "600",
            tmp,
            HOSTAPD_CONF_FILE
        ]))

    finally:

        os.unlink(tmp)


def set_networkmanager_managed(interface, managed):
    """
    NetworkManager must leave the interface alone while hostapd
    runs the access point.
    """

    if not which("nmcli"):
        return True, "OK"

    return run_command(privileged([
        "nmcli",
        "device",
        "set",
        interface,
        "managed",
        "yes" if managed else "no"
    ]))


def get_hostapd_error():

    ok, output = run_command(privileged([
        "journalctl",
        "-u",
        "hostapd",
        "-n",
        "5",
        "--no-pager",
        "-o",
        "cat"
    ]))

    return output if ok and output else "hostapd failed to start."


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def save_wifi_settings(data):
    """
    Validates the settings, then applies them through safe apply.
    Returns a transaction result dict with the new settings.
    """

    ok, result = validate_wifi_settings(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(WIFI_SETTINGS, result)
    outcome["settings"] = get_wifi_settings()

    return outcome


def verify_wifi_settings():

    if not get_wifi_settings()["enabled"]:
        return True, "OK"

    return unit_stays_active("hostapd")


def apply_wifi_settings():
    """
    Applies the running Wi-Fi settings to hostapd.
    """

    settings = get_wifi_settings()

    if not has_hostapd():

        if not settings["enabled"]:
            return True, "Access point turned off."

        return False, "hostapd is not available."

    interface = settings["interface"]

    if not settings["enabled"]:

        for cmd in (
            ["systemctl", "stop", "hostapd"],
            ["systemctl", "disable", "hostapd"]
        ):
            ok, result = run_command(privileged(cmd))

            if not ok:
                return False, f"Wi-Fi settings could not be applied: {result}"

        set_networkmanager_managed(interface, True)

        return True, "Access point turned off."

    ok, result = install_hostapd_config(
        render_hostapd_config(settings)
    )

    if not ok:
        return False, f"Wi-Fi settings could not be applied: {result}"

    ok, result = set_networkmanager_managed(interface, False)

    if not ok:
        return False, (
            f"NetworkManager could not release {interface}: {result}"
        )

    commands = []

    # Raspberry Pi OS soft-blocks Wi-Fi until a country is set.
    if which("rfkill"):
        commands.append(["rfkill", "unblock", "wlan"])

    # The Debian package ships hostapd masked.
    commands += [
        ["systemctl", "unmask", "hostapd"],
        ["systemctl", "enable", "hostapd"],
        ["systemctl", "restart", "hostapd"]
    ]

    for cmd in commands:

        ok, result = run_command(privileged(cmd))

        if not ok:

            if cmd[-2:] == ["restart", "hostapd"]:
                result = get_hostapd_error()

            return False, f"Wi-Fi settings could not be applied: {result}"

    return True, "Access point applied."


# -------------------------------------------------------------------
# Clients
# -------------------------------------------------------------------

def get_wifi_clients(interface=None):
    """
    Parses `iw dev <iface> station dump` and matches hostnames
    from the DHCP leases.
    """

    interface = interface or get_wifi_settings()["interface"]

    iw = which("iw")

    if not iw or interface not in get_wireless_interfaces():
        return []

    ok, output = run_command(privileged([
        iw,
        "dev",
        interface,
        "station",
        "dump"
    ]))

    if not ok or not output:
        return []

    leases = {
        lease["mac"]: lease
        for lease in get_dhcp_leases()
    }

    clients = []
    current = None

    for line in output.splitlines():

        if line.startswith("Station "):

            mac = line.split()[1].upper()
            lease = leases.get(mac, {})

            current = {
                "mac": mac,
                "hostname": lease.get("hostname", ""),
                "ip": lease.get("ip", ""),
                "signal": None,
                "connected": None,
                "rx_bytes": 0,
                "tx_bytes": 0
            }

            clients.append(current)
            continue

        if not current or ":" not in line:
            continue

        key, value = line.strip().split(":", 1)
        value = value.strip()

        try:

            if key == "signal":
                current["signal"] = int(value.split()[0])
            elif key == "connected time":
                current["connected"] = int(value.split()[0])
            elif key == "rx bytes":
                current["rx_bytes"] = int(value)
            elif key == "tx bytes":
                current["tx_bytes"] = int(value)

        except (ValueError, IndexError):
            pass

    return clients


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def get_wifi_status():

    installed = has_hostapd()

    return {
        "installed": installed,
        "running": installed and is_hostapd_running(),
        "config_file": HOSTAPD_CONF_FILE
    }


def get_wifi_options():

    return {
        "bands": {
            band: {
                "channels": info["channels"],
                "default": info["default"]
            }
            for band, info in BANDS.items()
        },
        "psc_channels": PSC_CHANNELS,
        "security": list(SECURITY_MODES),
        # Per interface: channels per band, or null when unknown.
        "support": {
            interface: get_band_support(interface)
            for interface in get_wireless_interfaces()
        }
    }
