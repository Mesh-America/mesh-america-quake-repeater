// Compile the real implementation and transaction templates against metadata
// failures. The FS mock keeps SDK-internal namespace operations independent of
// caller-visible exists() so redundant source probes can be counted honestly.
#include <ClientACL.cpp>
#include <cstdio>
#include <cstdlib>

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); \
} } while (0)

static const char* P = mesh::CLIENT_ACL_PRIMARY_PATH;
static const char* T = mesh::CLIENT_ACL_TEMP_PATH;
static const char* B = mesh::CLIENT_ACL_BACKUP_PATH;
static mesh::LocalIdentity self;
static const uint8_t key[PUB_KEY_SIZE] = {0x12, 0x34};

static std::vector<uint8_t> crc_image(uint8_t value) {
  std::vector<uint8_t> bytes(201, value);
  const uint32_t crc = mesh::updateClientACLCRC(
      0xffffffffu, bytes.data(), bytes.size()) ^ 0xffffffffu;
  bytes.insert(bytes.end(), mesh::CLIENT_ACL_CRC_MAGIC,
               mesh::CLIENT_ACL_CRC_MAGIC + 4);
  const uint8_t* raw = reinterpret_cast<const uint8_t*>(&crc);
  bytes.insert(bytes.end(), raw, raw + sizeof(crc));
  return bytes;
}

static void admission_benchmark() {
  FakeFilesystem fs;
  ClientACL acl;
  acl.load(&fs, self);
  for (unsigned i = 0; i < 32; ++i) {
    uint8_t public_key[PUB_KEY_SIZE] = {};
    public_key[0] = uint8_t(i + 1);
    CHECK(acl.applyPermissions(self, public_key, PUB_KEY_SIZE,
        i == 0 ? PERM_ACL_ADMIN : PERM_ACL_READ_ONLY));
  }
  CHECK(acl.save(&fs));
  fs.exists_calls = 0;
  fs.read_open_count.clear();
  CHECK(acl.save(&fs));
  unsigned read_opens = 0;
  for (const auto& item : fs.read_open_count) read_opens += item.second;
  const unsigned existence_probes = fs.exists_calls;
  CHECK(fs.files[P].size() == 32 * 201 + 8);
  CHECK(validateContactsFileIntegrity(&fs, P));
  // Exclude this final assertion's extra reader from the benchmark count.
  std::printf("BENCH exists=%u reads=%u bytes=%zu\n",
      existence_probes, read_opens, fs.files[P].size());
}

#if !defined(ACL_METADATA_BENCHMARK_ONLY)
static void absent_and_error_are_distinct() {
  FakeFilesystem fs;
  acl_metadata::reset();
  bool present = true;
  CHECK(mesh::clientACLFilePresence(&fs, P, present) && !present);
  CHECK(fs.exists_calls == 0);
  acl_metadata::failures[P].insert(2);
  present = true;
  CHECK(!mesh::clientACLFilePresence(&fs, P, present) && present);
  CHECK(fs.remove_calls == 0 && fs.rename_calls == 0);
  bool metadata_ok = true;
  fs.metadata_error = true;
  CHECK(!openRead(&fs, P, &metadata_ok) && !metadata_ok);
  CHECK(fs.read_open_count.empty());
}

static void decisions_fail_before_mutation() {
  for (const char* failed : {P, B}) {
    FakeFilesystem fs;
    fs.files[P] = crc_image(0x11);
    fs.files[T] = crc_image(0x22);
    const auto before = fs.files;
    acl_metadata::reset();
    acl_metadata::failures[failed].insert(1);
    CHECK(!mesh::publishVerifiedClientACLTemp(&fs, true,
        validateContactsFileIntegrityChecked));
    CHECK(fs.files == before && fs.remove_calls == 0 && fs.rename_calls == 0);
  }
  FakeFilesystem fs;
  fs.files[P] = crc_image(0x11);
  fs.files[T] = crc_image(0x22);
  const auto before = fs.files;
  acl_metadata::reset();acl_metadata::failures[P].insert(1);
  CHECK(!mesh::recoverClientACLFiles(&fs));
  CHECK(fs.files == before && fs.remove_calls == 0 && fs.rename_calls == 0);
}

static void backup_error_cannot_make_legacy_valid_or_delete_primary() {
  FakeFilesystem fs;
  fs.files[P] = std::vector<uint8_t>(201, 0x11);
  fs.files[B] = crc_image(0x22);
  const auto before = fs.files;
  acl_metadata::reset();acl_metadata::failures[B].insert(1);
  CHECK(!mesh::recoverClientACLFilesVerified(&fs,
      validateContactsFileIntegrityChecked));
  CHECK(fs.files == before && fs.remove_calls == 0 && fs.rename_calls == 0);
  acl_metadata::reset();acl_metadata::failures[B].insert(1);
  CHECK(validateContactsFileIntegrityChecked(&fs, P)
      == mesh::ClientACLFileValidation::MetadataError);
  CHECK(fs.files == before);
}

static void missing_path_lookup_keeps_original_policy() {
  FakeFilesystem fs;
  ClientInfo client = {};
  client.out_path_is_persistable = false;
  client.out_path_len = 1;
  uint8_t previous[MAX_PATH_SIZE] = {};
  uint8_t length = OUT_PATH_UNKNOWN;
  bool metadata_ok = true;
  acl_metadata::reset();
  auto view = storedClientPathForSave(&fs, &client, previous, &length,
                                     &metadata_ok);
  CHECK(metadata_ok && view.encoded_path_len == OUT_PATH_UNKNOWN);
  CHECK(fs.missing_read_opens == 0);
}

static void stored_path_metadata_failure_never_publishes_unknown() {
  for (const std::set<unsigned>& faults : {
      std::set<unsigned>{3}, std::set<unsigned>{4}, std::set<unsigned>{3, 4}}) {
    FakeFilesystem fs;
    ClientACL acl;acl_metadata::reset();acl.load(&fs, self);
    CHECK(acl.applyPermissions(self, key, PUB_KEY_SIZE, PERM_ACL_ADMIN));
    auto* client = acl.getClient(key, PUB_KEY_SIZE);
    client->out_path_len = 1;client->out_path[0] = 0x5a;
    CHECK(acl.save(&fs));
    const auto original = fs.files[P];
    client->out_path_is_persistable = false;client->out_path[0] = 0x7b;
    fs.exists_calls = 0;fs.remove_calls = fs.rename_calls = 0;
    acl_metadata::reset();acl_metadata::failures[P] = faults;
    CHECK(!acl.save(&fs));
    CHECK(fs.files[P] == original && fs.rename_calls == 0);
    CHECK(fs.exists_calls == 0);
  }
}

static void postrename_error_rolls_back_only_with_confirmed_presence() {
  for (bool persistent : {false, true}) {
    FakeFilesystem fs;
    const auto old = crc_image(0x11), next = crc_image(0x22);
    fs.files[P] = old;fs.files[T] = next;
    acl_metadata::reset();acl_metadata::failures[P].insert(2);
    if (persistent) acl_metadata::failures[P].insert(3);
    CHECK(!mesh::publishVerifiedClientACLTemp(&fs, true,
        validateContactsFileIntegrityChecked));
    if (!persistent) {
      CHECK(fs.files[P] == old && !fs.files.count(B));
    } else {
      // A failed metadata probe is never absence. Keep both recoverable
      // artifacts when even rollback cannot prove the new target present.
      CHECK(fs.files[P] == next && fs.files[B] == old && fs.remove_calls == 0);
      acl_metadata::reset();
      CHECK(mesh::recoverClientACLFilesVerified(&fs,
          validateContactsFileIntegrityChecked));
      CHECK(fs.files[P] == next && !fs.files.count(B));
    }
  }
}

static void committed_primary_survives_cleanup_metadata_error() {
  FakeFilesystem fs;
  const auto old = crc_image(0x11), next = crc_image(0x22);
  fs.files[P] = old;fs.files[T] = next;
  acl_metadata::reset();acl_metadata::failures[B].insert(3);
  CHECK(mesh::publishVerifiedClientACLTemp(&fs, true,
      validateContactsFileIntegrityChecked));
  CHECK(fs.files[P] == next && fs.files[B] == old && fs.remove_calls == 0);
}

static void complete_readback_and_crc_checks_remain_required() {
  for (unsigned fault = 0; fault < 3; ++fault) {
    FakeFilesystem fs;ClientACL acl;acl_metadata::reset();acl.load(&fs, self);
    CHECK(acl.applyPermissions(self, key, PUB_KEY_SIZE, PERM_ACL_ADMIN));
    CHECK(acl.save(&fs));const auto old = fs.files[P];
    if (fault == 0) fs.corrupt_on_close = T;
    if (fault == 1) fs.write_budget = 3;
    if (fault == 2) fs.unreadable.insert(T);
    CHECK(!acl.save(&fs));CHECK(fs.files[P] == old);
  }
}
#endif

int main() {
#if !defined(ACL_METADATA_BENCHMARK_ONLY)
  absent_and_error_are_distinct();
  decisions_fail_before_mutation();
  backup_error_cannot_make_legacy_valid_or_delete_primary();
  missing_path_lookup_keeps_original_policy();
  stored_path_metadata_failure_never_publishes_unknown();
  postrename_error_rolls_back_only_with_confirmed_presence();
  committed_primary_survives_cleanup_metadata_error();
  complete_readback_and_crc_checks_remain_required();
  std::puts("ACL metadata failure checks passed");
#else
  admission_benchmark();
#endif
}
