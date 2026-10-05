import os
import shutil
import socket
import subprocess
import threading
import time
import psutil
from datetime import datetime

from services.network import privileged, run_command


def get_hostname():
    return socket.gethostname()


def set_hostname(hostname):
    """
    Change the system hostname.

    Priority:
    1. hostnamectl (real Raspberry Pi deployment)
    2. hostname (WSL/dev fallback)

    Returns (success, message)
    """

    hostname = hostname.strip()

    if not hostname:
        return False, "Hostname cannot be empty."

    if len(hostname) > 63:
        return False, "Hostname is too long."

    # --- Preferred: systemd hostnamectl ---
    try:

        cmd = ["hostnamectl", "set-hostname", hostname]

        if os.geteuid() == 0:
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            subprocess.run(["sudo", "-n"] + cmd, check=True, capture_output=True)

        return True, hostname

    except Exception:
        pass

    # --- Development fallback (WSL/Linux) ---
    try:

        cmd = ["hostname", hostname]

        if os.geteuid() == 0:
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            subprocess.run(["sudo", "-n"] + cmd, check=True, capture_output=True)

        return True, hostname

    except Exception:
        return False, (
            "Permission denied. "
            "Hostname changes require elevated privileges."
        )


def get_ip():

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "Unknown"


def get_uptime():

    uptime = int(psutil.boot_time())
    seconds = int(datetime.now().timestamp()) - uptime

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    return f"{hours}h {minutes}m"


def get_cpu_temp():

    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read())/1000:.1f}°C"
    except:
        return "--"


def get_ram():
    return f"{psutil.virtual_memory().percent:.1f}%"


# Primes psutil: the first non-blocking reading is always 0.
psutil.cpu_percent(interval=None)


def get_cpu_load():
    """
    CPU load in % across all cores since the previous call (the
    dashboard asks every second), without blocking the request.
    """

    return f"{psutil.cpu_percent(interval=None):.0f}%"


def get_time():
    return datetime.now().strftime("%H:%M:%S")


def get_ping(destination="1.1.1.1"):

    try:

        destination = str(destination).strip()

        if not destination:
            return "-- ms"

        out = subprocess.check_output(
            [
                "ping",
                "-4",
                "-c",
                "1",
                "-W",
                "1",
                destination
            ],
            text=True
        )

        return out.split("time=")[1].split()[0] + " ms"

    except Exception:
        return "-- ms"

# -------------------------------------------------------------------
# Reboot
# -------------------------------------------------------------------

# Time for the browser to receive the answer before the router goes down.
REBOOT_DELAY = 2


def can_reboot():
    """
    (True, "OK") or (False, why): systemd is there and the app may run
    `systemctl reboot` (as root or through passwordless sudo).
    """

    if not shutil.which("systemctl"):
        return False, "systemctl is not available."

    if os.geteuid() == 0:
        return True, "OK"

    # Lists the permission without running anything.
    ok, _ = run_command(["sudo", "-n", "-l", "systemctl", "reboot"])

    if not ok:
        return False, "The app is not allowed to reboot (passwordless sudo for systemctl is missing)."

    return True, "OK"


def reboot_system():
    """
    Reboots after REBOOT_DELAY seconds, so the request can still be
    answered. Unconfirmed changes are reverted by the reboot, because
    the running config is rebuilt from /var/lib.
    Returns (success, message).
    """

    ok, message = can_reboot()

    if not ok:
        return False, message

    def reboot_later():

        time.sleep(REBOOT_DELAY)

        ok, result = run_command(privileged(["systemctl", "reboot"]))

        if not ok:

            from services.logs import log_event

            log_event("system", f"Reboot failed: {result}", "error")

    threading.Thread(target=reboot_later, name="reboot", daemon=True).start()

    return True, "The router is rebooting."
