#include "FakeFilesystem.h"
#include <cerrno>
#include <sys/stat.h>
#define FILESYSTEM FakeFilesystem
#include <helpers/ContactInfo.h>
#include <helpers/ContactFileTransaction.h>
#include "packet_under_test.h"

static_assert(MESH_CONTACT_CACHE == 0,
              "This fixture must exercise PSRAM/explicit inline-path storage");

// Replace only the SDK metadata syscall; the production presence/error logic
// and transaction implementation are compiled unchanged.
int fixtureStat(FakeFilesystem* fs, const char* vfs_path, struct stat*) {
  if (fs->metadata_error) { errno = EIO; return -1; }
  assert(strncmp(vfs_path, "/spiffs", 7) == 0);
  if (!fs->exists(vfs_path + 7)) { errno = ENOENT; return -1; }
  return 0;
}
#include "presence_under_test.h"

struct Host {
  std::vector<ContactInfo> contacts;
  unsigned copies = 0;
  size_t capacity = 350;
  bool onContactLoaded(const ContactInfo& c) {
    if (contacts.size() >= capacity) return false;
    contacts.push_back(c);
    return true;
  }
  bool getContactForSave(uint32_t index, ContactInfo& contact) {
    ++copies;
    if (index >= contacts.size()) return false;
    contact = contacts[index];
    return true;
  }
  ContactInfo* getContactForStore(uint32_t) {
    assert(false && "Uncached ESP must keep getContactForSave copy semantics");
    return nullptr;
  }
};
using DataStoreHost = Host;

// Hardware-only constructor/FS seams are supplied here. The state fields and
// all save/load/dirty/transaction bodies below come from production sources.
class DataStore {
  FakeFilesystem* _fs;
  bool _channel_load_incomplete = false;
  bool _uncached_contact_load_incomplete = false;
#include "contact_write_state_under_test.h"
public:
  explicit DataStore(FakeFilesystem& fs) : _fs(&fs) {}
  ~DataStore();
  FakeFilesystem* _getContactsChannelsFS() const { return _fs; }
  File openRead(FakeFilesystem* fs, const char* path) { return fs->open(path); }
  bool hasIncompleteContactLoad() const;
  void loadContacts(DataStoreHost*);
  bool saveContacts(DataStoreHost*, bool (*)(const ContactInfo&));
  bool flushContactWrites(DataStoreHost*, bool (*)(const ContactInfo&));
  bool markContactDirty(const ContactInfo&);
  bool releaseContact(const ContactInfo&);
  bool serviceContactWrites(DataStoreHost*, bool (*)(const ContactInfo&));
  bool hasPendingContactWrites() const;
  bool deleteBlobByKey(const uint8_t[], int);
  bool verifying() const { return _contact_write_verifying; }
  bool readyToPublish() const {
    return _contact_write && _contact_write->readyToPublish();
  }
};
#include "store_under_test.h"

ContactInfo contact(unsigned number) {
  ContactInfo c;
  for (unsigned i = 0; i < 32; ++i) c.id.pub_key[i] = (number * 13 + i * 17) & 255;
  memcpy(c.id.pub_key, &number, sizeof(number));
  snprintf(c.name, sizeof(c.name), "Fixture %u", number);
  c.type = 1;
  c.flags = number & 31;
  c.tx_radio = number % 5;
  c.sync_since = 1000 + number;
  c.last_advert_timestamp = 2000 + number;
  c.lastmod = 3000 + number;
  c.gps_lat = 4000 + number;
  c.gps_lon = -5000 - number;
  uint8_t path[9];
  for (unsigned i = 0; i < sizeof(path); ++i) path[i] = number + i;
  assert(c.setPath(path, 0x83));
  return c;
}

Host table(unsigned count = 32) {
  Host h;
  for (unsigned i = 0; i < count; ++i) h.contacts.push_back(contact(i));
  return h;
}

bool keepContact(const ContactInfo& c) { return c.type != 0; }
bool keepEven(const ContactInfo& c) { return (c.id.pub_key[0] & 1) == 0; }
using Filter = bool (*)(const ContactInfo&);

std::vector<uint8_t> image(const Host& h, Filter filter = nullptr) {
  std::vector<uint8_t> bytes;
  for (const auto& c : h.contacts) {
    if (filter && !filter(c)) continue;
    uint8_t record[mesh::storage::CONTACT_RECORD_SIZE];
    assert(serializeContactRecord(c, record));
    bytes.insert(bytes.end(), record, record + sizeof(record));
  }
  return bytes;
}

unsigned drain(DataStore& store, Host& h, Filter filter = nullptr) {
  const bool existed = SPIFFS.exists("/contacts3");
  const auto old = existed ? SPIFFS.files.at("/contacts3") : std::vector<uint8_t>();
  unsigned passes = 0;
  while (store.hasPendingContactWrites()) {
    const unsigned writes = SPIFFS.writes, reads = SPIFFS.reads;
    assert(++passes < 5000);
    assert(store.serviceContactWrites(&h, filter));
    assert(SPIFFS.writes - writes <= 1);
    assert(SPIFFS.reads - reads <= 1);
    // Transport service runs here, between every production pass. It must
    // never observe an unpublished replacement or a target-name gap.
    if (store.hasPendingContactWrites()) {
      assert(SPIFFS.exists("/contacts3") == existed);
      if (existed) assert(SPIFFS.files.at("/contacts3") == old);
    }
  }
  assert(SPIFFS.files.at("/contacts3") == image(h, filter));
  assert(!SPIFFS.exists("/contacts3.tmp"));
  assert(SPIFFS.missing_remove_logs == 0);
  return passes;
}

void bootCheck(const Host& expected, Filter filter = nullptr) {
  Host boot;
  DataStore after_reset(SPIFFS);
  after_reset.loadContacts(&boot);
  assert(!after_reset.hasIncompleteContactLoad());
  assert(image(boot) == image(expected, filter));
  assert(!after_reset.hasPendingContactWrites());
}

void boundedFullTableAndFirstSave() {
  SPIFFS = FakeFilesystem();
  Host h = table(350);
  for (unsigned i = 0; i < h.contacts.size(); i += 7) h.contacts[i].type = 0;
  DataStore store(SPIFFS);
  assert(store.markContactDirty(h.contacts[0]));
  const auto expected = image(h, keepContact);
  const auto passes = drain(store, h, keepContact);
  assert(passes > expected.size() / 64);
  assert(SPIFFS.largest_read <= 64);
  assert(SPIFFS.largest_write == mesh::storage::CONTACT_RECORD_SIZE);
  assert(SPIFFS.removes == 0); // first publication has no backup/temp to delete
  assert(h.copies >= h.contacts.size());
  bootCheck(h, keepContact);
}

void mutationRestart(unsigned phase) {
  SPIFFS = FakeFilesystem();
  Host h = table();
  SPIFFS.files["/contacts3"] = image(h);
  const auto old = SPIFFS.files.at("/contacts3");
  DataStore store(SPIFFS);
  assert(store.markContactDirty(h.contacts[0]));
  unsigned passes = 0;
  while ((phase == 0 && passes < 5)
      || (phase == 1 && (!store.verifying() || SPIFFS.reads == 0))
      || (phase == 2 && !store.readyToPublish())) {
    assert(++passes < 1000);
    assert(store.serviceContactWrites(&h, nullptr));
  }
  const auto removed = h.contacts[4];
  h.contacts.erase(h.contacts.begin() + 4);
  assert(store.releaseContact(removed));
  std::reverse(h.contacts.begin(), h.contacts.end());
  h.contacts[0] = contact(777);
  assert(store.markContactDirty(h.contacts[0]));
  assert(store.serviceContactWrites(&h, nullptr)); // discard obsolete job
  assert(store.hasPendingContactWrites());
  assert(!SPIFFS.exists("/contacts3.tmp"));
  assert(SPIFFS.files.at("/contacts3") == old);
  drain(store, h);
  bootCheck(h);
}

void faultAndRetry(unsigned fault) {
  SPIFFS = FakeFilesystem();
  Host h = table();
  SPIFFS.files["/contacts3"] = image(h);
  const auto old = SPIFFS.files.at("/contacts3");
  DataStore store(SPIFFS);
  h.contacts[2] = contact(888);
  assert(store.markContactDirty(h.contacts[2]));
  if (fault == 0) SPIFFS.max_write = 50;
  if (fault == 1) SPIFFS.fail_create = true;
  if (fault == 7) SPIFFS.metadata_error = true;
  bool injected = fault == 0 || fault == 1 || fault == 7;
  bool success = true;
  for (unsigned pass = 0; pass < 1000 && success; ++pass) {
    if (!injected && store.verifying()) {
      if (fault == 2) SPIFFS.fail_read = "/contacts3.tmp";
      if (fault == 3) SPIFFS.files.at("/contacts3.tmp")[20] ^= 1;
      if (fault == 4) SPIFFS.files.at("/contacts3.tmp").pop_back();
      if (fault <= 4) injected = true;
    }
    if (!injected && store.readyToPublish()) {
      SPIFFS.fail_rename = SPIFFS.renames + (fault == 5 ? 1 : 2);
      injected = true;
    }
    success = store.serviceContactWrites(&h, nullptr);
  }
  assert(injected && !success);
  assert(store.hasPendingContactWrites());
  assert(SPIFFS.files.at("/contacts3") == old);
  assert(!SPIFFS.exists("/contacts3.tmp"));
  assert(SPIFFS.missing_remove_logs == 0);
  SPIFFS.max_write = std::numeric_limits<size_t>::max();
  SPIFFS.fail_create = SPIFFS.metadata_error = false;
  SPIFFS.fail_read.clear();
  SPIFFS.fail_rename = 0;
  drain(store, h);
  bootCheck(h);
}

void syncFlushAndFilterChange() {
  SPIFFS = FakeFilesystem();
  Host h = table();
  SPIFFS.files["/contacts3"] = image(h);
  DataStore store(SPIFFS);
  assert(store.markContactDirty(h.contacts[0]));
  for (unsigned i = 0; i < 10; ++i) assert(store.serviceContactWrites(&h, nullptr));
  h.contacts[0] = contact(901);
  assert(store.markContactDirty(h.contacts[0]));
  assert(store.flushContactWrites(&h, keepEven));
  assert(!store.hasPendingContactWrites());
  assert(SPIFFS.files.at("/contacts3") == image(h, keepEven));
  bootCheck(h, keepEven);
  assert(store.markContactDirty(h.contacts[0]));
  for (unsigned i = 0; i < 10; ++i) assert(store.serviceContactWrites(&h, keepEven));
  assert(store.serviceContactWrites(&h, keepContact)); // changed filter cancels
  assert(store.hasPendingContactWrites() && !SPIFFS.exists("/contacts3.tmp"));
  drain(store, h, keepContact);
  bootCheck(h, keepContact);
  Host replacement = table(17);
  assert(store.markContactDirty(h.contacts[0]));
  for (unsigned i = 0; i < 10; ++i) assert(store.serviceContactWrites(&h, nullptr));
  assert(store.serviceContactWrites(&replacement, nullptr)); // changed host cancels
  assert(store.hasPendingContactWrites() && !SPIFFS.exists("/contacts3.tmp"));
  drain(store, replacement);
  bootCheck(replacement);
}

void realBackupCleanupFailure() {
  SPIFFS = FakeFilesystem();
  Host h = table();
  const auto old = image(h);
  SPIFFS.files["/contacts3"] = old;
  SPIFFS.files["/contacts3.bak"] = {42};
  DataStore store(SPIFFS);
  h.contacts[1] = contact(987);
  assert(store.markContactDirty(h.contacts[1]));
  SPIFFS.fail_remove = true;
  bool success = true;
  for (unsigned i = 0; i < 1000 && success; ++i) {
    success = store.serviceContactWrites(&h, nullptr);
  }
  assert(!success && store.hasPendingContactWrites());
  assert(SPIFFS.files.at("/contacts3") == old);
  assert(SPIFFS.files.at("/contacts3.bak") == std::vector<uint8_t>({42}));
  // Best-effort temp cleanup cannot hide the primary remove failure.
  assert(SPIFFS.exists("/contacts3.tmp") && SPIFFS.missing_remove_logs == 0);
  SPIFFS.fail_remove = false;
  drain(store, h);
  bootCheck(h);
}

void rebootAbortRecoveryAndDurableRemoval() {
  SPIFFS = FakeFilesystem();
  Host h = table();
  const auto old = image(h);
  SPIFFS.files["/contacts3"] = old;
  {
    DataStore store(SPIFFS);
    assert(store.markContactDirty(h.contacts[0]));
    for (unsigned i = 0; i < 7; ++i) assert(store.serviceContactWrites(&h, nullptr));
  } // CPU reset/destruction must abandon an incomplete lazy image.
  assert(SPIFFS.files.at("/contacts3") == old);
  assert(!SPIFFS.exists("/contacts3.tmp"));
  bootCheck(h);
  assert(SPIFFS.rename("/contacts3", "/contacts3.bak")); // interrupted publication
  bootCheck(h); // production load recovers the prior complete table
  {
    DataStore store(SPIFFS);
    const auto removed = h.contacts[8];
    h.contacts.erase(h.contacts.begin() + 8);
    assert(store.releaseContact(removed));
    drain(store, h);
  }
  bootCheck(h); // committed removal survives a new DataStore instance
  SPIFFS.fail_read = "/contacts3";
  Host incomplete;
  DataStore failed_boot(SPIFFS);
  failed_boot.loadContacts(&incomplete);
  assert(failed_boot.hasIncompleteContactLoad());
  const auto before = SPIFFS.files;
  assert(!failed_boot.serviceContactWrites(&incomplete, nullptr));
  assert(!failed_boot.flushContactWrites(&incomplete, nullptr));
  assert(SPIFFS.files == before);
}

void expectedAbsenceAndRealDeleteFailures() {
  SPIFFS = FakeFilesystem();
  DataStore store(SPIFFS);
  uint8_t key[32] = {1, 2, 3};
  char path[64];
  makeBlobPath(key, sizeof(key), path, sizeof(path));
  assert(store.deleteBlobByKey(key, sizeof(key)));
  assert(SPIFFS.removes == 0 && SPIFFS.missing_remove_logs == 0);
  SPIFFS.metadata_error = true;
  assert(!store.deleteBlobByKey(key, sizeof(key)));
  assert(SPIFFS.removes == 0);
  SPIFFS.metadata_error = false;
  SPIFFS.files[path] = {7, 8};
  SPIFFS.fail_remove = true;
  assert(!store.deleteBlobByKey(key, sizeof(key)));
  assert(SPIFFS.exists(path));
  SPIFFS.fail_remove = false;
  assert(store.deleteBlobByKey(key, sizeof(key)));
  assert(!SPIFFS.exists(path));
  assert(store.deleteBlobByKey(key, sizeof(key)));
  assert(SPIFFS.removes == 2 && SPIFFS.missing_remove_logs == 0);
  // Failed construction/destruction must not remove a temp that never existed.
  SPIFFS.fail_create = true;
  { mesh::ContactFileTransaction writer(&SPIFFS, "/empty", companionPathPresence);
    assert(!writer); }
  assert(SPIFFS.removes == 2 && SPIFFS.missing_remove_logs == 0);
  SPIFFS.metadata_error = true;
  { mesh::ContactFileTransaction writer(&SPIFFS, "/unreadable", companionPathPresence);
    assert(!writer); }
  assert(SPIFFS.removes == 2 && SPIFFS.missing_remove_logs == 0);
}

int main() {
  boundedFullTableAndFirstSave();
  for (unsigned phase = 0; phase < 3; ++phase) mutationRestart(phase);
  for (unsigned fault = 0; fault < 8; ++fault) faultAndRetry(fault);
  syncFlushAndFilterChange();
  realBackupCleanupFailure();
  rebootAbortRecoveryAndDurableRemoval();
  expectedAbsenceAndRealDeleteFailures();
}
