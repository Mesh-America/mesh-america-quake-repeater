#!/usr/bin/env python3
"""Offline picker packaging preserves qualified full/reduced OTA choices."""
import importlib.util
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_firmware_picker', ROOT / 'scripts/package_firmware_picker.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class PickerMarkup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def matching(self, attribute, value):
        return [(index, tag, attrs) for index, (tag, attrs) in enumerate(self.tags)
                if attrs.get(attribute) == value]

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class OfflinePickerPackageTests(unittest.TestCase):
    def assert_picker_first(self, text):
        markup = PickerMarkup(text)
        form = markup.matching('data-role', 'form')
        release = markup.matching('data-role', 'release-set')
        help_panels = markup.matching('class', 'firmware-picker-help')
        self.assertEqual(len(form), 1)
        self.assertEqual(len(release), 1)
        self.assertEqual(len(help_panels), 1)
        help_index, help_tag, help_attrs = help_panels[0]
        self.assertEqual(help_tag, 'details')
        self.assertNotIn('open', help_attrs)
        self.assertLess(form[0][0], release[0][0])
        self.assertLess(markup.matching('data-role', 'result')[0][0], help_index)
        fields = [(attrs.get('data-field'), index) for index, (_, attrs)
                  in enumerate(markup.tags) if 'data-field' in attrs]
        self.assertEqual(fields[0][0], 'hardwareFamily')
        field_positions = dict(fields)
        self.assertLess(field_positions['role'], field_positions['install'])
        self.assertTrue({'chipFamily', 'hardwareFamily', 'hardware', 'install',
                         'role', 'logging', 'firmwareProfile', 'mode'}.issubset(
                         {field for field, _ in fields}))
        for _, attrs in markup.tags:
            for described_by in attrs.get('aria-describedby', '').split():
                self.assertEqual(len(markup.matching('id', described_by)), 1)

    def test_hosted_page_starts_with_choices_not_instructions(self):
        source = (ROOT / 'docs/firmware_picker.md').read_text(encoding='utf-8')
        title_end = source.index('# Firmware picker') + len('# Firmware picker')
        picker_start = source.index('<div class="firmware-picker"')
        self.assertFalse(source[title_end:picker_start].strip())
        self.assert_picker_first(source)
        self.assertNotIn('The unified\nRAK4631 image', source)

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
        self.assert_picker_first(packaged)
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
        self.assertIn('data-share-url="https://mikecarper.github.io/MeshCore/p/"', packaged)
        self.assertIn('shortSelectionUrl', packaged)

    def test_controls_must_belong_to_the_packaged_release_family(self):
        with self.assertRaisesRegex(ValueError, 'match the supplied release family'):
            PACKAGE.package([dict(tag_name='v1.17.1.6', assets=[])],
                            dict(familyTag='v1.17.1.7', profiles={}))


if __name__ == '__main__':
    unittest.main()
