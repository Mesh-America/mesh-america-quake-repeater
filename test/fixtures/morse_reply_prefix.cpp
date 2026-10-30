struct Callbacks {
  TestRadio* radio;
  mesh::Radio* getProfileRadio() { return radio; }
};
struct PrefixedCLI {
  Callbacks* _callbacks;
  void handle(const char* command, char* reply) { @COMMON_MORSE_CALL@ }
};
int main() {
  TestRadio radio; radio.rx_supported = true;
  radio.capture = std::string(mesh::MorseRx::CaptureCapacity, 'E');
  Callbacks callbacks{&radio}; PrefixedCLI cli{&callbacks};
  char reply[161]; memset(reply, '~', sizeof(reply)); memcpy(reply, "AB:", 3);
  cli.handle("morse read", reply + 3);
  assert(!memcmp(reply, "AB:", 3) && reply[160] == '~');
  assert(memchr(reply + 3, 0, 157));
  unsigned offset = 0, total = 0, next = 0;
  assert(sscanf(reply + 3, "> %u/%u next=%u", &offset, &total, &next) == 3);
  assert(offset == 0 && total == mesh::MorseRx::CaptureCapacity && next > 0 && next < 125);
  assert(strlen(reply) < 160);
}
