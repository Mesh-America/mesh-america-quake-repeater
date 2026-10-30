#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#define LOW 0
#define HIGH 1
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
void delay(unsigned long ms);
unsigned long micros();
unsigned long millis();
void digitalWrite(int pin, int value);
int digitalRead(int pin);
void pinMode(int pin, int mode);
struct RecordingSerial {
  void begin(unsigned long) {}
  template<class T> void print(const T&) {}
  template<class T> void println(const T&) {}
};
inline RecordingSerial Serial;
