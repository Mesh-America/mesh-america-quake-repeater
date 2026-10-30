#include <helpers/UDPBridgePrefs.h>
#include <cassert>
#include <cstring>
#include <cstdio>
struct Callbacks {
  mesh::bridge::udp::Prefs prefs;
  bool network = true;
  unsigned closes = 0, resumes = 0;
  bool isUDPBridgeNetworkEnabled() const { return network; }
  bool setUDPBridgeNetworkState(bool enabled) { network = enabled; if (enabled) ++resumes; else ++closes; return true; }
  const mesh::bridge::udp::Prefs* getUDPBridgePrefs() const { return &prefs; }
} callbacks;
struct Board {
  bool running = false, allow_start = true, allow_stop = true;
  unsigned starts = 0;
  bool isOTAUpdateRunning() const { return running; }
  bool startOTAUpdate(const char*, char* reply, bool) {
    assert(!callbacks.network); ++starts;
    if (allow_start) running = true;
    strcpy(reply, allow_start ? "Started" : "Failed"); return allow_start;
  }
  bool stopOTAUpdate(char* reply) { if (allow_stop) running = false; strcpy(reply, "Stopped"); return allow_stop; }
} board;
struct NodePrefs { const char* node_name = "test"; } prefs;
struct CLI {
  Board* _board = &board;
  NodePrefs* _prefs = &prefs;
  Callbacks* _callbacks = &callbacks;
  bool _wifi_ota_resume_udp = false;
  void run(const char* command, char* reply) {
    if (false) {
OTA_HERE
    }
  }
};
int main() {
  callbacks.prefs.enabled = 1;
  CLI cli; char reply[160] = {};
  cli.run("start ota invalid", reply); assert(board.starts == 0 && callbacks.closes == 0);
  board.allow_start = false;
  cli.run("start ota", reply);
  assert(callbacks.closes == 1 && callbacks.resumes == 1 && callbacks.network && !cli._wifi_ota_resume_udp);
  board.allow_start = true;
  cli.run("start ota ap", reply);
  assert(!callbacks.network && cli._wifi_ota_resume_udp);
  cli.run("start ota ap", reply); // Repeating a start retains the original pause.
  board.allow_stop = false;
  cli.run("stop ota", reply); assert(!callbacks.network && cli._wifi_ota_resume_udp);
  board.allow_stop = true;
  cli.run("stop ota", reply); assert(callbacks.network && !cli._wifi_ota_resume_udp);
  cli.run("start ota", reply); callbacks.prefs.enabled = 0;
  cli.run("stop ota", reply); assert(!callbacks.network && !cli._wifi_ota_resume_udp);
  callbacks.prefs.enabled = 1;
  const unsigned resumes = callbacks.resumes;
  cli.run("stop ota", reply); assert(!callbacks.network && callbacks.resumes == resumes);
  cli.run("start ota", reply); cli.run("stop ota", reply);
  assert(!callbacks.network && callbacks.resumes == resumes); // An initially stopped session remains stopped.
}
