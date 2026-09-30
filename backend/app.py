import os

from flask import (
    Flask,
    render_template,
    abort,
    jsonify,
    request,
    session,
    redirect,
    url_for
)

from auth import (
    verify_login,
    login_user,
    is_logged_in,
    login_required,
    get_idle_timeout,
    get_absolute_timeout,
    set_session_timeouts,
    change_password
)

from services.system import (
    get_hostname,
    set_hostname,
    get_ip,
    get_uptime,
    get_cpu_temp,
    get_ram,
    get_time,
    get_ping
)

from services.network import (
    get_default_interface,
    get_gateway,
    get_dns,
    get_connection_type,
    get_ip as get_network_ip,
    get_connected_clients,
    get_clients,
    get_lan_config,
    get_interfaces,
    validate_lan_config,
    apply_lan_config,
    apply_interface_config,
    set_device_alias
)

from services.modem import get_modem_data
from services.traffic import get_traffic, get_history

from services.config import (
    load_json,
    save_json,
    RUNTIME_DIR
)


app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static"
)

app.secret_key = os.getenv("SECRET_KEY", "chaos-router-dev")


# Runtime state (/tmp)
NETWORK_PENDING_FILE = f"{RUNTIME_DIR}/network_pending.json"


# ------------------------------------------------------------
# Authentication
# ------------------------------------------------------------

@app.route("/")
def home():

    if not is_logged_in():
        return redirect(url_for("login_page"))

    return render_template("base.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():

    data = request.get_json()

    username = data.get("username", "")
    password = data.get("password", "")

    if verify_login(username, password):

        login_user(username)

        return jsonify({
            "success": True
        })

    return jsonify({
        "success": False
    }), 401


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login_page"))


# ------------------------------------------------------------
# SPA Fragments
# ------------------------------------------------------------

VALID_PAGES = {
    "dashboard",
    "network",
    "clients",
    "vpn",
    "modem",
    "logs",
    "system",
    "apps"
}


@app.route("/fragment/<page>")
@login_required
def fragment(page):

    if page not in VALID_PAGES:
        abort(404)

    return render_template(f"{page}.html")


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------

@app.route("/api/dashboard")
@login_required
def dashboard_api():

    traffic = get_traffic()

    return jsonify({
        "hostname": get_hostname(),
        "ip": get_ip(),
        "uptime": get_uptime(),
        "cpu_temp": get_cpu_temp(),
        "ram": get_ram(),
        "time": get_time(),
        "clients": get_connected_clients(),
        "active": max(
            1 if traffic["rx"] > 0 or traffic["tx"] > 0 else 0,
            0
        ),
        "download": traffic["rx"],
        "upload": traffic["tx"],
        "history": get_history()
    })


# ------------------------------------------------------------
# Network
# ------------------------------------------------------------

@app.route("/api/network")
@login_required
def network_api():

    interface = get_default_interface()

    return jsonify({
        "interface": interface,
        "gateway": get_gateway(interface),
        "ip": get_network_ip(interface),
        "dns": get_dns(),
        "connection": get_connection_type(interface),
        "wan": "Connected" if interface != "Unknown" else "Disconnected"
    })


@app.route("/api/network/interfaces")
@login_required
def network_interfaces_api():

    return jsonify(get_interfaces())


@app.route("/api/network/config")
@login_required
def network_config_api():

    return jsonify(get_lan_config())


@app.route("/api/network/pending")
@login_required
def network_pending_api():

    return jsonify(load_json(NETWORK_PENDING_FILE, {}))


@app.route("/api/network/stage", methods=["POST"])
@login_required
def network_stage_api():

    data = request.get_json()

    ok, message = validate_lan_config(data)

    if not ok:
        return jsonify({
            "success": False,
            "message": message
        }), 400

    save_json(NETWORK_PENDING_FILE, data)

    return jsonify({
        "success": True,
        "pending": data
    })


@app.route("/api/network/discard", methods=["POST"])
@login_required
def network_discard_api():

    save_json(NETWORK_PENDING_FILE, {})

    return jsonify({
        "success": True
    })


@app.route("/api/network/apply", methods=["POST"])
@login_required
def network_apply_api():

    pending = load_json(NETWORK_PENDING_FILE, {})

    if not pending:
        return jsonify({
            "success": False,
            "message": "No pending changes."
        }), 400

    success, result = apply_interface_config(
        pending,
        dry_run=False
    )

    if success:

        save_json(NETWORK_PENDING_FILE, {})

        return jsonify({
            "success": True,
            "message": "Network configuration applied.",
            "result": result
        })

    return jsonify({
        "success": False,
        "message": result
    }), 500


# ------------------------------------------------------------
# Modem + Header
# ------------------------------------------------------------

@app.route("/api/modem")
@login_required
def modem_api():

    return jsonify(get_modem_data())


@app.route("/api/header")
@login_required
def header_api():

    traffic = get_traffic()
    modem = get_modem_data()

    return jsonify({
        "network": modem["network"],
        "model": modem["model"],
        "carrier": modem["carrier"],
        "ping": get_ping(),
        "time": get_time(),
        "user": session["user"],
        "rx": traffic["rx"],
        "tx": traffic["tx"]
    })


# ------------------------------------------------------------
# Clients
# ------------------------------------------------------------

@app.route("/api/clients")
@login_required
def clients_api():

    return jsonify(get_clients())


@app.route("/api/clients/alias", methods=["POST"])
@login_required
def client_alias():

    data = request.get_json()

    mac = data.get("mac", "").strip()
    alias = data.get("alias", "").strip()

    if not mac:
        return jsonify({
            "success": False,
            "message": "MAC address is required."
        }), 400

    set_device_alias(mac, alias)

    return jsonify({
        "success": True,
        "mac": mac.upper(),
        "alias": alias
    })


@app.route("/api/clients/rename", methods=["POST"])
@login_required
def rename_client():

    return client_alias()


# ------------------------------------------------------------
# System
# ------------------------------------------------------------

@app.route("/api/system/hostname", methods=["POST"])
@login_required
def update_hostname():

    data = request.get_json()

    success, message = set_hostname(
        data["hostname"]
    )

    if success:

        return jsonify({
            "success": True,
            "hostname": message
        })

    return jsonify({
        "success": False,
        "message": message
    }), 400


@app.route("/api/system/security")
@login_required
def system_security():

    return jsonify({
        "idle_timeout": get_idle_timeout(),
        "absolute_timeout": get_absolute_timeout()
    })


@app.route("/api/system/security", methods=["POST"])
@login_required
def update_security():

    data = request.get_json()

    idle_timeout = data.get("idle_timeout")
    absolute_timeout = data.get("absolute_timeout")

    try:
        idle_timeout = int(idle_timeout)
        absolute_timeout = int(absolute_timeout)
    except (TypeError, ValueError):

        return jsonify({
            "success": False,
            "message": "Timeout values must be numbers."
        }), 400

    if idle_timeout < 60:

        return jsonify({
            "success": False,
            "message": "Idle timeout must be at least 1 minute."
        }), 400

    if absolute_timeout < 60:

        return jsonify({
            "success": False,
            "message": "Absolute timeout must be at least 1 minute."
        }), 400

    if absolute_timeout < idle_timeout:

        return jsonify({
            "success": False,
            "message": "Absolute timeout must be greater than idle timeout."
        }), 400

    set_session_timeouts(
        idle_timeout=idle_timeout,
        absolute_timeout=absolute_timeout
    )

    return jsonify({
        "success": True,
        "idle_timeout": idle_timeout,
        "absolute_timeout": absolute_timeout
    })


@app.route("/api/system/password", methods=["POST"])
@login_required
def update_password():

    data = request.get_json()

    current_password = data.get(
        "current_password",
        ""
    )

    new_password = data.get(
        "new_password",
        ""
    )

    if not current_password or not new_password:

        return jsonify({
            "success": False,
            "message": "All password fields are required."
        }), 400

    if len(new_password) < 8:

        return jsonify({
            "success": False,
            "message": "Password must be at least 8 characters."
        }), 400

    success, message = change_password(
        current_password,
        new_password
    )

    if not success:

        return jsonify({
            "success": False,
            "message": message
        }), 400

    return jsonify({
        "success": True,
        "message": message
    })


# ------------------------------------------------------------
# Development
# ------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )