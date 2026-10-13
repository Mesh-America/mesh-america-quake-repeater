#!/usr/bin/env python3
"""Run real USB editing, Morse progress and the existing short-write queue."""
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_companion_usb_input as usb
from test_radio_receive_contract import method
from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]


class MorseTerminalInputTests(unittest.TestCase):
    def test_actual_parser_editing_reply_and_physical_short_write_ownership(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text(encoding="ascii")
        mesh = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text(encoding="ascii")
        header = (ROOT / "examples/companion_radio/MyMesh.h").read_text(encoding="ascii")
        functions = "\n".join(extract_braced(main, signature) for signature in (
            "static void clearUsbTerminalLine()",
            "static bool acceptUsbBinaryStartupFrame(uint32_t completed_at)",
            "static void enterUsbTerminalMode(bool show_banner",
            "static void leaveUsbTerminalMode(bool acknowledge)",
            "static void resetUsbMotaMode()",
            "static void leaveUsbMotaMode(bool acknowledge)",
            "static bool enterUsbMotaMode(mesh::UsbMotaEntryOrigin origin)",
            "static void serviceUsbMota()",
            "static bool serviceUsbMotaResponseBoundary()",
            "static void resetUsbTerminalHostSession()",
            "static void serviceUsbTerminal()",
            "static void expireUsbBinaryStartupProbeBeforeDispatch()",
            "static void syncUsbTerminalInputEditing()",
        )).replace("static void enterUsbTerminalMode(bool show_banner)",
                   "static void enterUsbTerminalMode(bool show_banner = true)")
        producer = method(mesh, "void MyMesh::serviceMorseTerminal(").replace("MyMesh::", "Mesh::")
        setter = method(header, "void setTerminalInputEditing(")
        code = usb.HARNESS.split("static void reset()", 1)[0]
        code = code.replace('#include <cassert>', '#include <cassert>\n#include <helpers/NonBlockingWriteStream.h>\n#define COMPANION_FEATURE_TEXT_TERMINAL 1')
        code = code.replace("  std::deque<uint8_t> bytes;", "  size_t write_capacity=64,write_limit=2;\n  std::deque<uint8_t> bytes;")
        code = code.replace("int availableForWrite() override { return 4096; }", "int availableForWrite() override { return int(write_capacity); }")
        code = code.replace("output.append(reinterpret_cast<const char*>(p),n); return n;",
                            "const size_t count=std::min(n,std::min(write_capacity,write_limit)); output.append(reinterpret_cast<const char*>(p),count); return count;")
        code = code.replace("} input;", "} input;\nmesh::BufferedNonBlockingWriteStream<128> terminal(input);")
        code = code.replace("static Stream& usbTerminalOutput() { return input; }", "static Stream& usbTerminalOutput() { return terminal; }")
        code = code.replace("void discardUsbTerminalOutput() {}", "void discardUsbTerminalOutput() { terminal.discardPending(); }")
        code = code.replace("Stream& usbCompanionPort() { return input; }", "Stream& usbCompanionPort() { return input; }\nStream& usbTerminalPort() { return terminal; }\nbool hasPendingUsbTerminalOutput() { return terminal.queuedByteCount()!=0; }")
        radio = r'''
struct Radio {
  bool receiving=true; uint32_t generation=1; std::string capture="E";
  bool isMorseRxActive() const { return receiving; }
  uint32_t morseCaptureGeneration() const { return generation; }
  size_t morseCaptureLength() const { return capture.size(); }
  size_t readMorseCapture(size_t offset,char* out,size_t cap) const {
    const size_t n=offset<capture.size()?std::min(capture.size()-offset,cap-1):0;
    memcpy(out,capture.data()+std::min(offset,capture.size()),n); out[n]=0; return n;
  }
};
struct Clock { uint32_t getMillis() const { return g_mock_millis; } };
'''
        fields = r'''
  Radio radio; Radio* _radio=&radio; Clock clock; Clock* _ms=&clock;
  Stream* _terminal_output=nullptr; bool _terminal_mode=true;
  bool _terminal_input_editing=false,_terminal_morse_atomic=true;
  bool _terminal_login_pending=false,_terminal_trace_pending=false;
  struct Command { bool pending=false; bool isPending() const { return pending; } } _terminal_command;
  Stream* _morse_terminal_owner=nullptr;
  uint32_t _morse_terminal_generation=0,_morse_terminal_next_at=0;
  uint16_t _morse_terminal_offset=0; uint8_t _morse_terminal_pending_chars=0;
  bool _morse_terminal_was_receiving=false; unsigned stops=0;
  bool hasTerminalOutput() const { return _terminal_output!=nullptr; }
  void serviceMorseTerminal();
@SETTER@
'''.replace("@SETTER@", setter)
        code = code.replace("struct Mesh {", radio + "\nstruct Mesh {" + fields)
        code = code.replace("terminal=true; waiting=!banner;", "terminal=true; waiting=!banner; _terminal_mode=true; _terminal_output=&::terminal; _terminal_morse_atomic=true; _terminal_input_editing=false;")
        code = code.replace("terminal=false; waiting=false;", "terminal=false; waiting=false; _terminal_mode=false; _terminal_output=nullptr; _terminal_morse_atomic=false;")
        code = code.replace("void handleTerminalCommand(char* command) { commands.emplace_back(command); }", r'''
  void handleTerminalCommand(char* command, bool=true,
      size_t (*)(Stream&,const uint8_t*,size_t)=nullptr) {
    commands.emplace_back(command);
    if(!strcmp(command,"morse stop")) { radio.receiving=false; ++stops; }
    usbTerminalOutput().print("  -> OK - Morse stopped\r\n");
  }
''')
        # This lifecycle fixture used raw output as a mock before; transitions
        # now operate on the actual queue, just as the production facade does.
        code = code.replace("static void queueUsbTerminalControlReply(const char* reply) { input.output+=reply; }",
                            "static void queueUsbTerminalControlReply(const char* reply) { terminal.write(reinterpret_cast<const uint8_t*>(reply),strlen(reply)); }")
        code = code.replace("static void drainUsbTerminalOutputBeforeProtocolSwitch() {}",
                            "static void drainUsbTerminalOutputBeforeProtocolSwitch() { for(unsigned i=0;i<1000&&terminal.queuedByteCount();++i) terminal.service(); terminal.discardPending(); }")
        code = code.replace("@FUNCTIONS@", producer + "\n" + functions)
        accessor = extract_braced(usb.CONTEXT, "static SerialMotaSource& serialFolderSource()")
        code = usb.bind_production_input_constants(code.replace("@SOURCE_ACCESSOR@", accessor))
        code += r'''
static void drain() {
  unsigned loops=0;
  while(terminal.queuedByteCount()) { terminal.service(); assert(++loops<1000); }
}
int main() {
  g_mock_millis=100; enterUsbTerminalMode(true); input.output.clear();
  // One whole Morse record is admitted although the hardware accepts only
  // two bytes per write. The existing queue owns its entire unwritten suffix.
  the_mesh.serviceMorseTerminal(); assert(terminal.queuedByteCount()>0);
  const auto prefix=input.output; input.write_capacity=0;
  the_mesh.radio.capture="E SOS";
  input.push("morse st"); syncUsbTerminalInputEditing(); the_mesh.serviceMorseTerminal();
  serviceUsbTerminal(); syncUsbTerminalInputEditing();
  assert(usb_terminal_line_len==8 && !strcmp(usb_terminal_line,"morse st"));
  assert(the_mesh._terminal_input_editing && input.output==prefix);
  input.write_capacity=64; drain();
  const auto typed=input.output;
  for(unsigned i=0;i<10;++i) { g_mock_millis+=250; the_mesh.serviceMorseTerminal(); }
  assert(input.output==typed && the_mesh.commands.empty() && the_mesh._morse_terminal_offset==1);
  // Immediate stop is parsed with a blocked/unread output endpoint. Its reply
  // queues after the previous whole record, never inside it or typed text.
  input.write_capacity=0; input.push("op\r"); syncUsbTerminalInputEditing();
  serviceUsbTerminal(); syncUsbTerminalInputEditing();
  assert(the_mesh.stops==1 && !the_mesh.radio.receiving);
  assert(the_mesh.commands.size()==1 && the_mesh.commands[0]=="morse stop");
  assert(!the_mesh._terminal_input_editing && !usb_terminal_line_len);
  the_mesh.serviceMorseTerminal(); assert(the_mesh._morse_terminal_offset==1);
  input.write_capacity=64; drain();
  assert(input.output=="\r\n[Morse RX] E\r\n> morse stop\r\n  -> OK - Morse stopped\r\n> ");
  the_mesh.serviceMorseTerminal(); drain();
  assert(input.output.find("  -> OK - Morse stopped")<input.output.find("[Morse RX]  SOS"));
  // Pending remote replies and unrelated owner state cannot inject progress.
  the_mesh.radio.receiving=true; the_mesh.radio.capture+=" T";
  the_mesh._terminal_command.pending=true; g_mock_millis+=250;
  const auto before=input.output; the_mesh.serviceMorseTerminal(); assert(input.output==before);
  the_mesh._terminal_command.pending=false;
  Input wrong_owner; the_mesh.setTerminalInputEditing(wrong_owner,true);
  assert(!the_mesh._terminal_input_editing);
  // Raw TCP/HWCDC/UART sessions are intentionally manual-read only.
  the_mesh._terminal_morse_atomic=false; the_mesh.serviceMorseTerminal(); assert(input.output==before);
  the_mesh._terminal_morse_atomic=true;
  // A protocol handoff discards no already-drained record into Binary mode.
  input.push(USB_TERMINAL_STOP_TOKEN); serviceUsbTerminal(); syncUsbTerminalInputEditing();
  assert(!the_mesh.isTerminalMode() && !terminal.queuedByteCount());
  const auto binary_before=input.output; the_mesh.serviceMorseTerminal();
  assert(input.output==binary_before);
}
'''
        with tempfile.TemporaryDirectory(prefix="morse-terminal-input-") as directory:
            temp = Path(directory)
            cpp = temp / "test.cpp"
            cpp.write_text(code, encoding="ascii")
            for sanitize in (False, True):
                with self.subTest(sanitizers=sanitize):
                    binary = temp / f"test-{sanitize}"
                    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"] if sanitize else []
                    built = subprocess.run(["g++", "-std=c++17", *flags, "-I", str(ROOT / "test/mocks"),
                                            "-I", str(ROOT / "src"), str(cpp),
                                            str(ROOT / "src/helpers/ArduinoSerialInterface.cpp"),
                                            str(ROOT / "src/helpers/ota/MotaSourceSerial.cpp"), "-o", str(binary)],
                                           capture_output=True, text=True)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    ran = subprocess.run([str(binary)], capture_output=True, text=True)
                    self.assertEqual(ran.returncode, 0, ran.stderr)
        actual_loop = method(main, "\nvoid loop()")
        self.assertLess(actual_loop.index("syncUsbTerminalInputEditing();"), actual_loop.index("the_mesh.loop();"))
        self.assertLess(actual_loop.index("serviceUsbTerminal();"), actual_loop.rindex("syncUsbTerminalInputEditing();"))


if __name__ == "__main__":
    unittest.main()
