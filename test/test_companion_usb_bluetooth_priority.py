"""Execute USB/Bluetooth priority transitions with the real transport manager."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_companion_bluetooth_control import HARNESS as BLUETOOTH_HARNESS
from test_radio_receive_contract import method


ROOT = Path(__file__).resolve().parents[1]


TRANSPORT_HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <helpers/MultiSerialInterface.h>
#include <helpers/UsbBluetoothPriority.h>

struct Transport : BaseSerialInterface {
 bool enabled=false,connected=false,frame=false;
 unsigned enables=0,disables=0,writes=0;
 void enable() override {enabled=true;++enables;}
 void disable() override {enabled=false;connected=false;++disables;}
 bool isEnabled() const override {return enabled;}
 bool isConnected() const override {return connected;}
 bool isReadBusy() const override {return false;}
 bool isWriteBusy() const override {return false;}
 size_t writeFrame(const uint8_t*,size_t n) override {++writes;return n;}
 size_t checkRecvFrame(uint8_t* out) override {
   if(!frame)return 0;frame=false;out[0]=0x42;return 1;
 }
};
struct Fixture {
 MultiSerialInterface manager;
 Transport ble,usb,wifi,ethernet;
 Fixture(){
   assert(manager.addInterface(InterfaceType::Bluetooth,&ble));
   assert(manager.addInterface(InterfaceType::USB,&usb));
   assert(manager.addInterface(InterfaceType::WiFi,&wifi));
   assert(manager.addInterface(InterfaceType::Ethernet,&ethernet));
 }
 void route(Transport& target){
   target.connected=true;target.frame=true;
   uint8_t data[176];assert(manager.checkRecvFrame(data)==1);
   assert(manager.captureReplyRoute()==&target);
 }
};
'''


class UsbBluetoothPriorityTests(unittest.TestCase):
    def compile_and_run(self, source_text, flags=()):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Arduino.h").write_text(
                "#pragma once\n#include <cstdint>\n#include <cstddef>\n"
                "#include <initializer_list>\n"
            )
            source = folder / "usb_ble_priority.cpp"
            source.write_text(source_text)
            binary = folder / "usb_ble_priority"
            built = subprocess.run(
                [
                    os.environ.get("CXX", "g++"),
                    "-std=c++17", "-Wall", "-Wextra",
                    "-I", str(folder), "-I", str(ROOT), "-I", str(ROOT / "src"),
                    *["-D" + flag for flag in flags],
                    str(source), "-o", str(binary),
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_data_host_priority_and_disconnect_hold(self):
        self.compile_and_run(TRANSPORT_HARNESS + r'''
int main(){
 mesh::UsbBluetoothPriority policy;
 // Battery and a charge-only cable have no enumerated data host.
 assert(!policy.update(false,0));
 assert(!policy.update(false,60000));
 assert(policy.update(true,60001));
 assert(policy.update(true,90000));
 // A bus reset cannot briefly advertise Bluetooth to a nearby phone.
 assert(policy.update(false,90001));
 assert(policy.update(false,90500));
 assert(!policy.update(false,90501));
 assert(!policy.update(false,100000));
 // Re-enumeration cancels the pending release, without inheriting its timer.
 assert(policy.update(true,100001));
 assert(policy.update(false,100010));
 assert(policy.update(true,100509));
 assert(policy.update(false,100510));
 assert(policy.update(false,101009));
 assert(!policy.update(false,101010));
 // The absence hold has the same duration when millis() wraps.
 mesh::UsbBluetoothPriority wrapped;
 assert(wrapped.update(true,0xfffffe00u));
 assert(wrapped.update(false,0xffffff00u));
 assert(wrapped.update(false,0x000000f3u));
 assert(!wrapped.update(false,0x000000f4u));
}
''')

    def test_boot_wake_and_explicit_requests_during_usb_priority(self):
        self.compile_and_run(TRANSPORT_HARNESS + r'''
int main(){
 Fixture f;
 f.manager.setBluetoothInhibited(true);
 assert(f.manager.isBluetoothInhibited());
 f.manager.enable();
 assert(!f.ble.enabled&&f.ble.enables==0);
 assert(f.usb.enabled&&f.wifi.enabled&&f.ethernet.enabled);
 // Opening/closing a serial application is not an enable route around USB.
 f.manager.enableBluetooth();
 assert(!f.ble.enabled&&f.ble.enables==0);
 const unsigned stopped=f.ble.disables;
 f.manager.setBluetoothInhibited(true);
 assert(f.ble.disables==stopped); // Repeated mounted polls are idempotent.
 f.manager.disable();f.manager.enable();
 assert(!f.ble.enabled&&f.ble.enables==0&&f.usb.enabled);
 f.manager.setBluetoothInhibited(false);
 assert(f.ble.enabled&&f.ble.enables==1);
 f.manager.setBluetoothInhibited(false);
 assert(f.ble.enables==1);
 // An off request while paused survives unplugging.
 f.manager.setBluetoothInhibited(true);
 f.manager.disableBluetooth();
 f.manager.setBluetoothInhibited(false);
 assert(!f.ble.enabled&&f.ble.enables==1);
 // An explicit on request is remembered, without advertising during USB.
 f.manager.setBluetoothInhibited(true);
 f.manager.enableBluetooth();
 assert(!f.ble.enabled&&f.ble.enables==1);
 f.manager.setBluetoothInhibited(false);
 assert(f.ble.enabled&&f.ble.enables==2);
 // Saved-off startup/wake remains off after the temporary policy clears.
 Fixture off;
 off.manager.setBluetoothAutoEnable(false);
 off.manager.setBluetoothInhibited(true);off.manager.enable();
 off.manager.setBluetoothInhibited(false);
 assert(!off.ble.enabled&&off.ble.enables==0&&off.usb.enabled);
 off.manager.setBluetoothInhibited(true);off.manager.enableBluetooth();
 off.manager.setBluetoothInhibited(false);
 assert(off.ble.enabled&&off.ble.enables==1); // Runtime-only override.
 off.manager.disable();off.manager.enable();
 assert(!off.ble.enabled&&off.ble.enables==1);
 // An unplug cannot wake the aggregate transport when it is disabled.
 Fixture sleeping;
 sleeping.manager.enable();sleeping.manager.setBluetoothInhibited(true);
 sleeping.manager.disable();
 const unsigned sleeping_enables=sleeping.ble.enables;
 sleeping.manager.setBluetoothInhibited(false);
 assert(!sleeping.ble.enabled&&sleeping.ble.enables==sleeping_enables);
}
''')

    def test_actual_t1000_service_uses_enumeration_and_cancels_only_bluetooth(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text()
        service = method(main, "static void serviceCompanionUsbBluetoothPriority(")
        source = TRANSPORT_HARNESS + r'''
uint32_t now_ms=0;
uint32_t millis(){return now_ms;}
MultiSerialInterface interface_manager;
Transport bluetooth_interface,usb_interface;
struct {
 bool host=false,charging=true,reader=false;
 unsigned samples=0;
 bool isUsbHostConnected(){++samples;return host;}
} board;
struct {
 unsigned streams=0,operations=0;
 void cancelSerialResponseStream(BaseSerialInterface* route){
   assert(route==&bluetooth_interface);++streams;
 }
 void cancelSerialOperationsForRoute(BaseSerialInterface* route){
   assert(route==&bluetooth_interface);++operations;
 }
} the_mesh;
''' + service + r'''
int main(){
 interface_manager.addInterface(InterfaceType::Bluetooth,&bluetooth_interface);
 interface_manager.addInterface(InterfaceType::USB,&usb_interface);
 serviceCompanionUsbBluetoothPriority();interface_manager.enable();
 assert(bluetooth_interface.enabled&&board.charging&&!board.reader);
 board.host=true;now_ms=100;serviceCompanionUsbBluetoothPriority();
#if defined(T1000_E) && defined(USE_TINYUSB)
 assert(interface_manager.isBluetoothInhibited()&&!bluetooth_interface.enabled);
 assert(usb_interface.enabled&&the_mesh.streams==1&&the_mesh.operations==1);
 // The host stays enumerated even with both serial readers closed.
 now_ms=10000;serviceCompanionUsbBluetoothPriority();
 assert(!bluetooth_interface.enabled&&the_mesh.streams==1);
 board.reader=true;now_ms=10001;serviceCompanionUsbBluetoothPriority();
 board.reader=false;now_ms=10002;serviceCompanionUsbBluetoothPriority();
 assert(!bluetooth_interface.enabled&&the_mesh.operations==1);
 board.host=false;now_ms=10003;serviceCompanionUsbBluetoothPriority();
 now_ms=10502;serviceCompanionUsbBluetoothPriority();
 assert(!bluetooth_interface.enabled);
 now_ms=10503;serviceCompanionUsbBluetoothPriority();
 assert(bluetooth_interface.enabled&&!interface_manager.isBluetoothInhibited());
 assert(the_mesh.streams==1&&the_mesh.operations==1&&usb_interface.enabled);
#else
 assert(bluetooth_interface.enabled&&!interface_manager.isBluetoothInhibited());
 assert(board.samples==0&&the_mesh.streams==0&&the_mesh.operations==0);
#endif
}
'''
        for flags in (
            ("T1000_E=1", "USE_TINYUSB=1"),
            ("USE_TINYUSB=1",),
            ("T1000_E=1",),
        ):
            with self.subTest(configuration=flags):
                self.compile_and_run(source, flags=flags)

    def test_priority_preserves_usb_routes_and_rejects_old_bluetooth_replies(self):
        self.compile_and_run(TRANSPORT_HARNESS + r'''
int main(){
 const uint8_t reply[]={1,2,3};
 Fixture f;f.manager.enable();f.route(f.usb);
 const unsigned usb_enables=f.usb.enables,usb_disables=f.usb.disables;
 f.manager.setBluetoothInhibited(true);
 assert(f.manager.captureReplyRoute()==&f.usb);
 assert(f.manager.isReplyRouteAvailable(&f.usb));
 assert(f.manager.writeFrame(reply,sizeof(reply))==sizeof(reply));
 assert(f.usb.writes==1&&f.ble.writes==0);
 assert(f.usb.enabled&&f.wifi.enabled&&f.ethernet.enabled);
 assert(f.usb.enables==usb_enables&&f.usb.disables==usb_disables);
 // An interrupted multi-frame BLE reply must not fall back to USB.
 f.manager.setBluetoothInhibited(false);f.route(f.ble);
 f.manager.lockReplyRoute();f.manager.setBluetoothInhibited(true);
 assert(!f.manager.isReplyRouteAvailable(&f.ble));
 assert(f.manager.writeFrameToRoute(&f.ble,reply,sizeof(reply))==0);
 assert(f.manager.writeFrame(reply,sizeof(reply))==0);
 assert(f.usb.writes==1&&f.ble.writes==0);
 f.manager.unlockReplyRoute();f.route(f.usb);
 assert(f.manager.writeFrame(reply,sizeof(reply))==sizeof(reply));
 assert(f.usb.writes==2);
}
''')

    def test_wireless_master_off_remains_off_after_usb_disconnect(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text()
        prefix = BLUETOOTH_HARNESS.split("@METHODS@")[0]
        adapter = method(main, "class CompanionWirelessBackend") + ";\n"
        disable = method(main, "static void disableCompanionBluetoothForCli(")
        self.compile_and_run(prefix + disable + adapter + r'''
int main(){
 using namespace mesh::wireless;
 interface_manager.addInterface(InterfaceType::Bluetooth,&bluetooth_interface);
 interface_manager.addInterface(InterfaceType::USB,&usb_serial_interface);
 interface_manager.enable();
 CompanionWirelessBackend backend;control().begin(backend);
 interface_manager.setBluetoothInhibited(true);
 assert(!bluetooth_interface.enabled&&the_mesh.durable_bluetooth_preference);
 char status[192];
 assert(control().handle("set 2.4ghz off",status,sizeof(status),now_ms,Independent));
 now_ms+=250;control().service(now_ms);
 assert(control().masterOff()&&control().blocked(Bluetooth));
 assert(!control().pending());
 const unsigned previous_enables=bluetooth_interface.enables;
 interface_manager.setBluetoothInhibited(false);
 interface_manager.enableBluetooth(); // Master-off is still authoritative.
 assert(!bluetooth_interface.enabled&&bluetooth_interface.enables==previous_enables);
 interface_manager.disable();interface_manager.enable();
 assert(!bluetooth_interface.enabled&&usb_serial_interface.enabled);
 assert(the_mesh.durable_bluetooth_preference&&the_mesh.saves==0);
 // Explicit restore-all is accepted while USB owns the transport. Reporting
 // a startup failure here would contradict the remembered resume request.
 interface_manager.setBluetoothInhibited(true);
 assert(control().handle("set 2.4ghz on all",status,sizeof(status),now_ms,Independent));
 now_ms+=250;control().service(now_ms);
 assert(!control().pending()&&!control().masterOff()&&!control().blocked(Bluetooth));
 assert(!bluetooth_interface.enabled); // No bypass during USB priority.
 assert(control().handle("get 2.4ghz",status,sizeof(status),now_ms,Independent));
 assert(!strstr(status,"failed"));
 interface_manager.setBluetoothInhibited(false);
 assert(bluetooth_interface.enabled&&usb_serial_interface.enabled);
 assert(the_mesh.durable_bluetooth_preference&&the_mesh.saves==0);
}
''', flags=("BLE_PIN_CODE=1", "NRF52_PLATFORM=1", "ENABLE_USB_INTERFACE=1"))

    def test_cli_saved_on_pauses_for_usb_and_saved_off_survives_unplug(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text()
        prefix = BLUETOOTH_HARNESS.split("@METHODS@")[0]
        methods = "\n".join(method(main, signature) for signature in (
            "static bool hasCompanionNonBluetoothClient(",
            "static void disableCompanionBluetoothForCli(",
            "bool handleCompanionBluetoothCommand(",
        ))
        self.compile_and_run(prefix + methods + r'''
int main(){
 interface_manager.addInterface(InterfaceType::Bluetooth,&bluetooth_interface);
 interface_manager.addInterface(InterfaceType::USB,&usb_serial_interface);
 interface_manager.enable();interface_manager.setBluetoothInhibited(true);
 char reply[192];
 assert(handleCompanionBluetoothCommand("get bluetooth",reply,sizeof(reply)));
 assert(strstr(reply,"off")&&strstr(reply,"USB"));
 const unsigned previous_enables=bluetooth_interface.enables;
 assert(handleCompanionBluetoothCommand("set bluetooth on",reply,sizeof(reply)));
 assert(strstr(reply,"OK")&&strstr(reply,"USB"));
 assert(the_mesh.durable_bluetooth_preference&&!bluetooth_interface.enabled);
 assert(bluetooth_interface.enables==previous_enables);
 interface_manager.setBluetoothInhibited(false);
 assert(bluetooth_interface.enabled);
 interface_manager.setBluetoothInhibited(true);
 assert(handleCompanionBluetoothCommand("set bluetooth off",reply,sizeof(reply)));
 assert(strstr(reply,"OK")&&!the_mesh.durable_bluetooth_preference);
 interface_manager.setBluetoothInhibited(false);
 assert(!bluetooth_interface.enabled);
 // Failed preference persistence cannot turn a saved-off device on later.
 interface_manager.setBluetoothInhibited(true);the_mesh.storage_accepts=false;
 assert(handleCompanionBluetoothCommand("set bluetooth on",reply,sizeof(reply)));
 assert(strstr(reply,"Error")&&!the_mesh.durable_bluetooth_preference);
 interface_manager.setBluetoothInhibited(false);
 assert(!bluetooth_interface.enabled&&usb_serial_interface.enabled);
}
''', flags=("BLE_PIN_CODE=1", "NRF52_PLATFORM=1", "ENABLE_USB_INTERFACE=1"))


if __name__ == "__main__":
    unittest.main()
