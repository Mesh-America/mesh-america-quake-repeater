#pragma once
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

// Models Adafruit's bounded printf so a long verse sent via printf is caught.
class Stream {
public:
  std::string text;
  size_t max_write = 65535;
  size_t credit = 65535;
  size_t writes = 0;
  size_t write(const uint8_t* value, size_t size) {
    ++writes;
    if (size > max_write) size = max_write;
    if (size > credit) size = credit;
    credit -= size;
    text.append(reinterpret_cast<const char*>(value), size);
    return size;
  }
  size_t print(const char* value) {
    return write(reinterpret_cast<const uint8_t*>(value), std::strlen(value));
  }
  size_t printf(const char* format, ...) {
    char buf[256];
    va_list args;
    va_start(args, format);
    vsnprintf(buf, sizeof(buf), format, args);
    va_end(args);
    return print(buf);
  }
};
