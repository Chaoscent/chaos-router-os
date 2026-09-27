import json
from pathlib import Path
from functools import wraps

from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import check_password_hash

USERS_FILE = Path(__file__).parent / "data" / "users.json"


def load_users():
    with open(USERS_FILE) as f:
        return json.load(f)


def verify_login(username, password):
    users = load_users()

    if username not in users:
        return False

    return check_password_hash(users[username]["password"], password)


def is_logged_in():
    return "user" in session


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():

            # SPA/API requests should return 401 instead of embedding login.html
            if request.path.startswith("/api/") or request.path.startswith("/fragment/"):
                return jsonify({"error": "unauthorized"}), 401

            # Normal browser navigation goes to the login page
            return redirect(url_for("login_page"))

        return func(*args, **kwargs)

    return wrapper