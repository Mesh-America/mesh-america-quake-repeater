"""Execute the production profile sleep handoff with elapsed and wrapping clocks."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Esp32ProfileIdleSleepTest(unittest.TestCase):
    def test_absolute_role_and_radio_deadlines_survive_preemption(self):
        source = r'''
#include <cassert>
#include <cstdint>
#include <helpers/esp32/ProfileIdleSleep.h>
static uint64_t now_us = 0;
int64_t esp_timer_get_time() { return static_cast<int64_t>(now_us); }
struct Mesh {
  bool ready = true;
  uint32_t budget_ms = 10, query_cost_us = 0;
  unsigned reads = 0;
  bool getDualRadioIdleDelay(uint32_t& out) {
    ++reads;
    out = budget_ms;
    now_us += query_cost_us;
    return ready;
  }
} mesh_node;
struct Board {
  unsigned calls = 0;
  uint32_t deadline = 0;
  void sleepUntilMicroseconds(uint32_t value) { ++calls; deadline = value; }
} board;
int main() {
  for (uint64_t start : {100000ULL, 0xfffffc00ULL, 0x1fffffc00ULL}) {
    now_us = start;
    mesh_node = {};
    board = {};
    assert(mesh::esp32::tryProfileIdleSleep(mesh_node, board, uint32_t(start), 30));
    assert(board.calls == 1 && board.deadline == uint32_t(start + 10000));

    // A role deadline calculated before other loop work is never restarted.
    now_us = start + 4000;
    assert(mesh::esp32::tryProfileIdleSleep(mesh_node, board, uint32_t(start), 7));
    assert(board.deadline == uint32_t(start + 7000));
    now_us = start + 5001;
    const unsigned before = board.calls;
    assert(!mesh::esp32::tryProfileIdleSleep(mesh_node, board, uint32_t(start), 7));
    assert(board.calls == before);
    now_us = start + 8000;
    assert(!mesh::esp32::tryProfileIdleSleep(mesh_node, board, uint32_t(start), 7));

    // An IRQ/task delay in the scanner query reduces the board's remaining
    // time instead of moving the absolute deadline forward by that delay.
    now_us = start;
    mesh_node.query_cost_us = 6000;
    assert(mesh::esp32::tryProfileIdleSleep(mesh_node, board, uint32_t(start), 30));
    assert(now_us == start + 6000 && board.deadline == uint32_t(start + 10000));
    mesh_node.query_cost_us = 0;
    mesh_node.budget_ms = 2;
    now_us = start;
    assert(mesh::esp32::tryProfileIdleSleep(mesh_node, board, uint32_t(start), 30));
    assert(board.deadline == uint32_t(start + 2000));
  }
  now_us = 100000;
  for (uint32_t budget : {0U, 1U, 11U, 0xffffffffU}) {
    mesh_node = {};
    mesh_node.budget_ms = budget;
    const unsigned before = board.calls;
    assert(!mesh::esp32::tryProfileIdleSleep(mesh_node, board, 100000, 30));
    assert(board.calls == before);
  }
  mesh_node = {};
  mesh_node.ready = false;
  assert(!mesh::esp32::tryProfileIdleSleep(mesh_node, board, 100000, 30));
  mesh_node = {};
  const unsigned reads = mesh_node.reads;
  assert(!mesh::esp32::tryProfileIdleSleep(mesh_node, board, 100000, 0));
  assert(!mesh::esp32::tryProfileIdleSleep(mesh_node, board, 100000, 0xffffffffU));
  assert(mesh_node.reads == reads);
}
'''
        with tempfile.TemporaryDirectory(prefix="mesh-esp32-profile-handoff-") as directory:
            path = Path(directory)
            (path / "esp_timer.h").write_text("#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time();\n")
            (path / "test.cpp").write_text("#include <initializer_list>\n" + source)
            built = subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                    "-I", str(path), "-I", str(ROOT / "src"), str(path / "test.cpp"),
                                    "-o", str(path / "test")], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(path / "test")], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == "__main__":
    unittest.main()
