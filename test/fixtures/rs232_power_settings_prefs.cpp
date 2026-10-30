struct Capture {
  std::vector<uint8_t> bytes;
  std::map<const void*, size_t> offsets;
  size_t write(const uint8_t* data, size_t size) {
    offsets[data] = bytes.size(); bytes.insert(bytes.end(), data, data + size); return size;
  }
  size_t offset(const void* field) const { return offsets.at(field); }
};
static void defaults(const NodePrefs& prefs) {
  assert(prefs.rs232_heartbeat == 1);
  assert(prefs.rs232_autosleep == 1);
  assert(prefs.rs232_idle_seconds == 300);
}
static void seed(CommonCLI& cli) {
  strcpy(cli.prefs.node_name, "UART power node");
  strcpy(cli.prefs.password, "same-secret");
  cli.prefs.bridge_uart = 2; cli.prefs.bridge_enabled = 1;
  cli.prefs.rs232_bridge_enabled = 1; cli.prefs.bridge_baud = 57600;
  setDefaultDirectRetryPrefs(&cli.prefs);
}
static void read(CommonCLI& cli, const std::vector<uint8_t>& image) {
  // Reused objects must not retain a previous opt-in after any failed read.
  cli.prefs.rs232_heartbeat = 0; cli.prefs.rs232_autosleep = 1;
  cli.prefs.rs232_idle_seconds = 3600;
  cli.fs.files["/com_prefs"] = image;
  cli.loadPrefsInt(&cli.fs, "/com_prefs");
  assert(strcmp(cli.prefs.node_name, "UART power node") == 0);
  assert(strcmp(cli.prefs.password, "same-secret") == 0);
  assert(cli.prefs.rs232_bridge_enabled == 1 && cli.prefs.bridge_uart == 2);
}
int main() {
  using namespace mesh::bridge;
  CommonCLI writer; seed(writer);
  defaults(writer.prefs);
  Capture baseline; assert(writeCommonPrefsImage(baseline, &writer.prefs));
  assert(rs232power::PREFS_SIZE == 10 && baseline.bytes.size() == 887);
  assert(baseline.offset(writer.prefs.node_name) == 4);
  assert(baseline.offset(&writer.prefs.freq) == 72);
  assert(baseline.offset(&writer.prefs.bridge_enabled) == 127);
  assert(baseline.offset(&writer.prefs.ota_channel) == 873);
  assert(baseline.bytes[875] == 1 && baseline.bytes[876] == 0xB1);
  assert(baseline.bytes[877] == 'R' && baseline.bytes[878] == 'S');
  CommonCLI reader;
  std::vector<uint8_t> legacy(baseline.bytes.begin(), baseline.bytes.begin() + 877);
  read(reader, legacy); defaults(reader.prefs);
  for (uint8_t heartbeat : {0, 1}) {
    for (uint8_t autosleep : {0, 1, 2}) {
      for (uint16_t idle : {60, 300, 3600}) {
        writer.prefs.rs232_heartbeat = heartbeat;
        writer.prefs.rs232_autosleep = autosleep;
        writer.prefs.rs232_idle_seconds = idle;
        writer.savePrefs(&writer.fs, PrefsSaveRouting::Scope::Common);
        assert(writer._common_save_succeeded);
        Capture checked; assert(writeCommonPrefsImage(checked, &writer.prefs));
        assert(checked.bytes == writer.fs.files.at("/com_prefs"));
        assert(checked.bytes.size() == baseline.bytes.size());
        for (size_t offset = 0; offset < 877; ++offset) {
          assert(checked.bytes[offset] == baseline.bytes[offset]);
        }
        read(reader, checked.bytes);
        assert(reader.prefs.rs232_heartbeat == heartbeat);
        assert(reader.prefs.rs232_autosleep == autosleep);
        assert(reader.prefs.rs232_idle_seconds == idle);
      }
    }
  }
  writer.prefs.rs232_heartbeat = 0; writer.prefs.rs232_autosleep = 1;
  writer.prefs.rs232_idle_seconds = 60;
  Capture current; assert(writeCommonPrefsImage(current, &writer.prefs));
  for (size_t length = 877; length < 887; ++length) {
    read(reader, {current.bytes.begin(), current.bytes.begin() + length});
    defaults(reader.prefs);
  }
  for (size_t offset = 877; offset < 887; ++offset) {
    auto bad = current.bytes; bad[offset] ^= 1;
    read(reader, bad); defaults(reader.prefs);
  }
  // Checked but unsupported versions/booleans/ranges are also fail-closed.
  for (auto entry : {std::pair<size_t, uint8_t>{880, 2}, {881, 2}, {882, 3},
                     {884, 0}, {883, 255}}) {
    auto bad = current.bytes; bad[entry.first] = entry.second;
    uint16_t crc = rs232heartbeat::checksum(bad.data() + 877, 8);
    bad[885] = crc >> 8; bad[886] = crc;
    read(reader, bad); defaults(reader.prefs);
  }
  for (int offset = 877; offset < 887; ++offset) {
    reader.fs.fail_read_after = offset;
    read(reader, current.bytes); defaults(reader.prefs);
  }
  reader.fs.fail_read_after = -1;
  reader.prefs.rs232_heartbeat = 0; reader.prefs.rs232_autosleep = 1;
  reader.prefs.rs232_idle_seconds = 3600;
  reader.loadPrefsInt(&reader.fs, "/missing"); defaults(reader.prefs);
  reader.fs.fail_read_open = true;
  reader.loadPrefsInt(&reader.fs, "/com_prefs"); defaults(reader.prefs);

  for (int fault = 0; fault < 6; ++fault) {
    for (int offset = 877; offset < 887; ++offset) {
      CommonCLI transaction; seed(transaction);
      transaction.savePrefs(&transaction.fs, PrefsSaveRouting::Scope::Common);
      assert(transaction._common_save_succeeded);
      const auto previous = transaction.fs.files.at("/com_prefs");
      transaction.prefs.rs232_heartbeat = 0; transaction.prefs.rs232_autosleep = 1;
      transaction.prefs.rs232_idle_seconds = 60;
      if (fault == 0) transaction.fs.fail_write = true;
      if (fault == 1) transaction.fs.fail_write_after = offset;
      if (fault == 2) transaction.fs.fail_read_open = true;
      if (fault == 3) {
#ifdef WITH_MQTT_BRIDGE
        continue; // Observer verifies reopened size; it does not re-read CRC bytes.
#else
        transaction.fs.fail_read_after = offset;
#endif
      }
      if (fault == 4) transaction.fs.fail_rename = 1;
      if (fault == 5) transaction.fs.fail_rename_from = {"/com_prefs.tmp"};
      assert(!transaction.trySavePrefs());
      assert(transaction.fs.files.at("/com_prefs") == previous);
      transaction.fs.fail_write = false; transaction.fs.fail_write_after = -1;
      transaction.fs.fail_read_open = false; transaction.fs.fail_read_after = -1;
      transaction.fs.fail_rename = 0; transaction.fs.fail_rename_from.clear();
      assert(transaction.recoverCommonPrefsFiles(&transaction.fs));
      read(transaction, previous); defaults(transaction.prefs);
    }
  }
}
