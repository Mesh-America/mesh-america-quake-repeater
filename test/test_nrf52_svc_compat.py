"""Regression for pointer side effects hidden by Nordic's SVC assembly."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "src/helpers/nrf52/SoftDeviceSvcCompat.h"
CORE = Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))
BIN = CORE / "packages/toolchain-gccarmnoneeabi/bin"
PROBE = r'''
#include <stdint.h>
SVCALL(0x80, uint32_t, system_call(uint32_t *value));
__attribute__((used, noinline)) uint32_t read_output(void) {
  uint32_t value = 0;
  system_call(&value);
  return value;
}
__attribute__((used, noinline)) uint32_t write_input(void) {
  uint32_t value = 0x12345678;
  return system_call(&value);
}
'''


class Nrf52SvcCompatTest(unittest.TestCase):
    def test_framework_and_application_receive_the_guard(self):
        script = (ROOT / "scripts/nrf52_lto_toolchain.py").read_text()
        self.assertIn('env.AppendUnique(CCFLAGS=[', script)
        self.assertIn('"-include"', script)
        self.assertIn('SoftDeviceSvcCompat.h', script)
        self.assertIn('pre:scripts/nrf52_lto_toolchain.py',
                      (ROOT / "platformio.ini").read_text())

    def test_lto_preserves_supervisor_input_and_output_memory(self):
        cc = shutil.which("arm-none-eabi-gcc") or str(BIN / "arm-none-eabi-gcc")
        dump = shutil.which("arm-none-eabi-objdump") or str(BIN / "arm-none-eabi-objdump")
        if not Path(cc).is_file() or not Path(dump).is_file():
            if os.environ.get("MESHCORE_REQUIRE_ARM_COMPILER") == "1":
                self.fail("ARM compiler and objdump are required for the LTO regression")
            self.skipTest("ARM compiler required for the LTO regression")
        with tempfile.TemporaryDirectory(prefix="meshcore-svc-lto-") as temp:
            folder = Path(temp)
            probe = folder / "probe.c"
            probe.write_text(PROBE)
            # Reproduce the SDK wrapper's missing IPA and memory protections.
            broken = folder / "broken.h"
            broken.write_text(HEADER.read_text().replace(", noipa", "")
                              .replace(', "memory"', ""))
            assemblies = {}
            for name, header in (("fixed", HEADER), ("broken", broken)):
                elf = folder / (name + ".elf")
                result = subprocess.run([
                    cc, "-DNRF52_PLATFORM", "-include", str(header),
                    "-mcpu=cortex-m4", "-mthumb", "-Os", "-flto",
                    "-fipa-pta", "-fmerge-all-constants", "-nostdlib",
                    "-Wl,-e,read_output", str(probe), "-o", str(elf),
                ], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                assemblies[name] = subprocess.check_output([
                    dump, "-d", "--disassemble=read_output", str(elf),
                ], text=True)
            # The broken wrapper returns a compile-time zero after the SVC;
            # the fixed wrapper reloads the value written by the supervisor.
            self.assertRegex(assemblies["fixed"], r"\bldr\s+r0,\s*\[sp")
            self.assertNotRegex(assemblies["broken"], r"\bldr\s+r0,\s*\[sp")
            self.assertRegex(assemblies["fixed"], r"\bstr\s+r\d+,\s*\[sp")
            self.assertNotRegex(assemblies["broken"], r"\bstr\s+r\d+,\s*\[sp")


if __name__ == "__main__":
    unittest.main()
