import subprocess
import re

from services.modem_detector import detect_modem

SIGNAL_ENABLED = False


def run(cmd):
    try:
        return subprocess.check_output(cmd, text=True)
    except:
        return None


def enable_signal_polling():
    global SIGNAL_ENABLED

    if SIGNAL_ENABLED:
        return

    run(["mmcli", "-m", "0", "--signal-setup=5"])
    SIGNAL_ENABLED = True


def parse(pattern, text, default="Unknown"):
    if not text:
        return default

    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


def get_modem_data():
    hardware = detect_modem()

    if run(["which", "mmcli"]) is None:
        return mock(hardware)

    if run(["mmcli", "-L"]) is None:
        return mock(hardware)

    enable_signal_polling()

    info = run(["mmcli", "-m", "0"])
    signal = run(["mmcli", "-m", "0", "--signal-get"])

    if info is None:
        return mock(hardware)

    return {
        "vendor": hardware["vendor"],
        "model": hardware["model"],
        "usb_id": hardware["usb_id"],

        "carrier": parse(r"operator name:\s+(.+)", info, "No Carrier"),
        "network": parse(r"access tech:\s+(.+)", info, "Disconnected"),
        "signal": parse(r"signal quality:\s+'?(\d+)", info, "0"),
        "imei": parse(r"equipment id:\s+(.+)", info),
        "sim": parse(r"SIM\s+\|.*?state:\s+(.+)", info, "Unknown"),

        "rsrp": parse(r"RSRP:\s+'?(-?\d+\.\d+|-?\d+)", signal, "--"),
        "rsrq": parse(r"RSRQ:\s+'?(-?\d+\.\d+|-?\d+)", signal, "--"),
        "sinr": parse(r"(?:SNR|SINR):\s+'?(-?\d+\.\d+|-?\d+)", signal, "--"),

        "band": "Auto"
    }


def mock(hardware):
    return {
        "vendor": hardware["vendor"],
        "model": hardware["model"],
        "usb_id": hardware["usb_id"],

        "carrier": "Chaos Mock",
        "network": "5G NSA",
        "signal": "92",
        "imei": "866123456789012",
        "sim": "Ready",
        "rsrp": "-68",
        "rsrq": "-9",
        "sinr": "22",
        "band": "n78"
    }