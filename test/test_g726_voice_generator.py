"""Validate the experimental G.726 catalog without FFmpeg or speech synthesis."""
from pathlib import Path
import hashlib
import io
import importlib.util
import re
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from test_button_voice_generator import CATALOG, ZIRA_RECORDINGS
from test_gps_voice_generator import ZIRA_GPS_RECORDINGS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'scripts/generate_g726_voice.py'
sys.path.insert(0,str(ROOT/'scripts'))
try:
    spec=importlib.util.spec_from_file_location('g726_generator_under_test',SCRIPT)
    generator=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
finally:
    sys.path.remove(str(ROOT/'scripts'))

# Independent FFmpeg reference payloads from approved Zira WAVs; fixed here
# rather than inferred from the generated header being tested. Tuple order is
# 16 kbps then 24 kbps, always raw MSB-first g726, not g726le.
GOLDENS = {
    'actionFailed': ('33663298be60ec0e2add5ebde561e69e503f222a0ab8c37323498eb1d1714365', '7e5e12f8372c473055bd07e169b3438c6f816dd68f0cd1b3ef09048f6fe51afc'),
    'advertFailed': ('135d7e4ca80bcc34c02f51d72220aa17f4fc75f0d23fdac3f7eb46c53b2ecdc1', '92ce6a28b2daca7754f2b845320da0520fab447fdff46ac89ff59d283b5f28a6'),
    'advertQueued': ('6f0820ccb7823100f9ad0987f45c82db1b80eb2ab3cbefdd5ebff223e59bf94b', '776a6c07f48cae3f9038f811585d1d99da35f2c203333556ad4dd9b72b9e30da'),
    'alertsSilent': ('3392d2847dfcbdc8a3851653a777e32eedbd748b0588fbb1e8af8bbc75f78516', 'f01749532c1edba71079594f58dca6888cc37b9ac3cb9ec9ec12ffd813834a69'),
    'alertsSoundOnly': ('1488c87772a6868b621eed3144ec46e2bda551265919cd5dd881f2640628096a', '801e8c93c52d6b219557aaff305ccdbd3c59caa5dc4bce4a1f41cc90c08b5da9'),
    'alertsSoundVibration': ('90506e3b6d2626021f34c93337bb4460b77360547dbd51b821c24b23e84c2634', '4255e55a8e6be96ac8da1e8b36476896f758b27db3f88bef045f0af180f7edf8'),
    'alertsVibrationOnly': ('b4e62f14ddb4c1f6783018feeae3a732bd97e73275659d4106b4ad4eca83ac70', '9ea16e3f209a544d86bab44bc36bb811d79630134fa1ccc455a68ff06edde980'),
    'notificationCleared': ('734d1eaa542201c3138962647672f076a317bef044bf25ead2c4648797ed6550', '867ef876f2804b8d2767afddd9f7d922c129e6f47dfbe08d4ed5966ae6d3d24b'),
    'ready': ('2a266c9f56176376eb2322a2b72e4df868a35926f4b520e13acf337e792534e3', '8eaa38100aa5a482ad72504ce40995979de45843794ffd198b2d1685089e17be'),
    'restarting': ('9c204820af9bb40de30edac13bea43249884ba82753b9f6706b311abd9a93786', '2a6f1c6fcbaa26a12c9381f5ace6c7cda68f89ed7651dc506fff27d8a41aeae6'),
    'shuttingDown': ('cef5b599fa81aef97459becae5e2b8e85287f153a7b5d6c5467959ee8facc130', '11fde2f8561194d823252cf957f044dc24900ebdb0debb0dae83d043b81ee627'),
    'soundOff': ('20a8242182bead0359ea4920c99963ce324285a4e1d28bfcb3d8324d10d7e8c4', 'ccbf34a368af7d89892c96b8b8b59361e7671e717354d41c3c365c011a5a1261'),
    'soundOn': ('e346e20ea7e69b5f40f39235d57d9e5805353a4a7abbf52800f46a9670d25fd1', '4a5f531ce35dafdd1c7735bb3d67018bae73c724cce1bf8fc0dba10a15b4d201'),
    'usbSetup': ('fe99f1b81aff17db4afd6c1b9f21e70a78e983bdf1b61de99bb5ff90f01cda75', 'a714e239ebc3c2c373f246a627334db974b6d197e096e1025d10748e01f40498'),
    'gpsOff': ('2d85181600ccd769a2be90393244cbd31ca8bdc3f0a919c8f24be6ed6b1792e2', 'c7ca2f32062ce0f16531d1e11c42faba2e3486b609a96c5160d0ab7d87917587'),
    'gpsOn': ('8d198c025d6bc123e59d890a718835f27c75bf404f5c5288bbf08780e514aff0', 'fc44dccf32f0fb94a4d3b8b4b114eea19c5210e515d3b300fce847e5fc788b4a'),
}


class EncodeTests(unittest.TestCase):
    def test_encoder_uses_exact_msb_first_ffmpeg_command_pcm_and_ceil_length(self):
        for bitrate in (16,24):
            for samples in ([0,-1,1], [32767,-32768,0,127,-128,1024,-1024,7,-7]):
                with self.subTest(bitrate=bitrate,samples=len(samples)):
                    size=(len(samples)*(bitrate//8)+7)//8
                    payload=bytes(range(size))
                    with mock.patch.object(generator.subprocess,'run',
                                           return_value=SimpleNamespace(stdout=payload)) as run:
                        self.assertEqual(generator.encode(samples,bitrate,'chosen-ffmpeg'),payload)
                    self.assertEqual(run.call_args.args[0],[
                        'chosen-ffmpeg','-hide_banner','-loglevel','error','-f','s16le',
                        '-ar','8000','-ac','1','-i','pipe:0','-c:a','g726',
                        '-b:a',str(bitrate*1000),'-f','g726','pipe:1'])
                    self.assertEqual(run.call_args.kwargs['input'],
                                     struct.pack('<'+'h'*len(samples),*samples))
                    self.assertTrue(run.call_args.kwargs['check'])
                    self.assertEqual(run.call_args.kwargs['stdout'],subprocess.PIPE)
                    self.assertEqual(run.call_args.kwargs['stderr'],subprocess.PIPE)

    def test_bad_bitrates_are_rejected_before_spawning_ffmpeg(self):
        for bitrate in (-1,0,8,32,40,None,'16'):
            with self.subTest(bitrate=bitrate), mock.patch.object(generator.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'bitrate must be 16 or 24'):
                    generator.encode([0,1,-1],bitrate)
                run.assert_not_called()

    def test_short_long_ffmpeg_output_and_failed_process_are_rejected(self):
        for bitrate in (16,24):
            expected=(5*(bitrate//8)+7)//8
            for length in (expected-1,expected+1):
                with self.subTest(bitrate=bitrate,length=length):
                    with mock.patch.object(generator.subprocess,'run',
                                           return_value=SimpleNamespace(stdout=bytes(length))):
                        with self.assertRaisesRegex(ValueError,f'expected {expected} bytes, got {length}'):
                            generator.encode([0]*5,bitrate)
        with mock.patch.object(generator.subprocess,'run',
                               side_effect=subprocess.CalledProcessError(1,['ffmpeg'])):
            with self.assertRaises(subprocess.CalledProcessError):generator.encode([0],16)


class CatalogTests(unittest.TestCase):
    def test_mock_generation_emits_both_bitrate_catalogs_and_exact_source_lengths(self):
        names=tuple(name for name,_ in CATALOG)+('gpsOn','gpsOff')
        source_samples={name:[index]*((index+1)*3) for index,name in enumerate(names)}
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);output=directory/'generated.h'
            arguments=self.argv(directory,output,'Microsoft Zira Desktop')
            def read(path):
                name={'missing-on.wav':'gpsOn','missing-off.wav':'gpsOff'}.get(path.name,path.stem)
                return source_samples[name]
            def encode(samples,bitrate,ffmpeg):
                self.assertEqual(ffmpeg,'ffmpeg')
                return bytes([bitrate])*((len(samples)*(bitrate//8)+7)//8)
            with mock.patch.object(sys,'argv',arguments), mock.patch.object(generator,'read',side_effect=read), \
                    mock.patch.object(generator,'encode',side_effect=encode) as encoder, \
                    mock.patch.object(sys,'stdout',io.StringIO()):
                generator.main()
            self.assertEqual(encoder.call_count,32)
            source=output.read_text(encoding='utf-8')
            for bitrate in (16,24):
                body=source.split(f'#if MESH_GPS_VOICE_G726_BITRATE == {bitrate}\n',1)[1]
                body=body.split(f'#endif // {bitrate} kbps',1)[0]
                for name in names:
                    count=len(source_samples[name])
                    self.assertIn(f'{name}Data, sizeof({name}Data), {count}, 8000, VoiceCodec::G726{bitrate}',body)
                self.assertEqual(body.count('#ifdef HAS_DRV2605'),4)
                self.assertEqual(body.count('#endif // HAS_DRV2605'),4)

    def test_invalid_source_lengths_preserve_existing_experimental_header(self):
        for count in (0,32001):
            with self.subTest(samples=count), tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary);output=directory/'generated.h'
                output.write_bytes(b'existing experiment\n')
                def read(path):return [0]*count if path.name=='missing-off.wav' else [0,1,-1]
                with mock.patch.object(sys,'argv',self.argv(directory,output,'Microsoft Zira Desktop')), \
                        mock.patch.object(generator,'read',side_effect=read), \
                        mock.patch.object(generator,'encode') as encoder:
                    with self.assertRaisesRegex(ValueError,'nonempty clip under four seconds'):
                        generator.main()
                encoder.assert_not_called()
                self.assertEqual(output.read_bytes(),b'existing experiment\n')

    def test_generated_16_and_24_catalogs_match_independent_zira_reference_hashes_and_lengths(self):
        source=(ROOT/'src/helpers/ui/G726VoiceData.h').read_text(encoding='utf-8')
        self.assertIn('// Voice: Microsoft Zira Desktop. 8 kHz mono, MSB-first raw G.726',source)
        self.assertIn('EXPERIMENT ONLY',source)
        self.assertIn('#if !defined(MESH_GPS_VOICE_G726_BITRATE)',source)
        names=tuple(name for name,_ in CATALOG)+('gpsOn','gpsOff')
        samples={name:value[1] for name,value in {**ZIRA_RECORDINGS,**ZIRA_GPS_RECORDINGS}.items()}
        self.assertEqual(set(names),set(GOLDENS))
        for index,bitrate in enumerate((16,24)):
            with self.subTest(bitrate=bitrate):
                body=source.split(f'#if MESH_GPS_VOICE_G726_BITRATE == {bitrate}\n',1)[1]
                body=body.split(f'#endif // {bitrate} kbps',1)[0]
                arrays={name:bytes(int(value,16) for value in re.findall(r'0x([0-9a-fA-F]{2})',data))
                        for name,data in re.findall(r'static const uint8_t (\w+)Data\[\] = \{(.*?)\};',body,re.S)}
                clips={name:(data,size,int(count),int(rate),int(codec))
                       for name,data,size,count,rate,codec in re.findall(
                           r'static constexpr VoiceClip (\w+)Clip = \{\s*'
                           r'(\w+)Data, sizeof\((\w+)Data\), (\d+), (\d+), VoiceCodec::G726(\d+)\s*\};',body)}
                self.assertEqual(tuple(arrays),names)
                self.assertEqual(tuple(clips),names)
                for name in names:
                    self.assertEqual(clips[name],(name,name,samples[name],8000,bitrate))
                    self.assertEqual(len(arrays[name]),(samples[name]*(bitrate//8)+7)//8)
                    self.assertEqual(hashlib.sha256(arrays[name]).hexdigest(),GOLDENS[name][index],name)
                # Each optional mode must be inside a HAS_DRV2605 guard; the
                # common twelve clips must remain outside those guards.
                guarded=False
                for line in body.splitlines():
                    if line=='#ifdef HAS_DRV2605':
                        self.assertFalse(guarded);guarded=True
                    elif line=='#endif // HAS_DRV2605':
                        self.assertTrue(guarded);guarded=False
                    else:
                        match=re.match(r'static const uint8_t (\w+)Data',line)
                        if match:self.assertEqual(guarded,match[1].startswith('alerts'),match[1])
                self.assertFalse(guarded)

    def test_cli_refuses_production_filenames_and_invalid_voice_without_touching_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            for name in ('ButtonVoiceData.h','GpsVoiceData.h','buttonvoicedata.h','GPSVOICEDATA.H'):
                with self.subTest(name=name):
                    target=directory/name;target.write_bytes(b'existing selected IMA audio\n')
                    result=self.cli(directory,target,'Microsoft Zira Desktop')
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('must not overwrite production IMA headers',result.stderr)
                    self.assertEqual(target.read_bytes(),b'existing selected IMA audio\n')
            for voice in ('','   ','name\nsecondline','name\rsecondline'):
                with self.subTest(voice=voice):
                    target=directory/'experimental.h';target.write_bytes(b'existing experiment\n')
                    result=self.cli(directory,target,voice)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('nonempty single-line label',result.stderr)
                    self.assertEqual(target.read_bytes(),b'existing experiment\n')

    def cli(self,directory,output,voice):
        return subprocess.run([sys.executable,*self.argv(directory,output,voice)],
                              capture_output=True,text=True,timeout=30)

    def argv(self,directory,output,voice):
        return [str(SCRIPT),'--directory',str(directory/'missing-catalog'),
                '--on',str(directory/'missing-on.wav'),'--off',str(directory/'missing-off.wav'),
                '--output',str(output),'--voice',voice]


if __name__=='__main__':unittest.main()
