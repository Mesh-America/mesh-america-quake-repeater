#!/usr/bin/env python3
"""The ordinary release has one ESP32 Full OTA identity per board and role."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_local_release import select_ordinary_full_records


def record(target: str, profile: str = "full", platform: str = "ESP32_PLATFORM") -> dict:
    return {"manifest": {"target": target, "build_profile": profile, "platform": platform},
            "files": []}


class ReleaseFullSelectionTest(unittest.TestCase):
    def test_meshtower_sd_primary_filters_stale_internal_images_without_relabeling(self):
        primary = "Heltec_tower_v2_sdcard_repeater_lora_ota_no_external_sensors"
        variants = []
        for sensor in ("full", "reduced"):
            item = record(primary, "auto", "NRF52_PLATFORM")
            item["manifest"].update(artifact_target=primary + "-" + sensor + "-ota",
                                    capabilities=["sensor.profile." + sensor])
            variants.append(item)
        companion = record("Heltec_tower_v2_companion_radio_full", platform="NRF52_PLATFORM")
        room = record("Heltec_tower_v2_room_server_lora_ota_no_external_sensors",
                      platform="NRF52_PLATFORM")
        legacy = [record(target, "auto", "NRF52_PLATFORM") for target in (
            "Heltec_tower_v2_repeater",
            "Heltec_tower_v2_repeater_lora_ota_no_external_sensors",
        )]
        selected = select_ordinary_full_records(legacy + variants + [companion, room])
        self.assertEqual(selected, variants + [companion, room])
        for before, after in zip(variants, selected):
            self.assertIs(before, after)
            self.assertEqual(after["manifest"]["target"], primary)

    def test_meshtower_internal_images_cannot_substitute_for_missing_primary(self):
        for target in ("Heltec_tower_v2_repeater",
                       "Heltec_tower_v2_repeater_lora_ota_no_external_sensors"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "requires the SD primary"):
                    select_ordinary_full_records([record(target, "auto", "NRF52_PLATFORM")])

    def test_nrf52_full_and_reduced_ota_pair_is_never_collapsed(self):
        for role in ('repeater', 'room_server', 'sensor'):
            target = 'RAK_3401_' + role
            variants = []
            for sensor in ('full', 'reduced'):
                item = record(target, 'auto', 'NRF52_PLATFORM')
                item['manifest'].update(artifact_target=target + '-' + sensor + '-ota',
                                        capabilities=['sensor.profile.' + sensor])
                variants.append(item)
            self.assertEqual(select_ordinary_full_records(variants), variants)

    def test_resume_filters_sibling_full_images_only(self):
        inputs = [
            record("Heltec_v3_repeater_observer_mqtt"),
            record("Heltec_v3_repeater_bridge_espnow"),
            record("Heltec_v3_repeater"),
            record("Heltec_v3_repeater", "standard"),
            record("Heltec_v3_room_server"),
            record("Station_G2_repeater"),
            record("Station_G2_repeater_observer_mqtt"),
            record("Tbeam_SX1262_repeater_bridge_espnow"),
            record("Tbeam_SX1262_repeater_observer_mqtt"),
            record("LilyGo_TLora_V2_1_1_6_repeater"),
            record("LilyGo_TLora_V2_1_1_6_repeater_observer_mqtt_"),
            record("Meshadventurer_sx1262_repeater"),
            record("Meshadventurer_sx1262_repeater_bridge_espnow"),
            record("RAK_4631_repeater", platform="NRF52_PLATFORM"),
        ]
        selected = select_ordinary_full_records(inputs)
        self.assertEqual({item["manifest"]["target"] for item in selected}, {
            "Heltec_v3_repeater", "Heltec_v3_room_server",
            "Station_G2_repeater_observer_mqtt",
            "Tbeam_SX1262_repeater_observer_mqtt",
            "LilyGo_TLora_V2_1_1_6_repeater_observer_mqtt_",
            "Meshadventurer_sx1262_repeater_bridge_espnow",
            "RAK_4631_repeater",
        })
        self.assertEqual(len(selected), 8)  # standard V3 remains alongside Full V3


if __name__ == "__main__":
    unittest.main()
