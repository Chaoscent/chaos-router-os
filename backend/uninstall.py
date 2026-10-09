"""
System part of the uninstaller: undoes what Chardsoft Router OS changed on
the system, before uninstall.sh deletes its files and packages.

    sudo .venv/bin/python backend/uninstall.py [--dry-run]

Runs as root, with the router's settings still in place (they say what
is set up). Like the factory reset, every area is switched off through
its own code, but further:

- Wi-Fi, DHCP, DNS, VPN servers and client profiles off, their units,
  configs, keys and certificates removed.
- Firewall: every rule Chardsoft Router OS added removed, ufw off.
- IP forwarding and NAT off; the CHAOS-NAT, CHAOS-SETUP and CHAOS-BLOCK
  iptables chains removed.
- LAN bridge removed. The WAN/LAN routing properties Chardsoft Router OS set
  on Ethernet connections (never-default, route-metric) go back to
  NetworkManager's defaults. eth0's address settings stay as they are,
  so the router stays reachable.
- Config files Chardsoft Router OS wrote: dnsmasq drop-ins, hostapd, Caddy
  app routes, the OpenVPN NAT script.

Errors are reported and skipped: an uninstall goes as far as it can.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["CHAOS_SKIP_STARTUP"] = "1"
os.environ["CHAOS_SETUP_WIFI"] = "0"
os.environ.setdefault("SECRET_KEY", "uninstall-only")

DRY_RUN = "--dry-run" in sys.argv

# Files Chardsoft Router OS writes outside its own folders.
DNSMASQ_FILES = (
    "/etc/dnsmasq.d/chaos-router-dhcp.conf",
    "/etc/dnsmasq.d/chaos-router-dns.conf",
    "/etc/dnsmasq.d/chaos-router-setup.conf",
    "/etc/dnsmasq.d/chaos-router-apps.conf"
)

CADDY_APPS_DIR = "/etc/caddy/chaos-apps"

problems = []


def say(message):
    print(f"    {message}", flush=True)


def step(label, func, *args):
    """
    Runs one part; reports instead of stopping on errors.
    """

    if DRY_RUN:
        say(f"would: {label}")
        return

    try:
        result = func(*args)
    except Exception as e:
        problems.append(f"{label}: {e}")
        say(f"! {label}: {e}")
        return

    if isinstance(result, tuple) and len(result) == 2 and result[0] is False:
        problems.append(f"{label}: {result[1]}")
        say(f"! {label}: {result[1]}")
    else:
        say(f"ok: {label}")


# -------------------------------------------------------------------
# Areas off
# -------------------------------------------------------------------

def area_settings():
    """
    Each area switched off, in order: everything that depends on the
    network first, the network last. None: the area removes its file.
    """

    from services.config import load_defaults
    from services import wifi, dhcp, firewall, modem

    return [
        ("vpn_profiles", {"profiles": []}),
        ("openvpn", {"server": {"enabled": False}, "clients": []}),
        ("wireguard", {"server": {"enabled": False}, "peers": []}),
        ("wifi", wifi.off_settings()),
        # The modem's connection is removed (and with it the saved PIN).
        ("modem", dict(modem.DEFAULT_SETTINGS)),
        ("dns", None),
        ("dhcp", dhcp.off_settings()),
        ("blocked_devices", {"devices": []}),
        ("routing", {"forwarding": False, "nat": False}),
        ("firewall", {
            **load_defaults(firewall.FIREWALL, firewall.BUILTIN_FIREWALL),
            "enabled": False,
            "essentials": False,
            "rules": [],
            "logging": "low",
            "policies": {"incoming": "deny", "outgoing": "allow", "routed": "deny"}
        }),
        ("network", {"interfaces": {}, "eth0_role": "lan", "lan": {"bridge": False}})
    ]


def area_off(name, data):

    from services.areas import AREAS
    from services.config import save_running, delete_running

    area = AREAS[name]

    if data is None:
        delete_running(name)
    else:
        save_running(name, data, secret=area.secret)

    return area.apply() if area.apply else (True, "OK")


def remove_vpn_profiles():

    from factory_reset import remove_vpn_profiles as remove

    remove()


# -------------------------------------------------------------------
# Leftovers the areas keep while switched off
# -------------------------------------------------------------------

def remove_ufw_rules():
    """
    Every rule still in the ledger (any owner): the VPNs, the essential
    rules, the user's rules.
    """

    from services.config import load_system
    from services import firewall

    ledger = load_system(firewall.RULE_LEDGER, {})

    for owner in list(ledger):

        ok, result = firewall.sync_rules(owner, [])

        if not ok:
            return False, f"{owner}: {result}"

    return True, "OK"


def remove_chain(tool, table, chain, parents):

    from services.network import run_command, privileged

    for parent in parents:
        # Delete every hook (there may be more than one).
        for _ in range(10):
            ok, _result = run_command(privileged([tool, "-t", table, "-D", parent, "-j", chain]))
            if not ok:
                break

    run_command(privileged([tool, "-t", table, "-F", chain]))
    run_command(privileged([tool, "-t", table, "-X", chain]))

    return True, "OK"


def remove_chains():

    from shutil import which

    from services import routing, clients, setup_network

    for tool in filter(None, (which("iptables"), which("ip6tables"))):
        remove_chain(tool, "filter", clients.CHAIN, ("INPUT", "FORWARD"))

    if which("iptables"):
        remove_chain(which("iptables"), "nat", routing.CHAIN, ("POSTROUTING",))
        remove_chain(which("iptables"), "nat", setup_network.NAT_CHAIN, ("PREROUTING",))

    return True, "OK"


def remove_files():

    from services.network import run_command, privileged
    from services import wifi, wireguard, openvpn

    paths = [
        *DNSMASQ_FILES,
        CADDY_APPS_DIR,
        *wifi.config_files(),
        wireguard.SERVER_CONF,
        openvpn.SERVER_CONF,
        openvpn.PKI_DIR,
        openvpn.NAT_SCRIPT
    ]

    failed = []

    for path in paths:

        if not os.path.lexists(path):
            continue

        ok, result = run_command(privileged(["rm", "-rf", path]))

        if not ok:
            failed.append(f"{path}: {result}")

    return (False, "; ".join(failed)) if failed else (True, "OK")


def restart_dnsmasq():

    from services import dhcp

    if not dhcp.has_dnsmasq():
        return True, "OK"

    # dnsmasq runs on with its own defaults (or is removed with its
    # package afterwards).
    return dhcp.restart_dnsmasq()


def reset_route_properties():
    """
    never-default / route-metric back to NetworkManager's defaults on
    connections where Chardsoft Router OS set them (LAN: never-default yes;
    WAN: route-metric 50). Active connections get them right away.
    """

    from services.network import run, run_command, has_networkmanager, WAN_ROUTE_METRIC

    if not has_networkmanager():
        return True, "OK"

    output = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"]) or ""

    changed = []

    for line in output.splitlines():

        # nmcli -t escapes ":" in names as "\:".
        parts = line.replace("\\:", "\0").split(":")

        if len(parts) < 3:
            continue

        name, kind, device = (p.replace("\0", ":") for p in parts[:3])

        if kind != "802-3-ethernet":
            continue

        values = run(["nmcli", "-g", "ipv4.never-default,ipv4.route-metric", "connection", "show", name]) or ""
        never_default, _, metric = values.partition("\n")

        properties = []

        if never_default.strip() == "yes":
            properties += ["ipv4.never-default", "no"]

        if metric.strip() == WAN_ROUTE_METRIC:
            properties += ["ipv4.route-metric", "-1"]

        if not properties:
            continue

        ok, result = run_command(["nmcli", "connection", "modify", name, *properties])

        if not ok:
            return False, f"{name}: {result}"

        if device:
            # Without taking the connection down (keeps SSH alive).
            run_command(["nmcli", "device", "reapply", device])

        changed.append(name)

    return True, ", ".join(changed) or "OK"


def report_eth0():
    """
    What eth0 keeps (its address settings stay as they are).
    """

    from services.network import run

    method = run(["nmcli", "-g", "IP4.ADDRESS,GENERAL.CONNECTION", "device", "show", "eth0"])

    if method:
        address, _, connection = method.partition("\n")
        say(f"eth0 keeps its connection '{connection.strip()}' ({address.strip() or 'no address'}).")

    return True, "OK"


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():

    if os.geteuid() != 0 and not DRY_RUN:
        print("Run as root (uninstall.sh does).", file=sys.stderr)
        return 1

    step("VPN client profiles", remove_vpn_profiles)

    from services.areas import AREAS

    for name, data in area_settings():
        step(f"{AREAS[name].label} off", area_off, name, data)

    step("Firewall rules", remove_ufw_rules)
    step("iptables chains (CHAOS-NAT, CHAOS-SETUP, CHAOS-BLOCK)", remove_chains)
    step("Config files (dnsmasq, hostapd, VPN, Caddy routes)", remove_files)
    step("dnsmasq restarted", restart_dnsmasq)
    step("Routing properties of Ethernet connections", reset_route_properties)

    if not DRY_RUN:
        report_eth0()

    if problems:
        say(f"{len(problems)} step(s) had problems (see above); the uninstall goes on.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
