import socket
import psutil
import time
from datetime import datetime


def get_hostname():
    return socket.gethostname()


def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "Unavailable"


def get_uptime():
    uptime = time.time() - psutil.boot_time()

    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)

    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read()) / 1000, 1)
    except:
        return None


def get_ram():
    return psutil.virtual_memory().percent


def get_time():
    return datetime.now().strftime("%H:%M:%S")
