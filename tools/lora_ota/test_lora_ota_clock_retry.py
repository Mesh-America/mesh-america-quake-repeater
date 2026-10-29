"""Clock-reply loss retries whole reads without weakening schedule evidence."""

import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

import lora_ota as ota


class RemoteClockRetryTests(unittest.TestCase):
    key = 'AA' * 32

    class Clock:
        def __init__(self):
            self.now = 0.0
            self.sleeps = []

        def monotonic(self):
            return self.now

        def time(self):
            return 1000.0 + self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    @contextlib.contextmanager
    def timing(self, clock):
        with (
            mock.patch.object(ota.time, 'monotonic', side_effect=clock.monotonic),
            mock.patch.object(ota.time, 'time', side_effect=clock.time),
            mock.patch.object(ota.time, 'sleep', side_effect=clock.sleep),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            yield

    def fixture(self, replies):
        clock = self.Clock()
        controller = ota.Controller.__new__(ota.Controller)
        controller.reply_timeout = 20
        controller.clock_markers = []
        requested_epochs = []
        replies = iter(replies)

        def execute(commands, _label, timeout):
            self.assertEqual(commands[0], 'echo')
            self.assertEqual(commands[2:], ['contact_info', 'remote', 'req_clock', 'remote'])
            self.assertEqual(timeout, ota.TEMP_RADIO_PREFLIGHT_OPERATION_TIMEOUT_SECONDS)
            controller.clock_markers.append(commands[1])
            started_at = clock.time()
            reply = next(replies)
            if isinstance(reply, Exception):
                clock.now += 12
                raise reply
            duration = reply.get('duration', 3)
            clock.now += duration
            keys = reply.get('keys', [self.key])
            contact = ''.join(json.dumps(dict(adv_name='remote', public_key=key)) + '\n'
                              for key in keys)
            marker = '' if reply.get('missing_marker') else commands[1] + '\n'
            if reply.get('lost'):
                tail = json.dumps({'error': 'Getting data'}) + '\n'
            else:
                epochs = reply.get('epochs', [requested_epochs[-1] if requested_epochs else int(started_at)])
                tail = ''.join(str(epoch) + '\n' for epoch in epochs)
            return subprocess.CompletedProcess([], 0, stdout=marker + contact + tail, stderr='')

        def remote(target, command, **kwargs):
            self.assertEqual(target, 'remote')
            self.assertIs(kwargs.get('retry'), False)
            self.assertRegex(command, r'^time [0-9]+$')
            requested_epochs.append(int(command.split()[1]))
            return 'OK - clock set: 08:00 - 15/1/2027 UTC'

        controller._execute = mock.Mock(side_effect=execute)
        controller.remote_command = mock.Mock(side_effect=remote)
        return controller, clock

    def pin(self, controller):
        return ota.pin_remote_clock_forward(controller, 'remote', self.key)

    def test_initial_reply_loss_retries_with_fresh_marker_and_successful_rtt_only(self):
        controller, clock = self.fixture([{'lost': True, 'duration': 12}, {}, {}])
        with self.timing(clock), mock.patch.object(
            ota, 'require_remote_clock_within_host_policy',
            wraps=ota.require_remote_clock_within_host_policy,
        ) as policy:
            result = self.pin(controller)
        before = policy.call_args_list[0].args[0]
        self.assertEqual((before.monotonic_started_at, before.monotonic_completed_at), (14, 17))
        self.assertEqual((before.host_started_at, before.host_completed_at), (1014, 1017))
        self.assertEqual(before.round_trip_seconds, 3)
        self.assertEqual((result.monotonic_started_at, result.monotonic_completed_at), (17, 20))
        self.assertEqual(controller.remote_command.call_args.args[1], 'time 1137')
        controller.remote_command.assert_called_once()
        self.assertEqual(clock.sleeps, [2])
        self.assertEqual(len(controller.clock_markers), 3)
        self.assertEqual(len(set(controller.clock_markers)), 3)

    def test_lost_marker_and_transport_timeout_are_bounded_read_only_retries(self):
        for lost in ({'missing_marker': True}, ota.TransmissionError('read timed out')):
            with self.subTest(lost=lost):
                controller, clock = self.fixture([lost, {}, {}])
                with self.timing(clock):
                    self.pin(controller)
                controller.remote_command.assert_called_once()
                self.assertEqual(clock.sleeps, [2])
                self.assertEqual(len(set(controller.clock_markers)), 3)

    def test_multiple_epochs_are_terminal_instead_of_retryable_packet_loss(self):
        controller, clock = self.fixture([{'epochs': [1000, 1001]}])
        with self.timing(clock), self.assertRaisesRegex(ota.OtaError, '2 unambiguous') as error:
            self.pin(controller)
        self.assertNotIsInstance(error.exception, ota.TransmissionError)
        controller._execute.assert_called_once()
        controller.remote_command.assert_not_called()
        self.assertEqual(clock.sleeps, [])

    def test_missing_wrong_or_ambiguous_full_identity_never_retries(self):
        for keys in ([], ['FF' * 32], [self.key, self.key]):
            with self.subTest(keys=keys):
                controller, clock = self.fixture([{'keys': keys}])
                with self.timing(clock), self.assertRaisesRegex(ota.OtaError, 'exact contact identity'):
                    self.pin(controller)
                controller._execute.assert_called_once()
                controller.remote_command.assert_not_called()
                self.assertEqual(clock.sleeps, [])

    def test_invalid_zero_signed_and_oversized_epochs_are_not_retried(self):
        for epoch in ('0', '-1', '+1000', '4294967296', '10000000000', '9' * 5000):
            with self.subTest(length=len(epoch), prefix=epoch[:12]):
                controller, clock = self.fixture([{'epochs': [epoch]}])
                with self.timing(clock), self.assertRaisesRegex(ota.OtaError, 'invalid') as error:
                    self.pin(controller)
                self.assertNotIsInstance(error.exception, ota.TransmissionError)
                controller._execute.assert_called_once()
                controller.remote_command.assert_not_called()
                self.assertEqual(clock.sleeps, [])

    def test_initial_loss_exhaustion_has_finite_budget_and_never_writes_clock(self):
        controller, clock = self.fixture([{'lost': True}] * 4)
        with self.timing(clock), self.assertRaisesRegex(ota.TransmissionError, 'after 3 retries'):
            self.pin(controller)
        self.assertEqual(controller._execute.call_count, 4)
        controller.remote_command.assert_not_called()
        self.assertEqual(clock.sleeps, [2, 4, 8])

    def test_post_write_loss_retries_fresh_readback_without_replaying_write(self):
        controller, clock = self.fixture([{}, {'lost': True, 'duration': 12}, {}])
        with self.timing(clock):
            result = self.pin(controller)
        self.assertEqual((result.monotonic_started_at, result.monotonic_completed_at), (17, 20))
        self.assertEqual(result.round_trip_seconds, 3)
        controller.remote_command.assert_called_once()
        self.assertEqual(clock.sleeps, [2])

    def test_ambiguous_post_write_readback_is_terminal_without_replaying_write(self):
        controller, clock = self.fixture([{}, {'epochs': [1123, 1124]}])
        with self.timing(clock), self.assertRaisesRegex(ota.OtaError, '2 unambiguous') as error:
            self.pin(controller)
        self.assertNotIsInstance(error.exception, ota.TransmissionError)
        self.assertEqual(controller._execute.call_count, 2)
        controller.remote_command.assert_called_once()
        self.assertEqual(clock.sleeps, [])

    def test_post_write_loss_exhaustion_cannot_repeat_clock_mutation(self):
        controller, clock = self.fixture([{}] + [{'lost': True}] * 4)
        with self.timing(clock), self.assertRaisesRegex(ota.TransmissionError, 'after 3 retries'):
            self.pin(controller)
        self.assertEqual(controller._execute.call_count, 5)
        controller.remote_command.assert_called_once()
        self.assertEqual(clock.sleeps, [2, 4, 8])


if __name__ == '__main__':
    unittest.main()
