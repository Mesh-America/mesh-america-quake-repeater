"""Offline regression tests for uncertain target TempRadio cleanup."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import lora_ota as ota
import test_lora_ota as fixtures

KEY='ab'*32
NORMAL=ota.RadioSettings(910.525,62.5,7,5,False)

class CleanupTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(target=KEY,temp_radio='909.5,500,7,5,180',temp_values=(909.5,500,7,5,180))
    def controller(self,mode='off'):
        calls=[]
        def remote(target,command,**kwargs):
            self.assertEqual(target,KEY);self.assertIs(kwargs['retry'],False);calls.append(command)
            if command.startswith('tempradio '):
                if mode in ('lost','long'):raise ota.TransmissionError('lost cleanup ACK')
                return 'OK - temp params for 1 mins'
            if command=='get public.key':
                return '> '+('cd'*32 if mode=='wrong-key' else KEY)
            if command=='get tempradio':
                if mode=='long':raise ota.TransmissionError('still only reachable on old temporary tuple')
                if mode=='malformed':return '> unexpected'
                return '> off'
            raise AssertionError(command)
        return types.SimpleNamespace(remote_command=remote,get_radio=lambda **kwargs:NORMAL,calls=calls)
    def state(self,directory):return ota.TargetTempCleanup(Path(directory),self.args(),NORMAL)
    def test_lost_ack_does_not_accept_temporary_identity_as_return(self):
        controller=self.controller('lost')
        with contextlib.redirect_stderr(io.StringIO()) as warning:
            acknowledged=ota.shorten_target_temp_window(controller,self.args())
        self.assertFalse(acknowledged)
        self.assertEqual(controller.calls,['tempradio 909.5,500,7,5,1'])
        self.assertIn('original long lease may remain active',warning.getvalue())
    def test_attempt_is_persisted_before_send_and_never_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state(directory);controller=self.controller('lost');remote=controller.remote_command
            def checked(*args,**kwargs):
                self.assertTrue(json.loads(state.path.read_text())['shorten_attempted'])
                return remote(*args,**kwargs)
            controller.remote_command=checked
            with contextlib.redirect_stderr(io.StringIO()):state.shorten_once(controller,self.args())
            state.shorten_once(controller,self.args())
            self.assertEqual(len(controller.calls),1)
            self.assertTrue(state.report['cleanup_required'])
            self.assertFalse(state.report['shorten_acknowledged'])
            self.assertEqual(state.path.stat().st_mode&0o777,0o600)
    def test_positive_ack_still_requires_independent_normal_return(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state(directory);controller=self.controller()
            state.shorten_once(controller,self.args())
            self.assertTrue(state.report['shorten_acknowledged'])
            self.assertTrue(state.report['cleanup_required'])
            state.prove_normal(controller,self.args())
            self.assertFalse(state.report['cleanup_required'])
            self.assertTrue(state.report['normal_return_verified'])
            self.assertEqual(controller.calls,['tempradio 909.5,500,7,5,1','get public.key','get tempradio'])
    def test_lost_ack_can_resolve_only_from_full_key_and_inactive_temp_on_normal(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state(directory);controller=self.controller('lost')
            with contextlib.redirect_stderr(io.StringIO()):state.shorten_once(controller,self.args())
            state.prove_normal(controller,self.args())
            self.assertTrue(state.report['normal_return_verified'])
            self.assertFalse(state.report['shorten_acknowledged'])
            self.assertEqual(len([x for x in controller.calls if x.startswith('tempradio ')]),1)
    def test_wrong_key_and_malformed_status_are_not_retried(self):
        for mode,expected_count in [('wrong-key',1),('malformed',2)]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                state=self.state(directory);controller=self.controller(mode)
                with self.assertRaises(ota.OtaError):state.prove_normal(controller,self.args())
                self.assertEqual(len(controller.calls),expected_count)
                self.assertTrue(json.loads(state.path.read_text())['cleanup_required'])
    def test_active_profile_is_not_mistaken_for_normal_return(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state(directory);controller=self.controller();remote=controller.remote_command
            clock=types.SimpleNamespace(now=100.0)
            def sleep(seconds):clock.now+=seconds
            fake_time=types.SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep)
            def active_until_return(target,command,**kwargs):
                if command=='get tempradio' and clock.now<175:
                    controller.calls.append(command);return '> 909.500,500.000,7,5,32'
                return remote(target,command,**kwargs)
            controller.remote_command=active_until_return
            with mock.patch.object(ota,'time',fake_time),contextlib.redirect_stdout(io.StringIO()):
                state.prove_normal(controller,self.args())
            self.assertGreaterEqual(clock.now,175)
            self.assertTrue(state.report['normal_return_verified'])
            self.assertGreater(len(state.report['proof_records']),2)
    def test_unresolved_long_lease_keeps_obligation_and_bounded_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state(directory);controller=self.controller('long');clock=types.SimpleNamespace(now=100.0)
            def sleep(seconds):clock.now+=seconds
            fake_time=types.SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep)
            remote=controller.remote_command
            def bounded_loss(target,command,**kwargs):
                if command=='get tempradio':clock.now+=min(20,kwargs['operation_timeout'])
                return remote(target,command,**kwargs)
            controller.remote_command=bounded_loss
            with mock.patch.object(ota,'time',fake_time),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ota.TransmissionError):
                state.prove_normal(controller,self.args())
            saved=json.loads(state.path.read_text())
            self.assertTrue(saved['cleanup_required']);self.assertFalse(saved['normal_return_verified'])
            self.assertLessEqual(clock.now,190)
            self.assertTrue(all(r['operation_timeout']<=190-r['started_at'] for r in saved['proof_records']))
            self.assertFalse(any(x.startswith('tempradio ') for x in controller.calls))
    def test_wrong_controller_channel_stops_before_target_read(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state(directory);controller=self.controller()
            controller.get_radio=lambda **kwargs:ota.RadioSettings(909.5,500,7,5,False)
            with self.assertRaises(ota.OtaError):state.prove_normal(controller,self.args())
            self.assertEqual(controller.calls,[])
            self.assertTrue(state.report['cleanup_required'])

    def test_failed_main_keeps_obligation_after_lost_cleanup_ack(self):
        controller=mock.Mock()
        controller.get_radio.return_value=NORMAL
        calls=[];clock=types.SimpleNamespace(now=100.0)
        def remote(target,command,**kwargs):
            self.assertEqual(target,KEY);self.assertIs(kwargs['retry'],False)
            calls.append(command)
            if command.startswith('tempradio '):
                raise ota.TransmissionError('lost one-minute cleanup ACK')
            self.assertEqual(command,'get public.key')
            clock.now+=min(20,kwargs['operation_timeout'])
            raise ota.TransmissionError('target remains on the original long lease')
        controller.remote_command.side_effect=remote
        def sleep(seconds):clock.now+=seconds
        fake_time=types.SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep,time=lambda:1800000000)
        image=fixtures.firmware(b'cleanup main regression'*300,fixtures.VERSION_NEW)
        package=ota.parse_mota(fixtures.mota_blob(image));seeder=mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)/'work'
            argv=['release.mota',KEY,'--controller-serial','/dev/controller',
                  '--source-serial','/dev/source','--password','test-only',
                  '--work-dir',str(work),'--yes']
            error=io.StringIO()
            with contextlib.ExitStack() as stack:
                for name in ('preflight_inputs','preflight_source_cli','bind_contact_selectors',
                             'ensure_source_clock_gate_safe','ensure_controller_clock_safe',
                             'verify_shared_source_identity','confirm_update','run_temp_radio_preflight',
                             'arm_target_temp_radio','switch_controller_to_temp_radio',
                             'find_and_start_pull'):
                    stack.enter_context(mock.patch.object(ota,name))
                stack.enter_context(mock.patch.object(ota,'time',fake_time))
                stack.enter_context(mock.patch.object(ota,'read_source_rxps',return_value=ota.RxpsSettings(False,0,0)))
                stack.enter_context(mock.patch.object(ota,'read_remote_rxps',return_value=ota.RxpsSettings(False,0,0)))
                stack.enter_context(mock.patch.object(ota,'disable_source_rxps',return_value=False))
                stack.enter_context(mock.patch.object(ota,'read_lora_ota_participant_versions',return_value={}))
                stack.enter_context(mock.patch.object(ota,'prepare_ota_hop_settings',return_value=[]))
                stack.enter_context(mock.patch.object(ota,'query_target',return_value=fixtures.target()))
                stack.enter_context(mock.patch.object(ota,'prepare_package',return_value=(Path('release.mota'),package,None)))
                stack.enter_context(mock.patch.object(ota,'arm_source_temp_radio_once',return_value=True))
                stack.enter_context(mock.patch.object(ota,'shorten_source_temp_window',return_value=True))
                stack.enter_context(mock.patch.object(ota,'source_cli_command',return_value='OK'))
                stack.enter_context(mock.patch.object(ota,'SeederProcess',return_value=seeder))
                stack.enter_context(mock.patch.object(ota,'monitor_download',side_effect=ota.OtaError('synthetic transfer failure')))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(contextlib.redirect_stderr(error))
                result=ota.main(argv,controller_override=controller)
            saved=json.loads((work/ota.TARGET_TEMP_RECOVERY_FILE).read_text())
        self.assertEqual(result,2)
        self.assertEqual([c for c in calls if c.startswith('tempradio ')],['tempradio 909.5,500,5,5,1'])
        self.assertTrue(saved['cleanup_required']);self.assertTrue(saved['shorten_attempted'])
        self.assertFalse(saved['shorten_acknowledged']);self.assertFalse(saved['normal_return_verified'])
        self.assertNotIn('ota self',calls)
        self.assertIn('restoring the controller does not prove the destination returned',error.getvalue())

if __name__=='__main__':unittest.main()
