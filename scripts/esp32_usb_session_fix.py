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



# HWCDC fixes are deliberately limited to the installed Arduino2.0.17 C3/S3
# native Serial/JTAG driver. Other versions retain their own framework driver.
PINNED_HWCDC_SHA256 = "d0a8ca606c2729c8522a041113285dbf27033c22a5a6af8649a7305ffe84c449"
PATCHED_HWCDC_SHA256 = "5107db35dc3c855326dff0a9b93b279ee9bda60b5cc1ebcdce77a9028e3577b4"
HWCDC_TX_SUPPORT = r"""
// MeshCore pinned HWCDC TX suffix/interrupt backport (upstream #12606).
static uint8_t mesh_hwcdc_tx_stash[64] = {0};
static size_t mesh_hwcdc_tx_stash_len = 0;
static bool mesh_hwcdc_tx_allowed = true;
static bool mesh_hwcdc_fifo_pending = false;
static uint32_t mesh_hwcdc_active_writers = 0;
static portMUX_TYPE mesh_hwcdc_tx_mux = portMUX_INITIALIZER_UNLOCKED;

static inline void mesh_hwcdc_enable_tx_intr() {
    portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    if (mesh_hwcdc_tx_allowed) {
        usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
    }
    portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
}

extern "C" void meshEsp32HwcdcSetTxAllowed(bool allowed) {
    portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    mesh_hwcdc_tx_allowed = allowed;
    if (!allowed) usb_serial_jtag_ll_disable_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
    portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
}

extern "C" void meshEsp32HwcdcKickTx() {
    portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    if (mesh_hwcdc_tx_allowed) {
        usb_serial_jtag_ll_txfifo_flush();
        usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
    }
    portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
}

extern "C" bool meshEsp32HwcdcTxPending() {
    portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    UBaseType_t waiting = 0;
    if (tx_ring_buf) vRingbufferGetInfo(tx_ring_buf, NULL, NULL, NULL, NULL, &waiting);
    const bool pending = mesh_hwcdc_tx_stash_len != 0 || waiting != 0
        || mesh_hwcdc_fifo_pending || mesh_hwcdc_active_writers != 0;
    portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    return pending;
}

static inline void mesh_hwcdc_clear_tx_stash() {
    portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    mesh_hwcdc_tx_stash_len = 0;
    portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
}

extern "C" bool meshEsp32HwcdcDiscardTxStash() {
    // Caller has detached pads and stopped producers. Do not mistake ordinary
    // flush/ring-empty for completion of a previously staged FIFO payload.
    portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    const bool permitted = !mesh_hwcdc_tx_allowed && mesh_hwcdc_active_writers == 0;
    if (permitted) {
        mesh_hwcdc_tx_stash_len = 0;
        mesh_hwcdc_fifo_pending = false;
    }
    portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    return permitted;
}

class mesh_hwcdc_writer_scope {
    bool _entered;
public:
    mesh_hwcdc_writer_scope() {
        portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
        _entered = mesh_hwcdc_tx_allowed;
        if (_entered) ++mesh_hwcdc_active_writers;
        portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    }
    ~mesh_hwcdc_writer_scope() {
        if (!_entered) return;
        portENTER_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
        --mesh_hwcdc_active_writers;
        portEXIT_CRITICAL_SAFE(&mesh_hwcdc_tx_mux);
    }
    operator bool() const { return _entered; }
    mesh_hwcdc_writer_scope(const mesh_hwcdc_writer_scope&) = delete;
    mesh_hwcdc_writer_scope& operator=(const mesh_hwcdc_writer_scope&) = delete;
};
"""
HWCDC_IN_EMPTY = r"""    if (usbjtag_intr_status & USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY) {
        // A real host pickup is stronger proof than the SOF tick heuristic.
        connected = true;
        usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
        size_t sent_size = 0;
        bool staged = false;
        portENTER_CRITICAL_ISR(&mesh_hwcdc_tx_mux);
        mesh_hwcdc_fifo_pending = false; // this IN_EMPTY acknowledges the previous payload
        if (!mesh_hwcdc_tx_allowed) {
            usb_serial_jtag_ll_disable_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
        } else if (tx_ring_buf != NULL && usb_serial_jtag_ll_txfifo_writable() == 1) {
            size_t queued_size = mesh_hwcdc_tx_stash_len;
            bool from_stash = queued_size != 0;
            uint8_t* queued_buff = from_stash ? mesh_hwcdc_tx_stash
                : (uint8_t*)xRingbufferReceiveUpToFromISR(tx_ring_buf, &queued_size, 64);
            if (queued_buff != NULL && queued_size != 0) {
                sent_size = usb_serial_jtag_ll_write_txfifo(queued_buff, queued_size);
                usb_serial_jtag_ll_txfifo_flush();
                staged = true;
                mesh_hwcdc_fifo_pending = sent_size != 0;
                mesh_hwcdc_tx_stash_len = queued_size - sent_size;
                if (mesh_hwcdc_tx_stash_len) {
                    memmove(mesh_hwcdc_tx_stash, queued_buff + sent_size, mesh_hwcdc_tx_stash_len);
                }
                if (!from_stash) vRingbufferReturnItemFromISR(tx_ring_buf, queued_buff, &xTaskWoken);
                usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
            } else {
                // Preserve the full-packet terminating ZLP. Disable and inspect
                // again under the producer/ISR lock so a wakeup cannot be lost.
                usb_serial_jtag_ll_txfifo_flush();
                usb_serial_jtag_ll_disable_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
                UBaseType_t waiting = 0;
                vRingbufferGetInfo(tx_ring_buf, NULL, NULL, NULL, NULL, &waiting);
                if (waiting || mesh_hwcdc_tx_stash_len) {
                    usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
                }
            }
        }
        portEXIT_CRITICAL_ISR(&mesh_hwcdc_tx_mux);
        if (staged) {
            event.tx.len = sent_size;
            arduino_hw_cdc_event_post(ARDUINO_HW_CDC_EVENTS, ARDUINO_HW_CDC_TX_EVENT,
                &event, sizeof(arduino_hw_cdc_event_data_t), &xTaskWoken);
        }
    }

"""
HWCDC_CONNECTED = r"""bool HWCDC::isCDC_Connected()
{
    if (!isPlugged()) {
        connected = false;
        return false;
    }
    if (connected) return true;
    // Re-arm on every attempt. Keep a suffix across transient SOF false.
    meshEsp32HwcdcKickTx();
    return false;
}

"""


def patched_hwcdc_source(source):
    import hashlib
    source = source.replace("\r\n", "\n")
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest == PATCHED_HWCDC_SHA256:
        return source
    if digest != PINNED_HWCDC_SHA256:
        raise RuntimeError("ESP32 HWCDC TX fix: changed pinned2.0.17 source; review SDK update")
    # Perform exact-shape transforms only after the complete input hash passes.
    source = source.replace('#include "esp_freertos_hooks.h"\n',
                            '#include "esp_freertos_hooks.h"\n#include <string.h>\n', 1)
    source = source.replace('usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);',
                            'mesh_hwcdc_enable_tx_intr();')
    begin = source.index('    if (usbjtag_intr_status & USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY) {')
    end = source.index('    if (usbjtag_intr_status & USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT) {', begin)
    source = source[:begin] + HWCDC_IN_EMPTY + source[end:]
    begin = source.index('bool HWCDC::isCDC_Connected()')
    end = source.index('static void flushTXBuffer(', begin)
    source = source[:begin] + HWCDC_CONNECTED + source[end:]
    source = source.replace('static xSemaphoreHandle tx_lock = NULL;\n',
                            'static xSemaphoreHandle tx_lock = NULL;\n' + HWCDC_TX_SUPPORT, 1)
    source = source.replace('        connected = false;\n    }\n\n//    if (usbjtag_intr_status',
                            '        portENTER_CRITICAL_ISR(&mesh_hwcdc_tx_mux);\n'
                            '        mesh_hwcdc_tx_stash_len = 0;\n        mesh_hwcdc_fifo_pending = false;\n'
                            '        portEXIT_CRITICAL_ISR(&mesh_hwcdc_tx_mux);\n        connected = false;\n    }\n\n//    if (usbjtag_intr_status', 1)
    source = source.replace('    if(buffer == NULL) {\n',
                            '    if(buffer == NULL) {\n        mesh_hwcdc_clear_tx_stash();\n', 1)
    source = source.replace('size_t HWCDC::setTxBufferSize(size_t tx_queue_len){\n',
                            'size_t HWCDC::setTxBufferSize(size_t tx_queue_len){\n    mesh_hwcdc_clear_tx_stash();\n', 1)
    source = source.replace('    if(tx_ring_buf == NULL) {\n        return;\n    }\n    if(!HWCDC::isConnected())',
                            '    if(tx_ring_buf == NULL) {\n        return;\n    }\n'
                            '    mesh_hwcdc_writer_scope writer;\n    if (!writer) return;\n    if(!HWCDC::isConnected())', 1)
    source = source.replace('size_t HWCDC::write(const uint8_t *buffer, size_t size)\n{\n',
                            'size_t HWCDC::write(const uint8_t *buffer, size_t size)\n{\n'
                            '    mesh_hwcdc_writer_scope writer;\n    if (!writer) return 0;\n', 1)
    source = source.replace('        flushTXBuffer((const uint8_t*)&c, 1);\n        return;\n',
                            '        flushTXBuffer((const uint8_t*)&c, 1);\n        meshEsp32HwcdcKickTx();\n        return;\n', 1)
    # The disconnected write path previously left new bytes parked without
    # an interrupt. Kick after its existing FIFO-policy admission.
    source = source.replace('        flushTXBuffer(buffer, size);\n    } else {\n',
                            '        flushTXBuffer(buffer, size);\n        meshEsp32HwcdcKickTx();\n    } else {\n', 1)
    return source


def hwcdc_primary_enabled(build_env):
    defines = {}
    for definition in build_env.get("CPPDEFINES", []):
        if isinstance(definition, (tuple, list)):
            defines[definition[0]] = str(definition[1])
        else:
            defines[str(definition)] = "1"
    return (defines.get("ARDUINO_USB_CDC_ON_BOOT") == "1"
            and defines.get("ARDUINO_USB_MODE") == "1")


def pinned_hwcdc_framework(source):
    import re
    version = source.parent / "esp_arduino_version.h"
    values = dict(re.findall(r"^#define ESP_ARDUINO_VERSION_(MAJOR|MINOR|PATCH)\s+(\d+)\s*$",
                             version.read_text(encoding="utf-8"), re.MULTILINE))
    if set(values) != {"MAJOR", "MINOR", "PATCH"}:
        raise RuntimeError("ESP32 HWCDC TX fix: malformed framework version header")
    return values == {"MAJOR": "2", "MINOR": "0", "PATCH": "17"}


def replace_hwcdc_source(build_env, node):
    if not hwcdc_primary_enabled(build_env):
        return node
    source = Path(node.srcnode().get_abspath())
    if not pinned_hwcdc_framework(source):
        return node
    patched = patched_hwcdc_source(source.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-esp32-usb" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    build_env.AppendUnique(CPPPATH=[str(source.parent)])
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_source, "*cores*esp32*USBCDC.cpp")
    build_env.AddBuildMiddleware(replace_source, "*cores*esp32*USB.cpp")
    build_env.AddBuildMiddleware(replace_hwcdc_source, "*cores*esp32*HWCDC.cpp")


if "Import" in globals():
    Import("env")
    install(env)
