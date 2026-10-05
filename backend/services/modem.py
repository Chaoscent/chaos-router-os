import subprocess
import re

from services.modem_detector import detect_modem

SIGNAL_ENABLED = False


def run(cmd):
    try:
        return subprocess.check_output(cmd, text=True)
    except:
        return None


def enable_signal_polling(index):
    global SIGNAL_ENABLED

    if SIGNAL_ENABLED:
        return

    run(["mmcli", "-m", index, "--signal-setup=5"])
    SIGNAL_ENABLED = True


def parse(pattern, text, default="Unknown"):
    if not text:
        return default

    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


# Values that are not known are None; the pages show them as "--".
UNKNOWN_FIELDS = (
    "carrier", "network", "signal", "imei", "sim",
    "rsrp", "rsrq", "sinr", "band"
)


def get_modem_index():
    """
    The first modem ModemManager knows, e.g. "0", or None.
    """

    output = run(["mmcli", "-L"])

    match = re.search(r"/Modem/(\d+)", output or "")

    return match.group(1) if match else None


def signal_values(text):
    """
    rsrp / rsrq / sinr from `mmcli --signal-get`, which lists one
    section per technology ("LTE  | rsrp: -90.00 dBm", "5G | ...").
    5G values win over LTE (5G NSA reports both).
    """

    sections = {}
    current = None

    for line in (text or "").splitlines():

        head, sep, rest = line.partition("|")

        if not sep:
            continue

        if head.strip():
            current = head.strip().lower()

        match = re.match(r"\s*([\w/]+):\s*'?(-?\d+(?:\.\d+)?)", rest)

        if current and match:
            sections.setdefault(current, {})[match.group(1).lower()] = match.group(2)

    values = {}

    for tech in ("lte", "5g"):

        found = sections.get(tech, {})

        for key, names in (("rsrp", ("rsrp",)), ("rsrq", ("rsrq",)), ("sinr", ("s/n", "snr", "sinr"))):

            for name in names:
                if name in found:
                    values[key] = found[name]

    return values


# ModemManager access technologies -> what people know them as.
ACCESS_TECH = {
    "5gnr": "5G",
    "lte": "LTE",
    "umts": "3G",
    "hsdpa": "3G",
    "hsupa": "3G",
    "hspa": "3G",
    "hspa-plus": "3G+",
    "edge": "2G",
    "gprs": "2G",
    "gsm": "2G"
}


def format_access_tech(value):
    """
    "lte, 5gnr" -> "5G NSA", "5gnr" -> "5G SA", "lte" -> "LTE".
    """

    if not value:
        return None

    techs = [t.strip().lower() for t in value.split(",") if t.strip()]

    if "5gnr" in techs:
        return "5G NSA" if "lte" in techs else "5G SA"

    for tech in techs:
        if tech in ACCESS_TECH:
            return ACCESS_TECH[tech]

    return value


def no_data(hardware, state, model=None):
    """
    Honest placeholder: which modem (if any) and why there is no data.
    state: "absent" (no modem), "not_ready" (modem found, no answer).
    """

    return {
        "state": state,
        "vendor": hardware["vendor"],
        "model": model or hardware["model"],
        "usb_id": hardware["usb_id"],
        **{field: None for field in UNKNOWN_FIELDS}
    }


def get_modem_data():
    """
    Live modem data from ModemManager. "state" is "ready", "not_ready"
    (a modem is there but does not answer yet) or "absent".
    """

    hardware = detect_modem()

    index = get_modem_index() if run(["which", "mmcli"]) is not None else None

    if index is None:

        if hardware["usb_id"]:
            return no_data(hardware, "not_ready")

        return no_data(hardware, "absent", model="No modem")

    enable_signal_polling(index)

    info = run(["mmcli", "-m", index])
    signal = run(["mmcli", "-m", index, "--signal-get"])

    if info is None:
        return no_data(hardware, "not_ready")

    def field(pattern, text=info):
        value = parse(pattern, text, None)
        return value if value not in ("--", "") else None

    radio = signal_values(signal)

    return {
        "state": "ready",
        "vendor": hardware["vendor"] if hardware["usb_id"] else field(r"manufacturer:\s+(.+)"),
        "model": hardware["model"] if hardware["usb_id"] else field(r"model:\s+(.+)"),
        "usb_id": hardware["usb_id"],

        "carrier": field(r"operator name:\s+(.+)"),
        "network": format_access_tech(field(r"access tech:\s+(.+)")),
        "signal": field(r"signal quality:\s+'?(\d+)"),
        "imei": field(r"equipment id:\s+(.+)"),
        "sim": field(r"SIM\s+\|.*?state:\s+(.+)"),

        "rsrp": radio.get("rsrp"),
        "rsrq": radio.get("rsrq"),
        "sinr": radio.get("sinr"),

        # ModemManager does not report the active band.
        "band": None
    }
