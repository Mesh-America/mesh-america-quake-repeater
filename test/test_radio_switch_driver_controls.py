"""Execute production switch-feature masks and conservative modulation paths."""
from pathlib import Path
import unittest

from test_radio_receive_contract import method
import test_sx1262_batched_modulation as compiler


ROOT = Path(__file__).resolve().parents[1]


class RadioSwitchDriverControlsTests(unittest.TestCase):
    compile_run = compiler.BatchedModulationTests.compile_run

    def test_sx1262_compile_opt_outs_cannot_be_enabled_at_runtime(self):
        source = (ROOT / "src/helpers/radiolib/CustomSX1262.h").read_text()
        definitions = source[source.index("#ifndef MC_SX1262_FAST_PROFILE_SWITCH"):
                             source.index("#ifndef SX126X_TX_BUSY_TIMEOUT_MS")]
        methods = "\n".join(method(source, signature) for signature in (
            "uint8_t defaultProfileSwitchFeatures(", "uint8_t profileSwitchCapabilities(",
            "uint8_t getProfileSwitchFeatures(", "void setProfileSwitchFeatures("))
        state = (ROOT / "src/helpers/radiolib/SX1262ProfileSwitchState.h").read_text()
        harness = r'''
#include <cassert>
#include <helpers/RadioSwitchTuning.h>
@OVERRIDES@
@DEFINITIONS@
@STATE@
struct Radio {
  SX1262ProfileSwitchState _profileSwitch{true};
  uint8_t _profileSwitchFeatures=defaultProfileSwitchFeatures();
  @METHODS@
};
int main() {
  Radio r;
  assert(r.profileSwitchCapabilities()==@CAPS@);
  assert(r.getProfileSwitchFeatures()==@CAPS@);
  for(unsigned bits=0;bits<256;++bits) {
    r._profileSwitch.rxResult(0,true);
    r._profileSwitch.begin(true,true);r._profileSwitch.standbyResult(0);
    r._profileSwitch.packetResult(0,32,1,255,0,0);
    r._profileSwitch.modulationResult(0,7,3,1,0);
    r.setProfileSwitchFeatures(uint8_t(bits));
    assert(r.getProfileSwitchFeatures()==(bits & @CAPS@));
    assert(r._profileSwitch.enabled==bool(bits & @CAPS@ & mesh::RadioSwitchTuning::Warm));
    assert(!r._profileSwitch.rxValid && !r._profileSwitch.active
        && !r._profileSwitch.modulationValid && !r._profileSwitch.packetValid);
  }
}
'''
        policies = (
            ("", 63),
            ("#define MC_SX1262_FAST_PROFILE_SWITCH 0", 32),
            ("#define MC_SX1262_FAST_FS 0", 37),
            ("#define MC_SX1262_FAST_PACKET_CACHE 0", 59),
            # The I/O-expander board retains its proven IQ workaround cache.
            ("#define MC_SX1262_FAST_FS 0\n#define MC_SX1262_FAST_PACKET_CACHE 0\n"
             "#define MC_SX1262_FAST_IQ_CACHE 1", 41),
        )
        for overrides, caps in policies:
            with self.subTest(overrides=overrides):
                self.compile_run(harness.replace("@OVERRIDES@", overrides)
                                 .replace("@DEFINITIONS@", definitions)
                                 .replace("@STATE@", state)
                                 .replace("@METHODS@", methods)
                                 .replace("@CAPS@", str(caps)))

    def test_lr1110_compile_opt_out_keeps_all_shortcuts_unavailable(self):
        source = (ROOT / "src/helpers/radiolib/CustomLR1110.h").read_text()
        methods = "\n".join(method(source, signature) for signature in (
            "uint8_t profileSwitchCapabilities(", "uint8_t getProfileSwitchFeatures(",
            "void setProfileSwitchFeatures("))
        state = (ROOT / "src/helpers/radiolib/LR1110ProfileSwitchState.h").read_text()
        harness = r'''
#include <cassert>
#include <helpers/RadioSwitchTuning.h>
#define MC_LR1110_FAST_PROFILE_SWITCH @ENABLED@
@STATE@
struct Radio {
  LR1110ProfileSwitchState _profileSwitch{true};
  uint8_t _profileSwitchFeatures=profileSwitchCapabilities();
  bool _profilePacketDirty=true;
  @METHODS@
};
int main() {
  Radio r;
  assert(r.profileSwitchCapabilities()==@CAPS@);
  for(unsigned bits=0;bits<256;++bits) {
    r._profilePacketDirty=true;r.setProfileSwitchFeatures(uint8_t(bits));
    assert(r.getProfileSwitchFeatures()==(bits & @CAPS@));
    assert(r._profileSwitch.enabled==bool(bits & @CAPS@ & mesh::RadioSwitchTuning::Warm));
    assert(!r._profileSwitch.rxValid && !r._profileSwitch.modulationValid
        && !r._profilePacketDirty);
  }
}
'''
        for enabled in (0, 1):
            with self.subTest(enabled=enabled):
                self.compile_run(harness.replace("@STATE@", state)
                                 .replace("@METHODS@", methods)
                                 .replace("@ENABLED@", str(enabled))
                                 .replace("@CAPS@", "55" if enabled else "0"))

    def test_both_wrappers_execute_normal_setters_when_batch_is_disabled(self):
        harness = r'''
#include <cassert>
#include <string>
#include <helpers/RadioSwitchTuning.h>
#define RADIOLIB_ERR_NONE 0
struct @CHIP@ {
  std::string trace;char failure=0;
  int call(char op) {trace+=op;return failure==op?-7:0;}
  int setLoRaModulationParams(float bw,uint8_t sf,uint8_t cr) {
    assert(bw==62.5f && sf==7 && cr==5);return call('M');
  }
  int setSpreadingFactor(uint8_t sf) {assert(sf==7);return call('S');}
  int setBandwidth(float bw) {assert(bw==62.5f);return call('B');}
  int setCodingRate(uint8_t cr) {assert(cr==5);return call('C');}
};
struct Wrapper {
  @CHIP@ radio;@CHIP@* _radio=&radio;uint8_t features=0;
  uint8_t getDriverSwitchFeatures() const {return features;}
  @METHOD@
};
int main() {
  for(unsigned flags=0;flags<128;++flags) for(char failure:std::string("0MSBC")) {
    Wrapper w;w.features=flags;w.radio.failure=failure;
    const bool batch=flags & mesh::RadioSwitchTuning::Batch;
    assert(w.applyProfileModulation(62.5f,7,5)==(batch ? failure!='M'
        : failure!='S' && failure!='B' && failure!='C'));
    assert(w.radio.trace==(batch ? "M":failure=='S'?"S":failure=='B'?"SB":"SBC"));
  }
}
'''
        for family in ("SX1262", "LR1110"):
            with self.subTest(family=family):
                source = (ROOT / f"src/helpers/radiolib/Custom{family}Wrapper.h").read_text()
                self.compile_run(harness.replace("@CHIP@", f"Custom{family}")
                                 .replace("@METHOD@", method(source, "bool applyProfileModulation(")))


if __name__ == "__main__":
    unittest.main()
