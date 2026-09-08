#!/usr/bin/env python3
"""Run the actual shared OtaContext and byte-exact mOTA transfers under sanitizers."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from test_t096_full_memory import method

ROOT = Path(__file__).resolve().parents[1]


class SharedMotaQueueTest(unittest.TestCase):
    def test_context_lifecycle_and_real_transfers_preserve_unread_messages(self):
        with tempfile.TemporaryDirectory(prefix="meshcore-mota-queue-") as temp:
            binary = Path(temp) / "transfer"
            tinf = Path(temp) / "tinf.o"
            control = method((ROOT / "examples/companion_radio/main.cpp").read_text(),
                             "class Nrf52BleMotaSourceControl")
            (Path(temp) / "ble_control_under_test.h").write_text(control + ";\n")
            subprocess.run([
                "cc", "-DENABLE_OTA=1", "-fsanitize=address,undefined", "-g",
                "-c", str(ROOT / "src/helpers/ota/OtaTinf.c"), "-o", str(tinf),
            ], check=True)
            sources = [
                "test/fixtures/shared_mota_queue/test_shared_mota_queue.cpp",
                "src/helpers/ota/OtaContext.cpp", "src/helpers/ota/OtaManager.cpp",
                "src/helpers/ota/OtaProtocol.cpp", "src/helpers/ota/MotaContainer.cpp",
                "src/helpers/ota/MerkleTree.cpp", "src/helpers/ota/OtaDeflate.cpp",
                "src/Utils.cpp",
            ]
            built = subprocess.run([
                "c++", "-std=c++17", "-fsanitize=address,undefined", "-g",
                "-DNRF52_PLATFORM=1", "-DOTA_SEEDER_ONLY=1",
                "-DCOMPANION_RADIO_FULL=1", "-DOTA_SHARED_COMPANION_QUEUE=1",
                "-DENABLE_OTA=1", "-I", str(ROOT / "src"),
                "-I", str(ROOT / "test/mocks"), "-I", temp,
                *[str(ROOT / source) for source in sources], str(tinf),
                "-o", str(binary),
            ], text=True, capture_output=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
