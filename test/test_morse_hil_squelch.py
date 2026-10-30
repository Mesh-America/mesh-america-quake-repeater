#!/usr/bin/env python3
"""Execute actual lab-only receive squelch CLI and identity-bound runner paths."""
from pathlib import Path
import argparse
import importlib.util
import json
import math
import sys
import types
import unittest
from unittest.mock import patch

from test_morse_tx import compile_run, portable_radio_header

ROOT = Path(__file__).resolve().parents[1]


def load_bench():
    serial = types.ModuleType("serial")
    serial_tools = types.ModuleType("serial.tools")
    serial_tools.list_ports = types.SimpleNamespace(comports=lambda: [])
    with patch.dict(sys.modules, {"serial": serial, "serial.tools": serial_tools}):
        spec = importlib.util.spec_from_file_location("squelch_bench", ROOT / "tools/hil/morse_bench.py")
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
    return bench


class MorseHilSquelchTests(unittest.TestCase):
    def test_actual_cli_strict_bounds_idle_ownership_volatile_and_shipping_absence(self):
        prefix = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        prefix = prefix.replace("struct TestRadio : mesh::Radio {",
                                "struct TestRadio : mesh::Radio {\n  bool packet=false; bool isReceiving() override { return packet; }")
        code = prefix + r'''
int main() {
  TestRadio radio;
  radio.rx_supported=true;
  struct Guard { char reply[157]; uint32_t after=0xaabbccdd; } out;
  const auto run=[&](const char* text) {
    assert(mesh::handleMorseCommand(&radio,text,out.reply,sizeof(out.reply)));
    assert(out.after==0xaabbccdd && strlen(out.reply)<sizeof(out.reply));
    return std::string(out.reply);
  };
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  assert(run("get morse.hil.squelch")=="> auto; volatile HIL RX only");
  assert(isnan(mesh::morseHilSquelch()));
  for(const char* value : {"-160","0","-100.125"}) {
    const auto command=std::string("set morse.hil.squelch ")+value;
    assert(run(command.c_str()).find("OK -")==0);
  }
  assert(fabsf(mesh::morseHilSquelch()+100.125f)<0.0001f);
  const float accepted=mesh::morseHilSquelch();
  assert(run("get morse.hil.squelch")=="> -100.125 dBm; volatile HIL RX only");
  for(const char* invalid : {"", "nan", "NaN", "inf", "-inf", "1", "-160.01", "-999",
      "1e2", "-100x", "auto x", "AUTO", "auto,1", "--100", "42949672960"}) {
    const auto command=std::string("set morse.hil.squelch ")+invalid;
    assert(run(command.c_str()).find("Error:")==0);
    assert(mesh::morseHilSquelch()==accepted);
  }
  for(bool* busy : {&radio.active,&radio.cw,&radio.rx_active,&radio.packet}) {
    *busy=true;
    assert(run("set morse.hil.squelch auto").find("busy")!=std::string::npos);
    assert(run("get morse.hil.squelch").find("-100.125")!=std::string::npos);
    *busy=false;
  }
  radio.receiving=false;
  assert(run("set morse.hil.squelch auto").find("busy")!=std::string::npos);
  radio.receiving=true;
  assert(run("get morse.hil.squelch extra").find("Error:")==0);
  assert(run("morse.hil.squelch -100").find("Error:")==0);
  assert(run("set morse.hil.squelch auto").find("OK -")==0);
  assert(isnan(mesh::morseHilSquelch()));
  radio.rx_supported=false;
  assert(run("set morse.hil.squelch -100").find("unsupported")!=std::string::npos);
  assert(isnan(mesh::morseHilSquelch()));
  assert(mesh::saves==0 && radio.starts==0 && radio.stops==0 && radio.rx_starts==0 && radio.rx_stops==0);
#else
  (void)run;
  for(const char* command : {"get morse.hil.squelch","set morse.hil.squelch -100",
      "set morse.hil.squelch auto","morse.hil.squelch"}) {
    strcpy(out.reply,"unchanged");
    assert(!mesh::handleMorseCommand(&radio,command,out.reply,sizeof(out.reply)));
    assert(!strcmp(out.reply,"unchanged") && out.after==0xaabbccdd);
  }
  assert(mesh::saves==0 && radio.starts==0 && radio.stops==0 && radio.rx_starts==0);
#endif
}
'''
        fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        for hil in (0, 1):
            with self.subTest(hil=hil):
                compile_run(self, code, flags=("-Wno-unused-parameter", f"-DMESH_MORSE_HIL={hil}"),
                            headers={"Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs_mock})

    def test_argument_readback_validation_safe_standard_fallback_and_cleanup(self):
        bench = load_bench()
        self.assertIsNone(bench.parse_rx_squelch("auto"))
        for text, expected in (("-160",-160),("0",0),("-100.1254",-100.125),("-.5",-.5)):
            self.assertEqual(bench.parse_rx_squelch(text),expected)
        for text in ("","NaN","nan","inf","-inf","1","-160.01","-1e2","-100x","auto x"):
            with self.subTest(text=text),self.assertRaises(argparse.ArgumentTypeError):
                bench.parse_rx_squelch(text)
        device = object.__new__(bench.Console)
        calls = []
        device.start_when_idle=lambda command:calls.append(command)
        device.command=lambda command:(calls.append(command),"> -100.125 dBm; volatile HIL RX only")[1]
        self.assertIn("-100.125",device.set_rx_squelch(-100.125))
        self.assertEqual(calls,["set morse.hil.squelch -100.125","get morse.hil.squelch"])
        for value in (math.nan,math.inf,-math.inf,1,-160.01):
            before=len(calls)
            with self.assertRaises(ValueError): device.set_rx_squelch(value)
            self.assertEqual(len(calls),before)
        device.command=lambda command:"> auto; volatile HIL RX only"
        with self.assertRaisesRegex(RuntimeError,"readback mismatch"): device.set_rx_squelch(-100)
        self.assertIn("auto",device.set_rx_squelch())
        device.command=lambda command:"> -100.125x dBm; volatile HIL RX only"
        with self.assertRaisesRegex(RuntimeError,"readback mismatch"): device.set_rx_squelch(-100.125)
        device.start_when_idle=lambda command:(_ for _ in ()).throw(RuntimeError(
            "set morse.hil.squelch auto: Error: unknown setting: morse.hil.squelch"))
        self.assertEqual(device.set_rx_squelch(),"production image: adaptive RX squelch only")
        with self.assertRaisesRegex(RuntimeError,"unknown setting"): device.set_rx_squelch(-100)
        device.failed=True
        with self.assertRaisesRegex(RuntimeError,"unknown setting"): device.set_rx_squelch()
        device.failed=False
        device.start_when_idle=lambda command:(_ for _ in ()).throw(RuntimeError("Error: radio busy"))
        with self.assertRaisesRegex(RuntimeError,"busy"): device.set_rx_squelch()
        calls=[]
        device.command=lambda command,**kwargs:calls.append(command)
        device.set_hil_timing=lambda:calls.append("timing reset")
        device.set_rx_squelch=lambda:calls.append("squelch auto")
        device.port=types.SimpleNamespace(close=lambda:calls.append("port close"))
        device.close()
        self.assertEqual(calls,["morse stop","timing reset","squelch auto","set morse.wpm 25","port close"])
        device.failed=True; calls=[]
        device.close()
        self.assertEqual(calls,["port close"])

    def test_trial_squelch_only_receiver_exact_match_and_metadata(self):
        bench=load_bench()
        actions=[]
        class Device:
            def __init__(self,name,text="SOS"): self.serial_number=name; self.text=text
            def command(self,command):
                actions.append((self.serial_number,command))
                return "> off;" if command=="get morse" else "OK"
            def start_when_idle(self,command): return self.command(command)
            def set_hil_timing(self,value): return "standard timing"
            def set_rx_squelch(self,value):
                actions.append((self.serial_number,"squelch",value))
                return f"> {value:.3f} dBm; volatile HIL RX only"
            def capture(self): return self.text
        for text,passed in (("SOS",True),(" SOS ",True),("E SOS",False),("SOS E",False),("S OS",False),("SO?",False)):
            actions.clear()
            with patch.object(bench.time,"sleep"):
                result=bench.trial(Device("tx"),Device("rx",text),25,"SOS",rx_squelch=-100)
            self.assertEqual(result["passed"],passed)
            self.assertEqual(result["decoded"],text)
            self.assertEqual(result["rx_squelch_dbm"],-100)
            self.assertIn("-100.000",result["rx_squelch_status"])
            self.assertEqual([a for a in actions if len(a)==3],[("rx","squelch",-100)])
            self.assertLess(actions.index(("rx","squelch",-100)),actions.index(("rx","morse listen 1.0000")))
            self.assertFalse(any("set tx" in a[1] for a in actions))

    def test_main_quiet_both_receivers_and_trial_option_exact_identities(self):
        bench=load_bench()
        class Output:
            def exists(self): return False
            def write_text(self,text): self.text=text
        for quiet in (False,True):
            output=Output(); opened=[]; calls=[]; trials=[]
            class Device:
                def __init__(self,identity):
                    self.serial_number=identity; self.commands=[]; opened.append(identity)
                def setup(self,frequency): calls.append((self.serial_number,"setup",frequency))
                def close(self): calls.append((self.serial_number,"close"))
                def command(self,command): self.commands.append(command); return "stats"
                def start_when_idle(self,command): self.command(command)
                def set_rx_squelch(self,value):
                    calls.append((self.serial_number,"squelch",value))
                    return "> -100.000 dBm; volatile HIL RX only"
                def capture(self): return ""
            def trial(*args,**kwargs): trials.append(kwargs); return {"passed":True}
            argv=["bench","--output","memory","--rates","25","--messages","1","--rx-squelch","-100"]
            if quiet: argv+=["--quiet-seconds","1"]
            with patch.object(bench,"Console",Device),patch.object(bench,"trial",trial), \
                 patch.object(bench,"Path",lambda path:output),patch.object(bench.time,"sleep"), \
                 patch("builtins.print"),patch.object(sys,"argv",argv):
                bench.main()
            result=json.loads(output.text)
            self.assertEqual(opened,[bench.SERIALS["rak"],bench.SERIALS["t096"]])
            self.assertEqual(result["rx_squelch_dbm"],-100)
            if quiet:
                self.assertEqual([c for c in calls if len(c)==3 and c[1]=="squelch"],
                                 [(identity,"squelch",-100) for identity in opened])
                self.assertEqual(len(result["trials"]),2)
                for row in result["trials"]:
                    self.assertEqual(row["rx_squelch_dbm"],-100)
                    self.assertIn("-100.000",row["rx_squelch_status"])
                    self.assertTrue(row["passed"])
                self.assertEqual(trials,[])
            else:
                self.assertEqual([row["rx_squelch"] for row in trials],[-100,-100])


if __name__ == "__main__":
    unittest.main()
