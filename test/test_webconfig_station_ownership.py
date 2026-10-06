"""Exercise production portal ownership and failed-join recovery without a radio."""
from pathlib import Path
import re
import unittest

from test_replay_reset_integration import extract_braced
import test_wifi_ota_start as wifi_start

ROOT = Path(__file__).resolve().parents[1]


class WebConfigStationOwnershipTest(unittest.TestCase):
    compile_and_run = wifi_start.WiFiOtaStartTest.compile_and_run

    def test_infrastructure_uses_actual_mqtt_worker_and_refreshes_ownership(self):
        fixture = (ROOT / "test/fixtures/webconfig_station_owner.cpp").read_text()
        for role, worker in (("simple_repeater", "mqtt_bridge"),
                             ("simple_room_server", "bridge")):
            with self.subTest(role=role):
                source = (ROOT / "examples" / role / "MyMesh.cpp").read_text()
                start = extract_braced(source, "bool MyMesh::startWebConfig(")
                start += "\n" + extract_braced(source, "bool MyMesh::startWebConfigImpl(")
                tick = source.index("_webconfig->tick(millis());")
                refresh_start = source.rfind("#ifdef WITH_MQTT_BRIDGE", 0, tick)
                refresh_end = source.index("#endif", refresh_start) + len("#endif")
                self.assertLess(refresh_end, tick)
                self.assertFalse(source[refresh_end:tick].strip())
                refresh = source[refresh_start:refresh_end]
                self.assertIn("_webconfig->updateWiFiOwnership(", refresh)
                body = fixture.replace("@WORKER@", worker).replace("@START@", start)
                body = body.replace("@SUSPEND@", extract_braced(source,
                    "void MyMesh::suspendUnconfiguredSetupBridges()"))
                body = body.replace("@REFRESH@", refresh)
                self.compile_and_run(body, "-DWITH_MQTT_BRIDGE=1")
                # A stopped/unconfigured MQTT implementation used to keep
                # ownership forever merely because its code was compiled in.
                stale = re.sub(r"owns_wifi = !.*?;", "owns_wifi = false;", body,
                               count=1, flags=re.DOTALL)
                self.assertNotEqual(body, stale)
                with self.assertRaises(AssertionError):
                    self.compile_and_run(stale, "-DWITH_MQTT_BRIDGE=1")

    def station_fixture(self):
        source = (ROOT / "src/helpers/esp32/WebConfigServer.cpp").read_text()
        header = (ROOT / "src/helpers/esp32/WebConfigServer.h").read_text()
        fixture = (ROOT / "test/fixtures/webconfig_station_recovery.cpp").read_text()
        constructor = extract_braced(source, "WebConfigServer::WebConfigServer(")
        start = extract_braced(source, "bool WebConfigServer::startAutoMode(")
        attempt = extract_braced(source, "bool WebConfigServer::beginSavedStation(")
        setter = extract_braced(header, "void updateWiFiOwnership(")
        tick = extract_braced(source, "void WebConfigServer::tick(")
        # Execute the complete production join/fallback/retry/promotion blocks.
        # HTTP batching, display, and settings routes below them are irrelevant.
        begin = tick.index("  if (_mode == MODE_OFF) return;")
        end = tick.index("  if (_dns) _dns->processNextRequest();")
        recovery = "void WebConfigServer::tick(uint32_t now) {\n" + tick[begin:end] + "\n}"
        batch_start = source.index('      if (_standalone_wifi && strcmp(e.key, "wifi.ssid")')
        batch_end = source.index("      _cb->execCommand(e.cmd, e.reply);", batch_start)
        batch = source[batch_start:batch_end]
        capability = re.search(r'  doc\["wifi_psk64"\] = .*?;', source).group(0)
        return (fixture.replace("@CONSTRUCTOR@", constructor).replace("@START@", start)
                .replace("@SETTER@", setter).replace("@RECOVERY@", recovery)
                .replace("@ATTEMPT@", attempt).replace("@CREDENTIAL_BATCH@", batch)
                .replace("@PSK_CAPABILITY@", capability))

    def test_failed_boot_join_retries_saved_credentials_with_no_mqtt_owner(self):
        self.compile_and_run(self.station_fixture(), "-DWITH_MQTT_BRIDGE=1")

    def test_external_owner_excluded_and_runtime_ownership_can_transfer(self):
        self.compile_and_run(self.station_fixture(), "-DWITH_MQTT_BRIDGE=1",
                             "-DTEST_EXTERNAL_OWNER=1")

    def test_canonical_raw_psk_wins_and_legacy_mqtt_credentials_still_load(self):
        fixture = self.station_fixture()
        self.compile_and_run(fixture, "-DWITH_MQTT_BRIDGE=1",
                             "-DTEST_CREDENTIAL_PRIORITY=1")
        for old in (
                fixture.replace('doc["wifi_psk64"] = _standalone_wifi;',
                                'doc["wifi_psk64"] = (_mqtt_prefs == nullptr || !_owns_wifi);'),
                fixture.replace('_standalone_wifi && strcmp(e.key,',
                                '(_mqtt_prefs == nullptr || !_owns_wifi) && strcmp(e.key,')):
            self.assertNotEqual(old, fixture)
            with self.assertRaises(AssertionError):
                self.compile_and_run(old, "-DWITH_MQTT_BRIDGE=1",
                                     "-DTEST_CREDENTIAL_PRIORITY=1")

    def test_non_mqtt_portal_retains_saved_station_recovery(self):
        self.compile_and_run(self.station_fixture())

    def test_manual_companion_start_preserves_legacy_join_and_15s_fallback(self):
        self.compile_and_run(self.station_fixture(), "-DWITH_MQTT_BRIDGE=1",
                             "-DTEST_LEGACY_COMPANION=1")


if __name__ == "__main__":
    unittest.main()
