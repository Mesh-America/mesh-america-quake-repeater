"""Validate speech-generation plans, fixed audio identity, and fixture encoding."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_button_voice_generator import parse_header, write_wav

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
BASELINE_FILTER = (
    "highpass=f=350,lowpass=f=3400,"
    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
    "volume=1.4,alimiter=limit=0.8:level=disabled,apad=pad_dur=0.05"
)
SELECTED_FILTER = (
    "highpass=f=350,lowpass=f=3400,"
    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
    "acompressor=threshold=0.08:ratio=6:attack=5:release=70:makeup=4:knee=4:detection=rms,"
    "volume=1.4,aresample=8000,alimiter=limit=0.12:level=disabled,apad=pad_dur=0.05"
)

# Independently pinned from approved Zira WAVs (rate -1 / compressed / peak
# 0.12 / 8 kHz), not from the header being tested or its voice-name metadata.
ZIRA_GPS_RECORDINGS = {
    'gpsOn': ('8bb2571a94245c9df307857a072f5e8900e72976c81536dc02c25251da42ca7a', 9683),
    'gpsOff': ('4dd8519110914aba97d84d2d1b72a20dec8bb8ed573aa167551d8e092af8ffcb', 9237),
}


class AssetTests(unittest.TestCase):
    def test_production_gps_recordings_are_the_approved_zira_audio_and_metadata(self):
        source = (ROOT / 'src/helpers/ui/GpsVoiceData.h').read_text(encoding='utf-8')
        self.assertEqual([line for line in source.splitlines() if line.startswith('// Voice:')],
                         ['// Voice: Microsoft Zira Desktop'])
        arrays, clips = parse_header(source)
        self.assertEqual(tuple(arrays), tuple(ZIRA_GPS_RECORDINGS))
        self.assertEqual(tuple(clips), tuple(ZIRA_GPS_RECORDINGS))
        for name, (fingerprint, samples) in ZIRA_GPS_RECORDINGS.items():
            with self.subTest(recording=name):
                self.assertEqual(hashlib.sha256(arrays[name]).hexdigest(), fingerprint)
                self.assertEqual(clips[name], (name, name, samples, 8000))

    def test_optional_voice_metadata_preserves_generic_pcm_fixture_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            on, off = directory / 'on.wav', directory / 'off.wav'
            write_wav(on, [0, 0, 1, -1, 2, -2, 3, -3, 1000])
            write_wav(off, [0, 1, -1, 2, -2, 3, -3, -1000])
            outputs = []
            for arguments in ((), ('--voice', 'Microsoft Zira Desktop')):
                target = directory / ('selected.h' if arguments else 'plain.h')
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/generate_gps_voice.py'),
                     '--on', str(on), '--off', str(off), '--output', str(target), *arguments],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(target.read_text(encoding='utf-8'))
            self.assertNotIn('// Voice:', outputs[0])
            self.assertIn('// Voice: Microsoft Zira Desktop\n', outputs[1])
            self.assertEqual(parse_header(outputs[0]), parse_header(outputs[1]))

    def test_powershell_forwards_selected_voice_to_encoder_metadata(self):
        source = (ROOT / 'scripts/generate_gps_voice.ps1').read_text(encoding='utf-8')
        invocation = next(line for line in source.splitlines()
                          if line.startswith('& python $gpsEncoder '))
        self.assertIn('--voice $Voice', invocation)


@unittest.skipUnless(POWERSHELL, "PowerShell is needed for generator plan tests")
class Tests(unittest.TestCase):
    def plan(self, *arguments):
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "scripts/generate_gps_voice.ps1"),
             *arguments, "-WhatIf", "-Verbose"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )

    def test_selected_defaults_and_original_profile(self):
        result = self.plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(SELECTED_FILTER, result.stdout)
        self.assertIn("Microsoft Zira Desktop; rate: -1", result.stdout)
        self.assertIn(str(ROOT / "src/helpers/ui/GpsVoiceData.h"), result.stdout)
        result = self.plan(
            "-Voice", "Microsoft Zira Desktop", "-Compress:$false", "-PeakLimit", "0.8",
            "-OutputHeader", "out/gps-voice/original-zira.h",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(BASELINE_FILTER, result.stdout)
        self.assertIn("Microsoft Zira Desktop; rate: -1", result.stdout)
        self.assertNotIn("acompressor=", result.stdout)

    def test_compressed_variant_is_planned_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "preview"
            header = Path(temporary) / "headers/mark.h"
            result = self.plan(
                "-Voice", "Microsoft Mark", "-Rate", "0", "-Compress",
                "-PeakLimit", "0.10", "-OutputDirectory", str(directory),
                "-OutputHeader", str(header),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Microsoft Mark; rate: 0", result.stdout)
            self.assertIn("acompressor=threshold=0.08:ratio=6", result.stdout)
            self.assertIn("makeup=4:knee=4:detection=rms", result.stdout)
            self.assertIn("aresample=8000,alimiter=limit=0.1:level=disabled", result.stdout)
            self.assertIn(str(header), result.stdout)
            self.assertFalse(directory.exists())
            self.assertFalse(header.parent.exists())

    def test_variants_require_an_explicit_header(self):
        for arguments in (("-Compress:$false",), ("-Voice", "Microsoft Mark"),
                          ("-Rate", "0"), ("-PeakLimit", "0.10")):
            with self.subTest(arguments=arguments):
                result = self.plan(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("explicit -OutputHeader", result.stderr)

    def test_invalid_header_extension_is_rejected(self):
        result = self.plan("-OutputHeader", "out/gps-voice/test.wav")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name a .h file", result.stderr)

    def test_file_directory_collisions_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            file = path / "existing-file"
            file.touch()
            result = self.plan("-OutputDirectory", str(file))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("names an existing file", result.stderr)
            directory = path / "existing-directory.h"
            directory.mkdir()
            result = self.plan("-OutputHeader", str(directory))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("names an existing directory", result.stderr)

    def test_rate_and_peak_ranges_are_rejected(self):
        for arguments in (("-Rate", "11"), ("-Rate", "-11"),
                          ("-PeakLimit", "0.01"), ("-PeakLimit", "1.1")):
            with self.subTest(arguments=arguments):
                result = self.plan("-OutputHeader", "out/gps-voice/test.h", *arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(arguments[0][1:], result.stderr)


if __name__ == "__main__":
    unittest.main()
