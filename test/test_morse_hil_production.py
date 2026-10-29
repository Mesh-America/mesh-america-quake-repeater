#!/usr/bin/env python3
"""Prove production-equivalent HIL flags survive actual PlatformIO/SCons parsing."""
import ast
import configparser
import importlib.util
import os
from pathlib import Path
import re
import sys
import unittest

from test_morse_tx import compile_run

ROOT = Path(__file__).resolve().parents[1]
RF_DEFAULTS = {
    "MESH_MORSE_HIL_WARM_TX": 0,
    "MESH_MORSE_HIL_RSSI_WINDOW": 0,
    "MESH_MORSE_HIL_PA_RAMP_US": 3400,
    "MESH_MORSE_HIL_SAMPLE_INTERVAL_MS": 2,
    "MESH_MORSE_HIL_FAST_OFF_DEBOUNCE": 0,
    "MESH_MORSE_HIL_PACKET_GATING": 0,
}
GOOD_FLAGS = ["-DMESH_MORSE_HIL=1", "-DMESH_MORSE_HIL_PRODUCTION_RF=1"] + [
    f"-D{name}={value}" for name, value in RF_DEFAULTS.items()]
GUARD_MESSAGE = "Production-equivalent HIL requires the shipping Morse RF settings"
FIXTURE = """
#include <helpers/MorseTx.h>
#include <helpers/MorseRx.h>
#include <cassert>
int main() {
  static_assert(mesh::MorseRx::SampleIntervalMillis == 2, "shipping sampler must remain two ms");
  static_assert(mesh::MorseRx::ReceiverBitRateKbps == 1.2f, "shipping receiver clock must remain unchanged");
  mesh::MorseTx sender;
  assert(sender.start("SOS",25,0) == mesh::MorseTxResult::Started);
  assert(sender.nextDeadline() == 48);
}
"""


def platformio_flag_environment():
    """Import only the real parser helpers: never invoke a PlatformIO process."""
    scons_override = os.environ.get("MESH_TEST_SCONS_PATH")
    if scons_override:
        sys.path.insert(0, scons_override)
    elif importlib.util.find_spec("SCons") is None:
        core = Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))
        choices = sorted((core / "packages/tool-scons").glob("scons-local-*"))
        if not choices:
            raise AssertionError("Earlier PlatformIO native CI step must install SCons; set MESH_TEST_SCONS_PATH for another host")
        sys.path.insert(0, str(choices[-1]))
    import SCons.Environment
    import SCons.Node.FS
    import SCons.Util

    builder_override = os.environ.get("MESH_TEST_PLATFORMIO_BUILDER")
    if builder_override:
        builder = Path(builder_override)
    else:
        package = importlib.util.find_spec("platformio")
        if package is None:
            raise AssertionError("PlatformIO parser package is required; set MESH_TEST_PLATFORMIO_BUILDER for another host")
        builder = Path(package.origin).parent / "builder/tools/piobuild.py"
    parsed = ast.parse(builder.read_text(encoding="utf-8"))
    names = {"ParseFlagsExtended", "ProcessFlags", "ProcessUnFlags"}
    selected = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in selected} != names:
        raise AssertionError("Installed PlatformIO flag helper contract changed; review the actual implementation")
    namespace = {"Util": SCons.Util, "FS": SCons.Node.FS, "os": os, "string_types": (str,)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(builder), "exec"), namespace)
    env = SCons.Environment.Environment(tools=["gcc"])
    for name in names:
        env.AddMethod(namespace[name], name)
    return env


def local_hil_flags(config, section, option, chain=()):
    """Resolve local recipe references; external base recipes contain no HIL flags."""
    key = (section, option)
    if key in chain:
        raise AssertionError("HIL recipe contains a recursive interpolation")
    value = config.get(section, option, fallback="")
    def expand(match):
        referenced, field = match.group(1), match.group(2)
        return local_hil_flags(config, referenced, field, chain + (key,)) if config.has_section(referenced) else ""
    return re.sub(r"\$\{([^}.]+)\.([^}]+)\}", expand, value)


class ProductionHilFlagTests(unittest.TestCase):
    def test_production_guard_rejects_receiver_clock_override_without_fixture_assertion(self):
        # The actual header must reject an experimental clock, independently
        # of this suite's ordinary fixture assertion or the chosen INI recipe.
        fixture = "#include <helpers/MorseRx.h>\nint main() {}\n"
        compile_run(self, fixture, flags=GOOD_FLAGS)
        compile_run(self, fixture, flags=GOOD_FLAGS + ["-DMESH_MORSE_HIL_RX_BITRATE_KBPS=1.2f"])
        for rate in ("0.6f", "20.0f", "300.0f"):
            with self.subTest(rate=rate), self.assertRaisesRegex(
                    AssertionError, "Production-equivalent HIL requires the shipping Morse receiver clock"):
                compile_run(self, fixture, flags=GOOD_FLAGS + [f"-DMESH_MORSE_HIL_RX_BITRATE_KBPS={rate}"])
        experimental = [flag for flag in GOOD_FLAGS if not flag.startswith("-DMESH_MORSE_HIL_PRODUCTION_RF=")]
        fixture = ("#include <helpers/MorseRx.h>\n"
                   "static_assert(mesh::MorseRx::ReceiverBitRateKbps == 20.0f, \"lab override remains available\");\n"
                   "int main() {}\n")
        compile_run(self, fixture, flags=experimental + ["-DMESH_MORSE_HIL_RX_BITRATE_KBPS=20.0f"])

    def test_correct_rf_defaults_compile_and_each_experimental_rf_value_is_rejected(self):
        compile_run(self, FIXTURE, flags=GOOD_FLAGS)
        for name in RF_DEFAULTS:
            bad = 800 if name.endswith("PA_RAMP_US") else 1
            if name.endswith("RSSI_WINDOW"):
                bad = 2
            flags = [flag for flag in GOOD_FLAGS if not flag.startswith(f"-D{name}=")]
            flags.append(f"-D{name}={bad}")
            with self.subTest(flag=name), self.assertRaisesRegex(AssertionError, GUARD_MESSAGE):
                compile_run(self, FIXTURE, flags=flags)
        for hil in (None, 0):
            flags = [flag for flag in GOOD_FLAGS if not flag.startswith("-DMESH_MORSE_HIL=")]
            if hil is not None:
                flags.append(f"-DMESH_MORSE_HIL={hil}")
            with self.subTest(hil=hil), self.assertRaisesRegex(AssertionError, GUARD_MESSAGE):
                compile_run(self, FIXTURE, flags=flags)

    def test_actual_scons_inline_undef_is_a_negative_control_not_an_override(self):
        env = platformio_flag_environment()
        # PlatformIO moves -U after its CPPDEFINES. A textual -U then -D must
        # never be accepted as proof of the final production flag values.
        env.ProcessFlags(" ".join(GOOD_FLAGS + ["-UMESH_MORSE_HIL_PA_RAMP_US", "-DMESH_MORSE_HIL_PA_RAMP_US=3400"]))
        resolved = env.subst("$CCFLAGS $_CPPDEFFLAGS").split()
        self.assertGreater(resolved.index("-UMESH_MORSE_HIL_PA_RAMP_US"),
                           max(i for i, item in enumerate(resolved) if item.startswith("-DMESH_MORSE_HIL_PA_RAMP_US=")))
        with self.assertRaisesRegex(AssertionError, GUARD_MESSAGE):
            compile_run(self, FIXTURE, flags=resolved)

    def test_both_actual_production_recipes_survive_scons_and_compiler_ordering(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / "tools/hil/morse_bench.ini", encoding="utf-8")
        for section in ("env:morse_production_rak4631_companion", "env:morse_production_pocket_companion"):
            with self.subTest(recipe=section):
                env = platformio_flag_environment()
                flags = local_hil_flags(config, section, "build_flags")
                unflags = local_hil_flags(config, section, "build_unflags")
                env.ProcessFlags(flags)
                env.ProcessUnFlags(unflags)
                resolved = [flag for flag in env.subst("$CCFLAGS $_CPPDEFFLAGS").split()
                            if flag.startswith(("-DMESH_MORSE_", "-UMESH_MORSE_"))]
                for name, expected in RF_DEFAULTS.items():
                    self.assertEqual([flag for flag in resolved if flag.startswith(f"-D{name}=")],
                                     [f"-D{name}={expected}"])
                    self.assertNotIn(f"-U{name}", resolved)
                self.assertIn("-DMESH_MORSE_HIL_PRODUCTION_RF=1", resolved)
                compile_run(self, FIXTURE, flags=resolved)


if __name__ == "__main__":
    unittest.main()
