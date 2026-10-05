"""
Helpers shared by the WireGuard, OpenVPN and VPN client modules.
"""

import ipaddress
import os
import re
import shutil
import subprocess
import tempfile

from services.network import (
    run,
    run_command,
    privileged,
    get_wan_interface
)

from services import firewall

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# VPN tools live in /usr/sbin, which is often missing from a user's PATH.
SBIN_PATH = os.pathsep.join([
    os.environ.get("PATH", ""),
    "/usr/sbin",
    "/sbin"
])

DEFAULT_WAN_INTERFACE = "wwan0"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")

FIREWALL_COMMENT = "Chaos Router OS"


# -------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------

def which(name):

    return shutil.which(name, path=SBIN_PATH)


def valid_name(name):

    return bool(NAME_RE.fullmatch(str(name or "")))


# -------------------------------------------------------------------
# Root-owned files
# -------------------------------------------------------------------

def write_root_file(path, content, mode="600"):

    fd, tmp = tempfile.mkstemp(prefix="chaos-vpn-")

    try:

        with os.fdopen(fd, "w") as f:
            f.write(content)

        # -D creates missing parent directories.
        return run_command(privileged([
            "install",
            "-D",
            "-m",
            mode,
            tmp,
            path
        ]))

    finally:

        os.unlink(tmp)


def read_root_file(path):
    """
    Returns (ok, exact file content). Unlike run_command, nothing is
    stripped, so files round-trip byte for byte.
    """

    try:

        result = subprocess.run(
            privileged(["cat", path]),
            text=True,
            capture_output=True
        )

    except Exception as e:
        return False, str(e)

    if result.returncode != 0:
        return False, result.stderr.strip() or f"Could not read {path}."

    return True, result.stdout


def remove_root_file(path):

    return run_command(privileged(["rm", "-f", path]))


# -------------------------------------------------------------------
# systemd
# -------------------------------------------------------------------

def unit_active(unit):

    return run(["systemctl", "is-active", unit]) == "active"


def unit_enabled(unit):

    return run(["systemctl", "is-enabled", unit]) == "enabled"


def systemctl(*args):

    return run_command(privileged(["systemctl", *args]))


def unit_error(unit):

    ok, output = run_command(privileged([
        "journalctl",
        "-u",
        unit,
        "-n",
        "5",
        "--no-pager",
        "-o",
        "cat"
    ]))

    return output if ok and output else f"{unit} failed to start."


def start_unit(unit, enable=True):
    """
    (Re)starts a unit and optionally enables it at boot.
    Returns (ok, message) with the unit's log on failure.
    """

    if enable:

        ok, result = systemctl("enable", unit)

        if not ok:
            return False, result

    ok, _ = systemctl("restart", unit)

    if not ok:
        return False, unit_error(unit)

    return True, "OK"


def stop_unit(unit):

    systemctl("disable", unit)

    return systemctl("stop", unit)


# -------------------------------------------------------------------
# Networking
# -------------------------------------------------------------------

def get_lan_interfaces():

    return firewall.get_lan_interfaces()


def get_lan_networks():
    """
    LAN subnets in CIDR form, e.g. ["192.168.1.0/24"].
    """

    networks = []

    for interface in get_lan_interfaces():

        output = run(["ip", "-4", "-o", "addr", "show", interface])

        for line in (output or "").splitlines():

            if "inet " not in line:
                continue

            try:
                networks.append(str(ipaddress.IPv4Interface(
                    line.split("inet ", 1)[1].split()[0]
                ).network))
            except ValueError:
                pass

    return networks


# -------------------------------------------------------------------
# Firewall integration
# -------------------------------------------------------------------

def firewall_rules_for(description, rules):
    """
    Tags ufw rule args with a recognisable comment.
    """

    return [
        rule + ["comment", f"{FIREWALL_COMMENT}: {description}"]
        for rule in rules
    ]


def sync_firewall(owner, rules):
    """
    Makes ufw hold exactly these rules for this owner (rules are kept
    even while the firewall is off, so VPNs work once it is enabled).
    Returns a warning string, or None.
    """

    ok, result = firewall.sync_rules(owner, rules)

    return None if ok else f"Firewall rules could not be updated: {result}"
