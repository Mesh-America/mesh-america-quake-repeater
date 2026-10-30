#include <helpers/MorseTx.h>
#include <cassert>
#include <cstring>
#include <string>
#include <vector>

using mesh::MorseTx;
using Result = mesh::MorseTxResult;

static std::vector<uint32_t> phases(const char* text, uint8_t wpm, uint32_t start,
                                    bool hardware_delay = false) {
  uint32_t planned = 0;
  const auto valid = MorseTx::validate(text, wpm, &planned);
  MorseTx timer;
  if (valid != Result::Started) {
    assert(valid == Result::TooLong && timer.start(text, wpm, start) == valid);
    assert(!timer.active() && !timer.keyed());
    return {};
  }
  assert(timer.start(text, wpm, start) == Result::Started);
  std::vector<uint32_t> result;
  uint32_t now = start, total = 0;
  while (timer.active()) {
    const uint32_t phase = timer.nextDeadline() - now;
    assert(phase > 0 && phase < 65536);
    assert(timer.remainingMillis(now) == planned - total);
    assert(timer.advance(now + phase - 1) == MorseTx::Edge::None);
    now += phase; total += phase; result.push_back(phase);
    const auto edge = timer.advance(now);
    assert(edge != MorseTx::Edge::None && edge != MorseTx::Edge::Expired);
    if (timer.active() && hardware_delay) {
      now += 3; timer.edgeApplied(now);
      assert(timer.nextDeadline() > now); // The native transition owns its delay.
    }
    assert(result.size() < 2000);
  }
  assert(total == planned && timer.remainingMillis(now) == 0);
  return result;
}

int main() {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  using mesh::MorseHilTimingConfig;
  assert(mesh::morseHilTiming().jitter_percent == 0);
  const auto baseline = phases("SOS E T", 25, 100);
  for (const auto config : {MorseHilTimingConfig(), MorseHilTimingConfig(20,0,0,1),
      MorseHilTimingConfig(0,20,0,1), MorseHilTimingConfig(0,-20,0,1),
      MorseHilTimingConfig(0,0,50,1), MorseHilTimingConfig(15,10,25,12345),
      MorseHilTimingConfig(20,-20,50,0xffffffff)}) {
    assert(mesh::setMorseHilTiming(config));
    for (const uint8_t wpm : {uint8_t(1),uint8_t(25),uint8_t(60),uint8_t(200),uint8_t(255)}) {
      for (const char* text : {"E", "SOS E T", "   a    B  ", ". , ? ' ! / ( ) & : ; = + - _ \" $ @"}) {
        const auto first = phases(text, wpm, 100);
        assert(first == phases(text, wpm, 0xffffffe0));
      }
    }
  }
  assert(mesh::setMorseHilTiming(MorseHilTimingConfig(15,10,25,12345)));
  const auto expected = phases("SOS E T",25,100);
  assert(expected != baseline);
  assert(expected == phases("SOS E T",25,100,true));
  MorseTx running;
  assert(running.start("SOS E T",25,100) == Result::Started);
  assert(mesh::setMorseHilTiming(MorseHilTimingConfig(20,-20,50,54321)));
  uint32_t now=100;
  std::vector<uint32_t> actual;
  while(running.active()) {
    const uint32_t phase=running.nextDeadline()-now;
    actual.push_back(phase); now+=phase; running.advance(now);
  }
  assert(actual == expected); // Active settings are a snapshot, not live globals.

  assert(mesh::setMorseHilTiming(MorseHilTimingConfig(10,0,0,12345)));
  const auto fast = phases(std::string(80,'E').c_str(),255,100);
  bool changed_mark=false;
  for(size_t index=0;index<fast.size();index+=2) if(fast[index]!=5) changed_mark=true;
  assert(changed_mark); // Fractional jitter must survive at five-ms nominal dots.

  assert(mesh::setMorseHilTiming(MorseHilTimingConfig()));
  uint32_t duration=0;
  assert(MorseTx::validate(std::string(38,'E').c_str(),1,&duration)==Result::Started && duration==178800);
  assert(mesh::setMorseHilTiming(MorseHilTimingConfig(0,0,50,1)));
  duration=0xaabbccdd;
  assert(MorseTx::validate(std::string(38,'E').c_str(),1,&duration)==Result::TooLong);
  assert(duration==0xaabbccdd);
  assert(!mesh::setMorseHilTiming(MorseHilTimingConfig(21,0,0,1)));
  assert(!mesh::setMorseHilTiming(MorseHilTimingConfig(0,21,0,1)));
  assert(!mesh::setMorseHilTiming(MorseHilTimingConfig(0,-21,0,1)));
  assert(!mesh::setMorseHilTiming(MorseHilTimingConfig(0,0,51,1)));
  assert(!mesh::setMorseHilTiming(MorseHilTimingConfig(0,0,0,0)));
  assert(mesh::morseHilTiming().extra_gap_percent==50);
  MorseTx deadline;
  assert(deadline.start("SOS",25,0xffffffe0)==Result::Started);
  assert(deadline.advance(deadline.hardDeadline())==MorseTx::Edge::Expired);
  assert(!deadline.active() && !deadline.keyed());
  assert(mesh::setMorseHilTiming(MorseHilTimingConfig()));
#else
  struct ShippingLayout {
    char text[MorseTx::MaxTextLength+1];
    uint32_t next,hard_end,remaining;
    uint16_t unit,phase;
    uint8_t character,symbol,code,count;
    bool active,keyed;
  };
  static_assert(sizeof(MorseTx)==sizeof(ShippingLayout),"production TX layout must not grow");
  assert(phases("SOS",25,100)==std::vector<uint32_t>({48,48,48,48,48,144,144,48,144,48,144,144,48,48,48,48,48}));
#endif
}
