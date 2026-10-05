"""
Safe apply: a bad config must never brick the router.

Every settings change goes through change():

    1. The new settings become the running config (/tmp).
    2. They are applied to the system and verified (services start
       and stay up).
    3. Verified changes are committed to /var/lib, which is what the
       router boots with.

If applying or verifying fails, the persistent (last good) config is
restored and applied again.

Changes that can cut the user off (network, firewall, Wi-Fi, ...)
are additionally held as pending until the user confirms them from
the browser. Without a confirmation they are reverted after
CONFIRM_TIMEOUT seconds; a reboot reverts them too, because the
running config is rebuilt from /var/lib at boot.
"""

import os
import threading
import time

from services.config import (
    load_running,
    save_running,
    delete_running,
    has_persistent,
    save_persistent,
    commit,
    revert
)

from services.logs import log_event

CONFIRM_TIMEOUT = int(os.getenv("CHAOS_CONFIRM_TIMEOUT", "120"))

# /tmp/chaos-router-os/pending.json
PENDING = "pending"

_lock = threading.RLock()
_timer = None


def log(message, level="info"):

    log_event("settings", message, level)


def get_area(name):

    # Imported late: the registry imports every service module.
    from services.areas import AREAS

    return AREAS[name]


def result(success, message, **extra):

    return {
        "success": success,
        # Kept for pages that check whether settings were stored.
        "saved": success,
        "message": message,
        "pending": extra.pop("pending", None),
        **extra
    }


# -------------------------------------------------------------------
# Apply / restore
# -------------------------------------------------------------------

def _apply(area):

    if not area.apply:
        return True, "Saved."

    try:

        ok, message = area.apply()

        if ok and area.verify:

            verified, problem = area.verify()

            if not verified:
                return False, problem

        return ok, message

    except Exception as e:
        return False, f"{area.label} failed: {e}"


def _restore(area):
    """
    Back to the persistent config, applied again.
    """

    revert(area.name)

    if not area.apply:
        return

    ok, message = _apply(area)

    if not ok:
        log(f"Restoring {area.label} failed: {message}", "error")


def _ensure_baseline(area):
    """
    Before the first change to an area, record what is running now
    as its persistent config, so there is something to go back to.
    """

    if not area.apply or has_persistent(area.name):
        return

    baseline = area.baseline() if area.baseline else None

    if baseline is not None:
        save_persistent(area.name, baseline, secret=area.secret)


# -------------------------------------------------------------------
# Changes
# -------------------------------------------------------------------

def change(name, data, confirm=None, hint=None, apply=True):
    """
    Applies new settings for an area. Returns a result dict:
    {"success", "message", "pending"}.

    apply=False records a change that is already in effect (e.g. an
    issued certificate) without re-applying the area.
    """

    with _lock:

        area = get_area(name)

        needs_confirm = area.confirm if confirm is None else confirm

        if not apply:
            needs_confirm = False

        if not needs_confirm and is_pending(name):
            return result(False, (
                f"{area.label} has unconfirmed changes. "
                f"Keep or revert them first."
            ))

        _ensure_baseline(area)

        save_running(name, data, secret=area.secret)

        ok, message = _apply(area) if apply else (True, "Saved.")

        if not ok:

            _restore(area)

            log(f"{area.label}: change failed and was rolled back. {message}", "error")

            return result(False, f"{message} Previous settings restored.")

        if needs_confirm:

            _add_pending(area, hint)

            log(f"{area.label}: new settings applied, waiting for confirmation.")

            return result(True, message, pending=get_pending())

        commit(name)

        if area.apply and apply:
            log(f"{area.label}: settings applied and saved.")
        else:
            log(f"{area.label}: settings saved.")

        return result(True, message)


# -------------------------------------------------------------------
# Pending confirmation
# -------------------------------------------------------------------

def load_pending():

    pending = load_running(PENDING, None)

    return pending if pending and pending.get("areas") else None


def is_pending(name):

    pending = load_pending()

    return bool(pending) and any(
        a["name"] == name for a in pending["areas"]
    )


def _add_pending(area, hint):

    pending = load_pending() or {"areas": []}

    pending["areas"] = [
        a for a in pending["areas"] if a["name"] != area.name
    ] + [{
        "name": area.name,
        "label": area.label,
        "hint": hint
    }]

    # Every new change restarts the countdown.
    pending["deadline"] = time.time() + CONFIRM_TIMEOUT

    save_running(PENDING, pending)

    _start_timer(CONFIRM_TIMEOUT)


def get_pending():
    """
    The pending changes with seconds remaining, or None.
    """

    with _lock:

        pending = load_pending()

        if not pending:
            return None

        remaining = pending["deadline"] - time.time()

        # Fallback in case the timer thread is gone.
        if remaining <= 0:
            revert_pending("Not confirmed in time.")
            return None

        return {
            "areas": pending["areas"],
            "remaining": int(remaining),
            "timeout": CONFIRM_TIMEOUT
        }


def confirm_pending():

    with _lock:

        pending = load_pending()

        if not pending:
            return result(False, "Nothing to confirm.")

        for entry in pending["areas"]:
            commit(entry["name"])

        _clear_pending()

        labels = ", ".join(a["label"] for a in pending["areas"])

        log(f"Changes confirmed and saved: {labels}.")

        return result(True, f"Changes kept: {labels}.")


def revert_pending(reason="Reverted."):

    with _lock:

        pending = load_pending()

        if not pending:
            return result(False, "Nothing to revert.")

        # Undo in reverse order of applying.
        for entry in reversed(pending["areas"]):
            _restore(get_area(entry["name"]))

        _clear_pending()

        labels = ", ".join(a["label"] for a in pending["areas"])

        log(f"Changes reverted ({labels}): {reason}", "warning")

        save_running("last_revert", {
            "areas": pending["areas"],
            "reason": reason,
            "time": int(time.time())
        })

        return result(True, f"Changes reverted: {labels}.")


def _clear_pending():

    global _timer

    delete_running(PENDING)

    if _timer:
        _timer.cancel()
        _timer = None


def _start_timer(seconds):

    global _timer

    if _timer:
        _timer.cancel()

    _timer = threading.Timer(seconds, _expire)
    _timer.daemon = True
    _timer.start()


def _expire():

    with _lock:

        pending = load_pending()

        if pending and time.time() >= pending["deadline"] - 0.5:
            revert_pending("Not confirmed in time.")


# -------------------------------------------------------------------
# Startup
# -------------------------------------------------------------------

def recover_pending():
    """
    The app restarted while changes awaited confirmation. Nobody can
    confirm them any more, so they are reverted.
    """

    if load_pending():
        revert_pending("The app restarted before the changes were confirmed.")


def apply_all():
    """
    At boot: applies every configured area from the running config,
    which was just rebuilt from /var/lib.
    """

    from services.areas import AREAS

    for name, area in AREAS.items():

        if not area.apply or load_running(name, None) is None:
            continue

        ok, message = _apply(area)

        if ok:
            log(f"Boot: {area.label} applied.")
        else:
            log(f"Boot: {area.label} failed to apply: {message}", "error")
