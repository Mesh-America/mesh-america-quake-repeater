#pragma once

// Local, explicitly instrumented builds only. Never write asynchronous output.
#if defined(ESP32_PLATFORM) && defined(MESH_HIL_RADIO_TRACE) && MESH_HIL_RADIO_TRACE
#include "ESP32RadioTrace.h"
#include <esp_system.h>
#include <stdio.h>
#include <string.h>

namespace mesh { namespace radiotrace {

inline uint64_t bootToken() {
  // A capture identity, not a security token. Initialize outside radio hot paths.
  static const uint64_t value = (uint64_t(esp_random()) << 32) | esp_random();
  return value;
}

inline const char* imageMarker() {
  return Marker;
}

inline bool parseTraceNumber(const char*& value, uint32_t& out) {
  if (*value < '0' || *value > '9') return false;
  uint32_t result = 0;
  while (*value >= '0' && *value <= '9') {
    const uint32_t digit = *value++ - '0';
    if (result > (UINT32_MAX - digit) / 10) return false;
    result = result * 10 + digit;
  }
  out = result;
  return true;
}

inline void formatTraceRecord(const Trace& capture, unsigned kind, uint32_t index,
                              char* reply, size_t capacity) {
  const uint32_t counts[] = {capture.span_count, capture.rx_count,
                            capture.tx_count, capture.bucket_count};
  const size_t limits[] = {SpanCapacity, RxCapacity, TxCapacity, BucketCapacity};
  if (kind >= 4 || index >= counts[kind] || index >= limits[kind]) {
    snprintf(reply, capacity, "Error: trace record unavailable");
    return;
  }
  if (kind == 0) {
    const Span& r = capture.spans[index];
    snprintf(reply, capacity, "> span=%lu,%lu,%lu,%lu,%u,%u,%u",
        (unsigned long)index, (unsigned long)r.begin_us, (unsigned long)r.header_us,
        (unsigned long)r.end_us, (unsigned)r.rx_index, (unsigned)r.profile, (unsigned)r.reason);
  } else if (kind == 1) {
    const RxRecord& r = capture.rx[index];
    snprintf(reply, capacity, "> rx=%lu,%lu,%lu,%lu,%lu,%016llx,%u,%u,%u,%u",
        (unsigned long)index, (unsigned long)r.done_lo_us, (unsigned long)r.done_hi_us,
        (unsigned long)r.read_begin_us, (unsigned long)r.rearm_end_us,
        (unsigned long long)r.hash64, (unsigned)r.len, (unsigned)r.span_index,
        (unsigned)r.profile, (unsigned)r.flags);
  } else if (kind == 2) {
    const TxRecord& r = capture.tx[index];
    snprintf(reply, capacity, "> tx=%lu,%016llx,%lu,%lu,%lu,%lu,%lu,%lu,%u,%u,%u,%lu",
        (unsigned long)index, (unsigned long long)r.hash64,
        (unsigned long)r.launch_lo_us, (unsigned long)r.launch_hi_us,
        (unsigned long)r.busy_low_us, (unsigned long)r.done_lo_us,
        (unsigned long)r.done_hi_us, (unsigned long)r.toa_us,
        (unsigned)r.len, (unsigned)r.profile, (unsigned)r.flags, (unsigned long)r.spi_errors);
  } else {
    const Bucket& r = capture.buckets[index];
    snprintf(reply, capacity, "> bucket=%lu,%lu,%lu,%lu,%lu,%lu", (unsigned long)index,
        (unsigned long)r.start_us, (unsigned long)r.max_scan_gap_us,
        (unsigned long)r.max_visit_overdue_us, (unsigned long)r.max_scan_gap_end_us,
        (unsigned long)r.max_visit_overdue_end_us);
  }
}

inline bool handleTraceCommand(const char* command, char* reply, size_t capacity) {
  if (!command || !reply || !capacity) return false;
  const char* get = "get radio.trace";
  const char* set = "set radio.trace";
  const bool getter = !strncmp(command, get, strlen(get))
      && (command[strlen(get)] == 0 || command[strlen(get)] == ' ');
  const bool setter = !strncmp(command, set, strlen(set))
      && (command[strlen(set)] == 0 || command[strlen(set)] == ' ');
  if (!getter && !setter) return false;
  const char* value = command + strlen(getter ? get : set);
  if (*value == ' ') ++value;
  Trace& capture = trace();
  const uint64_t now = nowUs();
  capture.tick(now);
  if (getter && !*value) {
    snprintf(reply, capacity,
        "> rt=1 boot=%016llx session=%lu state=%u epoch=%llu end=%llu flags=%lu mode=%s",
        (unsigned long long)bootToken(), (unsigned long)capture.session,
        (unsigned)capture.state, (unsigned long long)capture.epoch_us,
        (unsigned long long)capture.end_us, (unsigned long)capture.flags,
#if defined(MESH_HIL_RADIO_TRACE_TX_ONLY) && MESH_HIL_RADIO_TRACE_TX_ONLY
        "tx");
#else
        "rx");
#endif
    return true;
  }
  if (getter && !strcmp(value, "marker")) {
    snprintf(reply, capacity, "> %s", imageMarker());
    return true;
  }
  if (getter && !strncmp(value, "clock ", 6)) {
    const char* nonce = value + 6;
    bool valid = strlen(nonce) == 16;
    for (size_t i = 0; valid && i < 16; ++i) {
      const char c = nonce[i];
      valid = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')
          || (c >= 'A' && c <= 'F');
    }
    if (valid) {
      snprintf(reply, capacity, "> rt=1 boot=%016llx session=%lu nonce=%s us=%llu",
          (unsigned long long)bootToken(), (unsigned long)capture.session, nonce,
          (unsigned long long)now);
    } else snprintf(reply, capacity, "Error: clock requires exactly 16 hex digits");
    return true;
  }
  if (getter && !strcmp(value, "stats")) {
    snprintf(reply, capacity,
        "> spans=%lu rx=%lu tx=%lu buckets=%lu span_drop=%lu rx_drop=%lu tx_drop=%lu",
        (unsigned long)capture.span_count, (unsigned long)capture.rx_count,
        (unsigned long)capture.tx_count, (unsigned long)capture.bucket_count,
        (unsigned long)capture.span_dropped, (unsigned long)capture.rx_dropped,
        (unsigned long)capture.tx_dropped);
    return true;
  }
  if (getter && !strcmp(value, "gaps")) {
    snprintf(reply, capacity,
        "> scan=%lu overdue=%lu blackout=%lu spi_err=%lu invalid=%lu context_err=%lu",
        (unsigned long)capture.max_scan_gap_us, (unsigned long)capture.max_visit_overdue_us,
        (unsigned long)capture.max_blackout_us, (unsigned long)capture.spi_errors,
        (unsigned long)capture.invalidations, (unsigned long)capture.context_errors);
    return true;
  }
  if (setter && !strcmp(value, "stop")) {
    capture.stop(now);
    snprintf(reply, capacity, "OK - radio trace frozen");
    return true;
  }
  if (setter && !strncmp(value, "arm ", 4)) {
    const char* argument = value + 4;
    uint32_t delay = 0, duration = 0;
    if (!parseTraceNumber(argument, delay) || *argument++ != ' '
        || !parseTraceNumber(argument, duration) || *argument
        || delay > MaxDelayMs || !duration || duration > MaxCaptureMs) {
      snprintf(reply, capacity, "Error: arm requires delay 0..180000 and duration 1..180000 ms");
    } else if (capture.state == State::Armed || capture.state == State::Capturing) {
      snprintf(reply, capacity, "Error: stop the current trace before arming");
    } else if (!capture.arm(now, delay, duration)) {
      snprintf(reply, capacity, "Error: radio trace could not be armed");
    } else snprintf(reply, capacity, "OK - radio trace armed session=%lu", (unsigned long)capture.session);
    return true;
  }
  // Dump frozen RAM only, so reads cannot perturb an active capture or race it.
  if (getter) {
    const char* kinds[] = {"span ", "rx ", "tx ", "bucket "};
    for (unsigned kind = 0; kind < 4; ++kind) {
      if (strncmp(value, kinds[kind], strlen(kinds[kind]))) continue;
      const char* argument = value + strlen(kinds[kind]);
      uint32_t index = 0;
      if (!parseTraceNumber(argument, index) || *argument) {
        snprintf(reply, capacity, "Error: trace index must be an unsigned integer");
      } else if (capture.state != State::Frozen) {
        snprintf(reply, capacity, "Error: stop the trace before reading records");
      } else {
        // Record formatters below are intentionally bounded to one CLI frame.
        formatTraceRecord(capture, kind, index, reply, capacity);
      }
      return true;
    }
  }
  snprintf(reply, capacity, "Error: use get radio.trace [clock N|stats|gaps|marker|span N|rx N|tx N|bucket N] or set radio.trace arm D T|stop");
  return true;
}

} }
#endif
