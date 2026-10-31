#!/usr/bin/env python3
"""The Quake Repeater images keep the WisBlock sensor rail powered.

Release 1.18.0.1 shipped the RAK4631 image with the 3V3_S rail switched off by the default
`gps-only` peripheral mode, so the earthquake sensor and the environment sensor disappeared
from telemetry. The cause was a missing build flag, and no test read the real build
definition, so Keymind's suite passed.

This test reads the build flags of every Mesh America Quake Repeater environment from
PlatformIO's own resolved configuration (so `extends` and `${...}` interpolation apply),
keeps only the defines that the rail policy reads, and compiles the production policy
fixture with them against an expected hold mask that is written down here:

    RAK4631 image  -> SensorPower (16)   the D7S and RAK1906 sit on 3V3_S
    RAK3401 image  -> RadioPower  (1)    the 1 W radio holds the rail

The fixture's static_assert makes the build fail when the real configuration and the
expectation disagree. Removing MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL from the real RAK4631
environment therefore turns this test red, and the negative control below proves the test
is sensitive to exactly that.

Set PIO to the pio executable when it is not on PATH. The compile step needs a host C++
compiler (CXX, default g++); there is deliberately no skip when it is missing, because a
skipped safety test is a passing one.
"""
from pathlib import Path
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/wisblock_shared_power_policy.cpp"

# Written down on purpose: the expectation must not be derived from the build definition.
EXPECTED_HOLDS = {
    "MeshAmerica_Quake_Repeater_RAK4631": 16,  # WisBlockRailHold::SensorPower
    "MeshAmerica_Quake_Repeater_RAK3401": 1,   # WisBlockRailHold::RadioPower
}

# The defines the rail policy reads (WisBlockSharedPowerPolicy.h, wisBlockCompileRailHolds()).
RAIL_DEFINES = {
    "RAK_3401",
    "RAK_4631",
    "MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL",
    "ETHERNET_ENABLED",
    "ETHERNET_USE_RAK13800",
    "RAK4631_COMBINED_ETHERNET",
}
HOLD_FLAG = "MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL"


def pio_command():
    explicit = os.environ.get("PIO")
    if explicit:
        return shlex.split(explicit, posix=(os.name != "nt"))
    found = shutil.which("pio")
    return [found] if found else [sys.executable, "-m", "platformio"]


def resolved_config():
    done = subprocess.run([*pio_command(), "project", "config", "--json-output"],
                          cwd=ROOT, text=True, capture_output=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError("pio project config failed:\n" + done.stdout + done.stderr)
    return {section: dict(items) for section, items in json.loads(done.stdout)}


def defines_of(build_flags):
    """-D defines from a resolved build_flags value (a string or a list of strings)."""
    chunks = [build_flags] if isinstance(build_flags, str) else list(build_flags)
    tokens = []
    for chunk in chunks:
        tokens.extend(shlex.split(chunk, posix=True))
    found, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        if token == "-D" and i + 1 < len(tokens):
            found.append(tokens[i + 1])
            i += 2
            continue
        if token.startswith("-D") and len(token) > 2:
            found.append(token[2:])
        i += 1
    return found


def rail_defines(define_list):
    return [d for d in define_list if d.split("=", 1)[0] in RAIL_DEFINES]


def compile_policy(rail_flags, expected):
    """Compile and run the production policy fixture; returns the completed processes."""
    with tempfile.TemporaryDirectory(prefix="quake-rail-") as folder:
        binary = Path(folder) / "policy"
        compiled = subprocess.run([
            os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
            *["-D" + d for d in rail_flags], f"-DEXPECTED_COMPILE_HOLDS={expected}",
            "-I" + str(ROOT / "src"), str(FIXTURE), "-o", str(binary),
        ], text=True, capture_output=True, timeout=120)
        if compiled.returncode != 0:
            return compiled, None
        executed = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
        return compiled, executed


CONFIG = None


def config():
    global CONFIG
    if CONFIG is None:
        CONFIG = resolved_config()
    return CONFIG


def quake_envs():
    return sorted(s[len("env:"):] for s in config() if s.startswith("env:MeshAmerica_Quake_Repeater_"))


class QuakeRailDefaultTests(unittest.TestCase):
    def test_every_quake_environment_has_a_written_expectation(self):
        self.assertEqual(sorted(EXPECTED_HOLDS), quake_envs(),
                         "a Quake Repeater environment was added or removed: write down its "
                         "expected rail hold mask in EXPECTED_HOLDS")

    def test_resolved_flags_carry_the_rail_defines(self):
        flags = {env: rail_defines(defines_of(config()["env:" + env]["build_flags"])) for env in EXPECTED_HOLDS}
        self.assertIn("RAK_4631", flags["MeshAmerica_Quake_Repeater_RAK4631"])
        self.assertIn(HOLD_FLAG + "=1", flags["MeshAmerica_Quake_Repeater_RAK4631"])
        self.assertIn("RAK_3401", flags["MeshAmerica_Quake_Repeater_RAK3401"])
        self.assertNotIn(HOLD_FLAG, [d.split("=", 1)[0] for d in flags["MeshAmerica_Quake_Repeater_RAK3401"]])

    def test_real_build_definition_gives_the_expected_rail_holds(self):
        for env, expected in EXPECTED_HOLDS.items():
            with self.subTest(env=env, expected=expected):
                flags = rail_defines(defines_of(config()["env:" + env]["build_flags"]))
                compiled, executed = compile_policy(flags, expected)
                self.assertEqual(compiled.returncode, 0,
                                 f"{env}: real build flags {flags} do not give hold mask {expected}\n"
                                 + compiled.stdout + compiled.stderr)
                self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)

    def test_negative_control_missing_hold_flag_is_caught(self):
        env = "MeshAmerica_Quake_Repeater_RAK4631"
        flags = rail_defines(defines_of(config()["env:" + env]["build_flags"]))
        without = [d for d in flags if d.split("=", 1)[0] != HOLD_FLAG]
        self.assertNotEqual(flags, without, "the real RAK4631 environment no longer carries the hold flag")
        compiled, _ = compile_policy(without, EXPECTED_HOLDS[env])
        self.assertNotEqual(compiled.returncode, 0,
                            "removing the sensor-rail hold did not fail the build: the test cannot "
                            "catch the 1.18.0.1 defect")
        self.assertIn("static assertion", compiled.stdout + compiled.stderr)


if __name__ == "__main__":
    unittest.main()
