#!/usr/bin/env python3
"""Run the MeshTower selector with peripheral stores and the real manifest parser."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
OTA = ROOT / "src/helpers/ota"
FLAGS = ["-DNRF52_PLATFORM=1", "-DHELTEC_TOWER_V2_SDCARD=1",
         "-DOTA_SD_STORE=1", "-DOTA_FLASH_STORE=1", "-DOTA_TOWER_AUTO_STORE=1"]

CAPS = r'''
#pragma once
#include <stdint.h>
namespace mesh { namespace ota {
static const uint8_t OTA_BL_STORAGE_SD = 1;
static const uint8_t OTA_BL_STORAGE_STAGE_CEILING = 2;
struct OtaBlCaps {
  bool present = false;
  uint16_t apply_abi = 3, codec_mask = 5;
  uint8_t storage_flags = 9, optional_app_storage = 2;
};
extern OtaBlCaps installed;
extern int cap_reads;
inline OtaBlCaps ota_bootloader_app_caps() { ++cap_reads; return installed; }
} }
'''

STORES = r'''
#pragma once
#include "OtaStore.h"
#include <string.h>
namespace mesh {
class MainBoard {};
namespace ota {
struct Medium {
  int constructors = 0, destructors = 0, probes = 0;
  int begin_calls = 0, plan_calls = 0, read_calls = 0, write_calls = 0;
  int clear_calls = 0, discard_calls = 0, reopen_calls = 0;
  int meta_calls = 0, finalize_calls = 0, checkpoints = 0;
  int format_calls = 0, erase_calls = 0, space_calls = 0, list_calls = 0;
  bool present = true, mountable = true, begin_ok = true, layout_ok = true;
  bool io_ok = true, discard_ok = true, staged = false;
  uint32_t total = 0, last_target = 0;
  const uint8_t* last_mid = nullptr;
  uint8_t bytes[512] = {0};
};
extern Medium sd_medium, flash_medium;
extern int auth_clears;
class FakeStore : public OtaStore {
protected:
  Medium& media;
  uint32_t total = 0;
public:
  explicit FakeStore(Medium& m) : media(m) { ++media.constructors; }
  ~FakeStore() override { ++media.destructors; }
  bool begin(uint32_t n) override {
    ++media.begin_calls;
    total = 0;
    if (!media.present || !media.begin_ok) return false;
    total = media.total = n; media.staged = true; return true;
  }
  bool write(uint32_t p, const uint8_t* d, uint32_t n) override {
    ++media.write_calls;
    if (!media.present || !media.io_ok || p + n > total || p + n > sizeof(media.bytes)) return false;
    memcpy(media.bytes + p, d, n); return true;
  }
  bool read(uint32_t p, uint8_t* d, uint32_t n) const override {
    ++media.read_calls;
    if (!media.present || !media.io_ok || p + n > total || p + n > sizeof(media.bytes)) return false;
    memcpy(d, media.bytes + p, n); return true;
  }
  uint32_t capacity() const override { return media.present ? 8192u : 0u; }
  uint32_t staged_size() const override { return total; }
  void clear() override { ++media.clear_calls; total = 0; }
  bool discard() override {
    ++media.discard_calls; total = 0;
    if (!media.present || !media.discard_ok) return false;
    media.staged = false; media.total = 0; return true;
  }
  bool set_meta_size(uint32_t) override { ++media.meta_calls; return media.io_ok; }
  bool finalize() override { ++media.finalize_calls; return media.present && media.io_ok; }
  void checkpoint() override { ++media.checkpoints; }
  bool reopen() override {
    ++media.reopen_calls;
    total = media.present && media.staged ? media.total : 0;
    return total != 0;
  }
  bool reopenFor(const uint8_t* mid, uint32_t target) override {
    media.last_mid = mid; media.last_target = target; return reopen();
  }
  bool plan_layout(bool, uint32_t, uint32_t, uint32_t, bool) override {
    ++media.plan_calls; return media.layout_ok;
  }
};
class OtaStoreSdNrf52 : public FakeStore {
public:
  OtaStoreSdNrf52() : FakeStore(sd_medium) { ++auth_clears; }
  bool probeMedia() { ++media.probes; return media.present && media.mountable; }
  void clear() override { ++media.clear_calls; total = 0; media.staged = false; }
  const char* last_error() const { return "SD peripheral error"; }
  bool formatCard(MainBoard&) { ++media.format_calls; return media.present; }
  bool eraseCard(MainBoard&) { ++media.erase_calls; return media.present; }
  bool getSpace(MainBoard&, uint64_t& used, uint64_t& free) {
    ++media.space_calls; used = 1; free = 2; return media.present;
  }
  bool listFiles(MainBoard&, uint16_t, char*, size_t) { ++media.list_calls; return media.present; }
};
class OtaStoreFlashNrf52 : public FakeStore {
public:
  OtaStoreFlashNrf52() : FakeStore(flash_medium) { ++auth_clears; }
};
} }
'''

DRIVER = r'''
#include "OtaStoreTowerNrf52.h"
#include "OtaByteIO.h"
#include <assert.h>
#include <string.h>
using namespace mesh::ota;
namespace mesh { namespace ota {
OtaBlCaps installed;
Medium sd_medium, flash_medium;
int cap_reads = 0, auth_clears = 0;
} }

static void defaults() {
  installed.present = true;
  installed.storage_flags = 9;
  installed.optional_app_storage = 2;
}
static void manifest(Medium& m, uint8_t flags = 0) {
  m.staged = true;
  memset(m.bytes, 0, sizeof(m.bytes));
  uint8_t* p = m.bytes + 8;
  const bool boot = flags & MFLAG_BOOTLOADER;
  p[0] = boot ? MOTA_BOOT_FORMAT_VER : MOTA_APP_FORMAT_VER;
  p[1] = flags; p[2] = HASH_ALGO_SHA256;
  wr_u32le(p + 3, 11); wr_u32le(p + 7, 1);
  wr_u32le(p + 11, boot ? 0xA000u : 1024u);
  wr_u32le(p + 15, boot ? 0xA000u : 64u);
  p[19] = 10;
  p[20] = 1; p[21] = 2; p[22] = 3; p[23] = 4;
  p[56] = flags & MFLAG_FULL ? CODEC_FULL : CODEC_DETOOLS_INPLACE;
  m.total = boot ? 41330u : 278u;
}
static void startup() {
  OtaStoreTowerNrf52 store;
  assert(sd_medium.constructors == 1 && flash_medium.constructors == 0 && auth_clears == 1);
  OtaStoreSdNrf52* owner = &store.sdStore();
  assert(owner == &store.externalStore());
  assert(!store.usesExternalStore() && !store.usesExternal() && !store.usesInternal());
  assert(!store.compatible() && store.capacity() == 0 && store.staged_size() == 0);
  uint8_t byte = 0;
  assert(!store.read(0, &byte, 1) && !store.write(0, &byte, 1));
  assert(!store.set_meta_size(1) && !store.finalize());
  store.checkpoint(); store.clear(); store.resetSelection();
  assert(owner == &store.sdStore());
  assert(sd_medium.probes == 0 && cap_reads == 0 && flash_medium.constructors == 0);
  assert(sd_medium.clear_calls == 0 && sd_medium.reopen_calls == 0);
}
static void primary() {
  defaults(); OtaStoreTowerNrf52 store;
  assert(store.selectStorage() && store.usesExternalStore() && store.compatible());
  assert(sd_medium.probes == 1 && sd_medium.reopen_calls == 0 && flash_medium.constructors == 0);
  assert(store.plan_layout(true, 1024, 209, 64, false));
  assert(store.begin(278));
  uint8_t data[4] = {1, 2, 3, 4}, got[4] = {0};
  assert(store.write(0, data, 4) && store.read(0, got, 4) && memcmp(data, got, 4) == 0);
  assert(store.set_meta_size(16) && store.finalize()); store.checkpoint();
  assert(store.staged_size() == 278 && store.capacity() == 8192);
  assert(store.selectStorage() && sd_medium.probes == 1 && cap_reads == 1);
  assert(sd_medium.begin_calls == 1 && sd_medium.meta_calls == 1 && sd_medium.finalize_calls == 1);
  assert(sd_medium.checkpoints == 1 && flash_medium.begin_calls == 0 && auth_clears == 1);
  assert(store.plan_layout(true, 0xA000, 365, 0xA000, true));
}
static void fallback(bool unmountable) {
  defaults(); sd_medium.present = unmountable; sd_medium.mountable = false;
  OtaStoreTowerNrf52 store;
  assert(store.selectStorage() && store.usesInternal() && !store.usesExternal());
  assert(flash_medium.constructors == 1 && auth_clears == 2);
  assert(!store.begin(278) && flash_medium.begin_calls == 0);
  assert(!store.plan_layout(true, 1024, 209, 64, false));
  assert(!store.begin(278) && flash_medium.begin_calls == 0);
  assert(!store.plan_layout(true, 0xA000, 365, 0xA000, true));
  assert(!store.begin(41330) && flash_medium.begin_calls == 0);
  assert(store.plan_layout(false, 1024, 209, 64, false) && store.begin(278));
  assert(flash_medium.plan_calls == 1 && flash_medium.begin_calls == 1);
  uint8_t data = 7, got = 0;
  assert(store.write(0, &data, 1) && store.read(0, &got, 1) && got == data);
  assert(store.set_meta_size(16) && store.finalize()); store.checkpoint();
  sd_medium.present = sd_medium.mountable = true;
  assert(store.selectStorage() && store.usesInternal() && sd_medium.probes == 1);
  assert(sd_medium.begin_calls == 0 && sd_medium.plan_calls == 0);
  store.clear();
  assert(store.usesInternal() && !store.begin(278) && flash_medium.begin_calls == 1);
  assert(store.plan_layout(false, 1024, 209, 64, false) && store.begin(278));
}
static void old_or_unqualified() {
  defaults(); sd_medium.present = false;
  for (uint8_t option : {0u, 1u, 4u, 6u}) {
    installed.optional_app_storage = option;
    OtaStoreTowerNrf52 store;
    assert(!store.selectStorage() && !store.usesInternal() && !store.usesExternal());
    assert(!store.begin(278) && store.capacity() == 0);
  }
  installed.optional_app_storage = 2; installed.storage_flags = 2;
  { OtaStoreTowerNrf52 store; assert(!store.selectStorage()); }
  installed.storage_flags = 9; installed.present = false;
  { OtaStoreTowerNrf52 store; assert(!store.selectStorage()); }
  assert(flash_medium.constructors == 0 && flash_medium.begin_calls == 0);
  installed.present = true; installed.optional_app_storage = 0; sd_medium.present = true;
  { OtaStoreTowerNrf52 store; assert(store.selectStorage() && store.usesExternal()); }
  installed.present = false;
  { OtaStoreTowerNrf52 store;
    assert(!store.selectStorage() && store.usesExternal() && !store.compatible());
    assert(!store.begin(278)); }
}
static void failures() {
  defaults(); OtaStoreTowerNrf52 store;
  assert(store.selectStorage());
  sd_medium.layout_ok = false;
  assert(!store.plan_layout(false, 1024, 209, 64, false) && !store.begin(278));
  assert(sd_medium.begin_calls == 0 && store.usesExternal() && flash_medium.constructors == 0);
  sd_medium.layout_ok = true; sd_medium.begin_ok = false;
  assert(store.plan_layout(false, 1024, 209, 64, false) && !store.begin(278));
  assert(sd_medium.begin_calls == 1 && flash_medium.constructors == 0);
  sd_medium.begin_ok = true; assert(store.begin(278));
  sd_medium.present = false; uint8_t byte = 0;
  assert(!store.write(0, &byte, 1) && !store.read(0, &byte, 1) && !store.finalize());
  assert(store.usesExternal() && store.selectStorage() && sd_medium.probes == 1);
  assert(flash_medium.constructors == 0 && !store.discard());
  store.resetSelection();
  assert(store.selectStorage() && store.usesInternal() && flash_medium.constructors == 1);
}
static void resume(bool internal) {
  defaults(); sd_medium.present = !internal;
  Medium& m = internal ? flash_medium : sd_medium;
  manifest(m);
  OtaStoreTowerNrf52 store;
  uint8_t good[4] = {1, 2, 3, 4}, wrong[4] = {9, 9, 9, 9};
  assert(!store.reopenFor(wrong, 11) && store.staged_size() == 0);
  assert(m.staged && m.clear_calls == 0 && m.discard_calls == 0);
  assert(!store.reopenFor(nullptr, 22) && store.staged_size() == 0);
  assert(store.reopenFor(good, 11) && store.staged_size() == m.total);
  if (internal) assert(m.last_mid == good && m.last_target == 11);
  assert(store.reopen() && store.staged_size() == m.total);
  manifest(m, MFLAG_FULL);
  assert(store.reopen() == !internal);
  manifest(m, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER);
  assert(store.reopen() == !internal);
  m.bytes[8] = 99;
  assert(!store.reopen());
  assert(m.staged && m.clear_calls == 0 && m.discard_calls == 0);
  assert(sd_medium.probes == 1);
}
static void cancellation() {
  defaults(); sd_medium.present = false;
  OtaStoreTowerNrf52 store; OtaStoreSdNrf52* owner = &store.sdStore();
  assert(store.plan_layout(false, 1024, 209, 64, false) && store.begin(278));
  store.clear(); assert(store.staged_size() == 0 && flash_medium.staged);
  manifest(flash_medium); assert(store.reopen());
  flash_medium.discard_ok = false; assert(!store.discard() && flash_medium.staged);
  flash_medium.discard_ok = true; assert(store.discard() && !flash_medium.staged);
  sd_medium.present = true; store.resetSelection();
  assert(flash_medium.destructors == 1 && owner == &store.sdStore());
  assert(store.capacity() == 0 && store.selectStorage() && store.usesExternal());
  assert(store.begin(278)); store.clear();
  assert(store.usesExternal() && !sd_medium.staged && sd_medium.clear_calls == 1);
  assert(sd_medium.probes == 2);
}
static void management() {
  defaults(); sd_medium.present = false; OtaStoreTowerNrf52 store;
  assert(store.selectStorage() && store.usesInternal());
  mesh::MainBoard board; uint64_t used = 0, free = 0; char out[20];
  assert(!store.formatCard(board) && !store.eraseCard(board));
  assert(!store.getSpace(board, used, free) && !store.listFiles(board, 0, out, sizeof(out)));
  assert(sd_medium.format_calls == 1 && sd_medium.erase_calls == 1);
  assert(sd_medium.space_calls == 1 && sd_medium.list_calls == 1);
  sd_medium.present = true;
  assert(store.formatCard(board) && store.eraseCard(board));
  assert(store.getSpace(board, used, free) && used == 1 && free == 2);
  assert(store.listFiles(board, 1, out, sizeof(out)) && store.usesInternal());
  assert(flash_medium.begin_calls == 0 && sd_medium.probes == 1);
}
int main(int argc, char** argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "startup")) startup();
  else if (!strcmp(argv[1], "primary")) primary();
  else if (!strcmp(argv[1], "missing")) fallback(false);
  else if (!strcmp(argv[1], "unmountable")) fallback(true);
  else if (!strcmp(argv[1], "legacy")) old_or_unqualified();
  else if (!strcmp(argv[1], "failures")) failures();
  else if (!strcmp(argv[1], "resume-sd")) resume(false);
  else if (!strcmp(argv[1], "resume-internal")) resume(true);
  else if (!strcmp(argv[1], "cancel")) cancellation();
  else if (!strcmp(argv[1], "management")) management();
  else return 2;
}
'''

PROBE = r'''
#include "OtaStoreSdNrf52.h"
#include <assert.h>
#include <stdlib.h>
using namespace mesh::ota;
static bool mountable;
static unsigned mounts, capacity_calls;
static uint32_t sectors;
namespace mesh { namespace ota {
OtaStoreSdNrf52::OtaStoreSdNrf52() {}
OtaStoreSdNrf52::~OtaStoreSdNrf52() {}
bool OtaStoreSdNrf52::mount() { ++mounts; return mountable; }
uint32_t OtaStoreSdNrf52::capacity() const { ++capacity_calls; return sectors * 512u; }
bool OtaStoreSdNrf52::begin(uint32_t) { abort(); }
bool OtaStoreSdNrf52::write(uint32_t, const uint8_t*, uint32_t) { abort(); }
bool OtaStoreSdNrf52::read(uint32_t, uint8_t*, uint32_t) const { abort(); }
void OtaStoreSdNrf52::clear() { abort(); }
bool OtaStoreSdNrf52::discard() { abort(); }
bool OtaStoreSdNrf52::set_meta_size(uint32_t) { abort(); }
bool OtaStoreSdNrf52::finalize() { abort(); }
void OtaStoreSdNrf52::checkpoint() { abort(); }
bool OtaStoreSdNrf52::reopen() { abort(); }
bool OtaStoreSdNrf52::plan_layout(bool, uint32_t, uint32_t, uint32_t, bool) { abort(); }
} }
int main() {
  OtaStoreSdNrf52 store;
  assert(mounts == 0 && capacity_calls == 0);
  mountable = false; sectors = 10;
  assert(!store.probeMedia() && mounts == 1 && capacity_calls == 0);
  mountable = true; sectors = 0;
  assert(!store.probeMedia() && mounts == 2 && capacity_calls == 1);
  sectors = 10;
  assert(store.probeMedia() && mounts == 3 && capacity_calls == 2);
}
'''


class TowerAutoStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++")
        if not cls.compiler:
            raise unittest.SkipTest("C++ compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="tower-auto-storage-")
        cls.work = Path(cls.temp.name)
        for name in ("OtaStore.h", "OtaFormat.h", "MotaContainer.h", "OtaByteIO.h"):
            shutil.copyfile(OTA / name, cls.work / name)
        (cls.work / "OtaBlInfo.h").write_text(CAPS)
        (cls.work / "stores.h").write_text(STORES)
        for name in ("OtaStoreFlashNrf52.h", "OtaStoreSdNrf52.h"):
            (cls.work / name).write_text('#include "stores.h"\n')
        (cls.work / "Utils.h").write_text("""
#pragma once
#include <stddef.h>
#include <stdint.h>
namespace mesh { class Utils { public:
static void sha256(uint8_t*, size_t, const uint8_t*, int);
static void sha256(uint8_t*, size_t, const uint8_t*, int, const uint8_t*, int);
}; }
""")
        (cls.work / "test.cpp").write_text('#include <initializer_list>\n' + DRIVER)
        cls.header = (OTA / "OtaStoreTowerNrf52.h").read_text()
        cls.exe = cls.compile(cls.header, "selector")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def compile(cls, header, name):
        (cls.work / "OtaStoreTowerNrf52.h").write_text(header)
        exe = cls.work / name
        subprocess.run([cls.compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                        *FLAGS, "-I", str(cls.work), "-I", str(OTA),
                        str(cls.work / "test.cpp"), str(OTA / "MotaContainer.cpp"),
                        "-o", str(exe)], check=True, capture_output=True, text=True)
        return exe

    def test_selection_and_transfer_boundaries(self):
        for scenario in ("startup", "primary", "missing", "unmountable", "legacy",
                         "failures", "resume-sd", "resume-internal", "cancel", "management"):
            with self.subTest(scenario=scenario):
                subprocess.run([str(self.exe), scenario], check=True, capture_output=True)

    def test_exact_real_sd_probe_never_opens_or_removes_files(self):
        # Keep the source away from the selector's peripheral doubles so its
        # quoted include resolves to the real production SD header.
        probe_dir = self.work / "real-probe"
        probe_dir.mkdir()
        source = probe_dir / "probe.cpp"
        source.write_text(PROBE)
        exe = self.work / "probe"
        subprocess.run([self.compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        "-DNRF52_PLATFORM=1", "-DOTA_SD_STORE=1", "-I", str(OTA),
                        str(source), "-o", str(exe)], check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True)

    def test_unsupported_recipe_cannot_enable_tower_selection(self):
        (self.work / "OtaStoreTowerNrf52.h").write_text(self.header)
        source = self.work / "guard.cpp"
        source.write_text('#include "OtaStoreTowerNrf52.h"\n')
        for missing in FLAGS[:-1]:
            with self.subTest(missing=missing):
                flags = [flag for flag in FLAGS if flag != missing]
                result = subprocess.run([self.compiler, "-std=c++11", "-fsyntax-only",
                                         *flags, "-I", str(self.work), str(source)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires the qualified nRF52 SD primary", result.stderr)

    def test_negative_controls_expose_unsafe_selection_and_resume(self):
        mutations = [
            ("startup-probe", "OtaStoreTowerNrf52() = default;",
             "OtaStoreTowerNrf52() { selectStorage(); }", "startup"),
            ("legacy-fallback", "sd_profile && caps.optional_app_storage == OTA_BL_STORAGE_STAGE_CEILING",
             "sd_profile", "legacy"),
            ("internal-full", "_mode == INTERNAL_MODE && (full || bootloader)",
             "false", "missing"),
            ("missing-layout", "_mode == INTERNAL_MODE && !_layout_accepted",
             "false", "missing"),
            ("resume-identity", "reopened && resumeMatches(mid, target)",
             "reopened", "resume-sd"),
        ]
        for name, old, new, scenario in mutations:
            with self.subTest(mutation=name):
                self.assertEqual(self.header.count(old), 1)
                exe = self.compile(self.header.replace(old, new), name)
                result = subprocess.run([str(exe), scenario], capture_output=True)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
