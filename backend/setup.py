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
"""

import re
import threading

from werkzeug.security import generate_password_hash

from services.config import load_persistent

from services import transaction, wifi

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


def get_setup_info():
    """
    What the setup page needs to offer the Wi-Fi step.
    """

    settings = wifi.get_wifi_settings()
    interfaces = wifi.get_wireless_interfaces()

    return {
        "wifi": {
            "available": bool(interfaces) and wifi.has_hostapd(),
            "interfaces": interfaces,
            "interface": settings["interface"] if settings["interface"] in interfaces
                         else (interfaces[0] if interfaces else settings["interface"]),
            "ssid": settings["ssid"],
            "country": settings["country"]
        }
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

    return wifi.validate_wifi_settings({
        "enabled": True,
        "interface": data.get("interface"),
        "ssid": data.get("ssid"),
        "password": data.get("password"),
        "country": str(data.get("country") or "").upper(),
        # Works with every device; WPA3 can be chosen on the WiFi page.
        "security": "wpa2",
        "band": "2.4",
        "channel": wifi.BANDS["2.4"]["default"]
    })


def complete_setup(data):
    """
    Returns (True, username) or (False, message).
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

        if wifi_settings:

            # No confirmation: the browser may be on the old network.
            # A network that fails to start is rolled back instead.
            outcome = transaction.change(wifi.WIFI_SETTINGS, wifi_settings, confirm=False)

            if not outcome["success"]:
                return False, f"Wi-Fi could not be started: {outcome['message']}"

        outcome = transaction.change(USERS, {
            username: {"password": generate_password_hash(data["admin"]["password"])}
        })

        if not outcome["success"]:
            return False, f"The account could not be saved: {outcome['message']}"

        log_event("setup", f"Setup complete. Admin account '{username}' created"
                  + (f", Wi-Fi '{wifi_settings['ssid']}' started." if wifi_settings else "."))

        return True, username
