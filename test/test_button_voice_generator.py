"""Validate the fixed prerecorded catalog without speech synthesis or hardware."""
from pathlib import Path
import hashlib
import importlib.util
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
ENCODER = ROOT / "scripts/generate_button_voice.py"
SYNTHESIZER = ROOT / "scripts/generate_button_voice.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
CATALOG = (
    ("ready", "Ready"),
    ("notificationCleared", "Notification cleared"),
    ("advertQueued", "Advert queued"),
    ("advertFailed", "Advert failed"),
    ("soundOn", "Sound on"),
    ("soundOff", "Sound off"),
    ("actionFailed", "Action failed"),
    ("usbSetup", "USB setup"),
    ("shuttingDown", "Shutting down"),
    ("restarting", "Restarting"),
    ("alertsSoundVibration", "Sound and vibration"),
    ("alertsSoundOnly", "Sound only"),
    ("alertsVibrationOnly", "Vibration only"),
    ("alertsSilent", "Silent"),
)

# Approved Microsoft Zira Desktop, rate -1 / compressed / peak-0.12 / 8 kHz.
# Fingerprints were derived from the freshly synthesized WAVs, then checked
# against the selected header. They must not be computed from that header at
# test runtime: a Zira default/label does not establish the recordings' identity.
ZIRA_RECORDINGS = {
    'ready': ('1b7823a41160abedaebb87d185a60c53bd11aba167797210c1dc37486e7c2fe0', 3147),
    'notificationCleared': ('86ef9cdaaeee5e56254fef71512fe0de11119f732b2ab3125d2efda1c6dd538d', 10984),
    'advertQueued': ('93db629d81e9d029a46f49df068dc0d8b8182687b348ec6123b43b8910ab2abb', 7062),
    'advertFailed': ('2465649d7259fed3283915e5e56d23ae9f43772f10a419a84d654ab0360c778e', 7429),
    'soundOn': ('a644478dbe1ef01d126de862b2153b077b468acaa4e452dd26b12ec4878faf1e', 6229),
    'soundOff': ('43565c13fab68fa5e0ca20c55a7213e10109e6289e4fa35dc7396acdda905f78', 5393),
    'actionFailed': ('971c92c5150931ffe63504573996ee931d77d77c2a888dfe35f8ba389a8c32d8', 7470),
    'usbSetup': ('f42ae082f7eab15bc7e2bd7b25f1ed50c6ed264099e5b7814897828d5b8ef051', 8957),
    'shuttingDown': ('973104cd1e48c6f584ec1e9eb3169bfa78bedc9399dbede88e364ef5571c91bb', 7461),
    'restarting': ('49425018482bdee20b8140cd2c33419778b591ba93e0d1137f06a0ab18a3f035', 5866),
    'alertsSoundVibration': ('8fedaa6d711c8623f67719214bc4d040ad43ad17736bcac82a516b8fc9c5aa93', 10915),
    'alertsSoundOnly': ('6f5d4f043d53c9ff40537a13df600f7c0c71abb462ddc97f357fceda8e5fd565', 7108),
    'alertsVibrationOnly': ('bd2e5d34d79655c721774db8a6e76aaf26c54b8e075fea3ddd21a427ac6f3f2e', 8723),
    'alertsSilent': ('fcdef5047e616f6454aae42c90bb238303654b04e21fc9e5378693d91233e2a8', 5717),
}


def write_wav(path, samples, *, rate=8000, channels=1, width=2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        values = samples * channels
        payload = (struct.pack("<" + "h" * len(values), *values)
                   if width == 2 else bytes(len(values)))
        wav.writeframes(payload)


def select_vibration(source, enabled=True):
    """Select the generated catalog's HAS_DRV2605 branches for asset tests."""
    lines = []
    stack = [True]
    for line in source.splitlines():
        if line == '#ifdef HAS_DRV2605':
            stack.append(stack[-1] and enabled)
        elif line == '#else' and len(stack) > 1:
            stack[-1] = stack[-2] and not stack[-1]
        elif line == '#endif // HAS_DRV2605':
            stack.pop()
        elif stack[-1]:
            lines.append(line)
    assert len(stack) == 1
    return '\n'.join(lines)


def parse_header(source, has_drv2605=True):
    source = select_vibration(source, has_drv2605)
    spans = {
        name: bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", body))
        for name, body in re.findall(
            r"static const uint8_t (\w+)Data\[\] = \{(.*?)\};", source, re.S)
    }
    arrays, clips = {}, {}
    for name, data, size, samples, rate, prefix, prefix_size in re.findall(
            r"static constexpr VoiceClip (\w+)Clip = \{\s*"
            r"(\w+)Data, sizeof\((\w+)Data\), (\d+), (\d+)"
            r"(?:, (\w+)Data, sizeof\((\w+)Data\))?\s*\};", source):
        assert data == size and prefix == prefix_size
        clips[name] = (data, size, int(samples), int(rate))
        arrays[name] = (spans[prefix] if prefix else b'') + spans[data]
    return arrays, clips


class EncoderTests(unittest.TestCase):
    def test_profitable_prefix_groups_regenerate_exact_phrases_for_both_board_policies(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            samples = self.fixtures(directory)
            common = [((i*997)%18001)-9000 for i in range(257)]
            for name, tail in (('advertQueued',[1000,-1000]), ('advertFailed',[-3000,3000]),
                               ('soundOff',[2000,-2000]), ('alertsSoundOnly',[-4000,4000])):
                samples[name] = common+tail*80
                write_wav(directory/(name+'.wav'), samples[name])
            source = directory/'shared.h'
            self.assertEqual(self.generate(directory,source).returncode,0)
            header = source.read_text()
            self.assertIn('advertPrefixData',header)
            self.assertIn('soundPrefixData',header)
            # Compare to the original independently encoded fixture bytes.
            spec = importlib.util.spec_from_file_location(
                'fixture_gps_encoder',ROOT/'scripts/generate_gps_voice.py')
            encoder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(encoder)
            for vibration in (False,True):
                arrays, clips = parse_header(header,vibration)
                names = CATALOG if vibration else CATALOG[:10]
                for name,_ in names:
                    self.assertEqual(arrays[name],encoder.encode(samples[name]))
                    self.assertEqual(clips[name],(name,name,len(samples[name]),8000))
                self.assertEqual('soundPrefixData' in select_vibration(header,vibration),vibration)

    def fixtures(self, directory):
        samples = {}
        for index, (name, _) in enumerate(CATALOG):
            # This known prefix encodes to 00 91 a1 b3 from predictor/index 0.
            # Odd and even lengths exercise the padded final nibble separately.
            values = [0, 0, 1, -1, 2, -2, 3, -3]
            values += [((offset * 997 + index * 1733) % 20001) - 10000
                       for offset in range(9 + index * 7)]
            write_wav(directory / (name + ".wav"), values)
            samples[name] = values
        return samples

    def generate(self, directory, output, *arguments):
        return subprocess.run(
            [sys.executable, str(ENCODER), "--directory", str(directory),
             "--output", str(output), *arguments], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )

    def test_fixed_catalog_sizes_independent_streams_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            samples = self.fixtures(directory)
            first, second = directory / "first.h", directory / "second.h"
            result = self.generate(directory, first)
            self.assertEqual(result.returncode, 0, result.stderr)
            repeated = self.generate(directory, second)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(result.stdout, repeated.stdout)
            source = first.read_text(encoding="utf-8")
            self.assertNotIn('// Voice:', source)
            self.assert_x1_only_recordings_are_guarded(source)
            arrays, clips = parse_header(source)
            self.assertEqual(tuple(arrays), tuple(name for name, _ in CATALOG))
            self.assertEqual(tuple(clips), tuple(arrays))
            for name, phrase in CATALOG:
                with self.subTest(phrase=phrase):
                    count = len(samples[name])
                    self.assertEqual(clips[name], (name, name, count, 8000))
                    self.assertEqual(len(arrays[name]), (count + 1) // 2)
                    self.assertEqual(arrays[name][:4], bytes.fromhex("00 91 a1 b3"))
                    if count & 1:
                        self.assertEqual(arrays[name][-1] >> 4, 0)
                    self.assertIn('// "' + phrase + '"', source)
                    self.assertIn(f"{phrase}: {count / 8000:.3f}s", result.stdout)
            self.assertIn(
                f"Button confirmations: {sum(len(data) for data in arrays.values())} audio bytes",
                result.stdout,
            )

    def test_checked_in_assets_match_fixed_catalog_and_clip_bounds(self):
        source = (ROOT / "src/helpers/ui/ButtonVoiceData.h").read_text(encoding="utf-8")
        self.assert_x1_only_recordings_are_guarded(source)
        arrays, clips = parse_header(source)
        self.assertEqual(tuple(arrays), tuple(name for name, _ in CATALOG))
        self.assertEqual(tuple(clips), tuple(arrays))
        for name, phrase in CATALOG:
            with self.subTest(phrase=phrase):
                data_name, size_name, count, rate = clips[name]
                self.assertEqual((data_name, size_name, rate), (name, name, 8000))
                self.assertGreater(count, 0)
                self.assertLessEqual(count, 32000)
                self.assertEqual(len(arrays[name]), (count + 1) // 2)
                self.assertTrue(any(arrays[name]))
                if count & 1:
                    self.assertEqual(arrays[name][-1] >> 4, 0)
                self.assertIn('// "' + phrase + '"', source)

    def test_optional_voice_metadata_does_not_change_encoded_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixtures(directory)
            plain, selected = directory / 'plain.h', directory / 'zira.h'
            baseline = self.generate(directory, plain)
            voiced = self.generate(directory, selected, '--voice', 'Microsoft Zira Desktop')
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertEqual(voiced.returncode, 0, voiced.stderr)
            source = selected.read_text(encoding='utf-8')
            self.assertIn('// Voice: Microsoft Zira Desktop\n', source)
            self.assertEqual(parse_header(source), parse_header(plain.read_text(encoding='utf-8')))

    def test_selected_production_recordings_are_the_approved_zira_catalog_not_just_zira_labels(self):
        source = (ROOT / 'src/helpers/ui/ButtonVoiceData.h').read_text(encoding='utf-8')
        self.assertEqual([line for line in source.splitlines() if line.startswith('// Voice:')],
                         ['// Voice: Microsoft Zira Desktop'])
        arrays, clips = parse_header(source)
        self.assertEqual(tuple(arrays), tuple(ZIRA_RECORDINGS))
        self.assertEqual(tuple(clips), tuple(ZIRA_RECORDINGS))
        for name, (fingerprint, samples) in ZIRA_RECORDINGS.items():
            with self.subTest(recording=name):
                self.assertEqual(hashlib.sha256(arrays[name]).hexdigest(), fingerprint)
                self.assertEqual(clips[name], (name, name, samples, 8000))

    def assert_x1_only_recordings_are_guarded(self, source):
        arrays, clips = parse_header(source, has_drv2605=False)
        self.assertEqual(tuple(arrays), tuple(name for name, _ in CATALOG[:10]))
        self.assertEqual(tuple(clips), tuple(arrays))
        # The optional shared Sound prefix must not add storage on boards
        # which have no sound-only alert-mode announcement.
        self.assertNotIn('soundPrefixData', select_vibration(source, False))

    def test_changed_source_wav_replaces_only_its_matching_clip(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixtures(directory)
            output = directory / "selected.h"
            result = self.generate(directory, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            previous, previous_clips = parse_header(output.read_text(encoding="utf-8"))
            write_wav(directory / "ready.wav", [1000, -1000] * 16)
            result = self.generate(directory, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            current, current_clips = parse_header(output.read_text(encoding="utf-8"))
            self.assertNotEqual(current["ready"], previous["ready"])
            self.assertEqual(current_clips["ready"], ("ready", "ready", 32, 8000))
            for name, _ in CATALOG[1:]:
                self.assertEqual(current[name], previous[name])
                self.assertEqual(current_clips[name], previous_clips[name])

    def test_empty_and_overlong_clips_do_not_replace_existing_header(self):
        for count in (0, 32001):
            with self.subTest(samples=count), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.fixtures(directory)
                # A late failure must not leave a partially regenerated catalog.
                write_wav(directory / (CATALOG[-1][0] + ".wav"), [0] * count)
                output = directory / "selected.h"
                output.write_bytes(b"existing selected header\n")
                result = self.generate(directory, output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("nonempty clip under four seconds", result.stderr)
                self.assertEqual(output.read_bytes(), b"existing selected header\n")

    def test_four_second_boundary_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixtures(directory)
            write_wav(directory / "restarting.wav", [0] * 32000)
            output = directory / "boundary.h"
            result = self.generate(directory, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            arrays, clips = parse_header(output.read_text(encoding="utf-8"))
            self.assertEqual(len(arrays["restarting"]), 16000)
            self.assertEqual(clips["restarting"][2:], (32000, 8000))

    def test_wrong_wav_formats_and_missing_catalog_clip_preserve_header(self):
        for format_options in ({"rate": 16000}, {"channels": 2}, {"width": 1}, None):
            with self.subTest(format=format_options), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.fixtures(directory)
                wav = directory / "restarting.wav"
                if format_options is None:
                    wav.unlink()
                else:
                    write_wav(wav, [0] * 32, **format_options)
                output = directory / "selected.h"
                output.write_bytes(b"selected header\n")
                result = self.generate(directory, output)
                self.assertNotEqual(result.returncode, 0)
                if format_options is not None:
                    self.assertIn("Expected mono 16-bit PCM at 8000 Hz", result.stderr)
                self.assertEqual(output.read_bytes(), b"selected header\n")

    def test_powershell_and_encoder_have_the_same_fixed_phrase_catalog(self):
        source = SYNTHESIZER.read_text(encoding="utf-8")
        body = source.split("$buttonPhrases = [ordered]@{", 1)[1].split("}", 1)[0]
        self.assertEqual(tuple(re.findall(r"(\w+) = '([^']+)'", body)), CATALOG)
        self.assertIn("[string]$Voice = 'Microsoft Zira Desktop'", source)
        self.assertIn("$buttonVoice.SelectVoice($Voice)", source)
        invocation = next(line for line in source.splitlines()
                          if line.startswith('& python $buttonEncoder '))
        self.assertIn('--voice $Voice', invocation)
        self.assertIn("$buttonVoices -notcontains $Voice", source)
        self.assertIn("$buttonVoice.Rate = -1", source)
        self.assertIn("acompressor=threshold=0.08:ratio=6", source)
        self.assertIn("aresample=8000,alimiter=limit=0.12:level=disabled", source)


@unittest.skipUnless(POWERSHELL, "PowerShell is needed for synthesis plan tests")
class PlanTests(unittest.TestCase):
    def plan(self, directory=None, header=None, *arguments):
        targets = []
        if directory is not None:
            targets += ["-OutputDirectory", str(directory)]
        if header is not None:
            targets += ["-OutputHeader", str(header)]
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(SYNTHESIZER),
             *targets, *arguments, "-WhatIf", "-Verbose"], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )

    def test_defaults_keep_zira_and_the_selected_production_header(self):
        result = self.plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Synthesize and encode Microsoft Zira Desktop button confirmations", result.stdout)
        self.assertIn(str(ROOT / "src/helpers/ui/ButtonVoiceData.h"), result.stdout)

    def test_whatif_creates_neither_audio_directory_nor_header_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "audio"
            header = Path(temporary) / "headers" / "button.h"
            result = self.plan(directory, header)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Synthesize and encode Microsoft Zira Desktop button confirmations", result.stdout)
            self.assertIn(str(header), result.stdout)
            self.assertFalse(directory.exists())
            self.assertFalse(header.parent.exists())

    def test_whatif_does_not_overwrite_existing_header(self):
        for voice in ("Microsoft Mark", "Microsoft Zira Desktop"):
            with self.subTest(voice=voice), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "audio"
                header = Path(temporary) / "button.h"
                header.write_bytes(b"selected prerecorded catalog\n")
                result = self.plan(directory, header, "-Voice", voice)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Synthesize and encode {voice} button confirmations", result.stdout)
                self.assertEqual(header.read_bytes(), b"selected prerecorded catalog\n")
                self.assertFalse(directory.exists())

    def test_onlymissing_whatif_preserves_existing_recordings_and_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            header = directory / "selected.h"
            recording = directory / "soundOff.wav"
            header.write_bytes(b"selected prerecorded catalog\n")
            write_wav(recording, [0, 1, -1, 2, -2])
            original = recording.read_bytes()
            result = self.plan(directory, header, "-OnlyMissing")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(recording.read_bytes(), original)
            self.assertEqual(header.read_bytes(), b"selected prerecorded catalog\n")
            self.assertFalse((directory / "alertsSilent.wav").exists())

    def test_mark_variant_with_explicit_header_plans_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "mark"
            header = Path(temporary) / "headers" / "mark.h"
            result = self.plan(directory, header, "-Voice", "Microsoft Mark")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Synthesize and encode Microsoft Mark button confirmations", result.stdout)
            self.assertIn(str(header), result.stdout)
            self.assertFalse(directory.exists())
            self.assertFalse(header.parent.exists())

    def test_non_default_voice_requires_an_explicit_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "mark"
            result = self.plan(directory, None, "-Voice", "Microsoft Mark")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Voice variants require an explicit -OutputHeader", result.stderr)
            self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
