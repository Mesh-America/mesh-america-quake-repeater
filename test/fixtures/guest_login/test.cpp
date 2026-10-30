#include <helpers/GuestLoginSettings.h>
#include <helpers/PersistentStoreFormat.h>
#include <cassert>
#include <cstdio>

using mesh::GuestLoginSettings;
using Bytes = std::vector<uint8_t>;
constexpr char Path[] = "/guest_login";
Bytes image(bool enabled) {
  Bytes bytes = {'G', 'L', 'G', '1', uint8_t(enabled), 0, 0, 0, 0, 0, 0, 0};
  mesh::storage::writeLE32(bytes.data() + 8,
      mesh::storage::updateCRC32(0xffffffff, bytes.data(), 8));
  return bytes;
}
void basics() {
  GuestLoginSettings no_fs;
  assert(!no_fs.enabled() && !no_fs.healthy() && !no_fs.setEnabled(true));
  assert(!no_fs.begin(nullptr));
  GuestMemoryFS fs;
  GuestLoginSettings settings;
  assert(settings.begin(&fs) && settings.healthy() && !settings.enabled());
  assert(fs.files.empty() && fs.writes == 0); // Older installs remain off without migration writes.
  assert(settings.setEnabled(true) && settings.enabled());
  assert(fs.files.at(Path) == image(true));
  GuestLoginSettings reboot;
  assert(reboot.begin(&fs) && reboot.enabled());
  assert(reboot.setEnabled(false) && !reboot.enabled());
  assert(fs.files.at(Path) == image(false));
  assert(settings.begin(&fs) && !settings.enabled());
  assert(!fs.files.count("/guest_login.tmp") && !fs.files.count("/guest_login.bak"));
}
void malformed() {
  for (unsigned length = 0; length < 25; ++length) {
    if (length == 12) continue;
    GuestMemoryFS fs;
    fs.files[Path] = image(true); fs.files[Path].resize(length);
    GuestLoginSettings settings;
    assert(!settings.begin(&fs) && !settings.enabled());
    assert(settings.healthy() && settings.setEnabled(true)); // Explicit admin repairs malformed image.
  }
  for (unsigned byte = 0; byte < 12; ++byte) {
    GuestMemoryFS fs; fs.files[Path] = image(true); fs.files[Path][byte] ^= 1;
    GuestLoginSettings settings;
    assert(!settings.begin(&fs) && !settings.enabled());
    assert(settings.setEnabled(false));
  }
  GuestMemoryFS fs; fs.files[Path] = image(true); fs.files[Path][4] = 2;
  mesh::storage::writeLE32(fs.files[Path].data() + 8,
      mesh::storage::updateCRC32(0xffffffff, fs.files[Path].data(), 8));
  GuestLoginSettings settings;
  assert(!settings.begin(&fs) && !settings.enabled());
}
void failedSaves() {
  for (unsigned fault = 0; fault < 10; ++fault) {
    GuestMemoryFS fs; fs.files[Path] = image(true);
    GuestLoginSettings settings; assert(settings.begin(&fs));
    switch (fault) {
      case 0: fs.fail_open_write = true; break;
      case 1: fs.short_write = 5; break;
      case 2: fs.corrupt_stage = true; break;
      case 3: fs.fail_stage_open = true; break;
      case 4: fs.fail_stage_read = true; break;
      case 5: fs.fail_publish = true; break;
      case 6: fs.false_publish = true; break;
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
      case 7: fs.fail_backup = true; break;
      case 8: fs.files["/guest_login.bak"] = image(false); fs.fail_remove_backup = true; break;
#else
      case 7: fs.fail_open_write = true; break;
      case 8: fs.short_write = 0; break;
#endif
      case 9: fs.files["/guest_login.tmp"] = image(false); fs.fail_remove_temp = true; break;
    }
    const bool saved = settings.setEnabled(false);
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
    // AtomicFileWriter can truncate scratch even when stale scratch removal fails.
    if (fault == 9) { assert(saved && !settings.enabled()); continue; }
#endif
    assert(!saved);
    assert(fs.files.at(Path) == image(true));
    if (settings.healthy()) assert(settings.enabled());
    else assert(!settings.enabled() && !settings.setEnabled(true));
    GuestMemoryFS reboot_fs; reboot_fs.files = fs.files;
    GuestLoginSettings reboot; assert(reboot.begin(&reboot_fs) && reboot.enabled());
  }
  for (unsigned count = 0; count < 12; ++count) {
    GuestMemoryFS fs; fs.files[Path] = image(false);
    GuestLoginSettings settings; assert(settings.begin(&fs)); fs.short_write = count;
    assert(!settings.setEnabled(true) && !settings.enabled());
    assert(fs.files.at(Path) == image(false));
  }
}
void uncertainPublication() {
  for (bool old : {false, true}) {
    GuestMemoryFS fs; fs.files[Path] = image(old);
    GuestLoginSettings settings; assert(settings.begin(&fs)); fs.fail_public_read = true;
    assert(!settings.setEnabled(!old));
    assert(!settings.healthy() && !settings.enabled() && !settings.setEnabled(old));
    fs.fail_public_read = false;
    assert(settings.begin(&fs) && settings.enabled() == !old);
  }
  GuestMemoryFS fs; fs.files[Path] = image(false);
  GuestLoginSettings settings; assert(settings.begin(&fs)); fs.late_error = true;
  assert(settings.setEnabled(true) && settings.enabled()); // Exact public bytes beat rename return value.
}
void rebootEveryBoundary() {
  for (bool old : {false, true}) {
    GuestMemoryFS fs; fs.files[Path] = image(old);
    GuestLoginSettings settings; assert(settings.begin(&fs)); fs.capture = true;
    assert(settings.setEnabled(!old));
    const auto snapshots = fs.snapshots;
    assert(snapshots.size() > 10);
    for (const auto& snapshot : snapshots) {
      GuestMemoryFS reboot_fs; reboot_fs.files = snapshot;
      GuestLoginSettings reboot;
      assert(reboot.begin(&reboot_fs));
      if (snapshot.count(Path)) assert(reboot.enabled() == (snapshot.at(Path) == image(true)));
      else if (snapshot.count("/guest_login.bak"))
        assert(reboot.enabled() == (snapshot.at("/guest_login.bak") == image(true)));
      else assert(!reboot.enabled());
    }
  }
  GuestMemoryFS fs; fs.files["/guest_login.tmp"] = image(true);
  GuestLoginSettings settings;
  assert(settings.begin(&fs) && !settings.enabled()); // Never recover uncommitted enable scratch.
}
void loadErrors() {
  GuestMemoryFS fs; fs.files[Path] = image(true);
  GuestLoginSettings settings; fs.fail_public_read = fs.published = true;
  assert(!settings.begin(&fs) && !settings.healthy() && !settings.enabled());
  assert(!settings.setEnabled(true));
#if !defined(RP2040_PLATFORM)
  fs.fail_public_read = false; fs.fail_metadata = true;
  assert(!settings.begin(&fs) && !settings.healthy() && !settings.enabled());
#endif
}
int main(int argc, char** argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "basics")) basics();
  else if (!strcmp(argv[1], "malformed")) malformed();
  else if (!strcmp(argv[1], "failed_saves")) failedSaves();
  else if (!strcmp(argv[1], "uncertain")) uncertainPublication();
  else if (!strcmp(argv[1], "reboot")) rebootEveryBoundary();
  else if (!strcmp(argv[1], "load_errors")) loadErrors();
  else assert(false);
  printf("guest login %s passed\n", argv[1]);
}
