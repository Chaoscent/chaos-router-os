"""
Factory reset: back to a freshly installed router.

1. Every settings area is set back to its defaults (/etc/chaos-router-os,
   else the built-in ones) and applied: Wi-Fi, DHCP, DNS, VPNs off, own
   firewall rules removed, LAN bridge removed. eth0's own connection
   is left as it is, so the router stays reachable.
2. Generated secrets are deleted (OpenVPN certificates, WireGuard and
   hostapd configs, VPN client profiles).
3. /var/lib/chaos-router-os and /tmp/chaos-router-os are emptied.
4. The router reboots. At boot the defaults from /etc are applied
   (firewall, NAT) and, with no admin account, the setup Wi-Fi with its
   captive portal starts (see setup.py, services/setup_network.py).

Runs in the background after the request is answered.
"""

import shutil
import threading
import time

from services.config import (
    STATE_DIR,
    RUNTIME_DIR,
    load_defaults,
    save_running,
    delete_running
)

from services.network import run_command, privileged

from services import (
    wifi,
    dhcp,
    firewall,
    routing,
    wireguard,
    openvpn,
    vpn_profiles
)

from services.vpn_common import stop_unit, sync_firewall, remove_root_file

from services.system import can_reboot

# Time for the browser to get the answer before services go down.
START_DELAY = 2


def log(message):

    # The event log is erased with everything else; the app's own
    # output (journal) keeps the record.
    print(f"[factory-reset] {message}", flush=True)


# -------------------------------------------------------------------
# Services back to defaults
# -------------------------------------------------------------------

def remove_vpn_profiles():
    """
    Stops and deletes every VPN client profile, including its unit
    (otherwise an autostart profile would come back at boot).
    """

    for profile in vpn_profiles.load_profiles():

        stop_unit(vpn_profiles.unit_name(profile))
        sync_firewall(vpn_profiles.firewall_owner(profile), [])
        remove_root_file(vpn_profiles.config_path(profile))

        if profile["type"] == "openvpn":
            remove_root_file(vpn_profiles.auth_path(profile))


def factory_settings():
    """
    The running config each area is applied with, in order: services
    that depend on the network first, the network itself last.
    None means "not managed": the area removes its own files.
    """

    return [
        ("vpn_profiles", {"profiles": []}),
        ("openvpn", {"server": {"enabled": False}, "clients": []}),
        ("wireguard", {"server": {"enabled": False}, "peers": []}),
        ("wifi", {**load_defaults(wifi.WIFI_SETTINGS, wifi.DEFAULT_SETTINGS), "enabled": False}),
        ("dns", None),
        ("dhcp", {**load_defaults(dhcp.DHCP_SETTINGS, dhcp.DEFAULT_SETTINGS), "enabled": False}),
        ("blocked_devices", {"devices": []}),
        ("routing", load_defaults(routing.ROUTING, routing.DEFAULT_SETTINGS)),
        # With /etc defaults: on with the essential rules, own rules gone.
        ("firewall", load_defaults(firewall.FIREWALL, firewall.BUILTIN_FIREWALL)),
        # No interface changes: eth0 keeps its connection. The LAN
        # bridge (and eth0 as its port) is removed.
        ("network", {"interfaces": {}, "eth0_role": "lan", "lan": {"bridge": False}})
    ]


def reset_services():

    from services.areas import AREAS

    try:
        remove_vpn_profiles()
    except Exception as e:
        log(f"VPN profiles: {e}")

    for name, data in factory_settings():

        area = AREAS[name]

        try:

            if data is None:
                delete_running(name)
            else:
                save_running(name, data, secret=area.secret)

            ok, message = area.apply() if area.apply else (True, "OK")

            log(f"{area.label}: {message}" if ok else f"{area.label} failed: {message}")

        except Exception as e:
            log(f"{area.label} failed: {e}")


def remove_secrets():

    for path in (
        openvpn.PKI_DIR,
        openvpn.SERVER_CONF,
        wireguard.SERVER_CONF,
        wifi.HOSTAPD_CONF_FILE
    ):

        ok, result = run_command(privileged(["rm", "-rf", path]))

        if not ok:
            log(f"Could not remove {path}: {result}")


def empty_directory(directory):
    """
    Deletes everything inside, keeps the directory (and its owner).
    """

    if not directory.exists():
        return

    for path in directory.iterdir():

        try:

            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()

        except OSError as e:
            log(f"Could not delete {path}: {e}")


# -------------------------------------------------------------------
# Run
# -------------------------------------------------------------------

def run_reset():

    time.sleep(START_DELAY)

    log("Started.")

    reset_services()
    remove_secrets()

    empty_directory(STATE_DIR)
    empty_directory(RUNTIME_DIR)

    log("Settings erased. Rebooting.")

    # The app is in setup mode from here on, even before the reboot.
    import setup
    setup._complete = False

    ok, result = run_command(privileged(["systemctl", "reboot"]))

    if not ok:

        # No reboot: open the setup Wi-Fi right away instead.
        log(f"Reboot failed ({result}); starting the setup Wi-Fi now.")

        from services import setup_network

        setup_network.start()


def factory_reset(username, password):
    """
    Checks the admin's password and that the router may reboot, then
    resets in the background. Returns (success, message).
    """

    from auth import verify_login

    if not username or not verify_login(username, str(password or "")):
        return False, "Wrong password."

    ok, message = can_reboot()

    if not ok:
        return False, f"Factory reset needs a reboot. {message}"

    threading.Thread(target=run_reset, name="factory-reset", daemon=True).start()

    return True, "Erasing all settings. The router reboots in a moment."
