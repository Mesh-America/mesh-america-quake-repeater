#!/usr/bin/env python3
"""Exercise the real release contract without invoking PlatformIO or building."""
import configparser
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(os.environ.get('MESHCORE_TEST_ROOT', Path(__file__).resolve().parents[1]))
SCRIPT = Path(os.environ.get('MESHCORE_BUILD_CONTRACT_SCRIPT', ROOT / 'build_legacy.sh'))

PROBE = r'''
set -euo pipefail
pio() { echo 'forbidden PlatformIO invocation' >&2; return 99; }
platformio() { pio "$@"; }
source "$1"
target=$2
NRF52_OTA_SENSOR_PROFILE=$3
BUILD_PROFILE_FOR_TARGET=auto
PIO_ENV_PLATFORM_BY_NAME[$target]=NRF52_PLATFORM
PIO_ENV_OTA_BY_NAME[$target]=1
PIO_ENV_FLAGS_BY_NAME=()
BUILD_CAPABILITIES=()
BUILD_EXPECTATIONS=()
BUILD_APPLICATION_EXPECTATIONS=()
BUILD_REDUCTIONS=()
PLATFORMIO_BUILD_FLAGS=''
PLATFORMIO_BUILD_UNFLAGS=''
declare_build_capability_contract "$target" NRF52_PLATFORM
apply_lora_ota_no_external_sensors_profile "$target"
printf 'EXPECT:%s\n' "${BUILD_EXPECTATIONS[@]}"
printf 'FLAGS:%s\n' "$PLATFORMIO_BUILD_FLAGS"
printf 'REDUCTION:%s\n' "${BUILD_REDUCTIONS[@]}"
'''


def contract(target, profile):
    result = subprocess.run(['bash', '-c', PROBE, 'rak-gps-contract', str(SCRIPT), target, profile],
                            cwd=ROOT, text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    fields = {'EXPECT': [], 'FLAGS': [], 'REDUCTION': []}
    for line in result.stdout.splitlines():
        prefix, sep, value = line.partition(':')
        if sep and prefix in fields:
            fields[prefix].append(value)
    return fields


class RakRs232GpsContractTest(unittest.TestCase):
    def test_serial1_both_sensor_profiles_do_not_promise_or_enable_gps(self):
        for board in ('3401', '4631'):
            target = 'RAK_' + board + '_repeater_bridge_rs232_serial1'
            config = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(';',))
            config.read(ROOT / ('variants/rak' + board + '/platformio.ini'))
            recipe = config['env:' + target]['build_flags']
            self.assertRegex(recipe, r'-D\s*WITH_RS232_BRIDGE=Serial1\b')
            self.assertIn('-UENV_INCLUDE_GPS', recipe)
            # Target-local UART ownership must override the inherited GPS
            # provider before either sensor-profile overlay is applied.
            gps_overrides = re.findall(r'-(?:D\s*ENV_INCLUDE_GPS(?:=\d+)?|U\s*ENV_INCLUDE_GPS)\b', recipe)
            self.assertTrue(gps_overrides)
            self.assertNotRegex(gps_overrides[-1], r'-D\s*ENV_INCLUDE_GPS(?:=1)?$')
            for profile in ('full', 'reduced'):
                with self.subTest(board=board, sensor_profile=profile):
                    result = contract(target, profile)
                    self.assertFalse(any(value.startswith('sensor.gps=') for value in result['EXPECT']))
                    flags = ' '.join(result['FLAGS'])
                    self.assertNotRegex(flags, r'-D\s*ENV_INCLUDE_GPS(?:=1)?(?:\s|$)')
                    for sensor in ('INA219', 'INA226', 'INA260', 'INA3221'):
                        self.assertTrue(any(value.startswith('sensor.' + sensor.lower() + '=')
                                            for value in result['EXPECT']))
                        if profile == 'reduced':
                            self.assertIn('-DENV_INCLUDE_' + sensor + '=1', flags)
                            self.assertNotIn('-UENV_INCLUDE_' + sensor, flags)
                    if profile == 'reduced':
                        self.assertIn('-UENV_INCLUDE_BME280', flags)
                        self.assertTrue(any('GPS conflicts with RS-232 on Serial1' in value
                                            for value in result['REDUCTION']))

    def test_compatible_gps_profiles_still_require_the_linked_provider(self):
        for target in ('RAK_3401_repeater', 'RAK_4631_repeater',
                       'RAK_4631_repeater_bridge_rs232_serial2'):
            for profile in ('full', 'reduced'):
                with self.subTest(target=target, sensor_profile=profile):
                    result = contract(target, profile)
                    self.assertIn('sensor.gps=meshcore.capability.rak_wisblock_gps.v1', result['EXPECT'])


if __name__ == '__main__':
    unittest.main()
