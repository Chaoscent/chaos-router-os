from time import time
from collections import deque

INTERFACE = None

_prev_rx = 0
_prev_tx = 0
_prev_time = time()

history = deque(maxlen=60)


def _detect_interface():

    global INTERFACE

    if INTERFACE:
        return INTERFACE

    with open("/proc/net/dev") as f:

        for line in f.readlines()[2:]:

            name = line.split(":")[0].strip()

            if name not in ("lo",):
                INTERFACE = name
                break

    return INTERFACE or "eth0"


def _read_bytes():

    interface = _detect_interface()

    with open("/proc/net/dev") as f:

        for line in f.readlines()[2:]:

            if line.strip().startswith(interface + ":"):

                parts = line.split()

                rx = int(parts[1])
                tx = int(parts[9])

                return rx, tx

    return 0, 0


def get_traffic():

    global _prev_rx, _prev_tx, _prev_time

    rx, tx = _read_bytes()

    now = time()
    dt = now - _prev_time

    if dt <= 0:
        dt = 1

    down = ((rx - _prev_rx) * 8) / dt / 1_000_000
    up = ((tx - _prev_tx) * 8) / dt / 1_000_000

    if _prev_rx == 0:
        down = 0
        up = 0

    _prev_rx = rx
    _prev_tx = tx
    _prev_time = now

    down = max(0, round(down, 1))
    up = max(0, round(up, 1))

    history.append({
        "rx": down,
        "tx": up
    })

    return {
        "rx": down,
        "tx": up
    }


def get_history():
    return list(history)
