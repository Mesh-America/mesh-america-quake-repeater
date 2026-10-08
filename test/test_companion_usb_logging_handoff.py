#!/usr/bin/env python3
"""Execute real USB logging/mOTA handoffs across retained response boundaries."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test_companion_usb_input import (
    CONTEXT, HARNESS, MAIN, ROOT, bind_production_input_constants,
)
from test_replay_reset_integration import extract_braced


CASES = r'''
static void selectAscii() {
  if (!the_mesh.terminal) {
    input.push(USB_TERMINAL_START_TOKEN); input.push("\n");
    uint8_t frame[MAX_FRAME_SIZE]={};
    assert(usb_serial_interface.checkRecvFrame(frame)==0);
    serviceUsbTerminal();
    assert(the_mesh.terminal);
  }
}

static void verifyNextClients() {
  selectAscii();
  input.push("get name\r\n"); serviceUsbTerminal();
  assert(the_mesh.commands.size()==1 && the_mesh.commands[0]=="get name");
  logging=false; serviceUsbLoggingOwnership(false);
  input.push(USB_TERMINAL_STOP_TOKEN); serviceUsbTerminal();
  assert(!the_mesh.terminal && !usb_serial_interface.isPassthroughMode());
  input.frame();
  uint8_t frame[MAX_FRAME_SIZE]={};
  assert(usb_serial_interface.checkRecvFrame(frame)==2);
  assert(frame[0]==0x16 && frame[1]==3);
  assert(usb_serial_interface.getCompletedFrameCount()==1);
}

static void responseHandoffs() {
  // Every partial stage is exercised, with image bytes that resemble both
  // ASCII ownership commands and Companion framing (including embedded NUL).
  const char controls[]="\nget name\r\nota folder off\n+++MESHCORE-TERM-STOP\n";
  std::vector<uint8_t> payload(controls,controls+sizeof(controls)-1);
  payload.insert(payload.end(),{'<',2,0,0x16,3});
  for (uint8_t status : {uint8_t(0),uint8_t(1)}) {
    const auto late=response(3,status==0?payload:std::vector<uint8_t>{},status);
    for (size_t prefix=0;prefix<late.size();++prefix) {
      for (bool logging_after_close : {false,true}) {
        for (bool logging_off_before_close : {false,true}) {
          for (auto origin : {mesh::UsbMotaEntryOrigin::ASCII,
                              mesh::UsbMotaEntryOrigin::BINARY}) {
            reset(); network=false; leaveUsbTerminalMode(false);
            assert(enterUsbMotaMode(origin));
            auto& source=mesh::ota::OtaContext::serialFolderSource();
            input.responses.emplace_back(late.begin(),late.begin()+prefix);
            std::vector<uint8_t> data(payload.size());
            assert(!source.read(0,0,data.data(),data.size()));
            assert(source.hasPendingResponse());
            logging=network=true; serviceUsbLoggingOwnership(true);
            assert(!usb_mota_mode && usb_logging_network_parked);
            assert(usb_serial_interface.isPassthroughMode());
            assert(the_mesh.attaches==1 && the_mesh.detaches==1);
            if (logging_off_before_close) {
              logging=false; serviceUsbLoggingOwnership(false);
              assert(!usb_logging_network_parked && source.hasPendingResponse());
              assert(usb_serial_interface.isPassthroughMode());
            }
            network=false; logging=logging_after_close;
            uint8_t command[MAX_FRAME_SIZE]={};
            for (size_t i=prefix;i<late.size();++i) {
              input.bytes.push_back(late[i]);
              serviceUsbLoggingOwnership(logging);
              // Unparking cannot raw-drain the retained response, even if
              // diagnostics are being disabled at the same time.
              assert(input.available()==1);
              assert(usb_serial_interface.isPassthroughMode());
              assert(usb_serial_interface.checkRecvFrame(command)==0);
              serviceUsbTerminal();
              assert(source.hasPendingResponse()==(i+1<late.size()));
              assert(the_mesh.commands.empty() && the_mesh.detaches==1);
              assert(!usb_serial_interface.hasReceivedFrame());
            }
            assert(!usb_logging_network_parked && !source.hasPendingResponse());
            verifyNextClients();
          }
        }
      }
    }
  }

  // The boundary consumer stops at the checksum, leaving a subsequent real
  // ASCII command intact rather than discarding the entire queued snapshot.
  reset(); network=false; leaveUsbTerminalMode(false);
  assert(enterUsbMotaMode(mesh::UsbMotaEntryOrigin::BINARY));
  auto& source=mesh::ota::OtaContext::serialFolderSource();
  const auto late=response(3,{42,43});
  input.responses.emplace_back(late.begin(),late.begin()+5);
  uint8_t data[2]={}; assert(!source.read(0,0,data,2));
  logging=network=true; serviceUsbLoggingOwnership(true);
  for (size_t i=5;i<late.size();++i) input.bytes.push_back(late[i]);
  input.push("get name\n"); network=false;
  serviceUsbTerminal();
  assert(!source.hasPendingResponse() && input.available()==9);
  assert(the_mesh.commands.empty());
  serviceUsbTerminal();
  assert(the_mesh.commands.size()==1 && the_mesh.commands[0]=="get name");

  // Without a retained binary response, the original bounded discard still
  // removes log-only input. A refilling source cannot trap this handoff.
  reset(); network=true; logging=true; leaveUsbTerminalMode(false);
  serviceUsbLoggingOwnership(true); assert(usb_logging_network_parked);
  input.push("xxxx"); input.replenish=true;
  const unsigned reads=input.reads; network=false;
  serviceUsbLoggingOwnership(true);
  assert(input.reads==reads+4 && input.available()==4);
  assert(!usb_logging_network_parked && the_mesh.terminal);
  input.replenish=false;
}

static void probeHandoffs() {
  // Empty and oversize startup frames grant no Binary proof; a deliberate
  // mOTA token after either must supersede the abandoned probe's deadline.
  for (uint16_t length : {uint16_t(0),uint16_t(177),uint16_t(65535)}) {
    for (bool attach_succeeds : {false,true}) {
      reset(); network=false; the_mesh.attach_succeeds=attach_succeeds;
      input.bytes={'<',uint8_t(length),uint8_t(length>>8)};
      for (uint32_t i=0;i<length;++i) input.bytes.push_back('x');
      input.push("ota folder on\n"); serviceUsbTerminal();
      assert(usb_binary_startup_probe.isActive() && !the_mesh.terminal);
      uint8_t frame[MAX_FRAME_SIZE]={};
      assert(usb_serial_interface.checkRecvFrame(frame)==0);
      assert(!usb_serial_interface.hasReceivedFrame());
      serviceUsbTerminal();
      assert(usb_mota_mode==attach_succeeds && !the_mesh.terminal);
      assert(!usb_binary_startup_probe.isActive());
      assert(usb_serial_interface.isPassthroughMode()==attach_succeeds);
      const unsigned banners=the_mesh.banners;
      input.bytes.push_back('x'); g_mock_millis+=1001;
      expireUsbBinaryStartupProbeBeforeDispatch();
      assert(usb_mota_mode==attach_succeeds && !the_mesh.terminal);
      assert(the_mesh.banners==banners && input.available()==1);
    }
  }

  // A deferred ASCII default from a prior network handoff must also lose to
  // deliberate mOTA ownership, including Binary-origin attach failure.
  for (bool attach_succeeds : {false,true}) {
    for (auto origin : {mesh::UsbMotaEntryOrigin::ASCII,
                        mesh::UsbMotaEntryOrigin::BINARY}) {
      reset(); leaveUsbTerminalMode(false); network=true;
      usb_ascii_session_default.request(usb_serial_interface.getCompletedFrameCount());
      usb_binary_startup_probe.start(millis(),usb_serial_interface.getCompletedFrameCount());
      the_mesh.attach_succeeds=attach_succeeds;
      assert(enterUsbMotaMode(origin)==attach_succeeds);
      assert(!usb_binary_startup_probe.isActive());
      network=false; serviceUsbAsciiSessionDefault();
      assert(!usb_ascii_session_default.shouldRestore(
          true,false,usb_serial_interface.getCompletedFrameCount()));
      assert(usb_mota_mode==attach_succeeds);
      assert(the_mesh.terminal==(!attach_succeeds && origin==mesh::UsbMotaEntryOrigin::ASCII));
    }
  }
}

int main() { responseHandoffs(); probeHandoffs(); }
'''


class CompanionUsbLoggingHandoffTests(unittest.TestCase):
    def test_actual_logging_and_mota_ownership(self):
        functions = "\n".join(extract_braced(MAIN, signature) for signature in (
            "static void clearUsbTerminalLine()",
            "static bool acceptUsbBinaryStartupFrame(uint32_t completed_at)",
            "static void enterUsbTerminalMode(bool show_banner",
            "static void enterUsbLoggingTerminalMode()",
            "static void leaveUsbTerminalMode(bool acknowledge)",
            "static void resetUsbMotaMode()",
            "static void leaveUsbMotaMode(bool acknowledge)",
            "static bool enterUsbMotaMode(mesh::UsbMotaEntryOrigin origin)",
            "static void serviceUsbMota()",
            "static bool serviceUsbMotaResponseBoundary()",
            "static void resetUsbTerminalHostSession()",
            "static void serviceUsbAsciiSessionDefault()",
            "static void serviceUsbLoggingOwnership(bool logging_enabled) {",
            "static void serviceUsbTerminal()",
            "static void expireUsbBinaryStartupProbeBeforeDispatch()",
        ))
        functions = functions.replace(
            "static void enterUsbTerminalMode(bool show_banner)",
            "static void enterUsbTerminalMode(bool show_banner = true)")
        harness = HARNESS[:HARNESS.index("int main()")]
        harness = harness.replace("#define COMPANION_FEATURE_NETWORK_TERMINAL 0",
                                  "#define COMPANION_FEATURE_NETWORK_TERMINAL 1")
        harness = harness.replace(
            "static void serviceUsbLoggingOwnership(bool) {}",
            "static bool network=false;\n"
            "static bool usb_terminal_host_reset_completion_pending=false;\n"
            "static bool isNetworkTerminalActive() { return network; }\n"
            "static void serviceUsbLoggingOwnership(bool);")
        source = bind_production_input_constants(harness.replace("@FUNCTIONS@", functions).replace(
            "@SOURCE_ACCESSOR@",
            extract_braced(CONTEXT, "static SerialMotaSource& serialFolderSource()")))
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "usb-handoff.cpp"
            cpp.write_text(source + CASES, encoding="ascii")
            for sanitizer in (False, True):
                with self.subTest(sanitizer=sanitizer):
                    binary = Path(directory) / ("usb-handoff-" + str(sanitizer))
                    flags = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                              "-fno-pie", "-no-pie"] if sanitizer else [])
                    build = subprocess.run([
                        "g++", "-std=c++17", *flags,
                        "-I", str(ROOT / "test/mocks"), "-I", str(ROOT / "src"),
                        str(cpp), str(ROOT / "src/helpers/ArduinoSerialInterface.cpp"),
                        str(ROOT / "src/helpers/ota/MotaSourceSerial.cpp"),
                        "-o", str(binary)], capture_output=True, text=True, timeout=60)
                    self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
                    run = subprocess.run([str(binary)], capture_output=True,
                                         text=True, timeout=20)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
