#include <helpers/MorseSettings.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>

using mesh::MorseSettings;
static constexpr const char* Path = "/morse_prefs";
static constexpr const char* Backup = "/morse_prefs.bak";

static MemoryFS filesystem() {
  MemoryFS fs;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  fs.rename_replaces = true;
#endif
  return fs;
}

static std::vector<uint8_t> image(const MorseSettings& prefs) {
  uint8_t bytes[mesh::MorseSettingsImageSize];
  mesh::encodeMorseSettings(prefs, bytes);
  return {bytes, bytes + sizeof(bytes)};
}

static MorseSettings custom() {
  MorseSettings prefs;
  prefs.frequency_khz = 902321; prefs.wpm = 60;
  return prefs;
}

static void defaults() {
  assert(mesh::morseSettings().frequency_khz == 902100 && mesh::morseSettings().wpm == 25);
}

static void equals(const MorseSettings& actual, const MorseSettings& expected) {
  assert(actual.frequency_khz == expected.frequency_khz && actual.wpm == expected.wpm);
}

static void codec() {
  MorseSettings prefs;
  assert(mesh::MorseSettingsImageSize == 12 && prefs.frequencyMHz() == 902.100f);
  const uint8_t expected[] = {@DEFAULT_IMAGE@};
  assert(image(prefs) == std::vector<uint8_t>(expected, expected + sizeof(expected)));
  const auto bytes = image(custom());
  MorseSettings decoded;
  assert(mesh::decodeMorseSettings(bytes.data(), bytes.size(), decoded));
  equals(decoded, custom());
  for (size_t length = 0; length < mesh::MorseSettingsImageSize; ++length) {
    assert(!mesh::decodeMorseSettings(bytes.data(), length, decoded));
    equals(decoded, custom());
  }
  assert(!mesh::decodeMorseSettings(nullptr, bytes.size(), decoded));
  assert(!mesh::decodeMorseSettings(bytes.data(), bytes.size() + 1, decoded));
  for (size_t offset = 0; offset < bytes.size(); ++offset) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      auto corrupt = bytes; corrupt[offset] ^= 1U << bit;
      assert(!mesh::decodeMorseSettings(corrupt.data(), corrupt.size(), decoded));
      equals(decoded, custom());
    }
  }
  for (int reason = 0; reason < 4; ++reason) {
    auto invalid = prefs;
    if (reason == 0) invalid.wpm = 0;
    if (reason == 1) invalid.wpm = uint8_t(mesh::MorseMaxWpm + 1);
    if (reason == 2) invalid.frequency_khz = mesh::MorseMinFrequencyKHz - 1;
    if (reason == 3) invalid.frequency_khz = mesh::MorseMaxFrequencyKHz + 1;
    const auto checked = image(invalid); // valid checksum does not waive range checks
    assert(!mesh::decodeMorseSettings(checked.data(), checked.size(), decoded));
    equals(decoded, custom());
  }
  auto unsupported = bytes; unsupported[2] = 2;
  const auto crc = mesh::morseSettingsCRC(unsupported.data(), 8);
  for (unsigned i = 0; i < 4; ++i) unsupported[8 + i] = uint8_t(crc >> (8 * i));
  assert(!mesh::decodeMorseSettings(unsupported.data(), unsupported.size(), decoded));
}

static void load_and_roundtrip() {
  assert(!mesh::loadMorseSettings(nullptr)); defaults(); assert(!mesh::morseSettingsUsable());
  assert(!mesh::saveMorseSettings(custom()));
  auto fs = filesystem();
  fs.files["/identity"] = {1, 2, 3, 4};
  fs.files["/com_prefs"] = {5, 6, 7, 8};
  fs.files["/acl"] = {9, 10};
  const auto unrelated = fs.files;
  assert(!mesh::loadMorseSettings(&fs)); defaults(); assert(mesh::morseSettingsUsable());
  for (uint8_t speed : {1, 25, 60}) {
    for (uint32_t frequency : {100000, 902100, 1000000}) {
      MorseSettings prefs; prefs.wpm = speed; prefs.frequency_khz = frequency;
      assert(mesh::saveMorseSettings(prefs));
      assert(mesh::morseSettingsUsable());
      equals(mesh::morseSettings(), prefs);
      assert(fs.files.at(Path) == image(prefs));
      assert(mesh::loadMorseSettings(&fs)); equals(mesh::morseSettings(), prefs);
      for (const auto& entry : unrelated) assert(fs.files.at(entry.first) == entry.second);
      assert(!fs.exists("/morse_prefs.tmp"));
    }
  }
  fs.files.erase(Path);
  assert(!mesh::loadMorseSettings(&fs)); defaults(); // never reuse previous loaded values
  assert(mesh::saveMorseSettings(custom()));
  for (int reason = 0; reason < 4; ++reason) {
    auto invalid = custom();
    if (reason == 0) invalid.wpm = 0;
    if (reason == 1) invalid.wpm = uint8_t(mesh::MorseMaxWpm + 1);
    if (reason == 2) invalid.frequency_khz = 99999;
    if (reason == 3) invalid.frequency_khz = 1000001;
    const auto before = fs.files;
    assert(!mesh::saveMorseSettings(invalid));
    equals(mesh::morseSettings(), custom()); assert(fs.files == before);
  }
}

static void malformed_and_read_failures() {
  const auto good = image(custom());
  for (size_t length = 0; length < good.size(); ++length) {
    auto fs = filesystem();
    fs.files[Path] = {good.begin(), good.begin() + length};
    assert(!mesh::loadMorseSettings(&fs)); defaults(); assert(!mesh::morseSettingsUsable());
  }
  for (size_t offset = 0; offset < good.size(); ++offset) {
    auto fs = filesystem(); fs.files[Path] = good; fs.files[Path][offset] ^= 1;
    assert(!mesh::loadMorseSettings(&fs)); defaults(); assert(!mesh::morseSettingsUsable());
  }
  for (int fault = 0; fault < 3; ++fault) {
    for (int position = 0; position < 12; ++position) {
      auto fs = filesystem(); fs.files[Path] = good;
      if (fault == 0) fs.fail_read_open = true;
      if (fault == 1) fs.fail_read_after = position;
      if (fault == 2) fs.fail_presence = true;
      assert(!mesh::loadMorseSettings(&fs)); defaults();
      assert(!mesh::morseSettingsUsable());
      const auto before = fs.files;
      assert(!mesh::saveMorseSettings(MorseSettings())); // unreadable image never overwritten
      assert(fs.files == before);
      fs.fail_read_open = false; fs.fail_read_after = -1; fs.fail_presence = false;
      assert(!mesh::morseSettingsUsable()); // elapsed time alone does not clear error
      assert(fs.files == before);
      assert(mesh::saveMorseSettings(MorseSettings())); // explicit verified retry now permitted
      defaults(); assert(mesh::morseSettingsUsable());
    }
  }
}

static void backup_recovery() {
  const auto good = image(custom());
  for (bool corrupt_primary : {false, true}) {
    auto fs = filesystem(); fs.files[Backup] = good;
    if (corrupt_primary) fs.files[Path] = {0, 1, 2};
    fs.files["/morse_prefs.tmp"] = image(MorseSettings()); // unpublished temp never wins
    assert(mesh::loadMorseSettings(&fs)); equals(mesh::morseSettings(), custom());
    assert(mesh::morseSettingsUsable());
    assert(fs.files.at(Path) == good && !fs.exists(Backup));
    assert(mesh::saveMorseSettings(MorseSettings()));
  }
  for (int fault = 0; fault < 3; ++fault) {
    auto fs = filesystem(); fs.files[Backup] = good;
    fs.files[Path] = fault == 2 ? good : std::vector<uint8_t>{1, 2, 3};
    if (fault == 0) fs.fail_remove = true;
    if (fault == 1) fs.fail_rename_from = {Backup};
    if (fault == 2) fs.fail_read_paths = {Path};
    assert(mesh::loadMorseSettings(&fs)); equals(mesh::morseSettings(), custom());
    assert(!mesh::morseSettingsUsable());
    assert(fs.files.at(Backup) == good); // sole readable copy protected from next save
    const auto before = fs.files;
    assert(!mesh::saveMorseSettings(MorseSettings()));
    equals(mesh::morseSettings(), custom()); assert(fs.files == before);
    fs.fail_remove = false; fs.fail_rename = 0; fs.fail_rename_from.clear(); fs.fail_read_paths.clear();
    assert(!mesh::morseSettingsUsable());
    assert(mesh::saveMorseSettings(MorseSettings())); defaults();
    assert(mesh::morseSettingsUsable());
  }
  {
    auto fs = filesystem(); fs.files[Path] = good; fs.files[Backup] = {0};
    assert(mesh::loadMorseSettings(&fs)); equals(mesh::morseSettings(), custom());
    assert(fs.files.at(Backup) == std::vector<uint8_t>{0}); // valid primary is authoritative
  }
}

static void transaction_failures() {
  for (int fault = 0; fault < 6; ++fault) {
    for (int position = 0; position < 12; ++position) {
      auto fs = filesystem(); fs.files[Path] = image(custom());
      assert(mesh::loadMorseSettings(&fs));
      const auto before = fs.files.at(Path);
      if (fault == 0) fs.fail_write = true;
      if (fault == 1) fs.fail_write_after = position;
      if (fault == 2) fs.fail_read_open = true;
      if (fault == 3) fs.fail_read_after = position;
      if (fault == 4) fs.fail_rename = 1;
      if (fault == 5) fs.fail_rename_from = {"/morse_prefs.tmp"};
      assert(!mesh::saveMorseSettings(MorseSettings()));
      assert(!mesh::morseSettingsUsable()); // no uncertain frequency is sent after an error
      equals(mesh::morseSettings(), custom());
      assert(fs.files.at(Path) == before);
      fs.fail_write = false; fs.fail_write_after = -1;
      fs.fail_read_open = false; fs.fail_read_after = -1;
      fs.fail_rename = 0; fs.fail_rename_from.clear();
      assert(mesh::loadMorseSettings(&fs)); equals(mesh::morseSettings(), custom());
      assert(mesh::saveMorseSettings(MorseSettings())); defaults();
    }
  }
}

int main() {
  codec(); load_and_roundtrip(); malformed_and_read_failures();
  backup_recovery(); transaction_failures();
}
