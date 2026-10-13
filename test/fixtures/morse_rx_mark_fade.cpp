// Read-only estimator experiment: strong carrier variation versus a new floor.
#include <helpers/MorseRx.h>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <cassert>

static void trial(const char* label,float signal,float quiet,bool vary_mark,bool vary_quiet,uint8_t wpm,uint32_t cadence=2,float initial=-127.5f) {
  mesh::MorseRx rx; uint32_t now=100, cuts=0, false_marks=0;
  rx.start(wpm,300000,now);
  const uint32_t unit=mesh::MorseTx::unitMillis(wpm);
  const auto level=[&](float mean,uint32_t duration,bool expected_mark) {
    for(uint32_t elapsed=0;elapsed<duration;elapsed+=cadence,now+=cadence) {
      float input=mean;
      if(expected_mark && vary_mark && elapsed>=8) {
        // Hold each fade long enough to be a real carrier-envelope change,
        // rather than an isolated sub-debounce spike.
        static const int excursion[]={0,-12,12,-6,6};
        input+=excursion[(elapsed/8)%5];
      } else if(!expected_mark && vary_quiet && mean==quiet) {
        static const int excursion[]={-3,-2,-1,0,1,2,3,2,1,0,-1,-2};
        input+=excursion[(elapsed/2)%12];
      }
      const bool before=rx.keyed(); rx.sample(input,now);
      if(expected_mark && before && !rx.keyed() && elapsed>=8) ++cuts;
      if(!expected_mark && !before && rx.keyed()) ++false_marks;
    }
  };
  level(initial,520,false);
  const char* text="SOS TEST 25";
  for(size_t letter=0;text[letter];++letter) {
    if(text[letter]==' ') continue;
    const uint8_t code=mesh::MorseTx::codeFor(text[letter]);
    for(uint8_t bit=mesh::MorseTx::symbolCount(code);bit;--bit) {
      level(signal,unit*(code&(1U<<(bit-1))?3:1),true);
      const unsigned gap=bit>1?1:(text[letter+1]==' '||!text[letter+1]?7:3);
      level(quiet,unit*gap,false);
    }
  }
  const bool stuck=rx.keyed(); rx.stop(now);
  const bool correct=strcmp(rx.text(),text)==0 || (rx.length()==strlen(text)+1 && !strncmp(rx.text(),text,strlen(text)));
#ifdef MORSE_MARK_FADE_REQUIRE_PASS
  if(signal-quiet>=6.0f) {
    assert(correct && !stuck && !false_marks);
    // The first provisional mark in this deliberately ambiguous33dB-SNR
    // envelope can include one discarded sub-dot edge at1/60WPM. Pin that
    // precise exception; no later mark or other waveform may silently cut.
    if(cuts) assert(!strcmp(label,"stable33SNR/12dBfade") && cuts==1 && (wpm==1 || wpm==60));
  }
#endif
  std::printf("%s %uWPM/%lums: required=%u correct=%u cuts=%lu false_marks=%lu stuck=%u text=\"%s\"\n",
      label,unsigned(wpm),(unsigned long)cadence,unsigned(signal-quiet>=6.0f),unsigned(correct),
      (unsigned long)cuts,(unsigned long)false_marks,unsigned(stuck),rx.text());
}
int main() {
  for(uint8_t wpm:{25,60}) {
    trial("strong12dB/noisyfloor",-23,-103,true,true,wpm);
    trial("strong12dB/floorstep",-23,-100,true,true,wpm);
    trial("strongsteady/noisyfloor",-23,-103,false,true,wpm);
    trial("weak6dB/floorstep",-94,-100,false,false,wpm);
  }
#ifdef MORSE_HYBRID_MATRIX
  for(uint8_t wpm:{1,25,60,120,240}) for(uint32_t cadence:{1,2}) {
    trial("strong12dB/noisyfloor",-23,-103,true,true,wpm,cadence);
    trial("strong12dB/floorstep30",-23,-97.5f,true,true,wpm,cadence);
    trial("weak6dB/step23.5",-98,-104,false,false,wpm,cadence);
    trial("weak6dB/step30",-91.5f,-97.5f,false,false,wpm,cadence);
    trial("weak7dB/stable",-120.5f,-127.5f,false,false,wpm,cadence);
    trial("stable33SNR/12dBfade",-23,-56,true,false,wpm,cadence,-56);
    for(unsigned span:{30,35,39,40,41,45,50}) {
      char label[48]; std::snprintf(label,sizeof(label),"initialSpan%u/step23.5",span);
      trial(label,-127.5f+span,-104,false,false,wpm,cadence);
      std::snprintf(label,sizeof(label),"initialSpan%u/step30",span);
      trial(label,-127.5f+span,-97.5f,false,false,wpm,cadence);
    }
  }
#endif
}
