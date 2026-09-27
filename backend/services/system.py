import os
import socket
import subprocess
import psutil
from datetime import datetime


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


def get_time():
    return datetime.now().strftime("%H:%M:%S")


def get_ping():

    try:

        out = subprocess.check_output(
            ["ping", "-c", "1", "-W", "1", "1.1.1.1"],
            text=True
        )

        return out.split("time=")[1].split()[0] + " ms"

    except:
        return "-- ms"