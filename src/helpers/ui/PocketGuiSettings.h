#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace mesh {
namespace ui {
namespace pocket {

constexpr uint8_t MAP_ZOOM_AUTO = 9;

// Store an explicit wire record rather than compiler-specific structure padding.
struct Settings {
  uint8_t channel = 0;
  uint8_t text_large = 0;
  uint8_t name_len = 1;
  uint8_t flip = 0;
  uint8_t dark = 0;
  uint8_t idle = 1;
  uint8_t refresh = 3;
  uint8_t map_zoom = MAP_ZOOM_AUTO;
};

constexpr size_t SETTINGS_RECORD_SIZE = 13;
constexpr unsigned SETTINGS_COUNT = 8;

inline bool settingsValid(const Settings& value, unsigned channel_count = 40) {
  return channel_count != 0 && channel_count <= 256 && value.channel < channel_count
      && value.text_large <= 1 && value.name_len <= 3
      && value.flip <= 1 && value.dark <= 1
      && value.idle <= 3 && value.refresh <= 3 && value.map_zoom <= MAP_ZOOM_AUTO;
}

inline uint16_t settingsChecksum(const uint8_t* bytes, size_t length) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < length; ++i) {
    crc ^= (uint16_t)bytes[i] << 8;
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = crc & 0x8000 ? (uint16_t)((crc << 1) ^ 0x1021)
                         : (uint16_t)(crc << 1);
  }
  return crc;
}

inline bool encodeSettings(const Settings& value, uint8_t* bytes, size_t size,
                           unsigned channel_count = 40) {
  if (bytes == nullptr || size != SETTINGS_RECORD_SIZE || !settingsValid(value, channel_count)) return false;
  bytes[0] = 'P'; bytes[1] = 'G'; bytes[2] = 3;
  bytes[3] = value.channel;
  bytes[4] = value.text_large;
  bytes[5] = value.name_len;
  bytes[6] = value.flip | (value.dark << 1);
  bytes[7] = value.idle;
  bytes[8] = value.refresh;
  bytes[9] = value.map_zoom;
  bytes[10] = 0;
  const uint16_t crc = settingsChecksum(bytes, 11);
  bytes[11] = (uint8_t)crc;
  bytes[12] = (uint8_t)(crc >> 8);
  return true;
}

inline bool decodeSettings(Settings& value, const uint8_t* bytes, size_t size,
                           unsigned channel_count = 40) {
  if (bytes == nullptr || size != SETTINGS_RECORD_SIZE
      || bytes[0] != 'P' || bytes[1] != 'G' || bytes[2] < 1 || bytes[2] > 3
      || (bytes[6] & ~3U) != 0 || bytes[10] != 0
      || (bytes[2] < 3 && bytes[9] > 8)
      || settingsChecksum(bytes, 11) != (uint16_t)(bytes[11] | (uint16_t)bytes[12] << 8)) return false;
  Settings next;
  next.channel = bytes[3]; next.text_large = bytes[4]; next.name_len = bytes[5];
  next.flip = bytes[6] & 1; next.dark = (bytes[6] >> 1) & 1;
  next.idle = bytes[7]; next.refresh = bytes[8]; next.map_zoom = bytes[9];
  if (!settingsValid(next, channel_count)) return false;
  // Older choices were 10/30/60/manual. Keep their other preferences while
  // applying the Pocket panel's ten-partial-update cleanup limit.
  if (bytes[2] == 1) next.refresh = 3;
  value = next;
  return true;
}

inline uint32_t idleMillis(const Settings& value) {
  static const uint32_t values[] = {30000, 60000, 300000, 0};
  return values[value.idle <= 3 ? value.idle : 1];
}

inline int refreshCount(const Settings& value) {
  static const int values[] = {1, 3, 5, 10};
  return values[value.refresh <= 3 ? value.refresh : 3];
}

inline unsigned nameCharacters(const Settings& value) {
  static const uint8_t values[] = {3, 5, 8, 0};
  return values[value.name_len <= 3 ? value.name_len : 1];
}

inline uint8_t mapZoomIndex(const Settings& value, bool located = true) {
  // A local range has no useful center until a node location is available.
  if (!located) return 0;
  return value.map_zoom < MAP_ZOOM_AUTO ? value.map_zoom : 3;
}

inline double mapHeightKm(const Settings& value, bool located = true) {
  static const uint16_t values[] = {20000, 5000, 1000, 200, 100, 50, 20, 10, 5};
  return values[mapZoomIndex(value, located)];
}

inline bool zoomMap(Settings& value, bool closer, bool located) {
  if (!located) return false;
  const uint8_t index = mapZoomIndex(value, located);
  if ((closer && index == 8) || (!closer && index == 0)) return false;
  value.map_zoom = closer ? index + 1 : index - 1;
  return true;
}

inline bool cycleSetting(Settings& value, unsigned row, unsigned channel_count = 40) {
  switch (row) {
    case 0:
      if (channel_count == 0 || channel_count > 256) return false;
      value.channel = (uint8_t)((value.channel + 1U) % channel_count); break;
    case 1: value.text_large = !value.text_large; break;
    case 2: value.name_len = (value.name_len + 1) % 4; break;
    case 3: value.flip = !value.flip; break;
    case 4: value.dark = !value.dark; break;
    case 5: value.idle = (value.idle + 1) % 4; break;
    case 6: value.refresh = (value.refresh + 1) % 4; break;
    case 7: value.map_zoom = (value.map_zoom + 1) % (MAP_ZOOM_AUTO + 1); break;
    default: return false;
  }
  return true;
}

struct BoardState {
  unsigned scroll = 0;
  void clamp(unsigned count) { if (scroll >= count) scroll = count == 0 ? 0 : count - 1; }
  bool scrollOlder(unsigned count) {
    clamp(count);
    if (count == 0 || scroll + 1 >= count) return false;
    ++scroll;
    return true;
  }
  bool scrollNewer() {
    if (scroll == 0) return false;
    --scroll;
    return true;
  }
  void messageAdded() { if (scroll != 0 && scroll < 31) ++scroll; }
};

inline uint32_t messageAgeSeconds(uint64_t now_millis, uint64_t heard_millis) {
  // MeshPocket uses Arduino's 32-bit millis(), widened in shared history.
  return (uint32_t)((uint32_t)now_millis - (uint32_t)heard_millis) / 1000;
}

// Never leave a partial UTF-8 character at the end of a displayed name.
inline size_t nextUtf8Character(const char* value, size_t offset, size_t length) {
  if (offset >= length) return length;
  const uint8_t lead = (uint8_t)value[offset];
  size_t count = lead < 0x80 ? 1 : lead >= 0xC2 && lead <= 0xDF ? 2
      : lead >= 0xE0 && lead <= 0xEF ? 3 : lead >= 0xF0 && lead <= 0xF4 ? 4 : 1;
  if (count > length - offset) return offset + 1;
  for (size_t i = 1; i < count; ++i)
    if (((uint8_t)value[offset + i] & 0xC0) != 0x80) return offset + 1;
  return offset + count;
}

inline void truncateCharacters(char* text, unsigned count) {
  if (text == nullptr || count == 0) return;
  const size_t length = strlen(text);
  size_t position = 0;
  for (unsigned i = 0; i < count && position < length; ++i)
    position = nextUtf8Character(text, position, length);
  text[position] = 0;
}

// The compact fonts include Latin-1. Replace unsupported code points without
// splitting UTF-8 or reading beyond the supplied input length.
inline void sanitizeText(char* output, size_t capacity, const char* input, size_t length) {
  if (output == nullptr || capacity == 0) return;
  size_t source = 0, destination = 0;
  if (input != nullptr) while (source < length && input[source] != 0) {
    const uint8_t lead = (uint8_t)input[source];
    const size_t next = nextUtf8Character(input, source, length);
    const size_t bytes = next - source;
    if (lead < 0x80) {
      if (destination + 1 >= capacity) break;
      output[destination++] = lead < 0x20 || lead == 0x7F ? ' ' : (char)lead;
    } else if (bytes == 2 && lead == 0xC2 && (uint8_t)input[source + 1] < 0xA0) {
      if (destination + 1 >= capacity) break;
      output[destination++] = ' ';
    } else if (bytes == 2 && (lead == 0xC2 || lead == 0xC3)) {
      if (destination + 2 >= capacity) break;
      output[destination++] = input[source];
      output[destination++] = input[source + 1];
    } else {
      if (destination + 1 >= capacity) break;
      output[destination++] = '*';
    }
    source = next;
  }
  output[destination] = 0;
}

struct BoardMessageView {
  const char* sender;
  size_t sender_length;
  const char* text;
};

inline void parseBoardMessage(const char* origin, const char* body, bool own_sent,
                              BoardMessageView& result) {
  result.sender = origin == nullptr ? "" : origin;
  result.sender_length = strlen(result.sender);
  result.text = body == nullptr ? "" : body;
  if (!own_sent) {
    const char* separator = strstr(result.text, ": ");
    if (separator != nullptr && separator != result.text
        && (size_t)(separator - result.text) <= 61) {
      result.sender = result.text;
      result.sender_length = (size_t)(separator - result.text);
      result.text = separator + 2;
    } else {
      // The old preview's origin includes a route suffix, never show it as a name.
      const char* route = strstr(result.sender, " [");
      if (route != nullptr) result.sender_length = (size_t)(route - result.sender);
    }
  }
}

}  // namespace pocket
}  // namespace ui
}  // namespace mesh
