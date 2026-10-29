#pragma once

#include <Dispatcher.h>

namespace mesh {

// Keyed Morse and RSSI-envelope capture require a responsive foreground loop.
// Defer optional background work without advancing its deadlines; the next
// ordinary pass resumes it. Keep voltage safety/watchdogs and command I/O live.
// An unkeyed CW meter test does not opt into this scheduling policy.
inline bool morseTimingActive(const Radio* radio) {
  return radio && (radio->isMorseTxActive() || radio->isMorseRxActive());
}

}  // namespace mesh
