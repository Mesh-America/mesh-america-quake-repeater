#!/usr/bin/env python3
"""Execute the pure native USB host-loss sleep policy without Arduino/USB."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <helpers/UsbHostSleepPolicy.h>
#include <iostream>
#include <stdexcept>

static void require(bool condition, const char* why) {
  if (!condition) throw std::runtime_error(why);
}

int main() {
  try {
    constexpr uint32_t grace = 120000U;
    for (uint32_t now : {0U, 1U, 120001U, UINT32_MAX}) {
      mesh::UsbHostSleepPolicy cold;
      cold.observe(false, now);
      require(!cold.shouldKeepAwake(now, grace), "never-seen host armed grace");
    }

    for (uint32_t start : {0U, 100U, UINT32_MAX - 60000U}) {
      mesh::UsbHostSleepPolicy policy;
      policy.observe(true, start);
      require(policy.shouldKeepAwake(start + grace + 1U, grace),
              "present host was allowed to sleep");
      policy.observe(false, start + 6U);
      require(policy.shouldKeepAwake(start + 6U, grace), "five-ms SOF loss lost grace");
      // Negative observations are not permission to renew the loss deadline.
      policy.observe(false, start + grace - 1U);
      require(policy.shouldKeepAwake(start + grace - 1U, grace), "grace ended early");
      policy.observe(false, start + grace);
      require(!policy.shouldKeepAwake(start + grace, grace), "grace never expired");
      policy.observe(false, start + 1U);
      require(!policy.shouldKeepAwake(start + 1U, grace), "old host revived after wrap");

      // A new actual host cancels absence and arms a fresh bounded deadline.
      const uint32_t returned_at = start + grace + 10U;
      policy.observe(true, returned_at);
      require(policy.shouldKeepAwake(returned_at, grace), "reconnect remained asleep");
      policy.observe(true, returned_at + 500U);
      policy.observe(false, returned_at + 506U);
      require(policy.shouldKeepAwake(returned_at + 500U + grace - 1U, grace),
              "last positive observation did not refresh grace");
      require(!policy.shouldKeepAwake(returned_at + 500U + grace, grace),
              "renewed grace was unbounded");
    }

    mesh::UsbHostSleepPolicy configurable;
    configurable.observe(true, 200U);
    configurable.observe(false, 201U);
    require(configurable.shouldKeepAwake(1199U, 1000U), "custom grace ended early");
    require(!configurable.shouldKeepAwake(1200U, 1000U), "custom grace never expired");
    configurable.observe(true, 3000U);
    require(configurable.shouldKeepAwake(3000U, 0U), "zero grace hid a live host");
    configurable.observe(false, 3000U);
    require(!configurable.shouldKeepAwake(3000U, 0U), "zero grace did not disable hold");
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
'''


class UsbHostSleepPolicyTest(unittest.TestCase):
    def test_host_loss_reconnect_expiry_and_clock_rollover(self):
        compiler = os.environ.get("CXX", "c++")
        self.assertIsNotNone(shutil.which(compiler), "a C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-usb-host-policy-") as temp:
            cpp = Path(temp) / "policy.cpp"
            binary = Path(temp) / "policy"
            cpp.write_text(HARNESS)
            compiled = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT / "src"), str(cpp), "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
