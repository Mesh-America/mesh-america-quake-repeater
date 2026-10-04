"""Exercise opt-in G.726 speech against independent FFmpeg MSB-packed vectors."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

import test_gps_voice_buttons as shared
from test_button_voice_generator import ZIRA_RECORDINGS
from test_gps_voice_generator import ZIRA_GPS_RECORDINGS

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('gcc')
CXX = shutil.which('g++')
DECODER = ROOT / 'src/helpers/ui/g726/g726_decoder.c'
SANITIZERS = (['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
               '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
              if os.environ.get('MESH_G726_TEST_SANITIZERS') == '1' else [])

# FFmpeg 7.1 g726 encoder/decoder, 8 kHz mono, continuous MSB-first packing.
# Input: 149 samples of int(23000*sin(i*.43)+7000*sin(i*1.97)). The reference
# PCM below is pinned, not computed with the decoder being tested. Odd sample
# counts exercise both cross-byte extraction and ignored final padding bits.
VECTORS = {
    16: (
        '1555aaae557fafd05c2fa3d41cebf7170be8f4133aedc41ffaf1d70ee83113caf9c402fa3d00',
        (12,60,68,80,100,120,144,192,-152,-260,-460,-808,-1348,-2240,-1496,-3228,
         2668,6388,11088,18032,28296,3608,-2328,-5448,-17708,-30576,-21068,-16732,
         -13524,7960,9392,10368,19852,31136,7272,9872,9056,-11444,-11928,-10604,
         -19392,-31324,-7528,-9496,-9344,11660,29504,21868,17484,28932,6588,6040,
         -2032,-15800,-30028,-23620,-19428,-15560,8012,1476,7584,18856,30580,8036,
         11692,10804,-11724,-14448,-12284,-20856,32136,-8856,-9784,-9688,12472,
         15444,12360,21112,18280,4004,3612,-1752,-11740,-20788,-16104,-24696,
         -20612,7188,-204,8240,23980,20804,14996,23660,8108,-3212,-8576,-10660,
         -18848,-25496,-18976,-15376,-5852,10232,7664,20152,-32364,13088,10528,
         10836,-900,-16984,-15196,-22620,28652,-15884,1424,-152,8760,23344,17788,
         21364,20676,8416,-2200,-2692,-13772,-24704,-19472,-14280,-21680,4836,
         4692,9024,25744,25352,17892,15096,11768,-7900,-14896,-14800,-21052,
         -29392,-11948,-6336,-6580,11280,18152),
    ),
    24: (
        'edb6db92493e6d25ef976a976b93679bfcd7677f2fb972d7467d37a512cf3a6d39a9f2bd367d4aed72adf29d93e96e65f6afdae8dda5f732',
        (0,60,76,92,108,132,180,252,-272,-476,-908,-1840,-3640,-7076,-1780,-3756,
         6724,16012,19764,21560,22432,8192,-8500,-3184,-18772,-24144,-17696,
         -14340,-18324,4024,13468,6724,19724,25136,11348,10740,9836,-5588,
         -19216,-9292,-28780,-23492,-10576,-4544,-6324,13428,24408,12108,27792,
         23912,2564,-912,-1384,-18568,-27700,-13868,-18952,-17316,3560,5296,
         7024,18520,25224,12844,15316,13484,-10176,-10292,-11676,-26980,-26004,
         -12020,-16696,-4148,14284,17648,15116,22948,21032,8440,5108,-2084,
         -17480,-21536,-18780,-25992,-16528,2392,-3592,9136,29948,21828,17336,
         23512,13388,-9504,-7892,-12828,-27144,-19100,-13100,-17900,-5200,
         11896,11460,20468,30592,19264,10800,12696,-3676,-18696,-14372,-20972,
         -30060,-11752,-3936,-5604,8180,25072,17120,19576,26832,9028,-3872,
         -1548,-15656,-28576,-16560,-15880,-21400,204,9884,6276,17700,27396,
         14016,12568,13016,-5332,-15028,-13156,-20244,-25892,-13184,-9964,
         -9684,11280,23016),
    ),
}

PREAMBLE = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <vector>
#include <helpers/ui/GpsVoice.h>
#define PIN_BUZZER 25
#include <helpers/ui/nrf52/GpsVoicePlayer.h>
uint32_t now_ms=0;
using namespace mesh::audio;
'''

DECODE_MAIN = r'''
int main(){
 constexpr auto codec=VoiceCodec::G726@RATE@;
 constexpr unsigned bits=@BITS@;
 const uint8_t data[]={@DATA@};
 const int16_t expected[]={@PCM@};
 constexpr unsigned count=sizeof(expected)/sizeof(expected[0]);
 const VoiceClip full{data,sizeof(data),count,8000,codec};
 assert(full.valid()&&full.bits()==bits);
 assert(full.requiredBytes(count)==sizeof(data));
 VoiceDecoder decoder;
 auto check=[&](VoiceClip clip,unsigned samples){
   decoder.begin(clip);assert(decoder.position()==0);
   for(unsigned i=0;i<samples;++i){assert(!decoder.done());assert(decoder.next()==expected[i]);}
   assert(decoder.done()&&decoder.position()==samples);
   for(unsigned i=0;i<8;++i)assert(decoder.next()==0&&decoder.position()==samples);
 };
 // Each clip resets adaptive state, including after partial playback.
 for(unsigned repetition=0;repetition<3;++repetition){
   check(full,count);decoder.begin(full);decoder.next();check(full,count);
 }
 for(unsigned n:{1u,2u,3u,4u,5u,7u,8u,9u,31u,32u,33u,63u,64u,65u,count}){
   VoiceClip short_clip{data,full.requiredBytes(n),n,8000,codec};
   assert(short_clip.valid());check(short_clip,n);
 }
 std::vector<uint8_t> padding(data,data+sizeof(data));
 const unsigned unused=(8-(count*bits)%8)%8;
 assert(unused);padding.back()^=(1u<<unused)-1;
 check({padding.data(),padding.size(),count,8000,codec},count);
 // Truncated metadata may decode only complete codes; it never reads padding
 // or a second byte beyond the declared span when a 3-bit code straddles it.
 for(size_t bytes=0;bytes<sizeof(data);++bytes){
   std::vector<uint8_t> bounded(data,data+bytes);
   VoiceClip short_clip{bounded.data(),bytes,count,8000,codec};
   assert(!short_clip.valid());check(short_clip,static_cast<unsigned>(bytes*8/bits));
 }
 check({nullptr,sizeof(data),count,8000,codec},0);
 check({data,sizeof(data),0,8000,codec},0);
 check({data,0,count,8000,codec},0);
 VoiceClip huge{data,sizeof(data)-1,std::numeric_limits<uint32_t>::max(),8000,codec};
 assert(!huge.valid());check(huge,static_cast<unsigned>((sizeof(data)-1)*8/bits));
 VoiceClip all_bytes{data,std::numeric_limits<size_t>::max(),
                     std::numeric_limits<uint32_t>::max(),8000,codec};
 assert(all_bytes.requiredBytes(all_bytes.samples)==
        (static_cast<uint64_t>(all_bytes.samples)*bits+7)/8);
 assert(all_bytes.valid()); // Validation only: actual pointer length is caller-owned.
 auto other=codec==VoiceCodec::G72616?VoiceCodec::G72624:VoiceCodec::G72616;
 for(auto invalid:{other,static_cast<VoiceCodec>(255)}){
   VoiceClip bad{data,sizeof(data),count,8000,invalid};
   assert(!bad.valid());check(bad,0);
 }
 assert(!VoiceClip(data,sizeof(data),count,16000,codec).valid());
 // IMA remains selectable in an experiment, with its original 4-argument API.
 const uint8_t ima[]={0x77};
 VoiceClip original{ima,sizeof(ima),2};assert(original.codec==VoiceCodec::Ima&&original.valid());
 decoder.begin(original);assert(decoder.next()==11&&decoder.next()==41&&decoder.done());
 check(full,count);decoder.begin(original);assert(decoder.next()==11);
}
'''

PLAYER_MAIN = r'''
int main(){
 constexpr auto codec=VoiceCodec::G726@RATE@;
 const uint8_t data[]={@DATA@};
 const int16_t expected[]={@PCM@};
 constexpr unsigned count=sizeof(expected)/sizeof(expected[0]);
 GpsVoicePlayer player;
 assert(player.setGain(2));
 for(unsigned n:{1u,3u,31u,32u,33u,63u,64u,65u,count}){
   VoiceClip clip{data,sizeof(data),n,8000,codec};
   assert(player.start(clip)&&player.active()&&player.playing());
   assert(HwPWM3.owned&&HwPWM3.bound_pin==PIN_BUZZER&&irq_enabled);
   assert(registers.COUNTERTOP==500&&registers.SEQ[0].REFRESH==0);
   VoiceDecoder reference;reference.begin(clip);
   VoiceInterpolator reconstruction;reconstruction.begin();
   for(unsigned i=0;i<2;++i){
     auto values=reinterpret_cast<const uint16_t*>(registers.SEQ[i].PTR);
     assert(registers.SEQ[i].CNT==128);
     for(unsigned j=0;j<128;++j){
       int32_t pcm=reconstruction.next(reference)*2;
       if(pcm>32767)pcm=32767;
       if(pcm < -32768)pcm=-32768;
       assert(values[j]==(0x8000|static_cast<uint16_t>((pcm+32768)*500/65536)));
     }
   }
   unsigned sequence=0,events=0;
   while(player.playing()){
     assert(++events<100);registers.EVENTS_SEQEND[sequence]=1;player.interrupt();sequence^=1;
   }
   assert(player.played()==n&&events==(n*4+127)/128&&player.active());
   player.service();assert(!player.active()&&!HwPWM3.owned&&!HwPWM3.pin&&!irq_enabled);
   assert(!registers.ENABLE&&pin_states[PIN_BUZZER]==LOW);
 }
 assert(player.started()==9&&player.completed()==9&&player.cancelled()==0);
 VoiceClip full{data,sizeof(data),count,8000,codec};
 assert(player.start(full));player.stop();
 assert(player.cancelled()==1&&!HwPWM3.owned&&!irq_enabled);
 assert(!player.start({data,sizeof(data)-1,count,8000,codec}));
 assert(!player.start({data,sizeof(data),count,16000,codec}));
 assert(!player.start({nullptr,sizeof(data),count,8000,codec}));
 assert(!player.start({data,sizeof(data),0,8000,codec}));
 assert(!player.start({data,sizeof(data),count,8000,static_cast<VoiceCodec>(255)}));
 auto other=codec==VoiceCodec::G72616?VoiceCodec::G72624:VoiceCodec::G72616;
 assert(!player.start({data,sizeof(data),count,8000,other}));
 HwPWM3.reject=true;assert(!player.start(full));
 assert(!player.active()&&!HwPWM3.owned&&!irq_enabled&&!registers.ENABLE);
}
'''


@unittest.skipUnless(CC and CXX, 'Native C and C++ compilers are required')
class Tests(unittest.TestCase):
    def build(self, source, bitrate, *, run=True, expected_error=None):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'Arduino.h').write_text(shared.ARDUINO)
            (directory/'HardwarePWM.h').write_text(shared.PWM)
            (directory/'NonBlockingRtttl.h').write_text(shared.RTTTL)
            path=directory/'test.cpp';path.write_text(source)
            binary=directory/'test'
            flags=[] if bitrate is None else [f'-DMESH_GPS_VOICE_G726_BITRATE={bitrate}',
                                              '-DMESH_BUTTON_AUDIO_HIL=1']
            if expected_error is not None:
                result=subprocess.run([CXX,'-std=c++17','-I'+str(ROOT/'src'),
                                       '-c',str(path),'-o',str(directory/'gate.o')],
                                      capture_output=True,text=True,timeout=30)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(expected_error,result.stderr)
                return
            objects=[]
            if bitrate is not None:
                obj=directory/'decoder.o'
                subprocess.run([CC,'-std=c99','-Wall','-Wextra','-Werror',*SANITIZERS,*flags,
                                '-I'+str(ROOT/'src'),'-c',str(DECODER),'-o',str(obj)],
                               check=True,timeout=30)
                objects.append(str(obj))
            subprocess.run([CXX,'-std=c++17','-Wall','-Wextra','-Werror',*SANITIZERS,*flags,
                            '-I'+str(directory),'-I'+str(ROOT/'src'),'-I'+str(ROOT),
                            str(path),*objects,'-o',str(binary)],check=True,timeout=30)
            if run:subprocess.run([str(binary)],check=True,timeout=30)

    def fixture(self, source, bitrate):
        data,pcm=VECTORS[bitrate]
        return (PREAMBLE+source.replace('@RATE@',str(bitrate))
                .replace('@BITS@',str(bitrate//8))
                .replace('@DATA@',','.join('0x'+data[i:i+2] for i in range(0,len(data),2)))
                .replace('@PCM@',','.join(map(str,pcm))))

    def test_msb_reference_vectors_reset_padding_odd_lengths_and_bounds(self):
        for bitrate in VECTORS:
            with self.subTest(bitrate=bitrate):self.build(self.fixture(DECODE_MAIN,bitrate),bitrate)

    def test_g726_shares_existing_pwm_interpolation_and_dma_lifecycle(self):
        for bitrate in VECTORS:
            with self.subTest(bitrate=bitrate):self.build(self.fixture(PLAYER_MAIN,bitrate),bitrate)

    def test_segmented_stream_preserves_cross_byte_codes_adaptive_state_and_bounds(self):
        source = DECODE_MAIN.split('int main(){', 1)[1].split(' assert(full.valid()', 1)[0]
        source = 'int main(){' + source + r'''
 for(size_t split=0;split<sizeof(data);++split){
   VoiceClip clip{data+split,sizeof(data)-split,count,8000,codec,data,split};
   assert(clip.valid());VoiceDecoder decoder;decoder.begin(clip);
   for(unsigned i=0;i<count;++i){assert(!decoder.done());assert(decoder.next()==expected[i]);}
   assert(decoder.done()&&decoder.position()==count);
   for(size_t tail=0;tail<sizeof(data)-split;++tail){
     std::vector<uint8_t> prefix(data,data+split),suffix(data+split,data+split+tail);
     // A non-null placeholder is legal when the suffix's declared length is
     // zero. ASan bounds the actual prefix/tail allocation independently.
     VoiceClip short_clip{tail?suffix.data():data,tail,count,8000,codec,
                          split?prefix.data():nullptr,split};
     assert(!short_clip.valid());decoder.begin(short_clip);
     const unsigned available=static_cast<unsigned>((split+tail)*8/bits);
     for(unsigned i=0;i<available;++i){assert(!decoder.done());assert(decoder.next()==expected[i]);}
     assert(decoder.done()&&decoder.position()==available&&decoder.next()==0);
   }
 }
 VoiceClip missing_prefix{data,sizeof(data),count,8000,codec,nullptr,1};
 assert(!missing_prefix.valid());VoiceDecoder decoder;decoder.begin(missing_prefix);
 assert(decoder.done()&&decoder.next()==0);
 VoiceClip huge{data,std::numeric_limits<size_t>::max(),
                std::numeric_limits<uint32_t>::max(),8000,codec,data,1};
 assert(huge.valid()&&huge.hasBytes(std::numeric_limits<size_t>::max()));
 GpsVoicePlayer player;assert(!player.start(missing_prefix)&&!player.active());
}
'''
        for bitrate in VECTORS:
            with self.subTest(bitrate=bitrate):self.build(self.fixture(source,bitrate),bitrate)

    def test_invalid_bitrates_or_missing_laboratory_gate_cannot_compile(self):
        for flags,error in (
            ('#define MESH_GPS_VOICE_G726_BITRATE 16\n','opt-in MESH_BUTTON_AUDIO_HIL'),
            ('#define MESH_BUTTON_AUDIO_HIL 0\n#define MESH_GPS_VOICE_G726_BITRATE 24\n',
             'opt-in MESH_BUTTON_AUDIO_HIL'),
            *[(f'#define MESH_BUTTON_AUDIO_HIL 1\n#define MESH_GPS_VOICE_G726_BITRATE {rate}\n',
               'bitrate must be 16 or 24') for rate in (0,8,32,40)],
        ):
            with self.subTest(flags=flags):
                self.build(flags+'#include <helpers/ui/GpsVoice.h>\n',None,expected_error=error)

    def test_default_ima_has_no_experimental_decoder_dependency(self):
        self.build(PREAMBLE+r'''
int main(){
 const uint8_t data[]={0x77};VoiceClip clip{data,sizeof(data),2};
 VoiceDecoder decoder;decoder.begin(clip);
 assert(decoder.next()==11&&decoder.next()==41&&decoder.done());
}
''',None)


REFERENCE_DIR = Path(os.environ.get('G726_REFERENCE_DIR',
                                  str(ROOT/'out/gps-voice/g726-test')))


@unittest.skipUnless(CC and CXX and (REFERENCE_DIR/'report.json').is_file(),
                     'Optional independently decoded voice-catalog fixtures are unavailable')
class LocalVoiceCatalogTests(unittest.TestCase):
    build = Tests.build

    def test_all_32_actual_zira_g726_recordings_match_independent_ffmpeg_pcm(self):
        report=json.loads((REFERENCE_DIR/'report.json').read_text(encoding='utf-8'))
        expected_samples={name:recording[1] for name,recording in
                          {**ZIRA_RECORDINGS,**ZIRA_GPS_RECORDINGS}.items()}
        self.assertEqual({clip['clip'] for clip in report['clips']}, set(expected_samples))
        for bitrate in (16,24):
            statements=[]
            for clip in report['clips']:
                name=clip['clip'];samples=clip['samples']
                self.assertEqual(samples,expected_samples[name])
                data=(REFERENCE_DIR/f'{name}.g726{bitrate}.be').read_bytes()
                pcm_bytes=(REFERENCE_DIR/f'{name}.g726{bitrate}.decoded8k.s16le').read_bytes()
                self.assertEqual(len(data),(samples*(bitrate//8)+7)//8)
                self.assertEqual(len(pcm_bytes),samples*2)
                self.assertEqual(hashlib.sha256(data).hexdigest(),
                                 clip['codecs'][f'g726{bitrate}']['payload_sha256'])
                pcm=struct.unpack(f'<{samples}h',pcm_bytes)
                statements.append('''{
 const uint8_t data[]={'''+','.join(map(str,data))+'''};
 const int16_t expected[]={'''+','.join(map(str,pcm))+'''};
 VoiceClip clip{data,sizeof(data),'''+str(samples)+''',8000,VoiceCodec::G726'''+str(bitrate)+'''};
 assert(clip.valid());VoiceDecoder decoder;decoder.begin(clip);
 for(unsigned i=0;i<clip.samples;++i){assert(!decoder.done());assert(decoder.next()==expected[i]);}
 assert(decoder.done()&&decoder.position()==clip.samples&&decoder.next()==0);
}
''')
            with self.subTest(bitrate=bitrate):
                self.build(PREAMBLE+'int main(){\n'+''.join(statements)+'}\n',bitrate)


if __name__=='__main__':
    unittest.main()
