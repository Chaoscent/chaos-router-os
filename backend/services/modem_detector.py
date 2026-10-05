import subprocess

KNOWN_MODEMS = {
    "2c7c:0801": ("Quectel", "RM520N-GL"),
    "2c7c:0800": ("Quectel", "RM500Q/RM502Q"),
    "2c7c:0125": ("Quectel", "RG500Q"),

    "2cb7:0007": ("Fibocom", "FM350"),
    "2cb7:01a2": ("Fibocom", "FM160"),

    "1199:9071": ("Sierra Wireless", "EM7455"),
    "1199:90d3": ("Sierra Wireless", "EM9191"),

    "1bc7:1201": ("Telit", "FN980"),
    "1bc7:1910": ("Telit", "LM960"),

    "1e0e:9001": ("SIMCom", "SIM8200"),
    "1e0e:9003": ("SIMCom", "SIM8262"),
}


def detect_modem():

    try:
        output = subprocess.check_output(["lsusb"], text=True)
    except:
        return {
            "vendor": None,
            "model": None,
            "usb_id": None
        }

    for line in output.splitlines():

        if "ID" not in line:
            continue

        usb_id = line.split("ID")[1].split()[0].lower()

        if usb_id in KNOWN_MODEMS:

            vendor, model = KNOWN_MODEMS[usb_id]

            return {
                "vendor": vendor,
                "model": model,
                "usb_id": usb_id
            }

    # Nothing known on USB. ModemManager may still find a modem.
    return {
        "vendor": None,
        "model": None,
        "usb_id": None
    }
