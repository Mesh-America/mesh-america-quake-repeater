"""Production crypto vs RFC vector + independent Python decoder, no AES mocks."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("management", ROOT / "tools/management/report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class ManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidates = [Path(os.environ.get("MESHCORE_CRYPTO_DIR", "/nonexistent"))]
        candidates += sorted((ROOT / ".pio/libdeps").glob("*/Crypto"))
        cls.crypto = next((p for p in candidates if (p / "AES128.cpp").is_file()), None)
        if cls.crypto is None:
            raise RuntimeError("Install rweather/Crypto 0.4.0 or set MESHCORE_CRYPTO_DIR (no mock fallback)")
        cls.work = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.work.name) / "management-test"
        sources = ["AES128.cpp", "AESCommon.cpp", "BlockCipher.cpp", "Crypto.cpp", "SHA256.cpp", "Hash.cpp"]
        host_define = [] if os.name == "nt" else ["-DHOST_BUILD"]
        sanitizers = [] if os.name == "nt" else ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        cmd = [shutil.which("g++") or "g++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra"] + host_define + [
               *sanitizers, "-I", str(cls.crypto), "-I", str(ROOT / "src"),
               str(ROOT / "src/helpers/ManagementReport.cpp"),
               str(ROOT / "test/fixtures/management/protocol_test.cpp")]
        cmd += [str(cls.crypto / p) for p in sources] + ["-o", str(cls.exe)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        result = subprocess.run([str(cls.exe)], check=True, capture_output=True, text=True)
        emitted = [bytes.fromhex(line) for line in result.stdout.splitlines()]
        cls.pages = [page for page in emitted if page[:4] == b"MGR3" and int.from_bytes(page[20:24], "little") == 42]
        cls.mgr2_pages = [page for page in emitted if page[:4] == b"MGR2"]
        cls.legacy_pages = [page for page in emitted if page[:4] == b"MGR1"]
        cls.empty_event_pages = [page for page in emitted if page[:4] == b"MGR3" and int.from_bytes(page[20:24], "little") == 43]
        # Compile the unchanged production runtime and transaction writer with
        # a memory filesystem/radio in place of the hardware-facing headers.
        fixture = ROOT / "test/fixtures/management"
        for name in ("ManagementReporter.cpp", "ManagementReporter.h", "FileRead.h", "ContactFileTransaction.h", "PersistentStoreFormat.h"):
            shutil.copyfile(ROOT / "src/helpers" / name, Path(cls.work.name) / name)
        for name in ("CommonCLI.h", "Mesh.h"):
            shutil.copyfile(fixture / name, Path(cls.work.name) / name)
        shutil.copyfile(ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h", Path(cls.work.name) / "IdentityStore.h")
        runtime = Path(cls.work.name) / "runtime-test"
        runtime_cmd = [shutil.which("g++") or "g++", "-std=c++17", "-O1", "-g"] + host_define + ["-DRP2040_PLATFORM",
                       *sanitizers, "-I", cls.work.name,
                       "-I", str(cls.crypto), "-I", str(ROOT / "src/helpers"), "-I", str(ROOT / "src"),
                       str(Path(cls.work.name) / "ManagementReporter.cpp"), str(ROOT / "src/helpers/ManagementReport.cpp"),
                       str(fixture / "runtime_test.cpp")]
        runtime_cmd += [str(cls.crypto / p) for p in sources] + ["-o", str(runtime)]
        subprocess.run(runtime_cmd, check=True, capture_output=True, text=True)
        cls.runtime = runtime

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_interoperable_full_report(self):
        decoded = report.decode_report(list(reversed(self.pages)), "management test password")
        self.assertEqual(decoded["sequence"], 42)
        self.assertEqual(len(decoded["acl"]), 36)
        self.assertEqual(decoded["firmware_version"], "1.17.1.5")
        self.assertEqual(decoded["protocol"], "MGR3")
        self.assertEqual(len(self.pages), 9)
        usb = decoded["usb_logging"]
        self.assertTrue(usb["supported"] and usb["recovery_deferred"])
        self.assertTrue(usb["host_connected"] and usb["reader_connected"])
        self.assertTrue(usb["logger_active"])
        self.assertEqual(usb["stage"], 2)
        self.assertEqual(usb["backoff_step"], 8)
        self.assertEqual(usb["retry_seconds"], 604800)
        self.assertEqual(usb["inactive_seconds"], 0xffffffff)
        self.assertTrue(usb["watchdog_auto"])
        self.assertEqual(usb["auto_connected_seconds"], 1209600)
        self.assertEqual(decoded["usb_watchdog_last"], dict(
            reasons=15, reason_names=["host-absent", "reader-absent", "tx-stalled", "client-inactive"],
            action_code=3, action="reboot-requested", persisted=True,
            epoch=1700000001, uptime_seconds=777, sequence=42))
        self.assertNotIn("manifest_id", decoded)

    def test_legacy_report_still_decodes_without_inventing_usb_status(self):
        decoded = report.decode_report(self.legacy_pages, "management test password")
        self.assertEqual(decoded["protocol"], "MGR1")
        self.assertEqual(len(decoded["acl"]), 36)
        self.assertIsNone(decoded["usb_logging"])
        self.assertIsNone(decoded["usb_watchdog_last"])
        with self.assertRaises(ValueError):
            report.decode_report([self.legacy_pages[0]] + self.pages[1:], "management test password")

    def test_mgr2_crypto_still_decodes_without_inventing_event(self):
        decoded = report.decode_report(self.mgr2_pages, "management test password")
        self.assertEqual(decoded["protocol"], "MGR2")
        self.assertEqual(len(decoded["acl"]), 36)
        self.assertEqual(len(self.mgr2_pages), 8)
        self.assertEqual(decoded["usb_logging"]["retry_seconds"], 604800)
        self.assertIsNone(decoded["usb_watchdog_last"])

    def test_current_none_event_with_empty_acl_is_authenticated(self):
        decoded = report.decode_report(self.empty_event_pages, "management test password")
        self.assertEqual(decoded["protocol"], "MGR3")
        self.assertEqual(decoded["acl"], [])
        self.assertIsNone(decoded["usb_watchdog_last"])

    def test_current_reports_decode_in_browser_with_real_production_ciphertext(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is required for cross-language management decoding")
        script = """
const assert = require('assert');
globalThis.crypto = require('crypto').webcrypto;
const decoder = require(process.argv[1]);
let data = '';
process.stdin.on('data', chunk => { data += chunk; });
process.stdin.on('end', async () => {
  try {
    const captures = JSON.parse(data);
    const pages = captures.MGR3;
    for (const magic of ['MGR1', 'MGR2']) {
      const legacy = await decoder.decodeManagement(captures[magic].join('\\n'), 'management test password');
      assert(legacy.authenticated && legacy.complete);
      assert.strictEqual(legacy.acl.length, 36);
      assert.strictEqual(legacy.public.protocol, magic);
      assert.strictEqual(legacy.pageCount, magic === 'MGR1' ? 6 : 8);
      assert.strictEqual(legacy.public.usbWatchdogLast, null);
      assert.strictEqual(legacy.public.usbLogging === null, magic === 'MGR1');
    }
    const empty = await decoder.decodeManagement(captures.empty.join('\\n'), 'management test password');
    assert(empty.authenticated && empty.complete && !empty.acl.length);
    assert.strictEqual(empty.public.protocol, 'MGR3');
    assert.strictEqual(empty.public.usbWatchdogLast, null);
    const result = await decoder.decodeManagement(pages.join('\\n'), 'management test password');
    assert(result.authenticated && result.complete);
    assert.strictEqual(result.acl.length, 36);
    assert.strictEqual(result.pageCount, 9);
    assert.strictEqual(result.public.protocol, 'MGR3');
    assert.strictEqual(result.public.usbLogging.retrySeconds, 604800);
    assert.strictEqual(result.public.usbLogging.inactiveSeconds, 0xffffffff);
    assert.strictEqual(result.public.usbLogging.hostConnected, true);
    assert.strictEqual(result.public.usbLogging.readerConnected, true);
    assert.strictEqual(result.public.usbLogging.loggerActive, true);
    assert.strictEqual(result.public.usbLogging.watchdogAuto, true);
    assert.strictEqual(result.public.usbLogging.autoConnectedSeconds, 1209600);
    assert.strictEqual(result.public.usbWatchdogLast.epoch, 1700000001);
    assert.strictEqual(result.public.usbWatchdogLast.uptimeSeconds, 777);
    assert.strictEqual(result.public.usbWatchdogLast.sequence, 42);
    assert.strictEqual(result.public.usbWatchdogLast.reasons, 15);
    assert.strictEqual(result.public.usbWatchdogLast.action, 'reboot-requested');
    assert.strictEqual(result.public.usbWatchdogLast.persisted, true);
    const raw = pages.map(page => '1900' + page + '00'.repeat((3 + Math.ceil((page.length / 2 - 3) / 16) * 16) - page.length / 2));
    const routed = await decoder.decodeManagement(raw.join('\\n'), 'management test password');
    assert(routed.authenticated && routed.complete);
    assert.strictEqual(routed.public.envelope.route, 'flood');
    const mutated = Buffer.from(pages[0], 'hex'); mutated[87] ^= 1;
    await assert.rejects(decoder.decodeManagement(mutated.toString('hex'), 'management test password'), /Password is wrong/);
    const changedLogger = Buffer.from(pages[0], 'hex'); changedLogger[84] ^= 4;
    await assert.rejects(decoder.decodeManagement(changedLogger.toString('hex'), 'management test password'), /Password is wrong/);
    for (let offset = 98; offset < 111; ++offset) {
      const changedEvent = Buffer.from(pages[0], 'hex'); changedEvent[offset] ^= 1;
      await assert.rejects(decoder.decodeManagement(changedEvent.toString('hex'), 'management test password'), /Password is wrong|Invalid/);
    }
    const changedSnapshot = Buffer.from(pages[1], 'hex'); changedSnapshot[99] ^= 1;
    await assert.rejects(decoder.decodeManagement(pages[0] + '\\n' + changedSnapshot.toString('hex'), ''), /same snapshot/);
  } catch (error) { console.error(error); process.exitCode = 1; }
});
"""
        import json
        subprocess.run([node, "-e", script, str(ROOT / "docs/_javascript/management_decoder.js")],
                       input=json.dumps({"MGR3": [page.hex() for page in self.pages],
                                         "MGR2": [page.hex() for page in self.mgr2_pages],
                                         "MGR1": [page.hex() for page in self.legacy_pages],
                                         "empty": [page.hex() for page in self.empty_event_pages]}),
                       text=True, check=True, timeout=30)

    def test_runtime_storage_scheduling_rollover_and_failures(self):
        subprocess.run([str(self.runtime)], check=True)

    def test_tampering_and_wrong_password(self):
        for position in (4, 20, 28, 74, 76, 83, 85, 86, 90, 94, *range(98, 111), 111, -1):
            changed = bytearray(self.pages[0]); changed[position] ^= 1
            with self.subTest(position=position), self.assertRaises(ValueError):
                report.decode_report([bytes(changed)] + self.pages[1:], "management test password")
        with self.assertRaises(ValueError):
            report.decode_report(self.pages, "incorrect management password")

    def test_logger_activity_is_authenticated_separately_from_connection(self):
        changed = bytearray(self.pages[0]); changed[84] ^= 4
        public = report._usb_status(changed)
        self.assertTrue(public["host_connected"] and public["reader_connected"])
        self.assertFalse(public["logger_active"])
        with self.assertRaises(ValueError):
            report.decode_page(bytes(changed), "management test password")

    def test_page_omission_duplicate_mixed(self):
        for pages in ([], self.pages[:-1], self.pages[1:] + [self.pages[1]], self.pages + [self.pages[0]]):
            with self.assertRaises(ValueError):
                report.decode_report(pages, "management test password")

    def test_current_size_page_bounds_and_unknown_version_are_rejected(self):
        for offset, value in ((3, ord("4")), (79, 8), (81, 6), (82, 5), (80, 37), (84, 8), (85, 0xc0)):
            changed = bytearray(self.pages[0]); changed[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                report.decode_page(bytes(changed), "management test password")
        for payload in (self.pages[0][:-1], self.pages[0] + b"\x00", self.pages[0][:99]):
            with self.assertRaises(ValueError):
                report.decode_page(payload, "management test password")

    def test_event_validation_and_advisory_zero_time(self):
        for code in (0x80, 0x8f, 0xdf, 0xef, 0xff):
            changed = bytearray(self.pages[0]); changed[98] = code
            with self.subTest(code=code), self.assertRaises(ValueError):
                report.decode_page(bytes(changed), "management test password")
        changed = bytearray(self.pages[0]); changed[107:111] = bytes(4)
        with self.assertRaises(ValueError):
            report.decode_page(bytes(changed), "management test password")
        changed = bytearray(self.pages[0]); changed[99:103] = bytes(4)
        self.assertEqual(report._watchdog_event(changed)["epoch"], 0)
        for action in range(1, 5):
            changed[98] = 15 | (action << 4)
            event = report._watchdog_event(changed)
            self.assertEqual(event["action_code"], action)
            self.assertFalse(event["persisted"])

    def test_authenticated_event_mismatch_is_not_one_snapshot(self):
        from Crypto.Cipher import AES
        page = self.pages[1]
        key = report.derive(report.password_key("management test password"), "MeshCore-MGR1-SIV", page[4:20])
        cipher = AES.new(key, AES.MODE_SIV); cipher.update(page[:111])
        private = cipher.decrypt_and_verify(page[111:-16], page[-16:])
        header = bytearray(page[:111]); header[99] ^= 1
        cipher = AES.new(key, AES.MODE_SIV); cipher.update(header)
        ciphertext, tag = cipher.encrypt_and_digest(private)
        changed = bytes(header) + ciphertext + tag
        self.assertEqual(report.decode_page(changed, "management test password"),
                         report.decode_page(page, "management test password"))
        with self.assertRaisesRegex(ValueError, "mixed report snapshots"):
            report.decode_report([self.pages[0], changed] + self.pages[2:], "management test password")

    def test_fingerprints_and_password_length(self):
        a = report.fingerprint("management test password", bytes(16), bytes(32))
        b = report.fingerprint("management test password", bytes([1]) + bytes(15), bytes(32))
        self.assertEqual(len(a), 12); self.assertNotEqual(a, b)
        for password in ("short", "x" * 97):
            with self.assertRaises(ValueError): report.password_key(password)

    def test_companions_excluded(self):
        for role in ("simple_repeater/MyMesh", "simple_room_server/MyMesh", "simple_sensor/SensorMesh"):
            self.assertIn("_cli.beginManagement(*this, _fs)", (ROOT / "examples" / (role + ".cpp")).read_text())
        for path in (ROOT / "examples/companion_radio").glob("*.*"):
            if path.suffix in (".cpp", ".h"): self.assertNotIn("beginManagement", path.read_text())

    def test_mqtt_paths_scopes_and_duplicate_uplinks(self):
        messages = []
        for route in range(4):
            for page in self.pages:
                wire = bytes([0x3c | route]) + (bytes(4) if route in (0, 3) else b"")
                wire += bytes([0x42]) + bytes.fromhex("1234abcd") + page
                message = dict(type="PACKET", direction="rx", raw=wire.hex())
                self.assertEqual(report.mqtt_payload(message), page)
                messages.extend([message, message])
        decoded = report.mqtt_reports(messages, "management test password")
        self.assertEqual(len(decoded), 1)
        self.assertEqual(len(decoded[0]["acl"]), 36)
        self.assertIsNone(report.mqtt_payload(dict(type="PACKET", direction="tx", raw=wire.hex())))
        self.assertIsNone(report.mqtt_payload(dict(type="PACKET", direction="rx", raw="3dc0")))
        self.assertEqual(report.mqtt_reports(messages[:2], "management test password"), [])
        for page in self.pages:
            padded = page + bytes(3 + ((len(page) - 3 + 15) // 16) * 16 - len(page))
            message = dict(type="PACKET", direction="rx", raw=(b"\x19\x00" + padded).hex())
            self.assertEqual(report.mqtt_payload(message), page)
            malformed = padded[:-1] + b"\x01" if len(padded) > len(page) else padded + b"\x00"
            message["raw"] = (b"\x19\x00" + malformed).hex()
            self.assertIsNone(report.mqtt_payload(message))


if __name__ == "__main__": unittest.main()
