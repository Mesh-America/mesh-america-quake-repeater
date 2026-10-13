#!/usr/bin/env python3
"""No-hardware tests for capture paging and identity/nonce-bound LoRa replies."""
from pathlib import Path
import argparse
import asyncio
import importlib.util
import json
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# Load the actual hardware runner with inert imports; these tests never create
# a serial port, run an SDK, touch a real output file or send radio commands.
serial_mock = types.ModuleType("serial")
serial_tools_mock = types.ModuleType("serial.tools")
serial_tools_mock.list_ports = types.SimpleNamespace(comports=lambda: [])
with patch.dict(sys.modules, {"serial":serial_mock,"serial.tools":serial_tools_mock}):
    bench_spec = importlib.util.spec_from_file_location("tested_morse_bench",ROOT / "tools/hil/morse_bench.py")
    actual_bench = importlib.util.module_from_spec(bench_spec)
    bench_spec.loader.exec_module(actual_bench)

bench = types.ModuleType("morse_bench")
bench.Console, bench.SERIALS = object, {"rak": "test-rak", "t096": "test-source","pocket":"test-pocket"}
bench.live_temporary_profile = actual_bench.live_temporary_profile
bench.DEFAULT_CW_FREQUENCY = actual_bench.DEFAULT_CW_FREQUENCY
bench.parse_cw_frequency = actual_bench.parse_cw_frequency
with patch.dict(sys.modules, {"morse_bench": bench}):
    spec = importlib.util.spec_from_file_location("tested_morse_remote", ROOT / "tools/hil/morse_remote.py")
    remote = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(remote)

KEY = "ab" * 32


def page(offset, total, following, fragment, truncated=0):
    marker = "END " if following is None else f"{following:04d}"
    return f"> {offset:04d}/{total:04d} next={marker} truncated={truncated} {fragment}"


class CaptureParserTests(unittest.TestCase):
    def test_cw_frequency_default_band_and_packet_guard_are_enforced(self):
        self.assertEqual(actual_bench.DEFAULT_CW_FREQUENCY,902.1)
        self.assertEqual(remote.DEFAULT_CW_FREQUENCY,902.1)
        for text,expected in (("902.1000001",902.1),("902",902.0),("928",928.0),
                              ("909.239999",909.239999),("909.760001",909.760001)):
            self.assertEqual(actual_bench.parse_cw_frequency(text),expected)
            self.assertEqual(remote.parse_cw_frequency(text),expected)
        for text in ("nan","inf","-inf","oops","901.999999","928.000001","909.5","909.24","909.76"):
            with self.subTest(text=text),self.assertRaises(argparse.ArgumentTypeError):
                actual_bench.parse_cw_frequency(text)

    def test_capture_evidence_keeps_transport_and_rf_accuracy_independent(self):
        local_pages=[{"offset":0,"reply":"local evidence"}]
        remote_pages=[{"offset":0,"reply":"remote evidence"}]
        noisy="REMOTE MORSE TEST E "
        evidence=remote.capture_evidence("REMOTE MORSE TEST",noisy,local_pages,noisy,remote_pages)
        self.assertTrue(evidence["exact_remote_match"])
        self.assertFalse(evidence["exact_rf_match"],"extra E noise must never become a successful RF result")
        self.assertEqual(evidence["local"],noisy)
        self.assertEqual(evidence["remote"],noisy)
        self.assertEqual(evidence["local_pages"],local_pages)
        self.assertEqual(evidence["remote_pages"],remote_pages)
        before_remote=remote.capture_evidence("SOS","SOS ",local_pages)
        self.assertIsNone(before_remote["exact_remote_match"])
        self.assertTrue(before_remote["exact_rf_match"])
        self.assertIsNone(before_remote["remote"])
        self.assertEqual(before_remote["remote_pages"],[])
        changed=remote.capture_evidence("SOS","SOS ",local_pages,"SOS",remote_pages)
        self.assertFalse(changed["exact_remote_match"],"transport must preserve even trailing whitespace exactly")
        self.assertTrue(changed["exact_rf_match"])

    def test_only_live_temporary_profiles_are_accepted(self):
        self.assertEqual(actual_bench.live_temporary_profile("> TempRadio active: 909.500,500,5,5 (30 min)\r\n> "),(909.5,500,5,5))
        self.assertEqual(actual_bench.live_temporary_profile("get tempradio\r\n  -> > 919.5,500.000,5,5,88\r\n"),(919.5,500,5,5))
        for reply in ("> off", "TempRadio inactive", "TempRadio pending: 909.5,500,5,5",
                      "saved radio: 909.5,500,5,5", "OK - saved", "TempRadio active: nan,500,5,5",
                      "TempRadio active: 909.5,500,5,5junk", "> 909.5,500,5,5,88,extra"):
            with self.subTest(reply=reply):
                self.assertIsNone(actual_bench.live_temporary_profile(reply))

    def test_nominal_cw_duration_matches_units_and_rejects_unencodable_words(self):
        # SOS is 21 mark/intra-character units plus two three-unit letter gaps.
        self.assertEqual(remote.nominal_seconds("SOS",25),27*.048)
        self.assertEqual(remote.nominal_seconds("E E",25),9*.048)
        self.assertEqual(remote.nominal_seconds("E",1),1.2)
        self.assertEqual(remote.nominal_seconds("E",60),.02)
        self.assertEqual(remote.nominal_seconds("?",25),15*.048)
        for text in ("", " SOS", "SOS ", "S  O", "S\tO"):
            with self.subTest(text=text), self.assertRaises((ValueError, KeyError)):
                remote.nominal_seconds(text,25)
        with self.assertRaises(KeyError):
            remote.nominal_seconds("snowman\u2603",25)

    def test_exact_padded_end_offsets_whitespace_and_maximum_capture(self):
        self.assertEqual(remote.parse_capture_page(page(0, 0, None, ""), 0), ("", None, 0))
        self.assertEqual(remote.parse_capture_page("AB|" + page(0, 8, 4, " SOS"), 0), (" SOS", 4, 8))
        self.assertEqual(remote.parse_capture_page(page(4, 8, None, " E  "), 4), (" E  ", None, 8))
        self.assertEqual(remote.parse_capture_page(page(4000, 4096, None, "E" * 96), 4000), ("E" * 96, None, 4096))
        self.assertEqual(remote.public_key("Public key: " + KEY.upper()), KEY)
        for key in ("none", KEY + "a", KEY + " " + "cd" * 32):
            with self.assertRaises(RuntimeError):
                remote.public_key(key)

    def test_bad_missing_truncated_nonprogressing_or_incomplete_pages_rejected(self):
        for reply, offset in ((page(1, 10, 2, "E"), 0), ("not a page", 0),
                              (page(0, 5, None, "ABC"), 0), (page(0, 5, 3, "AB"), 0),
                              (page(0, 5, 0, ""), 0), (page(0, 2, 2, "AB"), 0),
                              (page(0, 1, None, "AB"), 0), (page(0, 4097, 1, "E"), 0),
                              (page(0, 3, None, "ABC", 1), 0)):
            with self.subTest(reply=reply), self.assertRaises(RuntimeError):
                remote.parse_capture_page(reply, offset)


class BenchControlTests(unittest.TestCase):
    def test_direct_companion_ok_needs_closing_prompt_and_never_accepts_echo_only(self):
        class Port:
            in_waiting=0
            def __init__(self,chunks): self.chunks=iter(chunks); self.reads=0; self.writes=[]
            def write(self,data): self.writes.append(data)
            def read(self,length): self.reads+=1; return next(self.chunks,b"")
        for command,parts in (("set tempradio 909.5,500,5,5,30",(b"set tempradio 909.5,500,5,5,30\r\n",b"  OK\r\n",b"> ")),
                              ("get morse",(b"get morse\r\n  -> > off;\r\n",b"> "))):
            receiver=object.__new__(actual_bench.Console)
            receiver.companion=True; receiver.serial_number="test"; receiver.commands=[]; receiver.port=Port(parts)
            with patch.object(actual_bench,"time",types.SimpleNamespace(monotonic=lambda:0)):
                reply=receiver.command(command)
            self.assertEqual(reply,b"".join(parts).decode())
            self.assertEqual(receiver.port.reads,len(parts))
            self.assertEqual(receiver.port.writes,[(command+"\r\n").encode()])
        receiver=object.__new__(actual_bench.Console)
        receiver.companion=True; receiver.serial_number="test"; receiver.commands=[]
        receiver.port=Port((b"set tempradio 909.5,500,5,5,30\r\n> ",))
        times=iter((0,0,11))
        with patch.object(actual_bench,"time",types.SimpleNamespace(monotonic=lambda:next(times))):
            with self.assertRaisesRegex(RuntimeError,"Incomplete CLI response"):
                receiver.command("set tempradio 909.5,500,5,5,30")

    def test_sync_live_profile_waits_for_exact_applied_tuple_and_times_out(self):
        receiver=object.__new__(actual_bench.Console); receiver.serial_number="test"
        calls=[]; replies=iter(("OK - saved", "TempRadio pending: 909.5,500,5,5","> 919.5,500,5,5,88",
                               "TempRadio active: 909.5,500,5,5 (30 min)"))
        receiver.start_when_idle=lambda text:calls.append(text)
        receiver.command=lambda text:(calls.append(text),next(replies))[1]
        clock=types.SimpleNamespace(monotonic=lambda:0,sleep=lambda delay:calls.append(("sleep",delay)))
        with patch.object(actual_bench,"time",clock):
            self.assertIn("active",receiver.apply_live_temporary("909.5,500,5,5"))
        self.assertEqual(calls[0],"set tempradio 909.5,500,5,5,30")
        self.assertEqual(calls.count("get tempradio"),4)
        self.assertEqual(calls.count(("sleep",.1)),3)
        receiver.command=lambda text:"TempRadio pending: 909.5,500,5,5"
        times=iter((0,13))
        with patch.object(actual_bench,"time",types.SimpleNamespace(monotonic=lambda:next(times),sleep=lambda delay:None)):
            with self.assertRaisesRegex(RuntimeError,"did not apply"):
                receiver.apply_live_temporary("909.5,500,5,5")
        calls.clear()
        with self.assertRaises(ValueError): receiver.apply_live_temporary("909.5,500,5")
        self.assertEqual(calls,[])

    def test_selected_partner_and_direction_open_only_exact_pair(self):
        for partner,direction in ((None,"both"),("pocket","both"),("pocket","to-rak"),("pocket","from-rak")):
            with self.subTest(partner=partner,direction=direction):
                opened=[]; trials=[]
                class Output:
                    text=None
                    def exists(self): return False
                    def write_text(self,text): self.text=text
                output=Output()
                class Console:
                    def __init__(self,identity): self.serial_number=identity; self.commands=[]; opened.append(self)
                    def setup(self,cw_frequency=902.1): self.commands.append("setup"); self.cw_frequency=cw_frequency
                    def close(self): self.commands.append("close")
                def trial(tx,rx,wpm,message,trace=False):
                    trials.append((tx.serial_number,rx.serial_number,wpm,message,trace))
                    return {"passed":True}
                arguments=["morse_bench","--output","memory","--rates","25","--messages","1","--direction",direction]
                if partner:
                    arguments += ["--partner",partner]
                with patch.object(actual_bench,"Console",Console), patch.object(actual_bench,"trial",trial), \
                     patch.object(actual_bench,"Path",lambda path:output),patch("builtins.print"), \
                     patch.object(sys,"argv",arguments):
                    actual_bench.main()
                selected=partner or "t096"
                rak_id,partner_id=actual_bench.SERIALS["rak"],actual_bench.SERIALS[selected]
                self.assertEqual([device.serial_number for device in opened],[rak_id,partner_id])
                expected=[]
                if direction in ("both","to-rak"): expected.append((partner_id,rak_id))
                if direction in ("both","from-rak"): expected.append((rak_id,partner_id))
                self.assertEqual([(item[0],item[1]) for item in trials],expected)
                self.assertTrue(all(item[2:]==(25,actual_bench.MESSAGES[0],False) for item in trials))
                self.assertTrue(all(device.commands==["setup","close"] for device in opened))
                self.assertTrue(all(device.cw_frequency==902.1 for device in opened))
                result=json.loads(output.text)
                self.assertEqual(result["partner"],selected)
                self.assertEqual(result["direction"],direction)
                self.assertEqual(set(result["commands"]),{"rak",selected})
                self.assertTrue(result["finished"])
        with patch.object(actual_bench,"Console") as console,patch.object(actual_bench,"Path") as output_path, \
             patch.object(sys,"argv",["morse_bench","--output","memory","--partner","pocket","--t096-rxgain","off"]), \
             patch("sys.stderr"):
            output_path.return_value.exists.return_value=False
            with self.assertRaises(SystemExit): actual_bench.main()
            console.assert_not_called()

    def test_capture_payload_error_is_not_confused_with_cli_error(self):
        commands=[]
        receiver=object.__new__(actual_bench.Console)
        def command(text,**kwargs):
            commands.append((text,kwargs))
            return page(0,5,None,"ERROR")
        receiver.command=command
        self.assertEqual(receiver.capture(),"ERROR")
        self.assertEqual(commands,[("morse read 0",{"allow_error":True})])
        receiver.command=lambda text,**kwargs: "Error: no capture"
        with self.assertRaisesRegex(RuntimeError,"Malformed"):
            receiver.capture()

    def test_quiet_control_never_transmits_and_restores_gain_on_success_or_failure(self):
        for failure in (None,"gain_set","capture"):
            with self.subTest(failure=failure):
                devices=[]
                class Output:
                    text=None
                    def exists(self): return False
                    def write_text(self,text): self.text=text
                output=Output()
                class Console:
                    def __init__(self,identity):
                        self.serial_number=identity; self.commands=[]; self.closed=False
                        devices.append(self)
                    def setup(self,cw_frequency=902.1): self.commands.append("setup")
                    def command(self,text,*args,**kwargs):
                        self.commands.append(text)
                        if text=="get radio.fem.rxgain": return "> on"
                        if text=="set radio.fem.rxgain off" and failure=="gain_set":
                            raise RuntimeError("injected gain set failure")
                        return "OK"
                    def start_when_idle(self,text): return self.command(text)
                    def set_rx_squelch(self,value=None):
                        assert value is None, "Default quiet control must retain automatic squelch"
                        self.commands.extend(["set morse.hil.squelch auto","get morse.hil.squelch"])
                        return "> auto; volatile HIL RX only"
                    def capture(self):
                        if failure=="capture": raise RuntimeError("injected capture failure")
                        return ""
                    def close(self): self.closed=True
                with patch.object(actual_bench,"Console",Console), patch.object(actual_bench,"Path",lambda path:output), \
                     patch.object(actual_bench.time,"sleep"), patch("builtins.print"), \
                     patch.object(sys,"argv",["morse_bench","--output","memory","--quiet-seconds","1","--t096-rxgain","off"]):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError,"injected"):
                            actual_bench.main()
                    else:
                        actual_bench.main()
                self.assertEqual(len(devices),2)
                self.assertTrue(all(device.closed for device in devices))
                gain_device=next(device for device in devices if device.serial_number==actual_bench.SERIALS["t096"])
                self.assertEqual(gain_device.commands[-2:],["morse stop","set radio.fem.rxgain on"])
                self.assertFalse(any("morse send" in command for device in devices for command in device.commands))
                result=json.loads(output.text)
                self.assertEqual(result["finished"],failure is None)
                if failure:
                    self.assertIn("injected",result["error"])
                else:
                    self.assertEqual(len(result["trials"]),2)
                    self.assertTrue(all(item["kind"]=="quiet_control" and item["passed"] for item in result["trials"]))
                    self.assertTrue(all(item["rx_squelch_dbm"] is None
                                        and item["rx_squelch_status"]=="> auto; volatile HIL RX only"
                                        for item in result["trials"]))


class HandoffProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_live_profile_waits_for_exact_radio_and_bounds_timeout(self):
        calls=[]; replies=iter(("OK - saved","> off", "TempRadio pending: 909.5,500,5,5",
                               "> 919.5,500,5,5,88","> 909.5,500,5,5,88"))
        async def command(text): calls.append(text); return next(replies)
        with patch.object(remote,"time",types.SimpleNamespace(monotonic=lambda:0)),patch.object(remote.asyncio,"sleep") as sleep:
            self.assertEqual(await remote.apply_live_temporary(command,"909.5,500,5,5"),"> 909.5,500,5,5,88")
        self.assertEqual(calls,["set tempradio 909.5,500,5,5,30"]+["get tempradio"]*4)
        self.assertEqual(sleep.await_count,3)
        async def pending(text): return "TempRadio pending: 909.5,500,5,5"
        times=iter((0,13))
        with patch.object(remote,"time",types.SimpleNamespace(monotonic=lambda:next(times))):
            with self.assertRaisesRegex(RuntimeError,"did not apply"):
                await remote.apply_live_temporary(pending,"909.5,500,5,5")
        calls.clear()
        with self.assertRaises(ValueError): await remote.apply_live_temporary(command,"909.5,500,5")
        self.assertEqual(calls,[])

    def setUp(self):
        class Reader:
            def __init__(self):
                self.forwarded = []

            async def handle_rx(self, data):
                self.forwarded.append(data)

        class Event:
            def __init__(self, payload=None, error=False):
                self.payload, self.error = payload or {}, error

            def is_error(self):
                return self.error

        self.Reader, self.Event = Reader, Event
        self.original = Reader.handle_rx
        self.records, self.actions = [], []
        self.callbacks = []
        self.local_reply, self.remote_reply = None, None
        self.admission_error = False
        self.send_exception = None
        self.mc = types.SimpleNamespace(_reader=Reader())
        self.mc.commands = types.SimpleNamespace(send=self.send_local, send_cmd=self.send_remote)
        self.mc.subscribe = self.subscribe
        self.bridge = remote.BinaryCLI(self.mc, Reader, "CONTACT", lambda kind, **fields: self.records.append((kind, fields)))

    def tearDown(self):
        self.bridge.restore_reader()
        self.assertIs(self.Reader.handle_rx, self.original)

    def subscribe(self, kind, callback):
        self.assertEqual(kind, "CONTACT")
        self.actions.append("subscribe")
        self.callbacks.append(callback)

        def unsubscribe():
            self.actions.append("unsubscribe")
            self.callbacks.remove(callback)

        return types.SimpleNamespace(unsubscribe=unsubscribe)

    def deliver(self, text, peer=KEY[:12], text_type=1):
        for callback in tuple(self.callbacks):
            callback(self.Event({"pubkey_prefix": peer, "txt_type": text_type, "text": text}))

    async def send_local(self, data, expected_events):
        self.actions.append(("local_send", data))
        self.assertIsNone(expected_events)
        self.assertEqual(data[0], 0x42)
        if self.local_reply:
            await self.local_reply(data[1:].decode("ascii"))
        return self.Event()

    async def send_remote(self, key, text, timestamp):
        self.actions.append(("remote_send", key, text, timestamp))
        self.assertTrue(self.callbacks, "subscription must exist before admission/send")
        if self.send_exception:
            raise self.send_exception
        if self.remote_reply:
            self.remote_reply(text)
        return self.Event(error=self.admission_error)

    async def test_capture_paging_preserves_exact_text_and_rejects_changed_total_or_stall(self):
        answers = {"morse read 0": page(0, 8, 4, "SOS "), "morse read 4": page(4, 8, None, "TEST")}

        async def command(text):
            return answers[text]

        text, pages = await remote.read_capture(command)
        self.assertEqual(text, "SOS TEST")
        self.assertEqual([entry["offset"] for entry in pages], [0, 4])
        answers = {"morse read 0": page(0, 5, None, "ERROR")}
        self.assertEqual((await remote.read_capture(command))[0], "ERROR")
        answers = {"morse read 0": page(0, 8, 4, "SOS "), "morse read 4": page(4, 8, None, "TEST")}
        answers["morse read 4"] = page(4, 9, None, "TEST ")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await remote.read_capture(command)

        async def many(text):
            offset = int(text.split()[-1])
            return page(offset, 4096, offset + 1, "E")

        with self.assertRaisesRegex(RuntimeError, "did not finish"):
            await remote.read_capture(many)

    async def test_local_nonce_identity_bound_reader_and_forwarding(self):
        other = self.Reader()

        async def respond(text):
            prefix = text[:3]
            await other.handle_rx(b"\x1d" + prefix.encode() + b"OTHER READER")
            await self.mc._reader.handle_rx(b"\x02normal SDK event")
            await self.mc._reader.handle_rx(b"\x1dZZ|stale")
            await self.mc._reader.handle_rx(b"\x1d" + prefix.encode() + b"> correct")

        self.local_reply = respond
        self.assertEqual(await self.bridge.local("get morse"), "> correct")
        self.assertEqual(await self.bridge.local("get morse"), "> correct")
        self.assertEqual([action[1][1:4] for action in self.actions], [b"00|", b"01|"])
        self.assertEqual(len(other.forwarded), 2)
        self.assertEqual(self.mc._reader.forwarded, [b"\x02normal SDK event"] * 2)
        self.local_reply = None
        with self.assertRaises((TimeoutError, asyncio.TimeoutError, RuntimeError)):
            await self.bridge.local("get morse", timeout=.01)

    async def test_remote_fast_reply_precedes_send_event_and_rejects_wrong_correlation(self):
        def respond(text):
            prefix = text[:3]
            self.deliver(prefix + "wrong peer", peer="cd" * 6)
            self.deliver(prefix + "wrong message type", text_type=0)
            self.deliver("ZZ|wrong nonce")
            self.deliver(prefix + "OK - Morse RX queued", peer=KEY[:12].upper())

        self.remote_reply = respond
        current_utc=1234
        with patch.object(remote.time, "time", side_effect=lambda: current_utc):
            for expected in (1234, 1235):
                current_utc=expected
                reply, latency = await self.bridge.remote(KEY, "morse listen 1")
                self.assertEqual(reply, "OK - Morse RX queued")
                self.assertGreaterEqual(latency, 0)
                self.assertEqual(self.actions[-2][3], expected)
        self.assertEqual(self.actions[0], "subscribe")
        self.assertFalse(self.callbacks)
        self.assertEqual([record[1]["nonce"] for record in self.records], ["00", "01"])

    async def test_frozen_or_backstepped_clock_never_sends_and_unsubscribes(self):
        self.bridge.last_timestamp=1234
        for utc in (1234,1200):
            monotonic=iter((0,3))
            clock=types.SimpleNamespace(time=lambda: utc,monotonic=lambda: next(monotonic))
            with patch.object(remote,"time",clock):
                with self.assertRaisesRegex(RuntimeError,"stopped/backstepped"):
                    await self.bridge.remote(KEY,"morse listen 1")
            self.assertFalse(self.callbacks)
            self.assertFalse(any(isinstance(action,tuple) and action[0]=="remote_send" for action in self.actions))

    async def test_cancellation_during_utc_wait_unsubscribes_without_sending(self):
        self.bridge.last_timestamp=1234
        with patch.object(remote.time,"time",return_value=1234):
            pending=asyncio.create_task(self.bridge.remote(KEY,"morse listen 1"))
            await asyncio.sleep(.001)
            self.assertTrue(self.callbacks)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        self.assertFalse(self.callbacks)
        self.assertFalse(any(isinstance(action,tuple) and action[0]=="remote_send" for action in self.actions))

    async def test_remote_send_admission_is_not_reply_and_all_failures_unsubscribe(self):
        with self.assertRaises((TimeoutError, asyncio.TimeoutError, RuntimeError)):
            await self.bridge.remote(KEY, "morse listen 1", timeout=.01)
        self.assertFalse(self.callbacks)
        self.admission_error = True
        with self.assertRaisesRegex(RuntimeError, "not admitted"):
            await self.bridge.remote(KEY, "morse listen 1")
        self.assertFalse(self.callbacks)
        self.admission_error = False
        self.send_exception = ValueError("transport failed")
        with self.assertRaisesRegex(ValueError, "transport failed"):
            await self.bridge.remote(KEY, "morse listen 1")
        self.assertFalse(self.callbacks)

    async def test_error_replies_nonce_exhaustion_and_reader_restore_do_not_clobber_others(self):
        self.remote_reply = lambda text: self.deliver(text[:3] + "Error: radio busy")
        with self.assertRaisesRegex(RuntimeError, "Remote CLI error"):
            await self.bridge.remote(KEY, "morse listen 1")
        self.assertIn("Error:", (await self.bridge.remote(KEY, "morse listen 1", allow_error=True))[0])
        self.bridge.counter = 36**2
        with self.assertRaisesRegex(RuntimeError, "exhausted"):
            await self.bridge.remote(KEY, "morse listen 1")
        self.assertFalse(self.callbacks)
        external = lambda reader, data: None
        self.Reader.handle_rx = external
        self.bridge.restore_reader()
        self.assertIs(self.Reader.handle_rx, external)
        self.Reader.handle_rx = self.bridge.patched


class HarnessRunTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,source,*,noise=False,sdk_failure=False):
        actions=[]; opened=[]; results={"passed":False}; retained="SOS E " if noise else "SOS "
        source_key="cd"*32
        class Port:
            def __init__(self,identity): self.port=identity; self.is_open=True
            def write(self,data): actions.append(("port_write",self.port,data))
            def close(self): self.is_open=False; actions.append(("port_close",self.port))
        class Console:
            def __init__(self,identity,*args):
                self.identity=identity; self.port=Port(identity); self.commands=[]; self.status_reads=0
                opened.append(self); actions.append(("open",identity))
            def command(self,text,*args,**kwargs):
                self.commands.append(text); actions.append(("console",self.identity,text))
                if text=="get public.key": return KEY if self.identity==remote.SERIALS["rak"] else source_key
                if text=="get tempradio": return "> 909.5,500,5,5,88"
                if text=="get morse":
                    self.status_reads+=1
                    return "> RX 902.100 MHz" if self.status_reads==2 else "> off; captured=4"
                if text.startswith("morse read "): return page(0,len(retained),None,retained)
                return "OK"
            def start_when_idle(self,text): return self.command(text)
            def apply_live_temporary(self,profile): self.commands.append("set tempradio "+profile+",30"); actions.append(("temporary",self.identity,profile))
            def read_quiet(self,*args): return ""
            def close(self): self.port.close()
        class MC:
            def __init__(self): self.commands=types.SimpleNamespace(add_contact=self.add_contact)
            async def add_contact(self,contact):
                actions.append(("contact",contact["public_key"]))
                return types.SimpleNamespace(is_error=lambda:False)
            async def start_auto_message_fetching(self): actions.append(("fetch",))
            async def disconnect(self): actions.append(("disconnect",))
        class MeshCore:
            @staticmethod
            async def create_serial(port,**kwargs):
                actions.append(("sdk_open",port))
                return None if sdk_failure else MC()
        class Bridge:
            def __init__(self,*args): pass
            async def local(self,text,*args,**kwargs):
                actions.append(("local",text))
                if text=="get public.key": return source_key
                if text=="get tempradio": return "> TempRadio active: 909.5,500,5,5 (30 min)"
                return "> off;" if text=="get morse" else "OK"
            async def local_when_idle(self,text,*args,**kwargs): return await self.local(text)
            async def remote(self,key,text,*args,**kwargs):
                actions.append(("remote",text))
                if text=="morse listen 6": return "Error: duration",0
                if text.startswith("morse listen "): return "OK - Morse RX queued",0
                if text.startswith("morse read "): return page(0,len(retained),None,retained),0
                if text=="get tempradio": return "> 909.5,500,5,5,88",0
                if text=="get radio": return "> saved 910.525,250,11,8",0
                return "> off;",0
            def restore_reader(self): actions.append(("reader_restore",))
        sdk=types.ModuleType("meshcore"); sdk.MeshCore=MeshCore
        sdk.EventType=types.SimpleNamespace(CONTACT_MSG_RECV="CONTACT")
        reader=types.ModuleType("meshcore.reader"); reader.MessageReader=object
        async def call_inert(func,*args,**kwargs): return func(*args,**kwargs)
        def record(kind,**fields):
            actions.append(("record",kind))
            results.setdefault("events",[]).append({"kind":kind,**fields})
        args=types.SimpleNamespace(source=source,minutes=.5,wpm=25,message="SOS",repeat=1,cw_frequency=902.1)
        error=None
        with patch.dict(sys.modules,{"meshcore":sdk,"meshcore.reader":reader}), \
             patch.object(remote,"Console",Console),patch.object(remote,"BinaryCLI",Bridge), \
             patch.object(remote.asyncio,"to_thread",call_inert),patch.object(remote.asyncio,"sleep"), \
             patch.object(remote,"time",types.SimpleNamespace(time=lambda:1234,monotonic=lambda:0)):
            try:
                await remote.run(args,results,record)
            except RuntimeError as caught:
                error=caught
        return actions,opened,results,error

    async def test_exact_selected_source_and_expiry_recovery_before_comparison(self):
        for source,noise in (("t096",False),("pocket",False),("pocket",True)):
            with self.subTest(source=source,extra_noise=noise):
                actions,opened,result,error=await self.exercise(source,noise=noise)
                self.assertEqual([device.identity for device in opened],[remote.SERIALS["rak"],remote.SERIALS[source]])
                self.assertTrue(all(not device.port.is_open for device in opened))
                self.assertEqual(result["passed"],not noise)
                if noise:
                    self.assertRegex(str(error),"RF decoded text differs")
                    self.assertFalse(result["capture"]["exact_rf_match"])
                    self.assertTrue(result["capture"]["exact_remote_match"])
                    self.assertEqual(result["capture"]["local"],"SOS E ")
                    self.assertTrue(result["recovery"]["passed"])
                else:
                    self.assertIsNone(error)
                expired=actions.index(("record","listen_expired"))
                verified=actions.index(("record","source_packet_radio_verified"))
                self.assertLess(expired,verified)
                self.assertLess(verified,actions.index(("record","local_capture_received")))
                self.assertLess(actions.index(("record","local_capture_received")),actions.index(("remote","morse read 0")))
                self.assertIn(("record","recovery_checked"),actions)
                self.assertLess(actions.index(("record","recovery_checked")),actions.index(("disconnect",)))
                commands=[action[2] for action in actions if action[0]=="console"]
                commands += [action[1] for action in actions if action[0]=="local"]
                self.assertFalse(any(command.startswith("set name ") or command.startswith("set radio ") for command in commands))
                self.assertFalse(any("919.5" in command for command in commands))
                self.assertTrue(all(action[2]==remote.PACKET_RADIO for action in actions if action[0]=="temporary"))

    async def test_failed_binary_handoff_recovers_only_selected_identity(self):
        actions,opened,result,error=await self.exercise("pocket",sdk_failure=True)
        self.assertRegex(str(error),"Could not start source Binary")
        self.assertEqual([device.identity for device in opened],
                         [remote.SERIALS["rak"],remote.SERIALS["pocket"],remote.SERIALS["pocket"]])
        self.assertTrue(all(not device.port.is_open for device in opened))
        self.assertFalse(result["passed"])
        self.assertFalse(any(action[0]=="local" for action in actions))


if __name__ == "__main__":
    unittest.main()
