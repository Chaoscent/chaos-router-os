import json

import os

import time

from urllib.parse import urlsplit



from flask_sock import Sock

from flask import (

        Flask,

        render_template,

        abort,

        jsonify,

        request,

        session,

        redirect,

        url_for,

        Response

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

        get_uptime,

        get_cpu_temp,

        get_ram,

        get_cpu_load,

        reboot_system,

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

        change_interface,

        set_eth0_role,

        set_lan_bridge,

        get_network_settings,

        bridges_interface,

        get_lan_bridge_status,

        get_eth0_role,

        get_wan_interface,

        set_device_alias

)



from services.dhcp import (

        get_dhcp_settings,

        get_dhcp_status,

        get_dhcp_leases,

        get_lan_interfaces,

        render_dnsmasq_config,

        validate_dhcp_settings,

        prepare_change as prepare_dhcp_change,

        get_scopes as get_dhcp_scopes,

        save_dhcp_settings,

        apply_dhcp_settings,

        add_reservation,

        remove_reservation

)

from services.firewall import (

        get_firewall_status,

        get_essential_rules,

        set_firewall_enabled,

        set_essentials as set_firewall_essentials,

        set_policies as set_firewall_policies,

        set_logging as set_firewall_logging,

        add_rule as add_firewall_rule,

        delete_rule as delete_firewall_rule

)

from services.routing import (

        get_routing_status,

        save_routing_settings

)

from services.wifi import (

        get_wifi_settings,

        get_wifi_status,

        get_wifi_options,

        get_wireless_interfaces,

        get_wifi_clients,

        validate_network as validate_wifi_network,

        get_networks as get_wifi_networks,

        render_hostapd_config,

        save_wifi_settings,

        apply_wifi_settings

)

from services.wireguard import (

        get_wireguard_status,

        save_server as save_wireguard_server,

        add_peer as add_wireguard_peer,

        remove_peer as remove_wireguard_peer,

        get_peer_config as get_wireguard_peer_config

)

from services.openvpn import (

        get_openvpn_status,

        save_server as save_openvpn_server,

        add_client as add_openvpn_client,

        revoke_client as revoke_openvpn_client,

        get_client_config as get_openvpn_client_config

)

from services.vpn_profiles import (

        get_profiles_status,

        import_profile as import_vpn_profile,

        delete_profile as delete_vpn_profile,

        connect_profile as connect_vpn_profile,

        disconnect_profile as disconnect_vpn_profile,

        set_autostart as set_vpn_autostart,

        set_full_tunnel as set_vpn_full_tunnel

)

from services.clients import (

        get_client_list,

        block_device,

        unblock_device,

        ping_device,

        wake_device

)

from services.dns import (

        get_dns_settings,

        get_dns_status,

        get_dns_options,

        validate_dns_settings,

        render_dns_config,

        save_dns_settings,

        add_record as add_dns_record,

        remove_record as remove_dns_record,

        set_blocked_domains,

        lookup as dns_lookup

)

from services.backup import (

        create_backup,

        parse_backup,

        inspect_backup,

        restore_backup

)

from services.modem import (
        get_modem_data,
        public_settings as modem_public_settings,
        save_modem_settings,
        unlock_sim
)

from services import transaction

from services import setup_network

from services import shell as web_shell

from services.caddy import tls_allowed, root_certificate, BEHIND_CADDY

from services import apps as router_apps

from factory_reset import factory_reset

from setup import (
        is_setup_complete,
        get_setup_info,
        complete_setup
)

from security import (
        load_secret_key,
        SessionInterface,
        LOCALHOST,
        csrf_token,
        check_csrf,
        login_retry_after,
        record_login_failure,
        record_login_success
)

from services.logs import (

        log_event,

        get_logs,

        get_sources as get_log_sources,

        clear_events

)

from services.config import sync_boot

from services.traffic import get_traffic, get_history



from services.config import (

        load_defaults,

        load_running,

        save_running

)





app = Flask(

        __name__,

        template_folder="../frontend/templates",

        static_folder="../frontend/static"

)



# Random per router (see security.py), never a known default.
app.secret_key = load_secret_key()

# Secure session cookie for browsers on HTTPS (Caddy).
app.session_interface = SessionInterface()

app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax"
)

app.jinja_env.globals["csrf_token"] = csrf_token


def asset(filename):
        """
        A static file's URL with its modification time (?v=...): a
        changed file gets a new URL, so browsers never keep an old copy
        (tab icons are cached especially stubbornly).
        """

        try:
                version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
                version = 0

        return url_for("static", filename=filename, v=version)


def page_scripts_version():
        """
        Newest change among the page scripts that router.js loads by
        name (/static/js/<page>.js).
        """

        folder = os.path.join(app.static_folder, "js")

        try:
                return max(int(e.stat().st_mtime) for e in os.scandir(folder) if e.name.endswith(".js"))
        except (OSError, ValueError):
                return 0


app.jinja_env.globals["asset"] = asset
app.jinja_env.globals["page_scripts_version"] = page_scripts_version


def read_app_version():
        """
        The version from VERSION in the repository root, plus the git
        commit when running from a clone, e.g. "0.1.0-alpha (c827d5b)".
        Read once at startup.
        """

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        try:
                with open(os.path.join(root, "VERSION")) as f:
                        version = f.read().strip() or "unknown"
        except OSError:
                version = "unknown"

        from services.network import run

        # None without git or outside a clone: then just the version.
        commit = run(["git", "-C", root, "rev-parse", "--short", "HEAD"])

        return f"{version} ({commit})" if commit else version


APP_VERSION = read_app_version()

app.jinja_env.globals["app_version"] = APP_VERSION

# WebSockets (web shell).
sock = Sock(app)


@app.before_request
def setup_gate():

        # Not set up (fresh install or factory reset): only /setup works.
        # Set up: /setup is gone.
        path = request.path

        is_setup_path = path == "/setup" or path.startswith("/api/setup/")

        if is_setup_complete():

                if is_setup_path:
                        abort(404)

                return None

        if (
                is_setup_path
                or path.startswith("/static/")
                or path in ("/favicon.ico", "/caddy/tls-allowed", "/router-ca.crt")
        ):
                return None

        if path.startswith(("/api/", "/fragment/")) or request.method != "GET":

                return jsonify({

                        "success": False,

                        "message": "The router is not set up yet. Open /setup.",

                        "setup": True

                }), 409

        # Everything else, including captive portal checks from phones
        # (/generate_204, /hotspot-detect.html, ...), opens the setup page.
        # On the setup Wi-Fi every name points at the router, so send
        # phones to its address rather than the name they asked for.
        if (
                setup_network.is_on_setup_network(get_viewer_ip())
                and request.host.split(":")[0] != setup_network.ADDRESS
        ):
                return redirect(f"http://{setup_network.ADDRESS}/setup")

        return redirect("/setup")


# Once set up, the dashboard is HTTPS only. Before that, plain HTTP must
# keep working: the setup Wi-Fi's captive portal and the connectivity
# checks of phones use it. No HSTS: with the router's own CA it would
# make the browser's warning impossible to click through.
HTTP_ONLY_PATHS = ("/router-ca.crt", "/caddy/tls-allowed")


@app.before_request
def https_redirect():

        if (
                not BEHIND_CADDY
                or request.remote_addr not in LOCALHOST
                or request.headers.get("X-Forwarded-Proto") != "http"
                or request.path in HTTP_ONLY_PATHS
                or not is_setup_complete()
        ):
                return None

        # 308 keeps the method and body (for POSTs).
        return redirect("https://" + request.url.split("://", 1)[1], code=308)



@app.before_request
def csrf_protect():

        return check_csrf()

# Largest request accepted (config backups are the biggest uploads).
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024





# Interface edits staged on the Network page before applying
# (/tmp/chaos-router-os, gone after a reboot).
NETWORK_STAGED = "network_staged"



# dashboard.json: defaults in /etc/chaos-router-os,
# the user's settings in /var/lib/chaos-router-os.
DASHBOARD = "dashboard"

BUILTIN_DASHBOARD = {

        "ping_enabled": False,

        "ping_interval": 5,

        "ping_destination": "1.1.1.1"

}

VALID_PING_INTERVALS = {5, 10, 30, 60}





def load_dashboard_config():

        data = load_running(DASHBOARD, {})

        return data if isinstance(data, dict) else {}





def save_dashboard_config(config):

        return transaction.change(DASHBOARD, config)["success"]





def get_ping_config():

        config = load_dashboard_config()

        defaults = load_defaults(DASHBOARD, BUILTIN_DASHBOARD)



        enabled = config.get("ping_enabled", defaults["ping_enabled"])

        if not isinstance(enabled, bool):

                enabled = defaults["ping_enabled"]



        interval = config.get("ping_interval", defaults["ping_interval"])



        try:

                interval = int(interval)

        except (TypeError, ValueError):

                interval = defaults["ping_interval"]



        if interval not in VALID_PING_INTERVALS:

                interval = defaults["ping_interval"]



        destination = config.get("ping_destination", defaults["ping_destination"])

        if not isinstance(destination, str):
                destination = defaults["ping_destination"]

        destination = destination.strip()

        if not destination:
                destination = defaults["ping_destination"]

        return {

                "enabled": enabled,

                "interval": interval,

                "destination": destination

        }





def set_ping_config(enabled, interval, destination):

        config = load_dashboard_config()

        config["ping_enabled"] = bool(enabled)

        config["ping_interval"] = int(interval)

        config["ping_destination"] = destination.strip()

        save_dashboard_config(config)





# ------------------------------------------------------------

# Authentication

# ------------------------------------------------------------



@app.route("/")

def home():



        if not is_logged_in():

                return redirect(url_for("login_page"))



        return render_template("base.html")





# Browsers ask for /favicon.ico on their own.
@app.route("/favicon.ico")

def favicon():

        return app.send_static_file("favicon.ico")





# The local CA's root certificate: installed on a device, the router's
# HTTPS (dashboard and apps) is trusted without warnings. Public (it is
# a certificate, not a key) and over plain HTTP too: devices need it
# before they trust HTTPS.
@app.route("/router-ca.crt")

def router_ca():

        pem = root_certificate()

        if not pem:
                return jsonify({
                        "success": False,
                        "message": "No certificate yet. Open the dashboard over HTTPS once, then try again."
                }), 404

        return Response(
                pem,
                mimetype="application/x-x509-ca-cert",
                headers={"Content-Disposition": 'attachment; filename="chaos-router-ca.crt"'}
        )





# Caddy asks here before it makes an HTTPS certificate (on_demand_tls
# in deploy/Caddyfile): only for the router's own LAN addresses and
# names. Answered only to Caddy itself: it asks from localhost, without
# X-Forwarded-For (requests it forwards from browsers carry that header,
# and the Caddyfile does not forward /caddy/ at all).
@app.route("/caddy/tls-allowed")

def caddy_tls_allowed():

        if request.remote_addr not in LOCALHOST or "X-Forwarded-For" in request.headers:
                abort(404)

        if tls_allowed(request.args.get("domain")):
                return "", 200

        return "", 403





@app.route("/setup")

def setup_page():

        return render_template("setup.html")





@app.route("/api/setup/info")

def setup_info_api():

        return jsonify(get_setup_info(get_viewer_ip()))





@app.route("/api/setup/complete", methods=["POST"])

def setup_complete_api():

        data = request.get_json(silent=True) or {}

        ok, result = complete_setup(data)

        if not ok:

                return jsonify({"success": False, "message": result}), 400



        # Signed in right away: setup ends on the dashboard.
        login_user(result["username"])

        return jsonify({"success": True, "warning": result["warning"]})





@app.route("/login")

def login_page():

        return render_template("login.html")





@app.route("/api/login", methods=["POST"])

def api_login():

        data = request.get_json(silent=True) or {}

        username = str(data.get("username", ""))

        password = str(data.get("password", ""))

        address = get_viewer_ip()



        wait = login_retry_after(address)

        if wait:

                return jsonify({

                        "success": False,

                        "message": f"Too many failed attempts. Try again in {wait} seconds.",

                        "retry_after": wait

                }), 429



        if verify_login(username, password):

                record_login_success(address)

                login_user(username)

                log_event("auth", f"{username} logged in from {address}.")

                return jsonify({

                        "success": True

                })



        lockout = record_login_failure(address)

        log_event(

                "auth",

                f"Failed login for '{username[:64]}' from {address}."

                + (f" Locked out for {lockout} seconds." if lockout else ""),

                "warning"

        )

        if lockout:

                return jsonify({

                        "success": False,

                        "message": f"Too many failed attempts. Try again in {lockout} seconds.",

                        "retry_after": lockout

                }), 429

        return jsonify({

                "success": False,

                "message": "Invalid username or password."

        }), 401




# POST only (with the CSRF token), so other sites cannot log you out.
@app.route("/logout", methods=["POST"])

def logout():

        if session.get("user"):
                log_event("auth", f"{session['user']} logged out.")

        session.clear()

        return jsonify({"success": True})




# ------------------------------------------------------------

# SPA Fragments

# ------------------------------------------------------------



VALID_PAGES = {

        "dashboard",

        "shell",

        "network",

        "wifi",

        "dhcp",

        "dns",

        "clients",

        "firewall",

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

                "cpu_load": get_cpu_load(),

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

                "interface": traffic["interface"],

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

                "wan": "Connected" if interface != "Unknown" else "Disconnected",

                "eth0_role": get_eth0_role(),

                "wan_interface": get_wan_interface()

        })





@app.route("/api/network/lan")

@login_required

def network_lan_api():

        return jsonify(get_lan_bridge_status())





@app.route("/api/network/lan", methods=["POST"])

@login_required

def network_lan_save_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(set_lan_bridge(data))





@app.route("/api/network/eth0-role", methods=["POST"])

@login_required

def network_eth0_role_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                set_eth0_role(data.get("role"))
        )





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



        return jsonify(load_running(NETWORK_STAGED, {}))





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



        save_running(NETWORK_STAGED, data)



        return jsonify({

                "success": True,

                "pending": data

        })





@app.route("/api/network/discard", methods=["POST"])

@login_required

def network_discard_api():



        save_running(NETWORK_STAGED, {})



        return jsonify({

                "success": True

        })





@app.route("/api/network/apply", methods=["POST"])

@login_required

def network_apply_api():

        staged = load_running(NETWORK_STAGED, {})

        if not staged:

                return jsonify({

                        "success": False,

                        "message": "No pending changes."

                }), 400



        outcome = change_interface(staged)

        if outcome["success"]:

                save_running(NETWORK_STAGED, {})



        return safe_apply_response(outcome)




# ------------------------------------------------------------

# WiFi (hostapd)

# ------------------------------------------------------------



@app.route("/api/wifi")

@login_required

def wifi_api():

        networks = get_wifi_networks()

        return jsonify({

                # One network per radio (flat, with "interface").
                "networks": networks,

                "country": get_wifi_settings()["country"],

                "status": get_wifi_status(),

                # Radios that are ports of the LAN bridge have no own address.
                "bridged": {name: bridges_interface(name) for name in networks},

                "options": get_wifi_options(),

                "interfaces": get_wireless_interfaces()

        })





@app.route("/api/wifi/settings", methods=["POST"])

@login_required

def wifi_settings_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                save_wifi_settings(data)
        )




@app.route("/api/wifi/preview", methods=["POST"])

@login_required

def wifi_preview_api():

        data = request.get_json(silent=True) or {}

        ok, result = validate_wifi_network(data)

        if not ok:

                return jsonify({

                        "success": False,

                        "message": result

                }), 400



        return jsonify({

                "success": True,

                "config": render_hostapd_config(result)

        })





@app.route("/api/wifi/apply", methods=["POST"])

@login_required

def wifi_apply_api():

        applied, message = apply_wifi_settings()

        return jsonify({

                "success": applied,

                "message": message

        }), 200 if applied else 500





@app.route("/api/wifi/clients")

@login_required

def wifi_clients_api():

        return jsonify(get_wifi_clients())





# ------------------------------------------------------------

# DNS (dnsmasq)

# ------------------------------------------------------------



@app.route("/api/dns")

@login_required

def dns_api():

        return jsonify({

                "settings": get_dns_settings(),

                "status": get_dns_status(),

                "options": get_dns_options()

        })





@app.route("/api/dns/settings", methods=["POST"])

@login_required

def dns_settings_api():

        data = request.get_json(silent=True) or {}

        # Records and the blocklist have their own endpoints.
        data.pop("records", None)
        data.pop("blocked_domains", None)

        return safe_apply_response(
                save_dns_settings(data)
        )





@app.route("/api/dns/preview", methods=["POST"])

@login_required

def dns_preview_api():

        data = request.get_json(silent=True) or {}

        ok, result = validate_dns_settings(data)

        if not ok:

                return jsonify({

                        "success": False,

                        "message": result

                }), 400



        return jsonify({

                "success": True,

                "config": render_dns_config(result)

        })





@app.route("/api/dns/records", methods=["POST"])

@login_required

def dns_add_record_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                add_dns_record(str(data.get("name", "")), str(data.get("ip", "")))
        )





@app.route("/api/dns/records", methods=["DELETE"])

@login_required

def dns_remove_record_api():

        data = request.get_json(silent=True) or {}

        outcome = remove_dns_record(str(data.get("name", "")), str(data.get("ip", "")))

        if outcome["message"] == "Record not found.":
                return jsonify(outcome), 404

        return safe_apply_response(outcome)





@app.route("/api/dns/blocklist", methods=["POST"])

@login_required

def dns_blocklist_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                set_blocked_domains(data.get("domains", []))
        )





@app.route("/api/dns/lookup", methods=["POST"])

@login_required

def dns_lookup_api():

        data = request.get_json(silent=True) or {}

        return jsonify(dns_lookup(data.get("name"), data.get("type", "A")))





# ------------------------------------------------------------

# DHCP (dnsmasq)

# ------------------------------------------------------------



def safe_apply_response(outcome):

        # 400 when nothing changed (invalid input or a failed apply that
        # was rolled back), 200 when applied (possibly awaiting confirm).
        return jsonify(outcome), 200 if outcome["success"] else 400




@app.route("/api/dhcp")

@login_required

def dhcp_api():

        return jsonify({

                "settings": get_dhcp_settings(),

                # Per interface, prefilled for interfaces without DHCP.
                "scopes": get_dhcp_scopes(),

                "status": get_dhcp_status(),

                "interfaces": get_lan_interfaces()

        })





@app.route("/api/dhcp/settings", methods=["POST"])

@login_required

def dhcp_settings_api():

        data = request.get_json(silent=True) or {}

        # Reservations have their own endpoints.
        data.pop("reservations", None)

        return safe_apply_response(
                save_dhcp_settings(data)
        )





@app.route("/api/dhcp/preview", methods=["POST"])

@login_required

def dhcp_preview_api():

        data = request.get_json(silent=True) or {}

        data.pop("reservations", None)

        ok, result = prepare_dhcp_change(data)

        if not ok:

                return jsonify({

                        "success": False,

                        "message": result

                }), 400



        return jsonify({

                "success": True,

                "config": render_dnsmasq_config(result)

        })





@app.route("/api/dhcp/apply", methods=["POST"])

@login_required

def dhcp_apply_api():

        applied, message = apply_dhcp_settings()

        return jsonify({

                "success": applied,

                "message": message

        }), 200 if applied else 500




@app.route("/api/dhcp/leases")

@login_required

def dhcp_leases_api():

        return jsonify(get_dhcp_leases())





@app.route("/api/dhcp/reservations", methods=["POST"])

@login_required

def dhcp_add_reservation_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                add_reservation(data)
        )




@app.route("/api/dhcp/reservations/<mac>", methods=["DELETE"])

@login_required

def dhcp_remove_reservation_api(mac):

        outcome = remove_reservation(mac)

        if outcome["message"] == "Reservation not found.":
                return jsonify(outcome), 404

        return safe_apply_response(outcome)




# ------------------------------------------------------------

# VPN (WireGuard + OpenVPN)

# ------------------------------------------------------------



def vpn_response(ok, message, status=400, **extra):

        return jsonify({

                "success": ok,

                "message": message,

                **extra

        }), 200 if ok else status





def vpn_save_response(outcome):

        return safe_apply_response(outcome)




def vpn_download(ok, name, content):

        if not ok:

                return vpn_response(False, name, 404)



        return Response(

                content,

                mimetype="text/plain",

                headers={

                        "Content-Disposition":
                                f'attachment; filename="{name}"',

                        # Private keys inside: never cache.
                        "Cache-Control": "no-store"

                }

        )





@app.route("/api/vpn")

@login_required

def vpn_api():

        return jsonify({

                "wireguard": get_wireguard_status(),

                "openvpn": get_openvpn_status(),

                "profiles": get_profiles_status()

        })





@app.route("/api/vpn/wireguard/server", methods=["POST"])

@login_required

def vpn_wireguard_server_api():

        data = request.get_json(silent=True) or {}

        return vpn_save_response(
                save_wireguard_server(data)
        )





@app.route("/api/vpn/wireguard/peers", methods=["POST"])

@login_required

def vpn_wireguard_add_peer_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(add_wireguard_peer(

                data.get("name"),

                data.get("public_key")

        ))




@app.route("/api/vpn/wireguard/peers/<int:peer_id>", methods=["DELETE"])

@login_required

def vpn_wireguard_remove_peer_api(peer_id):

        outcome = remove_wireguard_peer(peer_id)

        if outcome["message"] == "Peer not found.":
                return jsonify(outcome), 404

        return safe_apply_response(outcome)




@app.route("/api/vpn/wireguard/peers/<int:peer_id>/config")

@login_required

def vpn_wireguard_peer_config_api(peer_id):

        return vpn_download(
                *get_wireguard_peer_config(peer_id)
        )





@app.route("/api/vpn/openvpn/server", methods=["POST"])

@login_required

def vpn_openvpn_server_api():

        data = request.get_json(silent=True) or {}

        return vpn_save_response(
                save_openvpn_server(data)
        )





@app.route("/api/vpn/openvpn/clients", methods=["POST"])

@login_required

def vpn_openvpn_add_client_api():

        data = request.get_json(silent=True) or {}

        return vpn_response(
                *add_openvpn_client(data.get("name"))
        )





@app.route("/api/vpn/openvpn/clients/<name>", methods=["DELETE"])

@login_required

def vpn_openvpn_revoke_client_api(name):

        return vpn_response(
                *revoke_openvpn_client(name)
        )





@app.route("/api/vpn/openvpn/clients/<name>/config")

@login_required

def vpn_openvpn_client_config_api(name):

        return vpn_download(
                *get_openvpn_client_config(name)
        )





@app.route("/api/vpn/profiles", methods=["POST"])

@login_required

def vpn_import_profile_api():

        data = request.get_json(silent=True) or {}

        ok, message, profile = import_vpn_profile(data)

        return vpn_response(ok, message, profile=profile)





@app.route("/api/vpn/profiles/<int:profile_id>", methods=["DELETE"])

@login_required

def vpn_delete_profile_api(profile_id):

        return vpn_response(
                *delete_vpn_profile(profile_id)
        )





@app.route("/api/vpn/profiles/<int:profile_id>/connect", methods=["POST"])

@login_required

def vpn_connect_profile_api(profile_id):

        ok, message = connect_vpn_profile(profile_id)

        log_event("vpn", message, "info" if ok else "error")

        return vpn_response(ok, message, status=500)




@app.route("/api/vpn/profiles/<int:profile_id>/disconnect", methods=["POST"])

@login_required

def vpn_disconnect_profile_api(profile_id):

        ok, message = disconnect_vpn_profile(profile_id)

        log_event("vpn", message, "info" if ok else "error")

        return vpn_response(ok, message, status=500)




@app.route("/api/vpn/profiles/<int:profile_id>/full-tunnel", methods=["POST"])

@login_required

def vpn_full_tunnel_profile_api(profile_id):

        data = request.get_json(silent=True) or {}

        return vpn_response(
                *set_vpn_full_tunnel(profile_id, data.get("enabled") is True)
        )





@app.route("/api/vpn/profiles/<int:profile_id>/autostart", methods=["POST"])

@login_required

def vpn_autostart_profile_api(profile_id):

        data = request.get_json(silent=True) or {}

        return vpn_response(
                *set_vpn_autostart(profile_id, data.get("enabled") is True)
        )





# ------------------------------------------------------------

# Firewall (UFW)

# ------------------------------------------------------------



def firewall_response(outcome):

        return safe_apply_response(outcome)




@app.route("/api/firewall")

@login_required

def firewall_api():

        return jsonify(get_firewall_status())




@app.route("/api/firewall/essentials")

@login_required

def firewall_essentials_api():

        return jsonify([

                {

                        "description": rule["description"],

                        "command": rule["command"]

                }

                for rule in get_essential_rules()

        ])





@app.route("/api/firewall/essentials", methods=["POST"])

@login_required

def firewall_essentials_setting_api():

        data = request.get_json(silent=True) or {}

        return firewall_response(
                set_firewall_essentials(data.get("enabled") is True)
        )





@app.route("/api/firewall/enable", methods=["POST"])

@login_required

def firewall_enable_api():

        data = request.get_json(silent=True) or {}

        essentials = data.get("essentials")

        return firewall_response(set_firewall_enabled(

                data.get("enabled") is True,

                essentials=essentials if isinstance(essentials, bool) else None

        ))





@app.route("/api/firewall/policies", methods=["POST"])

@login_required

def firewall_policies_api():

        data = request.get_json(silent=True) or {}

        return firewall_response(
                set_firewall_policies(data)
        )





@app.route("/api/firewall/logging", methods=["POST"])

@login_required

def firewall_logging_api():

        data = request.get_json(silent=True) or {}

        return firewall_response(
                set_firewall_logging(data.get("level"))
        )





@app.route("/api/firewall/rules", methods=["POST"])

@login_required

def firewall_add_rule_api():

        data = request.get_json(silent=True) or {}

        return firewall_response(
                add_firewall_rule(data)
        )





@app.route("/api/firewall/rules", methods=["DELETE"])

@login_required

def firewall_delete_rule_api():

        data = request.get_json(silent=True) or {}

        return firewall_response(
                delete_firewall_rule(str(data.get("id", "")))
        )





@app.route("/api/routing")

@login_required

def routing_api():

        return jsonify(get_routing_status())





@app.route("/api/routing/settings", methods=["POST"])

@login_required

def routing_settings_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                save_routing_settings(data)
        )





# ------------------------------------------------------------

# Safe apply (pending confirmation)

# ------------------------------------------------------------



@app.route("/api/config/pending")

@login_required

def config_pending_api():

        return jsonify({

                "pending": transaction.get_pending(),

                "last_revert": load_running("last_revert", None)

        })





@app.route("/api/config/confirm", methods=["POST"])

@login_required

def config_confirm_api():

        return safe_apply_response(
                transaction.confirm_pending()
        )





@app.route("/api/config/revert", methods=["POST"])

@login_required

def config_revert_api():

        return safe_apply_response(
                transaction.revert_pending("Reverted from the dashboard.")
        )





# ------------------------------------------------------------

# Backup & restore

# ------------------------------------------------------------



@app.route("/api/backup/export")

@login_required

def backup_export_api():

        filename, backup = create_backup()

        return Response(

                json.dumps(backup, indent=2),

                mimetype="application/json",

                headers={

                        "Content-Disposition":
                                f'attachment; filename="{filename}"',

                        # Passwords and keys inside: never cache.
                        "Cache-Control": "no-store"

                }

        )





@app.route("/api/backup/inspect", methods=["POST"])

@login_required

def backup_inspect_api():

        data = request.get_json(silent=True) or {}

        ok, backup = parse_backup(data.get("backup", ""))

        if not ok:

                return jsonify({

                        "success": False,

                        "message": backup

                }), 400



        summary, _ = inspect_backup(backup)

        return jsonify({

                "success": True,

                **summary

        })





@app.route("/api/backup/restore", methods=["POST"])

@login_required

def backup_restore_api():

        data = request.get_json(silent=True) or {}

        areas = data.get("areas")

        return safe_apply_response(restore_backup(

                data.get("backup", ""),

                areas if isinstance(areas, list) else None

        ))





# ------------------------------------------------------------

# Logs

# ------------------------------------------------------------



@app.route("/api/logs/sources")

@login_required

def logs_sources_api():

        return jsonify(get_log_sources())





@app.route("/api/logs")

@login_required

def logs_api():

        return jsonify(get_logs(

                source=request.args.get("source", "app"),

                limit=request.args.get("limit", 200),

                level=request.args.get("level"),

                search=request.args.get("search", "")[:200]

        ))





@app.route("/api/logs/clear", methods=["POST"])

@login_required

def logs_clear_api():

        clear_events()

        return jsonify({

                "success": True,

                "message": "Router event log cleared."

        })





# ------------------------------------------------------------

# Modem + Header

# ------------------------------------------------------------



@app.route("/api/modem")

@login_required

def modem_api():



        return jsonify(get_modem_data())




@app.route("/api/modem/settings")

@login_required

def modem_settings_get_api():

        return jsonify(modem_public_settings())




@app.route("/api/modem/settings", methods=["POST"])

@login_required

def modem_settings_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(save_modem_settings(data))




@app.route("/api/modem/unlock", methods=["POST"])

@login_required

def modem_unlock_api():

        data = request.get_json(silent=True) or {}

        outcome = unlock_sim(data.get("pin"), remember=data.get("remember") is not False)

        return jsonify(outcome), 200 if outcome["success"] else 400





@app.route("/api/header")

@login_required

def header_api():



        traffic = get_traffic()

        modem = get_modem_data()



        return jsonify({

                # Online = the router has a default route to the internet.
                "online": get_default_interface() != "Unknown",

                "modem_state": modem["state"],

                "network": modem["network"],

                "model": modem["model"],

                "carrier": modem["carrier"],

                "ping": None,

                "time": get_time(),

                "user": session["user"],

                "rx": traffic["rx"],

                "tx": traffic["tx"],

                "interface": traffic["interface"]

        })





# ------------------------------------------------------------

# Clients

# ------------------------------------------------------------



def get_viewer_ip():

        # Behind Caddy the request comes from localhost; the browser's
        # address is in X-Forwarded-For. Caddy appends it last, earlier
        # entries come from the client and can be faked.
        if request.remote_addr in LOCALHOST:

                forwarded = request.headers.get("X-Forwarded-For", "")

                if forwarded:
                        return forwarded.split(",")[-1].strip()



        return request.remote_addr





@app.route("/api/clients")

@login_required

def clients_api():

        return jsonify(get_client_list(get_viewer_ip()))




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





@app.route("/api/clients/block", methods=["POST"])

@login_required

def client_block_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                block_device(data.get("mac"), data.get("name"))
        )





@app.route("/api/clients/unblock", methods=["POST"])

@login_required

def client_unblock_api():

        data = request.get_json(silent=True) or {}

        return safe_apply_response(
                unblock_device(data.get("mac"))
        )





@app.route("/api/clients/ping", methods=["POST"])

@login_required

def client_ping_api():

        data = request.get_json(silent=True) or {}

        ok, message = ping_device(str(data.get("ip", "")))

        return jsonify({"success": ok, "message": message})





@app.route("/api/clients/wake", methods=["POST"])

@login_required

def client_wake_api():

        data = request.get_json(silent=True) or {}

        ok, message = wake_device(data.get("mac"), str(data.get("interface", "")))

        return jsonify({"success": ok, "message": message}), 200 if ok else 400





@app.route("/api/clients/rename", methods=["POST"])

@login_required

def rename_client():



        return client_alias()





# ------------------------------------------------------------

# Apps (Apps Addon)

# ------------------------------------------------------------



# Changes that can move the router's LAN addresses: the .local names
# (DNS, mDNS) follow them.
NAME_CHANGES = {
        "/api/network/apply",
        "/api/network/eth0-role",
        "/api/network/lan",
        "/api/wifi/settings",
        "/api/config/confirm",
        "/api/config/revert",
        "/api/backup/restore"
}


@app.after_request
def refresh_names(response):

        if (
                request.method == "POST"
                and request.path in NAME_CHANGES
                and response.status_code == 200
        ):
                router_apps.sync_integration_later()

        return response





@app.route("/api/apps")

@login_required

def apps_api():

        return jsonify(router_apps.get_apps())





@app.route("/api/apps/addon/install", methods=["POST"])

@login_required

def apps_addon_install_api():

        ok, message = router_apps.install_addon()

        return jsonify({"success": ok, "message": message}), 200 if ok else 400





@app.route("/api/apps/<app_id>/<action>", methods=["POST"])

@login_required

def apps_action_api(app_id, action):

        data = request.get_json(silent=True) or {}

        ok, message = router_apps.run_action(
                action, app_id, delete_data=data.get("delete_data") is True
        )

        return jsonify({"success": ok, "message": message}), 200 if ok else 400





@app.route("/api/apps/<app_id>/logs")

@login_required

def apps_logs_api(app_id):

        ok, logs = router_apps.get_logs(app_id)

        return jsonify({"success": ok, "logs": logs if ok else "", "message": "" if ok else logs}), 200 if ok else 400





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





@app.route("/api/system/ping")

@login_required

def system_ping():

        config = get_ping_config()



        return jsonify({

                "enabled": config["enabled"],

                "interval": config["interval"],

                "destination": config["destination"]

        })





@app.route("/api/system/reboot", methods=["POST"])

@login_required

def system_reboot_api():

        ok, message = reboot_system()

        if ok:
                log_event("system", f"Reboot requested by {session.get('user')} from {get_viewer_ip()}.")

        return jsonify({"success": ok, "message": message}), 200 if ok else 400





# ------------------------------------------------------------

# Web shell

# ------------------------------------------------------------



def check_password_again(password):
        """
        Asks for the admin password again (shell). Wrong attempts count
        towards the login lockout. Returns None or an error response.
        """

        address = get_viewer_ip()

        wait = login_retry_after(address)

        if wait:
                return jsonify({"success": False, "message": f"Too many failed attempts. Try again in {wait} seconds."}), 429

        if not verify_login(session.get("user"), str(password or "")):

                lockout = record_login_failure(address)

                log_event("shell", f"Wrong password for the web shell from {address}.", "warning")

                message = f"Wrong password. Locked for {lockout} seconds." if lockout else "Wrong password."

                return jsonify({"success": False, "message": message}), 403

        record_login_success(address)

        return None





@app.route("/api/shell/status")

@login_required

def shell_status_api():

        return jsonify(web_shell.get_shell_status(get_viewer_ip()))





@app.route("/api/shell/settings", methods=["POST"])

@login_required

def shell_settings_api():

        data = request.get_json(silent=True) or {}

        denied = check_password_again(data.get("password"))

        if denied:
                return denied

        return safe_apply_response(web_shell.save_shell_settings(data.get("enabled") is True))





@app.route("/api/shell/unlock", methods=["POST"])

@login_required

def shell_unlock_api():

        address = get_viewer_ip()

        if not web_shell.get_shell_settings()["enabled"]:
                return jsonify({"success": False, "message": "The web shell is turned off (System page)."}), 403

        allowed, reason = web_shell.is_allowed_address(address)

        if not allowed:
                return jsonify({"success": False, "message": reason}), 403

        data = request.get_json(silent=True) or {}

        denied = check_password_again(data.get("password"))

        if denied:
                return denied

        return jsonify({"success": True, "token": web_shell.issue_token(session.get("user"), address)})





@sock.route("/api/shell/ws")

def shell_ws(ws):

        # Same checks as every page, by hand: a WebSocket gets no
        # login_required redirect and no CSRF header.
        address = get_viewer_ip()

        def refuse(message):
                ws.send(f"\r\n\x1b[31m{message}\x1b[0m\r\n")
                ws.close()

        if not is_logged_in():
                return refuse("Not signed in.")

        # Another website always has another host name; ports are left
        # out because not every client sends them in the Host header.
        origin = urlsplit(request.headers.get("Origin", "")).hostname
        host = urlsplit(f"//{request.host}").hostname

        if not origin or origin != host:
                return refuse("Connection refused (wrong origin).")

        if not web_shell.get_shell_settings()["enabled"]:
                return refuse("The web shell is turned off.")

        allowed, reason = web_shell.is_allowed_address(address)

        if not allowed:
                return refuse(reason)

        user = session.get("user")

        if not web_shell.redeem_token(request.args.get("token"), user, address):
                return refuse("The key expired. Enter your password again.")

        # Never longer than the dashboard session itself.
        lifetime = max(0, session.get("created_at", 0) + get_absolute_timeout() - time.time())

        web_shell.run_session(ws, user, address, lifetime)





@app.route("/api/system/factory-reset", methods=["POST"])

@login_required

def system_factory_reset_api():

        data = request.get_json(silent=True) or {}

        user = session.get("user")

        ok, message = factory_reset(user, data.get("password"))

        if ok:
                print(f"[factory-reset] Requested by {user} from {get_viewer_ip()}.", flush=True)

        return jsonify({"success": ok, "message": message}), 200 if ok else 400





@app.route("/api/system/ping", methods=["POST"])

@login_required

def update_ping():

        data = request.get_json() or {}



        enabled = data.get("enabled")

        interval = data.get("interval")

        destination = data.get("destination", "")

        if not isinstance(destination, str):

                return jsonify({

                        "success": False,

                        "message": "Ping destination must be text."

                }), 400

        destination = destination.strip()



        if not isinstance(enabled, bool):

                return jsonify({

                        "success": False,

                        "message": "Ping enabled value must be true or false."

                }), 400



        try:

                interval = int(interval)

        except (TypeError, ValueError):

                return jsonify({

                        "success": False,

                        "message": "Ping interval must be a number."

                }), 400



        if interval not in VALID_PING_INTERVALS:

                return jsonify({

                        "success": False,

                        "message": "Ping interval must be 5, 10, 30, or 60 seconds."

                }), 400



        if not destination:

                return jsonify({

                        "success": False,

                        "message": "Ping destination cannot be empty."

                }), 400



        if len(destination) > 253:

                return jsonify({

                        "success": False,

                        "message": "Ping destination is too long."

                }), 400



        set_ping_config(enabled, interval, destination)



        return jsonify({

                "success": True,

                "enabled": enabled,

                "interval": interval,

                "destination": destination

        })





@app.route("/api/system/ping/value")

@login_required

def system_ping_value():

        config = get_ping_config()



        if not config["enabled"]:

                return jsonify({

                        "enabled": False,

                        "ping": None

                })



        return jsonify({

                "enabled": True,

                "ping": get_ping(config["destination"])

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



        user = session.get("user")

        success, message = change_password(

                current_password,

                new_password

        )

        log_event(
                "auth",
                f"Password changed for {user}." if success
                else f"Password change for {user} failed: {message}",
                "info" if success else "warning"
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

# Startup

# ------------------------------------------------------------



def startup():

        # After a boot, the running config is rebuilt from the
        # persistent (verified) config and applied to the system.
        if sync_boot():

                log_event(
                        "system",
                        "Boot: running config rebuilt from the saved settings."
                )

                transaction.apply_all()

                router_apps.sync_integration_later()

                return



        # The app restarted while changes awaited confirmation.
        transaction.recover_pending()

        # App names and routes, e.g. after an update of Router OS.
        router_apps.sync_integration_later()


def start_setup_wifi():

        # Not set up yet: open the setup Wi-Fi with its captive portal.
        if is_setup_complete():
                return

        ok, result = setup_network.start()

        if ok:
                print(
                        f"[setup] Setup Wi-Fi '{result}' is on. Show its password "
                        f"and QR code with: python backend/setup_wifi.py"
                )
        else:
                print(f"[setup] No setup Wi-Fi: {result}")





# The debug reloader imports this file twice; only the process that
# serves requests runs the startup. CHAOS_SKIP_STARTUP is for tools
# and tests that only need the app object.
if (
        os.getenv("CHAOS_SKIP_STARTUP") != "1"
        and not (
                __name__ == "__main__"
                and os.getenv("WERKZEUG_RUN_MAIN") != "true"
        )
):
        startup()

        start_setup_wifi()





# ------------------------------------------------------------

# Development

# ------------------------------------------------------------



if __name__ == "__main__":

        app.run(

                host="0.0.0.0",

                port=5000,

                debug=True

        )