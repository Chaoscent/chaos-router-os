"""
First-time setup (/setup).

The router is "not set up" while /var/lib/chaos-router-os holds no
admin account: right after installing, and again after a factory
reset (which empties /var/lib). There is no default login. Until
setup is complete, every page and API except /setup answers with
"not set up"; afterwards /setup is gone (404).

Setup creates the admin account and optionally the Wi-Fi network.
Wi-Fi is applied first, so a failure leaves the router in setup
mode and the user can fix it and try again.

While not set up, the setup Wi-Fi (services/setup_network.py) runs on
10.42.0.0/24 with a captive portal. A Wi-Fi network created here keeps
that subnet: 10.42.0.1 on the radio, DHCP 10.42.0.100-200.
"""

import re
import threading
import time

from werkzeug.security import generate_password_hash

from services.config import load_persistent

from services import transaction, wifi, dhcp, setup_network

from services.caddy import dashboard_url

from services.logs import log_event

USERS = "users"

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")

MIN_PASSWORD = 8
MAX_PASSWORD = 128

_lock = threading.Lock()

# Once complete, setup stays complete until the app restarts (a
# factory reset reboots the router).
_complete = False


def is_setup_complete():

    global _complete

    if _complete:
        return True

    users = load_persistent(USERS, None)

    _complete = isinstance(users, dict) and bool(users)

    return _complete


def get_setup_info(viewer_ip=None):
    """
    What the setup page needs to offer the Wi-Fi step.
    """

    interfaces = wifi.get_wireless_interfaces()

    # The radio the setup Wi-Fi runs on.
    interface = setup_network.pick_interface() or (interfaces[0] if interfaces else "wlan0")

    network = wifi.get_network(interface)

    return {
        "wifi": {
            "available": bool(interfaces) and wifi.has_hostapd(),
            "interfaces": interfaces,
            "interface": interface,
            "ssid": network["ssid"],
            "country": network["country"]
        },
        # This browser is on the setup Wi-Fi: skipping Wi-Fi ends its
        # connection, and a new Wi-Fi replaces the network it is on.
        "via_setup_wifi": bool(viewer_ip) and setup_network.is_on_setup_network(viewer_ip),
        # Behind Caddy on port 80; without it the portal's port-80
        # redirect is gone after setup, so the app's own port.
        "dashboard_url": dashboard_url(setup_network.ADDRESS)
    }


def validate_admin(data):

    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")

    if not USERNAME_RE.fullmatch(username):
        return False, "Username: 1-32 letters, numbers, dots, dashes or underscores."

    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return False, f"Password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters."

    if password.lower() in (username.lower(), "password", "12345678", "admin123"):
        return False, "Choose a password that is harder to guess."

    return True, username


def validate_wifi(data):
    """
    (True, settings or None) - None when Wi-Fi is skipped.
    """

    if not data or data.get("enabled") is not True:
        return True, None

    return wifi.validate_network({
        "enabled": True,
        "interface": data.get("interface"),
        "ssid": data.get("ssid"),
        "password": data.get("password"),
        "country": str(data.get("country") or "").upper(),
        # Works with every device; WPA3 can be chosen on the WiFi page.
        "security": "wpa2",
        "band": "2.4",
        "channel": wifi.BANDS["2.4"]["default"],
        # Same subnet as the setup Wi-Fi.
        "address": setup_network.ADDRESS,
        "prefix": setup_network.PREFIX
    })


def stop_setup_wifi_later(keep_access_point):
    """
    After the answer reached the browser (which may be on the setup
    Wi-Fi), remove the captive portal and, without new Wi-Fi, the
    setup network itself.
    """

    def run():
        time.sleep(3)
        setup_network.stop(keep_access_point=keep_access_point)

    threading.Thread(target=run, name="setup-wifi-stop", daemon=True).start()


def complete_setup(data):
    """
    Returns (True, {"username", "warning"}) or (False, message).
    """

    with _lock:

        if is_setup_complete():
            return False, "The router is already set up."

        ok, username = validate_admin(data.get("admin") or {})

        if not ok:
            return False, username

        ok, wifi_settings = validate_wifi(data.get("wifi"))

        if not ok:
            return False, f"Wi-Fi: {wifi_settings}"

        warning = None

        if wifi_settings:

            # No confirmation: the browser may be on the old network.
            # A network that fails to start is rolled back instead.
            outcome = transaction.change(
                wifi.WIFI_SETTINGS,
                wifi.with_network(wifi.get_wifi_settings(), wifi_settings),
                confirm=False
            )

            if not outcome["success"]:

                # The rollback stopped the radio: bring the setup Wi-Fi back.
                setup_network.start()

                return False, f"Wi-Fi could not be started: {outcome['message']}"

            # The real Wi-Fi now runs on the radio; drop the portal
            # before DHCP is set up for the same subnet.
            setup_network.stop(keep_access_point=True)

            # The setup Wi-Fi's range (.100-.200) on the same subnet.
            outcome = dhcp.follow_wifi(
                wifi_settings["interface"],
                wifi_settings["address"],
                wifi_settings["prefix"],
                confirm=False
            )

            if outcome and not outcome["success"]:

                # Setup still completes (the account is what matters), but
                # the page shows why devices get no address.
                warning = f"DHCP for the new Wi-Fi could not be started: {outcome['message']}"

                log_event("setup", warning, "warning")

        outcome = transaction.change(USERS, {
            username: {"password": generate_password_hash(data["admin"]["password"])}
        })

        if not outcome["success"]:
            return False, f"The account could not be saved: {outcome['message']}"

        log_event("setup", f"Setup complete. Admin account '{username}' created"
                  + (f", Wi-Fi '{wifi_settings['ssid']}' started." if wifi_settings else "."))

        if not wifi_settings:
            stop_setup_wifi_later(keep_access_point=False)

        return True, {"username": username, "warning": warning}
