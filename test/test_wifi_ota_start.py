#!/usr/bin/env python3
"""Exercise the actual browser OTA start/stop methods with fake WiFi and servers."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]


class WiFiOtaStartTest(unittest.TestCase):
    def compile_and_run(self, source, *flags):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "A host C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="wifi-ota-start-") as directory:
            path = Path(directory)
            (path / "test.cpp").write_text(source, encoding="ascii")
            sanitizer = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                          "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
            result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra",
                *sanitizer, *flags, "-I", str(ROOT / "src"), str(path / "test.cpp"), "-o", str(path / "test")],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(path / "test")], capture_output=True,
                                    text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_network_instructions_and_switching_on_all_esp32_uploaders(self):
        source = (ROOT / "src/helpers/ESP32Board.cpp").read_text()
        lightweight, other = source.split("#elif defined(ADMIN_PASSWORD) && !defined(DISABLE_WIFI_OTA)", 1)
        fixture = (ROOT / "test/fixtures/wifi_ota_start.cpp").read_text()
        for name, implementation, flags in (
            ("lightweight infrastructure", lightweight, ["-DLIGHTWEIGHT_WIFI_OTA=1"]),
            ("lightweight companion", lightweight, ["-DLIGHTWEIGHT_WIFI_OTA=1", "-DCOMPANION_RADIO_FULL=1"]),
            ("AsyncElegantOTA infrastructure", other, []),
        ):
            with self.subTest(uploader=name):
                methods = "\n".join(extract_braced(implementation, signature) for signature in (
                    "bool ESP32Board::startOTAUpdate(", "bool ESP32Board::stopOTAUpdate("))
                self.compile_and_run(fixture.replace("@METHODS@", methods), *flags)

    def test_common_cli_preserves_actionable_ota_errors(self):
        cli = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        start = cli.index('    } else if (memcmp(command, "start ota", 9)')
        end = cli.index('    } else if (memcmp(command, "clock", 5)', start)
        fixture = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
struct Board {
  const char* error = "ERR: OTA WiFi failed";
  bool startOTAUpdate(const char*, char* reply, bool) {
    strcpy(reply, error); return false;
  }
  bool stopOTAUpdate(char* reply) { strcpy(reply, error); return false; }
} board;
struct Prefs { const char* node_name = "test"; } prefs;
struct CLI {
  Board* _board = &board;
  Prefs* _prefs = &prefs;
  void run(const char* command, char* reply) {
    if (false) {
@CLI@
    }
  }
};
int main() {
  CLI cli;
  char reply[160] = {};
  for (const char* command : {"start ota", "start ota ap", "stop ota"}) {
    cli.run(command, reply);
    assert(strcmp(reply, "ERR: OTA WiFi failed") == 0);
    board.error = "ERR: OTA server failed";
    cli.run(command, reply);
    assert(strcmp(reply, "ERR: OTA server failed") == 0);
    board.error = "";
    cli.run(command, reply);
    assert(strcmp(reply, "Error") == 0);
    board.error = "ERR: OTA WiFi failed";
  }
}
'''
        self.compile_and_run('#include <initializer_list>\n' + fixture.replace("@CLI@", cli[start:end]))

    def test_common_cli_stops_webconfig_and_reports_the_handoff(self):
        cli = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        start = cli.index('    } else if (memcmp(command, "start ota", 9)')
        end = cli.index('    } else if (memcmp(command, "clock", 5)', start)
        fixture = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
struct Callbacks {
  bool active = true, allow_stop = true;
  int stops = 0, bridge_stops = 0, bridge_starts = 0;
  bool isWebConfigActive() const { return active; }
  bool stopWebConfigForOTA(char* reply) {
    ++stops;
    if (!allow_stop) { strcpy(reply, "ERR: handoff failed"); return false; }
    active = false; strcpy(reply, "WebConfig stopped"); return true;
  }
  void setBridgeState(bool enabled) { if (enabled) ++bridge_starts; else ++bridge_stops; }
} callbacks;
struct Board {
  bool allow_start = true;
  int starts = 0;
  bool startOTAUpdate(const char*, char* reply, bool) {
    assert(!callbacks.active); ++starts;
    strcpy(reply, allow_start ? "Started: http://10.20.30.40/update - Use same WiFi/LAN"
                             : "ERR: OTA WiFi failed");
    return allow_start;
  }
  bool stopOTAUpdate(char*) { return true; }
} board;
struct Prefs {
  const char* node_name = "test";
  bool bridge_enabled = false, espnow_bridge_enabled = false;
} prefs;
struct CLI {
  Board* _board = &board;
  Prefs* _prefs = &prefs;
  Callbacks* _callbacks = &callbacks;
  void run(const char* command, char* reply) {
    if (false) {
@CLI@
    }
  }
};
int main() {
  CLI cli;
  struct { char text[160] = {}; unsigned guard = 123; } reply;
  cli.run("start ota invalid", reply.text);
  assert(strstr(reply.text, "usage") && callbacks.stops == 0 && board.starts == 0);
  callbacks.allow_stop = false;
  cli.run("start ota", reply.text);
  assert(strcmp(reply.text, "ERR: handoff failed") == 0 && board.starts == 0);
  callbacks.allow_stop = true;
  cli.run("start ota", reply.text);
  assert(strstr(reply.text, "http://10.20.30.40/update") && strstr(reply.text, "; WebConfig stopped"));
  assert(callbacks.stops == 2 && board.starts == 1 && callbacks.bridge_stops == 1);
  cli.run("start ota ap", reply.text);
  assert(!strstr(reply.text, "WebConfig stopped") && callbacks.stops == 2 && board.starts == 2);
  callbacks.active = true;
  board.allow_start = false;
  cli.run("start ota", reply.text);
  assert(strcmp(reply.text, "ERR: OTA WiFi failed; WebConfig stopped") == 0);
  assert(callbacks.stops == 3 && board.starts == 3 && callbacks.bridge_stops == 2);
  cli.run("stop ota", reply.text);
  assert(callbacks.bridge_starts == 0); // Do not enable disabled bridges.
  prefs.espnow_bridge_enabled = true;
  cli.run("stop ota", reply.text);
  assert(callbacks.bridge_starts == 1); // Restore ESP-NOW even with MQTT off.
  assert(reply.guard == 123);
}
'''
        self.compile_and_run(fixture.replace("@CLI@", cli[start:end]),
                             "-DESP_PLATFORM=1", "-DADMIN_PASSWORD=1",
                             "-DWITH_MQTT_BRIDGE=1", "-DLIGHTWEIGHT_WIFI_OTA=1",
                             "-DWITH_ESPNOW_BRIDGE=1")

    def test_webconfig_teardown_cannot_turn_ota_wifi_off(self):
        source = (ROOT / "src/helpers/esp32/WebConfigServer.cpp").read_text()
        methods = "\n".join(extract_braced(source, signature) for signature in (
            "void WebConfigServer::requestStop(", "bool WebConfigServer::stopForOTA(",
            "void WebConfigServer::finalizeTeardown("))
        fixture = (ROOT / "test/fixtures/webconfig_ota_handoff.cpp").read_text()
        self.compile_and_run(fixture.replace("@METHODS@", methods))

    def test_full_companion_cli_reports_webconfig_stop_and_hardware_errors(self):
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        command = extract_braced(source, 'if (strcmp(command, "start ota") == 0')
        fixture = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
struct WebConfig {
  bool active = true, allowed = true;
  bool stopForOTA(char* reply) {
    if (!allowed) { strcpy(reply, "ERR: handoff failed"); return false; }
    active = false; return true;
  }
} portal;
struct Board {
  bool allowed = true;
  int starts = 0;
  bool startOTAUpdate(const char*, char* reply, bool) {
    assert(!portal.active); ++starts;
    strcpy(reply, allowed ? "Started: http://192.168.4.1:8080/update - Join WiFi MeshCore-OTA"
                          : "ERR: this partition layout requires a USB firmware update");
    return allowed;
  }
} board;
struct Mesh {
  struct { const char* node_name = "test"; } _prefs;
  WebConfig* _webconfig = &portal;
  bool isWebConfigActiveOrStopping() { return portal.active; }
  bool run(const char* command, char* reply, size_t reply_size) {
    @COMMAND@
    return false;
  }
};
int main() {
  Mesh mesh;
  char reply[160] = {};
  portal.allowed = false;
  assert(mesh.run("start ota", reply, sizeof(reply)));
  assert(strcmp(reply, "ERR: handoff failed") == 0 && board.starts == 0);
  portal.allowed = true;
  assert(mesh.run("start ota", reply, sizeof(reply)));
  assert(strstr(reply, ":8080/update") && strstr(reply, "; WebConfig stopped"));
  assert(board.starts == 1);
  portal.active = true;
  board.allowed = false;
  assert(mesh.run("start ota ap", reply, sizeof(reply)));
  assert(strstr(reply, "partition layout") && strstr(reply, "; WebConfig stopped"));
  struct { char text[20]; unsigned guard = 42; } short_reply;
  assert(mesh.run("start ota", short_reply.text, sizeof(short_reply.text)));
  assert(short_reply.guard == 42 && short_reply.text[19] == 0);
}
'''
        self.compile_and_run(fixture.replace("@COMMAND@", command), "-DWITH_WEBCONFIG=1")

    def test_lightweight_stop_keeps_slow_client_state_until_task_exits(self):
        source = (ROOT / "src/helpers/ESP32Board.cpp").read_text()
        implementation = source[source.index("class LightweightOTAServer {"):]
        method = extract_braced(implementation, "bool end()")
        fixture = r'''
#include <cassert>
#include <cstdint>
static unsigned delays = 0;
static void delay(unsigned value) { assert(value == 10); ++delays; }
struct Server { void stop() {} };
struct Updater {
  bool running = true;
  Server server;
  void* task = reinterpret_cast<void*>(1);
  void* board = reinterpret_cast<void*>(2);
  @END@
};
int main() {
  Updater updater;
  assert(!updater.end());
  assert(!updater.running && updater.task && updater.board && delays == 100);
  updater.task = nullptr; // Slow network write has now returned and task exited.
  assert(updater.end() && !updater.board && delays == 100);
}
'''
        self.compile_and_run(fixture.replace("@END@", method))


if __name__ == "__main__":
    unittest.main()
