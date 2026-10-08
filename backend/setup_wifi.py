"""
Shows the setup Wi-Fi's name, password and QR code in the terminal:

    python backend/setup_wifi.py

Scan the QR code with a phone to join; the setup page opens by itself.
The installer runs this at the end. Only works while the router is
not set up (after setup the setup Wi-Fi is gone).
"""

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.config import load_persistent, load_system
from services.setup_network import SETUP_WIFI, ADDRESS, qr_payload, pick_interface


def main():

    if load_persistent("users", None):
        print("The router is already set up; there is no setup Wi-Fi.")
        return 1

    if not pick_interface():
        print("This router has no Wi-Fi, so there is no setup Wi-Fi.")
        print("Open http://chaos-router.local/setup from a computer on the LAN.")
        return 1

    credentials = load_system(SETUP_WIFI, None)

    if not credentials:
        print("The setup Wi-Fi has not been started yet. Start the app first.")
        return 1

    print()
    print(f"  Wi-Fi name:  {credentials['ssid']}")
    print(f"  Password:    {credentials['password']}")
    print(f"  Then open:   http://{ADDRESS}/setup (opens by itself on most phones)")
    print()

    payload = qr_payload(credentials)

    if shutil.which("qrencode"):
        subprocess.run(["qrencode", "-t", "ansiutf8", "-m", "2", payload])
    else:
        print("  Install qrencode for a QR code: sudo apt install qrencode")

    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
