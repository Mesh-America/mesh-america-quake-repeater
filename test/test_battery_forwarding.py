"""Run the production battery forwarding policy, CLI and record under sanitizers."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
PREFIX = r'''
#include <helpers/BatteryForwarding.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>
using namespace mesh::batteryforward;

static bool same(const Settings& a, const Settings& b) {
  return a.enabled == b.enabled && a.repeatBelow == b.repeatBelow
      && a.floodBelow == b.floodBelow && a.emptyMv == b.emptyMv && a.fullMv == b.fullMv;
}

struct CLI {
  Settings settings;
  State state;
  Settings saved;
  bool saveOk = true;
  bool external = false;
  unsigned saveCalls = 0;
  uint16_t empty = 3000, full = 4200;
  char reply[192] = {};

  bool run(const char* command) {
    strcpy(reply, "untouched");
    return handleCommand(settings, state, empty, full, external, command,
                         reply, sizeof(reply), [&](const Settings& candidate) {
      ++saveCalls; saved = candidate; return saveOk;
    });
  }
  void ok(const char* command) {
    const unsigned before = saveCalls;
    assert(run(command));
    assert(strcmp(reply, "OK - saved") == 0 && saveCalls == before + 1);
    assert(same(settings, saved));
  }
  void error(const char* command) {
    const Settings before = settings;
    const unsigned calls = saveCalls;
    assert(run(command));
    assert(strncmp(reply, "Error:", 6) == 0);
    assert(same(settings, before) && saveCalls == calls);
  }
};
'''


class BatteryForwardingTests(unittest.TestCase):
    def exercise(self, body, prefix=PREFIX, flags=()):
        with tempfile.TemporaryDirectory(prefix="battery-forwarding-") as folder:
            work = Path(folder)
            source, binary = work / "main.cpp", work / "check"
            source.write_text(prefix + "\nint main() {\n" + body + "\n}\n", encoding="ascii")
            command = [os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-g",
                       "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                       *flags, "-I", str(ROOT / "src"), str(source), "-o", str(binary)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def runtime_prefix(self, extra_members=""):
        """Keep the production admission/sampling/CLI methods; fake only board/save boundaries."""
        source = (ROOT / "src/helpers/CommonCLI_Battery.cpp").read_text(encoding="ascii")
        methods = "\n".join(extract_braced(source, signature) for signature in (
            "uint16_t CommonCLI::batteryEmptyMv(", "uint16_t CommonCLI::batteryFullMv(",
            "uint8_t CommonCLI::batteryPercent(", "bool CommonCLI::batteryAllowsTransmit(",
            "bool CommonCLI::batteryAllowsForward(", "void CommonCLI::loopBatteryForwarding(",
            "bool CommonCLI::handleBatteryForwardingCommand("))
        return PREFIX + r'''
static uint32_t nowMs = 0;
static uint32_t millis() { return nowMs; }
namespace mesh {
struct Packet {
  bool forwarded = false, flood = false;
  bool isRouteFlood() const { return flood; }
};
namespace power {
static uint16_t configuredEmptyMv = 6000, configuredFullMv = 8400;
static uint16_t configuredEmpty() { return configuredEmptyMv; }
static uint16_t configuredFull() { return configuredFullMv; }
}
}
struct Board {
  uint16_t mv = 3000;
  unsigned reads = 0;
  float multiplier = 1.0f;
  bool adcSupported = true;
  uint16_t getBattMilliVolts() { ++reads; return uint16_t(float(mv) * multiplier); }
  bool setAdcMultiplier(float value) {
    if (!adcSupported) return false;
    multiplier = value == 0.0f ? 1.0f : value;
    return true;
  }
};
struct CommonCLI {
  Board* _board;
  Settings _battery_forward_settings;
  mutable State _battery_forward_state;
  bool saveOk = true;
  unsigned saveCalls = 0;
  Settings saved;
  explicit CommonCLI(Board& board) : _board(&board) {}
  bool saveBatteryForwarding(const Settings& settings) {
    ++saveCalls; saved = settings; return saveOk;
  }
  uint16_t batteryEmptyMv() const;
  uint16_t batteryFullMv() const;
  uint8_t batteryPercent(uint16_t mv) const;
  bool batteryAllowsTransmit(const mesh::Packet* packet) const;
  bool batteryAllowsForward(bool flood) const;
  void loopBatteryForwarding(bool force = false) const;
  bool handleBatteryForwardingCommand(const char* command, char* reply);
  EXTRA_MEMBERS
};
'''.replace("EXTRA_MEMBERS", extra_members) + methods

    def test_actual_set_command_voltage_policy_branch_refreshes_profile_endpoints_and_calibration(self):
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="ascii")
        setter = extract_braced(source, "void CommonCLI::handleSetCmd(")
        branch = extract_braced(setter, "if (mesh::power::handleVoltagePolicyCommand(")
        prefix = self.runtime_prefix("void dispatchVoltage(char* command, char* reply);")
        prefix += r'''
namespace mesh { namespace power {
static bool voltageSaveOk = true;
static unsigned voltageSaves = 0;
static Board* calibratedBoard = nullptr;
// This is the existing voltage-policy parser/save boundary. The dispatch block
// and battery refresh below are extracted unchanged from production.
static bool handleVoltagePolicyCommand(const char* command, char* reply, size_t capacity) {
  uint16_t empty = configuredEmptyMv, full = configuredFullMv;
  float calibration = calibratedBoard->multiplier;
  if (strcmp(command, "set battery.profile lifepo4") == 0) { empty = 2700; full = 3550; }
  else if (strcmp(command, "set battery.full 4200") == 0) full = 4200;
  else if (strcmp(command, "set battery.empty 3300") == 0) empty = 3300;
  else if (strcmp(command, "set adc.multiplier 1.2") == 0) calibration = 1.2f;
  else if (strcmp(command, "set adc.multiplier 1.0") == 0) calibration = 1.0f;
  else return false;
  ++voltageSaves;
  if (!voltageSaveOk) snprintf(reply, capacity, "Error: voltage setting could not be saved");
  else {
    configuredEmptyMv = empty; configuredFullMv = full;
    calibratedBoard->multiplier = calibration;
    snprintf(reply, capacity, "OK - saved");
  }
  return true;
}
}}
void CommonCLI::dispatchVoltage(char* command, char* reply) {
''' + branch + r'''
  strcpy(reply, "fallthrough");
}
'''
        self.exercise(r'''
  Board board;
  board.mv = 3500;
  CommonCLI cli(board);
  mesh::power::calibratedBoard = &board;
  mesh::power::configuredEmptyMv = 3000;
  mesh::power::configuredFullMv = 4200;
  cli._battery_forward_settings.enabled = Repeat;
  cli._battery_forward_settings.repeatBelow = 60;
  nowMs = 100;
  assert(!cli.batteryAllowsForward(false) && board.reads == 1);
  assert(cli._battery_forward_state.percentage == 41);
  char reply[160];
  auto dispatch = [&](const char* text) {
    char command[80]; strcpy(command, text);
    nowMs += 1; // Every command is much earlier than the 30-second sample expiry.
    cli.dispatchVoltage(command, reply);
    assert(strncmp(reply, "OK", 2) == 0);
  };
  dispatch("set battery.profile lifepo4");
  assert(board.reads == 2 && cli._battery_forward_state.percentage == 94);
  assert(cli._battery_forward_state.sampledAt == nowMs && cli.batteryAllowsForward(false));
  dispatch("set battery.full 4200");
  assert(board.reads == 3 && cli._battery_forward_state.percentage == 53);
  assert(!cli.batteryAllowsForward(false));
  dispatch("set battery.empty 3300");
  assert(board.reads == 4 && cli._battery_forward_state.percentage == 22);
  assert(!cli.batteryAllowsForward(false));
  dispatch("set adc.multiplier 1.2");
  assert(board.reads == 5 && cli._battery_forward_state.millivolts == 4200);
  assert(cli._battery_forward_state.percentage == 100 && cli.batteryAllowsForward(false));
  mesh::power::voltageSaveOk = false;
  const uint32_t sampledAt = cli._battery_forward_state.sampledAt;
  char failed[] = "set adc.multiplier 1.0";
  ++nowMs;
  cli.dispatchVoltage(failed, reply);
  assert(strncmp(reply, "Error:", 6) == 0 && board.reads == 5);
  assert(mesh::power::voltageSaves == 5 && board.multiplier == 1.2f);
  assert(cli._battery_forward_state.sampledAt == sampledAt && cli.batteryAllowsForward(false));
  char unknown[] = "set unrelated on";
  cli.dispatchVoltage(unknown, reply);
  assert(strcmp(reply, "fallthrough") == 0 && board.reads == 5);
''', prefix=prefix, flags=("-DNRF52_PLATFORM", "-DNRF52_POWER_MANAGEMENT"))

    def test_actual_set_command_adc_branch_resamples_success_and_skips_rejected_changes(self):
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="ascii")
        setter = extract_braced(source, "void CommonCLI::handleSetCmd(")
        branch = extract_braced(setter, 'if (memcmp(config, "adc.multiplier ", 15) == 0)')
        utils = (ROOT / "src/helpers/CLICommandUtils.h").read_text(encoding="ascii")
        parser = extract_braced(utils, "inline bool parseDecimalStrict(")
        prefix = self.runtime_prefix(r'''
  struct Prefs { float adc_multiplier = 0.0f; } prefs;
  Prefs* _prefs = &prefs;
  unsigned prefsSaves = 0;
  void savePrefs() { ++prefsSaves; }
  void dispatchAdc(char* command, char* reply);
''')
        prefix += "\nnamespace mesh { namespace cli {\n" + parser + "\n}}\n"
        prefix += "void CommonCLI::dispatchAdc(char* command, char* reply) {\n"
        prefix += "const char* config = &command[4];\n" + branch + "\n}\n"
        self.exercise(r'''
  Board board;
  board.mv = 3500;
  CommonCLI cli(board);
  cli._battery_forward_settings.enabled = Repeat;
  cli._battery_forward_settings.repeatBelow = 60;
  nowMs = 100;
  assert(!cli.batteryAllowsForward(false) && board.reads == 1);
  assert(cli._battery_forward_state.percentage == 41);
  char reply[160];
  char calibrate[] = "set adc.multiplier 1.2";
  ++nowMs;
  cli.dispatchAdc(calibrate, reply);
  assert(strncmp(reply, "OK", 2) == 0 && cli.prefsSaves == 1 && board.reads == 2);
  assert(cli.prefs.adc_multiplier == 1.2f && cli._battery_forward_state.millivolts == 4200);
  assert(cli._battery_forward_state.sampledAt == nowMs && cli.batteryAllowsForward(false));
  char malformed[] = "set adc.multiplier 1.2junk";
  cli.dispatchAdc(malformed, reply);
  assert(strncmp(reply, "Error:", 6) == 0 && cli.prefsSaves == 1 && board.reads == 2);
  board.adcSupported = false;
  char unsupported[] = "set adc.multiplier 1.0";
  cli.dispatchAdc(unsupported, reply);
  assert(strcmp(reply, "Error: unsupported") == 0 && cli.prefsSaves == 1 && board.reads == 2);
  assert(cli.prefs.adc_multiplier == 1.2f && cli.batteryAllowsForward(false));
  board.adcSupported = true;
  char reset[] = "set adc.multiplier 0";
  cli.dispatchAdc(reset, reply);
  assert(strcmp(reply, "OK - using default board multiplier") == 0);
  assert(cli.prefsSaves == 2 && board.reads == 3 && cli._battery_forward_state.percentage == 41);
  assert(!cli.batteryAllowsForward(false));
''', prefix=prefix, flags=("-DESP32_PLATFORM",))

    def test_actual_status_whitespace_forces_fresh_sample_but_invalid_suffix_does_not(self):
        self.exercise(r'''
  Board board;
  CommonCLI cli(board);
  char reply[157];
  board.mv = 4200;
  assert(cli.handleBatteryForwardingCommand("get battery.forward \t", reply));
  assert(board.reads == 1 && strstr(reply, "battery=100% mv=4200"));
  board.mv = 3000;
  assert(cli.handleBatteryForwardingCommand("get battery.forward x", reply));
  assert(strncmp(reply, "Error:", 6) == 0 && board.reads == 1);
  assert(!cli.handleBatteryForwardingCommand("get battery.forwarder", reply) && board.reads == 1);
  assert(cli.handleBatteryForwardingCommand("get battery.forward\t", reply));
  assert(board.reads == 2 && strstr(reply, "battery=0% mv=3000"));
  assert(cli.saveCalls == 0);
''', prefix=self.runtime_prefix(), flags=("-DESP32_PLATFORM",))

    def test_actual_runtime_admission_samples_before_first_packet_and_after_30_seconds(self):
        self.exercise(r'''
  Board board;
  CommonCLI cli(board);
  mesh::Packet own, relayed;
  own.flood = true; relayed.forwarded = true;
  const CommonCLI& admission = cli;
  for (unsigned i = 0; i < 5; ++i) {
    cli.loopBatteryForwarding();
    assert(admission.batteryAllowsForward(false));
    assert(admission.batteryAllowsForward(true));
  }
  assert(board.reads == 0 && !cli._battery_forward_state.sampled);
  cli._battery_forward_settings.enabled = Repeat | Flood;
  board.mv = 3108; // 9 percent: both policies must be applied before the CLI loop runs.
  nowMs = 100;
  assert(admission.batteryAllowsTransmit(nullptr) && admission.batteryAllowsTransmit(&own));
  assert(board.reads == 0); // Locally owned traffic never invokes the relay battery gate.
  assert(!admission.batteryAllowsTransmit(&relayed) && board.reads == 1);
  assert(cli._battery_forward_state.sampledAt == 100 && cli._battery_forward_state.percentage == 9);
  relayed.flood = true;
  assert(!admission.batteryAllowsTransmit(&relayed) && board.reads == 1);
  nowMs = 30099;
  board.mv = 4200;
  cli.loopBatteryForwarding();
  assert(!admission.batteryAllowsForward(false) && board.reads == 1);
  nowMs = 30100;
  assert(admission.batteryAllowsTransmit(&relayed) && board.reads == 2);
  assert(cli._battery_forward_state.sampledAt == 30100 && cli._battery_forward_state.percentage == 100);
  cli.loopBatteryForwarding();
  assert(admission.batteryAllowsForward(false) && board.reads == 2);
  nowMs = 200000; // The next retry must refresh after a long sleep, before the main CLI loop.
  board.mv = 3108;
  assert(!admission.batteryAllowsTransmit(&relayed) && board.reads == 3);
  assert(admission.batteryAllowsTransmit(&own) && admission.batteryAllowsTransmit(nullptr));
  assert(board.reads == 3);
''', prefix=self.runtime_prefix(), flags=("-DESP32_PLATFORM",))

    def test_actual_runtime_cli_immediately_resamples_saved_policy_and_status(self):
        self.exercise(r'''
  Board board;
  board.mv = 3300; // 25 percent with the ordinary 3000/4200 endpoints.
  CommonCLI cli(board);
  char reply[157];
  nowMs = 123;
  assert(cli.handleBatteryForwardingCommand("set repeat.battery 30", reply));
  assert(strcmp(reply, "OK - saved") == 0 && board.reads == 1 && cli.saveCalls == 1);
  assert(!cli.batteryAllowsForward(false) && !cli.batteryAllowsForward(true) && board.reads == 1);
  board.mv = 4200;
  assert(cli.handleBatteryForwardingCommand("get battery.forward", reply));
  assert(strstr(reply, "battery=100% mv=4200 repeat=allowed flood=allowed"));
  assert(board.reads == 2 && cli.saveCalls == 1);
  board.mv = 3108;
  cli.saveOk = false;
  assert(cli.handleBatteryForwardingCommand("set repeat.battery off", reply));
  assert(strstr(reply, "save unconfirmed") && board.reads == 2 && cli.saveCalls == 2);
  assert(cli._battery_forward_settings.enabled == Repeat && cli._battery_forward_state.percentage == 100);
  cli.saveOk = true;
  assert(cli.handleBatteryForwardingCommand("set repeat.battery off", reply));
  assert(board.reads == 3 && cli._battery_forward_settings.enabled == 0);
  assert(cli.batteryAllowsForward(false) && cli.batteryAllowsForward(true));
  nowMs += 100000;
  cli.loopBatteryForwarding();
  assert(board.reads == 3); // Disabled policies do not poll the ADC.
  assert(cli.handleBatteryForwardingCommand("set flood.battery 20", reply));
  assert(board.reads == 4 && cli._battery_forward_state.percentage == 9);
  mesh::Packet direct, flood, own;
  direct.forwarded = flood.forwarded = true;
  flood.flood = own.flood = true;
  assert(cli.batteryAllowsTransmit(&direct));
  assert(!cli.batteryAllowsTransmit(&flood));
  assert(cli.batteryAllowsTransmit(&own));
  // A missing or impossible battery reading immediately removes both gates.
  board.mv = 0;
  assert(cli.handleBatteryForwardingCommand("get battery.forward", reply));
  assert(strstr(reply, "battery=unknown mv=0 repeat=allowed flood=allowed"));
  assert(cli.batteryAllowsTransmit(&flood) && board.reads == 5);
''', prefix=self.runtime_prefix(), flags=("-DESP32_PLATFORM",))

    def test_actual_runtime_custom_voltage_endpoints_resample_and_compiled_two_cell_defaults(self):
        self.exercise(r'''
  Board board;
  CommonCLI cli(board);
  board.mv = 7200;
  assert(cli.batteryEmptyMv() == 6000 && cli.batteryFullMv() == 8400);
  assert(cli.batteryPercent(board.mv) == 50);
  char reply[157];
  assert(cli.handleBatteryForwardingCommand("set repeat.battery 55", reply));
  assert(!cli.batteryAllowsForward(false) && board.reads == 1);
  assert(cli.handleBatteryForwardingCommand("set battery.empty 5000", reply));
  assert(strcmp(reply, "OK - saved") == 0 && cli.batteryEmptyMv() == 5000);
  assert(cli.batteryFullMv() == 8400 && cli._battery_forward_state.percentage == 64);
  assert(cli.batteryAllowsForward(false) && board.reads == 2);
  assert(cli.handleBatteryForwardingCommand("set battery.full 10000", reply));
  assert(cli.batteryFullMv() == 10000 && cli._battery_forward_state.percentage == 44);
  assert(!cli.batteryAllowsForward(false) && board.reads == 3);
''', prefix=self.runtime_prefix(), flags=("-DESP32_PLATFORM", "-DBATT_MIN_MILLIVOLTS=6000",
                                                 "-DBATT_MAX_MILLIVOLTS=8400"))

    def test_actual_nrf52_runtime_uses_shared_voltage_policy_and_preserves_existing_endpoint_cli(self):
        self.exercise(r'''
  Board board;
  board.mv = 7200;
  CommonCLI cli(board);
  char reply[157] = "untouched";
  cli._battery_forward_settings.emptyMv = 3000;
  cli._battery_forward_settings.fullMv = 4200;
  assert(cli.batteryEmptyMv() == 6000 && cli.batteryFullMv() == 8400 && cli.batteryPercent(7200) == 50);
  for (const char* command : {"get battery.empty", "get battery.full", "set battery.empty 3300", "set battery.full 4200"}) {
    assert(!cli.handleBatteryForwardingCommand(command, reply));
    assert(strcmp(reply, "untouched") == 0 && board.reads == 0 && cli.saveCalls == 0);
  }
  assert(cli.handleBatteryForwardingCommand("set repeat.battery 60", reply));
  assert(!cli.batteryAllowsForward(false) && board.reads == 1);
  mesh::power::configuredFullMv = 9000;
  cli.loopBatteryForwarding(true);
  assert(cli._battery_forward_state.percentage == 40 && board.reads == 2);
  mesh::power::configuredFullMv = 8000;
  cli.loopBatteryForwarding(true);
  assert(cli._battery_forward_state.percentage == 60 && !cli.batteryAllowsForward(false));
  board.mv = 7240;
  cli.loopBatteryForwarding(true);
  assert(cli._battery_forward_state.percentage == 62 && cli.batteryAllowsForward(false));
''', prefix=self.runtime_prefix(), flags=("-DNRF52_PLATFORM", "-DNRF52_POWER_MANAGEMENT"))

    def test_defaults_are_off_and_thresholds_are_independent_and_persistent_in_cli(self):
        self.exercise(r'''
  CLI cli;
  assert(validSettings(cli.settings));
  assert(cli.settings.enabled == 0 && cli.settings.repeatBelow == 10
      && cli.settings.floodBelow == 20 && cli.settings.emptyMv == 0 && cli.settings.fullMv == 0);
  cli.state.update(1, 3000, 0, true, cli.settings);
  assert(cli.state.allows(false) && cli.state.allows(true));
  assert(cli.run("get repeat.battery") && strcmp(cli.reply, "> off below=10%") == 0);
  assert(cli.run("get flood.battery") && strcmp(cli.reply, "> off below=20%") == 0);
  assert(cli.saveCalls == 0);
  for (unsigned threshold = 1; threshold <= 100; ++threshold) {
    const std::string command = "set repeat.battery " + std::to_string(threshold);
    cli.ok(command.c_str());
    assert(cli.settings.repeatBelow == threshold && cli.settings.floodBelow == 20);
    assert(cli.settings.enabled == Repeat);
  }
  cli.ok("set repeat.battery 13");
  cli.ok("set flood.battery 37");
  assert(cli.settings.enabled == (Repeat | Flood));
  cli.ok("set repeat.battery off");
  assert(cli.settings.enabled == Flood && cli.settings.repeatBelow == 13);
  cli.ok("set repeat.battery on");
  cli.ok("set flood.battery off");
  assert(cli.settings.enabled == Repeat && cli.settings.floodBelow == 37);
  cli.ok("set flood.battery on");
  assert(cli.settings.enabled == (Repeat | Flood));
  assert(cli.settings.repeatBelow == 13 && cli.settings.floodBelow == 37);
  for (unsigned threshold = 1; threshold <= 100; ++threshold) {
    const std::string command = "set flood.battery " + std::to_string(threshold);
    cli.ok(command.c_str());
    assert(cli.settings.floodBelow == threshold && cli.settings.repeatBelow == 13);
  }
''')

    def test_cli_rejects_invalid_ranges_suffixes_extra_arguments_and_overflow(self):
        self.exercise(r'''
  CLI cli;
  for (const char* value : {"", "0", "101", "-1", "+10", "10.0", "10%", "15x",
                           "off on", "on off", "15 20", "10 ", "10\t", "ON", "OFF",
                           "4294967296", "1844674407370955161600000000000000"}) {
    for (const char* key : {"repeat.battery", "flood.battery"}) {
      const std::string command = std::string("set ") + key + " " + value;
      cli.error(command.c_str());
    }
  }
  cli.error("get repeat.battery 10");
  cli.error("get flood.battery off");
  cli.error("get battery.forward now");
  cli.error("set battery.forward on");
  for (const char* command : {"get repeat.batterys", "set repeat.battery2 10", "get flood.batteryx",
                              "get battery.forwarder", "repeat.battery", "Get repeat.battery", ""}) {
    assert(!cli.run(command));
    assert(strcmp(cli.reply, "untouched") == 0 && cli.saveCalls == 0);
  }
  cli.ok("set repeat.battery\t17");
  cli.ok("set flood.battery  21");
  assert(cli.settings.repeatBelow == 17 && cli.settings.floodBelow == 21);
  uint16_t parsed = 1234;
  assert(!parseNumber(nullptr, 1, 100, parsed) && parsed == 1234);
  assert(!parseNumber("", 1, 100, parsed) && parsed == 1234);
  assert(parseNumber("00015", 1, 100, parsed) && parsed == 15);
''')

    def test_command_null_and_bounded_reply_contract(self):
        self.exercise(r'''
  CLI cli;
  unsigned calls = 0;
  auto save = [&](const Settings&) { ++calls; return true; };
  char guard[] = {'A', 'B', 'C'};
  assert(!handleCommand(cli.settings, cli.state, 3000, 4200, false, nullptr, guard + 1, 1, save));
  assert(!handleCommand(cli.settings, cli.state, 3000, 4200, false, "get repeat.battery", nullptr, 1, save));
  assert(!handleCommand(cli.settings, cli.state, 3000, 4200, false, "get repeat.battery", guard + 1, 0, save));
  assert(calls == 0 && guard[0] == 'A' && guard[1] == 'B' && guard[2] == 'C');
  for (const char* command : {"get repeat.battery", "get battery.forward", "set flood.battery 999"}) {
    assert(handleCommand(cli.settings, cli.state, 3000, 4200, false, command, guard + 1, 1, save));
    assert(guard[0] == 'A' && guard[1] == '\0' && guard[2] == 'C' && calls == 0);
  }
''')

    def test_failed_persistence_leaves_active_candidate_and_sampling_unchanged(self):
        self.exercise(r'''
  CLI cli;
  cli.ok("set repeat.battery 15");
  cli.state.update(123, 3108, 9, true, cli.settings);
  const Settings before = cli.settings;
  const State sampled = cli.state;
  cli.saveOk = false;
  const unsigned calls = cli.saveCalls;
  assert(cli.run("set repeat.battery off"));
  assert(strstr(cli.reply, "save unconfirmed") && strstr(cli.reply, "active policy unchanged"));
  assert(cli.saveCalls == calls + 1 && same(cli.settings, before));
  assert(cli.saved.enabled == 0 && cli.saved.repeatBelow == 15);
  assert(cli.state.sampledAt == sampled.sampledAt && cli.state.millivolts == sampled.millivolts
      && cli.state.percentage == sampled.percentage && cli.state.valid == sampled.valid
      && cli.state.repeatBlocked == sampled.repeatBlocked && cli.state.floodBlocked == sampled.floodBlocked);
  assert(!cli.state.allows(false));
  cli.saveOk = true;
  cli.ok("set repeat.battery off");
  // The CLI owns persistence; its caller must immediately re-evaluate the sample.
  assert(cli.state.repeatBlocked && cli.state.sampledAt == 123);
  cli.state.update(124, 3108, 9, true, cli.settings);
  assert(cli.state.allows(false) && cli.state.allows(true));
  cli.ok("set flood.battery 30");
  cli.state.update(125, 3108, 9, true, cli.settings);
  assert(cli.state.allows(false) && !cli.state.allows(true));
''')

    def test_threshold_is_strictly_below_with_two_point_hysteresis_capped_at_100(self):
        self.exercise(r'''
  for (unsigned threshold = 1; threshold <= 100; ++threshold) {
    for (unsigned pct = 0; pct <= 100; ++pct) {
      const unsigned resume = threshold < 99 ? threshold + 2 : 100;
      assert(State::blocked(false, true, true, pct, threshold) == (pct < threshold));
      assert(State::blocked(true, true, true, pct, threshold) == (pct < resume));
      assert(!State::blocked(true, false, true, pct, threshold));
      assert(!State::blocked(true, true, false, pct, threshold));
    }
  }
  Settings settings;
  settings.enabled = Repeat | Flood;
  State state;
  state.update(1, 3240, 20, true, settings);
  assert(state.allows(false) && state.allows(true));
  state.update(2, 3228, 19, true, settings);
  assert(state.allows(false) && !state.allows(true));
  state.update(3, 3120, 10, true, settings);
  assert(state.allows(false) && !state.allows(true));
  state.update(4, 3108, 9, true, settings);
  assert(!state.allows(false) && !state.allows(true));
  state.update(5, 3132, 11, true, settings);
  assert(!state.allows(false) && !state.allows(true));
  state.update(6, 3144, 12, true, settings);
  assert(state.allows(false) && !state.allows(true));
  state.update(7, 3252, 21, true, settings);
  assert(state.allows(false) && !state.allows(true));
  state.update(8, 3264, 22, true, settings);
  assert(state.allows(false) && state.allows(true));
''')

    def test_invalid_unknown_battery_fails_open_and_sampling_handles_clock_wrap(self):
        self.exercise(r'''
  Settings settings;
  settings.enabled = Repeat | Flood;
  for (uint16_t mv : {uint16_t(0), uint16_t(1999), uint16_t(20001), uint16_t(65535)}) {
    State state;
    state.update(1, 3000, 0, true, settings);
    assert(!state.allows(false));
    state.update(2, mv, 0, true, settings);
    assert(!state.valid && state.allows(false) && state.allows(true));
  }
  for (unsigned pct : {101U, 255U}) {
    State state;
    state.update(1, 3000, 0, true, settings);
    state.update(2, 3000, pct, true, settings);
    assert(!state.valid && state.allows(false) && state.allows(true));
  }
  State state;
  assert(state.due(0));
  state.update(0xfffffff0U, 3000, 0, true, settings);
  assert(!state.due(0xfffffff0U) && !state.due(0x751fU));
  assert(state.due(0x7520U));
  state.update(7, 3000, 0, false, settings);
  assert(!state.valid && state.allows(false) && state.allows(true));
  CLI cli;
  cli.state = state;
  assert(cli.run("get battery.forward") && strstr(cli.reply, "battery=unknown"));
  assert(strstr(cli.reply, "repeat=allowed flood=allowed") && cli.saveCalls == 0);
''')

    def test_voltage_endpoints_allow_two_cell_conversion_and_reject_invalid_pairs(self):
        self.exercise(r'''
  CLI cli;
  assert(cli.run("get battery.empty") && strcmp(cli.reply, "> 3000") == 0);
  assert(cli.run("get battery.full") && strcmp(cli.reply, "> 4200") == 0);
  cli.error("set battery.empty 4200");
  cli.error("set battery.empty 4101");
  cli.ok("set battery.empty 4100");
  assert(cli.settings.emptyMv == 4100 && cli.settings.fullMv == 4200);
  cli.empty = cli.settings.emptyMv;
  cli.ok("set battery.full 8400");
  cli.full = cli.settings.fullMv;
  cli.ok("set battery.empty 6000");
  assert(cli.settings.emptyMv == 6000 && cli.settings.fullMv == 8400);
  assert(percent(6000, 6000, 8400) == 0 && percent(8400, 6000, 8400) == 100);
  assert(percent(7200, 6000, 8400) == 50 && percent(7180, 6000, 8400) == 49);
  assert(percent(0, 6000, 8400) == 0 && percent(65535, 6000, 8400) == 100);
  assert(percent(3000, 4200, 4200) == 100 && percent(3000, 4200, 3000) == 100);
  for (const char* value : {"0", "1999", "20001", "65536", "-1", "4.2", "4200mV", "4200 4300"}) {
    for (const char* key : {"battery.empty", "battery.full"}) {
      const std::string command = std::string("set ") + key + " " + value;
      cli.error(command.c_str());
    }
  }
  assert(validEndpoints(2000, 2100) && validEndpoints(2000, 20000));
  assert(!validEndpoints(1999, 4200) && !validEndpoints(3000, 3099));
  assert(!validEndpoints(19901, 20000) && !validEndpoints(2000, 20001));
''')

    def test_nrf52_external_voltage_policy_falls_through_without_writing(self):
        self.exercise(r'''
  CLI cli;
  cli.external = true;
  for (const char* command : {"get battery.empty", "get battery.full", "set battery.empty 3300",
                              "set battery.full 8400", "set battery.empty nonsense"}) {
    assert(!cli.run(command));
    assert(strcmp(cli.reply, "untouched") == 0 && cli.saveCalls == 0);
    assert(same(cli.settings, Settings{}));
  }
  cli.ok("set repeat.battery 17");
  cli.ok("set flood.battery 28");
  assert(cli.run("get repeat.battery") && strcmp(cli.reply, "> on below=17%") == 0);
  assert(cli.run("get flood.battery") && strcmp(cli.reply, "> on below=28%") == 0);
''')

    def test_record_roundtrip_truncation_bit_corruption_and_semantic_validation(self):
        self.exercise(r'''
  Settings expected;
  expected.enabled = Repeat | Flood;
  expected.repeatBelow = 17; expected.floodBelow = 43;
  expected.emptyMv = 6000; expected.fullMv = 8400;
  uint8_t bytes[RecordSize];
  encode(bytes, expected);
  Settings actual;
  assert(decode(bytes, sizeof(bytes), actual) && same(actual, expected));
  assert(bytes[8] == 0x70 && bytes[9] == 0x17 && bytes[10] == 0xd0 && bytes[11] == 0x20);
  for (size_t byte = 0; byte < RecordSize; ++byte) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      uint8_t corrupted[RecordSize];
      memcpy(corrupted, bytes, sizeof(bytes));
      corrupted[byte] ^= uint8_t(1U << bit);
      actual = expected;
      assert(!decode(corrupted, sizeof(corrupted), actual));
      assert(same(actual, Settings{}));
    }
  }
  for (size_t size = 0; size < RecordSize; ++size) {
    std::vector<uint8_t> truncated(bytes, bytes + size);
    actual = expected;
    assert(!decode(truncated.data(), size, actual) && same(actual, Settings{}));
  }
  std::vector<uint8_t> oversized(bytes, bytes + RecordSize);
  oversized.push_back(0);
  actual = expected;
  assert(!decode(oversized.data(), oversized.size(), actual) && same(actual, Settings{}));
  actual = expected;
  assert(!decode(nullptr, RecordSize, actual) && same(actual, Settings{}));
  auto rejectRecord = [&](const uint8_t* input) {
    uint8_t invalid[RecordSize];
    memcpy(invalid, input, sizeof(invalid));
    const uint16_t crc = checksum(invalid, 14);
    invalid[14] = uint8_t(crc); invalid[15] = uint8_t(crc >> 8);
    actual = expected;
    assert(!decode(invalid, sizeof(invalid), actual) && same(actual, Settings{}));
  };
  for (size_t reserved : {size_t(7), size_t(12), size_t(13)}) {
    uint8_t invalid[RecordSize];
    memcpy(invalid, bytes, sizeof(bytes)); invalid[reserved] = 1;
    rejectRecord(invalid);
  }
  for (unsigned fault = 0; fault < 7; ++fault) {
    Settings invalid = expected;
    if (fault == 0) invalid.enabled = 4;
    if (fault == 1) invalid.repeatBelow = 0;
    if (fault == 2) invalid.repeatBelow = 101;
    if (fault == 3) invalid.floodBelow = 0;
    if (fault == 4) invalid.floodBelow = 101;
    if (fault == 5) invalid.emptyMv = 0;
    if (fault == 6) invalid.fullMv = 6099;
    assert(!validSettings(invalid));
    uint8_t invalidBytes[RecordSize]; encode(invalidBytes, invalid);
    rejectRecord(invalidBytes);
  }
  encode(bytes, Settings{});
  assert(decode(bytes, RecordSize, actual) && same(actual, Settings{}));
''')


if __name__ == "__main__":
    unittest.main()
