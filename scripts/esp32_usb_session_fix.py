"""Build-local owner-task hooks for Arduino-ESP32 native CDC session cleanup.

Do not patch the shared SDK. Fail closed when the native-CDC implementation
changes: the endpoint query must match the descriptor actually compiled.
"""
from pathlib import Path


GUARD = "#if ARDUINO_USB_CDC_ON_BOOT && !ARDUINO_USB_MODE\n"
CDC_INCLUDE = '#include "esp32-hal-tinyusb.h"\n'
CDC_HOOKS = GUARD + '''#include "device/usbd_pvt.h"
extern "C" void meshEsp32TinyUsbCdcLineState(bool dtr) __attribute__((weak));
extern "C" bool meshEsp32TinyUsbAcceptRx() __attribute__((weak));
extern "C" void meshEsp32TinyUsbTxComplete() __attribute__((weak));
extern "C" bool meshEsp32TinyUsbTxPending() {
    return usbd_edpt_busy(0, 0x84);
}
#endif
'''
LINE_STATE = "void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts)\n{\n"
LINE_HOOK = GUARD + '''    // Capture the close synchronously, before another host can enqueue RX.
    if (itf == 0 && meshEsp32TinyUsbCdcLineState) {
        meshEsp32TinyUsbCdcLineState(dtr);
    }
#endif
'''
RX = "void USBCDC::_onRX(){\n"
RX_HOOK = GUARD + '''    if (itf == 0 && meshEsp32TinyUsbAcceptRx && !meshEsp32TinyUsbAcceptRx()) {
        tud_cdc_n_read_flush(itf);
        return;
    }
#endif
'''
TX_COMPLETE = "void tud_cdc_tx_complete_cb(uint8_t itf){\n"
TX_HOOK = GUARD + '''    if (itf == 0 && meshEsp32TinyUsbTxComplete) {
        meshEsp32TinyUsbTxComplete();
    }
#endif
'''
USB_INCLUDE = '#include "esp32-hal-tinyusb.h"\n'
USB_HOOKS = GUARD + '''extern "C" void meshEsp32TinyUsbDeviceSessionBoundary(bool mounted) __attribute__((weak));
#endif
'''
MOUNT = "void tud_mount_cb(void){\n"
UNMOUNT = "void tud_umount_cb(void){\n"


def patched_cdc_source(source):
    source = source.replace("\r\n", "\n")
    descriptor = "TUD_CDC_DESCRIPTOR(*itf, str_index, 0x85, 64, 0x03, 0x84, 64)"
    if (source.count(CDC_HOOKS) == 1 and source.count(LINE_HOOK) == 1
            and source.count(RX_HOOK) == 1 and source.count(TX_HOOK) == 1
            and source.count(descriptor) == 1):
        return source
    if (source.count(CDC_INCLUDE) != 1 or source.count(LINE_STATE) != 1
            or source.count(RX) != 1 or source.count(TX_COMPLETE) != 1
            or source.count(descriptor) != 1
            or "meshEsp32TinyUsb" in source):
        raise RuntimeError("ESP32 USB session fix: changed native CDC/endpoint layout; review SDK update")
    return (source.replace(CDC_INCLUDE, CDC_INCLUDE + CDC_HOOKS)
            .replace(LINE_STATE, LINE_STATE + LINE_HOOK)
            .replace(RX, RX + RX_HOOK)
            .replace(TX_COMPLETE, TX_COMPLETE + TX_HOOK))


def patched_usb_source(source):
    source = source.replace("\r\n", "\n")
    mount_hook = GUARD + "    if (meshEsp32TinyUsbDeviceSessionBoundary) meshEsp32TinyUsbDeviceSessionBoundary(true);\n#endif\n"
    unmount_hook = GUARD + "    if (meshEsp32TinyUsbDeviceSessionBoundary) meshEsp32TinyUsbDeviceSessionBoundary(false);\n#endif\n"
    if (source.count(USB_HOOKS) == 1 and source.count(mount_hook) == 1
            and source.count(unmount_hook) == 1):
        return source
    if (source.count(USB_INCLUDE) != 1 or source.count(MOUNT) != 1
            or source.count(UNMOUNT) != 1 or "meshEsp32TinyUsb" in source):
        raise RuntimeError("ESP32 USB session fix: changed USB lifecycle callbacks; review SDK update")
    return (source.replace(USB_INCLUDE, USB_INCLUDE + USB_HOOKS)
            .replace(MOUNT, MOUNT + mount_hook)
            .replace(UNMOUNT, UNMOUNT + unmount_hook))


def native_primary_enabled(build_env):
    defines = {}
    for definition in build_env.get("CPPDEFINES", []):
        if isinstance(definition, (tuple, list)):
            defines[definition[0]] = str(definition[1])
        else:
            defines[str(definition)] = "1"
    return (defines.get("ARDUINO_USB_CDC_ON_BOOT") == "1"
            and defines.get("ARDUINO_USB_MODE") == "0")


def replace_source(build_env, node):
    if not native_primary_enabled(build_env):
        return node
    source = Path(node.srcnode().get_abspath())
    patcher = patched_cdc_source if source.name == "USBCDC.cpp" else patched_usb_source
    patched = patcher(source.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-esp32-usb" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_source, "*cores*esp32*USBCDC.cpp")
    build_env.AddBuildMiddleware(replace_source, "*cores*esp32*USB.cpp")


if "Import" in globals():
    Import("env")
    install(env)
