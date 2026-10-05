"""
Routing: IP forwarding and NAT from the LAN to the internet.

Forwarding is the kernel switch (net.ipv4.ip_forward) that lets the
router pass traffic between interfaces at all. NAT (masquerading)
rewrites LAN addresses to the router's WAN address on the way out,
so LAN devices and VPN clients reach the internet.

The WAN is eth0 while it is in WAN mode, otherwise the modem (set on
the Network page; see network.get_wan_interface).

The NAT rule lives in a dedicated chain in the nat table, hooked into
POSTROUTING. ufw only manages the filter table, so enabling, disabling
or reloading the firewall never removes it.

Only IPv4 is handled. Turning on IPv6 forwarding makes the kernel
ignore router advertisements, which can cut the modem's IPv6 off.
"""

from services.config import load_settings

from services import transaction

from services.network import (
    run_command,
    privileged,
    get_wan_interface,
    get_eth0_role
)

from services.vpn_common import (
    which,
    get_lan_networks
)

from services.firewall import is_forwarding_enabled

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

ROUTING = "routing"

DEFAULT_SETTINGS = {
    "forwarding": True,
    "nat": True
}

CHAIN = "CHAOS-NAT"

FORWARD_SYSCTL = "net.ipv4.ip_forward"


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def get_routing_settings():

    settings = load_settings(ROUTING, DEFAULT_SETTINGS)

    return {key: settings[key] for key in DEFAULT_SETTINGS}


def get_routing_baseline():
    """
    What runs before the first change: forwarding as the system has
    it, and no NAT of ours.
    """

    return {
        "forwarding": is_forwarding_enabled(),
        "nat": False
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

    return True, {
        "forwarding": settings["forwarding"],
        "nat": settings["nat"]
    }


def save_routing_settings(data):

    ok, result = validate_routing_settings(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(ROUTING, result)
    outcome["status"] = get_routing_status()

    return outcome


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def nat_rule(wan):

    return ["-o", wan, "-j", "MASQUERADE"]


def iptables(*args):

    tool = which("iptables")

    if not tool:
        return False, "iptables is not available."

    return run_command(privileged([tool, "-t", "nat", *args]))


def is_nat_active(wan):

    hooked, _ = iptables("-C", "POSTROUTING", "-j", CHAIN)

    if not hooked:
        return False

    active, _ = iptables("-C", CHAIN, *nat_rule(wan))

    return active


def get_routing_status():

    settings = get_routing_settings()
    wan = get_wan_interface()

    return {
        "settings": settings,
        "wan": wan,
        "eth0_role": get_eth0_role(),
        "forwarding": is_forwarding_enabled(),
        "nat": is_nat_active(wan),
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

        return False, "iptables is not available."

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
    wan = get_wan_interface()

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

    if settings["nat"] and not is_nat_active(get_wan_interface()):
        return False, "The NAT rule is not active."

    return True, "OK"
