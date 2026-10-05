#!/usr/bin/env python3
"""Qualify the capture-only startup hook against Arduino3.3.11's actual ISR."""
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import test_hwcdc_startup_session as startup
import test_hwcdc_tx_backport as backport

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "test/fixtures/hwcdc_3311"
FIX = backport.module
RAW = (CORE / "HWCDC.cpp").read_text()
PATCHED = FIX.patched_hwcdc_startup_source(RAW)


def harness(**controls):
    state, functions, owner = startup.application_sources(**controls)
    # Reuse only the peripheral boundary. All driver methods below come from
    # the original 3.3.11 implementation with its capture-only startup patch.
    prefix = backport.HARNESS.split("@SUPPORT@", 1)[0]
    prefix = prefix.replace("static std::vector<unsigned> event_lengths;",
                            "static std::vector<unsigned> event_lengths;\n"
                            "static std::deque<int> queued_events;")
    prefix = prefix.replace(
        " if(event==ARDUINO_HW_CDC_TX_EVENT)event_lengths.push_back(data->tx.len);",
        " queued_events.push_back(event);\n"
        " if(event==ARDUINO_HW_CDC_TX_EVENT)event_lengths.push_back(data->tx.len);")
    fields = "\n".join(re.search(r"^static [^\n]*\b" + name + r"[^\n]*;",
                                  PATCHED, re.MULTILINE)[0]
                       for name in ("tx_stash_buf", "tx_stash_len", "hw_cdc_tx_mux"))
    driver = "\n".join(backport.body(PATCHED, signature) for signature in (
        "static inline void hw_cdc_enable_tx_intr(void)",
        "static inline void hw_cdc_enable_tx_intr_from_isr(void)",
        "static inline void hw_cdc_disable_tx_intr_from_isr(void)",
        "static inline void hw_cdc_clear_tx_stash(void)",
        "bool HWCDC::isCDC_Connected()",
        "static void hw_cdc_isr_handler(",
    ))
    service = r'''
static void pulse(unsigned limit=64) {
  fifo_limit=limit; intr_status=USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY;
  hw_cdc_isr_handler(nullptr);
}
static void reset() {
  ring=Ring{}; staged.clear(); event_lengths.clear(); queued_events.clear();
  tx_stash_len=0; irq_enabled=true; plugged=false; connected=false;
  before_empty_return=nullptr; flushes=0;
}
'''
    extra = startup.EXTRA.replace("#define MESH_HWCDC_PINNED_TX_BACKPORT 1",
                                  "#define MESH_HWCDC_PINNED_TX_BACKPORT 0")
    extra = extra.replace("mesh_hwcdc_tx_stash_len", "tx_stash_len")
    extra = extra.replace(" && mesh_hwcdc_fifo_pending", "")
    extra = extra.replace(" && !mesh_hwcdc_fifo_pending", "")
    extra = extra.replace(" && mesh_hwcdc_tx_allowed", "")
    extra = extra.replace("@STARTUP_STATE@", state).replace(
        "@FUNCTIONS@", functions).replace("@OWNER_RESET_HOOK@", owner)
    return prefix + FIX.HWCDC_3311_STARTUP_HOOK + fields + "\n" + driver + service + extra


class Hwcdc3311StartupSessionTests(startup.HwcdcStartupSessionTests):
    # Run the exact same client/session assertions and negative controls with
    # the actual 3.3.11 ISR and non-backport application cleanup branches.
    def run_case(self, case, *, expect_success=True, **controls):
        with tempfile.TemporaryDirectory(prefix="hwcdc-3311-startup-") as directory:
            directory = Path(directory)
            cpp, binary = directory / "startup.cpp", directory / "startup"
            cpp.write_text(harness(**controls), encoding="ascii")
            compiled = subprocess.run([
                "g++", "-std=c++17", "-pthread", "-Wall", "-Wextra",
                "-Wno-unused-parameter", "-Wno-sign-compare",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-pie", "-no-pie", "-I" + str(ROOT / "src"),
                str(cpp), "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary), case], capture_output=True,
                                    text=True, timeout=10)
            if expect_success:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            else:
                self.assertNotEqual(result.returncode, 0, "Negative control did not fail")

    def test_only_reset_event_posting_and_hook_declaration_change(self):
        self.assertEqual(hashlib.sha256(RAW.encode()).hexdigest(), FIX.PINNED_HWCDC_3311_SHA256)
        self.assertEqual(hashlib.sha256(PATCHED.encode()).hexdigest(), FIX.PATCHED_HWCDC_3311_SHA256)
        self.assertEqual(PATCHED.count(FIX.HWCDC_3311_STARTUP_HOOK), 1)
        self.assertEqual(PATCHED.count(FIX.HWCDC_3311_RESET_CAPTURE), 1)
        reverted = PATCHED.replace(FIX.HWCDC_3311_STARTUP_HOOK, "", 1).replace(
            FIX.HWCDC_3311_RESET_CAPTURE, FIX.HWCDC_3311_RESET_POST, 1)
        self.assertEqual(reverted, RAW, "Unrelated driver code changed")
        self.assertEqual(FIX.patched_hwcdc_startup_source(PATCHED), PATCHED)
        self.assertEqual(FIX.patched_hwcdc_startup_source(RAW.replace("\n", "\r\n")), PATCHED)
        for changed in (RAW + "\n", PATCHED + "\n",
                        RAW.replace("tx_stash_len = 0;", "tx_stash_len = 1;", 1)):
            with self.subTest(changed=hashlib.sha256(changed.encode()).hexdigest()):
                with self.assertRaises(RuntimeError):
                    FIX.patched_hwcdc_startup_source(changed)

    def test_build_local_patch_has_exact_version_and_mode_scope(self):
        class Node:
            def __init__(self, path): self.path = path
            def srcnode(self): return self
            def get_abspath(self): return str(self.path)
        class Environment(dict):
            def __init__(self, definitions, build):
                super().__init__(CPPDEFINES=definitions)
                self.build, self.paths = build, []
            def subst(self, value):
                assert value == "$BUILD_DIR"
                return str(self.build)
            def File(self, path): return path
            def AppendUnique(self, **kwargs): self.paths += kwargs["CPPPATH"]
        with tempfile.TemporaryDirectory(prefix="hwcdc-3311-source-") as directory:
            directory = Path(directory)
            sdk = directory / "sdk"; sdk.mkdir()
            path, version = sdk / "HWCDC.cpp", sdk / "esp_arduino_version.h"
            path.write_text(RAW, encoding="ascii")
            version.write_text((CORE / "esp_arduino_version.h").read_text(), encoding="ascii")
            node = Node(path)
            for definitions in ([], [("ARDUINO_USB_CDC_ON_BOOT", 0), ("ARDUINO_USB_MODE", 1)],
                                [("ARDUINO_USB_CDC_ON_BOOT", 1), ("ARDUINO_USB_MODE", 0)]):
                env = Environment(definitions, directory / "build")
                self.assertIs(FIX.replace_hwcdc_source(env, node), node)
                self.assertFalse(env.build.exists())
            env = Environment([("ARDUINO_USB_CDC_ON_BOOT", 1), ("ARDUINO_USB_MODE", 1)],
                              directory / "build")
            result = Path(FIX.replace_hwcdc_source(env, node))
            self.assertEqual(result.read_text(), PATCHED)
            self.assertEqual(path.read_text(), RAW)
            self.assertEqual(env.paths, [str(sdk)])
            before = result.stat().st_mtime_ns
            FIX.replace_hwcdc_source(env, node)
            self.assertEqual(result.stat().st_mtime_ns, before)
            path.write_text(RAW + "\n", encoding="ascii")
            with self.assertRaises(RuntimeError):
                FIX.replace_hwcdc_source(env, node)
            # An unreviewed framework version keeps its existing driver.
            version.write_text("#define ESP_ARDUINO_VERSION_MAJOR 3\n"
                               "#define ESP_ARDUINO_VERSION_MINOR 3\n"
                               "#define ESP_ARDUINO_VERSION_PATCH 12\n", encoding="ascii")
            self.assertIs(FIX.replace_hwcdc_source(env, node), node)

    def test_shared_predicate_is_exported_without_the_217_tx_backport(self):
        source = (ROOT / "src/helpers/UsbLogging.cpp").read_text()
        hook = source.index('extern "C" bool meshEsp32HwcdcShouldReportBusReset()')
        start = source.rfind("#if ", 0, hook)
        end = source.index("#endif", hook) + len("#endif")
        block = source[start:end]
        for guard in (0, 1):
            code = "#include <atomic>\n#include <cassert>\n"
            code += "#define MESH_ESP32_HWCDC_SESSION_GUARD " + str(guard) + "\n"
            code += "#define MESH_HWCDC_PINNED_TX_BACKPORT 0\n"
            code += "namespace mesh { static std::atomic<bool> esp32_hwcdc_startup_pending{true}; }\n"
            code += block + "\nint main() {\n#if MESH_ESP32_HWCDC_SESSION_GUARD\n"
            code += "assert(!meshEsp32HwcdcShouldReportBusReset());\n"
            code += "mesh::esp32_hwcdc_startup_pending.store(false);\n"
            code += "assert(meshEsp32HwcdcShouldReportBusReset());\n#endif\n}\n"
            with self.subTest(guard=guard), tempfile.TemporaryDirectory() as directory:
                cpp, binary = Path(directory) / "export.cpp", Path(directory) / "export"
                cpp.write_text(code, encoding="ascii")
                result = subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(binary)],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
