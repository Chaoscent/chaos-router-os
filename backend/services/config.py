"""
Where Chaos Router OS keeps its settings. Every file is JSON.

    /etc/chaos-router-os/      Defaults. Shipped with the OS, never
                               written by the app.
    /var/lib/chaos-router-os/  Persistent config: only settings that
                               were applied and verified. Deleting a
                               file here restores its defaults.
    /tmp/chaos-router-os/      Running config. Rebuilt from /var/lib
                               on every boot, so an unverified change
                               never survives a reboot.

Every settings file has the same name in each layer, e.g. dhcp.json.
Running settings = built-in fallback < /etc default < /tmp.

Changes go to /tmp first and are copied to /var/lib (commit) only
after they were applied and verified; see services/transaction.py.

/var/lib/chaos-router-os/system/ holds records of what is actually
applied to the system (e.g. firewall rules we added). They follow the
system, not the config, so they are never committed or reverted.

The directories can be overridden for development and tests with
CHAOS_DEFAULTS_DIR, CHAOS_STATE_DIR and CHAOS_RUNTIME_DIR.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

# -------------------------------------------------------------------
# Locations
# -------------------------------------------------------------------

DEFAULTS_DIR = Path(os.getenv("CHAOS_DEFAULTS_DIR", "/etc/chaos-router-os"))
STATE_DIR = Path(os.getenv("CHAOS_STATE_DIR", "/var/lib/chaos-router-os"))
RUNTIME_DIR = Path(os.getenv("CHAOS_RUNTIME_DIR", "/tmp/chaos-router-os"))
SYSTEM_DIR = STATE_DIR / "system"

BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"

# Files that hold keys or passwords.
SECRET_MODE = 0o600


# -------------------------------------------------------------------
# JSON Helpers
# -------------------------------------------------------------------

def load_json(path, default=None):

    if default is None:
        default = {}

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data, secret=False):

    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Keep the .json extension even for the short-lived temp file.
    base, ext = os.path.splitext(path)
    tmp = f"{base}.tmp{ext}"

    # Create secret files with tight permissions from the start,
    # so they are never briefly world-readable.
    mode = SECRET_MODE if secret else 0o644

    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)

    os.chmod(tmp, mode)
    os.replace(tmp, path)


# -------------------------------------------------------------------
# Layers
# -------------------------------------------------------------------

def defaults_path(name):

    return str(DEFAULTS_DIR / f"{name}.json")


def state_path(name):

    return str(STATE_DIR / f"{name}.json")


def runtime_path(name):

    return str(RUNTIME_DIR / f"{name}.json")


def system_path(name):

    return str(SYSTEM_DIR / f"{name}.json")


def load_defaults(name, builtin=None):
    """
    Built-in fallback, overridden key by key by
    /etc/chaos-router-os/<name>.json when it exists.
    """

    defaults = dict(builtin or {})

    data = load_json(defaults_path(name), {})

    if isinstance(data, dict):
        defaults.update(data)

    return defaults


def has_defaults(name):

    return os.path.exists(defaults_path(name))


# Marks "no default given": a missing file then reads as {}.
# Passing default=None makes a missing file read as None.
_EMPTY = object()


def _load_layer(path, default):

    fallback = {} if default is _EMPTY else default

    if not os.path.exists(path):
        return fallback

    return load_json(path, fallback)


# Running config (/tmp) ---------------------------------------------

def load_running(name, default=_EMPTY):

    return _load_layer(runtime_path(name), default)


def save_running(name, data, secret=False):

    save_json(runtime_path(name), data, secret=secret)


def delete_running(name):

    try:
        os.remove(runtime_path(name))
    except FileNotFoundError:
        pass


def load_settings(name, builtin=None):
    """
    Running settings: defaults with the running config on top.
    """

    settings = load_defaults(name, builtin)

    running = load_running(name, {})

    if isinstance(running, dict):
        settings.update(running)

    return settings


# Persistent config (/var/lib) --------------------------------------

def load_persistent(name, default=_EMPTY):

    return _load_layer(state_path(name), default)


def has_persistent(name):

    return os.path.exists(state_path(name))


def save_persistent(name, data, secret=False):

    save_json(state_path(name), data, secret=secret)


def _copy(src, dst):
    """
    Atomic copy that keeps the file mode (secrets stay 600).
    """

    base, ext = os.path.splitext(dst)
    tmp = f"{base}.tmp{ext}"

    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def commit(name):
    """
    Makes the running config persistent.
    """

    src = runtime_path(name)
    dst = state_path(name)

    if os.path.exists(src):
        _copy(src, dst)
    elif os.path.exists(dst):
        os.remove(dst)


def revert(name):
    """
    Replaces the running config with the persistent one.
    """

    src = state_path(name)
    dst = runtime_path(name)

    if os.path.exists(src):
        _copy(src, dst)
    else:
        delete_running(name)


# System records (/var/lib/chaos-router-os/system) -------------------

def load_system(name, default=_EMPTY):

    return _load_layer(system_path(name), default)


def save_system(name, data, secret=False):

    save_json(system_path(name), data, secret=secret)


# -------------------------------------------------------------------
# Migration from earlier locations
# -------------------------------------------------------------------

# (old path, new state name, holds secrets)
LEGACY_FILES = [
    (Path(old_dir) / f"{name}.json", name, secret)
    for old_dir in (
        "/etc/chaos-router",
        Path.home() / ".config" / "chaos-router"
    )
    for name, secret in (
        ("dhcp", False),
        ("wifi", True),
        ("wireguard", True),
        ("openvpn", True),
        ("vpn_profiles", True),
        ("device_aliases", False)
    )
] + [
    (STATE_DIR / "config" / "dashboard.json", "dashboard", False),
    (DEFAULTS_DIR / "config" / "security.json", "security", False)
]


def migrate_legacy_files():
    """
    Copies settings from earlier versions' locations into
    /var/lib/chaos-router-os once. Old files are left in place.
    """

    for old, name, secret in LEGACY_FILES:

        new = Path(state_path(name))

        if new.exists() or not old.is_file():
            continue

        try:

            shutil.copyfile(old, new)
            os.chmod(new, SECRET_MODE if secret else 0o644)

            print(f"[config] Migrated {old} -> {new}")

        except OSError as e:
            print(f"[config] Could not migrate {old}: {e}", file=sys.stderr)


# -------------------------------------------------------------------
# Boot
# -------------------------------------------------------------------

def get_boot_id():

    try:
        with open(BOOT_ID_FILE) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def sync_boot():
    """
    On the first start after a boot, rebuilds the running config
    from the persistent config. Returns True when it did.

    The kernel's boot ID tells a reboot apart from an app restart,
    which must keep running (possibly unconfirmed) changes.
    """

    boot_id = get_boot_id()

    if load_running("boot", {}).get("boot_id") == boot_id:
        return False

    for path in RUNTIME_DIR.glob("*.json"):
        path.unlink()

    for path in STATE_DIR.glob("*.json"):
        _copy(path, RUNTIME_DIR / path.name)

    save_running("boot", {
        "boot_id": boot_id,
        "synced_at": int(time.time())
    })

    return True


# -------------------------------------------------------------------
# Startup
# -------------------------------------------------------------------

def init_dirs():

    for path in (STATE_DIR, SYSTEM_DIR, RUNTIME_DIR):

        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    # Running config holds secrets (Wi-Fi password, VPN keys).
    try:
        os.chmod(RUNTIME_DIR, 0o700)
    except OSError:
        pass

    if not os.access(STATE_DIR, os.W_OK):

        print(
            f"[config] {STATE_DIR} is not writable; settings cannot be saved. "
            f"Run: sudo mkdir -p {STATE_DIR} && "
            f"sudo chown $(whoami) {STATE_DIR}",
            file=sys.stderr
        )

        return

    migrate_legacy_files()


init_dirs()
