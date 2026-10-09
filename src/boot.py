# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
#import webrepl
#webrepl.start()

# OTA safety net: a new release which doesn't start is rolled back
try:
    import ota_guard
    ota_guard.check_trial()
except Exception as e:
    print("ota_guard:", repr(e))
