import os
import subprocess
import re
import threading

from services.modem_detector import detect_modem
from services.config import load_settings
from services import transaction

SIGNAL_ENABLED = False


def run(cmd):
    try:
        return subprocess.check_output(cmd, text=True)
    except:
        return None


def privileged(cmd):

    from services.network import privileged as wrap
    return wrap(cmd)


def run_command(cmd):

    from services.network import run_command as runner
    return runner(cmd)


def enable_signal_polling(index):
    """
    Signal values (RSRP, RSRQ, SINR) are only measured after this, and
    ModemManager only allows it as root. Retried until it worked.
    """

    global SIGNAL_ENABLED

    if SIGNAL_ENABLED:
        return

    ok, _ = run_command(privileged(["mmcli", "-m", index, "--signal-setup=5"]))

    SIGNAL_ENABLED = ok


def parse(pattern, text, default="Unknown"):
    if not text:
        return default

    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


# Values that are not known are None; the pages show them as "--".
UNKNOWN_FIELDS = (
    "carrier", "network", "signal", "imei", "sim",
    "rsrp", "rsrq", "sinr", "band",
    "lock", "pin_retries", "modem_state", "connection",
    "usb_mode", "ipv4", "ipv6", "rx_packets", "rx_errors", "data_dropped"
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


# Locks that keep the SIM from working. Others, like sim-pin2 (the
# second PIN, only for fixed dialing numbers), do not.
BLOCKING_LOCKS = ("sim-pin", "sim-puk", "ph-sim-pin", "ph-net-pin")


def sim_status(lock, state):
    """
    "Waiting for PIN", "Blocked (PUK)", "Ready" or None (unknown).
    """

    if lock in ("sim-pin", "ph-sim-pin", "ph-net-pin"):
        return "Waiting for PIN"

    if lock == "sim-puk":
        return "Blocked (PUK)"

    if state in ("failed",):
        return "Failed"

    if state in (
        "enabled", "searching", "registered",
        "connecting", "connected", "disconnecting"
    ):
        return "Ready"

    return None


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
        **{field: None for field in UNKNOWN_FIELDS},
        # Also while the modem restarts after a USB mode switch.
        **data_link(hardware)
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

    ok, signal = run_command(privileged(["mmcli", "-m", index, "--signal-get"]))

    if not ok:
        signal = None

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
        "sim": sim_status(field(r"\|\s+lock:\s+(\S+)"), field(r"\|\s+state:\s+'?([a-z-]+)")),

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
        "connection": get_connection_state(),

        **data_link(hardware)
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


def connection_properties(settings, apn_mode="auto", apn=None):
    """
    nmcli properties of the chaos-modem connection. apn_mode: "auto"
    (the carrier's APN from NetworkManager's database), "given" (apn),
    or "legacy" (NetworkManager without gsm.auto-config).
    """

    props = [
        "connection.autoconnect", "yes",
        # NetworkManager's default: a few attempts, then a pause of
        # minutes before the next ones. 0 (for ever) retries without any
        # pause, hundreds of times a minute, which carriers may punish.
        "connection.autoconnect-retries", "-1",
        "gsm.home-only", "no" if settings["roaming"] else "yes",
        "gsm.username", settings["username"],
        "gsm.password", settings["password"],
        "gsm.password-flags", "0",
        "gsm.pin", settings["pin"],
        "gsm.pin-flags", "0",
        "ipv4.method", "auto",
        "ipv6.method", "auto"
    ]

    if apn_mode == "auto":
        props += ["gsm.apn", "", "gsm.auto-config", "yes"]
    elif apn_mode == "given":
        props += ["gsm.apn", apn or "", "gsm.auto-config", "no"]
    else:
        props += ["gsm.apn", apn or ""]

    return props


def network_apn():
    """
    The APN the network gave the modem when it attached (its initial
    bearer), e.g. "internet.telekom"; None when it reports none.
    """

    index = get_modem_index()

    if index is None:
        return None

    info = run(["mmcli", "-m", index]) or ""

    match = re.search(r"initial bearer path:\s+\S*/Bearer/(\d+)", info)

    if not match:
        return None

    bearer = run(["mmcli", "-b", match.group(1)]) or ""

    apn = parse(r"\|\s+apn:\s+(\S+)", bearer, None)

    # IMS (calls over LTE) and SOS (emergency calls) carry no internet;
    # with VoLTE, the modem often attaches with IMS.
    if not apn or apn == "--" or apn.lower() in ("ims", "sos") or not APN_RE.fullmatch(apn):
        return None

    return apn


def short_error(message):
    """
    NetworkManager's error without its "Hint: use journalctl ..." tail.
    """

    message = str(message or "").strip()

    message = re.split(r"\s*Hint: use ", message)[0].strip()

    return message.removeprefix("Error: ")[:200]


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

    def write(apn_mode, apn=None):

        props = connection_properties(settings, apn_mode, apn)

        if connection_exists():
            return run_command(privileged([
                "nmcli", "connection", "modify", CONNECTION, *props
            ]))

        return run_command(privileged([
            "nmcli", "connection", "add", "type", "gsm", "ifname", "*",
            "con-name", CONNECTION, *props
        ]))

    def up():
        return run_command(privileged(["nmcli", "--wait", "25", "connection", "up", CONNECTION]))

    # The APNs to try: the one entered; otherwise the carrier's from
    # NetworkManager's database (can be outdated), then the one the
    # network gave the modem, then none: the network's default for the
    # SIM, which works with plans whose APN isn't in the database.
    if settings["apn"]:
        attempts = [("given", settings["apn"])]
    else:
        attempts = [("auto", None)]
        given = network_apn()
        if given:
            attempts.append(("given", given))
        attempts.append(("given", ""))

    message = ""

    for apn_mode, apn in attempts:

        ok, result = write(apn_mode, apn)

        # Older NetworkManager without gsm.auto-config.
        if not ok and "auto-config" in str(result):
            ok, result = write("legacy", apn)

        if not ok:
            return False, f"The modem connection could not be saved: {short_error(result)}"

        connected, message = up()

        if connected:
            used = apn if apn_mode == "given" and apn else None
            return True, "Mobile data connected" + (f" (APN {used})." if used else ".")

        # A SIM or registration problem fails every APN alike.
        if any(word in str(message) for word in ("SIM", "PIN", "not registered")):
            break

    return True, (
        f"Mobile data on, not connected yet: {short_error(message)}. "
        f"It connects by itself when it can; if it never does, enter your carrier's APN."
    )


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

    if data.get("lock") != "sim-pin":
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


# -------------------------------------------------------------------
# The data link: USB mode, addresses, received data
# -------------------------------------------------------------------

USB_MODE_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "deploy", "modem-usb-mode.sh"
)

USB_MODES = {"qmi_wwan": "qmi", "cdc_mbim": "mbim"}

# A switch running in the background: {"running", "target", "message"}.
usb_switch = {"running": False, "target": None, "message": None}


def wwan_interface():
    """
    The modem's network interface (wwan0) and its driver, or (None, None).
    """

    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return None, None

    for name in names:

        if not name.startswith("wwan"):
            continue

        try:
            driver = os.path.basename(os.path.realpath(f"/sys/class/net/{name}/device/driver"))
        except OSError:
            driver = None

        return name, driver

    return None, None


def read_counter(interface, name):

    try:
        with open(f"/sys/class/net/{interface}/statistics/{name}") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def interface_addresses(interface):
    """
    (IPv4, IPv6) global addresses of an interface, None when it has none.
    """

    ipv4 = ipv6 = None

    for line in (run(["ip", "-o", "addr", "show", "dev", interface, "scope", "global"]) or "").splitlines():

        parts = line.split()

        if "inet" in parts and ipv4 is None:
            ipv4 = parts[parts.index("inet") + 1].split("/")[0]
        elif "inet6" in parts and ipv6 is None:
            ipv6 = parts[parts.index("inet6") + 1].split("/")[0]

    return ipv4, ipv6


def data_link(hardware):
    """
    USB mode, addresses and whether received data is being dropped:
    connected, but the driver counts the replies as errors (Quectel in
    MBIM mode) while next to nothing arrives.
    """

    interface, driver = wwan_interface()

    if interface is None:
        return {
            "usb_mode": None, "ipv4": None, "ipv6": None,
            "rx_packets": None, "rx_errors": None, "data_dropped": False,
            "quectel": str(hardware.get("usb_id") or "").startswith("2c7c:"),
            "usb_switch": dict(usb_switch)
        }

    ipv4, ipv6 = interface_addresses(interface)

    rx_packets = read_counter(interface, "rx_packets")
    rx_errors = read_counter(interface, "rx_errors")

    dropped = (
        rx_errors is not None and rx_packets is not None
        and rx_errors >= 3 and rx_errors > rx_packets
    )

    return {
        "usb_mode": USB_MODES.get(driver, driver),
        "ipv4": ipv4,
        "ipv6": ipv6,
        "rx_packets": rx_packets,
        "rx_errors": rx_errors,
        "data_dropped": dropped,
        "quectel": str(hardware.get("usb_id") or "").startswith("2c7c:"),
        "usb_switch": dict(usb_switch)
    }


def switch_usb_mode(target):
    """
    Starts switching a Quectel modem's USB mode in the background (the
    modem restarts, about a minute). Returns {"success", "message"}.
    """

    if target not in ("qmi", "mbim"):
        return {"success": False, "message": "Unknown mode."}

    if usb_switch["running"]:
        return {"success": False, "message": "The modem is already switching."}

    if not os.path.isfile(USB_MODE_SCRIPT):
        return {"success": False, "message": "The switch script is missing (reinstall Chaos Router OS)."}

    def work():

        ok, output = run_command(privileged([USB_MODE_SCRIPT, target]))

        lines = [l for l in str(output or "").strip().splitlines() if l.strip()]

        usb_switch.update({
            "running": False,
            "message": (lines[-1] if lines else ("Done." if ok else "The switch failed.")),
            "success": ok
        })

        # The connection comes back by itself; apply once for the new port.
        if ok and get_modem_settings()["enabled"]:
            apply_modem_settings()

    usb_switch.update({"running": True, "target": target, "message": None, "success": None})

    threading.Thread(target=work, name="modem-usb-mode", daemon=True).start()

    return {"success": True, "message": f"Switching the modem to {target.upper()} mode. It restarts; this takes about a minute."}
