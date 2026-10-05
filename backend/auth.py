import time
from pathlib import Path
from functools import wraps

from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

from services.config import (
    load_json,
    load_defaults,
    load_running
)

from services import transaction


# users.json: default login in /etc/chaos-router-os, changed
# passwords in /var/lib/chaos-router-os.
USERS = "users"

# Fallback default login shipped with the code.
BUILTIN_USERS_FILE = Path(__file__).parent / "data" / "users.json"

# security.json: default timeouts in /etc/chaos-router-os,
# the user's custom timeouts in /var/lib/chaos-router-os.
SECURITY = "security"

BUILTIN_SECURITY = {
    "idle_timeout": 300,        # 5 minutes
    "absolute_timeout": 3600    # 1 hour
}


def load_users():
    users = load_running(USERS, None)

    if users:
        return users

    return (
        load_defaults(USERS)
        or load_json(str(BUILTIN_USERS_FILE), {})
    )


def save_users(users):
    return transaction.change(USERS, users)["success"]


def load_security_config():
    """
    Only the user's custom timeouts; empty when none are set.
    """

    data = load_running(SECURITY, {})

    return data if isinstance(data, dict) else {}


def save_security_config(config):
    return transaction.change(SECURITY, config)["success"]


def _timeout(key):
    default = int(load_defaults(SECURITY, BUILTIN_SECURITY)[key])

    try:
        value = int(load_security_config().get(key))
    except (TypeError, ValueError):
        return default

    return value if value > 0 else default


def get_idle_timeout():
    return _timeout("idle_timeout")


def get_absolute_timeout():
    return _timeout("absolute_timeout")


def set_session_timeouts(idle_timeout=None, absolute_timeout=None):
    config = load_security_config()

    if idle_timeout is None:
        config.pop("idle_timeout", None)
    else:
        config["idle_timeout"] = int(idle_timeout)

    if absolute_timeout is None:
        config.pop("absolute_timeout", None)
    else:
        config["absolute_timeout"] = int(absolute_timeout)

    save_security_config(config)


def verify_login(username, password):
    users = load_users()

    if username not in users:
        return False

    return check_password_hash(
        users[username]["password"],
        password
    )


def login_user(username):
    now = time.time()

    session.clear()

    session["user"] = username
    session["created_at"] = now
    session["last_activity"] = now


def logout_user():
    session.clear()


def is_logged_in():
    if "user" not in session:
        return False

    now = time.time()

    created_at = session.get("created_at")
    last_activity = session.get("last_activity")

    if created_at is None or last_activity is None:
        session.clear()
        return False

    absolute_timeout = get_absolute_timeout()
    idle_timeout = get_idle_timeout()

    if now - created_at >= absolute_timeout:
        session.clear()
        return False

    if now - last_activity >= idle_timeout:
        session.clear()
        return False

    return True


def update_session_activity():
    if "user" in session:
        session["last_activity"] = time.time()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):

        if not is_logged_in():

            if request.path.startswith("/api/") or \
               request.path.startswith("/fragment/"):

                return jsonify({"error": "unauthorized"}), 401

            return redirect(url_for("login_page"))

        update_session_activity()

        return func(*args, **kwargs)

    return wrapper


def change_password(current_password, new_password):
    username = session.get("user")

    if not username:
        return False, "Not authenticated"

    users = load_users()

    if username not in users:
        return False, "User not found"

    if not check_password_hash(
        users[username]["password"],
        current_password
    ):
        return False, "Current password is incorrect"

    users[username]["password"] = generate_password_hash(
        new_password
    )

    if not save_users(users):
        return False, "Password could not be saved"

    session.clear()

    return True, "Password changed successfully"