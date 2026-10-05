"""
Logs: the router's own event log and the system journal.

Router events (logins, applied/reverted settings, blocks, ...) are kept
as JSON in /var/lib/chaos-router-os/system/events.json, newest last,
capped at MAX_EVENTS. They survive reboots, so a revert at boot can
still be read afterwards.

Service logs come from the systemd journal (`journalctl -o json`).
"""

import json
import re
import sys
import threading
import time

from services.config import load_system, save_system

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

EVENTS = "events"
MAX_EVENTS = 2000

LEVELS = ("debug", "info", "warning", "error")

_lock = threading.Lock()

# Journal sources: id -> (label, journalctl filter args).
JOURNAL_SOURCES = {
    "system": ("All system logs", []),
    "wifi": ("WiFi (hostapd)", ["-u", "hostapd"]),
    "dnsmasq": ("DHCP & DNS (dnsmasq)", ["-u", "dnsmasq"]),
    "network": ("Network (NetworkManager)", ["-u", "NetworkManager"]),
    "modem": ("Modem (ModemManager)", ["-u", "ModemManager"]),
    "firewall": ("Firewall (blocked traffic)", ["-k"]),
    "wireguard": ("WireGuard", ["-u", "wg-quick@*"]),
    "openvpn": ("OpenVPN", ["-u", "openvpn-server@*", "-u", "openvpn-client@*"]),
    "kernel": ("Kernel", ["-k"])
}

# syslog priorities 0-7 -> our levels.
PRIORITY_LEVELS = {
    0: "error", 1: "error", 2: "error", 3: "error",
    4: "warning",
    5: "info", 6: "info",
    7: "debug"
}

# Minimum level -> journalctl -p value.
LEVEL_PRIORITIES = {
    "warning": "warning",
    "error": "err"
}

UFW_FIELDS = re.compile(r"\b(IN|OUT|SRC|DST|PROTO|SPT|DPT)=(\S*)")

# Terminal colour codes some services print, e.g. "\x1b[33m".
ANSI_CODES = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def level_at_least(level, minimum):

    if minimum in (None, "", "all"):
        return True

    return LEVELS.index(level) >= LEVELS.index(minimum)


# -------------------------------------------------------------------
# Router events
# -------------------------------------------------------------------

def log_event(category, message, level="info", **details):
    """
    Records a router event. Never raises: logging must not break
    the action being logged.
    """

    entry = {
        "time": time.time(),
        "level": level if level in LEVELS else "info",
        "source": category,
        "message": message
    }

    if details:
        entry["details"] = details

    print(f"[{category}] {message}", file=sys.stderr)

    try:

        with _lock:

            events = load_system(EVENTS, [])

            if not isinstance(events, list):
                events = []

            events.append(entry)

            save_system(EVENTS, events[-MAX_EVENTS:])

    except Exception as e:
        print(f"[logs] Could not record event: {e}", file=sys.stderr)


def get_events(limit=200, level=None, search=""):

    events = load_system(EVENTS, [])

    if not isinstance(events, list):
        return []

    search = (search or "").lower()

    matched = [
        e for e in events
        if level_at_least(e.get("level", "info"), level)
        and (
            not search
            or search in e.get("message", "").lower()
            or search in e.get("source", "").lower()
        )
    ]

    # Newest first.
    return list(reversed(matched[-limit:]))


def clear_events():

    with _lock:
        save_system(EVENTS, [])

    log_event("logs", "Router event log cleared.")


# -------------------------------------------------------------------
# System journal
# -------------------------------------------------------------------

def _text(value):
    """
    The journal stores non-UTF-8 messages as byte arrays.
    """

    if isinstance(value, list):
        return bytes(value).decode("utf-8", "replace")

    return str(value or "")


def describe_ufw(message):
    """
    "[UFW BLOCK] IN=wwan0 ... SRC=1.2.3.4 DST=... PROTO=TCP DPT=22"
    -> "Blocked TCP 1.2.3.4 -> 10.0.0.2:22 on wwan0".
    """

    fields = dict(UFW_FIELDS.findall(message))

    action = "Blocked" if "BLOCK" in message else "Allowed"

    port = f":{fields['DPT']}" if fields.get("DPT") else ""

    interface = fields.get("IN") or fields.get("OUT") or "?"

    return (
        f"{action} {fields.get('PROTO', '?')} "
        f"{fields.get('SRC', '?')} -> {fields.get('DST', '?')}{port} "
        f"on {interface}"
    )


def read_journal(source, limit=200, level=None, search=""):
    """
    Returns (entries, error). Entries are newest first.
    """

    # Imported late: network -> transaction -> logs would be circular.
    from services.network import run_command, privileged

    if source not in JOURNAL_SOURCES:
        return [], "Unknown log source."

    _, filters = JOURNAL_SOURCES[source]

    search = (search or "").lower()

    # Filtering happens here, so read more lines when it will drop some.
    filtering = bool(search) or source == "firewall"
    lines = min(limit * 10, 5000) if filtering else limit

    cmd = [
        "journalctl",
        "--no-pager",
        "-o", "json",
        "-n", str(lines),
        *filters
    ]

    if level in LEVEL_PRIORITIES:
        cmd += ["-p", LEVEL_PRIORITIES[level]]

    ok, output = run_command(privileged(cmd))

    if not ok:
        return [], f"Could not read the system journal: {output}"

    entries = []

    for line in output.splitlines():

        try:
            record = json.loads(line)
        except ValueError:
            continue

        message = ANSI_CODES.sub("", _text(record.get("MESSAGE")))

        if source == "firewall":

            if "[UFW " not in message:
                continue

            message = describe_ufw(message)

        if search and search not in message.lower():
            continue

        try:
            priority = int(record.get("PRIORITY", 6))
        except ValueError:
            priority = 6

        entries.append({
            "time": int(record.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000,
            "level": PRIORITY_LEVELS.get(priority, "info"),
            "source": (
                record.get("SYSLOG_IDENTIFIER")
                or record.get("_SYSTEMD_UNIT")
                or ("kernel" if record.get("_TRANSPORT") == "kernel" else "system")
            ),
            "message": message
        })

    entries.reverse()

    return entries[:limit], None


# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------

def get_sources():

    return [{"id": "app", "label": "Router events"}] + [
        {"id": key, "label": label}
        for key, (label, _) in JOURNAL_SOURCES.items()
    ]


def get_logs(source="app", limit=200, level=None, search=""):

    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 200

    if level not in (None, "", "all") and level not in LEVELS:
        level = None

    if source == "app":
        return {"entries": get_events(limit, level, search), "error": None}

    entries, error = read_journal(source, limit, level, search)

    return {"entries": entries, "error": error}
