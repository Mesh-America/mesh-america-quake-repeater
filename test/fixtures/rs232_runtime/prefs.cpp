#include <fstream>
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

// The same executable can exchange actual serialized files with another profile.
// This catches role transitions which cannot be represented by a single macro set.
int main(int argc, char** argv) {
  if (argc > 1) {
    assert(argc == 7);
    CommonCLI cli;
    const bool writing = strcmp(argv[1], "write") == 0;
    if (writing) {
      cli.prefs.bridge_enabled = atoi(argv[3]);
      cli.prefs.espnow_bridge_enabled = atoi(argv[4]);
      cli.prefs.rs232_bridge_enabled = atoi(argv[5]);
      cli.prefs.bridge_uart = 2;
      cli.savePrefs(&cli.fs, PrefsSaveRouting::Scope::Common);
      assert(cli._common_save_succeeded);
      const auto& image = cli.fs.files.at("/com_prefs");
      std::ofstream stream(argv[2], std::ios::binary);
      stream.write(reinterpret_cast<const char*>(image.data()), image.size());
      assert(stream.good());
    } else {
      std::ifstream stream(argv[2], std::ios::binary);
      assert(stream.good());
      cli.fs.files["/com_prefs"] = std::vector<uint8_t>(
          std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
      cli.loadPrefsInt(&cli.fs, "/com_prefs");
      assert(cli.prefs.bridge_enabled == atoi(argv[3]));
      assert(cli.prefs.espnow_bridge_enabled == atoi(argv[4]));
      assert(cli.prefs.rs232_bridge_enabled == atoi(argv[5]));
      assert(cli.prefs.bridge_uart == atoi(argv[6]));
    }
    return 0;
  }
  CommonCLI writer;
  strcpy(writer.prefs.node_name, "Combined repeater");
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
  const size_t esp_marker_offset = channel_offset + 1;
  const size_t rs_intent_offset = initial.offset(&writer.prefs.rs232_bridge_enabled);
  const size_t rs_marker_offset = channel_offset + 3;
  assert(initial.bytes.size() == 877 && channel_offset == 873);
  assert(rs_intent_offset == channel_offset + 2);
#ifdef ESPNOW_BRIDGE_MERGED
  assert(initial.bytes[esp_marker_offset] == 0xA1);
#else
  assert(initial.bytes[esp_marker_offset] == 0);
#endif
#ifdef WITH_RS232_BRIDGE
  assert(initial.bytes[rs_marker_offset] == 0xB1);
#else
  assert(initial.bytes[rs_marker_offset] == 0);
#endif
  assert(initial.offset(writer.prefs.node_name) == 4);
  assert(initial.offset(&writer.prefs.freq) == 72);
  assert(enabled_offset == 127);

  for (uint8_t primary : {uint8_t{0}, uint8_t{1}}) {
    for (uint8_t secondary : {uint8_t{0}, uint8_t{1}}) {
      for (uint8_t uart_intent : {uint8_t{0}, uint8_t{1}}) {
        writer.prefs.bridge_enabled = primary;
        writer.prefs.espnow_bridge_enabled = secondary;
        writer.prefs.rs232_bridge_enabled = uart_intent;
        writer.savePrefs(&writer.fs, PrefsSaveRouting::Scope::Common);
        assert(writer._common_save_succeeded);
        const auto image = writer.fs.files.at("/com_prefs");
        Capture checked;
        assert(writeCommonPrefsImage(checked, &writer.prefs));
        assert(checked.bytes == image); // Checked and ordinary writers agree.
        CommonCLI reader;
        reader.fs.files["/com_prefs"] = image;
        reader.loadPrefsInt(&reader.fs, "/com_prefs");
#if defined(ESPNOW_BRIDGE_MERGED) && !defined(WITH_RS232_BRIDGE) && !defined(WITH_MQTT_BRIDGE)
        assert(reader.prefs.bridge_enabled == secondary);
#else
        assert(reader.prefs.bridge_enabled == primary);
#endif
        assert(reader.prefs.espnow_bridge_enabled == secondary);
#ifdef WITH_RS232_BRIDGE
        assert(reader.prefs.bridge_uart == 2);
#ifdef WITH_MQTT_BRIDGE
        assert(reader.prefs.rs232_bridge_enabled == uart_intent);
#else
        assert(reader.prefs.rs232_bridge_enabled == primary);
#endif
#else
        assert(reader.prefs.bridge_uart == 0 && reader.prefs.rs232_bridge_enabled == 0);
#endif
        assert(reader.prefs.bridge_baud == 57600 && reader.prefs.bridge_channel == 6);
        assert(strcmp(reader.prefs.node_name, writer.prefs.node_name) == 0);
        assert(strcmp(reader.prefs.bridge_secret, "test-secret") == 0);
      }
    }
  }
  writer.prefs.bridge_enabled = 1;
  writer.prefs.espnow_bridge_enabled = 1;
  writer.prefs.rs232_bridge_enabled = 1;
  writer.savePrefs(&writer.fs, PrefsSaveRouting::Scope::Common);
  assert(writer._common_save_succeeded);
  const auto on = writer.fs.files.at("/com_prefs");

#ifdef WITH_RS232_BRIDGE
  // Unmarked previous MQTT files cannot prove UART intent, even when they
  // contain UART2 and primary enabled. Dedicated UART profiles retain context.
  for (size_t length : {uart_offset, esp_marker_offset, rs_intent_offset}) {
    auto old = on; old.resize(length);
    CommonCLI reader;
    reader.fs.files["/com_prefs"] = old;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
#ifdef WITH_MQTT_BRIDGE
    assert(reader.prefs.bridge_enabled == 1 && reader.prefs.rs232_bridge_enabled == 0);
#elif defined(RS232_BRIDGE_MERGED) && !defined(RS232_BRIDGE_DEFAULT_ON)
    const bool legacy_uart_present = length > uart_offset;
    assert(reader.prefs.bridge_enabled == legacy_uart_present);
    assert(reader.prefs.rs232_bridge_enabled == legacy_uart_present);
#endif
    assert(reader.prefs.bridge_uart == 2 && reader._com_prefs_needs_upgrade);
  }
  // A partial new tail, invalid marker or invalid boolean must never fall back
  // to a different transport's primary setting. Short reads fail closed too.
  for (unsigned invalid = 0; invalid <= 255; ++invalid) {
    if (invalid == 0xB1) continue;
    CommonCLI reader;
    auto corrupt = on; corrupt[rs_marker_offset] = static_cast<uint8_t>(invalid);
    reader.fs.files["/com_prefs"] = corrupt;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.rs232_bridge_enabled == 0 && reader._com_prefs_needs_upgrade);
#ifdef WITH_MQTT_BRIDGE
    assert(reader.prefs.bridge_enabled == 1);
#else
    assert(reader.prefs.bridge_enabled == 0);
#endif
  }
  for (unsigned invalid = 2; invalid <= 255; ++invalid) {
    CommonCLI reader;
    auto corrupt = on; corrupt[rs_intent_offset] = static_cast<uint8_t>(invalid);
    reader.fs.files["/com_prefs"] = corrupt;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.rs232_bridge_enabled == 0);
  }
  for (size_t fault : {rs_intent_offset, rs_marker_offset}) {
    CommonCLI reader;
    reader.fs.files["/com_prefs"] = on;
    reader.fs.fail_read_after = static_cast<int>(fault);
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.rs232_bridge_enabled == 0);
  }
  CommonCLI torn;
  torn.fs.files["/com_prefs"] = {on.begin(), on.begin() + rs_marker_offset};
  torn.loadPrefsInt(&torn.fs, "/com_prefs");
  assert(torn.prefs.rs232_bridge_enabled == 0);
#if defined(RS232_BRIDGE_MERGED) && !defined(WITH_MQTT_BRIDGE)
  // Old Serial2 builds saved the generic UART1 fallback; known UART2 remains
  // the safe resolved port, without losing a valid new independent intent.
  auto dedicated = on; dedicated[uart_offset] = 1;
  CommonCLI legacy_reader;
  legacy_reader.fs.files["/com_prefs"] = dedicated;
  legacy_reader.loadPrefsInt(&legacy_reader.fs, "/com_prefs");
  assert(legacy_reader.prefs.bridge_enabled == 1 && legacy_reader.prefs.bridge_uart == 2);
#endif
#endif

#if defined(ESPNOW_BRIDGE_MERGED) && !defined(ESPNOW_BRIDGE_DEFAULT_ON)
  for (unsigned invalid = 0; invalid <= 255; ++invalid) {
    if (invalid == 0xA1) continue;
    auto old = on; old[esp_marker_offset] = static_cast<uint8_t>(invalid);
    CommonCLI reader;
    reader.fs.files["/com_prefs"] = old;
    reader.loadPrefsInt(&reader.fs, "/com_prefs");
    assert(reader.prefs.espnow_bridge_enabled == 0);
#if !defined(WITH_RS232_BRIDGE) && !defined(WITH_MQTT_BRIDGE)
    assert(reader.prefs.bridge_enabled == 0);
#else
    assert(reader.prefs.bridge_enabled == 1);
#endif
    assert(reader._com_prefs_needs_upgrade);
  }
  auto old = on; old.resize(esp_marker_offset);
  CommonCLI reader;
  reader.fs.files["/com_prefs"] = old;
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.espnow_bridge_enabled == 0);
  reader.fs.files["/com_prefs"] = on;
  reader.fs.fail_read_after = static_cast<int>(esp_marker_offset);
  reader.loadPrefsInt(&reader.fs, "/com_prefs");
  assert(reader.prefs.espnow_bridge_enabled == 0);
#endif
  // Every append boundary must commit atomically for observer and plain writers.
  for (size_t fault : {esp_marker_offset, rs_intent_offset, rs_marker_offset}) {
    const auto previous = writer.fs.files.at("/com_prefs");
    writer.fs.fail_write_after = static_cast<int>(fault);
    writer.prefs.rs232_bridge_enabled = 0;
    assert(!writer.trySavePrefs());
    assert(writer.fs.files.at("/com_prefs") == previous);
    writer.fs.fail_write_after = -1;
  }
}
