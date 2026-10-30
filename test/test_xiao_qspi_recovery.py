"""Exercise sleeping NOR startup and failed factory-reset recovery natively."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_nrf52_extrafs_contract import function_body


ROOT = Path(__file__).resolve().parents[1]


def method(source, signature):
    start = source.index(signature)
    return source[start:source.index("{", start) + 1] + function_body(source, signature) + "}"


def run_native(source, headers=None):
    with tempfile.TemporaryDirectory(prefix="mesh-xiao-qspi-") as temp:
        work = Path(temp)
        for name, content in (headers or {}).items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="ascii")
        cpp = work / "check.cpp"
        cpp.write_text(source, encoding="ascii")
        binary = work / "check"
        compiled = subprocess.run([
            "c++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            "-fno-pie", "-no-pie", "-I", str(work), "-I", str(ROOT / "src"),
            str(cpp), "-o", str(binary),
        ], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)


GPIO_DECLARATIONS = r"""#pragma once
#include <cstdint>
static constexpr uint8_t NRF_QSPI_PIN_NOT_CONNECTED = 0xFFu;
struct nrf_qspi_pins_t {
  uint8_t sck_pin, csn_pin, io0_pin, io1_pin, io2_pin, io3_pin;
};
enum { NRF_GPIO_PIN_DIR_INPUT, NRF_GPIO_PIN_DIR_OUTPUT,
       NRF_GPIO_PIN_INPUT_DISCONNECT, NRF_GPIO_PIN_NOPULL,
       NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE };
void nrf_gpio_pin_clear(uint32_t);
void nrf_gpio_pin_set(uint32_t);
void nrf_gpio_pin_write(uint32_t, bool);
void nrf_gpio_cfg(uint32_t, int, int, int, int, int);
void delayMicroseconds(uint32_t);
"""

GPIO_RUNTIME = r"""
#define NRF52_PLATFORM 1
#include <cassert>
#include <array>
#include <vector>
#include <helpers/nrf52/QspiFlashWake.h>

// Register-level adapter records pin latches/directions and feeds a sleeping
// serial NOR model only on clock edges. ACTIVATE cannot complete while asleep.
static nrf_qspi_pins_t expected;
static std::array<bool, 48> latch;
static std::array<int, 48> direction;
static std::vector<unsigned> touched;
static std::vector<unsigned> commands;
static unsigned now_us, wake_at, bits, byte;
static bool selected, asleep;
static const std::array<uint8_t, 8> contents = {0x17, 0x81, 0x05, 0x99, 1, 2, 3, 4};
static std::array<uint8_t, 8> flash;

static void reset(const nrf_qspi_pins_t& pins, bool sleeping) {
  expected = pins; latch.fill(false); direction.fill(-1);
  touched.clear(); commands.clear(); now_us = wake_at = bits = byte = 0;
  selected = false; asleep = sleeping; flash = contents;
}

static void check_pin(uint32_t pin) {
  assert(pin < latch.size());
  assert(pin == expected.sck_pin || pin == expected.csn_pin ||
         pin == expected.io0_pin || pin == expected.io1_pin ||
         pin == expected.io2_pin || pin == expected.io3_pin);
  touched.push_back(pin);
}

void nrf_gpio_pin_write(uint32_t pin, bool level) {
  check_pin(pin);
  const bool old = latch[pin];
  latch[pin] = level;
  if (pin == expected.csn_pin && old && !level) {
    assert(!latch[expected.sck_pin]);
    assert(direction[expected.io1_pin] == NRF_GPIO_PIN_DIR_INPUT);
    selected = true; bits = byte = 0;
  }
  if (pin == expected.sck_pin && !old && level && selected) {
    if (expected.io2_pin != NRF_QSPI_PIN_NOT_CONNECTED) {
      assert(latch[expected.io2_pin]);
    }
    if (expected.io3_pin != NRF_QSPI_PIN_NOT_CONNECTED) {
      assert(latch[expected.io3_pin]);
    }
    byte = (byte << 1) | latch[expected.io0_pin];
    ++bits;
  }
  if (pin == expected.csn_pin && !old && level && selected) {
    assert(bits == 8 && byte == 0xAB);
    commands.push_back(byte);
    selected = false; asleep = false; wake_at = now_us;
  }
}
void nrf_gpio_pin_clear(uint32_t pin) { nrf_gpio_pin_write(pin, false); }
void nrf_gpio_pin_set(uint32_t pin) { nrf_gpio_pin_write(pin, true); }
void nrf_gpio_cfg(uint32_t pin, int mode, int, int, int, int) {
  check_pin(pin); direction[pin] = mode;
}
void delayMicroseconds(uint32_t us) { now_us += us; }

static bool activate() {
  return !asleep && !selected && latch[expected.csn_pin] &&
      now_us - wake_at >= mesh::nrf52::QSPI_DPD_WAKE_GUARD_US;
}
static void check_waveform(const nrf_qspi_pins_t& pins, bool sleeping) {
  reset(pins, sleeping);
  assert(!activate());  // The old sleeping-chip path never reaches READY.
  mesh::nrf52::wakeQspiFlashBeforeActivate(pins);
  assert(activate());
  assert(commands == std::vector<unsigned>{0xAB});
  assert(now_us == 76 && bits == 8 && !selected);
  assert(!latch[pins.sck_pin] && latch[pins.csn_pin]);
  assert(direction[pins.io1_pin] == NRF_GPIO_PIN_DIR_INPUT);
  assert(flash == contents);
}

@VARIANT@
static void companion_startup() {
  @STARTUP@
  assert(activate());  // Stands for the first CustomLFS QSPI activation.
}

int main() {
  const nrf_qspi_pins_t xiao = {21, 25, 20, 24, 22, 23};
  check_waveform(xiao, true);
  check_waveform(xiao, false);  // Already awake NOR also accepts harmless AB.
  check_waveform({3, 31, 30, 29, NRF_QSPI_PIN_NOT_CONNECTED,
                  NRF_QSPI_PIN_NOT_CONNECTED}, true);
  reset(xiao, true);
  companion_startup();
  assert(commands == std::vector<unsigned>{0xAB} && flash == contents);
  for (unsigned i = 0; i < 8; ++i) {
    assert(mesh::nrf52::qspiReleaseFromDeepPowerDownBit(i) == ((0xAB >> (7-i)) & 1));
  }
  assert(!mesh::nrf52::qspiReleaseFromDeepPowerDownBit(8));
}
"""


class XiaoQspiRecoveryTest(unittest.TestCase):
    def test_real_gpio_waveform_wakes_nor_before_library_activation(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text()
        begin = main.index("if (!QSPIFlash.begin())")
        block_start = main.rindex("#if defined(XIAO_NRF52)", 0, begin)
        startup = main[block_start:begin]
        self.assertIn("wakeQspiFlashBeforeActivate(qspi_pins)", startup)
        startup = startup[startup.index("const nrf_qspi_pins_t"):startup.index("#endif")]

        variant = (ROOT / "variants/xiao_nrf52/variant.cpp").read_text()
        pin_map = variant[variant.index("g_ADigitalPinMap"):]
        pin_map = pin_map[pin_map.index("{") + 1:pin_map.index("}")]
        pin_map = re.sub(r"//[^\n]*", "", pin_map)
        values = [int(value.strip()) for value in pin_map.split(",") if value.strip()]
        header = (ROOT / "variants/xiao_nrf52/variant.h").read_text()
        declarations = "static const uint32_t g_ADigitalPinMap[] = {" + ",".join(map(str, values)) + "};\n"
        for pin in ("SCK", "CS", "IO0", "IO1", "IO2", "IO3"):
            value = re.search(r"#define PIN_QSPI_" + pin + r"\s+\((\d+)\)", header).group(1)
            declarations += "#define PIN_QSPI_" + pin + " " + value + "\n"
        run_native(GPIO_RUNTIME.replace("@STARTUP@", startup).replace("@VARIANT@", declarations), {
            "Arduino.h": "#pragma once\n#include <cstdint>\nvoid delayMicroseconds(uint32_t);\n",
            "hal/nrf_gpio.h": GPIO_DECLARATIONS,
            "hal/nrf_qspi.h": '#pragma once\n#include "nrf_gpio.h"\n',
        })

    def test_raw_ota_reuses_same_wake_before_activation(self):
        source = (ROOT / "src/helpers/ota/OtaStoreQspiNrf52.cpp").read_text()
        self.assertNotIn("static void wake_qspi_flash_before_activate", source)
        self.assertEqual(source.count("mesh::nrf52::wakeQspiFlashBeforeActivate(pins);"), 2)
        ensure = function_body(source, "bool OtaStoreQspiNrf52::ensureFlash(")
        self.assertLess(ensure.index("wakeQspiFlashBeforeActivate(pins)"),
                        ensure.index("NRF_QSPI_TASK_ACTIVATE"))

    def test_quarantined_qspi_vetoes_erase_before_primary_or_ram_mutation(self):
        store = (ROOT / "examples/companion_radio/DataStore.cpp").read_text()
        implementation = method(store, "bool DataStore::formatFileSystem()")
        run_native(r"""
#include <cassert>
#define NRF52_PLATFORM 1
#define QSPIFLASH 1
#define MESH_CONTACT_CACHE 0
#define MESH_DEBUG_PRINTLN(...) do {} while(0)
struct Fs {
  unsigned formats = 0;
  bool ok = true;
  unsigned retained = 0x1234;
  bool format() { ++formats; if (!ok) return false; retained = 0; return true; }
};
struct DataStore {
  Fs* _fs;
  Fs* _fsExtra;
  Fs* _configuredFsExtra;
  unsigned reset_calls = 0;
  unsigned _contact_recovery = 9;
  bool _contact_load_incomplete = true, _channel_load_incomplete = true;
  bool _identity_creation_blocked = true, _prefs_load_incomplete = true;
  void resetContactPageState() { ++reset_calls; }
  bool formatFileSystem();
};
@IMPLEMENTATION@
int main() {
  Fs primary, extra;
  DataStore store{&primary, nullptr, &extra};
  assert(!store.formatFileSystem());
  assert(primary.formats == 0 && extra.formats == 0 && store.reset_calls == 0);
  assert(primary.retained == 0x1234 && extra.retained == 0x1234);
  assert(store._contact_recovery == 9 && store._contact_load_incomplete);
  assert(store._channel_load_incomplete && store._identity_creation_blocked);
  assert(store._prefs_load_incomplete);

  store._fsExtra = &extra;
  extra.ok = false;
  assert(!store.formatFileSystem());
  assert(primary.formats == 1 && extra.formats == 1 && store.reset_calls == 1);
  assert(store._contact_recovery == 9 && store._contact_load_incomplete);
  extra.ok = true;
  assert(store.formatFileSystem());
  assert(primary.formats == 2 && extra.formats == 2);
  assert(store._contact_recovery == 0 && !store._contact_load_incomplete);
  assert(!store._channel_load_incomplete && !store._identity_creation_blocked);
  assert(!store._prefs_load_incomplete && extra.retained == 0);

  Fs lone_primary;
  DataStore lone{&lone_primary, nullptr, nullptr};
  assert(lone.formatFileSystem() && lone_primary.formats == 1);
}
""".replace("@IMPLEMENTATION@", implementation))

    def test_failed_factory_reset_keeps_services_and_routes_error_to_requester(self):
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        branch = function_body(source, "cmd_frame[0] == CMD_FACTORY_RESET")
        run_native(r"""
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <vector>
#define MESH_ENABLE_TX_BEACONS 1
#define MESH_DEBUG_PRINTLN(...) do {} while(0)
static std::vector<unsigned> events;
static bool beacons_on;
enum { RESP_CODE_OK = 0, RESP_CODE_ERR = 1, ERR_CODE_FILE_IO_ERROR = 5 };
struct BaseSerialInterface {
  std::array<bool, 4> enabled = {true, true, false, false};
  BaseSerialInterface* route = this;
  BaseSerialInterface* received_route = nullptr;
  std::vector<uint8_t> reply;
  BaseSerialInterface* captureReplyRoute() { events.push_back(1); return route; }
  void disable() { events.push_back(3); enabled.fill(false); route = nullptr; }
  void writeFrameToRoute(BaseSerialInterface* target, const uint8_t* p, size_t n) {
    received_route = target; reply.assign(p, p+n); events.push_back(4);
  }
  void writeFrame(const uint8_t* p, size_t n) { writeFrameToRoute(route, p, n); }
};
struct Board { bool rebooted = false; void reboot() { events.push_back(6); rebooted = true; } } board;
static void delay(unsigned ms) { assert(ms == 1000); events.push_back(5); }
struct Store {
  BaseSerialInterface* serial;
  BaseSerialInterface* other;
  std::array<bool, 4> before;
  bool ok;
  bool beacons_before;
  bool formatFileSystem() {
    events.push_back(2);
    assert(serial->enabled == before);  // No disabled transport before erase.
    assert(beacons_on == beacons_before);
    serial->route = other;  // Background route change must not steal failure.
    return ok;
  }
};
struct MyMesh {
  BaseSerialInterface* _serial;
  Store* _store;
  void reset() { @BRANCH@ }
  void suspendBeacons() { events.push_back(7); beacons_on = false; }
  void writeOKFrame(BaseSerialInterface* route = nullptr);
  void writeErrFrame(uint8_t, BaseSerialInterface* route = nullptr);
};
@REPLIES@
int main() {
  for (unsigned mask = 1; mask < 16; ++mask) {
   for (unsigned beacon = 0; beacon < 2; ++beacon) {
    BaseSerialInterface serial, requester, other;
    for (unsigned i = 0; i < 4; ++i) serial.enabled[i] = (mask & (1u << i)) != 0;
    serial.route = &requester;
    beacons_on = beacon != 0;
    Store store{&serial, &other, serial.enabled, false, beacons_on};
    MyMesh mesh{&serial, &store};
    events.clear(); board.rebooted = false;
    mesh.reset();
    assert((events == std::vector<unsigned>{1, 2, 4}));
    assert(serial.enabled == store.before && !board.rebooted);
    assert(beacons_on == store.beacons_before);
    assert(serial.received_route == &requester);
    assert((serial.reply == std::vector<uint8_t>{1, 5}));

    store.ok = true; serial.route = &requester; events.clear();
    mesh.reset();
    assert((events == std::vector<unsigned>{1, 2, 7, 3, 4, 5, 6}));
    assert(board.rebooted);
    assert(!beacons_on);
    for (bool on : serial.enabled) assert(!on);
   }
  }
}
""".replace("@BRANCH@", branch).replace("@REPLIES@", "\n".join(
            method(source, signature) for signature in (
                "void MyMesh::writeOKFrame(", "void MyMesh::writeErrFrame("))))


if __name__ == "__main__":
    unittest.main()
