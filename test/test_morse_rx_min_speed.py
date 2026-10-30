"""Enforce the requested 15 WPM RX floor while retaining slower transmit."""
from pathlib import Path
import unittest
from test_morse_tx import compile_run, portable_radio_header

ROOT = Path(__file__).resolve().parents[1]


class MorseRxMinimumSpeedTests(unittest.TestCase):
    def test_rx_floor_rejects_every_slow_speed_without_changing_tx_or_settings(self):
        first = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        code = first + r'''
int main() {
  static_assert(mesh::MorseRx::MinWpm == 15, "receive floor must remain explicit");
  TestRadio radio; radio.rx_supported = true;
  char reply[160];
  for (uint8_t speed = 0; speed < 15; ++speed) {
    mesh::MorseRx receiver;
    assert(receiver.start(speed, 1000, 0) == mesh::MorseRxResult::InvalidSpeed);
    assert(!receiver.active());
    if (!speed) continue;
    mesh::MorseTx transmitter;
    assert(transmitter.start("E", speed, 0) == mesh::MorseTxResult::Started);
    const auto setting = std::string("set morse.wpm ") + std::to_string(speed);
    assert(mesh::handleMorseCommand(&radio, setting.c_str(), reply, sizeof(reply)));
    assert(mesh::morseSettings().wpm == speed);
    radio.capture = "RETAIN";
    assert(mesh::handleMorseCommand(&radio, "morse listen 1", reply, sizeof(reply)));
    assert(std::string(reply) == "Error: Morse RX needs 15-60 WPM; set morse.wpm");
    assert(!radio.rx_active && radio.capture == "RETAIN" && mesh::morseSettings().wpm == speed);
    mesh::MorseReplyHandoff handoff; uint8_t actor[32] = {1}; handoff.beginCommand(actor);
    assert(!mesh::handleMorseReplyCommand(handoff, &radio, "morse listen 1", reply, sizeof(reply), 0));
    assert(!handoff.pending() && !radio.rx_active);
  }
  assert(mesh::MorseRx::validate(15, 1000) == mesh::MorseRxResult::Started);
  assert(mesh::handleMorseCommand(&radio, "set morse.wpm 15", reply, sizeof(reply)));
  assert(mesh::handleMorseCommand(&radio, "morse listen 1", reply, sizeof(reply)));
  assert(radio.rx_active && radio.speed == 15);
  assert(strstr(mesh::morseUsageError(), "RX >=15 WPM"));
}
'''
        fs = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        compile_run(self, code, flags=("-Wno-unused-parameter",), headers={
            "Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs})


if __name__ == "__main__":
    unittest.main()
