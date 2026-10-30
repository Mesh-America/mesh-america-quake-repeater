#!/usr/bin/env python3
"""Run the embedded bridge's real geometry and bootloader identity policy."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
STUBS = ROOT / 'tools/mota/tests/migration_stubs'

HARNESS = r'''
#include <array>
#include <cassert>
#include <cstring>
#include "helpers/ota/BootloaderMigrationPolicy.h"
using namespace mesh::ota;
using namespace mesh::ota::migration;
static void wr16(uint8_t *p, uint16_t n) { p[0]=n; p[1]=n>>8; }
static void wr32(uint8_t *p, uint32_t n) { wr16(p,n); wr16(p+2,n>>16); }
static OtaBootloaderIdentity identity(uint32_t version, uint32_t base=0x26000, uint16_t fwid=0xB6) {
  std::array<uint8_t, BOOT_SIZE> bytes;
  bytes.fill(0xFF);
  uint8_t *p=bytes.data()+OTA_BOOT_CANDIDATE_MANIFEST_OFFSET;
  wr32(p,OTA_BOOT_MANIFEST_MAGIC0); wr32(p+4,OTA_BOOT_MANIFEST_MAGIC1);
  wr16(p+8,1); wr16(p+10,44); wr32(p+12,BOOT_BASE); wr32(p+16,BOOT_SIZE);
  wr32(p+20,0x239A0029); std::memset(p+24,0,16); std::memcpy(p+24,"4631_DFU",8);
  wr32(p+44,OTA_BOOT_CONTINUITY_MAGIC0); wr32(p+48,OTA_BOOT_CONTINUITY_MAGIC1);
  wr16(p+52,2); wr16(p+54,32); wr32(p+56,version); wr16(p+60,140);
  wr16(p+62,fwid); wr32(p+64,base); wr16(p+68,1); wr16(p+70,0); wr32(p+72,0);
  wr32(p+40,ota_boot_image_crc32(bytes.data(),bytes.size(),OTA_BOOT_CANDIDATE_MANIFEST_OFFSET+40));
  OtaBootloaderIdentity out;
  assert(ota_bootloader_candidate_identity_from_image(bytes.data(),bytes.size(),out));
  bytes[10]^=1;
  OtaBootloaderIdentity corrupt;
  assert(!ota_bootloader_candidate_identity_from_image(bytes.data(),bytes.size(),corrupt));
  return out;
}
static Snapshot good() {
  Snapshot s{};
  s.part=0x52840; s.flash_page_size=4096; s.flash_pages=256;
  s.app_base=0x26000; s.app_ceiling=0xED000;
  s.softdevice_size=s.app_base; s.softdevice_fwid=s.expected_softdevice_fwid=0xB6;
  s.mbr_boot_override=s.mbr_params_override=UINT32_MAX;
  s.uicr_boot=BOOT_BASE; s.uicr_params=PARAMS_BASE;
  s.source=0xA0000; s.source_size=BOOT_SIZE; s.app_body_size=0x90000;
  s.app_image_size=s.app_body_size+ENDF_LEN;
  return s;
}
static std::array<uint8_t, BOOT_SIZE> labelled(const char *text, size_t offset=100) {
  std::array<uint8_t, BOOT_SIZE> bytes;
  bytes.fill(0xFF);
  assert(offset + std::strlen(text) + 1 <= bytes.size());
  std::memcpy(bytes.data() + offset, text, std::strlen(text) + 1);
  return bytes;
}
static InstalledVariant variant(const std::array<uint8_t, BOOT_SIZE> &image,
                                uint32_t version=0x02040CFF) {
  return installed_variant(image.data(), image.size(), version);
}
int main(int argc,char **argv) {
  assert(argc==2);
  if (!std::strcmp(argv[1],"normal-labels")) {
    assert(variant(labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.12\r\nModel: test\r\n")) == InstalledVariant::Normal);
    assert(variant(labelled("UF2 Bootloader 0.11.0-OTAFIX2.4.12\r\n")) == InstalledVariant::Normal);
    assert(variant(labelled("UF2 Bootloader BL_0x02040CFF\r\n")) == InstalledVariant::Normal);
    assert(variant(labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.11\r\n"),0x02040BFF) == InstalledVariant::Normal);
    assert(variant(labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.12-preview.16\r\n"),0x02040C10) == InstalledVariant::Normal);
    assert(variant(labelled("UF2 Bootloader BL_0x02040C10\r\n"),0x02040C10) == InstalledVariant::Normal);
    assert(variant(labelled("UF2 Bootloader v0.11.0-OTAFIX255.255.254-preview.254\r\n"),0xFFFFFEFE) == InstalledVariant::Normal);
  } else if (!std::strcmp(argv[1],"recovery-labels")) {
    for (const char *text: {"R_0x02040CFF", "UF2 Bootloader R_0x02040CFF\r\n",
                           "UF2 Bootloader R_v0.11.0-OTAFIX2.4.12\r\n",
                           "0.11.0-OTAFIX2.4.7-preview.2-recovery-allow-all s140 6.1.1"}) {
      auto bytes=labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.12\r\n");
      std::memcpy(bytes.data()+500,text,std::strlen(text)+1);
      assert(variant(bytes)==InstalledVariant::Recovery); // Recovery wins over a normal decoy.
      assert(variant(labelled(text))==InstalledVariant::Recovery);
    }
    // Historical compact recovery images have neither version label nor flag.
    assert(variant(labelled(""))==InstalledVariant::Unknown);
    auto bytes=labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.12\r\n");
    std::memcpy(bytes.data()+BOOT_SIZE-4,"R_0x",4);
    assert(variant(bytes)==InstalledVariant::Recovery);
  } else if (!std::strcmp(argv[1],"unknown-labels")) {
    for (const char *text: {"", "v0.11.0-OTAFIX2.4.12", "UF2 Bootloader ",
                           "UF2 Bootloader v0.11.0-OTAFIX2.4.11\r\n",
                           "UF2 Bootloader v0.11.0-OTAFIX2.4.12-preview.1\r\n",
                           "UF2 Bootloader v0.11.0-OTAFIX2.4.12-dirty\r\n",
                           "UF2 Bootloader v0.11.0-OTAFIX2.4.12\n",
                           "UF2 Bootloader v0.11.0-OTAFIX2.4.12",
                           "UF2 Bootloader vBL_0x02040CFF\r\n",
                           "UF2 Bootloader BL_0x02040DFF\r\n"})
      assert(variant(labelled(text))==InstalledVariant::Unknown);
    auto bytes=labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.12\r\n");
    assert(installed_variant(nullptr,BOOT_SIZE,0x02040CFF)==InstalledVariant::Unknown);
    assert(installed_variant(bytes.data(),BOOT_SIZE-1,0x02040CFF)==InstalledVariant::Unknown);
    assert(variant(bytes,0)==InstalledVariant::Unknown);
    assert(variant(bytes,UINT32_MAX)==InstalledVariant::Unknown);
    assert(variant(bytes,0x02040C00)==InstalledVariant::Unknown);
    const char *duplicate="UF2 Bootloader BL_0x02040CFF\r\n";
    std::memcpy(bytes.data()+500,duplicate,std::strlen(duplicate)+1);
    assert(variant(bytes)==InstalledVariant::Unknown);
    bytes=labelled("UF2 Bootloader v0.11.0-OTAFIX2.4.12\r\n");
    const char *conflict="UF2 Bootloader v0.11.0-OTAFIX2.4.11\r\n";
    std::memcpy(bytes.data()+500,conflict,std::strlen(conflict)+1);
    assert(variant(bytes)==InstalledVariant::Unknown);
    for (size_t tail=1;tail<40;++tail) {
      bytes.fill(0xFF);
      const char *label="UF2 Bootloader v0.11.0-OTAFIX2.4.12\r\n";
      size_t count=std::strlen(label);
      if (tail>=count) continue;
      std::memcpy(bytes.data()+BOOT_SIZE-tail,label,tail);
      assert(variant(bytes)==InstalledVariant::Unknown);
    }
  } else if (!std::strcmp(argv[1],"geometry")) {
    assert(preflight(good())==Gate::Ok);
    Snapshot s=good(); s.part=0x52833; assert(preflight(s)==Gate::Chip);
    s=good(); s.flash_page_size=2048; assert(preflight(s)==Gate::Chip);
    s=good(); s.flash_pages=512; assert(preflight(s)==Gate::Chip);
    s=good(); s.app_base=s.softdevice_size=0x27000;
    s.softdevice_fwid=s.expected_softdevice_fwid=0x123; assert(preflight(s)==Gate::Ok);
    s.expected_softdevice_fwid=0xB6; assert(preflight(s)==Gate::Softdevice);
    s=good(); s.softdevice_size=0x27000; assert(preflight(s)==Gate::Softdevice);
    s=good(); s.app_ceiling=0xEE000; assert(preflight(s)==Gate::Softdevice);
    s=good(); s.app_ceiling=s.app_base; assert(preflight(s)==Gate::Softdevice);
    s=good(); s.uicr_boot=0xF0000; assert(preflight(s)==Gate::BootAddress);
    s=good(); s.mbr_boot_override=BOOT_BASE; s.uicr_boot=0; assert(preflight(s)==Gate::Ok);
    s=good(); s.mbr_boot_override=0xF0000; assert(preflight(s)==Gate::BootAddress);
    s=good(); s.uicr_params=UINT32_MAX; assert(preflight(s)==Gate::ParamsAddress);
    s=good(); s.mbr_params_override=SETTINGS_BASE; assert(preflight(s)==Gate::ParamsAddress);
    const uint32_t bad[]={0,0x1000,0x25FFC,0xED000,BOOT_BASE,PARAMS_BASE,0x20000000,UINT32_MAX-3};
    for (uint32_t address:bad) { s=good(); s.source=address; assert(preflight(s)==Gate::Source); }
    s=good(); ++s.source; assert(preflight(s)==Gate::Source);
    s=good(); --s.source_size; assert(preflight(s)==Gate::Source);
    s=good(); s.app_body_size=s.source-s.app_base+BOOT_SIZE-1; assert(preflight(s)==Gate::Source);
    s=good(); s.app_body_size=s.app_ceiling-s.app_base+1; assert(preflight(s)==Gate::Source);
    s=good(); s.app_body_size=s.app_ceiling-s.app_base; s.app_image_size=s.app_body_size+ENDF_LEN;
    assert(preflight(s)==Gate::Source); // EndF must fit as well as the body.
    s=good(); --s.app_image_size; assert(preflight(s)==Gate::Source);
    s=good(); s.app_ceiling=0xD4000; s.app_body_size=0xAF000; assert(preflight(s)==Gate::Source);
  } else if (!std::strcmp(argv[1],"acl")) {
    for (unsigned slot=0;slot<8;++slot) {
      for (uint32_t address=BOOT_BASE;address<SETTINGS_BASE;address+=4096) {
        for (uint32_t permission:{2u,4u,6u}) {
          Snapshot s=good(); s.acl[slot]={address,4096,permission};
          assert(preflight(s)==Gate::Protection);
        }
      }
      Snapshot s=good(); s.acl[slot]={s.source,4096,4}; assert(preflight(s)==Gate::Protection);
      s.acl[slot].permissions=2; assert(preflight(s)==Gate::Ok);
      s.acl[slot]={SETTINGS_BASE,4096,2}; assert(preflight(s)==Gate::Ok);
      s.acl[slot]={UINT32_MAX-4095,0x10000,6}; assert(preflight(s)==Gate::Ok);
    }
  } else {
    const char name[16]="4631_DFU";
    auto candidate=identity(0x02040CFF), installed=identity(0x02040BFF);
    assert(candidate_matches_resource(candidate,0x239A0029,name,0x02040CFF,0x26000,0xB6));
    auto bad=candidate; bad.manifest_offset-=4;
    assert(!candidate_matches_resource(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
    assert(!candidate_matches_resource(candidate,0x239A0071,name,0x02040CFF,0x26000,0xB6));
    assert(!candidate_matches_resource(candidate,0x239A0029,name,0x02040C90,0x26000,0xB6));
    assert(!candidate_matches_resource(candidate,0x239A0029,name,0x02040CFF,0x27000,0x123));
    auto v7=identity(0x02040CFF,0x27000,0x123);
    assert(candidate_matches_resource(v7,0x239A0029,name,0x02040CFF,0x27000,0x123));
    assert(installed_can_migrate(installed,candidate,false,false,0x26000,0xB6));
    if (!std::strcmp(argv[1],"up-to-date")) {
      assert(installed_matches_resource(installed,0x239A0029,name,0x26000,0xB6));
      assert(!installed_up_to_date(installed,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      installed.boot_version=0x02040CFE; // Preview precedes the stable release.
      assert(!installed_up_to_date(installed,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      installed.boot_version=0x02040CFF;
      assert(installed_up_to_date(installed,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      installed.boot_version=0x02040D01; // Even a later preview must not be downgraded.
      assert(installed_up_to_date(installed,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.present=false;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.crc_ok=false;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.board_id^=1;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.device_name[0]='X';
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.image_start+=4096;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; --bad.image_size;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.continuity_present=false;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.softdevice_family=132;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.softdevice_fwid=0x123;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.app_base=0x27000;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.layout_abi=2;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.compat_flags=1;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.boot_version=0;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
      bad=installed; bad.boot_version=UINT32_MAX;
      assert(!installed_up_to_date(bad,0x239A0029,name,0x02040CFF,0x26000,0xB6));
    } else if (!std::strcmp(argv[1],"monotonic")) {
      installed.boot_version=candidate.boot_version;
      assert(!installed_can_migrate(installed,candidate,true,true,0x26000,0xB6));
      ++installed.boot_version;
      assert(!installed_can_migrate(installed,candidate,true,true,0x26000,0xB6));
    } else if (!std::strcmp(argv[1],"identity")) {
      bad=installed; bad.board_id^=1;
      assert(!installed_can_migrate(bad,candidate,true,true,0x26000,0xB6));
      bad=installed; bad.device_name[0]='X';
      assert(!installed_can_migrate(bad,candidate,true,true,0x26000,0xB6));
      bad=installed; bad.crc_ok=false;
      assert(!installed_can_migrate(bad,candidate,true,true,0x26000,0xB6));
      bad=installed; bad.softdevice_fwid=0x123;
      assert(!installed_can_migrate(bad,candidate,true,true,0x26000,0xB6));
      bad=installed; bad.continuity_present=false;
      assert(!installed_can_migrate(bad,candidate,true,true,0x26000,0xB6));
    } else {
      OtaBootloaderIdentity absent;
      assert(installed_can_migrate(absent,candidate,true,true,0x26000,0xB6));
      assert(!installed_can_migrate(absent,candidate,false,true,0x26000,0xB6));
      assert(!installed_can_migrate(absent,candidate,true,false,0x26000,0xB6));
      assert(!installed_can_migrate(absent,candidate,false,false,0x26000,0xB6));
    }
  }
}
'''


class MigrationPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='migration-policy-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = cls.compile(Path(cls.directory.name), HARNESS)

    @staticmethod
    def compile(directory, harness, include=None):
        source, binary = directory / 'policy.cpp', directory / 'policy'
        source.write_text(harness)
        command = [os.environ.get('CXX', 'g++'), '-std=c++17', '-O1', '-Wall', '-Wextra',
                   '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-pie', '-no-pie']
        if include:
            command += ['-I', str(include)]
        command += ['-I', str(STUBS), '-I', str(ROOT / 'src'), str(source), '-o', str(binary)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return binary

    def scenario(self, name):
        subprocess.run([str(self.binary), name], check=True)

    def test_actual_v6_v7_geometry_and_linked_source_bounds(self):
        self.scenario('geometry')

    def test_automatic_variant_recognizes_complete_normal_release_labels(self):
        self.scenario('normal-labels')

    def test_recovery_markers_override_normal_labels_and_missing_text_fails_closed(self):
        self.scenario('recovery-labels')

    def test_automatic_variant_rejects_unknown_ambiguous_or_truncated_labels(self):
        self.scenario('unknown-labels')

    def test_all_acl_slots_protect_source_bootloader_and_parameter_page(self):
        self.scenario('acl')

    def test_modern_loader_requires_strictly_newer_candidate(self):
        self.scenario('monotonic')

    def test_installed_version_noop_requires_exact_identity_and_platform(self):
        self.scenario('up-to-date')

    def test_crc_exact_identity_and_runtime_platform(self):
        self.scenario('identity')

    def test_manifestless_loader_requires_explicit_exact_legacy_hash(self):
        self.scenario('legacy')

    def test_negative_control_cannot_remove_installed_identity_check(self):
        original = (ROOT / 'src/helpers/ota/BootloaderMigrationPolicy.h').read_text()
        changed = original.replace('ota_bootloader_identity_matches(installed, candidate) &&', '')
        self.assertNotEqual(original, changed)
        with tempfile.TemporaryDirectory(prefix='migration-negative-') as directory:
            directory = Path(directory)
            header = directory / 'helpers/ota/BootloaderMigrationPolicy.h'
            header.parent.mkdir(parents=True)
            header.write_text(changed.replace('#include "OtaBootloaderUpdate.h"',
                                               '#include "helpers/ota/OtaBootloaderUpdate.h"'))
            binary = self.compile(directory, HARNESS, directory)
            result = subprocess.run([str(binary), 'identity'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Assertion', result.stderr)

    def test_negative_control_cannot_ignore_recovery_version_marker(self):
        original = (ROOT / 'src/helpers/ota/BootloaderMigrationPolicy.h').read_text()
        changed = original.replace(
            'boot_text_matches(image + i, left, recovery, sizeof(recovery) - 1)', 'false')
        self.assertNotEqual(original, changed)
        with tempfile.TemporaryDirectory(prefix='migration-recovery-negative-') as directory:
            directory = Path(directory)
            header = directory / 'helpers/ota/BootloaderMigrationPolicy.h'
            header.parent.mkdir(parents=True)
            header.write_text(changed.replace('#include "OtaBootloaderUpdate.h"',
                                               '#include "helpers/ota/OtaBootloaderUpdate.h"'))
            binary = self.compile(directory, HARNESS, directory)
            result = subprocess.run([str(binary), 'recovery-labels'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Assertion', result.stderr)


if __name__ == '__main__':
    unittest.main()
