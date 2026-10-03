#include <Arduino.h>
#include <Adafruit_TinyUSB.h>
#include <helpers/UsbLogging.h>
#include <helpers/UsbLoggingClientActivity.h>
#include <cassert>
#include <cstdio>
#include <functional>
#include <string>

MockSerial Serial;
static bool mounted = true, dtr = true, dfu = false;
static uint32_t baud = 115200;
static std::string fifo, host;
static std::function<void()> during_write;
extern "C" void tud_cdc_line_state_cb(uint8_t, bool, bool);
extern "C" void tud_cdc_line_coding_cb(uint8_t, const cdc_line_coding_t*);
extern "C" void tud_cdc_tx_complete_cb(uint8_t);
extern "C" void tud_umount_cb();
bool tud_mounted() { return mounted; }
bool tud_connect() { mounted = true; return true; }
bool tud_disconnect() { mounted = false; dtr = false; return true; }
bool tud_cdc_n_connected(uint8_t n) { assert(n == 0); return mounted && dtr; }
uint32_t tud_cdc_n_available(uint8_t n) { assert(n == 0); return 0; }
void tud_cdc_n_read_flush(uint8_t n) { assert(n == 0); }
uint32_t tud_cdc_n_write_available(uint8_t n) { assert(n == 0); return 64 - fifo.size(); }
uint32_t tud_cdc_n_write(uint8_t n, const void* data, uint32_t size) {
  assert(n == 0 && size <= 64 - fifo.size());
  if (during_write) {
    auto callback = std::move(during_write);
    during_write = nullptr;
    callback();
  }
  fifo.append(static_cast<const char*>(data), size);
  return size;
}
uint32_t tud_cdc_n_write_flush(uint8_t n) { assert(n == 0); return 0; }
uint32_t tud_cdc_n_write_clear(uint8_t n) { assert(n == 0); fifo.clear(); return 0; }
void tud_cdc_get_line_coding(cdc_line_coding_t* coding) { coding->bit_rate = baud; }
void TinyUSB_Port_EnterDFU() { dfu = true; }

static void service() {
  mesh::serviceUsbLoggingPort();
  mesh::serviceUsbTerminalPort();
  (void)mesh::takeUsbTerminalSessionReset();
  g_mock_millis += 8;
  assert(mesh::tryCompleteUsbTerminalSessionReset());
}
static void drain() {
  for (unsigned i = 0; i < 200; ++i) {
    if (!fifo.empty()) {
      host += fifo;
      fifo.clear();
      tud_cdc_tx_complete_cb(0);
    }
    service(); // Exercise the actual every-loop completion path too.
    if (fifo.empty() && !mesh::hasPendingUsbTerminalOutput()) return;
  }
  assert(false && "finite queue did not drain");
}
int main() {
  static_assert(MESH_USB_CONSOLE_COOPERATIVE, "ordinary native nRF52 must cooperate");
  mesh::setUsbLoggingEnabled(true);
  tud_cdc_line_state_cb(0, true, false);
  service();
  auto& console = mesh::usbConsolePort();
  const std::string reply = "-> " + std::string(200, 'R') + "\r\n";
  assert(console.write(reinterpret_cast<const uint8_t*>(reply.data()), reply.size()) == reply.size());
  assert(mesh::hasPendingUsbTerminalOutput());
  for (unsigned i = 0; i < 5; ++i) service();
  assert(fifo == reply.substr(0, 64)); // Clean epochs must not clear the FIFO.
  assert(mesh::usbLoggingPort().write(reinterpret_cast<const uint8_t*>("LOG\r\n"), 5) == 5);
  mesh::probeUsbLoggingTransport();
  drain();
  assert(host == reply + "LOG\r\n[USB watchdog] heartbeat\r\n");
  host.clear();
  const std::string raw = "RAW: " + std::string(512, 'A') + "\r\n";
  assert(mesh::usbLoggingPort().write(reinterpret_cast<const uint8_t*>(raw.data()), raw.size()) == raw.size());
  drain();
  assert(host == raw); // Shared-queue capacity must not drop >256-byte RAW.
  host.clear();
  uint8_t stale_printf[256];
  std::fill(stale_printf, stale_printf + 255, 'Z');
  stale_printf[255] = 0;
  assert(mesh::usbLoggingPort().write(stale_printf, 512) == 0); // No OOB read.
  during_write = [] {
    dtr = false;
    tud_cdc_line_state_cb(0, false, false);
    dtr = true;
    tud_cdc_line_state_cb(0, true, false);
    (void)mesh::takeUsbTerminalSessionReset();
    g_mock_millis += 8;
    // The old producer still owns the buffer and native writer gate.
    assert(!mesh::tryCompleteUsbTerminalSessionReset());
  };
  assert(console.write(reinterpret_cast<const uint8_t*>(reply.data()), reply.size()) == reply.size());
  service();
  drain();
  assert(host.empty()); // Failed busy purge must be retried before reopening.
  // A DTR-high host that stops reading never forces a retry/flush wait.
  fifo.assign(64, 'X');
  const std::string record(100, 'D');
  for (unsigned i = 0; i < 100; ++i)
    mesh::usbLoggingPort().write(reinterpret_cast<const uint8_t*>(record.data()), record.size());
  assert(console.availableForWrite() >= 3072 && mesh::canAcceptUsbConsoleCommand());
  const std::string huge(4096, 'F');
  assert(console.write(reinterpret_cast<const uint8_t*>(huge.data()), huge.size()) == 0);
  for (unsigned i = 0; i < 10000; ++i) mesh::serviceUsbTerminalPort();
  assert(fifo.size() == 64); // No progress invented by queue admission.
  assert(mesh::observeUsbLoggingTransport().pending);
  mesh::noteUsbLoggingStatsCommand("stats-core");
  assert(mesh::isUsbLoggingClientActive());
  dtr = false;
  tud_cdc_line_state_cb(0, false, false);
  dtr = true;
  tud_cdc_line_state_cb(0, true, false);
  service();
  assert(!mesh::isUsbLoggingClientActive() && !mesh::hasPendingUsbTerminalOutput());
  drain();
  assert(host.empty()); // No old response/log leaks across rapid reopen.
  mesh::noteUsbLoggingStatsCommand("stats-radio");
  mounted = false;
  tud_umount_cb();
  assert(!mesh::isUsbLoggingClientActive());
  mounted = true; dtr = true;
  tud_cdc_line_state_cb(0, true, false);
  service();
  baud = 1200; dtr = false;
  tud_cdc_line_state_cb(0, false, false);
  assert(dfu); // Existing bootloader entry is preserved.
  puts("native nRF52 console transport passed");
}
