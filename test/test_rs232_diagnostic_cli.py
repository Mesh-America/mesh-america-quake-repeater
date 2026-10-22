"""Compile actual RS232 diagnostic dispatch/forwarders with native fakes."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]


class Rs232DiagnosticCliTests(unittest.TestCase):
    def compile_run(self, source, flags=()):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="rs232-cli-") as directory:
            source_path = Path(directory) / "main.cpp"
            binary = Path(directory) / "check"
            source_path.write_text(source, encoding="ascii")
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                            "-I", str(ROOT / "src"), *flags, str(source_path),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)

    def test_actual_dispatch_strict_local_actions_and_bounded_replies(self):
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="ascii")
        header = (ROOT / "src/helpers/CommonCLI.h").read_text(encoding="ascii")
        body = extract_braced(source, "bool CommonCLI::handleRs232DiagnosticCommand(")
        defaults = "\n".join(extract_braced(header, signature) for signature in (
            "virtual void formatRs232Transport(", "virtual void formatRs232Stats(",
            "virtual bool sendRs232Test(", "virtual bool resetRs232Stats("))
        self.assertIn("if (handleRs232DiagnosticCommand(sender_timestamp, command, reply)) return;", source)
        self.compile_run(r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
static uint32_t now_ms = 0x1234ABCD;
uint32_t millis() { return now_ms; }
struct Callbacks {
  virtual ~Callbacks() = default;
''' + defaults + r'''
};
struct Fake : Callbacks {
  int statuses = 0, stats = 0, sends = 0, resets = 0;
  uint32_t nonce = 0;
  size_t capacity = 0;
  std::string page;
  bool send_result = true, reset_result = true, long_reply = false;
  void fill(char* reply, size_t cap, const char* value) {
    capacity = cap;
    const std::string text = long_reply ? std::string(300, 'x') : value;
    snprintf(reply, cap, "%s", text.c_str());
  }
  void formatRs232Transport(char* r, size_t cap) override {
    ++statuses; fill(r, cap, "status");
  }
  void formatRs232Stats(const char* p, char* r, size_t cap) override {
    ++stats; page = p; fill(r, cap, "stats");
  }
  bool sendRs232Test(uint32_t n) override {
    ++sends; nonce = n; return send_result;
  }
  bool resetRs232Stats() override { ++resets; return reset_result; }
  int count() const { return statuses + stats + sends + resets; }
};
struct CommonCLI {
  Callbacks* _callbacks;
  bool handleRs232DiagnosticCommand(uint32_t, const char*, char*);
};
''' + body + r'''
int main() {
  Fake callbacks;
  CommonCLI cli{&callbacks};
  char reply[160];
  auto command = [&](const char* text, uint32_t sender = 0) {
    memset(reply, 'Z', sizeof(reply));
    const bool handled = cli.handleRs232DiagnosticCommand(sender, text, reply);
    assert(reply[157] == 'Z' && reply[158] == 'Z' && reply[159] == 'Z');
    if (handled) assert(memchr(reply, 0, 157) != nullptr);
    return handled;
  };
  assert(command("get rs232.transport", 77));
  assert(callbacks.statuses == 1 && callbacks.capacity == 157);
  for (const char* page : {"", "rx", "tx", "drops", "test"}) {
    const std::string text = std::string("get rs232.stats") + (*page ? " " : "") + page;
    assert(command(text.c_str(), 77));
    assert(callbacks.page == page && callbacks.capacity == 157);
  }
  callbacks.long_reply = true;
  assert(command("get rs232.transport"));
  assert(strlen(reply) == 156);
  assert(command("get rs232.stats rx"));
  assert(strlen(reply) == 156);
  callbacks.long_reply = false;
  for (const char* text : {
      "get rs232.transport extra", "get rs232.transportx", "get rs232.transport ",
      "get rs232.statsrx", "get rs232.stats x", "get rs232.stats rx junk",
      "get rs232.stats ", "get rs232.stats\trx", "get rs232.stats  rx",
      "rs232", "rs232 testx", "rs232 test ", "rs232 test 1234567",
      "rs232 test 123456789", "rs232 test 0x123456", "rs232 test +1234567",
      "rs232 test 1234567Z", "rs232 test 12345678 ", "rs232 test 12345678 x",
      "rs232 resetstatsx", "rs232 resetstats ", "rs232 resetstats now"}) {
    const int before = callbacks.count();
    assert(command(text));
    assert(strncmp(reply, "Error:", 6) == 0 && callbacks.count() == before);
  }
  for (const char* text : {"rs232test", "rs232x test", "get rs232.enabled", "get rs232.status", "get repeat"}) {
    const int before = callbacks.count();
    assert(!command(text));
    assert(callbacks.count() == before);
  }
  for (uint32_t remote : {1U, UINT32_MAX}) {
    for (const char* text : {"rs232 test", "rs232 test 12345678", "rs232 resetstats"}) {
      const int before = callbacks.count();
      assert(command(text, remote));
      assert(strstr(reply, "local connection") && callbacks.count() == before);
    }
  }
  assert(command("rs232 test"));
  assert(callbacks.sends == 1 && callbacks.nonce == now_ms);
  assert(strcmp(reply, "OK - test queued id=1234ABCD; confirm on peer") == 0);
  assert(command("rs232 test 89abcDEF"));
  assert(callbacks.sends == 2 && callbacks.nonce == 0x89ABCDEF);
  assert(command("rs232 test 00000000"));
  assert(callbacks.sends == 3 && callbacks.nonce == 0);
  callbacks.send_result = false;
  assert(command("rs232 test DEADBEEF"));
  assert(callbacks.sends == 4 && strstr(reply, "not queued"));
  assert(command("rs232 resetstats"));
  assert(callbacks.resets == 1 && strcmp(reply, "OK - RS232 statistics reset") == 0);
  callbacks.reset_result = false;
  assert(command("rs232 resetstats"));
  assert(callbacks.resets == 2 && strstr(reply, "unavailable"));
  Callbacks unsupported;
  cli._callbacks = &unsupported;
  assert(command("get rs232.transport") && strstr(reply, "unavailable"));
  assert(command("get rs232.stats") && strstr(reply, "unavailable"));
  assert(command("rs232 test") && strstr(reply, "not queued"));
  assert(command("rs232 resetstats") && strstr(reply, "unavailable"));
}
''')

    def test_actual_repeater_forwarders_select_uart_and_handle_absent_transport(self):
        repeater = (ROOT / "examples/simple_repeater/MyMesh.h").read_text(encoding="ascii")
        signatures = ("void formatRs232Transport(", "void formatRs232Stats(",
                      "bool sendRs232Test(", "bool resetRs232Stats(")
        forwarders = "\n".join(extract_braced(repeater, signature) for signature in signatures)
        # Room servers own MQTT/ESP-NOW only and retain the explicit unsupported
        # defaults rather than accidentally routing UART diagnostics to MQTT.
        room = (ROOT / "examples/simple_room_server/MyMesh.h").read_text(encoding="ascii")
        for signature in signatures:
            self.assertNotIn(signature, room)
        source = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
struct Base {
  virtual void formatRs232Transport(char*, size_t) {}
  virtual void formatRs232Stats(const char*, char*, size_t) {}
  virtual bool sendRs232Test(uint32_t) { return false; }
  virtual bool resetRs232Stats() { return false; }
};
struct RS232Bridge {
  int calls = 0; uint32_t nonce = 0;
  void formatStatus(char* r, size_t cap) { ++calls; snprintf(r, cap, "status"); }
  void formatStats(const char* page, char* r, size_t cap) {
    ++calls; assert(strcmp(page, "rx") == 0); snprintf(r, cap, "rx");
  }
  bool sendTest(uint32_t n) { ++calls; nonce = n; return true; }
  void resetStats() { ++calls; }
};
struct Role : Base {
  RS232Bridge uart, mqtt_bridge, espnow_bridge;
  RS232Bridge* bridge = &uart;
''' + forwarders + r'''
};
int main() {
  Role role; char reply[160];
  memset(reply, 'Z', sizeof(reply));
  role.formatRs232Transport(reply, 157);
  role.formatRs232Stats("rx", reply, 157);
  assert(role.sendRs232Test(0xABCD));
  assert(role.resetRs232Stats());
  assert(role.uart.calls == 4 && role.uart.nonce == 0xABCD);
  assert(role.mqtt_bridge.calls == 0 && role.espnow_bridge.calls == 0);
  role.bridge = nullptr;
  role.formatRs232Transport(reply, 157);
  assert(strstr(reply, "unavailable"));
  role.formatRs232Stats("rx", reply, 157);
  assert(strstr(reply, "unavailable"));
  assert(!role.sendRs232Test(0xABCD) && !role.resetRs232Stats());
  assert(role.uart.calls == 4);
  assert(reply[157] == 'Z' && reply[158] == 'Z' && reply[159] == 'Z');
}
'''
        for macros in ((), ("WITH_ESPNOW_BRIDGE",), ("WITH_MQTT_BRIDGE",),
                       ("WITH_MQTT_BRIDGE", "WITH_ESPNOW_BRIDGE")):
            with self.subTest(macros=macros):
                self.compile_run(source, ["-DWITH_RS232_BRIDGE=1", *["-D" + m for m in macros]])

    def test_diagnostic_virtuals_are_absent_without_rs232(self):
        header = (ROOT / "src/helpers/CommonCLI.h").read_text(encoding="ascii")
        start = header.index("#if defined(WITH_RS232_BRIDGE)\n  virtual void formatRs232Transport(")
        end = header.index("\n#endif", start) + len("\n#endif")
        block = header[start:end]
        source = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <type_traits>
#include <utility>
struct Callbacks {
''' + block + r'''
};
template <typename T, typename = void> struct HasDiagnostics : std::false_type {};
template <typename T> struct HasDiagnostics<T, std::void_t<
  decltype(std::declval<T>().formatRs232Transport(nullptr, 0)),
  decltype(std::declval<T>().formatRs232Stats(nullptr, nullptr, 0)),
  decltype(std::declval<T>().sendRs232Test(0)),
  decltype(std::declval<T>().resetRs232Stats())>> : std::true_type {};
int main() {
#if defined(WITH_RS232_BRIDGE)
  static_assert(HasDiagnostics<Callbacks>::value);
  Callbacks callbacks; char reply[157];
  callbacks.formatRs232Transport(reply, sizeof(reply));
  assert(reply[0] == 'E');
  assert(!callbacks.sendRs232Test(0) && !callbacks.resetRs232Stats());
#else
  static_assert(!HasDiagnostics<Callbacks>::value);
  static_assert(sizeof(Callbacks) == 1);
#endif
}
'''
        self.compile_run(source)
        self.compile_run(source, ["-DWITH_RS232_BRIDGE=1"])


if __name__ == "__main__":
    unittest.main()
