#include <helpers/UDPBridgeSettings.h>
#include <cassert>
#include <vector>
#include <initializer_list>
using namespace mesh::bridge::udp;
using Bytes = std::vector<uint8_t>;
constexpr char Path[] = "/udp_bridge";
Bytes image(const Prefs& prefs) {
  Bytes result(PREFS_IMAGE_SIZE); encodePrefs(result.data(), prefs); return result;
}
Prefs configured() {
  Prefs prefs; prefs.enabled = 1;
  assert(parsePeer("192.168.1.22:4404", prefs.peers[0]));
  assert(parsePeer("10.2.3.4:65535", prefs.peers[7]));
  return prefs;
}
int main() {
  Prefs defaults; assert(validPrefs(defaults) && defaults.port == 4404 && !defaults.enabled);
  Peer peer;
  assert(parsePeer("192.168.1.10:1", peer));
  const Peer before = peer;
  for (const char* value : {"", "off ", "0.1.2.3:1", "127.1.2.3:2", "224.1.2.3:1",
      "255.255.255.255:3", "192.168.1.2", "1.2.3.4:0", "1.2.3.4:65536", "1.2.3.4:-1",
      "1.2.3.4:123456789123456789123456789", "1.2.3.4:1 ", "1.2.3.4:1x", "1.2.3.4:1:2",
      "1.2.3:1", "1.2.3.256:1", "999999999999999999999.1.2.3:2", "a.b.c.d:2", "1..3.4:2"}) {
    assert(!parsePeer(value, peer) && equalPeer(peer, before));
  }
  char text[24]; formatPeer(peer, text, sizeof(text)); assert(!strcmp(text, "192.168.1.10:1"));
  assert(parsePeer("off", peer) && !peer.enabled());
  formatPeer(peer, text, sizeof(text)); assert(!strcmp(text, "off"));
  Prefs good = configured(), loaded;
  assert(decodePrefs(image(good).data(), PREFS_IMAGE_SIZE, loaded));
  assert(image(loaded) == image(good));
  for (size_t size = 0; size <= 128; ++size) {
    if (size == PREFS_IMAGE_SIZE) continue;
    Bytes bad = image(good); bad.resize(size);
    loaded = defaults;
    assert(!decodePrefs(bad.data(), bad.size(), loaded) && image(loaded) == image(defaults));
  }
  for (size_t byte = 0; byte < PREFS_IMAGE_SIZE; ++byte) {
    Bytes bad = image(good); bad[byte] ^= 1;
    assert(!decodePrefs(bad.data(), bad.size(), loaded));
  }
  Prefs invalid = good; invalid.peers[1] = invalid.peers[0]; assert(!validPrefs(invalid));
  invalid = defaults; invalid.peers[0].ip[0] = 1; assert(!validPrefs(invalid));
  invalid = defaults; invalid.enabled = 2; assert(!validPrefs(invalid));
  invalid = defaults; invalid.port = 0; assert(!validPrefs(invalid));

  GuestMemoryFS fs;
  fs.files["/com_prefs"] = {1, 2, 3}; // The existing binary image is never rewritten.
  Settings store;
  assert(store.begin(&fs) && store.healthy() && !store.prefs().enabled && fs.writes == 0);
  assert(store.setPrefs(good) && image(store.prefs()) == image(good));
  assert(fs.files.at("/com_prefs") == Bytes({1, 2, 3}));
  Settings reboot; assert(reboot.begin(&fs) && image(reboot.prefs()) == image(good));
  for (unsigned fault = 0; fault < 10; ++fault) {
    GuestMemoryFS faulty; faulty.files[Path] = image(good);
    Settings current; assert(current.begin(&faulty));
    switch (fault) {
      case 0: faulty.fail_open_write = true; break;
      case 1: faulty.short_write = 5; break;
      case 2: faulty.corrupt_stage = true; break;
      case 3: faulty.fail_stage_open = true; break;
      case 4: faulty.fail_stage_read = true; break;
      case 5: faulty.fail_publish = true; break;
      case 6: faulty.false_publish = true; break;
      case 7: faulty.fail_backup = true; break;
      case 8: faulty.files["/udp_bridge.bak"] = image(defaults); faulty.fail_remove_backup = true; break;
      case 9: faulty.files["/udp_bridge.tmp"] = image(defaults); faulty.fail_remove_temp = true; break;
    }
    assert(!current.setPrefs(defaults));
    assert(image(current.prefs()) == image(good) && faulty.files.at(Path) == image(good));
    GuestMemoryFS after; after.files = faulty.files;
    Settings restored; assert(restored.begin(&after) && image(restored.prefs()) == image(good));
  }
  for (size_t size : {size_t(0), size_t(1), size_t(63), size_t(65), size_t(128)}) {
    GuestMemoryFS broken; broken.files[Path] = image(good); broken.files[Path].resize(size);
    Settings current; assert(!current.begin(&broken) && !current.prefs().enabled && current.healthy());
    assert(current.setPrefs(defaults));
  }
  GuestMemoryFS uncertain; uncertain.files[Path] = image(good);
  Settings previous; assert(previous.begin(&uncertain)); uncertain.fail_public_read = true;
  assert(!previous.setPrefs(defaults) && !previous.healthy() && image(previous.prefs()) == image(good));
  assert(!previous.setPrefs(good));
  uncertain.fail_public_read = false;
  assert(previous.begin(&uncertain) && !previous.prefs().enabled);
  GuestMemoryFS interrupted; interrupted.files[Path] = image(good);
  Settings writer; assert(writer.begin(&interrupted)); interrupted.capture = true;
  assert(writer.setPrefs(defaults));
  const auto snapshots = interrupted.snapshots;
  assert(snapshots.size() > 10);
  for (const auto& snapshot : snapshots) {
    GuestMemoryFS after; after.files = snapshot;
    Settings recovered; assert(recovered.begin(&after));
    assert(image(recovered.prefs()) == image(good) || image(recovered.prefs()) == image(defaults));
  }
  GuestMemoryFS staged; staged.files["/udp_bridge.tmp"] = image(good);
  Settings scratch; assert(scratch.begin(&staged) && !scratch.prefs().enabled);
  GuestMemoryFS unreadable; unreadable.files[Path] = image(good); unreadable.fail_metadata = true;
  Settings unavailable; assert(!unavailable.begin(&unreadable) && !unavailable.healthy());
  assert(!unavailable.setPrefs(defaults));
}
