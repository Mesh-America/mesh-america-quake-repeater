// Diagnostic for an OFF debounce committing before the RSSI decay settles.
#include <helpers/MorseRx.h>
#include <cstdio>
#include <initializer_list>
#include <cassert>
#include <cstring>
static void receive(uint8_t speed,uint32_t cadence) {
  mesh::MorseRx rx; uint32_t now=100;
  const auto unit=mesh::MorseTx::unitMillis(speed);
  rx.start(speed,300000,now);
  const auto level=[&](float value,uint32_t duration) {
    for (uint32_t elapsed=0; elapsed<duration; ++elapsed,++now)
      if (now%cadence==0) rx.sample(value,now);
  };
  level(-127.5f,520);
  level(-34.5f,unit); // E
  level(-94.0f,8); // long enough to commit OFF, not yet the true quiet floor
  level(-127.5f,unit*7-8);
  for (const char* pattern : {"...","---","..."}) {
    for (unsigned symbol=0; pattern[symbol]; ++symbol) {
      level(-118.0f,unit*(pattern[symbol]=='-' ? 3 : 1));
      if (pattern[symbol+1]) level(-127.5f,unit);
    }
    level(-127.5f,unit*3);
  }
  level(-127.5f,unit*7); rx.stop(now);
  mesh::MorseRxDiagnostics stats; rx.diagnostics(stats);
  std::printf("%uWPM/%lums: capture=\"%s\"; noise=%.1f\n",unsigned(speed),(unsigned long)cadence,rx.text(),stats.noise_dbm);
#ifdef MORSE_SHOULDER_REQUIRE_PASS
  assert(!strncmp(rx.text(),"E SOS",5) && (rx.length()==5 || (rx.length()==6 && rx.text()[5]==' ')));
#endif
}
int main() {
  for (uint8_t speed : {25,60}) for (uint32_t cadence : {1,2}) receive(speed,cadence);
#ifdef MORSE_SHOULDER_LAB_120
  for (uint32_t cadence : {1,2}) receive(120,cadence);
#endif
}
