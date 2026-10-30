#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace mesh { namespace FloodGroupPlainText {

struct Span {
  const uint8_t* data;
  size_t size;
  Span(const uint8_t* bytes = nullptr, size_t length = 0)
      : data(bytes), size(length) {}
};

struct View {
  uint32_t timestamp = 0;
  Span sender;
  Span text;
  bool has_sender = false;
};

// Views borrow the decrypted buffer. Never truncate fields before matching:
// a long display name still needs to match wildcard or content rules.
inline bool parse(const uint8_t* data, size_t size, uint8_t plain_type,
                  View& view) {
  view = View{};
  if (!data || size <= 5 || (data[4] >> 2) != plain_type) return false;
  memcpy(&view.timestamp, data, sizeof(view.timestamp));
  view.text = {data + 5, size - 5};
  // MACThenDecrypt returns complete AES blocks, including zero padding.
  const uint8_t* end = static_cast<const uint8_t*>(
      memchr(view.text.data, 0, view.text.size));
  if (!end) end = data + size;
  view.text.size = size_t(end - view.text.data);
  const uint8_t* colon = static_cast<const uint8_t*>(
      memchr(view.text.data, ':', view.text.size));
  if (!colon) return true;

  size_t sender_size = size_t(colon - view.text.data);
  while (sender_size && view.text.data[sender_size - 1] == ' ') --sender_size;
  bool valid_sender = sender_size != 0;
  for (size_t i = 0; i < sender_size; ++i) {
    if (view.text.data[i] < 0x20) valid_sender = false;
  }
  if (valid_sender) {
    view.sender = {view.text.data, sender_size};
    view.has_sender = true;
  }
  const uint8_t* body = colon + 1;
  if (body < end && *body == ' ') ++body;
  view.text = {body, size_t(end - body)};
  return true;
}

inline bool senderEquals(const View& view, const char* name) {
  if (!view.has_sender || !name) return false;
  const size_t size = strlen(name);
  if (size != view.sender.size) return false;
  for (size_t i = 0; i < size; ++i) {
    uint8_t left = view.sender.data[i];
    uint8_t right = uint8_t(name[i]);
    if (left >= 'A' && left <= 'Z') left += 'a' - 'A';
    if (right >= 'A' && right <= 'Z') right += 'a' - 'A';
    if (left != right) return false;
  }
  return true;
}

} } // namespace mesh::FloodGroupPlainText
