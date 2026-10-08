import subprocess
import re

from services.modem_detector import detect_modem
from services.config import load_settings
from services import transaction

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
    "rsrp", "rsrq", "sinr", "band",
    "lock", "pin_retries", "modem_state", "connection"
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
    state: "absent" (no modem), "not_ready" (modem found, no answer),
    "no_modemmanager" (modem found, ModemManager missing).
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

    has_mmcli = run(["which", "mmcli"]) is not None

    index = get_modem_index() if has_mmcli else None

    if index is None:

        if hardware["usb_id"]:
            return no_data(hardware, "not_ready" if has_mmcli else "no_modemmanager")

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
        "band": None,

        # "sim-pin" while the SIM waits for its PIN, "sim-puk" when it
        # is blocked; "none" or None when unlocked.
        "lock": field(r"\|\s+lock:\s+(\S+)"),
        "pin_retries": field(r"unlock retries:.*?sim-pin \((\d+)\)"),
        "modem_state": field(r"\|\s+state:\s+'?([a-z-]+)"),
        "connection": get_connection_state()
    }


# -------------------------------------------------------------------
# Mobile data (a NetworkManager connection) and the SIM PIN
# -------------------------------------------------------------------

MODEM_SETTINGS = "modem"

# NetworkManager connection for the modem; it brings the modem's
# data connection (wwan0) up at every start.
CONNECTION = "chaos-modem"

DEFAULT_SETTINGS = {
    # Off until switched on from the Modem page; an existing
    # connection of the user's own is left alone until then.
    "enabled": False,
    # Empty: NetworkManager picks the carrier's APN by itself.
    "apn": "",
    "username": "",
    "password": "",
    "roaming": False,
    # Only stored after it unlocked the SIM (see unlock_sim).
    "pin": ""
}

APN_RE = re.compile(r"^[A-Za-z0-9._-]{0,100}$")
PIN_RE = re.compile(r"^\d{4,8}$")


def privileged(cmd):

    from services.network import privileged as wrap
    return wrap(cmd)


def run_command(cmd):

    from services.network import run_command as runner
    return runner(cmd)


def get_modem_settings():

    settings = load_settings(MODEM_SETTINGS, DEFAULT_SETTINGS)

    return {key: settings.get(key, DEFAULT_SETTINGS[key]) for key in DEFAULT_SETTINGS}


def public_settings():
    """
    The settings for the page: the PIN and password are never sent
    back, only whether they are set.
    """

    settings = get_modem_settings()

    return {
        **{k: v for k, v in settings.items() if k not in ("pin", "password")},
        "pin_saved": bool(settings["pin"]),
        "password_saved": bool(settings["password"])
    }


def validate_modem_settings(data):

    settings = get_modem_settings()

    data = dict(data or {})

    # The page leaves the password empty to keep the saved one.
    if data.get("password") in (None, "") and not data.get("clear_password"):
        data.pop("password", None)

    data.pop("clear_password", None)

    # The PIN is only set through unlock_sim (or forgotten).
    if data.get("forget_pin"):
        data["pin"] = ""
    else:
        data.pop("pin", None)

    data.pop("forget_pin", None)

    settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})

    if not isinstance(settings["enabled"], bool) or not isinstance(settings["roaming"], bool):
        return False, "Invalid value."

    apn = str(settings["apn"] or "").strip()

    if not APN_RE.fullmatch(apn):
        return False, "Invalid APN: letters, numbers, dots and dashes only."

    username = str(settings["username"] or "")
    password = str(settings["password"] or "")

    for value in (username, password):
        if len(value) > 100 or any(ord(c) < 0x20 for c in value):
            return False, "Invalid username or password."

    pin = str(settings["pin"] or "")

    if pin and not PIN_RE.fullmatch(pin):
        return False, "Invalid PIN."

    return True, {
        "enabled": settings["enabled"],
        "apn": apn,
        "username": username,
        "password": password,
        "roaming": settings["roaming"],
        "pin": pin
    }


def validate_stored_settings(data):
    """
    Saved settings as they are (a backup): the PIN and password are
    kept, not taken from the page's rules.
    """

    data = {**DEFAULT_SETTINGS, **{k: v for k, v in (data or {}).items() if k in DEFAULT_SETTINGS}}

    pin, password = str(data["pin"] or ""), str(data["password"] or "")

    ok, result = validate_modem_settings({
        k: v for k, v in data.items() if k not in ("pin", "password")
    })

    if not ok:
        return False, result

    if pin and not PIN_RE.fullmatch(pin):
        return False, "Invalid PIN."

    if len(password) > 100 or any(ord(c) < 0x20 for c in password):
        return False, "Invalid password."

    return True, {**result, "pin": pin, "password": password}


def save_modem_settings(data):

    ok, result = validate_modem_settings(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(MODEM_SETTINGS, result)
    outcome["settings"] = public_settings()

    return outcome


def has_nmcli():

    return run(["which", "nmcli"]) is not None


def connection_exists():

    output = run(["nmcli", "-t", "-f", "NAME", "connection", "show"]) or ""

    return CONNECTION in output.splitlines()


def get_connection_state():
    """
    "activated", "activating", "deactivated"... of the chaos-modem
    connection, or None without one.
    """

    if not has_nmcli():
        return None

    output = run(["nmcli", "-t", "-f", "NAME,STATE", "connection", "show", "--active"]) or ""

    for line in output.splitlines():

        name, _, state = line.rpartition(":")

        if name == CONNECTION:
            return state or "activated"

    return "deactivated" if connection_exists() else None


def connection_properties(settings, auto_config=True):

    props = [
        "connection.autoconnect", "yes",
        # Retry for ever: the signal may come and go.
        "connection.autoconnect-retries", "0",
        "gsm.home-only", "no" if settings["roaming"] else "yes",
        "gsm.username", settings["username"],
        "gsm.password", settings["password"],
        "gsm.password-flags", "0",
        "gsm.pin", settings["pin"],
        "gsm.pin-flags", "0",
        "ipv4.method", "auto",
        "ipv6.method", "auto"
    ]

    if settings["apn"]:
        props += ["gsm.apn", settings["apn"]]
        if auto_config:
            props += ["gsm.auto-config", "no"]
    else:
        props += ["gsm.apn", ""]
        # NetworkManager 1.42+: the APN from the carrier database.
        if auto_config:
            props += ["gsm.auto-config", "yes"]

    return props


def apply_modem_settings():
    """
    Creates, updates or removes the chaos-modem connection. A missing
    signal is not an error: the connection comes up when it can.
    """

    settings = get_modem_settings()

    if not has_nmcli():

        if not settings["enabled"]:
            return True, "Mobile data off."

        return False, "NetworkManager (nmcli) is not available."

    if not settings["enabled"]:

        if connection_exists():

            ok, result = run_command(privileged(["nmcli", "connection", "delete", CONNECTION]))

            if not ok:
                return False, f"The modem connection could not be removed: {result}"

        return True, "Mobile data off."

    def write(auto_config):

        if connection_exists():
            return run_command(privileged([
                "nmcli", "connection", "modify", CONNECTION,
                *connection_properties(settings, auto_config)
            ]))

        return run_command(privileged([
            "nmcli", "connection", "add", "type", "gsm", "ifname", "*",
            "con-name", CONNECTION,
            *connection_properties(settings, auto_config)
        ]))

    ok, result = write(auto_config=True)

    # Older NetworkManager without gsm.auto-config.
    if not ok and "auto-config" in str(result):
        ok, result = write(auto_config=False)

    if not ok:
        return False, f"The modem connection could not be saved: {result}"

    up, message = run_command(privileged(["nmcli", "--wait", "20", "connection", "up", CONNECTION]))

    if not up:
        return True, f"Mobile data on; not connected yet ({str(message).strip()[:200]}). It connects by itself when it can."

    return True, "Mobile data connected."


def get_sim_path(index):

    info = run(["mmcli", "-m", index]) or ""

    match = re.search(r"primary sim path:\s+(\S+)", info) or re.search(r"/SIM/(\d+)", info)

    if not match:
        return None

    value = match.group(1)

    return value.rsplit("/", 1)[-1] if "/" in value else value


def unlock_sim(pin, remember=True):
    """
    Sends the PIN once (never retried: three wrong PINs block the SIM).
    Returns {"success", "message", "retries"}.
    """

    pin = str(pin or "").strip()

    if not PIN_RE.fullmatch(pin):
        return {"success": False, "message": "The PIN has 4 to 8 digits."}

    index = get_modem_index()

    if index is None:
        return {"success": False, "message": "No modem found."}

    data = get_modem_data()

    if data.get("lock") == "sim-puk":
        return {"success": False, "message": "The SIM is blocked (PUK required). Unblock it in a phone first."}

    if data.get("lock") not in ("sim-pin",):
        return {"success": False, "message": "The SIM does not ask for a PIN."}

    sim = get_sim_path(index)

    if sim is None:
        return {"success": False, "message": "No SIM found."}

    ok, result = run_command(privileged(["mmcli", "-i", sim, f"--pin={pin}"]))

    after = get_modem_data()

    if not ok:
        retries = after.get("pin_retries")
        return {
            "success": False,
            "message": "Wrong PIN." + (f" {retries} attempts left." if retries else ""),
            "retries": retries
        }

    if remember:

        settings = get_modem_settings()
        settings["pin"] = pin

        # Recorded without re-applying: the SIM is unlocked already;
        # the connection gets the PIN the next time it is applied.
        transaction.change(MODEM_SETTINGS, settings, apply=False)

        if settings["enabled"]:
            apply_modem_settings()

    return {"success": True, "message": "SIM unlocked."}
