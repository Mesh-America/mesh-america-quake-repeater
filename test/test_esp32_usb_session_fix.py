"""Build-local native CDC hooks must precede delayed framework events."""
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("esp_usb_fix", ROOT / "scripts/esp32_usb_session_fix.py")
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)
CDC = '''#include "esp32-hal-tinyusb.h"
TUD_CDC_DESCRIPTOR(*itf, str_index, 0x85, 64, 0x03, 0x84, 64)
void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts)
{
    devices[itf]->_onLineState(dtr, rts);
}
void USBCDC::_onLineState(bool _dtr, bool _rts){
    if(dtr == _dtr && rts == _rts) return;
    dtr = _dtr;
    arduino_usb_event_post();
}
void USBCDC::_onRX(){
    tud_cdc_n_read();
    xQueueSend();
}
void tud_cdc_tx_complete_cb(uint8_t itf){
    devices[itf]->_onTX();
}
'''
USB = '''#include "esp32-hal-tinyusb.h"
void tud_mount_cb(void){
    arduino_usb_event_post();
}
void tud_umount_cb(void){
    arduino_usb_event_post();
}
'''


class Esp32UsbSessionFixTests(unittest.TestCase):
    def test_owner_hooks_precede_state_changes_and_rx_queue(self):
        patched = FIX.patched_cdc_source(CDC)
        self.assertLess(patched.index("meshEsp32TinyUsbCdcLineState(dtr);"),
                        patched.index("devices[itf]->_onLineState(dtr, rts);"))
        self.assertLess(patched.index("!meshEsp32TinyUsbAcceptRx()"),
                        patched.index("xQueueSend();"))
        self.assertLess(patched.index("meshEsp32TinyUsbTxComplete();"),
                        patched.index("devices[itf]->_onTX();"))
        self.assertIn("usbd_edpt_busy(0, 0x84)", patched)
        self.assertEqual(FIX.patched_cdc_source(patched), patched)
        device = FIX.patched_usb_source(USB)
        for signature in (FIX.MOUNT, FIX.UNMOUNT):
            callback = device[device.index(signature):]
            self.assertLess(callback.index("meshEsp32TinyUsbDeviceSessionBoundary"),
                            callback.index("arduino_usb_event_post"))
        self.assertEqual(FIX.patched_usb_source(device), device)

    def test_changed_sdk_or_endpoint_fails_closed(self):
        for original, changed in (("0x84", "0x82"), (FIX.LINE_STATE, "unknown() {"),
                                  (FIX.RX, "changed_rx() {"),
                                  (FIX.TX_COMPLETE, "changed_tx() {")):
            with self.subTest(changed=original), self.assertRaises(RuntimeError):
                FIX.patched_cdc_source(CDC.replace(original, changed))
        with self.assertRaises(RuntimeError):
            FIX.patched_usb_source(USB.replace(FIX.UNMOUNT, "changed_unmount() {"))
        self.assertEqual(FIX.patched_cdc_source(CDC.replace("\n", "\r\n")),
                         FIX.patched_cdc_source(CDC))

    def test_only_primary_native_cdc_uses_build_local_copy(self):
        class Environment(dict):
            def subst(self, value):
                return self["BUILD_DIR"]
            def File(self, value):
                return value
        class Node:
            def __init__(self, path): self.path = path
            def srcnode(self): return self
            def get_abspath(self): return str(self.path)
        with tempfile.TemporaryDirectory(prefix="meshcore-esp-usb-hook-") as directory:
            directory = Path(directory)
            source = directory / "USBCDC.cpp"
            source.write_text(CDC, encoding="utf-8")
            node = Node(source)
            env = Environment(BUILD_DIR=str(directory / "build"),
                              CPPDEFINES=[("ARDUINO_USB_CDC_ON_BOOT", 1), ("ARDUINO_USB_MODE", 0)])
            result = Path(FIX.replace_source(env, node))
            self.assertNotEqual(result, source)
            self.assertEqual(source.read_text(), CDC)
            self.assertEqual(result.read_text(), FIX.patched_cdc_source(CDC))
            for definitions in ([], [("ARDUINO_USB_CDC_ON_BOOT", 1), ("ARDUINO_USB_MODE", 1)],
                                [("ARDUINO_USB_CDC_ON_BOOT", 0), ("ARDUINO_USB_MODE", 0)]):
                env["CPPDEFINES"] = definitions
                self.assertIs(FIX.replace_source(env, node), node)

    def test_installed_sdk_compatibility_when_available(self):
        # Package-free CI still exercises the golden anchors above. Check an
        # installed SDK on Windows and Unix, including a custom PIO core dir.
        core = Path(os.environ.get("PLATFORMIO_CORE_DIR", str(Path.home() / ".platformio")))
        package = core / "packages/framework-arduinoespressif32/cores/esp32"
        if not (package / "USBCDC.cpp").is_file():
            self.skipTest("installed Arduino-ESP32 SDK unavailable")
        for name, patcher in (("USBCDC.cpp", FIX.patched_cdc_source), ("USB.cpp", FIX.patched_usb_source)):
            original = (package / name).read_text(encoding="utf-8")
            self.assertIn("meshEsp32TinyUsb", patcher(original))

    def test_all_esp32_profiles_inherit_hook(self):
        config = (ROOT / "platformio.ini").read_text()
        base = config[config.index("[esp32_base]"):config.index("[esp32_ota]")]
        self.assertIn("pre:scripts/esp32_usb_session_fix.py", base)


if __name__ == "__main__":
    unittest.main()
