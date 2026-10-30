#!/usr/bin/env python3
"""Exercise C3's full queue while its explicit OTA work borrows cold storage."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def method(text, signature):
    start = text.index(signature)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class SharedCompanionOtaCapacityTest(unittest.TestCase):
    def compile(self, text, *, run=False):
        with tempfile.TemporaryDirectory(prefix="meshcore-shared-c3-") as temp:
            binary = Path(temp) / "queue"
            command = ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                       "-I", str(ROOT / "src"), "-x", "c++", "-",
                       "-o", str(binary)]
            if run:
                command[1:1] = ["-fsanitize=address,undefined", "-g"]
            result = subprocess.run(command, input=text, text=True,
                                    capture_output=True)
            if run:
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(binary)], text=True,
                                        capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            return result

    def test_224_normal_slots_and_128_retained_slots_preserve_fifo_and_ownership(self):
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        declaration = (ROOT / "examples/companion_radio/MyMesh.h").read_text()
        retained = re.search(
            r"static constexpr unsigned OTA_RETAINED_OFFLINE_FRAMES = (\d+);",
            declaration)[1]
        methods = "\n".join(method(source, signature) for signature in (
            "mesh::ota::OtaContext* MyMesh::acquireOfflineQueueForOta(void* owner)",
            "uint16_t MyMesh::drainOfflineQueueForOta(void* owner)",
            "void MyMesh::releaseOfflineQueueFromOta(void* owner)",
        ))
        harness = r'''
#include <helpers/BorrowableFrameBuffer.h>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <deque>
constexpr unsigned MAX_FRAME_SIZE = 176;
namespace mesh { namespace ota {
struct OtaContext {
  static unsigned live, constructions, destructions;
  uint8_t bytes[11284]; // source-only ESP32 linked context, not a RAM budget
  OtaContext() {
    ++live; ++constructions;
    memset(bytes, 0xA5, sizeof bytes);
  }
  ~OtaContext() {
    --live; ++destructions;
    memset(bytes, 0x5A, sizeof bytes);
  }
};
unsigned OtaContext::live = 0, OtaContext::constructions = 0,
         OtaContext::destructions = 0;
} }
struct MyMesh {
  struct Frame { uint8_t len; uint8_t buf[MAX_FRAME_SIZE]; };
  static constexpr unsigned OTA_RETAINED_OFFLINE_FRAMES = @RETAINED@;
  mesh::BorrowableFrameBuffer<Frame, 224, OTA_RETAINED_OFFLINE_FRAMES,
                             mesh::ota::OtaContext> offline_queue;
  int offline_queue_len = 0, offline_queue_head = 0;
  unsigned next = 0, notifications = 0;
  std::deque<unsigned> expected;
  static mesh::ota::OtaContext* acquireOfflineQueueForOta(void* owner);
  static uint16_t drainOfflineQueueForOta(void* owner);
  static void releaseOfflineQueueFromOta(void* owner);
  void add() {
    assert(offline_queue_len < int(offline_queue.capacity()));
    Frame& frame = offline_queue.at(
        (offline_queue_head + offline_queue_len) % offline_queue.capacity());
    frame.len = sizeof frame.buf;
    memset(frame.buf, next % 251, sizeof frame.buf);
    memcpy(frame.buf, &next, sizeof next);
    expected.push_back(next++);
    ++offline_queue_len;
  }
  int getFromOfflineQueue(uint8_t* bytes) {
    if (!offline_queue_len) return 0;
    Frame& frame = offline_queue.at(offline_queue_head);
    unsigned sequence;
    memcpy(&sequence, frame.buf, sizeof sequence);
    assert(frame.len == sizeof frame.buf && sequence == expected.front());
    for (unsigned i = sizeof sequence; i < sizeof frame.buf; ++i)
      assert(frame.buf[i] == sequence % 251);
    memcpy(bytes, frame.buf, frame.len);
    expected.pop_front();
    --offline_queue_len;
    offline_queue_head = offline_queue_len
        ? (offline_queue_head + 1) % offline_queue.capacity() : 0;
    ++notifications;
    return frame.len;
  }
  void pop() { uint8_t bytes[MAX_FRAME_SIZE]; assert(getFromOfflineQueue(bytes)); }
};
@METHODS@
int main() {
  using mesh::ota::OtaContext;
  MyMesh mesh;
  for (unsigned head = 0; head < 224; ++head) {
    while (mesh.offline_queue_len < 224) mesh.add();
    // Visit every wrapped head with a full 224-frame normal queue.
    for (unsigned i = 0; i < head; ++i) { mesh.pop(); mesh.add(); }
    int original_head = mesh.offline_queue_head;
    unsigned constructed = OtaContext::constructions;
    assert(!MyMesh::acquireOfflineQueueForOta(&mesh));
    assert(mesh.offline_queue_len == 224);
    assert(mesh.offline_queue_head == original_head);
    assert(OtaContext::constructions == constructed && OtaContext::live == 0);
    // Only the explicit drain consumes frames, preserving the newest 128.
    unsigned notified = mesh.notifications;
    assert(MyMesh::drainOfflineQueueForOta(&mesh) == 96);
    assert(mesh.notifications == notified + 96 && mesh.offline_queue_len == 128);
    assert(MyMesh::drainOfflineQueueForOta(&mesh) == 0);
    OtaContext* owner = MyMesh::acquireOfflineQueueForOta(&mesh);
    assert(owner && OtaContext::live == 1 && mesh.offline_queue.capacity() == 128);
    assert(OtaContext::constructions == constructed + 1);
    assert(MyMesh::acquireOfflineQueueForOta(&mesh) == owner);
    assert(OtaContext::constructions == constructed + 1);
    memset(owner->bytes, 0xCC, sizeof owner->bytes);
    for (unsigned i = 0; i < head % 128; ++i) { mesh.pop(); mesh.add(); }
    MyMesh::releaseOfflineQueueFromOta(&mesh);
    assert(OtaContext::live == 0 && mesh.offline_queue.capacity() == 224);
    assert(OtaContext::constructions == OtaContext::destructions);
    MyMesh::releaseOfflineQueueFromOta(&mesh); // idle release cannot destroy twice
    while (mesh.offline_queue_len < 224) mesh.add();
    while (mesh.offline_queue_len) mesh.pop();
    assert(mesh.expected.empty());
  }
}
'''.replace("@RETAINED@", retained).replace("@METHODS@", methods)
        self.compile(harness, run=True)

    def test_insufficient_workspace_or_no_retained_region_cannot_compile(self):
        harness = r'''
#include <helpers/BorrowableFrameBuffer.h>
#include <cstdint>
struct Frame { uint8_t len; uint8_t bytes[176]; };
struct Workspace { uint8_t bytes[@SIZE@]; };
mesh::BorrowableFrameBuffer<Frame, @CAPACITY@, 128, Workspace> queue;
int main() { return queue.capacity() == @CAPACITY@ ? 0 : 1; }
'''
        # Exact region bounds and the existing 256/128 geometry remain valid.
        for capacity, size, accepted in ((224, 96 * 177, True),
                                         (224, 96 * 177 + 1, False),
                                         (256, 19624, True),
                                         (128, 1, False)):
            with self.subTest(capacity=capacity, size=size):
                result = self.compile(harness.replace("@CAPACITY@", str(capacity))
                                      .replace("@SIZE@", str(size)))
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                if not accepted:
                    self.assertIn("static assertion failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
