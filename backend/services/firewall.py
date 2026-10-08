import ipaddress
import os
import re
import shlex
import shutil

from services.network import (
    run,
    run_command,
    privileged,
    get_wan_interface,
    get_lan_interface_names
)

from services.config import (
    load_defaults,
    has_defaults,
    load_running,
    load_system,
    save_system
)

from services import transaction

from services.caddy import APP_PORT, BEHIND_CADDY

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

UFW_DEFAULTS_FILE = "/etc/default/ufw"
UFW_CONF_FILE = "/etc/ufw/ufw.conf"

# ufw lives in /usr/sbin, which is often missing from a user's PATH.
UFW_SEARCH_PATH = os.pathsep.join([
    os.environ.get("PATH", ""),
    "/usr/sbin",
    "/sbin"
])

ACTIONS = ("allow", "deny", "reject", "limit")
DIRECTIONS = ("in", "out")
PROTOCOLS = ("any", "tcp", "udp")
POLICIES = ("allow", "deny", "reject")
POLICY_DIRECTIONS = ("incoming", "outgoing", "routed")
LOG_LEVELS = ("off", "low", "medium", "high", "full")

# /etc/default/ufw stores iptables targets.
POLICY_FROM_TARGET = {
    "ACCEPT": "allow",
    "DROP": "deny",
    "REJECT": "reject"
}

POLICY_KEYS = {
    "incoming": "DEFAULT_INPUT_POLICY",
    "outgoing": "DEFAULT_OUTPUT_POLICY",
    "routed": "DEFAULT_FORWARD_POLICY"
}

PORT_RE = re.compile(r"^\d{1,5}(:\d{1,5})?$")

COMMENT_RE = re.compile(r"^[A-Za-z0-9 ._:()/+-]{1,64}$")

ESSENTIAL_COMMENT = "Chaos Router OS"

# Comment prefix of the rules kept by the "essentials" setting.
ESSENTIAL_PREFIX = f"{ESSENTIAL_COMMENT}: Essential"

# The dashboard: HTTP and HTTPS (Caddy). Without Caddy (development)
# also the app's own port.
WEB_PORTS = ("80", "443") + (() if BEHIND_CADDY else (APP_PORT,))

# firewall.json: enabled, policies, logging, the essential rules
# switch and the user's rules.
FIREWALL = "firewall"

# Fallback when /etc/chaos-router-os has no firewall.json (and the
# base for importing an existing ufw setup).
BUILTIN_FIREWALL = {
    "enabled": False,
    "policies": {
        "incoming": "deny",
        "outgoing": "allow",
        "routed": "deny"
    },
    "logging": "low",
    "essentials": False,
    "rules": []
}

# Shipped to /etc/chaos-router-os/firewall.json by the installer: on,
# nothing comes in from the internet, the LAN keeps working.
DEFAULT_SETTINGS = {
    **BUILTIN_FIREWALL,
    "enabled": True,
    "essentials": True
}

# system/firewall_rules.json: the rules each owner ("user",
# "wireguard", ...) actually added to ufw. Follows ufw, not the
# config, so it is never reverted.
RULE_LEDGER = "firewall_rules"

# Rules owned by the VPN modules and the essential rules are not
# imported as user rules.
VPN_COMMENTS = (
    f"{ESSENTIAL_COMMENT}: WireGuard",
    f"{ESSENTIAL_COMMENT}: OpenVPN",
    f"{ESSENTIAL_COMMENT}: VPN client",
    ESSENTIAL_PREFIX
)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def get_ufw_path():

    return shutil.which("ufw", path=UFW_SEARCH_PATH)


def has_ufw():

    return get_ufw_path() is not None


def ufw(args):

    path = get_ufw_path()

    if not path:
        return False, "ufw is not available."

    return run_command(privileged([path] + args))


def read_key_values(path):

    values = {}

    try:

        with open(path, "r") as f:

            for line in f:

                line = line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)

                values[key.strip()] = value.strip().strip('"\'')

    except Exception:
        pass

    return values


def get_interfaces():

    output = run(["ip", "-o", "link", "show"])

    interfaces = []

    if not output:
        return interfaces

    for line in output.splitlines():

        parts = line.split(":", 2)

        if len(parts) < 2:
            continue

        name = parts[1].strip().split("@", 1)[0]

        if name and name != "lo":
            interfaces.append(name)

    return interfaces


def is_forwarding_enabled():

    try:

        with open("/proc/sys/net/ipv4/ip_forward") as f:
            return f.read().strip() == "1"

    except Exception:
        return False


# -------------------------------------------------------------------
# Status
# -------------------------------------------------------------------

def get_policies():

    defaults = read_key_values(UFW_DEFAULTS_FILE)

    policies = {}

    for direction, key in POLICY_KEYS.items():

        policies[direction] = POLICY_FROM_TARGET.get(
            defaults.get(key, "").upper(),
            "unknown"
        )

    return policies


def is_ufw_active():

    ok, output = ufw(["status"])

    return ok and "Status: active" in output


def get_firewall_settings():
    """
    The running firewall config. Before the first change from the
    dashboard, it is the installed defaults, or (without them) what
    ufw runs now.
    """

    running = load_running(FIREWALL, None)

    if running is None:

        if has_defaults(FIREWALL):
            return load_defaults(FIREWALL, BUILTIN_FIREWALL)

        return import_from_ufw()

    settings = load_defaults(FIREWALL, BUILTIN_FIREWALL)
    settings.update(running)

    return settings


def import_from_ufw():

    settings = load_defaults(FIREWALL, BUILTIN_FIREWALL)

    if not has_ufw():
        return settings

    ok, rules = read_ufw_rules()

    rules = [
        r for r in (rules if ok else [])
        if not r["comment"].startswith(VPN_COMMENTS)
    ]

    policies = get_policies()

    settings.update({
        "enabled": is_ufw_active(),
        "logging": read_key_values(UFW_CONF_FILE).get("LOGLEVEL") or "off",
        "policies": {
            d: p if p in POLICIES else settings["policies"][d]
            for d, p in policies.items()
        },
        "rules": [
            {"id": i + 1, "args": shlex.split(r["id"])}
            for i, r in enumerate(rules)
        ]
    })

    # These rules are in ufw already; record them as ours.
    ledger = load_system(RULE_LEDGER, {})

    if "user" not in ledger:
        ledger["user"] = [r["args"] for r in settings["rules"]]
        save_system(RULE_LEDGER, ledger)

    return settings


def rule_view(rule):

    spec = shlex.join(rule["args"])

    view = parse_rule(spec)
    view["id"] = rule["id"]
    view["spec"] = spec

    return view


def get_firewall_status():

    installed = has_ufw()
    settings = get_firewall_settings()

    return {
        "installed": installed,
        "active": installed and is_ufw_active(),
        "enabled": settings["enabled"],
        "logging": settings["logging"],
        "policies": settings["policies"],
        "forwarding": is_forwarding_enabled(),
        "interfaces": get_interfaces(),
        "essentials": settings["essentials"],
        "essential_rules": [
            {**parse_rule(shlex.join(r["args"])), "description": r["description"]}
            for r in get_essential_rules()
        ] if settings["essentials"] else [],
        "rules": [rule_view(r) for r in settings["rules"]],
        "rules_error": None
    }


# -------------------------------------------------------------------
# Rules
# -------------------------------------------------------------------

def parse_rule(spec):
    """
    Parses one rule from `ufw show added`, e.g.
    allow in on eth0 from 192.168.1.0/24 to any port 22 proto tcp comment 'SSH'
    route allow in on eth0 out on wwan0
    limit 22/tcp
    """

    try:
        tokens = shlex.split(spec)
    except ValueError:
        tokens = spec.split()

    rule = {
        "id": spec,
        "route": False,
        "action": "",
        "direction": "in",
        "interface": "",
        "out_interface": "",
        "from": "any",
        "from_port": "",
        "to": "any",
        "port": "",
        "proto": "any",
        "app": "",
        "comment": ""
    }

    i = 0

    if tokens[i:i + 1] == ["route"]:
        rule["route"] = True
        i += 1

    if i < len(tokens):
        rule["action"] = tokens[i]
        i += 1

    target = None

    while i < len(tokens):

        token = tokens[i]
        value = tokens[i + 1] if i + 1 < len(tokens) else ""

        if token in ("log", "log-all"):
            i += 1
            continue

        if token in DIRECTIONS:

            # "out on X" after "in on Y" is the route egress side.
            if rule["route"] and token == "out" and rule["interface"]:
                target = "out_interface"
            else:
                rule["direction"] = token
                target = "interface"

            i += 1
            continue

        if token == "on" and target:
            rule[target] = value
            i += 2
            continue

        if token == "from":
            rule["from"] = value
            target = "from_port"
            i += 2
            continue

        if token == "to":
            rule["to"] = value
            target = "port"
            i += 2
            continue

        if token == "port":
            rule["from_port" if target == "from_port" else "port"] = value
            i += 2
            continue

        if token == "proto":
            rule["proto"] = value
            i += 2
            continue

        if token == "app":
            rule["app"] = value
            i += 2
            continue

        if token == "comment":
            rule["comment"] = value
            i += 2
            continue

        # Simple syntax: "22/tcp", "80" or an app profile name.
        if "/" in token:
            port, proto = token.split("/", 1)
            rule["port"] = port
            rule["proto"] = proto
        elif PORT_RE.match(token):
            rule["port"] = token
        else:
            rule["app"] = token

        i += 1

    return rule


def read_ufw_rules():
    """
    The rules in ufw itself, parsed from `ufw show added`.
    """

    ok, output = ufw(["show", "added"])

    if not ok:
        return False, output

    rules = []

    for line in output.splitlines():

        line = line.strip()

        if not line.startswith("ufw "):
            continue

        rules.append(parse_rule(line[len("ufw "):]))

    return True, rules


def _valid_address(value):

    if value in ("", "any"):
        return True

    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def _valid_port(value):

    if not PORT_RE.fullmatch(value):
        return False

    ports = [int(p) for p in value.split(":")]

    if not all(1 <= p <= 65535 for p in ports):
        return False

    return len(ports) == 1 or ports[0] < ports[1]


def build_rule(data):
    """
    Validates a rule from the UI and returns (True, ufw args)
    or (False, message).
    """

    action = data.get("action")
    direction = data.get("direction", "in")
    interface = str(data.get("interface") or "").strip()
    proto = data.get("proto") or "any"
    port = str(data.get("port") or "").strip()
    source = str(data.get("from") or "any").strip()
    destination = str(data.get("to") or "any").strip()
    comment = str(data.get("comment") or "").strip()

    if action not in ACTIONS:
        return False, "Invalid action."

    if direction not in DIRECTIONS:
        return False, "Invalid direction."

    if action == "limit" and direction != "in":
        return False, "Limit only applies to incoming traffic."

    if interface and interface not in get_interfaces():
        return False, "Unknown interface."

    if proto not in PROTOCOLS:
        return False, "Invalid protocol."

    if port and not _valid_port(port):
        return False, "Invalid port. Use a number or a range like 1000:2000."

    if port and ":" in port and proto == "any":
        return False, "Port ranges need TCP or UDP."

    if not _valid_address(source):
        return False, "Invalid source address."

    if not _valid_address(destination):
        return False, "Invalid destination address."

    if comment and not COMMENT_RE.fullmatch(comment):
        return False, (
            "Comments may only use letters, numbers, "
            "spaces and . _ : ( ) / + -"
        )

    # A rule matching everything belongs in the default policy.
    if (
        not port
        and not interface
        and source in ("", "any")
        and destination in ("", "any")
    ):
        return False, (
            "Rule must specify a port, address or interface. "
            "Use the default policies to match all traffic."
        )

    args = [action, direction]

    if interface:
        args += ["on", interface]

    args += ["from", source or "any", "to", destination or "any"]

    if port:
        args += ["port", port]

    if proto != "any":
        args += ["proto", proto]

    if comment:
        args += ["comment", comment]

    return True, args


def strip_comment(args):

    return args[:args.index("comment")] if "comment" in args else list(args)


def next_rule_id(rules):

    return max([r["id"] for r in rules] + [0]) + 1


def add_rule(data):

    ok, args = build_rule(data)

    if not ok:
        return transaction.result(False, args)

    settings = get_firewall_settings()

    if any(strip_comment(r["args"]) == strip_comment(args)
           for r in settings["rules"]):
        return transaction.result(False, "That rule already exists.")

    settings["rules"].append({
        "id": next_rule_id(settings["rules"]),
        "args": args
    })

    return transaction.change(FIREWALL, settings)


def delete_rule(rule_id):

    settings = get_firewall_settings()

    try:
        rule_id = int(rule_id)
    except (TypeError, ValueError):
        return transaction.result(False, "Rule not found.")

    rules = [r for r in settings["rules"] if r["id"] != rule_id]

    if len(rules) == len(settings["rules"]):
        return transaction.result(False, "Rule not found.")

    settings["rules"] = rules

    return transaction.change(FIREWALL, settings)


# -------------------------------------------------------------------
# Applying rules
# -------------------------------------------------------------------

def sync_rules(owner, desired):
    """
    Makes ufw contain exactly `desired` for this owner: adds what is
    missing first, then deletes what is no longer wanted, so there is
    no moment without the wanted rules. Rules another owner still
    needs are kept.
    """

    if not has_ufw():
        return True, "OK"

    ledger = load_system(RULE_LEDGER, {})
    current = ledger.get(owner, [])

    for rule in desired:

        if rule in current:
            continue

        ok, result = ufw(rule)

        if not ok:
            return False, f"Could not add rule ({shlex.join(rule)}): {result}"

    keep = [
        strip_comment(rule)
        for other, rules in ledger.items() if other != owner
        for rule in rules
    ] + [strip_comment(rule) for rule in desired]

    for rule in current:

        if strip_comment(rule) in keep:
            continue

        ufw(["delete"] + strip_comment(rule))

    ledger[owner] = desired
    save_system(RULE_LEDGER, ledger)

    return True, "OK"


def apply_firewall():
    """
    Applies the running firewall config to ufw.
    """

    settings = get_firewall_settings()

    if not has_ufw():

        if not settings["enabled"]:
            return True, "Firewall off."

        return False, "ufw is not available."

    current = get_policies()

    for direction in POLICY_DIRECTIONS:

        policy = settings["policies"][direction]

        if current.get(direction) != policy:

            ok, result = ufw(["default", policy, direction])

            if not ok:
                return False, result

    conf = read_key_values(UFW_CONF_FILE)

    if (conf.get("LOGLEVEL") or "off") != settings["logging"]:

        ok, result = ufw(["logging", settings["logging"]])

        if not ok:
            return False, result

    ok, result = sync_rules("user", [r["args"] for r in settings["rules"]])

    if not ok:
        return False, result

    # Rebuilt on every apply, so they follow the LAN/WAN setup.
    ok, result = sync_rules("essentials", [
        r["args"] for r in get_essential_rules()
    ] if settings["essentials"] else [])

    if not ok:
        return False, result

    active = is_ufw_active()

    if settings["enabled"] and not active:
        ok, result = ufw(["--force", "enable"])
    elif not settings["enabled"] and active:
        ok, result = ufw(["disable"])
    else:
        ok, result = True, ""

    if not ok:
        return False, result

    return True, (
        "Firewall applied." if settings["enabled"] else "Firewall off."
    )


def verify_firewall():

    if not has_ufw():
        return True, "OK"

    if is_ufw_active() != get_firewall_settings()["enabled"]:
        return False, "ufw did not reach the requested state."

    return True, "OK"


# -------------------------------------------------------------------
# Essential rules
# -------------------------------------------------------------------

def get_lan_interfaces():
    """
    LAN interfaces that exist now (eth0, wlan0, wlan1, ...); eth0
    drops out in WAN mode.
    """

    return get_lan_interface_names()


def get_essential_rules():
    """
    Rules that keep the router reachable and the LAN working once
    incoming and routed traffic are denied by default. Everything is
    limited to the LAN interfaces: nothing is opened towards the WAN.
    """

    rules = []
    wan = get_wan_interface()

    for lan in get_lan_interfaces():

        rules.append({
            "description": f"SSH on {lan}",
            "args": ["allow", "in", "on", lan, "from", "any", "to", "any",
                     "port", "22", "proto", "tcp"]
        })

        for port in WEB_PORTS:

            rules.append({
                "description": f"Web interface {port} on {lan}",
                "args": ["allow", "in", "on", lan, "from", "any", "to", "any",
                         "port", port, "proto", "tcp"]
            })

        rules.append({
            "description": f"DHCP on {lan}",
            "args": ["allow", "in", "on", lan, "from", "any", "to", "any",
                     "port", "67", "proto", "udp"]
        })

        rules.append({
            "description": f"DNS on {lan}",
            "args": ["allow", "in", "on", lan, "from", "any", "to", "any",
                     "port", "53"]
        })

        rules.append({
            "description": f"Internet for {lan}",
            "args": ["route", "allow", "in", "on", lan,
                     "out", "on", wan]
        })

    for rule in rules:

        # Mark the rule so it is recognisable in ufw.
        rule["args"] = rule["args"] + [
            "comment",
            f"{ESSENTIAL_PREFIX}: {rule['description']}"
        ]

        rule["command"] = "ufw " + shlex.join(rule["args"])

    return rules


# -------------------------------------------------------------------
# Enable / defaults
# -------------------------------------------------------------------

def set_firewall_enabled(enabled, essentials=None):

    settings = get_firewall_settings()
    settings["enabled"] = enabled

    if essentials is not None:
        settings["essentials"] = essentials

    return transaction.change(FIREWALL, settings)


def set_essentials(enabled):

    settings = get_firewall_settings()
    settings["essentials"] = enabled

    return transaction.change(FIREWALL, settings)


def set_policies(policies):

    for direction, policy in (policies or {}).items():

        if direction not in POLICY_DIRECTIONS:
            return transaction.result(False, f"Invalid policy direction: {direction}")

        if policy not in POLICIES:
            return transaction.result(False, f"Invalid policy: {policy}")

    settings = get_firewall_settings()
    settings["policies"] = {**settings["policies"], **policies}

    return transaction.change(FIREWALL, settings)


def set_logging(level):

    if level not in LOG_LEVELS:
        return transaction.result(False, "Invalid logging level.")

    settings = get_firewall_settings()
    settings["logging"] = level

    return transaction.change(FIREWALL, settings)
