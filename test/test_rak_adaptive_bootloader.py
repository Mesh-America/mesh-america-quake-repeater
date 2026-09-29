"""Exercise the actual adaptive store with simulated internal and QSPI media."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdaptiveBootloaderTest(unittest.TestCase):
    def test_cli_uses_application_storage_gate_only_for_applications(self):
        cli = (ROOT / "src/helpers/ota/OtaCli.cpp").read_text()
        error = cli.index('ERR bootloader cannot apply from detected QSPI storage')
        start = cli.rfind('#elif defined(OTA_RAK_AUTO_STORE)', 0, error)
        end = cli.index('#elif defined(OTA_QSPI_STORE)', error)
        gate = cli[cli.index('\n', start) + 1:end]
        source = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
constexpr uint8_t OTA_BL_STORAGE_QSPI = 4;
struct Store {
  int mode;
  bool usesExternal() { return mode == 1; }
  bool usesInternal() { return mode == 0; }
  const char* selectionReason() { return "unsafe wiring"; }
};
bool rejected(bool selboot, int mode, uint8_t flags) {
  struct { Store fetch_store; } c = {{mode}};
  struct { uint8_t storage_flags; } bl = {flags};
  char reply[160];
''' + gate + r'''
  return false;
}
int main() {
  // The CLI has already required exact identity and privileged boot caps.
  assert(!rejected(true, 1, 0x0A));  // canonical bootloader, external app store
  assert(!rejected(true, 0, 0x0A));
  assert(!rejected(true, 2, 0x0A));  // optional NOR is irrelevant to internal boot staging
  assert(rejected(false, 1, 0x0A)); // app still needs the external capability
  assert(rejected(false, 2, 0x1E)); // unsafe application store remains rejected
  assert(!rejected(false, 1, 0x1E));
  assert(!rejected(false, 0, 0x0A));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "cli.cpp").write_text(source)
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            str(path / "cli.cpp"), "-o", str(path / "cli")], check=True)
            subprocess.run([str(path / "cli")], check=True)

    def test_storage_switch_and_manual_resume(self):
        header = (ROOT / "src/helpers/ota/OtaStoreAdaptiveNrf52.h").read_text()
        body = header[header.index("class OtaStoreAdaptiveNrf52"):
                      header.index("} // namespace ota")]
        source = r'''
#include <cassert>
#include <new>
#include "src/helpers/ota/OtaStore.h"
#include "src/helpers/ota/OtaBlInfo.h"
#include "src/helpers/ota/OtaRakStoragePolicy.h"
using namespace mesh::ota;
namespace mesh { namespace ota {
static bool capable = true, boot_resume = false, app_resume = false;
static unsigned detected = 2, internal_begins = 0, external_begins = 0;
static unsigned internal_live = 0, external_live = 0;
struct OtaBootloaderIdentity { bool crc_ok = true; const char* device_name = "4631_DFU"; };
bool ota_installed_bootloader_identity(OtaBootloaderIdentity&) { return true; }
struct MotaManifest { bool is_bootloader() const { return boot_resume; } };
bool mota_parse_manifest(const uint8_t*, size_t, MotaManifest&) { return true; }
OtaBlCaps simulatedCaps() {
  OtaBlCaps c; c.present = true; c.apply_abi = capable ? 3 : 2;
  c.codec_mask = 5; c.storage_flags = capable ? 0x1e : 0x16;
  c.optional_app_storage = capable ? 0x14 : 0; return c;
}
OtaBlCaps simulatedBootCaps() {
  auto c = simulatedCaps(); c.storage_flags = capable ? 0x0a : 0x02;
  c.optional_app_storage = 0; return c;
}
class Store : public OtaStore {
public:
  uint32_t size = 0;
  bool begin(uint32_t n) override { size = n; return true; }
  bool write(uint32_t, const uint8_t*, uint32_t) override { return true; }
  bool read(uint32_t, uint8_t*, uint32_t) const override { return true; }
  uint32_t capacity() const override { return 65536; }
  uint32_t staged_size() const override { return size; }
  void clear() override { size = 0; }
};
class OtaStoreFlashNrf52 : public Store {
public:
  OtaStoreFlashNrf52() { ++internal_live; assert(external_live == 0); }
  ~OtaStoreFlashNrf52() { --internal_live; }
  bool begin(uint32_t n) override { ++internal_begins; return Store::begin(n); }
  bool reopenFor(const uint8_t*, uint32_t) override { return boot_resume; }
};
class OtaStoreQspiNrf52 : public Store {
public:
  OtaStoreQspiNrf52() { ++external_live; assert(internal_live == 0); }
  ~OtaStoreQspiNrf52() { --external_live; }
  static uint8_t autoDetect() { return detected; }
  static bool headerW25Detected() { return true; }
  uint32_t jedec_id() const { return 0xef4015; }
  uint8_t status1() const { return 0; }
  const char* last_stage() const { return "ok"; }
  const char* last_error() const { return "ok"; }
  bool begin(uint32_t n) override { ++external_begins; return Store::begin(n); }
  bool reopenFor(const uint8_t*, uint32_t) override { return app_resume; }
};
#define ota_bootloader_app_caps simulatedCaps
#define ota_bootloader_update_caps simulatedBootCaps
'''
        source += body
        source += r'''
} }
int main() {
  uint8_t mid[4] = {1, 2, 3, 4};
  {
    OtaStoreAdaptiveNrf52 store;
    assert(store.usesExternal());
    assert(store.plan_layout(true, 40960, 365, 40960, true));
    assert(store.usesInternal());
    assert(store.begin(41330));
    assert(internal_begins == 1 && external_begins == 0);
    assert(store.plan_layout(true, 100000, 365, 100000, false));
    assert(store.usesExternal());
    assert(store.begin(100370));
    assert(external_begins == 1);
    boot_resume = true;
    assert(!store.reopenFor(nullptr, 0));
    assert(store.usesExternal());
    assert(store.reopenFor(mid, 0));
    assert(store.usesInternal());
    boot_resume = false;
    assert(!store.reopenFor(mid, 0));
    assert(store.usesExternal());
    app_resume = true;
    assert(store.reopenFor(mid, 0));
    assert(store.usesExternal());
    capable = false;
    assert(!store.plan_layout(true, 40960, 365, 40960, true));
    assert(store.usesExternal());
  }
  assert(internal_live == 0 && external_live == 0);
  capable = true; detected = 0;
  {
    OtaStoreAdaptiveNrf52 store;
    assert(store.usesInternal());
    assert(store.plan_layout(true, 40960, 365, 40960, true));
    assert(store.begin(41330));
    assert(store.plan_layout(false, 40960, 365, 40960, false));
    assert(store.usesInternal());
  }
  assert(internal_live == 0 && external_live == 0);
  for (uint8_t flags : {uint8_t(0x0a), uint8_t(0x1e)}) {
    OtaBlCaps c = simulatedCaps(); c.storage_flags = flags;
    assert(ota_bootloader_self_update_caps_valid(c));
    c.apply_abi = 2; assert(!ota_bootloader_self_update_caps_valid(c));
  }
  for (uint8_t flags : {uint8_t(0x09), uint8_t(0x0e), uint8_t(0x16), uint8_t(0x1f)}) {
    OtaBlCaps c = simulatedCaps(); c.storage_flags = flags;
    assert(!ota_bootloader_self_update_caps_valid(c));
  }
}
'''
        source = "#include <initializer_list>\n" + source
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "adaptive.cpp"
            exe = Path(directory) / "adaptive"
            cpp.write_text(source)
            subprocess.run([
                "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-DOTA_RAK_AUTO_STORE", "-DOTA_INTERNAL_BOOTLOADER_UPDATE",
                "-I", str(ROOT), str(cpp), "-o", str(exe),
            ], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
