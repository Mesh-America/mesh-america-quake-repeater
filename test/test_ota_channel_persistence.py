"""Exercise OTA channel persistence through the production common prefs store."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

from test_common_usb_debug import HARNESS
from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

MAIN = r'''
struct Capture {
  std::vector<uint8_t> bytes;
  std::map<const void*, size_t> offsets;
  size_t write(const uint8_t* data, size_t size) {
    offsets[data] = bytes.size();
    bytes.insert(bytes.end(), data, data + size);
    return size;
  }
  size_t offset(const void* field) const { return offsets.at(field); }
};

void seed(CommonCLI& cli) {
  auto& p = cli.prefs;
  strcpy(p.node_name, "OTA channel node");
  strcpy(p.password, "channel-pass");
  strcpy(p.owner_info, "owner information");
  p.node_lat = 40.125; p.node_lon = -105.25;
  p.freq = 920.25f; p.bw = 125; p.sf = 9; p.cr = 6;
  p.tx_power_dbm = 14;
  p.primary_radio_preamble = 96;
  p.gps_enabled = 1; p.gps_interval = 300;
  p.gps_sync_interval_hours = 336;
  p.espnow_bridge_enabled = 0;
  p.usb_logging_enabled = 0; p.usb_debug_enabled = 1;
  p.trace_when_repeat_off = 1;
  setDefaultDirectRetryPrefs(&p);
}

void assertExistingPrefs(const NodePrefs& actual, const NodePrefs& expected) {
  assert(strcmp(actual.node_name, expected.node_name) == 0);
  assert(strcmp(actual.password, expected.password) == 0);
  assert(strcmp(actual.owner_info, expected.owner_info) == 0);
  assert(actual.node_lat == expected.node_lat && actual.node_lon == expected.node_lon);
  assert(actual.freq == expected.freq && actual.bw == expected.bw);
  assert(actual.sf == expected.sf && actual.cr == expected.cr);
  assert(actual.tx_power_dbm == expected.tx_power_dbm);
  assert(actual.primary_radio_preamble == expected.primary_radio_preamble);
  assert(actual.gps_enabled == expected.gps_enabled && actual.gps_interval == expected.gps_interval);
  assert(actual.gps_sync_interval_hours == expected.gps_sync_interval_hours);
  assert(actual.espnow_bridge_enabled == expected.espnow_bridge_enabled);
  assert(actual.usb_logging_enabled == expected.usb_logging_enabled);
  assert(actual.usb_debug_enabled == expected.usb_debug_enabled);
  assert(actual.trace_when_repeat_off == expected.trace_when_repeat_off);
}

void testRoundTripsAndLayout() {
  CommonCLI cli;
  seed(cli);
  assert(cli.prefs.ota_channel == 0);
  Capture original;
  assert(writeCommonPrefsImage(original, &cli.prefs));
  const size_t channel_offset = original.offset(&cli.prefs.ota_channel);
  const size_t trace_offset = original.offset(&cli.prefs.trace_when_repeat_off);
  assert(channel_offset == trace_offset + sizeof(cli.prefs.trace_when_repeat_off));
  assert(channel_offset + sizeof(cli.prefs.ota_channel) + 3 == original.bytes.size());
  assert(original.bytes[channel_offset + 1] == 0); // reserved ESP-NOW profile
  assert(original.offset(&cli.prefs.rs232_bridge_enabled) == channel_offset + 2);
  assert(original.bytes[channel_offset + 2] == 0 && original.bytes.back() == 0);
  // The established common core remains at its public file offsets.
  assert(original.offset(cli.prefs.node_name) == 4);
  assert(original.offset(&cli.prefs.freq) == 72);
  assert(original.offset(&cli.prefs.sf) == 112);
  assert(original.offset(&cli.prefs.bw) == 116);

  for (uint8_t channel : {0, 1, 2}) {
    cli.prefs.ota_channel = channel;
    cli.savePrefs(&cli.fs, PrefsSaveRouting::Scope::Common);
    assert(cli._common_save_succeeded);
    const auto image = cli.fs.files.at("/com_prefs");
    Capture checked;
    assert(writeCommonPrefsImage(checked, &cli.prefs));
    assert(checked.bytes == image); // Checked and ordinary writers agree.
    assert(image.size() == original.bytes.size() && image[channel_offset] == channel);
    for (size_t i = 0; i < image.size(); ++i) {
      assert(i == channel_offset || image[i] == original.bytes[i]);
    }
    CommonCLI reader;
    reader.prefs.ota_channel = 2; // A reused preference object must be replaced.
    reader.fs.files["/com_prefs"] = image;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.ota_channel == channel);
    assertExistingPrefs(reader.prefs, cli.prefs);
  }
}

void testLegacyTruncatedAndCorruptImages() {
  CommonCLI writer;
  seed(writer);
  writer.prefs.ota_channel = 2;
  Capture captured;
  assert(writeCommonPrefsImage(captured, &writer.prefs));
  const size_t channel_offset = captured.offset(&writer.prefs.ota_channel);
  const size_t gps_offset = captured.offset(&writer.prefs.gps_sync_interval_hours);
  const size_t debug_offset = captured.offset(&writer.prefs.usb_debug_enabled);
  const size_t trace_offset = captured.offset(&writer.prefs.trace_when_repeat_off);
  const auto current = captured.bytes;
  CommonCLI reader;

  // Derive the previous image from the append boundary, without hardcoding its size.
  reader.fs.files["/com_prefs"] = current;
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.ota_channel == 2);
  reader.fs.files["/com_prefs"] = {current.begin(), current.begin() + channel_offset};
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.ota_channel == 0);
  assertExistingPrefs(reader.prefs, writer.prefs);

  for (size_t length = 0; length <= channel_offset; ++length) {
    reader.prefs.ota_channel = 2;
    reader.prefs.usb_debug_enabled = 1;
    reader.prefs.trace_when_repeat_off = 1;
    reader.prefs.gps_sync_interval_hours = 336;
    reader.fs.files["/com_prefs"] = {current.begin(), current.begin() + length};
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.ota_channel == 0);
    assert(reader.prefs.gps_sync_interval_hours == (length >= gps_offset + 2 ? 336 : 0));
    assert(reader.prefs.usb_debug_enabled == (length > debug_offset ? 1 : 0));
    assert(reader.prefs.trace_when_repeat_off == (length > trace_offset ? 1 : 0));
  }

  for (unsigned invalid = 3; invalid <= 255; ++invalid) {
    auto corrupt = current;
    corrupt[channel_offset] = static_cast<uint8_t>(invalid);
    reader.prefs.ota_channel = 2;
    reader.fs.files["/com_prefs"] = corrupt;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.ota_channel == 0);
    assertExistingPrefs(reader.prefs, writer.prefs);
  }

  // A file reporting a full size can still return a short/error read at the new byte.
  reader.fs.files["/com_prefs"] = current;
  reader.fs.fail_read_after = static_cast<int>(channel_offset);
  reader.prefs.ota_channel = 2;
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.ota_channel == 0);
  assertExistingPrefs(reader.prefs, writer.prefs);
  reader.fs.fail_read_after = -1;
  reader.prefs.ota_channel = 2;
  reader.loadPrefsInt(&reader.fs, "/missing");
  assert(reader.prefs.ota_channel == 0);
  reader.fs.fail_read_open = true;
  reader.prefs.ota_channel = 2;
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.ota_channel == 0);
}

void testFailedTransactionsRetainPreviousChannel() {
  for (uint8_t previous_channel : {1, 2}) {
    for (int fault : {0, 1, 2, 3, 4, 5}) {
#ifdef WITH_MQTT_BRIDGE
      // Observer finish() checks reopening and size; standard writers also read CRCs.
      if (fault == 3) continue;
#endif
      CommonCLI cli;
      seed(cli);
      cli.prefs.ota_channel = previous_channel;
      cli.savePrefs(&cli.fs, PrefsSaveRouting::Scope::Common);
      assert(cli._common_save_succeeded);
      const auto previous = cli.fs.files.at("/com_prefs");
      const NodePrefs expected = cli.prefs;
      Capture capture;
      assert(writeCommonPrefsImage(capture, &cli.prefs));
      const size_t channel_offset = capture.offset(&cli.prefs.ota_channel);
      if (fault == 0) cli.fs.fail_write = true;
      if (fault == 1) cli.fs.fail_write_after = static_cast<int>(channel_offset);
      if (fault == 2) cli.fs.fail_read_open = true;
      if (fault == 3) cli.fs.fail_read_after = static_cast<int>(channel_offset);
      if (fault == 4) cli.fs.fail_rename = 1;
      if (fault == 5) cli.fs.fail_rename_from = {"/com_prefs.tmp"};
      cli.prefs.ota_channel = previous_channel == 1 ? 2 : 1;
      assert(!cli.trySavePrefs());
      assert(cli.fs.files.at("/com_prefs") == previous);
      cli.fs.fail_write = false; cli.fs.fail_write_after = -1;
      cli.fs.fail_read_open = false; cli.fs.fail_read_after = -1;
      cli.fs.fail_rename = 0; cli.fs.fail_rename_from.clear();
      assert(cli.recoverCommonPrefsFiles(&cli.fs));
      assert(cli.fs.files.at("/com_prefs") == previous);
      cli.loadPrefsInt(&cli.fs, "/com_prefs");
      assert(cli.prefs.ota_channel == previous_channel);
      assertExistingPrefs(cli.prefs, expected);
    }
  }
}

int main() {
  testRoundTripsAndLayout();
  testLegacyTruncatedAndCorruptImages();
  testFailedTransactionsRetainPreviousChannel();
}
'''


def persistence_harness():
    source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="utf-8")
    header = (ROOT / "src/helpers/CommonCLI.h").read_text(encoding="utf-8")
    fields = header.split("class NodePrefs :", 1)[1].split("private:", 1)[0]
    fields = "\n".join(re.findall(
        r"^\s*(?:float|double|char|u?int(?:8|16|32)_t)\s+[^;]+;", fields, re.M))
    constants = "\n".join(re.findall(
        r"^\s*#define\s+\w+\s+(?:0x[\dA-Fa-f]+|\d+)\s*$", header, re.M))
    constants += "\n" + "\n".join(re.findall(
        r"^static const size_t LEGACY_\w+\s*=[^;]+;", source, re.M))
    constants += "\n" + re.search(
        r"^static constexpr uint8_t DEFAULT_ADVERT_LOC_POLICY\s*=[^;]+;",
        header, re.M).group()
    helpers = "\n".join(extract_braced(source, signature) for signature in (
        "static bool bwMatches(", "static bool isValidLoRaBandwidth(",
        "static float defaultLoRaBandwidth(", "static void markDirectRetryPrefsValid(",
        "static void applyFloodRetryPreset(", "static void applyDirectRetryPreset(",
        "static void setDefaultDirectRetryPrefs(", "static bool directRetryPrefsValid("))
    methods = "\n".join(extract_braced(source, signature) for signature in (
        "static const char* commonPrefsSaveResultName(",
        "bool CommonCLI::recoverCommonPrefsFiles(",
        "bool CommonCLI::saveCommonPrefsImageAtomically(",
        "void CommonCLI::savePrefs(FILESYSTEM*",
        "void CommonCLI::savePrefs(PrefsSaveRouting::Scope scope)",
        "bool CommonCLI::trySavePrefs(", "void CommonCLI::loadPrefsInt("))
    code = HARNESS[:HARNESS.index("struct Capture {")] + MAIN
    replacements = {
        "FIELDS": fields, "CONSTANTS": constants, "HELPERS": helpers,
        "LEGACY": extract_braced(header, "struct LegacyObserverTail") + ";",
        "SERIALIZER": "template<typename Writer>\n" + extract_braced(
            source, "static bool writeCommonPrefsImage("),
        "STORE": extract_braced(source, "class CommonPrefsFileStore"),
        "METHODS": methods,
        "DYNAMIC": "", "SET_DEBUG": "", "SET_MASTER": "",
        "GET_DEBUG": "", "GET_MASTER": "",
    }
    for key, value in replacements.items():
        code = code.replace("@" + key + "@", value)
    return code


class OtaChannelPersistenceTests(unittest.TestCase):
    def test_actual_serializers_loads_and_failed_commits_for_every_platform(self):
        code = persistence_harness()
        sanitizer_flags = [] if os.name == "nt" else [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-pie", "-no-pie"]
        variants = [("ENABLE_OTA", platform) for platform in (
            "NRF52_PLATFORM", "STM32_PLATFORM", "ESP32_PLATFORM", "RP2040_PLATFORM")]
        variants.append(("ENABLE_OTA", "ESP32_PLATFORM", "WITH_MQTT_BRIDGE"))
        variants.extend((("NRF52_PLATFORM",), ("ESP32_PLATFORM", "WITH_MQTT_BRIDGE")))
        with tempfile.TemporaryDirectory(prefix="common-ota-channel-") as directory:
            work = Path(directory)
            transaction = (ROOT / "src/helpers/ContactFileTransaction.h").read_text()
            (work / "ContactFileTransaction.h").write_text(transaction.replace(
                '#include "IdentityStore.h"', '#include <helpers/IdentityStore.h>'))
            (work / "test.cpp").write_text(code, encoding="utf-8")
            for macros in variants:
                with self.subTest(macros=macros):
                    exe = work / ("test.exe" if os.name == "nt" else "test")
                    built = subprocess.run([
                        os.environ.get("CXX", "g++"), "-std=c++17",
                        *["-D" + macro + "=1" for macro in macros], *sanitizer_flags,
                        "-I" + str(work), "-I" + str(ROOT / "test/fixtures/radio_profiles/mocks"),
                        "-I" + str(ROOT / "src"), "-I" + str(ROOT / "src/helpers"),
                        str(work / "test.cpp"), "-o", str(exe)],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    tested = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(tested.returncode, 0, tested.stderr)


if __name__ == "__main__":
    unittest.main()
