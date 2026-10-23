// Integrated STM32WL has no tunable transport or acknowledged fast retune
// cache. Its shared boot hook must not inspect an irrelevant saved record.
#define main existing_cli_main
#include "cli_test.cpp"
#undef main

int main() {
  static_assert(MESH_RADIO_SWITCH_TUNING == 0, "Integrated STM32WL tuning must be absent");
  MemoryFS fs;
  Clock clock;
  Radio radio;
  const std::vector<uint8_t> record(24, 0x55);
  fs.files["/radio_fast"] = record;
  mesh::RadioProfileCLI::configureBootTuning(&fs, radio);
  assert(fs.opened_paths.empty());

  mesh::RadioProfileCLI cli;
  cli.begin(&fs, &radio, &clock);
  for (const auto& path : fs.opened_paths) assert(path.find("/radio_fast") != 0);
  fs.opened_paths.clear();
  cli.loop();
  char reply[160];
  for (const char* command : {"get radio.fast", "get radio.fast.spi", "get radio.fast.caps",
                             "set radio.fast on", "set radio.fast.spi 8"}) {
    assert(!cli.handle(command, reply, sizeof(reply)));
  }
  assert(fs.opened_paths.empty());
  assert(fs.files["/radio_fast"] == record);
  assert(fs.files.size() == 1);
  const auto capabilities = radio.switchTuningCapabilities();
  assert(capabilities.flags == 0 && capabilities.spi_clocks == 0);
  assert(!radio.configureBootSwitchTuning({}));
  assert(radio.trySetSwitchTuning({}) == mesh::RadioParamApplyResult::FAILED);
  // Existing radio2 configuration commands remain available.
  assert(cli.handle("get radio2", reply, sizeof(reply)));
  assert(!strncmp(reply, "> off", 5));
}
