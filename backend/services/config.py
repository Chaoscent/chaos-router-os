import json
import os
import tempfile

# -------------------------------------------------------------------
# Chaos Router OS Configuration Paths
# -------------------------------------------------------------------

if os.geteuid() == 0:
    CONFIG_DIR = "/etc/chaos-router"
else:
    CONFIG_DIR = os.path.expanduser("~/.config/chaos-router")

RUNTIME_DIR = "/tmp/chaos-router"

# -------------------------------------------------------------------
# Directory Management
# -------------------------------------------------------------------

def ensure_dirs():
    """
    Create configuration and runtime directories if they do not exist.
    Safe to call repeatedly.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(RUNTIME_DIR, exist_ok=True)

# -------------------------------------------------------------------
# JSON Helpers
# -------------------------------------------------------------------

def load_json(path, default=None):
    """
    Load JSON from disk.

    Returns the provided default value if the file does not exist
    or contains invalid JSON.
    """

    ensure_dirs()

    if default is None:
        default = {}

    try:
        with open(path, "r") as f:
            return json.load(f)

    except (FileNotFoundError, json.JSONDecodeError):
        return default

# -------------------------------------------------------------------
# Atomic Writes
# -------------------------------------------------------------------

def save_json(path, data):
    """
    Atomically write JSON to disk.

    Writes to a temporary file first, flushes it to disk,
    then replaces the original file.
    """

    ensure_dirs()

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=directory)

    try:

        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, path)

    finally:

        if os.path.exists(temp_path):
            os.remove(temp_path)