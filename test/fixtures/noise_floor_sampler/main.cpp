#include <helpers/NoiseFloorHistorySampler.h>

#include <assert.h>
#include <limits>
#include <stdio.h>
#include <string>

using mesh::NoiseFloorHistory;
using mesh::NoiseFloorHistorySampler;
static constexpr uint32_t BASE = 1700000100UL;
static constexpr uint32_t MILLIS_BASE = 100000;

struct FakeProfiles {
  uint32_t generation[2] = {};
  bool second = false;
  bool enabled() const { return second; }
};

struct FakeRadio {
  FakeProfiles config;
  bool has_profiles = true;
  bool valid[2] = {};
  float dbm[2] = {};
  uint32_t published[2] = {};
  unsigned requests = 0;
  unsigned reads[2] = {};
  unsigned hardware_operations = 0;

  const FakeProfiles* profiles() const { return has_profiles ? &config : nullptr; }

  bool getNoiseFloorReading(uint8_t profile, float& floor, uint32_t& publication) {
    assert(profile < 2);
    ++reads[profile];
    if (!valid[profile]) return false;
    floor = dbm[profile];
    publication = published[profile];
    return true;
  }

  void requestNoiseFloorMeasurement() { ++requests; }

  void publish(uint8_t profile, uint32_t now_ms, float floor) {
    assert(profile < 2);
    valid[profile] = true;
    dbm[profile] = floor;
    published[profile] = now_ms;
  }
};

static uint32_t ms(unsigned seconds) { return MILLIS_BASE + seconds * 1000UL; }

static void successful() {
  FakeRadio radio;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  sampler.poll(radio, history, BASE, ms(0));
  assert(radio.requests == 1);
  for (unsigned offset : {4U, 304U, 604U}) {
    if (offset != 4) {
      sampler.poll(radio, history, BASE + offset - 4U, ms(offset - 4U));
    }
    radio.publish(0, ms(offset), offset == 4 ? -120 : offset == 304 ? -90 : -60);
    sampler.poll(radio, history, BASE + offset, ms(offset));
    const unsigned requests = radio.requests;
    for (unsigned i = offset; i < offset + 10; ++i) {
      sampler.poll(radio, history, BASE + i, ms(i));
    }
    assert(radio.requests == requests);
  }
  assert(radio.requests == 3 && history.sampleCount(0) == 0);
  sampler.poll(radio, history, BASE + 900, ms(900));
  assert(radio.requests == 4);
  assert(history.sampleCount(0) == 1 && history.sampleCodeAtOffset(0, 0) == 0);
  assert(history.sampleCodeAtOffset(1, 0) == 31);
  assert(radio.reads[1] == 0 && radio.hardware_operations == 0);
}

static void cached() {
  FakeRadio radio;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  radio.publish(0, ms(0), -110);
  sampler.poll(radio, history, BASE, ms(0));
  assert(radio.requests == 0);
  // A recent cached result may be read repeatedly, but is one publication.
  for (unsigned i = 1; i < 300; ++i) sampler.poll(radio, history, BASE + i, ms(i));
  assert(radio.requests == 0);
  sampler.poll(radio, history, BASE + 300, ms(300));
  assert(radio.requests == 1);
  for (unsigned i = 301; i < 600; ++i) sampler.poll(radio, history, BASE + i, ms(i));
  assert(radio.requests == 1);
  sampler.poll(radio, history, BASE + 600, ms(600));
  assert(radio.requests == 2);
  sampler.poll(radio, history, BASE + 900, ms(900));
  assert(history.sampleCount(0) == 1 && history.sampleCodeAtOffset(0, 0) == 31);
  assert(!history.hasValidSamples(0));

  // Calibration completed just before a subslot boundary still belongs to
  // that earlier subslot; it must not suppress the next measurement request.
  NoiseFloorHistory second_history;
  NoiseFloorHistorySampler second_sampler;
  FakeRadio second;
  second.publish(0, ms(299), -100);
  second_sampler.poll(second, second_history, BASE + 300, ms(300));
  assert(second.requests == 1);
}

static void rollover() {
  for (uint32_t first_ms : {0UL, 0xFFFFF000UL}) {
    FakeRadio radio;
    NoiseFloorHistory history;
    NoiseFloorHistorySampler sampler;
    for (unsigned offset : {0U, 300U, 600U}) {
      const uint32_t now = first_ms + offset * 1000UL;
      radio.publish(0, now, -119);
      sampler.poll(radio, history, BASE + offset, now);
    }
    assert(radio.requests == 0);
    sampler.poll(radio, history, BASE + 900, first_ms + 900000UL);
    assert(history.sampleCount(0) == 1 && history.sampleCodeAtOffset(0, 0) == 1);
    assert(radio.requests == 1);
  }
}

static void generations() {
  FakeRadio radio;
  radio.config.second = true;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  for (unsigned offset : {0U, 300U, 600U}) {
    if (offset == 600) ++radio.config.generation[0];
    radio.publish(0, ms(offset), -120);
    radio.publish(1, ms(offset), -70);
    sampler.poll(radio, history, BASE + offset, ms(offset));
  }
  sampler.poll(radio, history, BASE + 900, ms(900));
  assert(history.sampleCodeAtOffset(0, 0) == 31); // Pre-retune estimates discarded.
  assert(history.sampleCodeAtOffset(1, 0) == 26);
  for (unsigned offset : {904U, 1204U, 1504U}) {
    radio.publish(0, ms(offset), -118);
    radio.publish(1, ms(offset), -70);
    sampler.poll(radio, history, BASE + offset, ms(offset));
  }
  sampler.poll(radio, history, BASE + 1800, ms(1800));
  assert(history.sampleCodeAtOffset(0, 0) == 2);
  assert(history.sampleCodeAtOffset(1, 0) == 26);

  // A fresh-reading API becoming invalid clears accumulated estimates even
  // if generation is unchanged (gain/AGC recalibration).
  for (unsigned offset : {1804U, 2104U}) {
    radio.publish(0, ms(offset), -118);
    sampler.poll(radio, history, BASE + offset, ms(offset));
  }
  radio.valid[0] = false;
  sampler.poll(radio, history, BASE + 2105, ms(2105));
  radio.publish(0, ms(2404), -118);
  sampler.poll(radio, history, BASE + 2404, ms(2404));
  sampler.poll(radio, history, BASE + 2700, ms(2700));
  assert(history.sampleCodeAtOffset(0, 0) == 31);
  assert(history.sampleCodeAtOffset(0, 1) == 2); // Completed data stays intact.
}

static void enableDisable() {
  FakeRadio radio;
  radio.config.second = true;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  for (unsigned offset : {0U, 300U, 600U}) {
    if (offset == 300) radio.config.second = false;
    if (offset == 600) radio.config.second = true;
    radio.publish(0, ms(offset), -119);
    radio.publish(1, ms(offset), -70);
    const unsigned secondary_reads = radio.reads[1];
    sampler.poll(radio, history, BASE + offset, ms(offset));
    if (offset == 300) assert(radio.reads[1] == secondary_reads);
  }
  sampler.poll(radio, history, BASE + 900, ms(900));
  assert(history.sampleCodeAtOffset(0, 0) == 1);
  assert(history.sampleCodeAtOffset(1, 0) == 31); // No mixing across enablement.
  for (unsigned offset : {904U, 1204U, 1504U}) {
    radio.publish(0, ms(offset), -119);
    radio.publish(1, ms(offset), -70);
    sampler.poll(radio, history, BASE + offset, ms(offset));
  }
  sampler.poll(radio, history, BASE + 1800, ms(1800));
  assert(history.sampleCodeAtOffset(1, 0) == 26);
  radio.config.second = false;
  sampler.poll(radio, history, BASE + 1801, ms(1801));
  assert(history.sampleCodeAtOffset(1, 0) == 26); // Disabling retains old history.
}

static void clockChanges() {
  FakeRadio radio;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  for (unsigned offset : {0U, 300U, 600U}) {
    radio.publish(0, ms(offset), -118);
    sampler.poll(radio, history, BASE + offset, ms(offset));
  }
  radio.valid[0] = false;
  sampler.poll(radio, history, BASE + 3600, ms(601));
  assert(history.sampleCount(0) == 4);
  assert(history.sampleCodeAtOffset(0, 3) == 2);
  assert(history.sampleCodeAtOffset(0, 0) == 31);
  sampler.poll(radio, history, BASE + 1800, ms(602));
  assert(history.sampleCount(0) == 0);
  for (unsigned offset : {0U, 300U, 600U}) {
    radio.publish(0, ms(603 + offset), -119);
    sampler.poll(radio, history, BASE + 1800 + offset, ms(603 + offset));
  }
  sampler.poll(radio, history, BASE + 2700, ms(1503));
  assert(history.sampleCount(0) == 1 && history.sampleCodeAtOffset(0, 0) == 1);
  sampler.poll(radio, history, BASE + 2700 + 769U * 900U, ms(1504));
  assert(history.sampleCount(0) == 0);
}

static void unsupportedAndFresh() {
  FakeRadio unsupported;
  unsupported.has_profiles = false;
  NoiseFloorHistory empty;
  NoiseFloorHistorySampler no_hardware;
  for (unsigned offset : {0U, 300U, 600U, 900U}) {
    no_hardware.poll(unsupported, empty, BASE + offset, ms(offset));
  }
  assert(unsupported.requests == 4 && unsupported.reads[1] == 0);
  assert(unsupported.hardware_operations == 0);
  assert(empty.sampleCount(0) == 1 && !empty.hasValidSamples(0));
  assert(!empty.hasValidSamples(1));

  FakeRadio both;
  both.config.second = true;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  for (unsigned offset : {0U, 300U, 600U, 900U}) {
    both.publish(0, ms(offset), -119);
    both.publish(1, ms(offset), -70);
    sampler.poll(both, history, BASE + offset, ms(offset));
  }
  assert(both.requests == 0 && both.hardware_operations == 0);
  assert(history.sampleCodeAtOffset(0, 0) == 1 && history.sampleCodeAtOffset(1, 0) == 26);
  both.publish(0, ms(1200), -119);
  sampler.poll(both, history, BASE + 1200, ms(1200));
  assert(both.requests == 1); // Primary is fresh; secondary still needs a reading.
}

static void invalidReadings() {
  const float invalid[] = {
    std::numeric_limits<float>::quiet_NaN(),
    std::numeric_limits<float>::infinity(),
    -std::numeric_limits<float>::infinity(), -200.01f, 0.01f
  };
  for (float value : invalid) {
    FakeRadio radio;
    radio.config.second = true;
    NoiseFloorHistory history;
    NoiseFloorHistorySampler sampler;
    for (unsigned offset : {0U, 300U, 600U}) {
      radio.publish(0, ms(offset), value);
      radio.publish(1, ms(offset), -118);
      sampler.poll(radio, history, BASE + offset, ms(offset));
    }
    assert(radio.requests == 3); // Invalid values never suppress a request.
    sampler.poll(radio, history, BASE + 900, ms(900));
    assert(history.sampleCodeAtOffset(0, 0) == 31);
    assert(history.sampleCodeAtOffset(1, 0) == 2);
  }
  // Invalid data appearing after a valid estimate clears that pending profile,
  // rather than retaining a partial calibration across the invalid interval.
  FakeRadio radio;
  NoiseFloorHistory history;
  NoiseFloorHistorySampler sampler;
  radio.publish(0, ms(0), -120);
  sampler.poll(radio, history, BASE, ms(0));
  radio.publish(0, ms(1), invalid[0]);
  sampler.poll(radio, history, BASE + 1, ms(1));
  for (unsigned offset : {300U, 600U}) {
    radio.publish(0, ms(offset), -120);
    sampler.poll(radio, history, BASE + offset, ms(offset));
  }
  sampler.poll(radio, history, BASE + 900, ms(900));
  assert(history.sampleCodeAtOffset(0, 0) == 31);
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario(argv[1]);
  if (scenario == "successful") successful();
  else if (scenario == "cached") cached();
  else if (scenario == "rollover") rollover();
  else if (scenario == "generations") generations();
  else if (scenario == "enable_disable") enableDisable();
  else if (scenario == "clock") clockChanges();
  else if (scenario == "unsupported_fresh") unsupportedAndFresh();
  else if (scenario == "invalid") invalidReadings();
  else return 2;
  puts("noise floor sampler: ok");
}
