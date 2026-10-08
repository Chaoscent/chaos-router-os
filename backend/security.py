"""
Web security: the session signing key, CSRF protection and login
rate limiting.

- The key that signs session cookies is random per router, stored in
  /var/lib/chaos-router-os/system/secret_key.json (mode 600) and never
  part of a config backup.
- Every request that changes something must carry the session's CSRF
  token in the X-CSRF-Token header (added by static/js/csrf.js), and
  must not come from another site (Origin header).
- Failed logins are counted per client address. After a few, that
  address is locked out for a while, longer each time.
- Behind Caddy, the session cookie is marked Secure for browsers that
  came over HTTPS.
"""

import hmac
import os
import secrets
import threading
import time

from flask import request, session, jsonify
from flask.sessions import SecureCookieSessionInterface

from services.config import load_system, save_system

# -------------------------------------------------------------------
# Session key
# -------------------------------------------------------------------

SECRET_KEY = "secret_key"


def load_secret_key():
    """
    The router's own session key, created on first start. SECRET_KEY
    in the environment overrides it (e.g. for tests).
    """

    if os.getenv("SECRET_KEY"):
        return os.getenv("SECRET_KEY")

    stored = load_system(SECRET_KEY, None)

    if isinstance(stored, dict) and len(str(stored.get("key", ""))) >= 32:
        return stored["key"]

    key = secrets.token_hex(32)

    try:
        save_system(SECRET_KEY, {"key": key}, secret=True)
    except OSError as e:
        # Still secure, but everyone is logged out on every restart.
        print(f"[security] Could not store the session key: {e}")

    return key


# -------------------------------------------------------------------
# HTTPS (through Caddy)
# -------------------------------------------------------------------

LOCALHOST = ("127.0.0.1", "::1")


def is_https():
    """
    Whether the browser uses HTTPS. Caddy talks to the app over plain
    HTTP from localhost and says so in X-Forwarded-Proto; from anywhere
    else that header is ignored (it could be faked).
    """

    return (
        request.remote_addr in LOCALHOST
        and request.headers.get("X-Forwarded-Proto") == "https"
    )


class SessionInterface(SecureCookieSessionInterface):
    """
    The session cookie is Secure (never sent over plain HTTP) when it
    was set over HTTPS. Plain HTTP stays usable for the setup Wi-Fi's
    captive portal, so this can't be a fixed setting.
    """

    def get_cookie_secure(self, app):
        return is_https()


# -------------------------------------------------------------------
# CSRF
# -------------------------------------------------------------------

CSRF_HEADER = "X-CSRF-Token"

UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def csrf_token():
    """
    The session's token, created on first use (also before login, so
    the login form is protected too).
    """

    token = session.get("csrf")

    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token

    return token


def _same_origin():

    origin = request.headers.get("Origin")

    # Same-origin fetches may omit it; the token check still applies.
    if not origin or origin == "null":
        return origin is None

    return origin.split("://", 1)[-1] == request.host


def check_csrf():
    """
    before_request hook: None to continue, or a 403 response.
    """

    if request.method not in UNSAFE_METHODS:
        return None

    expected = session.get("csrf")
    sent = request.headers.get(CSRF_HEADER, "")

    if (
        expected
        and sent
        and hmac.compare_digest(expected, sent)
        and _same_origin()
    ):
        return None

    return jsonify({
        "success": False,
        "message": "Security check failed. Reload the page and try again."
    }), 403


# -------------------------------------------------------------------
# Login rate limiting
# -------------------------------------------------------------------

# Failures allowed within FAILURE_WINDOW before a lockout.
MAX_FAILURES = 5

FAILURE_WINDOW = 15 * 60

# First lockout, doubled for every further one, up to MAX_LOCKOUT.
BASE_LOCKOUT = 60

MAX_LOCKOUT = 15 * 60

_lock = threading.Lock()

# address -> {"failures": [times], "locked_until": t, "lockouts": n}
_attempts = {}


def _entry(address, now):

    entry = _attempts.setdefault(address, {
        "failures": [],
        "locked_until": 0,
        "lockouts": 0
    })

    entry["failures"] = [t for t in entry["failures"] if now - t < FAILURE_WINDOW]

    # A quiet window forgives earlier lockouts.
    if not entry["failures"] and now >= entry["locked_until"] + FAILURE_WINDOW:
        entry["lockouts"] = 0

    return entry


def login_retry_after(address):
    """
    Seconds this address must still wait, or 0.
    """

    now = time.time()

    with _lock:
        return max(0, int(_entry(address, now)["locked_until"] - now + 0.999))


def record_login_failure(address):
    """
    Counts a failed login. Returns the lockout in seconds it caused,
    or 0.
    """

    now = time.time()

    with _lock:

        entry = _entry(address, now)
        entry["failures"].append(now)

        if len(entry["failures"]) < MAX_FAILURES:
            return 0

        lockout = min(MAX_LOCKOUT, BASE_LOCKOUT * 2 ** entry["lockouts"])

        entry["lockouts"] += 1
        entry["locked_until"] = now + lockout
        entry["failures"] = []

        return lockout


def record_login_success(address):

    with _lock:
        _attempts.pop(address, None)
