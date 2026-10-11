"""Host-only exercise of the actual SX1262 owned protocol/packet staging path."""
from pathlib import Path
import unittest

import test_sx1262_batched_modulation as compiler
from test_radio_receive_contract import method

ROOT = Path(__file__).resolve().parents[1]


class ProtocolBatchingTests(unittest.TestCase):
    compile_run = compiler.BatchedModulationTests.compile_run

    def test_owned_protocol_commit_errors_and_full_setup_fallback(self):
        source = (ROOT / "src/helpers/radiolib/CustomSX1262.h").read_text()
        state = (ROOT / "src/helpers/radiolib/SX1262ProfileSwitchState.h").read_text()
        methods = "\n".join(method(source, signature).replace(" override", "") for signature in (
            "int16_t setCRC(", "int16_t explicitHeader()", "int16_t invertIQ(",
            "int16_t setProfileProtocol(", "int16_t startReceive()"))
        harness = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <string>
@STATE@
#define MC_SX1262_FAST_PACKET_CACHE 1
#define RADIOLIB_ERR_NONE 0
#define RADIOLIB_SX126X_RX_TIMEOUT_INF 0xffffff
#define RADIOLIB_SX126X_PACKET_TYPE_LORA 1
#define RADIOLIB_SX126X_LORA_CRC_ON 1
#define RADIOLIB_SX126X_LORA_HEADER_EXPLICIT 0
#define RADIOLIB_SX126X_LORA_IQ_STANDARD 0
#define RADIOLIB_RADIO_MODE_NONE 0
#define RADIOLIB_IRQ_RX_DEFAULT_FLAGS 1
#define RADIOLIB_IRQ_RX_DEFAULT_MASK 2
#define RADIOLIB_IRQ_PREAMBLE_DETECTED 3
struct Module {
  enum {MODE_RX=1}; std::string* trace;
  void setRfSwitchState(int n) { assert(n==MODE_RX);*trace+='W'; }
};
struct SX1262 {
  std::string trace; char fail=0; bool standbyXOSC=true;
  size_t preambleLengthLoRa=32;
  uint8_t crcTypeLoRa=1, implicitLen=255, headerType=0, invertIQEnabled=0;
  uint8_t physicalSync=0x12, physicalCrc=1, physicalLen=255, physicalHeader=0, physicalIq=0;
  bool iqWorkaroundNormal=true;
  unsigned packetWrites=0, workaroundWrites=0, syncWrites=0;
  uint32_t rxTimeout=0; int stagedMode=3;
  Module module{&trace};Module* getMod() { return &module; }
  int16_t call(char c) { trace+=c;return fail==c ? -100:0; }
  int16_t setSyncWord(uint8_t sync) {
    ++syncWrites;physicalSync=sync;return call('Y');
  }
  // Model the pinned RadioLib setPacketParams() IQ-register workaround as
  // part of the packet commit, including an error before the command itself.
  int16_t setPacketParams(size_t p,uint8_t crc,uint8_t len,uint8_t header,uint8_t iq) {
    assert(p==preambleLengthLoRa);
    ++workaroundWrites;
    if(call('I')) return -100;
    iqWorkaroundNormal=iq==0;
    ++packetWrites;
    if(call('P')) return -100;
    physicalCrc=crc;physicalLen=len;physicalHeader=header;physicalIq=iq;return 0;
  }
  int16_t setCRC(uint8_t crc,uint16_t,uint16_t,bool) {
    if(call('C')) return -100;crcTypeLoRa=crc;
    return setPacketParams(preambleLengthLoRa,crcTypeLoRa,implicitLen,headerType,invertIQEnabled);
  }
  int16_t explicitHeader() {
    if(call('E')) return -100;
    const int rc=setPacketParams(preambleLengthLoRa,crcTypeLoRa,255,0,invertIQEnabled);
    if(!rc) {implicitLen=255;headerType=0;}return rc;
  }
  int16_t invertIQ(bool enabled) {
    if(call('i')) return -100;invertIQEnabled=enabled;
    return setPacketParams(preambleLengthLoRa,crcTypeLoRa,implicitLen,headerType,invertIQEnabled);
  }
  int16_t clearIrqStatus() { return call('c'); }
  int16_t setRx(uint32_t timeout) { assert(timeout==0xffffff);return call('R'); }
  int16_t startReceive(uint32_t,uint32_t,uint32_t,size_t) {
    const int rc=setPacketParams(preambleLengthLoRa,crcTypeLoRa,implicitLen,headerType,invertIQEnabled);
    return rc ? rc:call('F');
  }
  uint8_t getPacketType() { call('Q');return 1; }
};
struct Radio: SX1262 {
  SX1262ProfileSwitchState _profileSwitch{true};
  bool _coldStandby=false;uint32_t _profileFastResumes=0;
  @METHODS@
};
void owned(Radio& r) {
  r._profileSwitch.rxResult(0,true);
  r._profileSwitch.packetResult(0,r.preambleLengthLoRa,r.crcTypeLoRa,r.implicitLen,r.headerType,r.invertIQEnabled);
  r._profileSwitch.begin(true,true);r._profileSwitch.standbyResult(0);
  assert(r._profileSwitch.canResumeFast());r.trace.clear();
}
void restored(Radio& r) {
  r._profileSwitch.end(false);r.fail=0;r.trace.clear();
  assert(r.setProfileProtocol(0x12)==0);
  assert(r.trace=="YCIPEIPiIP");
  assert(r.physicalSync==0x12 && r.physicalCrc==1 && r.physicalLen==255
      && r.physicalHeader==0 && r.physicalIq==0 && r.iqWorkaroundNormal);
  assert(r.startReceive()==0 && r._profileSwitch.rxValid);
}
int main() {
  // Staging itself is sync-only; resume performs exactly one full packet
  // write and one IQ workaround. An acknowledged old tuple cannot skip it.
  for(uint8_t sync:{uint8_t(0x12),uint8_t(0x2b)}) {
    Radio r;owned(r);assert(r.setProfileProtocol(sync)==0 && r.trace=="Y");
    assert(!r._profileSwitch.packetValid && r._profileSwitch.rxValid);
    assert(r.packetWrites==0 && r.workaroundWrites==0);
    assert(r.startReceive()==0 && r.trace=="YcIPWR");
    assert(r.packetWrites==1 && r.workaroundWrites==1 && r.syncWrites==1);
    assert(r._profileSwitch.packetValid && r._profileSwitch.rxValid);
    assert(r.physicalSync==sync && r.iqWorkaroundNormal && r.physicalLen==255);
  }
  // A nonstandard prior tuple is repaired, not merely assumed compatible.
  { Radio r;r.crcTypeLoRa=r.physicalCrc=0;r.implicitLen=r.physicalLen=16;
    r.headerType=r.physicalHeader=1;r.invertIQEnabled=r.physicalIq=1;r.iqWorkaroundNormal=false;
    owned(r);assert(r.setProfileProtocol(0x2b)==0);
    assert(r.physicalCrc==0 && r.physicalHeader==1 && r.physicalIq==1);
    assert(r.startReceive()==0 && r.packetWrites==1 && r.workaroundWrites==1);
    assert(r.physicalCrc==1 && r.physicalHeader==0 && r.physicalIq==0 && r.iqWorkaroundNormal);
  }
  // Setup, partial/busy hops, disabled optimization, and a revoked RX context
  // must execute all normal setters. No staging before acknowledged standby.
  for(int gate=0;gate<5;++gate) {
    Radio r;
    if(gate==1) {r._profileSwitch.rxResult(0,true);r._profileSwitch.begin(true,true);}
    if(gate==2) {owned(r);r._profileSwitch.enabled=false;r._profileSwitch.invalidate();}
    if(gate==3) {owned(r);r._profileSwitch.invalidate();}
    if(gate==4) {r._profileSwitch.rxResult(0,true);r._profileSwitch.begin(false,true);r._profileSwitch.standbyResult(0);}
    r.trace.clear();assert(r.setProfileProtocol(0x2b)==0 && r.trace=="YCIPEIPiIP");
    assert(r.packetWrites==3 && r.workaroundWrites==3 && !r._profileSwitch.packetValid);
  }
  // Sync, IRQ-clear, IQ-workaround, packet, and RX failures all revoke reuse;
  // wrapper rollback can then restore old wire settings through full setup.
  for(char failure:std::string("YcIPR")) {
    Radio r;owned(r);r.fail=failure;
    if(failure=='Y') assert(r.setProfileProtocol(0x2b)==-100);
    else {assert(r.setProfileProtocol(0x2b)==0);assert(r.startReceive()==-100);}
    assert(r._profileSwitch.failed() && !r._profileSwitch.rxValid && !r._profileSwitch.packetValid);
    restored(r);
  }
  // Fallback setup errors propagate; no later setter hides an earlier error.
  for(char failure:std::string("CEi")) {
    Radio r;r.fail=failure;assert(r.setProfileProtocol(0x2b)==-100);
    assert(r.trace.back()==failure && !r._profileSwitch.rxValid);restored(r);
  }
}
'''
        self.compile_run(harness.replace("@STATE@", state).replace("@METHODS@", methods))

    def test_wrapper_uses_batched_protocol_and_pinned_iq_workaround(self):
        wrapper = (ROOT / "src/helpers/radiolib/CustomSX1262Wrapper.h").read_text()
        apply = method(wrapper, "bool applyProtocol(")
        self.assertIn("setProfileProtocol(sync)", apply)
        self.assertNotIn("setCRC(", apply)
        radio = (ROOT / "src/helpers/radiolib/CustomSX1262.h").read_text()
        resume = method(radio, "int16_t startReceive()")
        self.assertIn("rc = setPacketParams(", resume)
        self.assertLess(resume.index("rc = setPacketParams("), resume.index("rc = setRx("))
        # The installed/pinned implementation delegates its required IQ-register
        # repair to setPacketParams. Keep this assumption explicit and tested.
        commands = ROOT / ".pio/libdeps/heltec_v4_2_v4_3_companion_radio_full_femon/RadioLib/src/modules/SX126x/SX126x_commands.cpp"
        if commands.exists():
            packet = method(commands.read_text(), "int16_t SX126x::setPacketParams(")
            self.assertIn("fixInvertedIQ(invertIQ)", packet)
            self.assertLess(packet.index("fixInvertedIQ("), packet.index("SPIwriteStream("))


if __name__ == "__main__":
    unittest.main()
