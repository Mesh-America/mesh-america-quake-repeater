#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#define PIN_BUZZER 25
#define MESH_BUTTON_AUDIO_HIL 1
#if defined(MESH_GPS_VOICE_G726_BITRATE)
#include <helpers/ui/G726VoiceData.h>
#else
#include <helpers/ui/ButtonVoiceData.h>
#include <helpers/ui/GpsVoiceData.h>
#endif
#include <helpers/ui/nrf52/GpsVoicePlayer.h>
uint32_t now_ms=0;
int main() {
  using namespace mesh::audio;
  const VoiceClip clips[]={readyClip,notificationClearedClip,advertQueuedClip,
    advertFailedClip,soundOnClip,soundOffClip,actionFailedClip,usbSetupClip,
    shuttingDownClip,restartingClip,gpsOnClip,gpsOffClip,
#ifdef HAS_DRV2605
    alertsSoundVibrationClip,alertsSoundOnlyClip,alertsVibrationOnlyClip,alertsSilentClip,
#endif
  };
  for (auto clip:clips) {
#ifdef PWM_OUTPUT
    GpsVoicePlayer player;
    assert(player.setGain(2));
    assert(player.start(clip));
    uint16_t first[2][128];
    for(unsigned i=0;i<2;++i)
      std::memcpy(first[i],reinterpret_cast<const void*>(registers.SEQ[i].PTR),sizeof(first[i]));
    unsigned sequence=0,events=0;
    while (player.playing()) {
      assert(++events<1000);
      const auto data=reinterpret_cast<const uint16_t*>(registers.SEQ[sequence].PTR);
      assert(std::fwrite(data,sizeof(*data),registers.SEQ[sequence].CNT,stdout)==registers.SEQ[sequence].CNT);
      registers.EVENTS_SEQEND[sequence]=1;player.interrupt();sequence^=1;
    }
    assert(player.played()==clip.samples);
    assert(player.completed()==1&&player.cancelled()==0);
    player.service();assert(!player.active()&&!HwPWM3.owned&&!irq_enabled);
    // Cancel before and after the GPS prefix seam, then restart. A tail must
    // never inherit another announcement's adaptive/interpolation state.
    for(unsigned fraction:{1u,3u}) {
      assert(player.start(clip));unsigned seq=0;
      while(player.playing()&&player.played()<clip.samples*fraction/4) {
        registers.EVENTS_SEQEND[seq]=1;player.interrupt();seq^=1;
      }
      assert(player.playing());player.stop();
      assert(!player.active()&&!HwPWM3.owned&&!irq_enabled);
      assert(player.start(clip));
      for(unsigned i=0;i<2;++i)
        assert(std::memcmp(first[i],reinterpret_cast<const void*>(registers.SEQ[i].PTR),sizeof(first[i]))==0);
      player.stop();
    }
    assert(player.started()==5&&player.completed()==1&&player.cancelled()==4);
#else
    VoiceDecoder decoder;decoder.begin(clip);
    for(uint32_t sample=0;sample<clip.samples;++sample) {
      assert(!decoder.done());const int16_t value=decoder.next();
      assert(std::fwrite(&value,sizeof(value),1,stdout)==1);
    }
    assert(decoder.done()&&decoder.position()==clip.samples&&decoder.next()==0);
#endif
  }
}
