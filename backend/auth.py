import json
import time
from pathlib import Path
from functools import wraps

from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash


USERS_FILE = Path(__file__).parent / "data" / "users.json"

CONFIG_DIR = Path("/etc/chaos-router-os/config")
SECURITY_FILE = CONFIG_DIR / "security.json"

DEFAULT_IDLE_TIMEOUT = 300          # 5 minutes
DEFAULT_ABSOLUTE_TIMEOUT = 3600     # 1 hour


def load_users():
    with open(USERS_FILE) as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)


def load_security_config():
    if not SECURITY_FILE.exists():
        return {}

    try:
        with open(SECURITY_FILE) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        return data

    except (OSError, json.JSONDecodeError):
        return {}


def save_security_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    temp_file = SECURITY_FILE.with_suffix(".tmp")

    with open(temp_file, "w") as f:
        json.dump(config, f, indent=4)

    temp_file.replace(SECURITY_FILE)


def get_idle_timeout():
    config = load_security_config()

    value = config.get("idle_timeout")

    if value is None:
        return DEFAULT_IDLE_TIMEOUT

    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_TIMEOUT

    if value <= 0:
        return DEFAULT_IDLE_TIMEOUT

    return value


def get_absolute_timeout():
    config = load_security_config()

    value = config.get("absolute_timeout")

    if value is None:
        return DEFAULT_ABSOLUTE_TIMEOUT

    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ABSOLUTE_TIMEOUT

    if value <= 0:
        return DEFAULT_ABSOLUTE_TIMEOUT

    return value


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

    save_users(users)

    session.clear()

    return True, "Password changed successfully"