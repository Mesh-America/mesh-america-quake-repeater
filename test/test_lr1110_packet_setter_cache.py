"""Run LR1110 packet-setter cache regressions against production C++ methods.

RadioLib's SPI operations are mocked; the actual setters, startReceive method
and ownership state are compiled as GNU++11. Linux runs also enable ASAN/UBSAN.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def production_method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class LR1110PacketSetterCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise RuntimeError("A native GNU++11 compiler is required")
        source = (ROOT / "src/helpers/radiolib/CustomLR1110.h").read_text()
        methods = "\n".join(production_method(source, signature) for signature in (
            "int16_t setCRC(", "int16_t implicitHeader(",
            "int16_t explicitHeader(", "int16_t invertIQ(", "int16_t startReceive()",
        ))
        state = (ROOT / "src/helpers/radiolib/LR1110ProfileSwitchState.h").read_text()
        harness = r"""
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string>
@STATE@
#define RADIOLIB_ERR_NONE 0
#define RADIOLIB_LR11X0_RX_TIMEOUT_INF 0xffffff
#define RADIOLIB_LR11X0_IRQ_ALL 0xffffffff
#define RADIOLIB_LR11X0_MAX_PACKET_LENGTH 255
#define RADIOLIB_RADIO_MODE_NONE 0
#define RADIOLIB_IRQ_RX_DEFAULT_FLAGS 1
#define RADIOLIB_IRQ_RX_DEFAULT_MASK 2
#define RADIOLIB_IRQ_PREAMBLE_DETECTED 3
#define RADIOLIB_IRQ_HEADER_ERR 6
struct Module {
  enum { MODE_RX = 1 };
  std::string* trace;
  explicit Module(std::string* value) : trace(value) {}
  void setRfSwitchState(int mode) { assert(mode == MODE_RX); *trace += 'W'; }
};
struct LR1110 {
  LR1110ProfileSwitchState* ownership = nullptr;
  int16_t setterResult = 0, normalResult = 0;
  unsigned setterCalls = 0, normalRxCalls = 0;
  uint8_t crcLength = 0;
  uint32_t crcInitial = 0, crcPolynomial = 0;
  bool crcInverted = false;
  size_t implicitLength = 0, preambleLengthLoRa = 32;
  uint8_t headerType = 0, crcTypeLoRa = 1, invertIQEnabled = 0;
  uint32_t rxTimeout = 0;
  int stagedMode = 7;
  std::string trace;
  Module module;
  Module* mod;
  LR1110() : module(&trace), mod(&module) {}
  void ordinaryWrite(char operation) {
    // Ownership must be revoked before issuing the ordinary RadioLib write.
    assert(ownership && !ownership->canResumeFast() && !ownership->rxValid);
    assert(!ownership->active && !ownership->standbyReady && !ownership->modulationValid);
    ++setterCalls; trace += operation;
  }
  int16_t setCRC(uint8_t len, uint32_t initial, uint32_t polynomial, bool inverted) {
    ordinaryWrite('C'); crcLength = len; crcInitial = initial;
    crcPolynomial = polynomial; crcInverted = inverted; crcTypeLoRa = len;
    return setterResult;
  }
  int16_t implicitHeader(size_t len) {
    ordinaryWrite('I'); implicitLength = len; headerType = 1; return setterResult;
  }
  int16_t explicitHeader() {
    ordinaryWrite('E'); headerType = 0; return setterResult;
  }
  virtual int16_t invertIQ(bool enabled) {
    ordinaryWrite('Q'); invertIQEnabled = enabled; return setterResult;
  }
  virtual int16_t startReceive() { assert(false); return -99; }
  int16_t startReceive(uint32_t timeout, uint32_t flags, uint32_t mask, size_t len) {
    assert(timeout == 0xffffff && flags == (1 | (1UL << 3)) && mask == (2 | (1UL << 6)) && len == 0);
    ++normalRxCalls; trace += 'N'; return normalResult;
  }
  int16_t setPacketParamsLoRa(size_t preamble, uint8_t header, uint8_t len, uint8_t crc, uint8_t iq) {
    assert(preamble == preambleLengthLoRa && header == headerType && len == 255);
    assert(crc == crcTypeLoRa && iq == invertIQEnabled); trace += 'P'; return 0;
  }
  int16_t clearIrqState(uint32_t) { assert(false); return -99; }
  int16_t setRx(uint32_t timeout) { assert(timeout == 0xffffff); trace += 'R'; return 0; }
};
struct Radio : LR1110 {
  uint32_t _activityAt=0;bool _headerSeen=false;
  LR1110ProfileSwitchState _profileSwitch{true};
  bool _profilePacketDirty = true;
  uint32_t _profileFastResumes = 0;
  Radio() { ownership = &_profileSwitch; }
  int16_t snapshotIrqAfterRxExit(uint32_t* irq) { *irq = 0; trace += 'S'; return 0; }
  @METHODS@
};
void acknowledgeFastContext(Radio& radio) {
  auto& state = radio._profileSwitch;
  state.rxResult(0, true);
  state.begin(true, true); state.standbyResult(0);
  state.modulationResult(0, 8, 4, 1, 0);
  assert(state.canResumeFast() && state.matchesModulation(8, 4, 1, 0));
}
void callSetter(Radio& radio, const std::string& which, int16_t expected) {
  int16_t result;
  if (which == "crc") {
    result = radio.setCRC(2, 0x12345678, 0x9abcdef0, false);
    assert(radio.crcLength == 2 && radio.crcInitial == 0x12345678);
    assert(radio.crcPolynomial == 0x9abcdef0 && !radio.crcInverted);
  } else if (which == "implicit") {
    result = radio.implicitHeader(137); assert(radio.implicitLength == 137);
  } else if (which == "explicit") {
    radio.headerType = 1; result = radio.explicitHeader(); assert(radio.headerType == 0);
  } else {
    assert(which == "iq");
    LR1110* polymorphic = &radio;
    result = polymorphic->invertIQ(true); assert(radio.invertIQEnabled);
  }
  assert(result == expected && radio.setterCalls == 1);
  assert(!radio._profileSwitch.canResumeFast() && !radio._profileSwitch.rxValid);
  assert(!radio._profileSwitch.matchesModulation(8, 4, 1, 0));
}
void rebuildNormalRx(Radio& radio) {
  // Even a failed ordinary setter must force the checked normal RX setup.
  radio.trace.clear();
  assert(radio.startReceive() == 0 && radio.trace == "N");
  assert(radio.normalRxCalls == 1 && radio._profileFastResumes == 0);
  assert(radio._profileSwitch.rxValid && !radio._profilePacketDirty);
  radio._profileSwitch.end(true);
  radio._profileSwitch.begin(true, true); radio._profileSwitch.standbyResult(0);
  radio.trace.clear();
  assert(radio.startReceive() == 0 && radio.trace == "SWR");
  assert(radio.normalRxCalls == 1 && radio._profileFastResumes == 1);
}
int main(int argc, char** argv) {
  assert(argc == 2); const std::string which = argv[1];
  if (which == "defaults") {
    Radio radio; acknowledgeFastContext(radio);
    assert(radio.setCRC(2) == 0);
    assert(radio.crcInitial == 0x1d0f && radio.crcPolynomial == 0x1021 && radio.crcInverted);
    return 0;
  }
  for (int failed = 0; failed < 2; ++failed) {
    Radio radio; acknowledgeFastContext(radio);
    radio.setterResult = failed ? -77 : 0;
    callSetter(radio, which, radio.setterResult); rebuildNormalRx(radio);
    Radio retry; acknowledgeFastContext(retry);
    callSetter(retry, which, 0); retry.normalResult = -88; retry.trace.clear();
    assert(retry.startReceive() == -88 && retry.trace == "N");
    assert(!retry._profileSwitch.rxValid && retry._profilePacketDirty);
    retry._profileSwitch.end(false);
    retry._profileSwitch.begin(true, true); retry._profileSwitch.standbyResult(0);
    assert(!retry._profileSwitch.canResumeFast());
    retry.normalResult = 0; retry.normalRxCalls = 0; rebuildNormalRx(retry);
  }
}
"""
        cls.directory = tempfile.TemporaryDirectory(prefix="lr1110-packet-setter-")
        cls.addClassCleanup(cls.directory.cleanup)
        folder = Path(cls.directory.name)
        cpp, cls.binary = folder / "test.cpp", folder / "test.exe"
        cpp.write_text(harness.replace("@STATE@", state.replace("#pragma once", ""))
                       .replace("@METHODS@", methods))
        flags = [] if os.name == "nt" else ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                                           "-fno-pie", "-no-pie"]
        built = subprocess.run([compiler, "-std=gnu++11", "-Wall", "-Wextra", *flags,
                                str(cpp), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=60)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    def run_case(self, scenario):
        ran = subprocess.run([str(self.binary), scenario], capture_output=True, text=True, timeout=10)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_crc_success_failure_and_normal_rx_rebuild(self): self.run_case("crc")
    def test_implicit_header_success_failure_and_normal_rx_rebuild(self): self.run_case("implicit")
    def test_explicit_header_success_failure_and_normal_rx_rebuild(self): self.run_case("explicit")
    def test_virtual_iq_success_failure_and_normal_rx_rebuild(self): self.run_case("iq")
    def test_crc_default_arguments_remain_unchanged(self): self.run_case("defaults")


if __name__ == "__main__":
    unittest.main()
