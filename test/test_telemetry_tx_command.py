#!/usr/bin/env python3
"""Exercise the actual repeater telemetry schedule command on the host."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]


class TelemetryScheduleCommandTests(unittest.TestCase):
    def test_actual_command_validation_permissions_and_rollback(self):
        source = (ROOT / "examples/simple_repeater/MyMesh.cpp").read_text(encoding="utf-8")
        limit = re.search(r"static const uint8_t TELEMETRY_HISTORY_TX_MAX_DAYS[^;]*;", source).group()
        helper = extract_braced(source, "static char* trimSpaces(")
        branch = extract_braced(source, "if (strncmp(command, telemetry_tx_schedule_command,")
        generated = (limit + "\n" + helper +
                     "\nvoid Fixture::handle(char* command, char* reply, ClientInfo* sender) {\n"
                     '  static const char telemetry_tx_schedule_command[] = "set telemetry.tx schedule";\n' +
                     branch + '\n  strcpy(reply, "Err - unrecognized command");\n}\n')
        sanitizers = [] if os.name == "nt" else ["-fsanitize=address,undefined",
                                               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        with tempfile.TemporaryDirectory() as work:
            (Path(work) / "production_telemetry_tx.inc").write_text(generated, encoding="ascii")
            executable = Path(work) / "telemetry-tx-command"
            compiled = subprocess.run([shutil.which("g++") or "g++", "-std=c++17", "-O1", "-g",
                                       "-Wall", "-Wextra", *sanitizers, "-I", work,
                                       str(ROOT / "test/fixtures/telemetry_tx_command/fixture.cpp"),
                                       "-o", str(executable)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
