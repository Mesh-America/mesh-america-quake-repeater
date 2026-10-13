// CW floor-step/fading regression, also reusable for read-only lab A/B copies.
// Default code prints results; REQUIRE_PASS asserts exact text and no stuck RF.
#include <helpers/MorseRx.h>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <cassert>
static void receive(const char* label,float quiet,float mark,bool fade,uint8_t wpm=25,uint32_t cadence=1,bool jitter=false,bool spikes=false) {
  mesh::MorseRx rx; uint32_t now=100;
  rx.start(wpm,300000,now);
  const uint32_t unit=mesh::MorseTx::unitMillis(wpm);
  const auto level=[&](float value,uint32_t duration) {
    for (uint32_t elapsed=0; elapsed<duration; ++elapsed,++now) {
      if (now%cadence==0) {
        float input=jitter && value!=quiet && value>-104 ? value+int(now%7)-3 : value;
        if (spikes && value==quiet && now%137==0) input=-60;
        rx.sample(input,now);
      }
    }
  };
  level(-127.5f,520);
  const char* text="SOS TEST 25";
  unsigned marks=0;
  for (size_t letter=0; text[letter]; ++letter) {
    if (text[letter]==' ') continue;
    const uint8_t code=mesh::MorseTx::codeFor(text[letter]);
    for (uint8_t bit=mesh::MorseTx::symbolCount(code); bit; --bit) {
      const unsigned units=code & (1U<<(bit-1)) ? 3 : 1;
      const float signal=fade && marks++>8 ? -94.0f : mark;
      level(signal,unit*units);
      const unsigned gap=bit>1 ? 1 : (text[letter+1]==' ' || !text[letter+1] ? 7 : 3);
      level(quiet,unit*gap);
    }
  }
  mesh::MorseRxDiagnostics diagnostics; rx.diagnostics(diagnostics);
  const bool stuck=rx.keyed(); rx.stop(now);
#ifdef MORSE_ESTIMATOR_REQUIRE_PASS
  assert(!stuck && !strncmp(rx.text(),text,strlen(text)));
  assert(rx.length()==strlen(text) || (rx.length()==strlen(text)+1 && rx.text()[strlen(text)]==' '));
#endif
  std::printf("%s (%u WPM, %lu ms polling): capture=\"%s\", stuck=%u, noise=%.1f, unit=%u\n",
      label,unsigned(wpm),(unsigned long)cadence,rx.text(),unsigned(stuck),diagnostics.noise_dbm,unsigned(diagnostics.unit_ms));
}
int main() {
  receive("unchanged floor / strong",-127.5f,-34.5f,false);
  receive("floor step / strong",-104.0f,-34.5f,false);
  receive("floor step / moderate",-104.0f,-64.0f,false);
  receive("floor step / weak6dB",-104.0f,-98.0f,false);
  receive("30dB floor step / weak6dB",-97.5f,-91.5f,false);
  receive("unchanged floor / fading",-127.5f,-34.5f,true);
  receive("floor step / fading",-104.0f,-34.5f,true);
#ifdef MORSE_ESTIMATOR_EXTENDED
  for (uint8_t speed : {1,25,60,120,240}) for (uint32_t cadence : {1,2}) {
    receive("floor step / strong",-104.0f,-34.5f,false,speed,cadence);
    receive("floor step / moderate",-104.0f,-64.0f,false,speed,cadence);
    receive("floor step / weak6dB",-104.0f,-98.0f,false,speed,cadence);
    receive("floor step / fading",-104.0f,-34.5f,true,speed,cadence);
    receive("floor step / 3dB jitter",-104.0f,-34.5f,false,speed,cadence,true);
    receive("unchanged floor / weak7dB",-127.5f,-120.5f,false,speed,cadence);
    receive("floor step / 1ms quiet spikes",-104.0f,-34.5f,false,speed,cadence,false,true);
  }
#endif
}
