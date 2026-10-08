"""
Caddy in front of the dashboard (deploy/Caddyfile).

The service runs gunicorn on CHAOS_BIND:CHAOS_PORT. With Caddy that is
127.0.0.1:5000 and Caddy serves ports 80 (HTTP) and 443 (HTTPS) on
every address; without Caddy (development) the app listens on
0.0.0.0:5000 itself.

Caddy makes HTTPS certificates from its local CA on the first visit,
for the name or address in the browser. Before that it asks the app
(/caddy/tls-allowed), which only allows the router's own LAN addresses
and names (and the names of installed apps), so nobody can make Caddy
create certificates for anything else.
"""

import ipaddress
import os
import socket

import psutil

APP_PORT = os.getenv("CHAOS_PORT", "5000")

BIND = os.getenv("CHAOS_BIND", "0.0.0.0")

LOCALHOST = ("127.0.0.1", "::1")

# The service binds to localhost only when Caddy is in front.
BEHIND_CADDY = BIND in LOCALHOST or BIND == "localhost"


def dashboard_url(address):
    """
    The dashboard's address for people, e.g. "http://192.168.1.1/".
    """

    if BEHIND_CADDY:
        return f"http://{address}/"

    return f"http://{address}:{APP_PORT}/"


def router_addresses():
    """
    IP addresses of the router on the LAN side: every interface except
    the internet uplink (WAN) and the modem.
    """

    # Imported here: services.network is large and imports a lot.
    from services.network import get_wan_interface

    wan = get_wan_interface()
    addresses = set()

    for name, entries in psutil.net_if_addrs().items():

        if name == wan or name.startswith("wwan"):
            continue

        for entry in entries:

            if entry.family not in (socket.AF_INET, socket.AF_INET6):
                continue

            # IPv6 link-local addresses carry a zone: fe80::1%eth0
            address = entry.address.split("%", 1)[0]

            try:
                addresses.add(str(ipaddress.ip_address(address)))
            except ValueError:
                pass

    return addresses


def router_names():
    """
    Host names that lead to the router: its hostname, with .local
    (mDNS) and with the LAN domain from the DHCP page.
    """

    from services.dhcp import get_dhcp_settings

    hostname = socket.gethostname().strip().lower()

    names = {"localhost"}

    if hostname:

        names |= {hostname, f"{hostname}.local"}

        domain = str(get_dhcp_settings().get("domain") or "").strip().lower().strip(".")

        if domain:
            names.add(f"{hostname}.{domain}")

    # The router's LAN name (dnsmasq answers it, see services/apps.py).
    from services.apps import ROUTER_DOMAIN

    names.add(ROUTER_DOMAIN)

    return names


def tls_allowed(name):
    """
    Whether Caddy may make a certificate for this name or address.
    """

    name = str(name or "").strip().lower().rstrip(".")

    if not name:
        return False

    # IPv6 addresses may come in brackets.
    try:
        return str(ipaddress.ip_address(name.strip("[]"))) in router_addresses()
    except ValueError:
        pass

    if name in router_names():
        return True

    # Installed apps (Apps Addon), e.g. nextcloud.chaos-router.lan
    from services.apps import get_app_hosts

    return name in get_app_hosts().values()
