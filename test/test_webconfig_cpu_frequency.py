#!/usr/bin/env python3
"""Exercise CPU-speed snapshots, canonical config writes and the shipped form."""

import json
from pathlib import Path
import unittest

import test_webconfig_lost_reply as web_fixture


ROOT = Path(__file__).resolve().parents[1]


class CpuFrequencyWebConfigTest(unittest.TestCase):
    compile_run = web_fixture.LostReplyWebConfigTest.compile_run
    setup_values = web_fixture.LostReplyWebConfigTest.setup_values
    run_page = web_fixture.LostReplyWebConfigTest.run_page

    def test_actual_json_snapshot_and_canonical_cli_batch(self):
        # Reuse the real authenticated GET/POST handlers, not a second JSON
        # implementation. Only their peripheral/HTTP boundaries are faked.
        source = web_fixture.LostReplyWebConfigTest.fixture(self)
        source = source.split("int main() {", 1)[0] + r'''
#include <helpers/esp32/CpuClockPolicy.h>
struct CpuBoard {
  uint16_t actual = 160;
  int applies = 0;
  bool supportsCpuFrequencyMHz(uint16_t mhz) const { return mhz == 80 || mhz == 160; }
  uint16_t getCpuFrequencyMHz() const { return actual; }
  bool applyCpuFrequencyMHz(uint16_t selected, bool) {
    ++applies; actual = selected ? selected : 80; return true;
  }
};
String cpuWriteBody(const char* value, const char* key = "cpu.freq") {
  return String("{\"reqid\":\"0123456789abcdef\",\"set\":{\"") + key + "\":" + value + "}}";
}
int main() {
  assert(mesh::esp32::managementPassword::publish("password"));
  for (unsigned mask = 0; mask < 16; ++mask) {
    WebConfigServer server;
    server.callbacks.node.cpu_freq_mhz = 80;
    server.callbacks.node.cpu_actual_mhz = 160;
    server.callbacks.node.cpu_supported_mask = mask;
    AsyncWebServerRequest get;
    server.handleConfigGet(&get);
    JsonDocument snapshot;
    assert(get.status == 200 && deserializeJson(snapshot, get.output) == DeserializationError::Ok);
    if (!(mask & 7)) {
      assert(snapshot["cpu"].isNull());
      continue;
    }
    assert(snapshot["cpu"]["selected_mhz"].as<unsigned>() == 80);
    assert(snapshot["cpu"]["actual_mhz"].as<unsigned>() == 160);
    JsonArray options = snapshot["cpu"]["supported_mhz"];
    const unsigned frequencies[] = {80, 160, 240};
    unsigned count = 0;
    for (unsigned bit = 0; bit < 3; ++bit) {
      if (mask & (1U << bit)) assert(options[count++].as<unsigned>() == frequencies[bit]);
    }
    assert(options.size() == count);
  }
  for (const char* text : {"auto", "80", "160", "240", "81", "80;reboot", ""}) {
    WebConfigServer server;
    const String value = String("\"") + text + "\"";
    AsyncWebServerRequest save(cpuWriteBody(value.c_str()));
    server.handleConfigPost(&save);
    assert(save.status == 202 && server._batch_count == 1 && !server._batch_reboot);
    assert(strcmp(server._batch[0].key, "cpu.freq") == 0);
    assert(String(server._batch[0].cmd) == String("set cpu.freq ") + text);
    CpuBoard board;
    uint16_t selected = 160;
    unsigned saves = 0;
    char reply[160] = {};
    assert(mesh::esp32::cpuclock::handleCommand(board, selected, true,
        server._batch[0].cmd, reply, sizeof(reply), [&]() { ++saves; return true; }));
    const bool valid = strcmp(text, "auto") == 0 || strcmp(text, "80") == 0 || strcmp(text, "160") == 0;
    if (valid) {
      assert(strncmp(reply, "OK - saved", 10) == 0 && saves == 1 && board.applies == 1);
      assert(selected == (strcmp(text, "auto") == 0 ? 0 : atoi(text)));
    } else {
      assert(strncmp(reply, "Error:", 6) == 0 && !saves && !board.applies);
      assert(selected == 160 && board.actual == 160);
    }
  }
  for (const char* invalid : {"null", "true", "80"}) {
    WebConfigServer server;
    AsyncWebServerRequest save(cpuWriteBody(invalid));
    server.handleConfigPost(&save);
    assert(save.status == 400 && server._batch_count == 0);
  }
  WebConfigServer server;
  AsyncWebServerRequest extra(cpuWriteBody("\"80\"", "cpu.freq.extra"));
  server.handleConfigPost(&extra);
  assert(extra.status == 400 && server._batch_count == 0);
  server.clearSessionLocked();
  AsyncWebServerRequest unauthenticated(cpuWriteBody("\"80\""));
  server.handleConfigPost(&unauthenticated);
  assert(unauthenticated.status == 401 && server._batch_count == 0);
  assert(wcIsAllowedSetKey("cpu.freq") && !wcSetKeyRequiresReboot("cpu.freq"));
}
'''
        self.compile_run(source)

    def test_shipped_form_uses_supported_options_and_saves_through_normal_batch(self):
        status, config = self.setup_values()
        status.update(mode="lan", capabilities=8192)
        config["cpu"] = {"selected_mhz": 0, "actual_mhz": 80, "supported_mhz": [80, 160]}
        prelude = r'''<script>
(function(){
  var status=%s,config=%s,submitted=null,saves=[];
  function reply(value,code){return Promise.resolve({ok:true,status:code||200,json:function(){return Promise.resolve(value)}})}
  window.fetch=function(path,options){
    if(path==="/api/status")return reply(status);
    if(path==="/api/config"&&(!options||options.method!=="POST"))return reply(config);
    if(path==="/api/config"){
      submitted=JSON.parse(options.body);saves.push(submitted);
      if(saves.length!==3){
        config.cpu.selected_mhz=submitted.set["cpu.freq"]==="auto"?0:Number(submitted.set["cpu.freq"]);
        config.cpu.actual_mhz=config.cpu.selected_mhz||80;
      }
      return reply({state:"pending",reqid:submitted.reqid,count:1},202);
    }
    if(path.indexOf("/api/config/result?")===0)return reply({state:"done",reqid:submitted.reqid,results:[{key:"cpu.freq",reply:saves.length===3?"Error: CPU clock apply failed; unchanged":"OK - saved"}]});
    return reply({});
  };
  function mark(key,value){document.body.setAttribute("data-test-cpu-"+key,String(value))}
  function waitFor(check,next,attempt){
    if(check()){next();return}
    if((attempt||0)>100){document.body.setAttribute("data-test-error","CPU save did not complete");return}
    setTimeout(function(){waitFor(check,next,(attempt||0)+1)},20);
  }
  window.addEventListener("load",function(){
    setTimeout(function(){enterApp()},50);
    setTimeout(function(){waitFor(function(){return st.cfg&&st.cfg.cpu},function(){
      var select=document.querySelector('[data-k="cpu.freq"]');
      mark("visible",!document.getElementById("cpu-frequency-setting").classList.contains("hide"));
      mark("enabled",!select.disabled);mark("initial",select.value);
      mark("options",Array.from(select.options).map(function(o){return o.value}).join(","));
      mark("actual",document.getElementById("cpu-frequency-status").textContent);
      mark("clean",Object.keys(st.dirty).length===0);
      select.value="160";select.dispatchEvent(new Event("input",{bubbles:true}));
      mark("dirty",st.dirty["cpu.freq"]);appSave();
      waitFor(function(){return saves.length===1&&st.orig["cpu.freq"]==="160"&&!st.dirty["cpu.freq"]},function(){
        mark("saved",saves[0].set["cpu.freq"]);mark("only-key",Object.keys(saves[0].set).join(","));
        mark("no-reboot",!saves[0].reboot);
        mark("after-actual",document.getElementById("cpu-frequency-status").textContent);
        select.value="auto";select.dispatchEvent(new Event("input",{bubbles:true}));appSave();
        waitFor(function(){return saves.length===2&&st.orig["cpu.freq"]==="auto"&&!st.dirty["cpu.freq"]},function(){
          mark("auto-saved",saves[1].set["cpu.freq"]);
          select.value="160";select.dispatchEvent(new Event("input",{bubbles:true}));appSave();
          waitFor(function(){return saves.length===3&&!document.getElementById("save-btn").disabled&&select.closest(".f").querySelector(".chip.err")},function(){
            mark("rejected-dirty",st.dirty["cpu.freq"]);mark("rejected-saved",st.orig["cpu.freq"]);
            mark("rejected-field",select.value);mark("rejected-actual",document.getElementById("cpu-frequency-status").textContent);
            setTimeout(function(){mark("requests",saves.length)},200);
          });
        });
      });
    });},200);
  });
})();
</script>''' % (json.dumps(status), json.dumps(config))
        dom = self.run_page(prelude, virtual_time=4000)
        for key, value in (("visible", "true"), ("enabled", "true"), ("initial", "auto"),
                           ("options", "auto,80,160"), ("actual", "Running at 80 MHz"),
                           ("clean", "true"), ("dirty", "160"), ("saved", "160"),
                           ("only-key", "cpu.freq"), ("no-reboot", "true"),
                           ("after-actual", "Running at 160 MHz"), ("auto-saved", "auto"),
                           ("rejected-dirty", "160"), ("rejected-saved", "auto"),
                           ("rejected-field", "160"), ("rejected-actual", "Running at 80 MHz"),
                           ("requests", "3")):
            self.assertIn('data-test-cpu-%s="%s"' % (key, value), dom)

    def test_shipped_form_hides_unavailable_clock_and_can_load_240(self):
        for cpu, values, visible, selected in (
                (None, "auto", False, "auto"),
                ({"selected_mhz": 240, "actual_mhz": 240,
                  "supported_mhz": [240, 80, 160, 240, 20]}, "auto,80,160,240", True, "240")):
            with self.subTest(cpu=cpu):
                status, config = self.setup_values()
                status.update(mode="lan")
                if cpu is not None:
                    config["cpu"] = cpu
                else:
                    config.pop("cpu", None)
                prelude = r'''<script>
window.fetch=function(path){var value=path==="/api/status"?%s:%s;return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(value)}})};
window.addEventListener("load",function(){
  setTimeout(function(){enterApp()},50);
  setTimeout(function(){
    var select=document.querySelector('[data-k="cpu.freq"]'),body=document.body;
    body.setAttribute("data-test-cpu-visible",!document.getElementById("cpu-frequency-setting").classList.contains("hide"));
    body.setAttribute("data-test-cpu-disabled",select.disabled);
    body.setAttribute("data-test-cpu-options",Array.from(select.options).map(function(o){return o.value}).join(","));
    body.setAttribute("data-test-cpu-selected",select.value);
    body.setAttribute("data-test-cpu-dirty",Object.keys(st.dirty).length);
  },650);
});
</script>''' % (json.dumps(status), json.dumps(config))
                dom = self.run_page(prelude)
                for key, value in (("visible", str(visible).lower()),
                                   ("disabled", str(not visible).lower()),
                                   ("options", values), ("selected", selected), ("dirty", "0")):
                    self.assertIn('data-test-cpu-%s="%s"' % (key, value), dom)


if __name__ == "__main__":
    unittest.main()
