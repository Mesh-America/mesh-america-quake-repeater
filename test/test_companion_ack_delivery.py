#!/usr/bin/env python3
"""Run production ACK bookkeeping against actual UART/TCP bounded queues."""

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
FIXTURE = ROOT / "test/fixtures/companion_ack_delivery/test.cpp"
SANITIZERS = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])


class CompanionAckDeliveryTests(unittest.TestCase):
    def test_actual_ack_routes_and_backpressure(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        header = (ROOT / "examples/companion_radio/MyMesh.h").read_text()
        dispatcher = (ROOT / "src/Dispatcher.cpp").read_text()
        native = (ROOT / "test/test_serial_mode_switch/test_serial_mode_switch.cpp").read_text()
        functions = "\n".join(extract_braced(source, signature) for signature in (
            "void MyMesh::clearExpectedAck(", "void MyMesh::expireExpectedAcks(",
            "MyMesh::AckTableEntry* MyMesh::findPendingTextMessage(",
            "bool MyMesh::processAck(",
            "void MyMesh::cancelSerialOperationsForRoute(",
            "bool MyMesh::hasFiniteDelayedReplyForRoute(",
        ))
        functions += "\n" + "\n".join(
            extract_braced(dispatcher, signature).replace("Dispatcher::", "MyMesh::")
            for signature in ("bool Dispatcher::millisHasNowPassed(",
                              "unsigned long Dispatcher::futureMillis(")
        )
        loop = extract_braced(source, "if (has_next_ack_expiry\n")
        functions += "\nvoid MyMesh::service() {\n" + loop + "\n}\n"
        # Execute the original successful-send slot initializer, not a copy of
        # its predicates. Radio composition itself is outside this queue test.
        sent = source[source.index("// The newest successfully-queued submission wins."):]
        initialize = extract_braced(sent, "if (expected_ack) {")
        functions += "\nvoid MyMesh::remember(uint32_t expected_ack, uint32_t msg_timestamp,\n"
        functions += "    ContactInfo* recipient, const uint8_t* text_fingerprint,\n"
        functions += "    const uint8_t* packet_retry_key, AckTableEntry* replacement_entry) {\n"
        functions += "  uint32_t est_timeout = 5000, one_key_delay = 0;\n" + initialize
        functions += "\n  expireExpectedAcks();\n}\n"
        constants = "\n".join(re.findall(
            r"^#define (?:EXPECTED_ACK_[A-Z_]+|PUSH_CODE_SEND_CONFIRMED)\s+.+$",
            source, re.MULTILINE))
        constants += "\n#define EXPECTED_ACK_TABLE_SIZE 8\n#define MAX_HASH_SIZE 8\n"
        with tempfile.TemporaryDirectory(prefix="meshcore-ack-delivery-") as directory:
            work = Path(directory)
            (work / "production_constants.inc").write_text(constants, encoding="ascii")
            (work / "production_stream.inc").write_text(
                extract_braced(native, "class BufferStream") + ";\n", encoding="ascii")
            (work / "production_entry.inc").write_text(
                extract_braced(header, "struct AckTableEntry") + ";\n", encoding="ascii")
            (work / "production_ack.inc").write_text(functions, encoding="ascii")
            for terminal, one_key in ((0, 0), (1, 0), (0, 1), (1, 1)):
                with self.subTest(terminal=terminal, one_key=one_key):
                    binary = work / f"ack-{terminal}-{one_key}.exe"
                    compiled = subprocess.run([
                        compiler, "-std=c++17", "-Werror", *SANITIZERS,
                        f"-DCOMPANION_FEATURE_TEXT_TERMINAL={terminal}",
                        f"-DMESH_ENABLE_ONE_KEY_DM={one_key}",
                        f"-I{work}", f"-I{ROOT / 'test/mocks'}",
                        f"-I{ROOT / 'test/fixtures/serial_wifi_sessions/mocks'}",
                        f"-I{ROOT / 'src'}", str(FIXTURE),
                        str(ROOT / "src/helpers/ArduinoSerialInterface.cpp"),
                        str(ROOT / "src/helpers/wifi/SerialWifiInterface.cpp"),
                        "-o", str(binary),
                    ], capture_output=True, text=True, timeout=60)
                    self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                    checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                    self.assertIn("PASS: 21 production ACK delivery checks", checked.stdout)


if __name__ == "__main__":
    unittest.main()
