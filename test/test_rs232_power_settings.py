#!/usr/bin/env python3
"""Execute checked RS-232 power preferences and exact production CLI branches."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_ota_channel_persistence import persistence_harness
from test_replay_reset_integration import extract_braced
from test_rs232_heartbeat_owner import HARNESS as OWNER_HARNESS

ROOT = Path(__file__).resolve().parents[1]
SANITIZERS = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]


class RS232PowerSettingsTests(unittest.TestCase):
    def compile_run(self, code, flags, persistence=False):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "a host C++ compiler is required")
        with tempfile.TemporaryDirectory(prefix="rs232-power-settings-") as directory:
            work = Path(directory)
            if persistence:
                transaction = (ROOT / "src/helpers/ContactFileTransaction.h").read_text(encoding="ascii")
                (work / "ContactFileTransaction.h").write_text(transaction.replace(
                    '#include "IdentityStore.h"', '#include <helpers/IdentityStore.h>'), encoding="ascii")
            cpp, binary = work / "test.cpp", work / "test"
            cpp.write_text(code, encoding="ascii")
            built = subprocess.run([compiler, "-std=c++17", *SANITIZERS, *flags,
                "-I" + str(work), "-I" + str(ROOT / "test/fixtures/radio_profiles/mocks"),
                "-I" + str(ROOT / "src"), "-I" + str(ROOT / "src/helpers"), str(cpp), "-o", str(binary)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_actual_writers_loaders_checked_tail_and_failed_transactions(self):
        base = persistence_harness().replace("#define WITH_RS232_BRIDGE_UART 1", "")
        code = base[:base.index("struct Capture {")]
        code += (ROOT / "test/fixtures/rs232_power_settings_prefs.cpp").read_text(encoding="ascii")
        for platform in ("NRF52_PLATFORM", "ESP32_PLATFORM"):
            for mqtt in (False, True):
                with self.subTest(platform=platform, mqtt=mqtt):
                    flags = ["-D" + platform, "-DENABLE_OTA=1", "-DWITH_RS232_BRIDGE=Serial2",
                             "-DWITH_RS232_BRIDGE_UART=2", "-DRS232_BRIDGE_MERGED=1"]
                    if mqtt:
                        flags.append("-DWITH_MQTT_BRIDGE=1")
                    self.compile_run(code, flags, persistence=True)

    def test_exact_cli_settings_and_standby_save_failure_recovery(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="ascii")
        header = (ROOT / "examples/simple_repeater/MyMesh.h").read_text(encoding="ascii")
        owner = "\n".join(extract_braced(header, signature) for signature in (
            "RS232Bridge* createRS232Bridge()", "bool beginRS232Bridge()", "bool endRS232Bridge()",
            "bool rs232BridgeEnabled() const", "bool isRs232BridgeRunning() const override",
            "void serviceRs232BridgePower()", "void formatRs232Status(char* reply) override",
            "bool setRs232BridgeState(bool enable)", "bool restartRs232Bridge()"))
        code = OWNER_HARNESS[:OWNER_HARNESS.index("static void enable(")]
        code = code.replace("@OWNER@", owner).replace("@SLEEP@", "")
        code = '#include <helpers/CLICommandUtils.h>\n#include <helpers/bridges/RS232PowerSettings.h>\n#include <initializer_list>\n#define BRIDGE_MAX_BAUD 115200\n' + code
        code = code.replace("bool battery_alert_enabled = false;", "bool battery_alert_enabled = false; uint32_t bridge_baud = 115200;")
        code = code.replace("NodePrefs _prefs;", "NodePrefs _prefs;\n  bool setBridgeState(bool) { return true; }")
        code += (ROOT / "test/fixtures/rs232_power_settings_cli.cpp").read_text(encoding="ascii")
        parsers = "\n".join(extract_braced(source, signature) for signature in (
            "static bool parseOnOffStrict(", "static bool configKeyEquals("))
        code = code.replace("@PARSERS@", parsers)
        commands = "\n".join(extract_braced(source, signature) for signature in (
            "void CommonCLI::handleSetCmd(", "void CommonCLI::handleGetCmd("))
        for platform in ("NRF52_PLATFORM", "ESP32_PLATFORM"):
            for mqtt in (False, True):
                with self.subTest(platform=platform, mqtt=mqtt):
                    flags = ["-D" + platform, "-DWITH_BRIDGE=1", "-DWITH_RS232_BRIDGE=Serial2",
                             "-DWITH_RS232_BRIDGE_UART=2", "-DWITH_RS232_BRIDGE_ALT=Serial1",
                             "-DWITH_RS232_BRIDGE_ALT_UART=1",
                             "-DENV_INCLUDE_GPS=1"]
                    if mqtt:
                        flags.append("-DWITH_MQTT_BRIDGE=1")
                    processed = subprocess.run([compiler, "-E", "-P", "-x", "c++", *flags, "-"],
                        input=commands, capture_output=True, text=True, check=True).stdout
                    sets = "\n".join(extract_braced(processed, signature) for signature in (
                        'if (strncmp(config, "rs232.heartbeat ", 16) == 0)',
                        'if (strncmp(config, "rs232.autosleep ", 16) == 0)',
                        'if (strncmp(config, "rs232.idle ", 11) == 0)',
                        'if (strncmp(config, "rs232.enabled ", 14) == 0)'))
                    sets += "\n" + "\nelse ".join(extract_braced(processed, signature) for signature in (
                        'if (memcmp(config, "bridge.enabled ", 15) == 0)',
                        'if (memcmp(config, "bridge.baud ", 12) == 0)',
                        'if (memcmp(config, "bridge.uart ", 12) == 0)')) + "\nreturn;"
                    gets = "\nelse ".join(extract_braced(processed, signature) for signature in (
                        'if (configKeyEquals(config, "rs232.heartbeat"))',
                        'if (configKeyEquals(config, "rs232.autosleep"))',
                        'if (configKeyEquals(config, "rs232.idle"))',
                        'if (configKeyEquals(config, "rs232.status"))'))
                    self.compile_run(code.replace("@SETS@", sets).replace("@GETS@", gets), flags)


if __name__ == "__main__":
    unittest.main()
