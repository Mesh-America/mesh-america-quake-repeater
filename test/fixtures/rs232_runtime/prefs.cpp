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

int main() {
  CommonCLI writer;
  strcpy(writer.prefs.node_name, "MKE combined repeater");
  strcpy(writer.prefs.password, "test-password");
  writer.prefs.bridge_uart = 2;
  writer.prefs.bridge_baud = 57600;
  writer.prefs.bridge_channel = 6;
  strcpy(writer.prefs.bridge_secret, "test-secret");
  Capture initial;
  assert(writeCommonPrefsImage(initial, &writer.prefs));
  const size_t uart_offset = initial.offset(&writer.prefs.bridge_uart);
  const size_t enabled_offset = initial.offset(&writer.prefs.bridge_enabled);
  const size_t channel_offset = initial.offset(&writer.prefs.ota_channel);
#ifdef ESPNOW_BRIDGE_MERGED
  assert(initial.bytes.size() == 875 && initial.bytes.back() == 0xA1);
  const size_t marker_offset = channel_offset + 1;
  assert(marker_offset == initial.bytes.size() - 1);
#else
  assert(initial.bytes.size() == 874 && channel_offset == initial.bytes.size() - 1);
#endif
  assert(initial.offset(writer.prefs.node_name) == 4);
  assert(initial.offset(&writer.prefs.freq) == 72);
  assert(initial.offset(&writer.prefs.bridge_enabled) == 127);

  for (uint8_t primary : {uint8_t{0}, uint8_t{1}}) {
    for (uint8_t secondary : {uint8_t{0}, uint8_t{1}}) {
      writer.prefs.bridge_enabled = primary;
      writer.prefs.espnow_bridge_enabled = secondary;
      writer.savePrefs(&writer.fs, PrefsSaveRouting::Scope::Common);
      assert(writer._common_save_succeeded);
      const auto image = writer.fs.files.at("/com_prefs");
      Capture checked;
      assert(writeCommonPrefsImage(checked, &writer.prefs));
      assert(checked.bytes == image); // Checked and ordinary writers agree.
      CommonCLI reader;
      reader.fs.files["/com_prefs"] = image;
      reader.loadPrefsInt(&reader.fs, "/com_prefs");
      assert(reader.prefs.bridge_enabled == primary);
      assert(reader.prefs.espnow_bridge_enabled == secondary);
#ifdef WITH_RS232_BRIDGE
      assert(reader.prefs.bridge_uart == 2);
#else
      assert(reader.prefs.bridge_uart == 0);
#endif
      assert(reader.prefs.bridge_baud == 57600 && reader.prefs.bridge_channel == 6);
      assert(strcmp(reader.prefs.node_name, writer.prefs.node_name) == 0);
      assert(strcmp(reader.prefs.bridge_secret, "test-secret") == 0);
    }
  }
  writer.prefs.bridge_enabled = 1;
  writer.prefs.espnow_bridge_enabled = 1;
  Capture on;
  assert(writeCommonPrefsImage(on, &writer.prefs));

#ifdef RS232_BRIDGE_MERGED
  // Missing UART tails and current no-bridge zero sentinels both fail safe.
  for (bool missing_tail : {false, true}) {
    auto old = on.bytes;
    if (missing_tail) old.resize(uart_offset);
    else old[uart_offset] = 0;
    assert(old[enabled_offset] == 1);
    CommonCLI reader;
    reader.fs.files["/com_prefs"] = old;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.bridge_enabled == 0 && reader.prefs.bridge_uart == 2);
    assert(reader._com_prefs_needs_upgrade);
  }
  // Older dedicated MKE builds selected Serial2 but persisted the UART1 fallback.
  auto dedicated = on.bytes;
  dedicated[uart_offset] = 1;
  CommonCLI legacy_reader;
  legacy_reader.fs.files["/com_prefs"] = dedicated;
  legacy_reader.loadPrefsInt(&legacy_reader.fs, "/com_prefs");
  assert(legacy_reader.prefs.bridge_enabled == 1 && legacy_reader.prefs.bridge_uart == 2);
#endif

#ifdef ESPNOW_BRIDGE_MERGED
  for (unsigned invalid = 0; invalid <= 255; ++invalid) {
    if (invalid == 0xA1) continue;
    auto old = on.bytes;
    old[marker_offset] = static_cast<uint8_t>(invalid);
    CommonCLI reader;
    reader.fs.files["/com_prefs"] = old;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.espnow_bridge_enabled == 0);
    assert(reader.prefs.bridge_enabled == 1 && reader._com_prefs_needs_upgrade);
  }
  // Old 874-byte profiles saved the unused secondary flag as one. It is not intent.
  auto old = on.bytes;
  old.resize(marker_offset);
  CommonCLI reader;
  reader.fs.files["/com_prefs"] = old;
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.espnow_bridge_enabled == 0 && reader.prefs.bridge_enabled == 1);
  reader.fs.files["/com_prefs"] = on.bytes;
  reader.fs.fail_read_after = static_cast<int>(marker_offset);
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.espnow_bridge_enabled == 0);

  // A torn append must retain the previous durable settings image.
  writer.savePrefs(&writer.fs, PrefsSaveRouting::Scope::Common);
  assert(writer._common_save_succeeded);
  const auto previous = writer.fs.files.at("/com_prefs");
  writer.fs.fail_write_after = static_cast<int>(marker_offset);
  writer.prefs.espnow_bridge_enabled = 0;
  assert(!writer.trySavePrefs());
  assert(writer.fs.files.at("/com_prefs") == previous);
#endif
}
