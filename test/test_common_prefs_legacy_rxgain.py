"""Execute current common-prefs reads against genuine compact stock writers."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test/fixtures/common_prefs_rxgain"

HARNESS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#define MESH_DEBUG_PRINTLN(...) ((void)0)
namespace mesh { void hilStartupTrace(const char*) {} }
template<typename T> T constrain(T n, int lo, int hi) {
  return std::max(T(lo), std::min(n, T(hi)));
}
struct NodePrefs { @FIELDS@ };
struct File {
  std::vector<uint8_t> bytes;
  size_t cursor = 0, reads = 0;
  size_t size() const { return bytes.size(); }
  size_t available() const { return bytes.size() - cursor; }
  size_t read(uint8_t* out, size_t n) {
    ++reads;
    n = std::min(n, available());
    if (n) memcpy(out, bytes.data() + cursor, n);
    cursor += n;
    return n;
  }
  size_t write(const uint8_t* in, size_t n) {
    bytes.insert(bytes.end(), in, in + n);
    return n;
  }
  void close() {}
};
@CONSTANTS@
struct CommonCLI {
  NodePrefs prefs{};
  NodePrefs* _prefs = &prefs;
  bool _com_prefs_needs_upgrade = false;
  void load(File& file) {
    const char* filename = "/com_prefs";
    (void)filename;
    @CORE_READER@
    @GAIN_TAIL@
    @GAIN_CONSTRAINT@
  }
  File stock1141() { File file; @STOCK_1141@ return file; }
  File stock1140() { File file; @STOCK_1140@ return file; }
  File modern() { File file; @MODERN_WRITER@ return file; }
};
CommonCLI stock(uint8_t gain) {
  CommonCLI writer;
  writer.prefs.rx_boosted_gain = gain;
  writer.prefs.freq = 910.0f;
  writer.prefs.bw = 62.5f;
  writer.prefs.bridge_baud = 115200;
  strcpy(writer.prefs.node_name, "synthetic legacy fixture");
  return writer;
}
void checkLoaded(File image, uint8_t board_default, uint8_t expected) {
  CommonCLI reader;
  reader.prefs.rx_boosted_gain = board_default;
  reader.load(image);
  assert(reader.prefs.rx_boosted_gain == expected);
  assert(reader.prefs.freq == 910.0f && reader.prefs.bw == 62.5f);
  assert(reader.prefs.bridge_baud == 115200);
  assert(!strcmp(reader.prefs.node_name, "synthetic legacy fixture"));
}
int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  if (scenario == "stock-on") {
    auto image = stock(1).stock1141();
    assert(image.size() == 290 && image.bytes[79] == 1);
    checkLoaded(image, 0, 1); // G2's newer default must not discard saved on.
    checkLoaded(image, 1, 1);
  } else if (scenario == "stock-off-padding") {
    auto off = stock(0).stock1141();
    auto padding = stock(1).stock1140();
    assert(off.size() == 290 && off.bytes[79] == 0);
    assert(padding.bytes == off.bytes); // No marker distinguishes old padding.
    checkLoaded(off, 0, 0);
    checkLoaded(off, 1, 1); // Ambiguous zero retains the existing board default.
    checkLoaded(padding, 0, 0);
    checkLoaded(padding, 1, 1);
  } else if (scenario == "malformed-truncated") {
    for (uint8_t invalid : {2, 0xff}) {
      auto image = stock(invalid).stock1141();
      for (uint8_t board_default : {0, 1})
        checkLoaded(image, board_default, board_default);
    }
    for (size_t length : {size_t(0), size_t(79), size_t(80), size_t(289)}) {
      auto image = stock(1).stock1141();
      image.bytes.resize(length);
      for (uint8_t board_default : {0, 1}) {
        CommonCLI reader;
        reader.prefs.rx_boosted_gain = board_default;
        reader.prefs.freq = 123.0f;
        reader.load(image);
        assert(reader._com_prefs_needs_upgrade && image.reads == 0);
        assert(reader.prefs.rx_boosted_gain == board_default);
        assert(reader.prefs.freq == 123.0f);
      }
    }
  } else if (scenario == "modern") {
    for (uint8_t saved : {0, 1}) {
      auto image = stock(saved).modern();
      assert(image.size() == 291 && image.bytes[79] == 0);
      assert(image.bytes[290] == saved);
      for (size_t length : {size_t(291), size_t(293), size_t(295), size_t(877)}) {
        image.bytes.resize(length, 0);
        image.bytes[79] = 1 - saved; // The appended field is authoritative.
        for (uint8_t board_default : {0, 1})
          checkLoaded(image, board_default, saved);
      }
    }
  } else if (scenario == "legacy-gaps") {
    for (size_t gap : {LEGACY_MQTT_GAP_3SLOT, LEGACY_MQTT_GAP_6SLOT}) {
      for (size_t tail : {size_t(1), LEGACY_OBS_TAIL_MAX}) {
        for (uint8_t saved : {0, 1}) {
          auto image = stock(1 - saved).stock1141();
          image.bytes.resize(290 + gap + tail, 0);
          image.bytes[290 + gap] = saved;
          for (uint8_t board_default : {0, 1})
            checkLoaded(image, board_default, saved);
        }
      }
    }
    // Unknown extended layouts must not be mistaken for compact stock gain.
    for (size_t extra : {LEGACY_MQTT_GAP_3SLOT + LEGACY_OBS_TAIL_MAX + 1,
                         LEGACY_MQTT_GAP_6SLOT,
                         LEGACY_MQTT_GAP_6SLOT + LEGACY_OBS_TAIL_MAX + 1}) {
      auto image = stock(1).stock1141();
      image.bytes.resize(290 + extra, 0);
      for (uint8_t board_default : {0, 1})
        checkLoaded(image, board_default, board_default);
    }
    // At the existing normal/gap boundary, byte290 still wins over byte79.
    auto normal = stock(1).stock1141();
    normal.bytes.resize(290 + LEGACY_MQTT_GAP_3SLOT, 0);
    checkLoaded(normal, 1, 0);
  } else if (scenario == "roundtrip") {
    auto original = stock(1).stock1141();
    const auto unchanged = original.bytes;
    CommonCLI reader;
    reader.prefs.rx_boosted_gain = 0;
    reader.load(original);
    auto rewritten = reader.modern();
    assert(original.bytes == unchanged); // Loading does not mutate the file.
    assert(rewritten.bytes[79] == 0 && rewritten.bytes[290] == 1);
    checkLoaded(rewritten, 0, 1);
  } else {
    assert(false);
  }
}
'''


def harness_source(source):
    """Extract actual prefix, branch selection, first tail field, and writer."""
    load = extract_braced(source, "void CommonCLI::loadPrefsInt(")
    core = load[load.index("    if (file.size() < 290)"):
                load.index('    mesh::hilStartupTrace("prefs_image_core_ready");')]
    gain_read = "file.read((uint8_t *)&_prefs->rx_boosted_gain, sizeof(_prefs->rx_boosted_gain));"
    tail_start = load.index("    size_t extra = file.available();")
    gap_read_end = load.index(gain_read, tail_start) + len(gain_read)
    gap = load[tail_start:gap_read_end]
    normal = extract_braced(load[gap_read_end:],
                            "if (file.available() >= (int)sizeof(_prefs->rx_boosted_gain))")
    tail = gap + "\n      }\n    } else {\n" + normal + "\n    }\n"
    tail = tail.replace("bool has_flood_retry_prefs = false;", "[[maybe_unused]] bool has_flood_retry_prefs = false;")
    constraint = re.search(r"^\s*_prefs->rx_boosted_gain = constrain[^\n]+", load, re.M).group()
    save = extract_braced(source, "void CommonCLI::savePrefs(FILESYSTEM*")
    writer_start = save.index("    uint8_t pad[8];")
    gain_write = "file.write((uint8_t *)&_prefs->rx_boosted_gain, sizeof(_prefs->rx_boosted_gain));"
    writer = save[writer_start:save.index(gain_write, writer_start) + len(gain_write)]
    names = set(re.findall(r"_prefs->(\w+)", core + tail + writer))
    header = (ROOT / "src/helpers/CommonCLI.h").read_text()
    declarations = re.findall(r"^\s*(?:float|double|char|u?int(?:8|16|32)_t)\s+[^;]+;",
                              header.split("class NodePrefs :", 1)[1].split("private:", 1)[0], re.M)
    fields = "\n".join(d for d in declarations if any(re.search(r"\b" + n + r"\b", d) for n in names))
    fields = re.sub(r"\s*=\s*[^,;]+", "", fields)
    constants = "\n".join(re.findall(r"^static const size_t LEGACY_(?:MQTT_GAP_\w+|OBS_TAIL_MAX)[^\n]+", source, re.M))
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    values = {"FIELDS": fields, "CORE_READER": core, "GAIN_TAIL": tail,
              "GAIN_CONSTRAINT": constraint, "MODERN_WRITER": writer, "CONSTANTS": constants}
    for version, marker in (("v1.14.1", "STOCK_1141"), ("v1.14.0", "STOCK_1140")):
        filename = version + "-writer.inc"
        data = (FIXTURES / filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != provenance[filename]["excerpt_sha256"]:
            raise ValueError("historical source excerpt changed: " + filename)
        values[marker] = data.decode()
    result = HARNESS
    for marker, value in values.items():
        result = result.replace("@" + marker + "@", value)
    return result


class CommonPrefsLegacyRxGainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="common-prefs-legacy-gain-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.source = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        cls.executable = cls.compile(harness_source(cls.source), "current")

    @classmethod
    def compile(cls, code, name):
        cpp = cls.work / (name + ".cpp")
        executable = cls.work / name
        cpp.write_text(code)
        flags = [] if os.name == "nt" else ["-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        built = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra",
                                "-Werror", *flags, str(cpp), "-o", str(executable)],
                               capture_output=True, text=True, timeout=60)
        if built.returncode:
            raise RuntimeError(built.stderr)
        return executable

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_genuine_stock_enabled_survives_new_disabled_default(self):
        self.scenario("stock-on")

    def test_stock_off_and_older_padding_keep_ambiguous_zero_default(self):
        self.scenario("stock-off-padding")

    def test_invalid_byte_and_truncated_core_preserve_defaults(self):
        self.scenario("malformed-truncated")

    def test_modern_explicit_gain_wins_including_off(self):
        self.scenario("modern")

    def test_known_gap_gain_and_unknown_layout_defaults_remain_authoritative(self):
        self.scenario("legacy-gaps")

    def test_next_normal_save_keeps_recovered_gain_without_moving_fields(self):
        self.scenario("roundtrip")

    def test_reverting_compact_recovery_breaks_genuine_stock_on(self):
        branch = extract_braced(self.source,
                               "if (file.size() == 290 && legacy_rx_boosted_gain == 1)")
        reverted = self.source.replace(branch, "(void)legacy_rx_boosted_gain;", 1)
        executable = self.compile(harness_source(reverted), "reverted")
        result = subprocess.run([str(executable), "stock-on"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reader.prefs.rx_boosted_gain == expected", result.stderr)


if __name__ == "__main__":
    unittest.main()
