@PARSERS@
struct CommonCLI {
  NodePrefs* _prefs;
  MyMesh* _callbacks;
  FakeSensors* _sensors;
  bool fail_save = false;
  unsigned saves = 0;
  NodePrefs stored;
  explicit CommonCLI(MyMesh& node) : _prefs(&node._prefs), _callbacks(&node), _sensors(&node.sensors) {}
  bool trySavePrefs() {
    if (fail_save) return false;
    ++saves; stored = *_prefs; return true;
  }
  void savePrefs() { ++saves; stored = *_prefs; }
  void set(const char* input, char* reply) {
    char config[256] = {}; assert(strlen(input) < sizeof(config)); strcpy(config, input);
    @SETS@
    strcpy(reply, "Unknown");
  }
  void get(const char* config, char* reply) {
    @GETS@
    else strcpy(reply, "Unknown");
  }
};
static void expect(CommonCLI& cli, const char* key, const char* value) {
  char reply[160] = {}; cli.get(key, reply); assert(strcmp(reply, value) == 0);
}
static void standby(MyMesh& node) {
  assert(node.bridge && node.isRs232BridgeRunning());
  node._prefs.rs232_autosleep = 1;
  node.bridge->capability_armed = true;
  node.bridge->requested = RS232Bridge::PowerAction::Suspend;
  node.serviceRs232BridgePower();
  assert(node.bridge && !node.isRs232BridgeRunning() && node.bridge->isPowerSuspended());
}
int main() {
  {
    MyMesh node; CommonCLI cli(node); char reply[160] = {};
    expect(cli, "rs232.heartbeat", "> on");
    expect(cli, "rs232.autosleep", "> on");
    expect(cli, "rs232.idle", "> 300s");
    for (const char* input : {"rs232.heartbeat on junk", "rs232.heartbeat off ",
                              "rs232.heartbeat -1", "rs232.heartbeat 1",
                              "rs232.autosleep on junk", "rs232.autosleep off ",
                              "rs232.autosleep -1", "rs232.autosleep 999",
                              "rs232.autosleep force junk", "rs232.autosleep force "}) {
      const unsigned saves = cli.saves; cli.set(input, reply);
      if (strncmp(reply, "Error:", 6) != 0 || cli.saves != saves) fprintf(stderr, "Unexpected boolean: %s => %s\n", input, reply);
      assert(strncmp(reply, "Error:", 6) == 0 && cli.saves == saves);
      assert(node._prefs.rs232_heartbeat == 1 && node._prefs.rs232_autosleep == 1);
    }
    for (const char* suffix : {"-1", "59", "3601", "4294967296",
                               "18446744073709551615", "60 seconds", "", "nan"}) {
      char input[128]; snprintf(input, sizeof(input), "rs232.idle %s", suffix);
      const unsigned saves = cli.saves; cli.set(input, reply);
      if (strncmp(reply, "Error:", 6) != 0 || cli.saves != saves) fprintf(stderr, "Unexpected idle: %s => %s\n", input, reply);
      assert(strncmp(reply, "Error:", 6) == 0 && cli.saves == saves);
      assert(node._prefs.rs232_idle_seconds == 300);
    }
    for (const char* input : {"rs232.idle +60", "rs232.idle 60 ", "rs232.idle  60\t"}) {
      cli.set(input, reply); assert(strncmp(reply, "OK", 2) == 0);
      assert(node._prefs.rs232_idle_seconds == 60);
    }
    cli.set("rs232.heartbeat off", reply); assert(strncmp(reply, "OK", 2) == 0);
    expect(cli, "rs232.heartbeat", "> off");
    cli.set("rs232.autosleep on", reply); assert(strncmp(reply, "OK", 2) == 0);
    expect(cli, "rs232.autosleep", "> on");
    cli.set("rs232.autosleep force", reply); assert(strncmp(reply, "OK", 2) == 0);
    expect(cli, "rs232.autosleep", "> force");
    for (uint16_t seconds : {60, 300, 999, 3600}) {
      char input[64]; snprintf(input, sizeof(input), "rs232.idle %u", seconds);
      cli.set(input, reply); assert(strncmp(reply, "OK", 2) == 0);
      assert(node._prefs.rs232_idle_seconds == seconds && cli.stored.rs232_idle_seconds == seconds);
    }
    cli.fail_save = true;
    cli.set("rs232.heartbeat on", reply); assert(strncmp(reply, "Error:", 6) == 0);
    assert(node._prefs.rs232_heartbeat == 0);
    cli.set("rs232.autosleep off", reply); assert(strncmp(reply, "Error:", 6) == 0);
    assert(node._prefs.rs232_autosleep == 2);
    cli.set("rs232.idle 60", reply); assert(strncmp(reply, "Error:", 6) == 0);
    assert(node._prefs.rs232_idle_seconds == 3600);
  }
  for (const char* command : {"rs232.enabled off", "rs232.enabled on",
                              "bridge.enabled off", "bridge.enabled on",
                              "bridge.baud 57600", "bridge.uart 1", "bridge.uart 2"}) {
    MyMesh node; CommonCLI cli(node); char reply[160] = {};
    node._prefs.bridge_enabled = node._prefs.rs232_bridge_enabled = 1;
    node._prefs.bridge_baud = 115200;
    assert(node.setRs232BridgeState(true)); standby(node);
    cli.fail_save = true; cli.set(command, reply);
#ifdef WITH_MQTT_BRIDGE
    if (strncmp(command, "bridge.enabled", 14) == 0) {
      // This alias belongs to MQTT, not UART. It must not delete/wake RS232.
      assert(node.bridge && node.bridge->isPowerSuspended() && !node.isRs232BridgeRunning());
      continue;
    }
#endif
    assert(strncmp(reply, "Error:", 6) == 0);
    assert(node._prefs.bridge_enabled && node._prefs.rs232_bridge_enabled);
    if (!node.bridge || !node.isRs232BridgeRunning()) fprintf(stderr, "Lost standby owner: %s => %s\n", command, reply);
    assert(node.bridge && node.isRs232BridgeRunning());
    assert(node._prefs.bridge_uart == 2 && node.active_rs232_bridge_uart == 2);
    assert(node._prefs.bridge_baud == 115200);
    assert(!Serial1.running && Serial2.running);
    cli.get("rs232.status", reply);
    assert(strstr(reply, "saved=on running=on") && strstr(reply, "autosleep=on"));
  }
  assert(RS232Bridge::live == 0);
}
