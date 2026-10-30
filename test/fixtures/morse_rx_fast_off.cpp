#include <helpers/MorseRx.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <string>
struct Receiver {
  mesh::MorseRx rx; uint32_t now=100;
  Receiver(uint8_t wpm) { assert(rx.start(wpm,300000,now)==mesh::MorseRxResult::Started); level(-110,520); }
  void level(float rssi,uint32_t duration) { for(uint32_t i=0;i<duration;++i) rx.sample(rssi,now++); }
  std::string finish() { level(-110,1000); rx.stop(now); return rx.text(); }
};
static std::string shortened_gaps(uint8_t wpm) {
  Receiver r(wpm);
  for(unsigned dot=0;dot<5;++dot) {
    r.level(-80,8); // plausible fast-dot RF fall lag, still less than the dash boundary
    if(dot<4) r.level(-110,2);
  }
  return r.finish();
}
int main() {
  for(uint8_t speed:{200,240}) {
    const auto decoded=shortened_gaps(speed);
    if(EXPECTED_FAST_OFF) assert(decoded=="5 ");
    else assert(decoded!="5 "); // negative control: two quiet samples never confirm a two-ms OFF debounce
    Receiver quiet(speed); quiet.level(-110,10000);
    assert(quiet.finish().empty());
    Receiver on_spikes(speed);
    for(unsigned spike=0;spike<50;++spike) { on_spikes.level(-80,2); on_spikes.level(-110,20); }
    assert(on_spikes.finish().empty()); // fast OFF does not weaken the rising debounce
    Receiver mark_glitch(speed);
    for(unsigned dot=0;dot<5;++dot) {
      mark_glitch.level(-80,3); mark_glitch.level(-110,1); mark_glitch.level(-80,3);
      if(dot<4) mark_glitch.level(-110,mesh::MorseTx::unitMillis(speed));
    }
    assert(mark_glitch.finish()=="5 "); // one-ms negative spikes still cannot cut a mark
  }
  assert(shortened_gaps(120)!="5 "); // quarter-dot is still two-ms, even with a lower one-ms floor
  Receiver fade(240);
  fade.level(-80,6); fade.level(-110,40); // establish a confirmed floor before subsequent variation
  assert(fade.finish().find('E')==0);
}
