#!/usr/bin/env python3
"""Execute the production discovery handler against idle and active tags."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
SANITIZERS = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])

HARNESS = r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#define MESH_DEBUG_PRINTLN(...) ((void)0)
#define PAYLOAD_TYPE_RESPONSE 1
#define MAX_PATH_SIZE 64
#define MAX_FRAME_SIZE 176
@CODES@
struct ContactInfo { struct { uint8_t pub_key[32] = {1, 2, 3, 4, 5, 6}; } id; };
struct BaseSerialInterface {};
struct Clock { uint32_t now = 100; uint32_t getMillis() const { return now; } };
struct SerialBoundary {
  bool available = true;
  unsigned writes = 0;
  BaseSerialInterface* written_route = nullptr;
  std::vector<uint8_t> written;
  bool isReplyRouteAvailable(BaseSerialInterface* route) const {
    return available && route != nullptr;
  }
  size_t writeFrameToRoute(BaseSerialInterface* route, const uint8_t* frame, size_t len) {
    ++writes; written_route = route; written.assign(frame, frame + len); return len;
  }
};
namespace mesh { struct Packet {
  static bool isValidPathLen(uint8_t);
  static size_t writePath(uint8_t*, const uint8_t*, uint8_t);
}; }
struct BaseChatMesh {
  unsigned base_path_calls = 0;
  bool onContactPathRecv(ContactInfo&, uint8_t*, uint8_t, uint8_t*, uint8_t,
                         uint8_t, uint8_t*, uint8_t) {
    ++base_path_calls;
    return true;
  }
};
struct MyMesh : BaseChatMesh {
  uint32_t pending_login = 0, pending_status = 0, pending_telemetry = 0;
  uint32_t pending_discovery = 0, pending_req = 0;
  BaseSerialInterface* pending_serial_reply_route = nullptr;
  unsigned long pending_serial_reply_deadline = 0;
  SerialBoundary serial;
  SerialBoundary* _serial = &serial;
  Clock clock;
  Clock* _ms = &clock;
  uint8_t out_frame[MAX_FRAME_SIZE] = {};
  bool millisHasNowPassed(unsigned long) const;
  size_t writePendingSerialFrame(const uint8_t*, size_t);
  void clearPendingReqs();
  void servicePendingSerialReply();
  bool onContactPathRecv(ContactInfo&, uint8_t*, uint8_t, uint8_t*, uint8_t,
                         uint8_t, uint8_t*, uint8_t);
};
@METHODS@

static bool response(MyMesh& mesh, uint32_t tag) {
  ContactInfo contact;
  uint8_t in_path[] = {0x21, 0x22}, out_path[] = {0x31}, extra[5] = {};
  memcpy(extra, &tag, sizeof(tag));
  return mesh.onContactPathRecv(contact, in_path, 2, out_path, 1,
                                PAYLOAD_TYPE_RESPONSE, extra, sizeof(extra));
}

int main() {
  BaseSerialInterface original_route, newer_route;
  unsigned checks = 0;
  // Radio and transport boundaries are mocks; every correlation decision,
  // output envelope, expiry, and retirement below executes production code.
  for (unsigned kind = 0; kind != 4; ++kind) {
    MyMesh mesh;
    uint32_t* pending[] = {&mesh.pending_login, &mesh.pending_status,
                          &mesh.pending_telemetry, &mesh.pending_req};
    *pending[kind] = 0x11223344;
    mesh.pending_serial_reply_route = &original_route;
    mesh.pending_serial_reply_deadline = 900;
    memset(mesh.out_frame, 0x5a, sizeof(mesh.out_frame));
    assert(response(mesh, 0));
    assert(*pending[kind] == 0x11223344);
    assert(mesh.pending_discovery == 0);
    assert(mesh.pending_serial_reply_route == &original_route);
    assert(mesh.pending_serial_reply_deadline == 900);
    assert(mesh.base_path_calls == 1 && mesh.serial.writes == 0);
    for (uint8_t byte : mesh.out_frame) assert(byte == 0x5a);
    ++checks;
  }
  {
    MyMesh mesh;
    mesh.pending_discovery = 17;
    mesh.pending_serial_reply_route = &original_route;
    mesh.pending_serial_reply_deadline = 900;
    assert(!response(mesh, 17));
    assert(mesh.base_path_calls == 0 && mesh.serial.writes == 1);
    assert(mesh.serial.written_route == &original_route);
    const std::vector<uint8_t> expected = {
        PUSH_CODE_PATH_DISCOVERY_RESPONSE, 0, 1, 2, 3, 4, 5, 6,
        1, 0x31, 2, 0x21, 0x22};
    assert(mesh.serial.written == expected);
    assert(mesh.pending_discovery == 0 && mesh.pending_serial_reply_route == nullptr);
    assert(mesh.pending_serial_reply_deadline == 0);
    ++checks;
  }
  {
    MyMesh mesh;
    mesh.pending_discovery = 17;
    mesh.pending_serial_reply_route = &original_route;
    mesh.pending_serial_reply_deadline = 900;
    assert(response(mesh, 18));
    assert(mesh.pending_discovery == 17 && mesh.base_path_calls == 1);
    assert(mesh.pending_serial_reply_route == &original_route && mesh.serial.writes == 0);
    ++checks;
  }
  for (uint32_t now : {100U, 101U}) {
    MyMesh mesh;
    mesh.pending_discovery = 17;
    mesh.pending_serial_reply_route = &original_route;
    mesh.pending_serial_reply_deadline = 100;
    mesh.clock.now = now;
    mesh.servicePendingSerialReply();
    assert(mesh.pending_discovery == 0 && mesh.pending_serial_reply_route == nullptr);
    mesh.pending_status = 23;
    mesh.pending_serial_reply_route = &newer_route;
    mesh.pending_serial_reply_deadline = 500;
    assert(response(mesh, 0));
    assert(mesh.pending_status == 23 && mesh.base_path_calls == 1);
    assert(mesh.pending_serial_reply_route == &newer_route);
    assert(mesh.pending_serial_reply_deadline == 500 && mesh.serial.writes == 0);
    ++checks;
  }
  assert(checks == 8);
  std::printf("PASS: %u production discovery correlation checks\n", checks);
}
"""


class CompanionDiscoveryCorrelationTests(unittest.TestCase):
    def test_actual_handler_preserves_unrelated_pending_requests(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        packet = (ROOT / "src/Packet.cpp").read_text()
        dispatcher = (ROOT / "src/Dispatcher.cpp").read_text()
        methods = "\n".join(extract_braced(source, signature) for signature in (
            "size_t MyMesh::writePendingSerialFrame(", "void MyMesh::clearPendingReqs(",
            "void MyMesh::servicePendingSerialReply(", "bool MyMesh::onContactPathRecv(",
        ))
        methods += "\n" + extract_braced(
            dispatcher, "bool Dispatcher::millisHasNowPassed(").replace("Dispatcher::", "MyMesh::")
        methods += "\nnamespace mesh {\n" + "\n".join(
            extract_braced(packet, signature) for signature in (
                "bool Packet::isValidPathLen(", "size_t Packet::writePath(",
            )) + "\n}\n"
        code = re.search(r"^#define PUSH_CODE_PATH_DISCOVERY_RESPONSE\s+\S+", source, re.MULTILINE)
        self.assertIsNotNone(code)
        generated = HARNESS.replace("@CODES@", code.group()).replace("@METHODS@", methods)
        with tempfile.TemporaryDirectory(prefix="meshcore-discovery-correlation-") as directory:
            work = Path(directory)
            cpp = work / "discovery.cpp"
            cpp.write_text(generated, encoding="ascii")
            binary = work / "discovery.exe"
            compiled = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *SANITIZERS,
                str(cpp), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("PASS: 8 production discovery correlation checks", checked.stdout)


if __name__ == "__main__":
    unittest.main()
