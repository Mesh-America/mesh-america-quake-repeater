#!/usr/bin/env python3
"""Reproduce the queued timer callback crash and verify the pinned backport."""
from pathlib import Path
import hashlib
import importlib.util
import os
import resource
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("esp32_nimble_timer_fix", ROOT / "scripts/esp32_nimble_timer_fix.py")
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)

# These are the actual relevant 2.5.1 function bodies, with the original
# preprocessor branches retained. Compile the transformed functions below.
TIMER_RESET = """static void
ble_hs_timer_reset(uint32_t ticks)
{
    int rc;

    if (!ble_hs_is_enabled()) {
        ble_npl_callout_stop(&ble_hs_timer);
        ble_npl_callout_deinit(&ble_hs_timer);
    } else {
        rc = ble_npl_callout_reset(&ble_hs_timer, ticks);
        BLE_HS_DBG_ASSERT_EVAL(rc == 0);
    }
}
"""
HOST_DEINIT = """void
ble_hs_deinit(void)
{
    ble_hs_flow_deinit();

#if BLE_MONITOR
    ble_monitor_deinit();
#endif

    ble_npl_mutex_deinit(&ble_hs_mutex);

    ble_mqueue_deinit(&ble_hs_rx_q);

    ble_hs_stop_deinit();

    ble_gap_deinit();

    ble_hs_hci_deinit();

    ble_npl_event_deinit(&ble_hs_ev_start_stage2);

    ble_npl_event_deinit(&ble_hs_ev_start_stage1);

    ble_npl_event_deinit(&ble_hs_ev_reset);

#if NIMBLE_BLE_CONNECT
    ble_npl_event_deinit(&ble_hs_ev_tx_notifications);

    ble_gatts_stop();
#endif

    ble_npl_callout_deinit(&ble_hs_timer);

#if (MYNEWT_VAL(BLE_HOST_BASED_PRIVACY))
    ble_hs_resolv_deinit();
#endif
}
"""
CALLOUT_DEINIT = """void
npl_freertos_callout_deinit(struct ble_npl_callout *co)
{
    if (!co->handle) {
        return;
    }

#if CONFIG_BT_NIMBLE_USE_ESP_TIMER
    if(esp_timer_stop(co->handle))
        ESP_LOGW(LOG_TAG, "Timer not stopped");

    if(esp_timer_delete(co->handle))
        ESP_LOGW(LOG_TAG, "Timer not deleted");
#else
    xTimerDelete(co->handle, portMAX_DELAY);
    ble_npl_event_deinit(&co->ev);
#endif
    memset(co, 0, sizeof(struct ble_npl_callout));
}
"""
SOURCE = "// NimBLE-Arduino 2.5.1 host function fixture.\n" + TIMER_RESET + HOST_DEINIT

HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#define BLE_MONITOR 0
#define NIMBLE_BLE_CONNECT 1
#define MYNEWT_VAL(x) 0
#define BLE_HS_DBG_ASSERT_EVAL(x) assert(x)
#define ESP_LOGW(...) ((void)0)
static constexpr unsigned portMAX_DELAY = 0xffffffff;
struct ble_npl_event { void (*fn)(ble_npl_event*); };
struct ble_npl_callout { void* handle; ble_npl_event ev; };
static ble_npl_callout ble_hs_timer{};
static ble_npl_event ble_hs_ev_start_stage2{}, ble_hs_ev_start_stage1{}, ble_hs_ev_reset{}, ble_hs_ev_tx_notifications{};
static int ble_hs_mutex = 0, ble_hs_rx_q = 0;
static bool enabled = true, host_running = true;
static unsigned stops = 0, deletes = 0, resets = 0, callbacks = 0, final_cleanups = 0;
static uint32_t last_ticks = 0;
static bool ble_hs_is_enabled() { return enabled; }
static void ble_npl_callout_stop(ble_npl_callout*) { ++stops; }
static int ble_npl_callout_reset(ble_npl_callout* co, uint32_t ticks) {
    assert(co->handle && co->ev.fn); ++resets; last_ticks = ticks; return 0;
}
static void ble_npl_event_deinit(ble_npl_event*) {}
static void xTimerDelete(void* handle, unsigned) { assert(handle); ++deletes; }
static int esp_timer_stop(void* handle) { assert(handle); return 0; }
static int esp_timer_delete(void* handle) { assert(handle); ++deletes; return 0; }
@CALLOUT_DEINIT@
static void ble_npl_callout_deinit(ble_npl_callout* co) { npl_freertos_callout_deinit(co); }
static void ble_hs_flow_deinit() { assert(!host_running); ++final_cleanups; }
static void ble_npl_mutex_deinit(int*) {}
static void ble_mqueue_deinit(int*) {}
static void ble_hs_stop_deinit() {}
static void ble_gap_deinit() {}
static void ble_hs_hci_deinit() {}
static void ble_gatts_stop() {}
@SOURCE@
static void timer_callback(ble_npl_event* ev) { assert(ev == &ble_hs_timer.ev); ++callbacks; }
static void ble_npl_event_run(ble_npl_event* ev) { ev->fn(ev); }
int main(int argc, char**) {
    for (unsigned cycle = 0; cycle < 1000; ++cycle) {
        host_running = true;
        enabled = true;
        ble_hs_timer.handle = reinterpret_cast<void*>(1);
        ble_hs_timer.ev.fn = timer_callback;
        ble_hs_timer_reset(125);
        assert(last_ticks == 125 && resets == cycle + 1);
        // An expired timer queues a pointer to this same embedded event.
        ble_npl_event* queued = &ble_hs_timer.ev;
        // ble_hs_stop_begin transitions ON -> STOPPING before rescheduling.
        enabled = false;
        ble_hs_timer_reset(0);
        // The old body memsets the queued callback here. Exercise the exact
        // indirect event call to reproduce PC zero, rather than masking it.
        if (argc > 1) {
            assert(queued->fn == nullptr);
            ble_npl_event_run(queued);
            return 99;
        }
        assert(queued->fn != nullptr && ble_hs_timer.handle);
        assert(deletes == cycle); // Stop alone must preserve the live callout.
        ble_npl_event_run(queued);
        assert(callbacks == cycle + 1 && stops == cycle + 1);
        host_running = false;
        ble_hs_deinit(); // Retained final cleanup releases the timer once.
        assert(deletes == cycle + 1 && final_cleanups == cycle + 1);
        assert(ble_hs_timer.handle == nullptr && ble_hs_timer.ev.fn == nullptr);
    }
    puts("queued timer shutdown and final cleanup passed");
}
"""


def fixture_pins(source=SOURCE):
    repaired = source.replace(FIX.ORIGINAL, FIX.REPAIRED, 1)
    return patch.multiple(FIX, PINNED_SHA256=hashlib.sha256(source.encode()).hexdigest(),
                          PATCHED_SHA256=hashlib.sha256(repaired.encode()).hexdigest())


def disable_core_dumps():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class FakeNode:
    def __init__(self, path):
        self.path = path

    def srcnode(self):
        return self

    def get_abspath(self):
        return str(self.path)


class FakeEnvironment:
    def __init__(self, build):
        self.build = build
        self.paths = []
        self.middleware = []

    def subst(self, expression):
        assert expression == "$BUILD_DIR"
        return str(self.build)

    def AppendUnique(self, **kwargs):
        for path in kwargs["CPPPATH"]:
            if path not in self.paths:
                self.paths.append(path)

    def File(self, path):
        return Path(path)

    def AddBuildMiddleware(self, callback, pattern):
        self.middleware.append((callback, pattern))


class NimbleTimerFixTests(unittest.TestCase):
    def test_queued_event_reproduces_null_call_and_fixed_cycles_release_timer(self):
        with fixture_pins():
            repaired = FIX.patched_nimble_source(SOURCE, FIX.PINNED_VERSION)
        self.assertIn(HOST_DEINIT, repaired)
        for esp_timer in (0, 1):
            with self.subTest(esp_timer=esp_timer), tempfile.TemporaryDirectory(prefix="nimble-timer-race-") as directory:
                root = Path(directory)
                cpp, executable = root / "test.cpp", root / "test"
                for legacy in (True, False):
                    text = HARNESS.replace("@SOURCE@", SOURCE if legacy else repaired).replace("@CALLOUT_DEINIT@", CALLOUT_DEINIT)
                    cpp.write_text(text)
                    command = [os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                               "-Wno-unused-function", "-fno-pie", "-no-pie", f"-DCONFIG_BT_NIMBLE_USE_ESP_TIMER={esp_timer}"]
                    if not legacy:
                        command += ["-fsanitize=address,undefined"]
                    built = subprocess.run(command + [str(cpp), "-o", str(executable)], text=True, capture_output=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    run = subprocess.run([str(executable)] + (["expect-null"] if legacy else []), text=True,
                                         capture_output=True, timeout=10, preexec_fn=disable_core_dumps)
                    if legacy:
                        self.assertEqual(run.returncode, -signal.SIGSEGV, run.stderr)
                    else:
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertIn("final cleanup passed", run.stdout)

    def test_version_hash_idempotence_and_final_cleanup_guards(self):
        with fixture_pins():
            expected = SOURCE.replace(FIX.ORIGINAL, FIX.REPAIRED, 1)
            self.assertEqual(FIX.patched_nimble_source(SOURCE, "2.5.1"), expected)
            self.assertEqual(FIX.patched_nimble_source(expected, "2.5.1"), expected)
            self.assertEqual(FIX.patched_nimble_source(SOURCE.replace("\n", "\r\n"), "2.5.1"), expected)
            self.assertEqual(SOURCE.splitlines().count("        ble_npl_callout_deinit(&ble_hs_timer);"), 1)
            self.assertIn(HOST_DEINIT, expected)
            self.assertEqual(len(SOURCE.splitlines()) - len(expected.splitlines()), 1)
            for version in ("2.5.0", "2.5.2", "3.0.0"):
                with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, "unreviewed library version"):
                    FIX.patched_nimble_source(SOURCE, version)
            for source in (SOURCE + "// changed\n", SOURCE.replace(HOST_DEINIT, ""), SOURCE + FIX.ORIGINAL):
                with self.assertRaisesRegex(RuntimeError, "changed pinned source"):
                    FIX.patched_nimble_source(source, "2.5.1")
            with patch.object(FIX, "REPAIRED", FIX.REPAIRED + "// unintended edit\n"):
                with self.assertRaisesRegex(RuntimeError, "unexpected transform"):
                    FIX.patched_nimble_source(SOURCE, "2.5.1")

    def test_middleware_only_copies_pinned_library_source(self):
        with tempfile.TemporaryDirectory(prefix="nimble-timer-middleware-") as directory, fixture_pins():
            root = Path(directory)
            library = root / "libdeps/test/NimBLE-Arduino"
            source = library.joinpath(*FIX.SOURCE_SUFFIX)
            source.parent.mkdir(parents=True)
            metadata = library / "library.properties"
            metadata.write_text("name=NimBLE-Arduino\nversion=2.5.1\n")
            source.write_text(SOURCE)
            source_timestamp = source.stat().st_mtime_ns
            node, env = FakeNode(source), FakeEnvironment(root / "build")
            FIX.install(env)
            self.assertEqual(env.middleware, [(FIX.replace_nimble_source, "*NimBLE-Arduino*ble_hs.c")])
            destination = FIX.replace_nimble_source(env, node)
            self.assertEqual(source.read_text(), SOURCE)
            self.assertEqual(source.stat().st_mtime_ns, source_timestamp)
            self.assertEqual(destination, root / "build/patched-esp32-nimble/ble_hs.c")
            self.assertEqual(destination.read_text(), SOURCE.replace(FIX.ORIGINAL, FIX.REPAIRED, 1))
            self.assertEqual(env.paths, [str(source.parent)])
            timestamp = destination.stat().st_mtime_ns
            self.assertEqual(FIX.replace_nimble_source(env, node), destination)
            self.assertEqual(destination.stat().st_mtime_ns, timestamp)
            # Arduino's native NimBLE and unrelated source files bypass this.
            other = FakeNode(root / "framework" / Path(*FIX.SOURCE_SUFFIX))
            self.assertIs(FIX.replace_nimble_source(env, other), other)
            other = FakeNode(source.with_name("ble_gap.c"))
            self.assertIs(FIX.replace_nimble_source(env, other), other)
            for content, reason in (("name=NimBLE-Arduino\nversion=2.5.2\n", "unreviewed library"),
                                    ("name=NimBLE-Arduino\nversion=2.5.1\nversion=2.5.1\n", "malformed"),
                                    ("name=Other\nversion=2.5.1\n", "malformed")):
                metadata.write_text(content)
                with self.assertRaisesRegex(RuntimeError, reason):
                    FIX.replace_nimble_source(env, node)
            metadata.unlink()
            with self.assertRaisesRegex(RuntimeError, "missing library"):
                FIX.replace_nimble_source(env, node)

    def test_installed_pinned_source_when_available(self):
        candidates = list((ROOT / ".pio/libdeps").glob("*/NimBLE-Arduino/src/nimble/nimble/host/src/ble_hs.c"))
        if not candidates:
            self.skipTest("NimBLE-Arduino 2.5.1 dependency is not installed")
        reviewed = 0
        for source in candidates:
            if FIX.library_version(source) != "2.5.1":
                continue
            with self.subTest(source=str(source)):
                original = source.read_text()
                self.assertIn(TIMER_RESET, original)
                self.assertIn(HOST_DEINIT, original)
                repaired = FIX.patched_nimble_source(original, "2.5.1")
                self.assertNotEqual(original, repaired)
                self.assertEqual(FIX.patched_nimble_source(repaired, "2.5.1"), repaired)
                self.assertEqual(len(original.splitlines()) - len(repaired.splitlines()), 1)
                self.assertIn("    ble_npl_callout_deinit(&ble_hs_timer);", repaired)
                reviewed += 1
        self.assertGreater(reviewed, 0, "No reviewed 2.5.1 dependency found")


if __name__ == "__main__":
    unittest.main()
