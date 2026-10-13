#pragma once

#include <Dispatcher.h>
#include <helpers/CLICommandUtils.h>
#include <helpers/MorseSettings.h>
#include <helpers/MorseReplyHandoff.h>
#include <stdio.h>
#include <string.h>

namespace mesh {

inline const char* morseUsageError() {
#if MESH_ENABLE_MORSE_RX
  return "Error: use morse send <text> | listen <minutes> | read [offset] | stats | clear | stop";
#else
  return "Error: use morse send <text> | stop";
#endif
}

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
inline bool parseMorseHilTiming(const char* argument, MorseHilTimingConfig& timing) {
  if (!argument || strlen(argument) >= 64) return false;
  char fields[64];
  strcpy(fields, argument);
  char* values[4] = {fields, nullptr, nullptr, nullptr};
  for (unsigned index = 0; index < 3; ++index) {
    char* separator = strchr(values[index], ',');
    if (!separator) return false;
    *separator = 0; values[index + 1] = separator + 1;
  }
  if (strchr(values[3], ',')) return false;
  uint32_t jitter = 0, gap = 0, seed = 0;
  int32_t drift = 0;
  if (!cli::parseUnsignedIntegerStrict(values[0], jitter) || jitter > 20
      || !cli::parseIntegerStrict(values[1], drift) || drift < -20 || drift > 20
      || !cli::parseUnsignedIntegerStrict(values[2], gap) || gap > 50
      || !cli::parseUnsignedIntegerStrict(values[3], seed) || !seed) return false;
  timing = MorseHilTimingConfig(uint8_t(jitter), int8_t(drift), uint8_t(gap), seed);
  return true;
}
#endif

// Intercept only an explicitly authenticated remote callback. Local USB/BLE
// commands keep immediate listening; a nonzero timestamp alone is not authority.
inline bool handleMorseReplyCommand(MorseReplyHandoff& handoff, Radio* radio,
                                    const char* command, char* reply,
                                    size_t capacity, uint32_t now) {
#if MESH_ENABLE_MORSE_RX
  if (!command || !reply || !capacity) return false;
  const char* key = command;
  bool query = false, setting = false;
  if (!strncmp(key, "get ", 4)) { query = true; key += 4; }
  else if (!strncmp(key, "set ", 4)) { setting = true; key += 4; }
  const size_t key_length = strcspn(key, " \t");
  const bool base = key_length == 5 && !strncmp(key, "morse", 5);
  const char* action = cli::skipRecentRepeaterSpaces(key + key_length);
  const size_t action_length = strcspn(action, " \t");
  const char* argument = cli::skipRecentRepeaterSpaces(action + action_length);
  const bool stop = base && !query && !setting && action_length == 4
      && !strncmp(action, "stop", 4) && !*argument;
  const bool listen = base && !query && !setting && action_length == 6
      && !strncmp(action, "listen", 6);
  if (stop && handoff.pending()) {
    handoff.cancel();
    snprintf(reply, capacity, "OK - pending Morse RX cancelled; packet radio unchanged");
    return true;
  }
  if (handoff.pending()) {
    if (base && !setting && !*action) {
      snprintf(reply, capacity, "> Morse RX queued; waiting for command reply to transmit; use morse stop to cancel");
      return true;
    }
    // Prevent a second explicit RF/settings action from replacing the staged
    // request. Read-only capture/status queries remain available.
    const bool read_only_morse = base && ((action_length == 4 && !strncmp(action, "read", 4))
        || (action_length == 5 && !strncmp(action, "stats", 5))
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
        || (action_length == 5 && !strncmp(action, "trace", 5))
#endif
        );
    const bool cw = (key_length == 2 && !strncmp(key, "cw", 2))
        || (key_length == 3 && !strncmp(key, "cw2", 3));
    if (setting || (base && !query && !read_only_morse)
        || (!query && cw && *action) || !strncmp(key, "tempradio", 9)
        || (!query && key_length == 5 && !strncmp(key, "radio", 5) && *action)
        || (!query && key_length == 6 && !strncmp(key, "radio2", 6) && *action)) {
      snprintf(reply, capacity, "Error: Morse reply handoff pending; use morse stop or retry later");
      return true;
    }
  }
  if (!handoff.remoteCommand() || !listen) return false;
  float minutes = 0;
  if (!radio || !radio->supportsMorseRx() || !morseSettingsUsable()
      || !cli::parseDecimalStrict(argument, minutes) || minutes <= 0 || minutes > 5) return false;
  const uint32_t duration = uint32_t(minutes * 60000.0f + 0.5f);
  if (duration < 1000 || duration > 300000) return false;
  if (radio->isCarrierWaveActive() || radio->isMorseTxActive() || radio->isMorseRxActive()) {
    snprintf(reply, capacity, "Error: radio busy; stop Morse/CW or retry when idle");
    return true;
  }
  const auto& settings = morseSettings();
  if (!handoff.stage(settings.frequency_khz, settings.wpm, duration, now)) {
    snprintf(reply, capacity, "Error: Morse reply handoff pending; retry later");
    return true;
  }
  snprintf(reply, capacity,
      "OK - Morse RX queued %.3f MHz for %.2f min; starts after this reply transmits; keep first 0.5 s quiet",
      settings.frequencyMHz(), minutes);
  return true;
#else
  (void)handoff; (void)radio; (void)command; (void)reply; (void)capacity; (void)now;
  return false;
#endif
}

#if MESH_ENABLE_MORSE_RX
inline void formatMorseCapturePage(Radio* radio, const char* argument,
                                   char* reply, size_t capacity) {
  uint32_t offset = 0;
  if (*argument && !cli::parseUnsignedIntegerStrict(argument, offset)) {
    snprintf(reply, capacity, "Error: use morse read [character offset]");
    return;
  }
  const size_t total = radio->morseCaptureLength();
  // The current bounded capture is 4096 characters. Fixed-width page headers
  // reserve their exact space before copying text into a single CLI reply.
  if (total > MorseRx::CaptureCapacity || total > 9999 || offset > total) {
    snprintf(reply, capacity, "Error: capture offset must be 0-%u", unsigned(total));
    return;
  }
  const int prefix = snprintf(reply, capacity, "> %04u/%04u next=---- truncated=%u ",
      unsigned(offset), unsigned(total), unsigned(radio->morseCaptureTruncated()));
  if (prefix < 0 || size_t(prefix) + 1 >= capacity) {
    snprintf(reply, capacity, "Error: reply buffer too small for capture page");
    return;
  }
  const size_t copied = radio->readMorseCapture(offset, reply + prefix, capacity - prefix);
  const size_t next = offset + copied;
  char following[5];
  if (next >= total) memcpy(following, "END ", 5);
  else snprintf(following, sizeof(following), "%04u", unsigned(next));
  char* marker = strstr(reply, "next=----");
  if (marker) memcpy(marker + 5, following, 4);
}

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
inline void formatMorseTracePage(Radio* radio, const char* argument,
                                char* reply, size_t capacity) {
  uint32_t offset = 0;
  if (*argument && !cli::parseUnsignedIntegerStrict(argument, offset)) {
    snprintf(reply, capacity, "Error: use morse trace [retained entry offset]");
    return;
  }
  const size_t length = radio->morseTraceLength();
  if (length > 512 || offset > length) {
    snprintf(reply, capacity, "Error: trace offset must be 0-%u", unsigned(length));
    return;
  }
  // `t` is the absolute total entry count; offset is relative to the retained
  // oldest sample. A changed t between pages identifies a moving HIL window.
  const int prefix = snprintf(reply, capacity, "> %03u/%03u t=%lu n=--- x=%u ",
      unsigned(offset), unsigned(length), (unsigned long)radio->morseTraceTotal(),
      unsigned(radio->morseTraceTruncated()));
  if (prefix < 0 || size_t(prefix) + 1 >= capacity) {
    snprintf(reply, capacity, "Error: reply buffer too small for trace page");
    return;
  }
  size_t used = prefix, next = offset;
  for (unsigned count = 0; count < 8 && next < length; ++count) {
    MorseRssiTraceEntry entry{};
    if (!radio->readMorseTrace(next, entry)) {
      snprintf(reply, capacity, "Error: trace changed; retry from offset 0");
      return;
    }
    char row[32];
    const int bytes = snprintf(row, sizeof(row), "%lu,%d,%u;",
        (unsigned long)entry.millis, int(entry.rssi_dbm), unsigned(entry.flags));
    if (bytes < 0 || size_t(bytes) >= sizeof(row) || used + size_t(bytes) >= capacity) break;
    memcpy(reply + used, row, bytes);
    used += bytes;
    reply[used] = 0;
    ++next;
  }
  if (next == offset && next < length) {
    snprintf(reply, capacity, "Error: reply buffer too small for trace entry");
    return;
  }
  char following[4];
  if (next >= length) memcpy(following, "END", 4);
  else snprintf(following, sizeof(following), "%03u", unsigned(next));
  char* marker = strstr(reply, "n=---");
  if (marker) memcpy(marker + 2, following, 3);
}
#endif
#endif  // MESH_ENABLE_MORSE_RX

// Only explicit commands enter TX/listening. Chat, private messages, captured
// Morse and boot never trigger a transmission. Caller authentication applies.
inline bool handleMorseCommand(Radio* radio, const char* command,
                               char* reply, size_t capacity) {
  if (!command || !reply || !capacity) return false;
  bool query = false, setting = false;
  const char* key = command;
  if (!strncmp(key, "get ", 4)) { query = true; key += 4; }
  else if (!strncmp(key, "set ", 4)) { setting = true; key += 4; }
  const size_t length = strcspn(key, " \t");
  const bool base = length == 5 && !strncmp(key, "morse", 5);
  const bool frequency = length == 10 && !strncmp(key, "morse.freq", 10);
  const bool speed = length == 9 && !strncmp(key, "morse.wpm", 9);
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  const bool hil_timing = length == 16 && !strncmp(key, "morse.hil.timing", 16);
  const bool hil_squelch = length == 17 && !strncmp(key, "morse.hil.squelch", 17);
#endif
  if (!base && !frequency && !speed
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
      && !hil_timing && !hil_squelch
#endif
      ) return false;
  if (!radio || (!radio->supportsMorseTx()
#if MESH_ENABLE_MORSE_RX
      && !radio->supportsMorseRx()
#endif
      )) {
    snprintf(reply, capacity, "Error: Morse unsupported on this radio");
    return true;
  }
  const char* args = cli::skipRecentRepeaterSpaces(key + length);
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  if (hil_squelch) {
#if MESH_ENABLE_MORSE_RX
    if (!radio->supportsMorseRx()) {
      snprintf(reply, capacity, "Error: Morse RX unsupported on this radio");
      return true;
    }
    if (query) {
      if (*args) snprintf(reply, capacity, "Error: unexpected argument");
      else if (isnan(morseHilSquelch())) snprintf(reply, capacity, "> auto; volatile HIL RX only");
      else snprintf(reply, capacity, "> %.3f dBm; volatile HIL RX only", morseHilSquelch());
      return true;
    }
    if (!setting) {
      snprintf(reply, capacity, "Error: use get/set morse.hil.squelch auto|-160..0");
      return true;
    }
    if (radio->isCarrierWaveActive() || radio->isMorseTxActive() || radio->isMorseRxActive()
        || !radio->isInRecvMode() || radio->isReceiving()) {
      snprintf(reply, capacity, "Error: radio busy; HIL squelch changes require idle RX");
      return true;
    }
    float value = NAN;
    if ((strcmp(args, "auto") && (!cli::parseDecimalStrict(args, value)
        || !isfinite(value))) || !setMorseHilSquelch(value)) {
      snprintf(reply, capacity, "Error: use morse.hil.squelch auto or -160..0 dBm");
      return true;
    }
    if (isnan(value)) snprintf(reply, capacity, "OK - HIL Morse squelch auto; volatile RX only");
    else snprintf(reply, capacity, "OK - HIL Morse squelch %.3f dBm; volatile RX only", value);
#else
    snprintf(reply, capacity, "Error: Morse RX unsupported on this radio");
#endif
    return true;
  }
  if (hil_timing) {
    if (query) {
      if (*args) snprintf(reply, capacity, "Error: unexpected argument");
      else {
        const auto& timing = morseHilTiming();
        snprintf(reply, capacity, "> jitter=%u%%; drift=%d%%; extraGap=%u%%; seed=%lu; volatile HIL TX only",
            unsigned(timing.jitter_percent), int(timing.drift_percent),
            unsigned(timing.extra_gap_percent), (unsigned long)timing.seed);
      }
      return true;
    }
    if (!setting) {
      snprintf(reply, capacity, "Error: use get/set morse.hil.timing");
      return true;
    }
    if (radio->isCarrierWaveActive() || radio->isMorseTxActive() || radio->isMorseRxActive()
        || !radio->isInRecvMode() || radio->isReceiving()) {
      snprintf(reply, capacity, "Error: radio busy; HIL timing changes require idle RX");
      return true;
    }
    MorseHilTimingConfig timing;
    if (!parseMorseHilTiming(args, timing) || !setMorseHilTiming(timing)) {
      snprintf(reply, capacity, "Error: use jitter0-20,drift-20..20,extraGap0-50,seed1..4294967295");
      return true;
    }
    snprintf(reply, capacity, "OK - HIL Morse timing %u,%d,%u,%lu; volatile TX only",
        unsigned(timing.jitter_percent), int(timing.drift_percent),
        unsigned(timing.extra_gap_percent), (unsigned long)timing.seed);
    return true;
  }
#endif
  const auto& current = morseSettings();
  if ((query || (base && !*args && !setting)) && !morseSettingsUsable()) {
    snprintf(reply, capacity, "Error: saved Morse settings unavailable; verify and save morse.freq");
    return true;
  }
  if (frequency || speed) {
    if (query) {
      if (*args) snprintf(reply, capacity, "Error: unexpected argument");
      else if (frequency) snprintf(reply, capacity, "> %.3f", current.frequencyMHz());
      else snprintf(reply, capacity, "> %u", unsigned(current.wpm));
      return true;
    }
    if (!setting) {
      snprintf(reply, capacity, "Error: use get/set morse.%s", frequency ? "freq" : "wpm");
      return true;
    }
    if (speed && !morseSettingsUsable()) {
      snprintf(reply, capacity, "Error: verify and save morse.freq before changing Morse WPM");
      return true;
    }
    if (radio->isCarrierWaveActive() || radio->isMorseTxActive()
#if MESH_ENABLE_MORSE_RX
        || radio->isMorseRxActive()
#endif
        ) {
      snprintf(reply, capacity, "Error: radio busy; stop Morse/CW before changing settings");
      return true;
    }
    auto candidate = current;
    if (frequency) {
      float value = 0;
      if (!cli::parseDecimalStrict(args, value)
          || value < MorseMinFrequencyKHz / 1000.0f
          || value > MorseMaxFrequencyKHz / 1000.0f) {
        snprintf(reply, capacity, "Error: morse.freq must be 100-1000 MHz");
        return true;
      }
      candidate.frequency_khz = uint32_t(value * 1000.0f + 0.5f);
    } else {
      uint32_t value = 0;
      if (!cli::parseUnsignedIntegerStrict(args, value)
          || value < MorseMinWpm || value > MorseMaxWpm) {
        snprintf(reply, capacity, "Error: morse.wpm must be %u-%u",
            unsigned(MorseMinWpm), unsigned(MorseMaxWpm));
        return true;
      }
      candidate.wpm = uint8_t(value);
    }
    if (!saveMorseSettings(candidate)) {
      snprintf(reply, capacity, "Error: Morse settings could not be saved");
    } else if (frequency) {
      snprintf(reply, capacity, "OK - morse.freq %.3f MHz", candidate.frequencyMHz());
    } else snprintf(reply, capacity, "OK - morse.wpm %u", unsigned(candidate.wpm));
    return true;
  }
  if ((!*args && !setting)) {
#if MESH_ENABLE_MORSE_RX
    if (radio->isMorseRxActive()) {
      const uint32_t left = radio->morseRxRemainingMillis();
      if (radio->morseRxRecovering()) snprintf(reply, capacity,
          "> Morse RX stopped; packet-radio recovery pending; captured=%u; truncated=%u",
          unsigned(radio->morseCaptureLength()), unsigned(radio->morseCaptureTruncated()));
      else snprintf(reply, capacity,
          "> RX%s %.3f MHz; BW %.2f kHz; %lu.%03lu seconds left; captured=%u; truncated=%u",
          radio->morseRxLearning() ? " learning/keep quiet" : "",
          radio->morseRxFrequency(), radio->morseRxBandwidthKHz(),
          (unsigned long)(left / 1000), (unsigned long)(left % 1000),
          unsigned(radio->morseCaptureLength()), unsigned(radio->morseCaptureTruncated()));
    } else
#endif
    if (radio->isMorseTxActive()) {
      const uint32_t left = radio->morseTxRemainingMillis();
      if (!left) snprintf(reply, capacity, "> RF stop/receive recovery pending; %.3f MHz; TX only",
          radio->morseTxFrequency());
      else snprintf(reply, capacity, "> on; %.3f MHz; %u WPM; %lu.%03lu seconds left; TX only",
          radio->morseTxFrequency(), unsigned(radio->morseTxWpm()),
          (unsigned long)(left / 1000), (unsigned long)(left % 1000));
    }
#if MESH_ENABLE_MORSE_RX
    else if (radio->supportsMorseRx()) snprintf(reply, capacity,
        "> off; %.3f MHz; %u WPM; captured=%u; truncated=%u%s; morse read",
        current.frequencyMHz(), unsigned(current.wpm),
        unsigned(radio->morseCaptureLength()), unsigned(radio->morseCaptureTruncated()),
        radio->morseCaptureTruncated() ? "; capture quota reached; RX ended early" : "");
#endif
    else snprintf(reply, capacity, "> off; %.3f MHz; %u WPM; TX only",
        current.frequencyMHz(), unsigned(current.wpm));
    return true;
  }
  if (query || setting) {
    snprintf(reply, capacity, "%s", morseUsageError());
    return true;
  }
  const size_t action_length = strcspn(args, " \t");
  const char* text = cli::skipRecentRepeaterSpaces(args + action_length);
  const bool stop = action_length == 4 && !strncmp(args, "stop", 4) && !*text;
  const bool send = action_length == 4 && !strncmp(args, "send", 4) && *text;
  const bool listen = action_length == 6 && !strncmp(args, "listen", 6);
  const bool read = action_length == 4 && !strncmp(args, "read", 4);
  const bool clear = action_length == 5 && !strncmp(args, "clear", 5) && !*text;
  const bool stats = action_length == 5 && !strncmp(args, "stats", 5) && !*text;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  const bool trace = action_length == 5 && !strncmp(args, "trace", 5);
#else
  const bool trace = false;
#endif
  if (!stop && !send && !listen && !read && !clear && !stats && !trace) {
    snprintf(reply, capacity, "%s", morseUsageError());
    return true;
  }
  if ((listen || read || clear || stats || trace)
#if MESH_ENABLE_MORSE_RX
      && !radio->supportsMorseRx()
#endif
      ) {
    snprintf(reply, capacity, "Error: Morse RX unsupported on this radio");
    return true;
  }
#if MESH_ENABLE_MORSE_RX
  if (read) {
    formatMorseCapturePage(radio, text, reply, capacity);
    return true;
  }
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  if (trace) {
    formatMorseTracePage(radio, text, reply, capacity);
    return true;
  }
#endif
  if (stats) {
    MorseRxDiagnostics data{};
    if (!radio->morseRxDiagnostics(data)) snprintf(reply, capacity, "> no Morse RX statistics");
    else snprintf(reply, capacity,
        "> samples=%lu; noise=%.1f; min=%.1f; max=%.1f; last=%.1f dBm; unit=%u ms; gap=%lu ms; bad=%u",
        (unsigned long)data.samples, data.noise_dbm, data.minimum_dbm, data.maximum_dbm,
        data.last_dbm, unsigned(data.unit_ms), (unsigned long)data.max_sample_gap_ms,
        unsigned(data.read_errors));
    return true;
  }
  if (clear) {
    if (radio->isMorseRxActive() || radio->isMorseTxActive())
      snprintf(reply, capacity, "Error: stop Morse before clearing capture");
    else { radio->clearMorseCapture(); snprintf(reply, capacity, "OK - Morse capture cleared"); }
    return true;
  }
  if (stop && radio->isMorseRxActive()) {
    const auto result = radio->stopMorseRx();
    if (result == MorseRxResult::Stopped) snprintf(reply, capacity,
        "OK - Morse RX stopped; capture retained%s", radio->isInRecvMode() ? "; receive resumed" : "");
    else snprintf(reply, capacity, "Error: Morse RX stop/receive recovery pending; capture retained");
    return true;
  }
#endif  // MESH_ENABLE_MORSE_RX
  // Do not stop an unrelated CW meter test through the Morse command.
  if (stop && !radio->isMorseTxActive()) {
    snprintf(reply, capacity, "OK - Morse not running");
    return true;
  }
  if ((send || listen) && !morseSettingsUsable()) {
    snprintf(reply, capacity, "Error: saved Morse settings unavailable; verify and save morse.freq");
    return true;
  }
#if MESH_ENABLE_MORSE_RX
  if (listen) {
    float minutes = 0;
    if (!cli::parseDecimalStrict(text, minutes) || minutes <= 0 || minutes > 5) {
      snprintf(reply, capacity, "Error: use morse listen <minutes: 1 second to 5 minutes>");
      return true;
    }
    const uint32_t duration = uint32_t(minutes * 60000.0f + 0.5f);
    if (duration < 1000 || duration > 300000) {
      snprintf(reply, capacity, "Error: Morse listening must last 1-300 seconds");
      return true;
    }
    const auto result = radio->startMorseRx(current.frequencyMHz(), current.wpm, duration);
    switch (result) {
      case MorseRxResult::Started:
        snprintf(reply, capacity, "OK - Morse RX %.3f MHz; BW %.2f kHz; %.2f min; keep first 0.5 s quiet; LoRa paused",
            current.frequencyMHz(), radio->morseRxBandwidthKHz(), minutes);
        break;
      case MorseRxResult::Busy:
        snprintf(reply, capacity, "Error: radio busy; stop Morse/CW or retry when idle"); break;
      case MorseRxResult::Unsupported:
        snprintf(reply, capacity, "Error: Morse RX unsupported on this radio"); break;
      case MorseRxResult::InvalidFrequency:
        snprintf(reply, capacity, "Error: Morse frequency unsupported by this radio"); break;
      case MorseRxResult::Overlap:
        snprintf(reply, capacity, "Error: Morse frequency overlaps radio or radio2; change morse.freq"); break;
      case MorseRxResult::InvalidSpeed:
        snprintf(reply, capacity, "Error: morse.wpm must be %u-%u", unsigned(MorseMinWpm), unsigned(MorseMaxWpm)); break;
      case MorseRxResult::InvalidDuration:
        snprintf(reply, capacity, "Error: Morse listening must last 1-300 seconds"); break;
      default:
        snprintf(reply, capacity, "Error: Morse RX transition failed; check radio recovery"); break;
    }
    return true;
  }
#endif
  if (send && !radio->supportsMorseTx()) {
    snprintf(reply, capacity, "Error: Morse TX unsupported on this radio");
    return true;
  }
  const auto result = stop ? radio->stopMorseTx()
      : radio->startMorseTx(current.frequencyMHz(), current.wpm, text);
  switch (result) {
    case MorseTxResult::Started:
      snprintf(reply, capacity, "OK - Morse TX %.3f MHz at %u WPM; RX paused; use morse stop",
          current.frequencyMHz(), unsigned(current.wpm));
      break;
    case MorseTxResult::Stopped:
      snprintf(reply, capacity, "OK - Morse stopped%s",
          radio->isInRecvMode() ? "; receive resumed" : "");
      break;
    case MorseTxResult::Busy:
      snprintf(reply, capacity, "Error: radio busy; stop Morse/CW or retry when idle");
      break;
    case MorseTxResult::Unsupported:
      snprintf(reply, capacity, "Error: Morse TX unsupported on this radio");
      break;
    case MorseTxResult::InvalidFrequency:
      snprintf(reply, capacity, "Error: Morse frequency unsupported by this radio");
      break;
    case MorseTxResult::Overlap:
      snprintf(reply, capacity, "Error: Morse frequency overlaps radio or radio2; change morse.freq");
      break;
    case MorseTxResult::InvalidText:
      snprintf(reply, capacity, "Error: supported Morse ASCII only (80 characters max)");
      break;
    case MorseTxResult::InvalidSpeed:
      snprintf(reply, capacity, "Error: morse.wpm must be %u-%u", unsigned(MorseMinWpm), unsigned(MorseMaxWpm));
      break;
    case MorseTxResult::TooLong:
      snprintf(reply, capacity, "Error: limit 80 characters/180 seconds; shorten text or raise WPM");
      break;
    default:
      snprintf(reply, capacity, "Error: Morse failed; check radio recovery");
      break;
  }
  return true;
}

}  // namespace mesh
