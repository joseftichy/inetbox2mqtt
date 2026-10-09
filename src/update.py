# MIT License
#
# Copyright (c) 2022  Dr. Magnus Christ (mc0110)
#
# This is part of the wifimanager package
# 
# 
# For the proper functioning of the connect-library, the keys "SSID", "WIFIPW", "HOSTNAME" should be included.
# Any other keys can be added

# 
# def set_cred_json():
#     import json
#     CRED_JSON = "cred.json"
# 
#     j = {
#      "SSID": ["text", "SSID:", "1"],
#      "WIFIPW": ["password", "Wifi passcode:", "2"],
#      "MQTT": ["text", "Broker name/IP:", "3"],
#      "UN": ["text", "Broker User:", "4"],
#      "UPW": ["text", "Broker password:", "5"],
#      "HOSTNAME": ["text", "Hostname:", "6"],
#      "ADC": ["checkbox", "Addon DuoControl :", "7"],
#      "ASL": ["checkbox", "Addon SpiritLevel:", "8"],
# #     "OSR": ["checkbox", "OS Web:", "9"],
#      }
#     with open(CRED_JSON, "w") as f: json.dump(j, f)
# 

RAW = "https://raw.githubusercontent.com/joseftichy/inetbox2mqtt/"
API = "https://api.github.com/repos/joseftichy/inetbox2mqtt/commits/"
NEW = "/ota_new"

old_rel = "?"
new_rel = "?"
sha = None

def _requests():
    try:
        import urequests as requests  # micropython 1.20
    except ImportError:
        import requests
    return requests

# args.dat "ota=beta" loads from the branch beta (test port), default is the main branch
def _branch():
    try:
        from args import Args
        return Args().get_key("ota") or "HEAD"
    except Exception:
        return "HEAD"

# all files are loaded from the same commit (and not from the 5 min cached branch)
def _base():
    global sha
    if sha is None:
        sha = _branch()
        try:
            r = _requests().get(API + sha, headers={"Accept": "application/vnd.github.sha", "User-Agent": "inetbox2mqtt"})
            try:
                s = r.text.strip()
                if r.status_code == 200 and len(s) == 40:
                    sha = s
            finally:
                r.close()
        except Exception as e:
            print("OTA: commit not found (" + repr(e) + "), using " + sha)
    return RAW + sha

# download repo_path into the file dest, raises OSError on any problem
def _download(repo_path, dest):
    r = _requests().get(_base() + repo_path)
    try:
        if r.status_code != 200:
            raise OSError("HTTP " + str(r.status_code))
        # the socket is closed by github at the end -> read exactly Content-Length bytes
        length = int(r.headers.get("Content-Length", "0"))
        if length <= 0:
            raise OSError("no Content-Length")
        n = 0
        with open(dest, "wb") as f:
            while n < length:
                b = r.raw.read(min(1024, length - n))
                if not b:
                    break
                f.write(b)
                n += len(b)
        if n != length:
            raise OSError("incomplete " + str(n) + "/" + str(length))
    finally:
        r.close()

# download with retries (wifi or github may drop the connection)
def _get_file(repo_path, dest, err_msg):
    import time
    for tries in range(5):
        try:
            _download(repo_path, dest)
            return
        except Exception as ex:
            print("OTA: " + repo_path + " try " + str(tries + 1) + ": " + repr(ex))
            err = str(ex)
            time.sleep(3)
    _abort(err_msg + " (" + err + ")")

# OTA failed before anything was replaced: keep the old release, back to normal run-mode
def _abort(msg):
    import ota_guard, machine
    print("OTA: " + msg)
    ota_guard._clear_dir(NEW)
    ota_guard.set_status(msg + " - " + old_rel + " kept")
    ota_guard.back_to_normal()
    machine.reset()

# all files are first downloaded to NEW; only if every download succeeds,
# the current files are saved to the backup and replaced
def update_repo():
    import os, gc
    import ota_guard

    # only the files which are on the filesystem of the flash image;
    # lin.py, inetboxapp.py, conversions.py, ... are frozen in the firmware -
    # as .py files they would be compiled into the RAM (MemoryError at start)
    env = [
        ["/src/", "args.py", "/"],
        ["/lib/", "web_os.py", "/lib"],
        ["/lib/", "web_os_main.py", "/lib"],
        ["/src/", "tools.py", "/"],
        ["/src/", "main.py", "/"],
        ["/src/", "main1.py", "/"],
        ["/lib/", "connect.py", "/lib"],
        ["/src/", "update.py", "/"],
        ["/src/", "ota_guard.py", "/"],
        ["/src/", "diag.py", "/"],
        ["/src/", "boot.py", "/"],
        ["/src/", "release.py", "/"],
        ]

    def dest(e):
        return e[2].rstrip("/") + "/" + e[1]

    ota_guard._clear_dir(NEW)
    ota_guard._mkdir(NEW)
    ota_guard._mkdir(NEW + "/lib")
    for e in env:
        gc.collect()
        print("Downloading " + e[0] + e[1])
        _get_file(e[0] + e[1], NEW + dest(e), "download of " + e[1] + " failed")
        yield (e[1], True)

    # everything is downloaded - save the running release and switch
    ota_guard.backup([dest(e) for e in env])
    for e in env:
        os.rename(NEW + dest(e), dest(e))
    ota_guard._clear_dir(NEW)
    ota_guard.start_trial()
    ota_guard.set_status("installed " + new_rel + " @" + sha[:7] + " (was " + old_rel + "), testing")
    print("OTA: " + new_rel + " installed, trial starts")

# releases < 3.0.3 have no ota_guard.py yet (it comes with the update) - load it first
def _ensure_guard():
    import os
    try:
        import ota_guard
        return
    except ImportError:
        pass
    import time, machine
    for tries in range(5):
        try:
            _download("/src/ota_guard.py", "/ota_guard.py")
            return
        except Exception as ex:
            print("OTA: /src/ota_guard.py try " + str(tries + 1) + ": " + repr(ex))
            try:
                os.remove("/ota_guard.py")  # no half file
            except OSError:
                pass
            time.sleep(3)
    # GitHub not reachable: keep the running release, back to normal run-mode
    with open("/run_mode.dat", "w") as f:
        f.write("1")
    machine.reset()

# returns the release-no of the repo, without touching the local files
def read_repo_rel():
    global old_rel, new_rel
    _ensure_guard()
    import ota_guard
    old_rel = ota_guard._rel(ota_guard._read("/release.py") or "")
    ota_guard.set_status("checking for update (running " + old_rel + ")")
    _get_file("/src/release.py", "/ota_rel.py", "GitHub not reachable")
    new_rel = ota_guard._rel(ota_guard._read("/ota_rel.py") or "")
    ota_guard._remove("/ota_rel.py")
    if new_rel == "?":
        _abort("no release-no found in repo")
    if new_rel == old_rel:
        ota_guard.set_status(old_rel + " is up to date")
    return new_rel

