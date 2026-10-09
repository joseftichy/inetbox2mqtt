# MIT License
#
# Diagnostics for inetbox2mqtt
#
# - install(): copies every log line (which passes the logger level) into a
#   small buffer, main1 publishes the buffer to MQTT (topic .../log)
# - count_boot(): boot counter, persisted in boots.dat
# - save_crash()/pop_crash(): traceback of a crash, published after the reboot
# - get(): dict with rssi, uptime, free memory, boots, reset cause, ip

import logging
import machine
import time
import gc
import sys

BOOTS = "boots.dat"
CRASH = "crash.txt"
MAX_LINES = 30
MAX_LEN = 250  # HA limits a sensor state to 255 chars

_lines = []
_dropped = 0
_boots = 0
_uptime = 0
_last = time.ticks_ms()


def uptime():
    global _uptime, _last
    now = time.ticks_ms()
    _uptime += time.ticks_diff(now, _last)
    _last = now
    return _uptime // 1000


def add_line(s):
    global _dropped
    if len(_lines) >= MAX_LINES:
        _lines.pop(0)
        _dropped += 1
    _lines.append(("[%ds] " % uptime() + s)[:MAX_LEN])


# returns up to n of the oldest buffered lines and removes them from the buffer
def take_lines(n=10):
    global _lines, _dropped
    l = _lines[:n]
    _lines = _lines[n:]
    if _dropped:
        l.insert(0, "... %d log lines dropped" % _dropped)
        _dropped = 0
    return l


def install():
    orig = logging.Logger.log

    def _log(self, level, msg, *args):
        # fast exit for the many debug calls in the LIN loop
        if level < (self.level or logging._level):
            return
        orig(self, level, msg, *args)
        try:
            text = msg % args if args else str(msg)
        except Exception:
            text = str(msg)
        add_line(logging._level_dict.get(level, str(level)) + ":" + str(self.name) + ":" + text)

    logging.Logger.log = _log


def count_boot():
    global _boots
    try:
        with open(BOOTS, "r") as f:
            _boots = int(f.read())
    except Exception:
        _boots = 0
    _boots += 1
    try:
        with open(BOOTS, "w") as f:
            f.write(str(_boots))
    except Exception:
        pass
    return _boots


def save_crash(e):
    sys.print_exception(e)
    try:
        with open(CRASH, "w") as f:
            sys.print_exception(e, f)
    except Exception:
        pass


# returns the saved traceback lines (or []) and deletes the file
def pop_crash():
    import os
    try:
        with open(CRASH, "r") as f:
            l = [s.rstrip() for s in f.read().split("\n") if s.strip()]
        os.remove(CRASH)
        return l
    except Exception:
        return []


def reset_cause():
    c = machine.reset_cause()
    for n in ("PWRON_RESET", "HARD_RESET", "WDT_RESET", "DEEPSLEEP_RESET", "SOFT_RESET"):
        if getattr(machine, n, None) == c:
            return n[:-6].lower()
    return str(c)


# the caller does the gc.collect() (main1: only in a LIN pause)
def get(con_if, rel_no):
    d = {
        "uptime": uptime(),
        "mem_free": gc.mem_free(),
        "boots": _boots,
        "reset_cause": reset_cause(),
        "release": rel_no,
        "rssi": None,
        "ip": None,
    }
    try:
        d["ip"] = con_if.ifconfig()[0]
        d["rssi"] = con_if.status("rssi")
    except Exception:
        pass
    return d
