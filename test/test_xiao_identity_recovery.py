"""Execute XIAO's actual target source with a radio that forbids absent I/O."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

IDENTITY = r"""#pragma once
#include <cstddef>
#include <cstdint>
namespace mesh {
struct RNG { virtual ~RNG() = default; virtual void random(uint8_t*, size_t) = 0; };
struct Identity { uint8_t pub_key[32] = {}; };
struct LocalIdentity : Identity {
  LocalIdentity() = default;
  explicit LocalIdentity(RNG* rng) { rng->random(pub_key, sizeof(pub_key)); }
};
}
"""

TARGET = r"""#pragma once
#include <helpers/IdentityGeneration.h>
#include <helpers/NRF52Crypto.h>
#include <cassert>
#include <memory>
#include <stdexcept>
int SPI, Wire;
unsigned radio_bytes, prng_bytes, crypto_calls, progress_calls, init_calls, rtc_calls;
long random(long minimum, long maximum) {
  assert(minimum == 0 && maximum == 256); ++prng_bytes; return 0x3c;
}
class PhysicalLayer {
public:
  bool available = false;
  uint8_t randomByte() {
    if (!available) throw std::logic_error("absent radio I/O");
    ++radio_bytes; return 0x5a;
  }
};
@RADIO_NOISE_LISTENER@
struct Module { Module(int, int, int, int, int&) {} };
struct FakeRadio : PhysicalLayer {
  std::unique_ptr<Module> module;
  bool next_result = false;
  FakeRadio(Module* m) : module(m) {}
  bool std_init(int* spi) {
    assert(spi == &SPI); ++init_calls; available = next_result; return next_result;
  }
};
struct XiaoNrf52Board {};
struct FakeWrapper { FakeWrapper(FakeRadio&, XiaoNrf52Board&) {} };
struct VolatileRTCClock {};
struct AutoDiscoverRTCClock {
  AutoDiscoverRTCClock(VolatileRTCClock&) {}
  void begin(int& wire) { assert(&wire == &Wire); ++rtc_calls; }
};
struct EnvironmentSensorManager {};
#define RADIO_CLASS FakeRadio
#define WRAPPER_CLASS FakeWrapper
#define P_LORA_NSS 4
#define P_LORA_DIO_1 1
#define P_LORA_RESET 2
#define P_LORA_BUSY 3
"""

HARNESS = r"""
#include "target.cpp"
#ifdef USE_CC310_HW_CRYPTO
namespace mesh {
void mixCC310Random(uint8_t* dest, size_t size) {
  ++crypto_calls;
  for (size_t i = 0; i < size; ++i) dest[i] ^= 0xa5;
}
}
#endif
static void progress(void*) { ++progress_calls; }
static void freshIdentity(bool radio_ready) {
  radio_bytes = prng_bytes = crypto_calls = progress_calls = 0;
  mesh::LocalIdentity identity;
  mesh::ScopedIdentityGenerationProgress hook(progress, nullptr);
  assert(mesh::generateUsableLocalIdentity(identity, radio_new_identity));
  assert(prng_bytes == 32 && radio_bytes == (radio_ready ? 32u : 0u));
  assert(progress_calls == 34); // Before/after generation plus every RNG byte.
  uint8_t expected = radio_ready ? 0x66 : 0x3c;
#ifdef USE_CC310_HW_CRYPTO
  expected ^= 0xa5;
  assert(crypto_calls == 1);
#else
  assert(crypto_calls == 0);
#endif
  for (uint8_t value : identity.pub_key) assert(value == expected);
}
int main() {
  freshIdentity(false); // No successful initialization has occurred yet.
  radio.next_result = true; assert(radio_init()); freshIdentity(true);
  radio.next_result = false; assert(!radio_init()); freshIdentity(false);
  radio.next_result = true; assert(radio_init()); freshIdentity(true);
  assert(init_calls == 3);
#ifdef DISABLE_I2C_RTC_SCAN
  assert(rtc_calls == 0);
#else
  assert(rtc_calls == 3);
#endif
}
"""


class XiaoIdentityRecoveryTests(unittest.TestCase):
    def test_absent_ready_failed_and_recovered_with_both_crypto_configs(self):
        compiler = os.environ.get("CXX") or shutil.which("c++")
        self.assertIsNotNone(compiler)
        wrappers = (ROOT / "src/helpers/radiolib/RadioLibWrappers.h").read_text()
        start = wrappers.index("class RadioNoiseListener :")
        listener = wrappers[start:wrappers.index("\n};", start) + 3]
        for crypto in (False, True):
            for rtc_scan in (False, True):
                with self.subTest(crypto=crypto, rtc_scan=rtc_scan), tempfile.TemporaryDirectory(prefix="xiao-identity-") as temp:
                    work = Path(temp)
                    (work / "helpers").mkdir()
                    (work / "Arduino.h").write_text("#pragma once\n", encoding="ascii")
                    (work / "Identity.h").write_text(IDENTITY, encoding="ascii")
                    (work / "helpers/ArduinoHelpers.h").write_text("#pragma once\n", encoding="ascii")
                    (work / "target.h").write_text(TARGET.replace("@RADIO_NOISE_LISTENER@", listener), encoding="ascii")
                    (work / "target.cpp").write_bytes((ROOT / "variants/xiao_nrf52/target.cpp").read_bytes())
                    (work / "check.cpp").write_text(HARNESS, encoding="ascii")
                    flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(work), "-I", str(ROOT / "src")]
                    if os.name != "nt":
                        flags += ["-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
                    if crypto:
                        flags += ["-DUSE_CC310_HW_CRYPTO=1"]
                    if not rtc_scan:
                        flags += ["-DDISABLE_I2C_RTC_SCAN=1"]
                    binary = work / "check"
                    built = subprocess.run([compiler, *flags, str(work / "check.cpp"), "-o", str(binary)], capture_output=True, text=True)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
