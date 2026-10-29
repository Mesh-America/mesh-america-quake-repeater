"""Offline per-relay lease obligations share the production target proof."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import types
import unittest
from unittest import mock
import lora_ota as ota

TARGET='ab'*32
RELAYS=['cd'*32,'ef'*32,'12'*32]
NORMAL=ota.RadioSettings(910.525,62.5,7,5,False)

class RelayCleanupTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(target=TARGET,temp_radio='909.5,500,7,5,180',
            temp_values=(909.5,500,7,5,180),relay_values=[(key,'private-'+str(i)) for i,key in enumerate(RELAYS)])
    def state(self,directory,args,key):
        return ota.RelayTempCleanup(Path(directory),args,NORMAL,key,dict(args.relay_values)[key],key)
    def controller(self,args,modes=None):
        modes=modes or {};calls=[]
        def remote(key,command,**kwargs):
            self.assertIs(kwargs['retry'],False)
            if key!=TARGET:self.assertEqual(kwargs['password'],dict(args.relay_values)[key])
            calls.append((key,command))
            mode=modes.get(key,'off')
            if command.startswith('tempradio '):
                if mode in ('lost-delivered','lost-undelivered'):raise ota.TransmissionError('lost ACK')
                if mode=='error':raise ota.OtaError('failed private-0')
                if mode=='interrupt':raise KeyboardInterrupt()
                return 'OK - temp params for 1 mins'
            if command=='get public.key':return '> '+('34'*32 if mode=='changed-key' else key)
            if command=='get tempradio':return '> 909.500,500.000,7,5,32' if mode in ('active','lost-undelivered') else '> off'
            raise AssertionError(command)
        return types.SimpleNamespace(remote_command=remote,get_radio=lambda **kwargs:NORMAL,calls=calls)
    def clock(self):
        clock=types.SimpleNamespace(now=100.0)
        def sleep(seconds):clock.now+=seconds
        return clock,types.SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep)
    def test_lost_delivered_relay_ack_resolves_only_from_independent_normal_off(self):
        args=self.args();key=RELAYS[0];c=self.controller(args,{key:'lost-delivered'})
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stderr(io.StringIO()):
            state=self.state(d,args,key)
            self.assertFalse(ota.shorten_relay_temp_windows(c,args,[(key,'private-0')],{key:key},cleanup_states={key:state}))
            self.assertTrue(state.report['cleanup_required'])
            self.assertFalse(state.report['shorten_acknowledged'])
            state.prove_normal(c,args)
            self.assertTrue(state.report['normal_return_verified'])
            self.assertEqual(c.calls,[(key,'tempradio 909.5,500,7,5,1'),(key,'get public.key'),(key,'get tempradio')])
            self.assertNotIn('private-0',state.path.read_text())
    def test_lost_undelivered_relay_ack_keeps_its_own_obligation(self):
        args=self.args();key=RELAYS[0];c=self.controller(args,{key:'lost-undelivered'});clock,fake=self.clock()
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
            state=self.state(d,args,key)
            state.shorten_once(c,args)
            with mock.patch.object(ota,'time',fake),self.assertRaises(ota.TransmissionError):state.prove_normal(c,args)
            saved=json.loads(state.path.read_text())
            self.assertTrue(saved['cleanup_required']);self.assertFalse(saved['normal_return_verified'])
            self.assertLessEqual(clock.now,190)
            state.shorten_once(c,args)
            self.assertEqual(sum(cmd.startswith('tempradio ') for _,cmd in c.calls),1)
    def test_changed_relay_full_identity_is_terminal_and_never_resolves(self):
        args=self.args();key=RELAYS[0];c=self.controller(args,{key:'changed-key'})
        with tempfile.TemporaryDirectory() as d:
            state=self.state(d,args,key)
            with self.assertRaisesRegex(ota.OtaError,'public key changed'):state.prove_normal(c,args)
            self.assertEqual(c.calls,[(key,'get public.key')]);self.assertTrue(state.report['cleanup_required'])
    def test_target_off_does_not_prove_a_relay_off_and_other_proofs_continue(self):
        args=self.args();c=self.controller(args,{RELAYS[0]:'active'});clock,fake=self.clock()
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
            target=ota.TargetTempCleanup(Path(d),args,NORMAL)
            states={key:self.state(d,args,key) for key in RELAYS[:2]}
            with mock.patch.object(ota,'time',fake),self.assertRaisesRegex(ota.OtaError,'normal return remains unproven'):
                ota.prove_owned_temp_cleanups(c,args,target,states)
            self.assertFalse(target.report['cleanup_required'])
            self.assertTrue(states[RELAYS[0]].report['cleanup_required'])
            self.assertFalse(states[RELAYS[1]].report['cleanup_required'])
            before=list(c.calls)
            with self.assertRaises(ota.OtaError):ota.prove_owned_temp_cleanups(c,args,target,states)
            self.assertEqual(c.calls,before) # No repeated failed proof nor relative setter.
    def test_each_independent_shortening_attempt_survives_errors_and_interrupts_once(self):
        args=self.args();modes={RELAYS[0]:'error',RELAYS[1]:'interrupt',RELAYS[2]:'lost-delivered'}
        c=self.controller(args,modes)
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stderr(io.StringIO()):
            states={key:self.state(d,args,key) for key in RELAYS}
            original=c.remote_command
            def before_send(key,command,**kwargs):
                self.assertTrue(json.loads(states[key].path.read_text())['shorten_attempted'])
                return original(key,command,**kwargs)
            c.remote_command=before_send
            with self.assertRaises(KeyboardInterrupt):ota.shorten_relay_temp_windows(c,args,cleanup_states=states)
            self.assertEqual([key for key,_ in c.calls],RELAYS)
            self.assertFalse(ota.shorten_relay_temp_windows(c,args,cleanup_states=states))
            self.assertEqual(len(c.calls),3)
            for key,state in states.items():
                self.assertTrue(state.report['shorten_attempted']);self.assertTrue(state.report['cleanup_required'])
                self.assertNotIn(dict(args.relay_values)[key],state.path.read_text())
                self.assertEqual(state.path.stat().st_mode&0o777,0o600)
    def test_missing_or_rebound_ownership_stops_before_any_write(self):
        args=self.args();c=self.controller(args)
        with tempfile.TemporaryDirectory() as d:
            states={RELAYS[0]:self.state(d,args,RELAYS[0])}
            with self.assertRaises(ota.OtaError):ota.shorten_relay_temp_windows(c,args,cleanup_states=states)
            self.assertEqual(c.calls,[])
            with self.assertRaises(ota.OtaError):ota.RelayTempCleanup(Path(d),args,NORMAL,RELAYS[1],'private-1',RELAYS[2])
            args.relay_values=[]
            with self.assertRaises(ota.OtaError):states[RELAYS[0]].prove_normal(c,args)
            self.assertEqual(c.calls,[])

    def test_fresh_process_keeps_attempt_and_constructor_cannot_reset_it(self):
        args=self.args();key=RELAYS[0];c=self.controller(args,{key:'lost-delivered'})
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stderr(io.StringIO()):
            state=self.state(d,args,key);state.shorten_once(c,args)
            before=state.path.read_bytes()
            probe=subprocess.run([sys.executable,'-B','-c',
                'import json,sys;d=json.load(open(sys.argv[1]));assert d["shorten_attempted"] and d["cleanup_required"];assert not d["shorten_acknowledged"]',str(state.path)],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(probe.returncode,0,probe.stderr)
            with self.assertRaisesRegex(ota.OtaError,'must not be overwritten'):self.state(d,args,key)
            self.assertEqual(state.path.read_bytes(),before)
            self.assertEqual(sum(cmd.startswith('tempradio ') for _,cmd in c.calls),1)

    def test_saved_normal_radio_does_not_hide_a_shared_live_temporary_override(self):
        args=self.args();args.source_shares_controller=True
        c=self.controller(args);clock,fake=self.clock()
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
            state=self.state(d,args,RELAYS[0])
            with mock.patch.object(ota,'time',fake),mock.patch.object(ota,'read_source_temp_radio_status',return_value=('active',ota.RadioSettings(909.5,500,7,5,False))),self.assertRaises(ota.TransmissionError):
                state.prove_normal(c,args)
            self.assertTrue(state.report['cleanup_required'])
            self.assertEqual(c.calls,[])
            self.assertTrue(all(r.get('state')=='active' for r in state.report['proof_records']))

    def test_authenticated_reply_capture_never_persists_private_password_text(self):
        args=self.args();key=RELAYS[0];c=self.controller(args);original=c.remote_command
        def reply(key,command,**kwargs):
            value=original(key,command,**kwargs)
            return value+'\nprivate-0' if command=='get public.key' else value
        c.remote_command=reply
        with tempfile.TemporaryDirectory() as d:
            state=self.state(d,args,key);state.prove_normal(c,args)
            self.assertFalse(state.report['cleanup_required'])
            self.assertNotIn('private-0',state.path.read_text())

    def test_target_env_or_getpass_secret_is_redacted_without_args_password(self):
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as d:
                args=self.args();args.password=None;secret='resolved-getpass-fixture'
                def remote(key,command,**kwargs):
                    self.assertEqual(kwargs['password'],secret)
                    if command.startswith('tempradio '):raise ota.TransmissionError('lost '+secret)
                    if command=='get public.key':return '> '+TARGET+'\n'+secret
                    if fail:raise ota.OtaError('proof failed '+secret)
                    return '> off'
                c=types.SimpleNamespace(remote_command=remote,get_radio=lambda **kwargs:NORMAL)
                state=ota.TargetTempCleanup(Path(d),args,NORMAL,password=secret)
                warning=io.StringIO()
                with contextlib.redirect_stderr(warning):state.shorten_once(c,args)
                self.assertNotIn(secret,warning.getvalue())
                if fail:
                    with self.assertRaises(ota.OtaError):state.prove_normal(c,args)
                    self.assertTrue(state.report['cleanup_required'])
                else:state.prove_normal(c,args)
                self.assertNotIn(secret,state.path.read_text())

if __name__=='__main__':unittest.main()
