"""
Web shell: a terminal on the router in the browser (System > Shell).

The app's user has passwordless sudo, so this is root access to the
router. Safeguards:

- Off by default; switched on in the System page (shell.json).
- Every session needs the admin password again (counted by the login
  rate limiter) and gets a one-time key that is valid for 60 seconds.
- Never from the internet side: the connection must not arrive on the
  WAN interface (eth0 in WAN mode) or on the modem.
- The WebSocket must come from the dashboard itself (Origin check).
- At most MAX_SESSIONS at once; closed after IDLE_TIMEOUT without
  input and at the session's absolute lifetime.
- Every session is logged.
"""

import codecs
import fcntl
import json
import os
import pty
import secrets
import select
import signal
import struct
import termios
import threading
import time

from services.config import load_running

from simple_websocket import ConnectionClosed

from services.network import run, get_wan_interface

from services.logs import log_event

SHELL = "shell"

DEFAULT_SETTINGS = {"enabled": False}

TOKEN_SECONDS = 60
IDLE_TIMEOUT = 15 * 60
MAX_SESSIONS = 2

SHELL_COMMAND = ["/bin/bash", "-l"]

_lock = threading.Lock()

# token -> {"user", "address", "expires"}
_tokens = {}

_sessions = 0


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def get_shell_settings():

    data = load_running(SHELL, {})

    return {"enabled": isinstance(data, dict) and data.get("enabled") is True}


def save_shell_settings(enabled):

    from services import transaction

    return transaction.change(SHELL, {"enabled": enabled is True})


# -------------------------------------------------------------------
# Where the viewer is
# -------------------------------------------------------------------

def arrival_interface(address):
    """
    The interface traffic to/from this address uses ("lo" for the
    router itself), or None.
    """

    output = run(["ip", "route", "get", str(address)]) or ""

    parts = output.split()

    if "dev" in parts and parts.index("dev") + 1 < len(parts):
        return parts[parts.index("dev") + 1]

    # Local addresses: "local 10.42.0.1 dev lo table local ..."
    return "lo" if output.startswith("local ") else None


def is_allowed_address(address):
    """
    (True, "") or (False, why): anything but the WAN side.
    """

    interface = arrival_interface(address)

    if interface is None:
        return False, "Your connection could not be traced to an interface."

    # The modem stays internet side even while eth0 is the WAN.
    if interface == get_wan_interface() or interface.startswith("wwan"):
        return False, f"The shell is not available from the internet side ({interface})."

    return True, ""


def get_shell_status(address):

    allowed, reason = is_allowed_address(address)

    with _lock:
        sessions = _sessions

    return {
        "enabled": get_shell_settings()["enabled"],
        "allowed": allowed,
        "reason": reason,
        "sessions": sessions,
        "max_sessions": MAX_SESSIONS,
        "idle_timeout": IDLE_TIMEOUT
    }


# -------------------------------------------------------------------
# One-time keys
# -------------------------------------------------------------------

def issue_token(user, address):

    now = time.time()
    token = secrets.token_urlsafe(32)

    with _lock:

        for key in [k for k, v in _tokens.items() if v["expires"] < now]:
            del _tokens[key]

        _tokens[token] = {"user": user, "address": address, "expires": now + TOKEN_SECONDS}

    return token


def redeem_token(token, user, address):
    """
    A key works once, for the same user and address, within 60 s.
    """

    with _lock:
        entry = _tokens.pop(str(token or ""), None)

    return bool(entry) and entry["user"] == user \
        and entry["address"] == address and entry["expires"] >= time.time()


# -------------------------------------------------------------------
# Session
# -------------------------------------------------------------------

def _set_size(fd, rows, cols):

    rows = max(2, min(int(rows), 500))
    cols = max(2, min(int(cols), 1000))

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _spawn():
    """
    Starts a login shell as the app's user in a new pseudo-terminal.
    Returns (pid, fd).
    """

    pid, fd = pty.fork()

    if pid == 0:

        env = {
            "TERM": "xterm-256color",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "HOME": os.path.expanduser("~"),
            "USER": os.environ.get("USER", ""),
            "SHELL": SHELL_COMMAND[0],
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        }

        try:
            os.chdir(env["HOME"])
        except OSError:
            pass

        os.execve(SHELL_COMMAND[0], SHELL_COMMAND, env)

    return pid, fd


def _stop(pid, fd):

    try:
        os.close(fd)
    except OSError:
        pass

    for sig in (signal.SIGHUP, signal.SIGKILL):

        try:
            os.killpg(os.getpgid(pid), sig)
        except OSError:
            break

        time.sleep(0.2)

        try:
            if os.waitpid(pid, os.WNOHANG)[0]:
                break
        except ChildProcessError:
            break


def run_session(ws, user, address, lifetime):
    """
    Bridges a WebSocket and a shell until either side closes, the user
    is idle for IDLE_TIMEOUT, or `lifetime` seconds have passed.

    Client messages are JSON: {"type": "input", "data": "..."} or
    {"type": "resize", "rows": n, "cols": n}. Output goes out as text.
    """

    global _sessions

    with _lock:

        if _sessions >= MAX_SESSIONS:
            ws.send("\r\n\x1b[31mToo many open shells. Close one first.\x1b[0m\r\n")
            return

        _sessions += 1

    pid, fd = _spawn()

    started = last_input = time.time()

    log_event("shell", f"Shell opened by {user} from {address}.", "warning")

    reason = "closed"

    try:

        decoder = codecs.getincrementaldecoder("utf-8")("replace")

        while True:

            now = time.time()

            if now - last_input > IDLE_TIMEOUT:
                reason = "idle"
                break

            if now - started > lifetime:
                reason = "session lifetime reached"
                break

            readable, _, _ = select.select([fd], [], [], 0.05)

            if readable:

                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b""

                # The shell exited (e.g. `exit`).
                if not chunk:
                    reason = "shell exited"
                    break

                ws.send(decoder.decode(chunk))

            try:
                message = ws.receive(timeout=0.05)
            except ConnectionClosed:
                reason = "browser disconnected"
                break

            if message is None:

                if not ws.connected:
                    reason = "browser disconnected"
                    break

                continue

            try:
                data = json.loads(message)
            except (TypeError, ValueError):
                continue

            if data.get("type") == "input" and isinstance(data.get("data"), str):

                os.write(fd, data["data"].encode("utf-8"))
                last_input = time.time()

            elif data.get("type") == "resize":

                try:
                    _set_size(fd, data.get("rows"), data.get("cols"))
                except (TypeError, ValueError, OSError):
                    pass

    except Exception as e:
        reason = f"error: {e}"

    finally:

        _stop(pid, fd)

        with _lock:
            _sessions -= 1

        log_event("shell", f"Shell of {user} from {address} closed ({reason}).")

        if reason in ("idle", "session lifetime reached"):

            try:
                ws.send(f"\r\n\x1b[33mDisconnected: {reason}.\x1b[0m\r\n")
            except Exception:
                pass
