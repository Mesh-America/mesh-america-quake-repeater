"""Keep canonical retry preference bytes while batching their atomic write."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <cstdint>
#include <cstddef>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <algorithm>
#include <limits>
#define DEFAULT_POWERSAVING_ENABLED 0
#define DEFAULT_ADVERT_LOC_POLICY 0
#ifndef FLOOD_RETRY_PREFIX_SLOTS
#define FLOOD_RETRY_PREFIX_SLOTS 8
#define FLOOD_RETRY_PREFIX_LEN 3
#define FLOOD_RETRY_BRIDGE_BUCKETS 6
#define FLOOD_RETRY_BUCKET_PREFIXES 17
#define FLOOD_RETRY_IGNORE_PREFIXES 8
#endif
namespace mesh { namespace bridge {constexpr uint8_t ESPNOW_FORMAT_WRAPPED=0;} struct RepeaterRadioTiming {static constexpr uint8_t DEFAULT_RX_WATCHDOG_ENABLED=1;}; }
class ConfigSerializer {public:virtual void structure() {} uint8_t base_padding[3] = {};};
'''

WRITER = r'''
struct Writer {
 std::vector<uint8_t> bytes;size_t budget=std::numeric_limits<size_t>::max();bool okay=true;
 __attribute__((noinline)) size_t write(const uint8_t* p,size_t n) {
  if(!okay)return 0;const size_t used=std::min(n,budget);bytes.insert(bytes.end(),p,p+used);budget-=used;
  if(used!=n)okay=false;return used;
 }
 bool commit()const{return okay;}
};
'''

REFERENCE_WRITES = r'''
    writer.write((uint8_t *)&prefs->retry_preset, sizeof(prefs->retry_preset));                     // 295
    writer.write((uint8_t *)&prefs->direct_retry_attempts, sizeof(prefs->direct_retry_attempts));   // 296
    writer.write((uint8_t *)&prefs->direct_retry_base_ms, sizeof(prefs->direct_retry_base_ms));     // 297
    writer.write((uint8_t *)&prefs->direct_retry_step_ms, sizeof(prefs->direct_retry_step_ms));     // 299
    writer.write((uint8_t *)&prefs->direct_retry_snr_margin_x4, sizeof(prefs->direct_retry_snr_margin_x4)); // 301
    writer.write((uint8_t *)&prefs->direct_retry_cr4_snr_x4, sizeof(prefs->direct_retry_cr4_snr_x4)); // 303
    writer.write((uint8_t *)&prefs->direct_retry_cr5_snr_x4, sizeof(prefs->direct_retry_cr5_snr_x4)); // 304
    writer.write((uint8_t *)&prefs->direct_retry_cr7_snr_x4, sizeof(prefs->direct_retry_cr7_snr_x4)); // 305
    writer.write((uint8_t *)&prefs->direct_retry_cr8_snr_x4, sizeof(prefs->direct_retry_cr8_snr_x4)); // 306
    writer.write((uint8_t *)&prefs->direct_retry_enabled, sizeof(prefs->direct_retry_enabled));       // 307
    writer.write((uint8_t *)&prefs->direct_retry_cr_enabled, sizeof(prefs->direct_retry_cr_enabled)); // 308
    writer.write((uint8_t *)&prefs->direct_retry_prefs_magic, sizeof(prefs->direct_retry_prefs_magic)); // 309
    writer.write((uint8_t *)&prefs->flood_retry_attempts, sizeof(prefs->flood_retry_attempts));       // 311
    writer.write((uint8_t *)&prefs->flood_retry_max_path, sizeof(prefs->flood_retry_max_path));       // 312
    writer.write((uint8_t *)&prefs->flood_retry_prefixes[0][0], sizeof(prefs->flood_retry_prefixes)); // 313
    writer.write((uint8_t *)&prefs->flood_retry_bridge_enabled, sizeof(prefs->flood_retry_bridge_enabled));
    writer.write((uint8_t *)&prefs->flood_retry_bridge_buckets[0][0][0], sizeof(prefs->flood_retry_bridge_buckets));
    writer.write((uint8_t *)&prefs->flood_retry_ignore_prefixes[0][0], sizeof(prefs->flood_retry_ignore_prefixes));
    writer.write((uint8_t *)&prefs->flood_retry_advert_enabled, sizeof(prefs->flood_retry_advert_enabled));
    writer.write((uint8_t *)&prefs->battery_alert_enabled, sizeof(prefs->battery_alert_enabled));
    writer.write((uint8_t *)&prefs->battery_alert_low_percent, sizeof(prefs->battery_alert_low_percent));
    writer.write((uint8_t *)&prefs->battery_alert_critical_percent, sizeof(prefs->battery_alert_critical_percent));
    writer.write((uint8_t *)&prefs->direct_retry_recent_enabled, sizeof(prefs->direct_retry_recent_enabled));
    writer.write((uint8_t *)&prefs->flood_channel_data_enabled, sizeof(prefs->flood_channel_data_enabled));
    writer.write((uint8_t *)&prefs->legacy_flood_channel_block_max_hops,
               sizeof(prefs->legacy_flood_channel_block_max_hops));
    writer.write((uint8_t *)&prefs->flood_channel_data_max_hops, sizeof(prefs->flood_channel_data_max_hops));
    writer.write((uint8_t *)&prefs->telemetry_access, sizeof(prefs->telemetry_access));             // 674
'''

CHECKS = r'''
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Winvalid-offsetof"
int main(){
 NodePrefs prefs;uint32_t state=1;size_t length=0;
 for(unsigned seed=0;seed<32;seed++) {
  Writer expected;
  auto* first=reinterpret_cast<uint8_t*>(&prefs)+__builtin_offsetof(NodePrefs,retry_preset);
  const size_t size=__builtin_offsetof(NodePrefs,telemetry_access)+sizeof(prefs.telemetry_access)-__builtin_offsetof(NodePrefs,retry_preset);
  for(size_t i=0;i<size;i++){state=state*1664525u+1013904223u;first[i]=uint8_t(state>>24);}
  reference(expected,&prefs);length=expected.bytes.size();assert(expected.commit());
  Writer actual;writeCommonRetryPrefs(actual,&prefs);assert(actual.commit()&&actual.bytes==expected.bytes);
  for(size_t limit=0;limit<=length;limit++){
   Writer a,b;a.budget=b.budget=limit;reference(a,&prefs);writeCommonRetryPrefs(b,&prefs);
   assert(a.bytes==b.bytes&&a.commit()==b.commit());assert(a.commit()==(limit==length));
  }
 }
 printf("PASS: exact canonical %zu-byte tail, 32 arbitrary states, every cumulative short-write boundary\n",length);
}
#pragma GCC diagnostic pop
'''

def fixture(padded=False):
    header = (ROOT / "src/helpers/CommonCLI.h").read_text()
    begin = header.index("class NodePrefs : public ConfigSerializer")
    begin = header.index("public:", begin)
    end = header.index("\nprivate:", begin)
    declarations = "class NodePrefs : public ConfigSerializer {\n" + header[begin:end] + "\n};\n"
    if padded:
        original = "  uint8_t direct_retry_attempts = 0;"
        assert original in declarations
        declarations = declarations.replace(original, original + "\n  uint8_t layout_break = 0;", 1)
    source = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
    begin = source.index("// This canonical retry/flood span contains no padding.")
    end = source.index("void CommonCLI::savePrefs(FILESYSTEM* fs", begin)
    helper = source[begin:end]
    return (PREFIX + declarations + helper + WRITER
            + "void reference(Writer& writer, NodePrefs* prefs) {\n"
            + REFERENCE_WRITES + "}\n" + CHECKS)


class CommonRetryTailTests(unittest.TestCase):
    def compile(self, work, definitions=(), padded=False):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "native C++ compiler required")
        cpp, executable = work / "tail.cpp", work / "tail"
        cpp.write_text(fixture(padded))
        result = subprocess.run([
            compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
            "-Wno-misleading-indentation", "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all", "-fno-pie", "-no-pie", *definitions,
            str(cpp), "-o", str(executable),
        ], capture_output=True, text=True, timeout=60)
        return result, executable

    def test_actual_members_match_old_bytes_and_every_short_write_boundary(self):
        for definitions in ((), ("-DENABLE_OTA=1", "-DRAK_4631=1"), (
                "-DFLOOD_RETRY_PREFIX_SLOTS=3", "-DFLOOD_RETRY_PREFIX_LEN=5",
                "-DFLOOD_RETRY_BRIDGE_BUCKETS=2", "-DFLOOD_RETRY_BUCKET_PREFIXES=7",
                "-DFLOOD_RETRY_IGNORE_PREFIXES=4")):
            with self.subTest(definitions=definitions), tempfile.TemporaryDirectory() as directory:
                result, executable = self.compile(Path(directory), definitions)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                checked = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn("exact canonical", checked.stdout)

    def test_changed_member_layout_refuses_to_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.compile(Path(directory), padded=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("retry tail has padding or changed order", result.stderr)


if __name__ == "__main__":
    unittest.main()
