import json
import os
from pathlib import Path

# -------------------------------------------------------------------
# Configuration Locations
# -------------------------------------------------------------------

SYSTEM_DIR = Path("/etc/chaos-router")
USER_DIR = Path.home() / ".config" / "chaos-router"
RUNTIME_DIR = Path("/tmp/chaos-router")

# Use /etc when writable (Pi), otherwise ~/.config (development/WSL)
if SYSTEM_DIR.exists() and os.access(SYSTEM_DIR, os.W_OK):
    CONFIG_DIR = SYSTEM_DIR
else:
    CONFIG_DIR = USER_DIR

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# Keep the old constant so existing imports don't break.
RUNTIME_DIR = str(RUNTIME_DIR)
CONFIG_DIR = str(CONFIG_DIR)

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


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp = f"{path}.tmp"

    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)

    os.replace(tmp, path)