"""Exercise production UDP preference parsing, atomic persistence and CLI."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/udp_bridge"

class UDPBridgeConfigTests(unittest.TestCase):
    def compile_run(self, source, settings=False, extra_flags=()):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="udp-config-") as directory:
            work = Path(directory)
            flags = []
            sources = []
            if settings:
                original = ROOT / "test/fixtures/guest_login/mocks"
                mocks = work / "mocks"
                shutil.copytree(original, mocks)
                for path in mocks.rglob("*"):
                    if path.is_file():
                        path.write_text(path.read_text().replace("/guest_login", "/udp_bridge"))
                flags = ["-DWITH_UDP_BRIDGE=1", "-DESP32_PLATFORM", "-DESP32", "-I", str(mocks)]
                sources = [str(ROOT / "src/helpers/UDPBridgeSettings.cpp")]
            main = work / "main.cpp"
            main.write_text(source, encoding="ascii")
            binary = work / "check"
            result = subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-Wno-misleading-indentation", "-Wno-sign-compare", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-no-pie", *flags, *extra_flags, "-I", str(ROOT / "src"), str(main), *sources,
                "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_parser_codec_and_transaction_boundaries(self):
        self.compile_run((FIXTURE / "settings.cpp").read_text(encoding="ascii"), settings=True)

    def test_actual_cli_dispatch(self):
        header = (ROOT / "src/helpers/CommonCLI.h").read_text(encoding="ascii")
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="ascii")
        body = extract_braced(source, "bool CommonCLI::handleUDPBridgeCommand(")
        callbacks = "\n".join(extract_braced(header, signature) for signature in (
            "virtual const mesh::bridge::udp::Prefs* getUDPBridgePrefs(",
            "virtual bool setUDPBridgePrefs(", "virtual void formatUDPBridgeStatus(",
            "virtual void formatUDPBridgeStats(", "virtual bool sendUDPBridgeTest(",
            "virtual bool resetUDPBridgeStats("))
        self.assertIn("if (handleUDPBridgeCommand(sender_timestamp, command, reply)) return;", source)
        fixture = (FIXTURE / "cli.cpp").read_text(encoding="ascii")
        self.compile_run(fixture.replace("CALLBACKS_HERE", callbacks).replace("HANDLER_HERE", body))

    def test_browser_ota_closes_udp_before_start_and_restores_only_saved_intent(self):
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="ascii")
        start = source.index('    } else if (memcmp(command, "start ota", 9)')
        end = source.index('    } else if (memcmp(command, "clock", 5)', start)
        fixture = (FIXTURE / "ota.cpp").read_text(encoding="ascii")
        self.compile_run(fixture.replace("OTA_HERE", source[start:end]), extra_flags=["-DWITH_UDP_BRIDGE=1"])

if __name__ == "__main__":
    unittest.main()
