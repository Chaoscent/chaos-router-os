"""
Writes the default settings to /etc/chaos-router-os.

The app itself never writes there; run this from the installer:

    sudo .venv/bin/python backend/install_defaults.py [--force]

Existing files are kept unless --force is given, so local edits to
the defaults survive updates.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Only the built-in defaults are needed; do not apply any config.
os.environ["CHAOS_SKIP_STARTUP"] = "1"

import app
import auth

from services import dhcp, wifi, wireguard, openvpn, routing, firewall
from services.config import DEFAULTS_DIR, defaults_path, save_json


def get_defaults():

    # Keys are generated per router, never shipped as defaults.
    wireguard_server = {
        k: v for k, v in wireguard.DEFAULT_SERVER.items()
        if k not in ("private_key", "public_key")
    }

    return {
        "dashboard": app.BUILTIN_DASHBOARD,
        "security": auth.BUILTIN_SECURITY,
        "firewall": firewall.DEFAULT_SETTINGS,
        "routing": routing.DEFAULT_SETTINGS,
        "dhcp": dhcp.DEFAULT_SETTINGS,
        "wifi": wifi.DEFAULT_SETTINGS,
        "wireguard": {"server": wireguard_server},
        "openvpn": {"server": openvpn.DEFAULT_SERVER}
    }


def main():

    force = "--force" in sys.argv

    DEFAULTS_DIR.mkdir(parents=True, exist_ok=True)

    for name, data in get_defaults().items():

        path = defaults_path(name)

        if os.path.exists(path) and not force:
            print(f"kept     {path}")
            continue

        save_json(path, data)

        print(f"written  {path}")


if __name__ == "__main__":
    main()
