"""Preserve original speech PCM/DMA output while sharing encoded flash spans."""
from pathlib import Path
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import test_gps_voice_buttons as shared
from test_button_voice_generator import select_vibration

ROOT = Path(__file__).resolve().parents[1]
CC, CXX = shutil.which('gcc'), shutil.which('g++')
SANITIZERS = (['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
               '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
              if os.environ.get('MESH_VOICE_TEST_SANITIZERS') == '1' else [])

# Pinned from the original contiguous approved catalogs and the original
# decoder/player before any sharing changes. PCM is s16le; DMA words are u16le
# at gain 2. These checks include every clip, final padding, IRQ refill and
# interpolation tail, not hashes derived from the implementation under test.
ORIGINAL_OUTPUT = {
    (0, False): ('481630ba68b1a29d5148fb1b552ca9bb78477ddc576bf9bad6d124d193dc994c',
                 '7438e1cc35538956c8959adf9056aeffbd77c20e4fbd23b1204c3c17ab15a9c0'),
    (0, True): ('4e7ba541d3909bf8bbc4ae94c220f3a3d6a2304efaf53e3335a0844574475e87',
                '6b0419e83310946342b136661460eed5795fa92b23eb9da6f43056d840d0c025'),
    (16, False): ('f61a12157647ba21320ec65fb7a4bdcee260703ca593b57e5770af45076c7972',
                  'f8bdd21166fe8606622abfb8cff27136612e65e61e9f18d02e95c41e62897196'),
    (16, True): ('86e13b896a20c5c77ca9dae9d71c52a1da78f7603a8c8e260a6c6c74d51567d6',
                 '10fb34b5487048a738a75c2bd4388c4ff370cbaebb54ed3a52006738dd86f425'),
    (24, False): ('e37d6bbd0c7f9ddd0018c7f50d3929b1deef27b405a7432c492b2fb67c46e11b',
                  '2a7815a6ea01302b0cfe2d2bb3d6a57adeeec155ba70ac8aa9e1e3965d8d54be'),
    (24, True): ('59167abf199c939cc62b3b03d9dbfcffd973c495104f89de29a6dd852100cdf2',
                 '2915281db72ebe103e7599a797f0413eb7245346ba55879c4a0a9ca1f61be293'),
}


@unittest.skipUnless(CC and CXX, 'Native C/C++ compilers are required')
class Tests(unittest.TestCase):
    def test_every_original_phrase_and_full_dma_stream_remains_bit_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory/'Arduino.h').write_text(shared.ARDUINO)
            (directory/'HardwarePWM.h').write_text(shared.PWM)
            for (rate, vibration), fingerprints in ORIGINAL_OUTPUT.items():
                flags = ['-DMESH_BUTTON_AUDIO_HIL=1']
                if rate:
                    flags.append(f'-DMESH_GPS_VOICE_G726_BITRATE={rate}')
                if vibration:
                    flags.append('-DHAS_DRV2605=1')
                objects = []
                if rate:
                    obj = directory/'g726.o'
                    subprocess.run([CC, '-std=c99', '-Wall', '-Wextra', '-Werror',
                                    *SANITIZERS, *flags, '-I'+str(ROOT/'src'), '-c',
                                    str(ROOT/'src/helpers/ui/g726/g726_decoder.c'),
                                    '-o', str(obj)], check=True, timeout=30)
                    objects.append(str(obj))
                for pwm, fingerprint in enumerate(fingerprints):
                    with self.subTest(rate=rate, vibration=vibration, pwm=bool(pwm)):
                        binary = directory/'catalog'
                        subprocess.run([CXX, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                        *SANITIZERS, *flags,
                                        *(['-DPWM_OUTPUT=1'] if pwm else []),
                                        '-I'+str(directory), '-I'+str(ROOT/'src'),
                                        str(ROOT/'test/fixtures/voice_prefixes/catalog.cpp'),
                                        *objects, '-o', str(binary)], check=True, timeout=30)
                        result = subprocess.run([str(binary)], check=True,
                                                capture_output=True, timeout=30)
                        self.assertEqual(hashlib.sha256(result.stdout).hexdigest(), fingerprint)

    def test_ima_seams_odd_lengths_truncation_and_invalid_metadata(self):
        source = r'''
#include <cassert>
#include <initializer_list>
#include <limits>
#include <vector>
#include <helpers/ui/GpsVoice.h>
int main(){
 using namespace mesh::audio;
 const uint8_t encoded[]={0x77,0x1f,0xca,0x26,0x84,0x92,0xbb};
 for(unsigned samples:{1u,2u,3u,7u,13u,14u}){
   VoiceDecoder original;original.begin({encoded,sizeof(encoded),samples});
   std::vector<int16_t> expected;
   while(!original.done())expected.push_back(original.next());
   for(size_t split=0;split<sizeof(encoded);++split){
     VoiceClip clip{encoded+split,sizeof(encoded)-split,samples,8000,encoded,split};
     assert(clip.valid());VoiceDecoder decoder;decoder.begin(clip);
     for(auto value:expected){assert(!decoder.done());assert(decoder.next()==value);}
     assert(decoder.done()&&decoder.position()==samples&&decoder.next()==0);
     for(size_t tail=0;tail<sizeof(encoded)-split;++tail){
       std::vector<uint8_t> prefix(encoded,encoded+split),suffix(encoded+split,encoded+split+tail);
       VoiceClip short_clip{tail?suffix.data():encoded,tail,samples,8000,
                            split?prefix.data():nullptr,split};
       decoder.begin(short_clip);
       unsigned count=0;
       while(!decoder.done()){assert(decoder.next()==expected[count++]);}
       assert(count==((split+tail)*2<samples?(split+tail)*2:samples));
       assert(short_clip.valid()==(count==samples));
     }
   }
 }
 VoiceClip bad{encoded,sizeof(encoded),14,8000,nullptr,1};
 assert(!bad.valid());VoiceDecoder decoder;decoder.begin(bad);
 assert(decoder.done()&&decoder.next()==0);
 VoiceClip huge{encoded,std::numeric_limits<size_t>::max(),
                std::numeric_limits<uint32_t>::max(),8000,encoded,1};
 assert(huge.valid()&&huge.hasBytes(std::numeric_limits<size_t>::max()));
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path, binary = directory/'seams.cpp', directory/'seams'
            path.write_text(source)
            subprocess.run([CXX, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            *SANITIZERS, '-I'+str(ROOT/'src'), str(path), '-o', str(binary)],
                           check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_only_profitable_shared_spans_are_stored_and_optional_sound_is_gated(self):
        expected = {0: (3135, 746, 1090), 16: (1535, 268, 545), 24: (1967, 427, 817)}
        for rate, sizes in expected.items():
            if rate:
                source = (ROOT/'src/helpers/ui/G726VoiceData.h').read_text()
                source = source.split(f'#if MESH_GPS_VOICE_G726_BITRATE == {rate}\n')[1]
                source = source.split(f'#endif // {rate} kbps')[0]
            else:
                source = ((ROOT/'src/helpers/ui/GpsVoiceData.h').read_text() + '\n'
                          + (ROOT/'src/helpers/ui/ButtonVoiceData.h').read_text())
            for vibration in (False, True):
                body = select_vibration(source, vibration)
                arrays = {name:bytes.fromhex(' '.join(re.findall(r'0x([0-9a-f]{2})',data)))
                          for name,data in re.findall(r'static const uint8_t (\w+)Data\[\] = \{(.*?)\};',body,re.S)}
                self.assertEqual(len(arrays['gps']), sizes[0])
                self.assertEqual(len(arrays['advertPrefix']), sizes[1])
                self.assertEqual('soundPrefix' in arrays, vibration)
                if vibration:
                    self.assertEqual(len(arrays['soundPrefix']), sizes[2])
                self.assertEqual(sum(name.startswith('gps') for name in arrays), 3)


if __name__ == '__main__':
    unittest.main()
