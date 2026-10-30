"""Bounded production-RF ESP32 raw RSSI diagnostics, without hardware or PIO."""
from pathlib import Path
import unittest
from test_morse_tx import compile_run, portable_radio_header
from test_morse_hil_production import GOOD_FLAGS
from test_radio_receive_contract import method

ROOT = Path(__file__).resolve().parents[1]
RAW_FLAGS = GOOD_FLAGS + ["-DESP32_PLATFORM", "-DMESH_MORSE_HIL_RAW_RSSI=1"]


class MorseRawRssiTests(unittest.TestCase):
    def test_every_sample_including_arming_candidates_rollover_half_db_and_frozen_overflow(self):
        compile_run(self, r'''
#include <helpers/MorseRx.h>
#include <cassert>
#include <memory>
#include <cstdio>
#include <initializer_list>
int main() {
  using Trace = mesh::MorseRssiTrace;
  static_assert(Trace::Capacity == 30001, "60s shipping-cadence prefix");
  static_assert(sizeof(Trace) < 91000, "raw capture must remain admitted and bounded");
  auto trace = std::unique_ptr<Trace>(new Trace);
  mesh::MorseRx rx; rx.setTrace(trace.get());
  const uint32_t start = 0xfffffff0U;
  assert(rx.start(25, 300000, start) == mesh::MorseRxResult::Started);
  for (uint32_t elapsed = 0; elapsed <= 60000; elapsed += 2) {
    const float rssi = elapsed >= 600 && elapsed < 630 ? -60.5f : (elapsed % 4 ? -110.5f : -110.0f);
    rx.sample(rssi, start + elapsed);
    assert(trace->length() == elapsed / 2 + 1);
  }
  mesh::MorseRxDiagnostics stats; rx.diagnostics(stats);
  assert(stats.samples == trace->total());
  for (size_t index : {size_t(0),size_t(1),size_t(249),size_t(255),size_t(256),size_t(300),size_t(314),size_t(10000),size_t(30000)}) {
    mesh::MorseRssiTraceEntry entry{}; assert(trace->read(index, entry));
    const uint32_t elapsed = uint32_t(index * 2);
    const float expected = elapsed >= 600 && elapsed < 630 ? -60.5f : (elapsed % 4 ? -110.5f : -110.0f);
    assert(entry.millis == elapsed && entry.rssi_dbm == expected);
  }
  rx.sample(-100, start + 60002);
  assert(trace->truncated() && trace->stopReason() == Trace::Window && trace->total() == 30002);
  mesh::MorseRssiTraceEntry retained; assert(trace->read(0, retained) && retained.millis == 0 && retained.rssi_dbm == -110);
  trace->clear(); assert(!trace->length() && !trace->total() && !trace->truncated());
  trace->sample(-127.5f, 0, 0); trace->sample(0, 1, 0);
  assert(trace->read(0, retained) && retained.rssi_dbm == -127.5f);
  assert(trace->read(1, retained) && retained.rssi_dbm == 0);
  trace->sample(-100.25f, 2, 0); assert(trace->stopReason() == Trace::Value && trace->length() == 2);
  trace->clear(); trace->sample(-100, 10, 0); trace->sample(-100, 9, 0);
  assert(trace->stopReason() == Trace::Gap && trace->length() == 1);
  trace->clear();
  for (size_t index = 0; index <= Trace::Capacity; ++index) trace->sample(-100, 0, 0);
  assert(trace->stopReason() == Trace::Full && trace->length() == Trace::Capacity);
  printf("raw trace bytes=%zu; all samples retained or explicitly truncated\n", sizeof(Trace));
}
''', flags=RAW_FLAGS)

    def test_raw_pages_preserve_half_db_timestamps_five_digit_offsets_and_never_stream_during_rx(self):
        first = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        code = first + r'''
#include <memory>
struct RawRadio : TestRadio {
  std::unique_ptr<mesh::MorseRssiTrace> trace{new mesh::MorseRssiTrace};
  size_t morseTraceLength() const override { return trace->length(); }
  uint32_t morseTraceTotal() const override { return trace->total(); }
  bool morseTraceTruncated() const override { return trace->truncated(); }
  bool readMorseTrace(size_t offset, mesh::MorseRssiTraceEntry& out) const override { return trace->read(offset,out); }
};
int main() {
  RawRadio radio; char reply[158];
  for (uint32_t index = 0; index < 15001; ++index) radio.trace->sample(-100.5f,index*2,0);
  radio.rx_active = true;
  mesh::formatMorseTracePage(&radio,"0",reply,157);
  assert(strstr(reply,"stop Morse RX"));
  radio.rx_active = false; memset(reply,'~',sizeof(reply));
  mesh::formatMorseTracePage(&radio,"10000",reply,157);
  assert(reply[157] == '~' && strlen(reply) < 157);
  assert(strstr(reply,"> morse.hil.raw-rssi-v1 10000/15001"));
  assert(strstr(reply,"q=-0.5 20000,201;20002,201;"));
  assert(!strstr(reply,"n=-----"));
  mesh::formatMorseTracePage(&radio,"15000",reply,157);
  assert(strstr(reply,"n=END  ") && strstr(reply,"30000,201;"));
  mesh::formatMorseTracePage(&radio,"15002",reply,157); assert(strstr(reply,"Error:"));
}
'''
        fs = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        compile_run(self, code, flags=RAW_FLAGS + ["-Wno-unused-parameter"], headers={
            "Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs})

    def test_raw_mode_requires_esp32_hil_and_all_shipping_rf_assertions(self):
        fixture = "#include <helpers/MorseRx.h>\nint main() {}\n"
        for missing in ("-DESP32_PLATFORM", "-DMESH_MORSE_HIL_PRODUCTION_RF=1", "-DMESH_MORSE_HIL=1"):
            flags = [flag for flag in RAW_FLAGS if flag != missing]
            with self.subTest(missing=missing), self.assertRaisesRegex(AssertionError, "Raw Morse RSSI requires|Production-equivalent HIL requires"):
                compile_run(self, fixture, flags=flags)
        for flag in ("-DMESH_MORSE_HIL_SAMPLE_INTERVAL_MS=1", "-DMESH_MORSE_HIL_PA_RAMP_US=800"):
            name = flag.split("=",1)[0] + "="
            flags = [item for item in RAW_FLAGS if not item.startswith(name)] + [flag]
            with self.subTest(changed_rf=flag), self.assertRaisesRegex(AssertionError, "Production-equivalent HIL requires"):
                compile_run(self, fixture, flags=flags)
        for window in (29999,60001):
            with self.subTest(window=window), self.assertRaisesRegex(AssertionError,"Raw Morse trace window must be"):
                compile_run(self, fixture, flags=RAW_FLAGS+[f"-DMESH_MORSE_HIL_RAW_WINDOW_MS={window}"])

    def test_shipping_and_default_hil_keep_their_existing_trace_layouts(self):
        compile_run(self, "#include <helpers/MorseRx.h>\nint main(){static_assert(sizeof(mesh::MorseRx)==4172,\"shipping layout unchanged\");}\n")
        compile_run(self, "#include <helpers/MorseRx.h>\nint main(){static_assert(sizeof(mesh::MorseRssiTrace)<2100,\"default HIL stays sparse\");}\n", flags=("-DMESH_MORSE_HIL=1",))
        with self.assertRaisesRegex(AssertionError,"MorseRawRssiTrace"):
            compile_run(self,"#include <helpers/MorseRx.h>\nint main(){mesh::MorseRawRssiTrace trace;}\n")

    def test_actual_lazy_admission_accounts_for_whole_raw_buffer_and_contiguous_allocation(self):
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text(encoding="utf-8")
        code = r'''
#include <helpers/MorseRx.h>
#include <cassert>
static size_t available = 0, largest = 0;
struct { size_t getFreeHeap() const { return available; } } ESP;
constexpr int MALLOC_CAP_8BIT = 1;
size_t heap_caps_get_largest_free_block(int) { return largest; }
struct RadioLibWrapper {
  mesh::MorseRx* _morse_rx = nullptr;
  mesh::MorseRssiTrace* _morse_trace = nullptr;
  bool canAllocateMorseReceiver() const;
};
''' + method(source,"bool RadioLibWrapper::canAllocateMorseReceiver(") + r'''
int main() {
  RadioLibWrapper radio;
  const size_t raw = sizeof(mesh::MorseRssiTrace);
  const size_t required = sizeof(mesh::MorseRx) + raw + 4096;
  assert(raw > 90000);
  available = required - 1; largest = raw; assert(!radio.canAllocateMorseReceiver());
  available = required; largest = raw - 1; assert(!radio.canAllocateMorseReceiver());
  largest = raw; assert(radio.canAllocateMorseReceiver());
  radio._morse_rx = reinterpret_cast<mesh::MorseRx*>(1);
  radio._morse_trace = reinterpret_cast<mesh::MorseRssiTrace*>(1);
  available = 4095; largest = 0; assert(!radio.canAllocateMorseReceiver());
  available = 4096; assert(radio.canAllocateMorseReceiver());
}
'''
        compile_run(self, code, flags=RAW_FLAGS)


if __name__ == "__main__":
    unittest.main()
