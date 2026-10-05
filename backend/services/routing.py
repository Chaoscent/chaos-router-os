"""
Routing: IP forwarding and NAT from the LAN to the internet.

Forwarding is the kernel switch (net.ipv4.ip_forward) that lets the
router pass traffic between interfaces at all. NAT (masquerading)
rewrites LAN addresses to the router's WAN address on the way out,
so LAN devices and VPN clients reach the internet.

The NAT rule lives in a dedicated chain in the nat table, hooked into
POSTROUTING. ufw only manages the filter table, so enabling, disabling
or reloading the firewall never removes it.

Only IPv4 is handled. Turning on IPv6 forwarding makes the kernel
ignore router advertisements, which can cut the modem's IPv6 off.
"""

import re

from services.config import load_settings

from services import transaction

from services.network import (
    run_command,
    privileged
)

from services.vpn_common import (
    which,
    get_wan_interface,
    get_lan_networks
)

from services.firewall import (
    get_interfaces,
    is_forwarding_enabled
)

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

ROUTING = "routing"

DEFAULT_SETTINGS = {
    "forwarding": True,
    "nat": True,
    # "auto" follows the default route (the modem when it is unknown).
    "wan_interface": "auto"
}

CHAIN = "CHAOS-NAT"

FORWARD_SYSCTL = "net.ipv4.ip_forward"

INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def get_routing_settings():

    return load_settings(ROUTING, DEFAULT_SETTINGS)


def get_routing_baseline():
    """
    What runs before the first change: forwarding as the system has
    it, and no NAT of ours.
    """

    return {
        "forwarding": is_forwarding_enabled(),
        "nat": False,
        "wan_interface": "auto"
    }


def validate_routing_settings(data):
    """
    Returns (True, settings) or (False, message).
    """

    settings = get_routing_settings()
    settings.update(data or {})

    for key in ("forwarding", "nat"):

        if not isinstance(settings.get(key), bool):
            return False, f"Invalid value for {key}."

    wan = settings.get("wan_interface")

    if wan != "auto" and not (
        isinstance(wan, str) and INTERFACE_RE.fullmatch(wan)
    ):
        return False, "Invalid WAN interface."

    return True, {
        "forwarding": settings["forwarding"],
        "nat": settings["nat"],
        "wan_interface": wan
    }


def save_routing_settings(data):

    ok, result = validate_routing_settings(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(ROUTING, result)
    outcome["status"] = get_routing_status()

    return outcome


def resolve_wan(settings=None):

    settings = settings or get_routing_settings()

    if settings["wan_interface"] == "auto":
        return get_wan_interface()

    return settings["wan_interface"]


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def nat_rule(wan):

    return ["-o", wan, "-j", "MASQUERADE"]


def iptables(*args):

    tool = which("iptables")

    if not tool:
        return False, "iptables is not installed."

    return run_command(privileged([tool, "-t", "nat", *args]))


def is_nat_active(wan):

    hooked, _ = iptables("-C", "POSTROUTING", "-j", CHAIN)

    if not hooked:
        return False

    active, _ = iptables("-C", CHAIN, *nat_rule(wan))

    return active


def get_routing_status():

    settings = get_routing_settings()
    wan = resolve_wan(settings)

    return {
        "settings": settings,
        "wan": wan,
        "forwarding": is_forwarding_enabled(),
        "nat": is_nat_active(wan),
        "interfaces": get_interfaces(),
        "lan_networks": get_lan_networks(),
        "installed": bool(which("iptables") and which("sysctl"))
    }


# -------------------------------------------------------------------
# Apply / verify
# -------------------------------------------------------------------

def set_forwarding(enabled):

    tool = which("sysctl")

    if not tool:
        return False, "sysctl is not available."

    return run_command(privileged([
        tool,
        "-w",
        f"{FORWARD_SYSCTL}={1 if enabled else 0}"
    ]))


def apply_nat(enabled, wan):
    """
    Rebuilds the NAT chain: one masquerade rule for the WAN, or none.
    """

    if not which("iptables"):

        if not enabled:
            return True, "NAT off."

        return False, "iptables is not installed."

    # Creating fails harmlessly when the chain exists.
    iptables("-N", CHAIN)

    ok, result = iptables("-F", CHAIN)

    if not ok:
        return False, f"Could not reset NAT: {result}"

    if enabled:

        ok, result = iptables("-A", CHAIN, *nat_rule(wan))

        if not ok:
            return False, f"Could not enable NAT on {wan}: {result}"

    # The hook stays while NAT is off; the chain is just empty.
    hooked, _ = iptables("-C", "POSTROUTING", "-j", CHAIN)

    if not hooked:

        ok, result = iptables("-A", "POSTROUTING", "-j", CHAIN)

        if not ok:
            return False, f"Could not activate NAT: {result}"

    return True, f"NAT on {wan}." if enabled else "NAT off."


def apply_routing():

    settings = get_routing_settings()
    wan = resolve_wan(settings)

    if wan not in get_interfaces() and settings["wan_interface"] != "auto":
        return False, f"Interface {wan} does not exist."

    ok, result = set_forwarding(settings["forwarding"])

    if not ok:
        return False, f"Could not change IP forwarding: {result}"

    ok, result = apply_nat(settings["nat"], wan)

    if not ok:
        return False, result

    forwarding = "on" if settings["forwarding"] else "off"

    return True, f"Forwarding {forwarding}. {result}"


def verify_routing():

    settings = get_routing_settings()

    if is_forwarding_enabled() != settings["forwarding"]:
        return False, "IP forwarding did not reach the requested state."

    if settings["nat"] and not is_nat_active(resolve_wan(settings)):
        return False, "The NAT rule is not active."

    return True, "OK"
