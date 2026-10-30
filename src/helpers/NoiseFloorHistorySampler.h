#pragma once

#include "NoiseFloorHistory.h"

namespace mesh {

// Collect successful publications, not repeated reads of a cached estimate.
// Calibration stays in the radio's existing bounded, packet-safe state machine.
class NoiseFloorHistorySampler {
  uint32_t _request_bucket = 0;
  uint32_t _generation[2] = {};
  bool _armed = false;
  bool _enabled[2] = {};
  bool _valid[2] = {};

public:
  template<class RadioT>
  void poll(RadioT& radio, NoiseFloorHistory& history,
            uint32_t epoch, uint32_t now_ms) {
    history.advance(epoch);
    const auto* profiles = radio.profiles();
    const uint32_t slot = epoch / NoiseFloorHistory::READ_INTERVAL_SECONDS;
    bool fresh[2] = {};
    for (uint8_t profile = 0; profile < 2; ++profile) {
      const bool enabled = profile == 0 || (profiles && profiles->enabled());
      const uint32_t generation = profiles ? profiles->generation[profile] : 0;
      if (_enabled[profile] != enabled || _generation[profile] != generation) {
        history.invalidateProfile(profile);
        _valid[profile] = false;
      }
      _enabled[profile] = enabled;
      _generation[profile] = generation;
      float dbm = 0;
      uint32_t published_ms = 0;
      const bool valid = enabled
          && radio.getNoiseFloorReading(profile, dbm, published_ms)
          && isfinite(dbm) && dbm >= -200.0f && dbm <= 0.0f;
      if (!valid && _valid[profile]) history.invalidateProfile(profile);
      _valid[profile] = valid;
      if (!valid) continue;
      const uint32_t age_ms = now_ms - published_ms;
      if (age_ms >= NoiseFloorHistory::READ_INTERVAL_SECONDS * 1000UL
          || age_ms / 1000UL > epoch) continue;
      const uint32_t measured_epoch = epoch - age_ms / 1000UL;
      history.observe(profile, measured_epoch, dbm, published_ms);
      fresh[profile] = measured_epoch / NoiseFloorHistory::READ_INTERVAL_SECONDS == slot;
    }
    if (!_armed || _request_bucket != slot) {
      _armed = true;
      _request_bucket = slot;
      if (!fresh[0] || (_enabled[1] && !fresh[1])) {
        radio.requestNoiseFloorMeasurement();
      }
    }
  }
};

}  // namespace mesh
