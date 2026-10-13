#!/usr/bin/env python3
"""Execute lab-only device TX timing, command ownership and runner metadata."""
from pathlib import Path
import argparse
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch

from test_morse_tx import compile_run, portable_radio_header

ROOT = Path(__file__).resolve().parents[1]


class MorseHilTimingTests(unittest.TestCase):
    def test_console_correlates_delayed_echo_response_and_closes_failed_session_safely(self):
        serial = types.ModuleType("serial")
        serial_tools = types.ModuleType("serial.tools")
        serial_tools.list_ports = types.SimpleNamespace(comports=lambda: [])
        with patch.dict(sys.modules, {"serial":serial,"serial.tools":serial_tools}):
            spec = importlib.util.spec_from_file_location("timed_console", ROOT / "tools/hil/morse_bench.py")
            bench = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bench)
        class Clock:
            now=0
            def monotonic(self): return self.now
        class Port:
            in_waiting=0
            def __init__(self,clock,chunks):
                self.clock=clock; self.chunks=list(chunks); self.writes=[]; self.closed=False
            def write(self,data): self.writes.append(data)
            def read(self,length):
                if self.chunks and self.clock.now >= self.chunks[0][0]:
                    return self.chunks.pop(0)[1]
                self.clock.now += .5
                return b""
            def close(self): self.closed=True
        def console(companion,chunks):
            clock=Clock(); device=object.__new__(bench.Console)
            device.serial_number="verified-test"; device.companion=companion
            device.commands=[]; device.failed=False; device.port=Port(clock,chunks)
            return device,clock
        command="set morse.hil.timing 0,0,0,1"
        stale=b"set morse.wpm 25\r\n  -> OK - morse.wpm 25\r\n> "
        own_echo=(command+"\r\n").encode()
        device,clock=console(True,[(0,stale),(4,own_echo),(6,b"  -> OK - HIL timing\r\n"),(7,b"> ")])
        with patch.object(bench,"time",clock):
            reply=device.command(command)
        self.assertEqual(reply,"> "+command+"\r\n  -> OK - HIL timing\r\n> ")
        self.assertGreaterEqual(clock.now,7)
        self.assertNotIn("morse.wpm",reply)
        self.assertEqual(device.port.writes,[(command+"\r\n").encode()])
        self.assertFalse(device.failed)
        # An infrastructure reply has no owned ASCII prompt; its response must
        # still follow this request's exact echo rather than an unrelated line.
        device,clock=console(False,[(0,b"old\r\n  -> stale\r\n"),
                                   (4,b"get morse\r\n\r\n  -> > off;\r\n")])
        with patch.object(bench,"time",clock):
            self.assertEqual(device.command("get morse"),"get morse\r\n\r\n  -> > off;\r\n")
        for chunks in ([(0,stale)],[(0,own_echo+b"  -> delayed\r\n")],
                       [(0,own_echo+b"> ")]):
            with self.subTest(chunks=chunks):
                device,clock=console(True,chunks)
                with patch.object(bench,"time",clock):
                    with self.assertRaisesRegex(RuntimeError,"Incomplete CLI response"):
                        device.command(command)
                    self.assertTrue(device.failed)
                    device.port.chunks.append((clock.now,b"  -> late\r\n> "))
                    with self.assertRaisesRegex(RuntimeError,"refusing further"):
                        device.command("morse stop")
                    device.close()
                self.assertTrue(device.port.closed)
                self.assertEqual(device.port.writes,[(command+"\r\n").encode()])
                self.assertTrue(device.commands[-1]["failed"])
                self.assertIn("+00:00",device.commands[-1]["utc"])
        # A complete CLI error is synchronized and can safely be followed up.
        device,clock=console(True,[(0,b"set tx -9\r\n  -> Error: radio busy\r\n> ")])
        with patch.object(bench,"time",clock):
            with self.assertRaisesRegex(RuntimeError,"radio busy"):
                device.command("set tx -9")
        self.assertFalse(device.failed)
        calls=[]
        device.command=lambda text,**options: (calls.append((text,options)),"OK")[1]
        with patch.object(bench,"time",clock): device.start_when_idle("set tx -9")
        self.assertEqual(calls,[("set tx -9",{"timeout":15,"allow_error":True})])

    def test_actual_scheduler_exact_planner_snapshot_wrap_and_shipping_layout(self):
        fixture = (ROOT / "test/fixtures/morse_hil_timing.cpp").read_text(encoding="ascii")
        for hil in (0, 1):
            with self.subTest(hil=hil):
                compile_run(self, fixture, flags=(f"-DMESH_MORSE_HIL={hil}", "-DMESH_MORSE_MAX_WPM=255"))

    def test_shared_cli_bounds_busy_replies_no_persistence_and_disabled_error(self):
        prefix = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        prefix = prefix.replace("struct TestRadio : mesh::Radio {", "struct TestRadio : mesh::Radio {\n  bool packet=false; bool isReceiving() override { return packet; }")
        code = prefix + r'''
int main() {
  TestRadio radio;
  struct Guard { char reply[157]; uint32_t after=0xaabbccdd; } out;
  const auto run=[&](const char* text) {
    assert(mesh::handleMorseCommand(&radio,text,out.reply,sizeof(out.reply)));
    assert(out.after==0xaabbccdd && strlen(out.reply)<sizeof(out.reply));
    return std::string(out.reply);
  };
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  assert(run("get morse.hil.timing").find("jitter=0%; drift=0%; extraGap=0%; seed=1")!=std::string::npos);
  assert(run("set morse.hil.timing 20,-20,50,4294967295").find("OK -")==0);
  assert(run("get morse.hil.timing").find("jitter=20%; drift=-20%; extraGap=50%; seed=4294967295")!=std::string::npos);
  assert(mesh::saves==0 && radio.starts==0);
  for(const char* invalid : {"", "1,2,3", "1,2,3,4,5", "21,0,0,1", "0,21,0,1", "0,-21,0,1",
      "0,0,51,1", "0,0,0,0", "0,0,0,4294967296", "1.5,0,0,1", "1,0,0,1x", "nan,0,0,1"}) {
    const auto command=std::string("set morse.hil.timing ")+invalid;
    assert(run(command.c_str()).find("Error:")==0);
    assert(mesh::morseHilTiming().seed==0xffffffff);
  }
  for(bool* busy : {&radio.active,&radio.cw,&radio.rx_active,&radio.packet}) {
    *busy=true;
    assert(run("set morse.hil.timing 0,0,0,1").find("busy")!=std::string::npos);
    assert(run("get morse.hil.timing").find("seed=4294967295")!=std::string::npos);
    *busy=false;
  }
  radio.receiving=false;
  assert(run("set morse.hil.timing 0,0,0,1").find("busy")!=std::string::npos);
  radio.receiving=true;
  assert(run("get morse.hil.timing extra").find("Error:")==0);
  assert(run("morse.hil.timing 0,0,0,1").find("Error:")==0);
  assert(run("set morse.hil.timing 0,0,0,1").find("OK -")==0);
  assert(mesh::saves==0 && radio.starts==0 && radio.stops==0);
#else
  (void)run;
  for(const char* command : {"get morse.hil.timing","set morse.hil.timing 0,0,0,1","morse.hil.timing"}) {
    strcpy(out.reply,"unchanged");
    assert(!mesh::handleMorseCommand(&radio,command,out.reply,sizeof(out.reply)));
    assert(!strcmp(out.reply,"unchanged") && out.after==0xaabbccdd);
  }
  assert(mesh::saves==0 && radio.starts==0 && radio.stops==0);
#endif
}
'''
        fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        for hil in (0, 1):
            with self.subTest(hil=hil):
                compile_run(self, code, flags=("-Wno-unused-parameter", f"-DMESH_MORSE_HIL={hil}"),
                            headers={"Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs_mock})

    def test_bench_human_arguments_readback_and_standard_reset(self):
        serial = types.ModuleType("serial")
        serial_tools = types.ModuleType("serial.tools")
        serial_tools.list_ports = types.SimpleNamespace(comports=lambda: [])
        with patch.dict(sys.modules, {"serial":serial,"serial.tools":serial_tools}):
            spec = importlib.util.spec_from_file_location("human_bench", ROOT / "tools/hil/morse_bench.py")
            bench = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bench)
        human = bench.parse_human_timing("15,-10,25,12345")
        self.assertEqual(human, {"jitter_percent":15,"drift_percent":-10,"extra_gap_percent":25,"seed":12345})
        for invalid in ("", "1,2,3", "21,0,0,1", "0,21,0,1", "0,0,51,1", "0,0,0,0", "0,0,0,4294967296", "1.5,0,0,1"):
            with self.subTest(invalid=invalid), self.assertRaises(argparse.ArgumentTypeError):
                bench.parse_human_timing(invalid)
        device = object.__new__(bench.Console)
        commands=[]
        device.start_when_idle=lambda command: commands.append(command)
        device.command=lambda command: (commands.append(command),"> jitter=15%; drift=-10%; extraGap=25%; seed=12345; volatile HIL TX only")[1]
        self.assertIn("seed=12345",device.set_hil_timing(human))
        self.assertEqual(commands,["set morse.hil.timing 15,-10,25,12345","get morse.hil.timing"])
        device.command=lambda command: "> jitter=0%; drift=0%; extraGap=0%; seed=1"
        with self.assertRaisesRegex(RuntimeError,"readback mismatch"):
            device.set_hil_timing(human)
        device.start_when_idle=lambda command: (_ for _ in ()).throw(RuntimeError("Error: HIL-only"))
        self.assertEqual(device.set_hil_timing(),"production image: standard timing only")
        with self.assertRaisesRegex(RuntimeError,"HIL-only"):
            device.set_hil_timing(human)
        device.start_when_idle=lambda command: (_ for _ in ()).throw(RuntimeError("Error: radio busy"))
        with self.assertRaisesRegex(RuntimeError,"busy"):
            device.set_hil_timing()
        device.start_when_idle=lambda command: (_ for _ in ()).throw(RuntimeError("set morse.hil.timing 0,0,0,1: Error: unknown setting: morse.hil.timing"))
        self.assertEqual(device.set_hil_timing(),"production image: standard timing only")
        with self.assertRaisesRegex(RuntimeError,"unknown setting"):
            device.set_hil_timing(human)
        device.failed=True
        with self.assertRaisesRegex(RuntimeError,"unknown setting"):
            device.set_hil_timing()

    def test_actual_trial_records_device_profile_without_relaxing_exact_text(self):
        serial = types.ModuleType("serial")
        serial_tools = types.ModuleType("serial.tools")
        serial_tools.list_ports = types.SimpleNamespace(comports=lambda: [])
        with patch.dict(sys.modules, {"serial":serial,"serial.tools":serial_tools}):
            spec = importlib.util.spec_from_file_location("human_trial", ROOT / "tools/hil/morse_bench.py")
            bench = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bench)
        actions=[]
        class Device:
            def __init__(self,name,decoded="SOS"):
                self.serial_number=name; self.decoded=decoded
            def command(self,command):
                actions.append((self.serial_number,command))
                return "> off;" if command=="get morse" else "OK"
            def set_hil_timing(self,timing):
                actions.append((self.serial_number,"device timing",timing))
                return "> jitter=15%; drift=10%; extraGap=25%; seed=12345"
            def start_when_idle(self,command): return self.command(command)
            def capture(self): return self.decoded
        human=bench.parse_human_timing("15,10,25,12345")
        with patch.object(bench.time,"sleep"):
            result=bench.trial(Device("tx"),Device("rx"," SOS "),25,"SOS",human_timing=human)
        self.assertTrue(result["passed"])
        self.assertEqual(result["human_timing"],human)
        self.assertIn("seed=12345",result["tx_timing_status"])
        self.assertLess(actions.index(("tx","device timing",human)),actions.index(("tx","morse send SOS")))
        for decoded in ("E SOS", "SOS E", "S OS", "SO?"):
            with self.subTest(decoded=decoded),patch.object(bench.time,"sleep"):
                result=bench.trial(Device("tx"),Device("rx",decoded),25,"SOS",human_timing=human)
            self.assertFalse(result["passed"])
            self.assertEqual(result["decoded"],decoded)
        class Output:
            text=None
            def exists(self): return False
            def write_text(self,text): self.text=text
        output=Output(); opened=[]; supplied=[]
        class Console:
            def __init__(self,identity): self.commands=[]; opened.append(identity)
            def setup(self,frequency): pass
            def close(self): pass
        def trial(*args,**kwargs): supplied.append(kwargs); return {"passed":True}
        with patch.object(bench,"Console",Console),patch.object(bench,"trial",trial), \
             patch.object(bench,"Path",lambda path:output),patch("builtins.print"), \
             patch.object(sys,"argv",["bench","--output","memory","--rates","25","--messages","1","--human-timing"]):
            bench.main()
        self.assertEqual(len(opened),2)
        self.assertEqual([call["human_timing"] for call in supplied],[human,human])
        import json
        self.assertEqual(json.loads(output.text)["human_timing"],human)


if __name__ == "__main__":
    unittest.main()
