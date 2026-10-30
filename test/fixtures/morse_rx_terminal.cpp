#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <string>

struct Stream {
  std::string output;
  int available_write = 128;
  int input_bytes = 0;
  size_t write_limit = 128;
  unsigned writes = 0;
  int available() const { return input_bytes; }
  int availableForWrite() const { return available_write; }
  size_t write(const uint8_t* data, size_t amount) {
    ++writes;
    const size_t count = std::min(amount, write_limit);
    output.append(reinterpret_cast<const char*>(data), count); return count;
  }
};
namespace mesh {
Stream usb_terminal;
Stream& usbTerminalPort() { return usb_terminal; }
bool hasPendingUsbTerminalOutput() { return false; }
Stream* active_reader_output = nullptr;
bool readerCommandActive(const Stream* output) { return output == active_reader_output; }
}
struct Radio {
  bool receiving = true;
  uint32_t generation = 1;
  std::string capture;
  bool isMorseRxActive() const { return receiving; }
  uint32_t morseCaptureGeneration() const { return generation; }
  size_t morseCaptureLength() const { return capture.size(); }
  size_t readMorseCapture(size_t offset, char* out, size_t capacity) const {
    const size_t count = offset < capture.size() ? std::min(capture.size() - offset, capacity - 1) : 0;
    memcpy(out, capture.data() + std::min(offset, capture.size()), count);
    out[count] = 0; return count;
  }
};
struct Clock { uint32_t now = 100; uint32_t getMillis() const { return now; } };
struct MyMesh {
  Radio radio;
  Radio* _radio = &radio;
  Clock clock;
  Clock* _ms = &clock;
  Stream* _terminal_output = nullptr;
  bool waiting_for_input = false;
  bool _terminal_morse_atomic = true, _terminal_input_editing = false, _terminal_mode = false;
  bool _terminal_login_pending = false, _terminal_trace_pending = false;
  struct Command { bool isPending() const { return false; } } _terminal_command;
  Stream* _morse_terminal_owner = nullptr;
  uint32_t _morse_terminal_generation = 0, _morse_terminal_next_at = 0;
  uint16_t _morse_terminal_offset = 0;
  uint8_t _morse_terminal_pending_chars = 0;
  bool _morse_terminal_was_receiving = false;
  bool hasTerminalOutput() const { return _terminal_output != nullptr; }
  bool isTerminalWaitingForInput() const { return waiting_for_input; }
  void serviceMorseTerminal();
};
@TERMINAL@

static void drain(MyMesh& m) {
  unsigned loops = 0;
  do {
    m.serviceMorseTerminal(); m.clock.now += 250;
    assert(++loops < 1000);
  } while (m._morse_terminal_offset < m.radio.capture.size() || m._morse_terminal_pending_chars);
}
static size_t occurrences(const std::string& haystack, const std::string& needle) {
  size_t count = 0, from = 0;
  while ((from = haystack.find(needle, from)) != std::string::npos) { ++count; from += needle.size(); }
  return count;
}
int main() {
#if COMPANION_FEATURE_READER
  {
    MyMesh m; Stream terminal, other; m._terminal_output = &terminal;
    m.radio.capture = "SOS"; terminal.available_write = 0;
    m.serviceMorseTerminal();
    assert(m._morse_terminal_pending_chars == 3);
    mesh::active_reader_output = &terminal; terminal.available_write = 128;
    m.radio.capture += " HELP";
    for (int i = 0; i < 10; ++i) { m.clock.now += 250; m.serviceMorseTerminal(); }
    assert(terminal.output.empty() && m._morse_terminal_offset == 0);
    assert(m._morse_terminal_pending_chars == 3);
    mesh::active_reader_output = &other; // only the exact output owner blocks progress
    drain(m);
    assert(terminal.output == "\r\n[Morse RX] SOS\r\n> \r\n[Morse RX]  HELP\r\n> ");
    mesh::active_reader_output = nullptr;
  }
#endif
  {
    MyMesh m; Stream terminal, binary;
    m.radio.capture = "SOS";
    m.serviceMorseTerminal();
    assert(terminal.output.empty() && binary.output.empty()); // no fallback or binary frame writes
    m._terminal_output = &terminal;
    terminal.available_write = 0; m.serviceMorseTerminal();
    assert(terminal.output.empty() && m._morse_terminal_pending_chars == 3);
    terminal.available_write = 128;
    drain(m);
    assert(terminal.output == "\r\n[Morse RX] SOS\r\n> " && m._morse_terminal_offset == 3);
    const auto previous = terminal.output;
    for (int i = 0; i < 100; ++i) m.serviceMorseTerminal();
    assert(terminal.output == previous);
    m.radio.capture += " HELP"; m.radio.receiving = false;
    drain(m);
    assert(terminal.output == previous + "\r\n[Morse RX]  HELP\r\n> ");
    assert(binary.output.empty());
  }
  {
    MyMesh m; Stream terminal; m._terminal_output = &terminal;
    m.radio.capture = "HELLO"; drain(m);
    assert(occurrences(terminal.output, "HELLO") == 1);
    m.waiting_for_input = true; m.radio.capture += " WORLD";
    const auto before = terminal.output;
    for (int i = 0; i < 10; ++i) { m.clock.now += 100; m.serviceMorseTerminal(); }
    assert(terminal.output == before && m._morse_terminal_offset == 5);
    m.waiting_for_input = false; drain(m);
    assert(occurrences(terminal.output, "HELLO") == 1 && occurrences(terminal.output, "WORLD") == 1);
  }
  {
    MyMesh m; Stream terminal; m._terminal_output = &terminal;
    terminal.available_write = 0; m.radio.capture = "OLD"; m.serviceMorseTerminal();
    assert(m._morse_terminal_pending_chars == 3);
    ++m.radio.generation; m.radio.capture = "NEW"; terminal.available_write = 128;
    drain(m);
    assert(terminal.output == "\r\n[Morse RX] NEW\r\n> ");
  }
  {
    MyMesh m; Stream first, second; m._terminal_output = &first;
    first.write_limit = 3; m.radio.capture = "SESSION"; m.serviceMorseTerminal();
    const auto partial = first.output;
    assert(partial == "\r\n[");
    assert(!m._terminal_morse_atomic); // a raw stream violating admission fails closed
    m._terminal_output = &second; m._terminal_morse_atomic = true; drain(m);
    assert(first.output == partial && second.output == "\r\n[Morse RX] SESSION\r\n> ");
  }
  {
    MyMesh m; Stream terminal; m._terminal_output = &terminal;
    m.radio.capture = std::string(125, 'E');
    drain(m);
    assert(occurrences(terminal.output, "[Morse RX]") == 3);
    const auto before = terminal.output;
    m._terminal_output = nullptr; m.serviceMorseTerminal();
    assert(terminal.output == before && !m._morse_terminal_owner && !m._morse_terminal_pending_chars);
  }
  {
    MyMesh m; Stream terminal; m._terminal_output = &terminal;
    m.clock.now = 0xfffffff0; m.radio.capture = "E"; drain(m);
    m.radio.capture += "T"; drain(m);
    assert(occurrences(terminal.output, "[Morse RX]") == 2);
  }
}
