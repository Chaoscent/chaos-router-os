"""
DNS server (dnsmasq), managed through safe apply as the "dns" area.

dnsmasq also runs DHCP (services/dhcp.py); each has its own drop-in
file and a restart applies both. DNS is never served on the WAN, so
the router cannot become an open resolver on the internet.
"""

import ipaddress
import os
import random
import re
import socket
import struct
import time

from services.config import load_settings, load_running

from services import transaction

from services.network import (
    unit_stays_active,
    get_lan_interface_names,
    effective_interface
)

from services.dhcp import (
    has_dnsmasq,
    install_dnsmasq_config,
    remove_dnsmasq_config,
    restart_dnsmasq,
    get_dhcp_settings
)

from services.firewall import get_interfaces

from services.vpn_common import get_wan_interface, DEFAULT_WAN_INTERFACE

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# dns.json in /etc/chaos-router-os (defaults) and /var/lib/chaos-router-os.
DNS_SETTINGS = "dns"

DNSMASQ_DNS_FILE = "/etc/dnsmasq.d/chaos-router-dns.conf"

TRUST_ANCHORS = "/usr/share/dnsmasq-base/trust-anchors.conf"

# VPN server interfaces, offered even before they exist
# (bind-dynamic picks them up when they appear).
VPN_INTERFACES = ("wg0", "ovpns0")

UPSTREAM_PRESETS = {
    "cloudflare": ("Cloudflare", ["1.1.1.1", "1.0.0.1"]),
    "quad9": ("Quad9 (blocks malware)", ["9.9.9.9", "149.112.112.112"]),
    "google": ("Google", ["8.8.8.8", "8.8.4.4"]),
    "adguard": ("AdGuard (blocks ads)", ["94.140.14.14", "94.140.15.15"])
}

DEFAULT_SETTINGS = {
    "enabled": True,
    # "preset" (one of UPSTREAM_PRESETS), "custom" or "isp".
    "upstream_mode": "preset",
    "upstream_preset": "cloudflare",
    "upstream_servers": [],
    "interfaces": ["eth0", "wlan0", "br0", "wg0", "ovpns0"],
    "cache_size": 1000,
    "dnssec": False,
    "log_queries": False,
    # Never send plain names or private reverse lookups upstream.
    "keep_local": True,
    "records": [],
    "blocked_domains": []
}

MAX_RECORDS = 500
MAX_BLOCKED = 5000

LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"

NAME_RE = re.compile(rf"^{LABEL}(\.{LABEL})*$")

# Upstream server, optionally with a port: 1.1.1.1 or 1.1.1.1#5353.
SERVER_RE = re.compile(r"^([0-9A-Fa-f:.]+)(#(\d{1,5}))?$")


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def get_dns_settings():

    return load_settings(DNS_SETTINGS, DEFAULT_SETTINGS)


def get_dhcp_interfaces():
    """
    Interfaces dnsmasq serves DHCP on always get DNS too, because the
    DHCP config's interface= line enables both.
    """

    dhcp = get_dhcp_settings()

    return [dhcp["interface"]] if dhcp["enabled"] else []


def get_interface_choices():

    existing = get_interfaces()
    forced = get_dhcp_interfaces()

    choices = []

    for name in get_lan_interface_names() + list(VPN_INTERFACES):

        if name not in existing and name not in VPN_INTERFACES:
            continue

        choices.append({
            "name": name,
            "label": {
                "wg0": "WireGuard devices (wg0)",
                "ovpns0": "OpenVPN devices (ovpns0)"
            }.get(name, name),
            "forced": name in forced
        })

    return choices


def get_upstream_servers(settings):

    mode = settings["upstream_mode"]

    if mode == "preset":
        return UPSTREAM_PRESETS[settings["upstream_preset"]][1]

    if mode == "custom":
        return settings["upstream_servers"]

    return []


def describe_upstream(settings):

    mode = settings["upstream_mode"]

    if mode == "preset":
        return UPSTREAM_PRESETS[settings["upstream_preset"]][0]

    if mode == "isp":
        return "Modem / ISP"

    return ", ".join(settings["upstream_servers"]) or "None"


def valid_name(name):

    return len(name) <= 253 and bool(NAME_RE.fullmatch(name))


def validate_server(entry):

    match = SERVER_RE.fullmatch(entry)

    if not match:
        return False

    try:
        ipaddress.ip_address(match.group(1))
    except ValueError:
        return False

    port = match.group(3)

    return not port or 1 <= int(port) <= 65535


def validate_dns_settings(data):
    """
    Returns (True, settings) or (False, message).
    """

    settings = get_dns_settings()
    settings.update(data or {})

    mode = settings.get("upstream_mode")

    if mode not in ("preset", "custom", "isp"):
        return False, "Invalid upstream mode."

    preset = settings.get("upstream_preset")

    if mode == "preset" and preset not in UPSTREAM_PRESETS:
        return False, "Unknown DNS provider."

    servers = [
        str(s).strip() for s in settings.get("upstream_servers") or []
        if str(s).strip()
    ]

    if mode == "custom":

        if not servers:
            return False, "Enter at least one upstream DNS server."

        if len(servers) > 4:
            return False, "At most four upstream servers."

        for server in servers:

            if not validate_server(server):
                return False, f"Invalid upstream server: {server}"

    choices = [c["name"] for c in get_interface_choices()]

    interfaces = [
        i for i in settings.get("interfaces") or []
        if i in choices
    ]

    try:
        cache_size = int(settings.get("cache_size"))
    except (TypeError, ValueError):
        return False, "Invalid cache size."

    if not 0 <= cache_size <= 10000:
        return False, "Cache size must be between 0 and 10000."

    dnssec = settings.get("dnssec") is True

    if dnssec and settings.get("enabled") and not os.path.exists(TRUST_ANCHORS):
        return False, "DNSSEC needs dnsmasq's trust anchors, which were not found."

    records = []
    seen = set()

    for record in settings.get("records") or []:

        name = str(record.get("name", "")).strip().lower().rstrip(".")
        ip = str(record.get("ip", "")).strip()

        if not valid_name(name):
            return False, f"Invalid record name: {name or '(empty)'}"

        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            return False, f"Invalid address for {name}: {ip or '(empty)'}"

        if (name, ip) in seen:
            continue

        seen.add((name, ip))
        records.append({"name": name, "ip": ip})

    if len(records) > MAX_RECORDS:
        return False, f"At most {MAX_RECORDS} local records."

    blocked = []

    for domain in settings.get("blocked_domains") or []:

        # Drop comments: whole lines and "domain # note".
        domain = str(domain).split("#", 1)[0].strip().lower()

        parts = domain.split()

        # Hosts-file style lines: "0.0.0.0 ads.example.com".
        if len(parts) == 2:
            try:
                ipaddress.ip_address(parts[0])
                domain = parts[1]
            except ValueError:
                pass

        domain = domain.rstrip(".")

        if not domain:
            continue

        if not valid_name(domain):
            return False, f"Invalid domain to block: {domain}"

        if domain not in blocked:
            blocked.append(domain)

    if len(blocked) > MAX_BLOCKED:
        return False, f"At most {MAX_BLOCKED} blocked domains."

    return True, {
        "enabled": settings.get("enabled") is True,
        "upstream_mode": mode,
        "upstream_preset": preset if preset in UPSTREAM_PRESETS else "cloudflare",
        "upstream_servers": servers,
        "interfaces": interfaces,
        "cache_size": cache_size,
        "dnssec": dnssec,
        "log_queries": settings.get("log_queries") is True,
        "keep_local": settings.get("keep_local") is True,
        "records": records,
        "blocked_domains": blocked
    }


# -------------------------------------------------------------------
# dnsmasq config
# -------------------------------------------------------------------

def render_dns_config(settings):

    lines = [
        "# Generated by Chaos Router OS. Do not edit by hand.",
        "# Changes are overwritten from the DNS page.",
        ""
    ]

    if not settings["enabled"]:

        # DNS off; dnsmasq keeps running DHCP.
        lines.append("port=0")

        return "\n".join(lines) + "\n"

    # Listen on interfaces as they appear (VPN servers start later).
    lines.append("bind-dynamic")

    # Never answer the internet.
    for wan in sorted({DEFAULT_WAN_INTERFACE, get_wan_interface()}):
        lines.append(f"except-interface={wan}")

    # Bridge ports (eth0 in br0) are served on their bridge.
    for interface in dict.fromkeys(effective_interface(i) for i in settings["interfaces"]):
        lines.append(f"interface={interface}")

    lines.append(f"cache-size={settings['cache_size']}")

    if settings["keep_local"]:

        lines += ["domain-needed", "bogus-priv"]

        domain = get_dhcp_settings()["domain"]

        if domain:
            # Names in the local domain are answered here, never upstream.
            lines += [f"local=/{domain}/", "expand-hosts"]

    servers = get_upstream_servers(settings)

    if servers:
        # Ignore /etc/resolv.conf and use these servers only.
        lines.append("no-resolv")
        lines += [f"server={server}" for server in servers]

    if settings["dnssec"]:
        lines += [f"conf-file={TRUST_ANCHORS}", "dnssec"]

    if settings["log_queries"]:
        lines.append("log-queries")

    if settings["records"]:

        lines += ["", "# Local records"]

        lines += [
            f"host-record={r['name']},{r['ip']}"
            for r in settings["records"]
        ]

    if settings["blocked_domains"]:

        lines += ["", "# Blocked domains (answered with 0.0.0.0 / ::)"]

        lines += [
            f"address=/{domain}/#"
            for domain in settings["blocked_domains"]
        ]

    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------
# Apply
# -------------------------------------------------------------------

def save_dns_settings(data, confirm=None):

    ok, result = validate_dns_settings(data)

    if not ok:
        return transaction.result(False, result)

    outcome = transaction.change(DNS_SETTINGS, result, confirm=confirm)
    outcome["settings"] = get_dns_settings()

    return outcome


def apply_dns_settings():

    settings = get_dns_settings()

    # Never changed from the dashboard (or reverted to that state):
    # dnsmasq runs with its own defaults, without our file.
    if load_running(DNS_SETTINGS, None) is None:

        if not has_dnsmasq():
            return True, "DNS settings not managed."

        remove_dnsmasq_config(DNSMASQ_DNS_FILE)

        ok, result = restart_dnsmasq()

        return ok, "DNS settings not managed." if ok else result

    if not has_dnsmasq():

        if not settings["enabled"]:
            return True, "DNS server off."

        return False, "dnsmasq is not available."

    ok, result = install_dnsmasq_config(
        render_dns_config(settings),
        DNSMASQ_DNS_FILE
    )

    if not ok:
        return False, f"DNS settings could not be applied: {result}"

    ok, result = restart_dnsmasq()

    if not ok:
        return False, f"dnsmasq failed to restart: {result}"

    return True, (
        "DNS server applied." if settings["enabled"] else "DNS server off."
    )


def verify_dns_settings():

    if not has_dnsmasq():
        return True, "OK"

    ok, message = unit_stays_active("dnsmasq")

    if not ok:
        return False, message

    if not get_dns_settings()["enabled"]:
        return True, "OK"

    # Any answer (even NXDOMAIN) proves the server is listening.
    result = dns_query("localhost", "A")

    if result["error"]:
        return False, f"The DNS server does not answer: {result['error']}"

    return True, "OK"


# -------------------------------------------------------------------
# Records and blocklist (no confirmation: they cannot cut you off)
# -------------------------------------------------------------------

def add_record(name, ip):

    settings = get_dns_settings()

    records = settings["records"] + [{"name": name, "ip": ip}]

    return save_dns_settings({"records": records}, confirm=False)


def remove_record(name, ip):

    settings = get_dns_settings()

    records = [
        r for r in settings["records"]
        if not (r["name"] == name and r["ip"] == ip)
    ]

    if len(records) == len(settings["records"]):
        return transaction.result(False, "Record not found.")

    return save_dns_settings({"records": records}, confirm=False)


def set_blocked_domains(domains):

    if isinstance(domains, str):
        domains = domains.splitlines()

    return save_dns_settings({"blocked_domains": domains}, confirm=False)


# -------------------------------------------------------------------
# DNS client (lookups, verification, cache statistics)
# -------------------------------------------------------------------

QTYPES = {"A": 1, "NS": 2, "CNAME": 5, "PTR": 12, "MX": 15, "TXT": 16, "AAAA": 28}
QTYPE_NAMES = {v: k for k, v in QTYPES.items()}

RCODES = {
    0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL",
    3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED"
}

CLASS_IN = 1
CLASS_CHAOS = 3


def _encode_name(name):

    out = b""

    for label in name.rstrip(".").split("."):

        raw = label.encode("idna") if label else b""

        if not raw or len(raw) > 63:
            raise ValueError("Invalid name.")

        out += bytes([len(raw)]) + raw

    return out + b"\x00"


def _read_name(buf, offset, depth=0):
    """
    Reads a (possibly compressed) name; returns (name, next offset).
    """

    labels = []
    jumped_end = None

    while True:

        if offset >= len(buf) or depth > 20:
            raise ValueError("Malformed name.")

        length = buf[offset]

        if length & 0xC0 == 0xC0:

            pointer = struct.unpack("!H", buf[offset:offset + 2])[0] & 0x3FFF

            if jumped_end is None:
                jumped_end = offset + 2

            offset = pointer
            depth += 1
            continue

        if length == 0:
            offset += 1
            break

        labels.append(buf[offset + 1:offset + 1 + length].decode("ascii", "replace"))
        offset += 1 + length

    return ".".join(labels), (jumped_end if jumped_end is not None else offset)


def _parse_rdata(buf, offset, rtype, length):

    data = buf[offset:offset + length]

    if rtype == 1 and length == 4:
        return socket.inet_ntop(socket.AF_INET, data)

    if rtype == 28 and length == 16:
        return socket.inet_ntop(socket.AF_INET6, data)

    if rtype in (2, 5, 12):
        return _read_name(buf, offset)[0]

    if rtype == 15:
        return _read_name(buf, offset + 2)[0]

    if rtype == 16:

        strings, i = [], 0

        while i < len(data):
            size = data[i]
            strings.append(data[i + 1:i + 1 + size].decode("utf-8", "replace"))
            i += 1 + size

        return "".join(strings)

    return data.hex()


def dns_query(name, qtype="A", server="127.0.0.1", port=53,
              qclass=CLASS_IN, timeout=2.0):
    """
    Minimal DNS query over UDP. Returns
    {"rcode", "answers": [{"type", "value", "ttl"}], "time_ms", "error"}.
    """

    result = {"rcode": None, "answers": [], "time_ms": None, "error": None}

    try:

        tid = random.randint(0, 0xFFFF)

        packet = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
        packet += _encode_name(name) + struct.pack("!HH", QTYPES[qtype], qclass)

        family = socket.AF_INET6 if ":" in server else socket.AF_INET

        started = time.monotonic()

        with socket.socket(family, socket.SOCK_DGRAM) as sock:

            sock.settimeout(timeout)
            sock.sendto(packet, (server, port))

            while True:

                buf, _ = sock.recvfrom(4096)

                if len(buf) >= 12 and struct.unpack("!H", buf[:2])[0] == tid:
                    break

        result["time_ms"] = round((time.monotonic() - started) * 1000, 1)

        _, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", buf[:12])

        result["rcode"] = RCODES.get(flags & 0x0F, str(flags & 0x0F))

        offset = 12

        for _ in range(qdcount):
            offset = _read_name(buf, offset)[1] + 4

        for _ in range(ancount):

            _, offset = _read_name(buf, offset)

            rtype, _, ttl, length = struct.unpack("!HHIH", buf[offset:offset + 10])
            offset += 10

            result["answers"].append({
                "type": QTYPE_NAMES.get(rtype, str(rtype)),
                "value": _parse_rdata(buf, offset, rtype, length),
                "ttl": ttl
            })

            offset += length

    except socket.timeout:
        result["error"] = "No answer (timeout)."
    except (OSError, ValueError, struct.error, KeyError) as e:
        result["error"] = str(e) or "Lookup failed."

    return result


def lookup(name, qtype="A"):

    name = str(name or "").strip().rstrip(".")

    if not valid_name(name):
        return {"error": "Enter a valid domain name."}

    if qtype not in ("A", "AAAA", "MX", "TXT", "CNAME", "NS"):
        return {"error": "Unsupported record type."}

    result = dns_query(name, qtype)
    result["name"] = name
    result["type"] = qtype

    return result


def get_cache_stats():
    """
    dnsmasq answers CHAOS-class TXT queries with its counters.
    """

    stats = {}

    for key in ("cachesize", "hits", "misses"):

        answer = dns_query(f"{key}.bind", "TXT", qclass=CLASS_CHAOS, timeout=1)

        try:
            stats[key] = int(answer["answers"][0]["value"])
        except (IndexError, KeyError, ValueError):
            return None

    total = stats["hits"] + stats["misses"]

    stats["hit_rate"] = round(stats["hits"] / total * 100) if total else None

    return stats


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def get_dns_status():

    from services.network import run

    settings = get_dns_settings()
    installed = has_dnsmasq()
    running = installed and run(["systemctl", "is-active", "dnsmasq"]) == "active"

    return {
        "installed": installed,
        "running": running,
        "serving": running and settings["enabled"],
        "upstream": describe_upstream(settings),
        "cache": get_cache_stats() if running and settings["enabled"] else None,
        "config_file": DNSMASQ_DNS_FILE
    }


def get_dns_options():

    return {
        "presets": [
            {"id": key, "label": label, "servers": servers}
            for key, (label, servers) in UPSTREAM_PRESETS.items()
        ],
        "interfaces": get_interface_choices(),
        "dnssec_available": os.path.exists(TRUST_ANCHORS),
        "local_domain": get_dhcp_settings()["domain"]
    }
