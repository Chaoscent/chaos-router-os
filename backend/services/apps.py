"""
Apps: the Apps page, and how installed apps plug into the router.

The apps themselves come from the Apps Addon (Chaos Router Apps), a
separate install with Docker and the App Manager
(/usr/local/bin/chaos-apps). Core never needs it: without the addon
the Apps page offers to install it (deploy/install-apps.sh).

Every installed app is reached by name, e.g. nextcloud.chaos-router.local
(<app>.chaos-router.local); the router itself is chaos-router.local:

- DNS: dnsmasq answers the name with the router's address on the
  interface the question came in on (its own drop-in file, so it works
  whatever the DNS page's state is).
- mDNS: chaos-router-mdns.service announces the same names with Avahi,
  for devices that look up .local names only that way (Apple devices,
  Linux with nss-mdns).
- Caddy: /etc/caddy/chaos-apps/<app>.caddy sends the name to the app's
  port on 127.0.0.1, over HTTP and HTTPS (deploy/Caddyfile).
- HTTPS: Caddy may make certificates for the names (services/caddy.py).

The names and ports of installed apps are kept in
/var/lib/chaos-router-os/system/apps.json, so DNS and HTTPS never have
to ask the App Manager.

Installing, removing, ... runs as a background job (one at a time);
the Apps page shows its output while it runs.
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time

import psutil

from services.config import load_system, save_system, system_path
from services.network import run_command, privileged
from services.logs import log_event

# Overridable for development and tests.
CLI = os.getenv("CHAOS_APPS_CLI", "/usr/local/bin/chaos-apps")

# Installs the addon (one click on the Apps page).
ADDON_INSTALLER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "deploy", "install-apps.sh")
)

CADDY_APPS_DIR = "/etc/caddy/chaos-apps"

# The router's name in the LAN; apps are <app>.ROUTER_DOMAIN.
ROUTER_DOMAIN = "chaos-router.local"

DNSMASQ_APPS_FILE = "/etc/dnsmasq.d/chaos-router-apps.conf"

# Read by deploy/mdns-publish.sh: "name address" per line.
MDNS_NAMES_FILE = os.path.join(os.path.dirname(system_path("x")), "mdns_names.txt")
MDNS_SERVICE = "chaos-router-mdns"

# System record: {"apps": {id: {"host", "port"}}}
APPS_RECORD = "apps"

ACTIONS = ("install", "start", "stop", "restart", "update", "remove")

ACTION_LABELS = {
    "install": "Installing",
    "start": "Starting",
    "stop": "Stopping",
    "restart": "Restarting",
    "update": "Updating",
    "remove": "Removing",
    "addon": "Installing the Apps Addon"
}

APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

MAX_JOB_LINES = 400

_job = None
_job_lock = threading.Lock()
_sync_lock = threading.Lock()


# -------------------------------------------------------------------
# Addon
# -------------------------------------------------------------------

def addon_installed():
    return os.path.isfile(CLI) and os.access(CLI, os.X_OK)


def cli_json(*args):
    """
    (True, data) from a JSON command of the App Manager, or (False, message).
    """

    ok, output = run_command(privileged([CLI, *args]))

    if not ok:
        return False, output

    try:
        return True, json.loads(output)
    except ValueError:
        return False, "The App Manager gave an unexpected answer."


# -------------------------------------------------------------------
# Names
# -------------------------------------------------------------------

def base_domain():
    """
    The router's name, under which every app gets its own name.
    """

    return ROUTER_DOMAIN


def app_host(app_id):
    return f"{app_id}.{base_domain()}"


def get_app_hosts():
    """
    {app id: host name} of installed apps (for DNS and HTTPS).
    """

    record = load_system(APPS_RECORD, {})
    apps = record.get("apps", {}) if isinstance(record, dict) else {}

    return {
        app_id: info["host"]
        for app_id, info in apps.items()
        if isinstance(info, dict) and info.get("host")
    }


# -------------------------------------------------------------------
# Apps page
# -------------------------------------------------------------------

def get_apps():

    job = job_view()

    if not addon_installed():
        return {
            "addon": {
                "installed": False,
                "can_install": os.path.isfile(ADDON_INSTALLER)
            },
            "apps": [],
            "base_domain": base_domain(),
            "job": job
        }

    ok, version = cli_json("version")

    addon = {
        "installed": True,
        "version": version.get("addon") if ok else None,
        "docker": version.get("docker") if ok else None,
        "docker_running": bool(ok and version.get("running")),
        "compose": version.get("compose") if ok else None,
        "error": None if ok else version
    }

    ok, catalog = cli_json("catalog")

    if not ok:
        addon["error"] = catalog
        catalog = []

    ok, status = cli_json("status")
    status = {s["id"]: s for s in status} if ok else {}

    apps = []

    for entry in catalog:

        app_id = entry.get("id", "")
        installed = status.get(app_id)
        host = (installed or {}).get("host") or app_host(app_id)

        apps.append({
            "id": app_id,
            "name": entry.get("name", app_id),
            "description": entry.get("description", ""),
            "category": entry.get("category", ""),
            "website": entry.get("website", ""),
            "download_mb": entry.get("download_mb"),
            "https": entry.get("https") is True,
            "first_steps": entry.get("first_steps", ""),
            "installed": installed is not None,
            "state": installed["state"] if installed else "not_installed",
            "host": host,
            "urls": {
                "http": f"http://{host}/",
                "https": f"https://{host}/"
            }
        })

    return {
        "addon": addon,
        "apps": apps,
        "base_domain": base_domain(),
        "job": job
    }


# -------------------------------------------------------------------
# Jobs
# -------------------------------------------------------------------

def job_view():

    with _job_lock:

        if not _job:
            return None

        return {
            key: (list(value) if key == "lines" else value)
            for key, value in _job.items()
        }


def _run_job(job, cmd, after):

    def add(line):
        line = ANSI_RE.sub("", line).rstrip()
        if line:
            with _job_lock:
                job["lines"].append(line)
                del job["lines"][:-MAX_JOB_LINES]

    success = False

    try:

        process = subprocess.Popen(
            privileged(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )

        for line in process.stdout:
            add(line)

        success = process.wait() == 0

    except OSError as e:
        add(f"Error: {e}")

    if success and after:
        try:
            after()
        except Exception as e:
            add(f"Warning: the app works, but connecting it to the router failed: {e}")

    with _job_lock:
        job["done"] = True
        job["success"] = success
        job["finished"] = time.time()

    target = job["name"] or "Apps Addon"

    log_event(
        "apps",
        f"{ACTION_LABELS[job['action']]} {target}: {'done' if success else 'failed'}.",
        "info" if success else "error"
    )


def start_job(action, app_id, name, cmd, after=None):

    global _job

    with _job_lock:

        if _job and not _job["done"]:
            return False, "Another app change is running. Wait until it is done."

        _job = {
            "id": int(time.time() * 1000),
            "action": action,
            "app": app_id,
            "name": name,
            "lines": [],
            "done": False,
            "success": None,
            "started": time.time(),
            "finished": None
        }

        job = _job

    threading.Thread(target=_run_job, args=(job, cmd, after), daemon=True).start()

    return True, f"{ACTION_LABELS[action]} {name or 'the Apps Addon'}..."


def install_addon():

    if addon_installed():
        return False, "The Apps Addon is already installed."

    if not os.path.isfile(ADDON_INSTALLER):
        return False, "The addon installer is missing (deploy/install-apps.sh)."

    return start_job("addon", None, None, [ADDON_INSTALLER])


def run_action(action, app_id, delete_data=False):

    if action not in ACTIONS:
        return False, "Unknown action."

    if not addon_installed():
        return False, "The Apps Addon is not installed."

    if not APP_ID_RE.fullmatch(str(app_id or "")):
        return False, "Unknown app."

    ok, catalog = cli_json("catalog")
    entry = next((a for a in catalog if a.get("id") == app_id), None) if ok else None

    if not entry:
        return False, "Unknown app."

    cmd = [CLI, action, app_id]

    if action == "install":
        cmd += ["--host", app_host(app_id)]

    if action == "remove" and delete_data:
        cmd.append("--delete-data")

    # Installing and removing change the router's names and routes.
    after = sync_integration if action in ("install", "remove") else None

    return start_job(action, app_id, entry.get("name", app_id), cmd, after)


# -------------------------------------------------------------------
# Router integration
# -------------------------------------------------------------------

def caddy_snippet(app_id, host, port):

    # Apps are HTTPS only (plain HTTP is redirected).
    return (
        f"# Chardsoft Router OS: app {app_id}. Written by the dashboard, do not edit.\n"
        f"@app-{app_id} host {host}\n"
        f"handle @app-{app_id} {{\n"
        f"\t@app-{app_id}-plain protocol http\n"
        f"\tredir @app-{app_id}-plain https://{{host}}{{uri}} 308\n"
        f"\n"
        f"\treverse_proxy 127.0.0.1:{int(port)}\n"
        f"}}\n"
    )


def _read(path):

    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _write_root_file(path, content):

    fd, tmp = tempfile.mkstemp(prefix="chaos-app-", suffix=".caddy")

    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return run_command(privileged(["install", "-m", "644", tmp, path]))
    finally:
        os.unlink(tmp)


def sync_caddy(apps):
    """
    One Caddy file per installed app; restarts Caddy when they changed.
    """

    if not os.path.isdir(os.path.dirname(CADDY_APPS_DIR)):
        return False, "Caddy is not installed."

    run_command(privileged(["mkdir", "-p", CADDY_APPS_DIR]))

    wanted = {
        f"{app_id}.caddy": caddy_snippet(app_id, info["host"], info["port"])
        for app_id, info in apps.items()
    }

    changed = False

    for name, content in wanted.items():

        path = os.path.join(CADDY_APPS_DIR, name)

        if _read(path) != content:
            ok, result = _write_root_file(path, content)
            if not ok:
                return False, result
            changed = True

    try:
        existing = os.listdir(CADDY_APPS_DIR)
    except OSError:
        existing = []

    for name in existing:
        if name.endswith(".caddy") and name not in wanted:
            run_command(privileged(["rm", "-f", os.path.join(CADDY_APPS_DIR, name)]))
            changed = True

    if not changed:
        return True, "Caddy is up to date."

    # The Caddyfile turns the admin API off: restart, not reload.
    active, _ = run_command(["systemctl", "is-active", "--quiet", "caddy"])

    if active:
        return run_command(privileged(["systemctl", "restart", "caddy"]))

    return True, "Caddy files written."


def dns_interfaces():
    """
    Every interface LAN devices or VPN clients may ask on: LAN ports
    (also while they are bridge ports), the bridge and the VPN servers.
    Interfaces without an address simply give no answer.
    """

    from services.network import is_lan_name, get_wan_interface
    from services.dns import VPN_INTERFACES

    wan = get_wan_interface()

    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        names = []

    found = [n for n in names if is_lan_name(n) and n != wan]

    return list(dict.fromkeys(found + ["br0", *VPN_INTERFACES]))


def dnsmasq_config(apps):

    lines = [
        "# Generated by Chardsoft Router OS: the router's name and the names",
        "# of installed apps. Each name gets the router's address on the",
        "# interface the question came in on.",
        "localise-queries"
    ]

    for host in [base_domain()] + [info["host"] for _, info in sorted(apps.items())]:
        lines += [f"interface-name={host},{iface}" for iface in dns_interfaces()]

    return "\n".join(lines) + "\n"


def sync_dns(apps):

    from services import dhcp

    if not dhcp.has_dnsmasq():
        return True, "dnsmasq is not installed."

    content = dnsmasq_config(apps)

    if _read(DNSMASQ_APPS_FILE) == content:
        return True, "App names are up to date."

    ok, result = dhcp.install_dnsmasq_config(content, path=DNSMASQ_APPS_FILE)

    if not ok:
        return False, result

    return dhcp.restart_dnsmasq()


def mdns_address():
    """
    The address announced over mDNS: one for all names (Avahi cannot
    give each interface its own). A LAN address on an interface that is
    up, the bridge first. Devices on another LAN interface still reach
    it: the router owns all its addresses.
    """

    from services.network import is_lan_name, get_wan_interface, run

    # The internet side: the WAN, and whatever carries the default route
    # (e.g. a VM's NAT adapter).
    route = (run(["ip", "route", "show", "default"]) or "").split()
    internet = {get_wan_interface()} | ({route[route.index("dev") + 1]} if "dev" in route else set())

    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()

    names = sorted(
        (n for n in addresses if n == "br0" or is_lan_name(n)),
        key=lambda n: (n in internet, n != "br0", not n.startswith(("eth", "en")), n)
    )

    # LAN interfaces first; the internet side only when nothing else has
    # an address (e.g. before setup, still connected to a home network).
    for name in names:

        if not stats.get(name) or not stats[name].isup:
            continue

        for entry in addresses[name]:
            if entry.family == socket.AF_INET and not entry.address.startswith("169.254."):
                return entry.address

    return None


def sync_mdns(apps):
    """
    The names file for chaos-router-mdns.service; restarts it on change.
    """

    address = mdns_address()

    hosts = [base_domain()] + [info["host"] for _, info in sorted(apps.items())]

    content = "".join(f"{host} {address}\n" for host in hosts) if address else ""

    if _read(MDNS_NAMES_FILE) == content:
        return True, "mDNS names are up to date."

    try:
        with open(MDNS_NAMES_FILE, "w") as f:
            f.write(content)
    except OSError as e:
        return False, str(e)

    if not os.path.exists(f"/etc/systemd/system/{MDNS_SERVICE}.service"):
        return True, "No mDNS service installed."

    return run_command(privileged(["systemctl", "restart", MDNS_SERVICE]))


def installed_apps():
    """
    {app id: {"host", "port"}} from the App Manager; renamed apps are
    told their current name.
    """

    if not addon_installed():
        return {}

    ok, status = cli_json("status")

    if not ok:
        raise RuntimeError(status)

    apps = {}

    for entry in status:

        app_id = entry.get("id", "")
        port = entry.get("port")

        if not APP_ID_RE.fullmatch(app_id) or not isinstance(port, int):
            continue

        host = app_host(app_id)

        # Installed under an older name: tell the app its current one.
        if entry.get("host") != host:
            run_command(privileged([CLI, "set-host", app_id, host]))

        apps[app_id] = {"host": host, "port": port}

    return apps


def sync_integration():
    """
    Brings the router's names (DNS, mDNS) and the app routes (Caddy) in
    line with the installed apps and the router's addresses. Safe to run
    any time; also without the Apps Addon (chaos-router.local).
    """

    with _sync_lock:

        apps = installed_apps()

        save_system(APPS_RECORD, {"apps": apps})

        syncs = [("DNS names", sync_dns), ("mDNS names", sync_mdns)]

        if addon_installed():
            syncs.append(("Caddy routes", sync_caddy))

        for what, sync in syncs:

            ok, result = sync(apps)

            if not ok:
                log_event("apps", f"{what}: {result}", "warning")


def sync_integration_later():
    """
    sync_integration() in the background (at startup, after network
    changes).
    """

    def run():
        try:
            sync_integration()
        except Exception as e:
            log_event("apps", f"Updating the app names failed: {e}", "warning")

    threading.Thread(target=run, daemon=True).start()


def get_logs(app_id, lines=200):

    if not addon_installed():
        return False, "The Apps Addon is not installed."

    if not APP_ID_RE.fullmatch(str(app_id or "")):
        return False, "Unknown app."

    return run_command(privileged([CLI, "logs", app_id, "--lines", str(int(lines))]))
