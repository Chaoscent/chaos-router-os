"""
Internet throughput, sampled once per second in the background.

Every page reads the same samples, so the header and the dashboard
always agree, no matter how many browsers poll them. The measured
interface is the WAN (eth0 in WAN mode, otherwise the modem); while
that is missing, the interface holding the default route is used.
"""

import threading
import time
from collections import deque

from services.network import get_wan_interface, get_default_interface

SAMPLE_SECONDS = 1

HISTORY_SECONDS = 60

_lock = threading.Lock()
_thread = None

# {"t": unix time, "rx": Mbps, "tx": Mbps}
history = deque(maxlen=HISTORY_SECONDS)

_latest = {"rx": 0.0, "tx": 0.0, "interface": None}


def _read_counters():
    """
    {interface: (rx_bytes, tx_bytes)} from /proc/net/dev.
    """

    counters = {}

    with open("/proc/net/dev") as f:

        for line in f.readlines()[2:]:

            name, _, data = line.partition(":")
            parts = data.split()

            if len(parts) >= 9:
                counters[name.strip()] = (int(parts[0]), int(parts[8]))

    return counters


def _pick_interface(counters):

    for name in (get_wan_interface(), get_default_interface()):

        if name in counters:
            return name

    return next((n for n in counters if n != "lo"), None)


def _sample_forever():

    previous = None

    while True:

        started = time.time()

        try:

            counters = _read_counters()
            interface = _pick_interface(counters)

            if interface:

                rx, tx = counters[interface]

                # The first sample, an interface switch or a counter
                # reset only sets the baseline.
                if previous and previous[0] == interface and rx >= previous[1] and tx >= previous[2]:

                    dt = max(started - previous[3], 0.001)

                    down = round((rx - previous[1]) * 8 / dt / 1_000_000, 4)
                    up = round((tx - previous[2]) * 8 / dt / 1_000_000, 4)

                    with _lock:
                        history.append({"t": round(started, 3), "rx": down, "tx": up})
                        _latest.update(rx=down, tx=up, interface=interface)

                previous = (interface, rx, tx, started)

        except Exception:
            previous = None

        time.sleep(max(0.05, SAMPLE_SECONDS - (time.time() - started)))


def _ensure_sampler():

    global _thread

    with _lock:

        if _thread and _thread.is_alive():
            return

        _thread = threading.Thread(target=_sample_forever, name="traffic-sampler", daemon=True)
        _thread.start()


def get_traffic():
    """
    The latest one-second rates in Mbps: {"rx", "tx", "interface"}.
    """

    _ensure_sampler()

    with _lock:
        return dict(_latest)


def get_history():
    """
    Up to the last 60 one-second samples: [{"t", "rx", "tx"}].
    """

    _ensure_sampler()

    with _lock:
        return list(history)
