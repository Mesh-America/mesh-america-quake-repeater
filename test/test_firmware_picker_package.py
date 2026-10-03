#!/usr/bin/env python3
"""Offline picker packaging preserves qualified full/reduced OTA choices."""
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_firmware_picker', ROOT / 'scripts/package_firmware_picker.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class OfflinePickerPackageTests(unittest.TestCase):
    def test_sensor_policy_pairs_and_individual_downloads_are_retained(self):
        source = 'a' * 40
        family = 'v1.17.1.7-dev-aaaaaaaa'
        logical = 'RAK_3401_repeater_lora_ota_no_external_sensors'
        controls = dict(familyTag=family, source=source, profiles={})
        assets = []
        for policy in ('full', 'reduced'):
            target = logical + '-' + policy
            controls['profiles'][target] = dict(platform='NRF52_PLATFORM', otaRole='lora-receiver',
                updateMethods=['lora'], sensorProfile=policy, sensorProfileSource=source)
            for extension in ('.zip', '.uf2'):
                name = target + '-ota-' + family + extension
                assets.append(dict(name=name, size=100,
                    browser_download_url='https://github.com/mikecarper/MeshCore/releases/download/' + family + '/' + name,
                    uploader={'token': 'not part of the picker'}))
        releases = [dict(name=family, tag_name=family, assets=assets, authorization='private')]
        packaged = PACKAGE.package(releases, controls)
        match = re.search(r'<script type="application/json" id="firmware-picker-data">(.*?)</script>', packaged)
        embedded = json.loads(match[1])
        self.assertEqual(embedded['controls'], controls)
        self.assertEqual(len(embedded['releases'][0]['assets']), 4)
        self.assertEqual({asset['name'] for asset in embedded['releases'][0]['assets']},
                         {asset['name'] for asset in assets})
        self.assertNotIn('authorization', embedded['releases'][0])
        self.assertTrue(all('uploader' not in asset for asset in embedded['releases'][0]['assets']))
        self.assertIn('Full supported sensors', packaged)
        self.assertIn('Reduced sensors', packaged)

    def test_controls_must_belong_to_the_packaged_release_family(self):
        with self.assertRaisesRegex(ValueError, 'match the supplied release family'):
            PACKAGE.package([dict(tag_name='v1.17.1.6', assets=[])],
                            dict(familyTag='v1.17.1.7', profiles={}))


if __name__ == '__main__':
    unittest.main()
