# MIT License
#
# OTA safety net for inetbox2mqtt
#
# - backup():  copies the current files to /ota_bak before an update
# - start_trial(): marks a freshly installed release as "on trial"
# - check_trial(): called from boot.py on every boot; after MAX_TRIALS boots
#   without confirm() the backup is restored (rollback). A hardware timer
#   resets the board if the new release hangs before it gets confirmed.
# - confirm(): called by main1 once MQTT works, ends the trial
# - set_status()/get_status(): last OTA result, published to MQTT by main1

import os
import machine

BAK = "/ota_bak"
TRIAL = "/ota_trial.dat"
STATUS = "/ota_status.dat"
RUN_MODE = "/run_mode.dat"
MAX_TRIALS = 3
TRIAL_TIME = 300  # sec, time for the new release to reach the MQTT broker

_timer = None


def exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _read(p):
    try:
        with open(p, "r") as f:
            return f.read()
    except OSError:
        return None


def _write(p, s):
    try:
        with open(p, "w") as f:
            f.write(s)
    except OSError:
        pass


def _remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _copy(src, dst):
    with open(src, "rb") as fi:
        with open(dst, "wb") as fo:
            while True:
                b = fi.read(1024)
                if not b:
                    break
                fo.write(b)


def _mkdir(p):
    try:
        os.mkdir(p)
    except OSError:
        pass


def _clear_dir(d):
    if not exists(d):
        return
    for name in os.listdir(d):
        p = d + "/" + name
        if os.stat(p)[0] & 0x4000:
            _clear_dir(p)
            os.rmdir(p)
        else:
            os.remove(p)


def set_status(s):
    _write(STATUS, s)


def get_status():
    return _read(STATUS)


def back_to_normal():
    # leave the OTA run-mode (2,3) without the connect object
    _write(RUN_MODE, "1")


# copy the given absolute paths (e.g. "/main.py", "/lib/connect.py") to BAK,
# the list of all paths is kept to remove files which didn't exist before
def backup(files):
    _clear_dir(BAK)
    _mkdir(BAK)
    _mkdir(BAK + "/lib")
    for p in files:
        if exists(p):
            _copy(p, BAK + p)
    _write(BAK + "/files.txt", "\n".join(files))


def restore():
    files = (_read(BAK + "/files.txt") or "").split("\n")
    for p in files:
        if not p:
            continue
        if exists(BAK + p):
            _copy(BAK + p, p)
        else:
            _remove(p)  # new with the failed release


def start_trial():
    _write(TRIAL, "0")


def check_trial():
    global _timer
    n = _read(TRIAL)
    if n is None:
        return
    try:
        n = int(n) + 1
    except ValueError:
        n = MAX_TRIALS + 1
    if n > MAX_TRIALS:
        print("OTA: new release failed %d times - rollback" % MAX_TRIALS)
        old = _read(BAK + "/release.py") or ""
        restore()
        _remove(TRIAL)
        set_status("rollback to " + _rel(old) + " - new release did not start")
        machine.reset()
    _write(TRIAL, str(n))
    print("OTA: trial boot %d/%d" % (n, MAX_TRIALS))
    _timer = machine.Timer(0)
    _timer.init(mode=machine.Timer.ONE_SHOT, period=TRIAL_TIME * 1000,
                callback=lambda t: machine.reset())


# returns True if a trial was running and is now confirmed
def confirm():
    global _timer
    if _timer is not None:
        _timer.deinit()
        _timer = None
    if exists(TRIAL):
        _remove(TRIAL)
        return True
    return False


# extract rel_no from the content of a release.py
def _rel(s):
    i = s.find('"')
    j = s.find('"', i + 1)
    if i < 0 or j < 0:
        return "?"
    return s[i + 1:j]
