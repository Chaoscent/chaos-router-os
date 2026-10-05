"""
Every settings area that goes through safe apply (transaction.py).

The order is the order areas are applied at boot: the network first,
then the firewall, then the services that depend on both.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from services import (
    network,
    firewall,
    routing,
    clients,
    dhcp,
    dns,
    wifi,
    wireguard,
    openvpn,
    vpn_profiles
)


@dataclass
class Area:

    name: str
    label: str

    # Applies the running config to the system: () -> (ok, message).
    # None for settings only the app itself reads.
    apply: Optional[Callable] = None

    # Checks the system after applying: () -> (ok, message).
    verify: Optional[Callable] = None

    # What runs now, recorded before the first change: () -> data.
    baseline: Optional[Callable] = None

    # Changes that can cut the user off wait for confirmation.
    confirm: bool = False

    # Holds passwords or keys (files get mode 600).
    secret: bool = False

    # Applied at boot from /etc/chaos-router-os even before the first
    # change, once the installer has written its defaults there.
    boot_defaults: bool = False

    # Areas that read this one's settings (e.g. which interface is the
    # WAN) and are re-applied whenever it changes or is reverted.
    dependents: Tuple[str, ...] = ()


AREAS = {area.name: area for area in (

    # eth0's LAN/WAN mode decides the WAN for everything below.
    Area(
        "network", "Network",
        apply=network.apply_network_settings,
        baseline=network.get_network_baseline,
        confirm=True,
        dependents=(
            "firewall", "routing", "dhcp", "dns",
            "wireguard", "openvpn", "vpn_profiles"
        )
    ),

    # Ships on (see firewall.DEFAULT_SETTINGS): applied at boot from
    # the installed defaults before the first change.
    Area(
        "firewall", "Firewall",
        apply=firewall.apply_firewall,
        verify=firewall.verify_firewall,
        baseline=firewall.get_firewall_settings,
        confirm=True,
        boot_defaults=True
    ),

    # Not confirmed: turning NAT off cuts the internet, not the
    # dashboard. Before the first change it runs on the defaults.
    Area(
        "routing", "Routing & NAT",
        apply=routing.apply_routing,
        verify=routing.verify_routing,
        baseline=routing.get_routing_baseline,
        boot_defaults=True
    ),

    # Blocking your own device locks you out: confirm like the firewall.
    Area(
        "blocked_devices", "Blocked devices",
        apply=clients.apply_blocked,
        verify=clients.verify_blocked,
        baseline=lambda: {"devices": []},
        confirm=True
    ),

    Area(
        "dhcp", "DHCP",
        apply=dhcp.apply_dhcp_settings,
        verify=dhcp.verify_dhcp_settings,
        baseline=dhcp.get_dhcp_settings,
        confirm=True
    ),

    # Applied after DHCP: both restart the same dnsmasq.
    # No baseline: before the first change dnsmasq runs on its own
    # defaults, and reverting there removes our DNS file.
    Area(
        "dns", "DNS",
        apply=dns.apply_dns_settings,
        verify=dns.verify_dns_settings,
        confirm=True
    ),

    Area(
        "wifi", "WiFi",
        apply=wifi.apply_wifi_settings,
        verify=wifi.verify_wifi_settings,
        baseline=wifi.get_wifi_settings,
        confirm=True,
        secret=True
    ),

    Area(
        "wireguard", "WireGuard server",
        apply=wireguard.apply_server,
        verify=wireguard.verify_server,
        baseline=wireguard.load_wireguard,
        confirm=True,
        secret=True
    ),

    Area(
        "openvpn", "OpenVPN server",
        apply=openvpn.apply_server,
        verify=openvpn.verify_server,
        baseline=openvpn.load_openvpn,
        confirm=True,
        secret=True
    ),

    Area(
        "vpn_profiles", "VPN client profiles",
        apply=vpn_profiles.apply_profiles,
        baseline=lambda: {"profiles": vpn_profiles.load_profiles()},
        secret=True
    ),

    # Read only by the app: verified by validation, committed at once.
    Area("device_aliases", "Device names"),
    Area("dashboard", "Dashboard"),
    Area("security", "Session timeouts"),
    Area("users", "Login", secret=True)

)}
