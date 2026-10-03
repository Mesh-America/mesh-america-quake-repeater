#include <algorithm>
#include <cassert>
#include <iostream>
#include <string>
#include "helpers/UsbLogging.h"
#include "helpers/UsbLoggingClientActivity.h"
#include "MeshCore.h"
#include "helpers/SerialPacketLog.h"

MockSerial Serial;
static bool connected = true;
static bool mounted = true;
static unsigned disconnect_calls = 0;
static unsigned connect_calls = 0;
static bool auto_drain = false;
static std::string fifo;
static std::string host;
static unsigned write_calls = 0;
static unsigned flush_calls = 0;
static unsigned clear_calls = 0;
static void (*during_write)() = nullptr;

bool tud_mounted() { return mounted; }
bool tud_disconnect() { ++disconnect_calls; mounted = false; connected = false; return true; }
bool tud_connect() { ++connect_calls; return true; }

bool tud_cdc_n_connected(uint8_t instance) {
  assert(!mock_isr);
  assert(instance == 0);
  return connected;
}
uint32_t tud_cdc_n_write_available(uint8_t instance) {
  assert(!mock_isr);
  assert(instance == 0);
  return 64 - fifo.size();
}
uint32_t tud_cdc_n_write(uint8_t instance, const void* data, uint32_t size) {
  assert(!mock_isr);
  assert(instance == 0);
  assert(size <= 64 - fifo.size());
  ++write_calls;
  if (during_write) during_write();
  fifo.append(static_cast<const char*>(data), size);
  return size;
}
uint32_t tud_cdc_n_write_flush(uint8_t instance) {
  assert(!mock_isr);
  assert(instance == 0);
  ++flush_calls;
  if (!auto_drain) return 0;
  const auto size = fifo.size();
  host += fifo;
  fifo.clear();
  return size;
}
bool tud_cdc_n_write_clear(uint8_t instance) {
  assert(!mock_isr);
  assert(instance == 0);
  ++clear_calls;
  fifo.clear();
  return true;
}

static size_t put(Stream& port, const std::string& value) {
  return port.write(reinterpret_cast<const uint8_t*>(value.data()), value.size());
}

#if MESH_ESP32_TINYUSB_NONBLOCKING
static void drain_all() {
  for (unsigned turn = 0; turn != 200; ++turn) {
    host += fifo;
    fifo.clear();
    mesh::serviceUsbTerminalPort();
    if (fifo.empty() && !mesh::hasPendingUsbTerminalOutput()) return;
  }
  assert(false && "finite queue should drain in bounded service calls");
}

static void fresh_session() {
  connected = false;
  arduino_usb_cdc_event_data_t event;
  event.line_state.dtr = false;
  Serial.callback(nullptr, nullptr, ARDUINO_USB_CDC_LINE_STATE_EVENT, &event);
  connected = true;  // fast close/reopen, without an intervening service poll
  mesh::serviceUsbLoggingPort();
  assert(mesh::takeUsbTerminalSessionReset());
  assert(!mesh::takeUsbTerminalSessionReset());
  assert(mesh::tryCompleteUsbTerminalSessionReset());
  fifo.clear();
  host.clear();
  auto_drain = false;
}

static void check_logging_watchdog_transport_observations_and_recovery() {
  fresh_session();
  mesh::setUsbLoggingEnabled(true);
  const auto initial = mesh::observeUsbLoggingTransport();
  assert(initial.supported && initial.host_connected && initial.reader_connected);
  assert(!initial.pending);
  assert(!mesh::isUsbLoggingClientActive()); // An open CDC is not an app poll.
  mesh::noteUsbLoggingStatsCommand("stats-core");
  assert(mesh::isUsbLoggingClientActive());
  fresh_session(); // Even a close/reopen between service calls revokes it.
  assert(!mesh::isUsbLoggingClientActive());
  mesh::noteUsbLoggingStatsCommand("stats-radio");
  mesh::setUsbLoggingEnabled(false);
  assert(!mesh::isUsbLoggingClientActive());
  mesh::setUsbLoggingEnabled(true);
  mesh::probeUsbLoggingTransport();
  const auto queued = mesh::observeUsbLoggingTransport();
  assert(queued.pending && queued.tx_progress == initial.tx_progress);
  assert(mesh::recoverUsbLoggingTransport(1) == mesh::UsbLoggingRecoveryResult::Attempted);
  // Purge and probe merely change queues; neither is host acknowledgement.
  assert(mesh::observeUsbLoggingTransport().tx_progress == initial.tx_progress);
  host += fifo; fifo.clear();
  Serial.callback(nullptr, nullptr, ARDUINO_USB_CDC_TX_EVENT, nullptr);
  const auto completed = mesh::observeUsbLoggingTransport();
  assert(completed.tx_progress == initial.tx_progress + 1);
  assert(!completed.pending);
  const auto detached_at = millis();
  assert(mesh::recoverUsbLoggingTransport(2) == mesh::UsbLoggingRecoveryResult::Attempted);
  assert(disconnect_calls == 1 && connect_calls == 0);
  assert(millis() == detached_at); // No blocking wait or descriptor rebuild.
  g_mock_millis += 49;
  mesh::serviceUsbLoggingPort();
  assert(connect_calls == 0);
  ++g_mock_millis;
  mesh::serviceUsbLoggingPort();
  assert(connect_calls == 1 && !mesh::observeUsbLoggingTransport().host_connected);
  mock_isr = true;
  assert(mesh::recoverUsbLoggingTransport(1) == mesh::UsbLoggingRecoveryResult::Deferred);
  mesh::probeUsbLoggingTransport();
  mock_isr = false;
  mounted = connected = true;
  fresh_session();
}

static void check_native_short_writes_and_mota() {
  const unsigned before = write_calls;
  assert(put(mesh::usbCompanionPort(), std::string(200, 'B')) == 64);
  assert(write_calls == before + 1);
  assert(put(mesh::usbCompanionPort(), "more") == 0);
  const unsigned flushed = flush_calls;
  mesh::usbCompanionPort().flush();
  assert(flush_calls == flushed);
  fifo.resize(59); // only 5 bytes free: an 11-byte mOTA record must not split
  assert(put(mesh::usbMotaPort(), std::string(11, 'M')) == 0);
  assert(write_calls == before + 1);
  fifo.resize(50);
  assert(put(mesh::usbMotaPort(), std::string(11, 'M')) == 11);
  assert(write_calls == before + 2);
  fresh_session();
}

static void check_ordered_text_and_functional_reserve() {
  const std::string log = "RAW: " + std::string(545, 'L') + "\r\n";
  const std::string reply = "  -> " + std::string(2177, 'R') + "\r\n";
  assert(put(mesh::usbLoggingPort(), log) == log.size());
  assert(fifo.size() == 64);
  assert(mesh::hasPendingUsbTerminalOutput());
  assert(mesh::canAcceptUsbConsoleCommand());  // logs cannot starve CLI input
  assert(put(mesh::usbConsolePort(), reply) == reply.size());
  assert(!mesh::canAcceptUsbConsoleCommand()); // previous reply needs draining
  assert(mesh::usbLoggingPort().availableForWrite() == 0);
  assert(put(mesh::usbLoggingPort(), std::string(900, 'X')) == 0);
  drain_all();
  assert(host == log + reply);  // no 64-byte log/reply interleaving
  assert(mesh::canAcceptUsbConsoleCommand());
  assert(mesh::usbTerminalDroppedBytes() == 0);
  fresh_session();
}

static void check_stalled_host_and_visible_overflow() {
  const std::string fill(4096, 'F');
  assert(put(mesh::usbConsolePort(), fill) == fill.size());
  assert(put(mesh::usbConsolePort(), std::string(64, 'T')) == 64);
  assert(!mesh::canAcceptUsbConsoleCommand());
  const unsigned before = write_calls;
  for (unsigned i = 0; i != 1000; ++i) mesh::serviceUsbLoggingPort();
  assert(write_calls == before);  // no retry loop enters a full USB FIFO
  assert(put(mesh::usbConsolePort(), "!") == 0);
  assert(mesh::usbTerminalDroppedBytes() == 1);
  drain_all();
  assert(host.find(fill + std::string(64, 'T')) == 0);
  assert(host.find("[USB terminal output dropped 1 bytes]") != std::string::npos);
  fresh_session();
}

static void check_disconnect_cleanup_keeps_new_host_input() {
  assert(put(mesh::usbConsolePort(), std::string(1000, 'O')) == 1000);
  const auto before = clear_calls;
  Serial.rx_count = 4;
  fresh_session();
  assert(clear_calls > before);
  assert(!mesh::hasPendingUsbTerminalOutput());
  assert(mesh::usbConsolePort().available() == 4);
  assert(mesh::usbConsolePort().peek() == 'v');
  assert(mesh::usbConsolePort().read() == 'v');
  assert(put(mesh::usbConsolePort(), "new\r\n") == 5);
  drain_all();
  assert(host == "new\r\n");
  fresh_session();
}

static void check_debug_formatter_and_reentrancy() {
  mesh::setUsbDebugEnabled(true);
  auto_drain = true;
  const std::string long_text(1000, 'D');
  assert(mesh::nrf52DebugPrintf("%s\n", long_text.c_str()) == 255);
  drain_all();
  assert(host.size() == 255);
  assert(host.substr(host.size() - 4) == "...\n");
  host.clear();
  during_write = [] {
    assert(mesh::nrf52DebugPrintf("must not recurse\n") == 0);
  };
  assert(mesh::nrf52DebugPrintf("outer\n") == 6);
  during_write = nullptr;
  drain_all();
  assert(host == "outer\n");
  fresh_session();
  mesh::setUsbDebugEnabled(false);
}

static void check_independent_debug_gate() {
  assert(!mesh::isUsbDebugEnabled());
  assert(mesh::isUsbLoggingEnabled());
  const auto before = write_calls;
  MESH_DEBUG_PRINTLN("default-off debug");
  assert(mesh::nrf52DebugPrintf("also quiet\n") == 0);
  assert(write_calls == before && !mesh::hasPendingUsbTerminalOutput());
  mesh::SerialLogLine<> raw;
  raw.printf("12:34:56 - 3/10/2026 U RAW: 0102");
  assert(raw.flush(mesh::usbLoggingPort()));
  drain_all();
  assert(host == "12:34:56 - 3/10/2026 U RAW: 0102\r\n");
  fresh_session();

  mesh::setUsbDebugEnabled(true);
  assert(mesh::isUsbDebugEnabled() && mesh::isUsbDebugLoggingEnabled());
  MESH_DEBUG_PRINTLN("explicit debug");
  drain_all();
  assert(host == "DEBUG: explicit debug\n");
  fresh_session();
  mesh::setUsbLoggingEnabled(false);
  assert(mesh::isUsbDebugEnabled() && !mesh::isUsbDebugLoggingEnabled());
  const auto gated = write_calls;
  MESH_DEBUG_PRINTLN("master is off");
  assert(write_calls == gated && !mesh::hasPendingUsbTerminalOutput());
  mesh::setUsbLoggingEnabled(true);
  assert(mesh::isUsbDebugLoggingEnabled());
  mesh::setUsbDebugEnabled(false);
  assert(mesh::isUsbLoggingEnabled() && !mesh::isUsbDebugLoggingEnabled());
  assert(!Serial.debug_enabled); // native raw framework output stays forbidden
}

static void check_cached_logging_gate_and_isr() {
  Stream& cached = mesh::usbLoggingPort();
  mesh::setUsbLoggingEnabled(false);
  assert(put(cached, "off") == 0);
  mesh::setUsbLoggingEnabled(true);
  mock_isr = true;
  const auto before = write_calls;
  assert(put(mesh::usbCompanionPort(), "isr") == 0);
  assert(put(mesh::usbConsolePort(), "isr") == 0);
  mesh::serviceUsbTerminalPort();
  assert(write_calls == before);
  mock_isr = false;
}

static void check_protocol_switch_cancels_text_and_overflow_marker() {
  fresh_session();
  assert(put(mesh::usbConsolePort(), std::string(5000, 'X')) == 0);
  assert(put(mesh::usbLoggingPort(), std::string(550, 'L')) == 550);
  mesh::setUsbLoggingEnabled(false);
  assert(!mesh::hasPendingUsbTerminalOutput());
  // A protocol owner may discard application text without resetting USB. The
  // already accepted FIFO prefix stays ordered before the new binary frame.
  mesh::discardUsbTerminalOutput();
  host += fifo;
  fifo.clear();
  assert(put(mesh::usbCompanionPort(), "binary") == 6);
  drain_all();
  assert(host == std::string(64, 'L') + "binary");
  // In particular, service must not inject a delayed ASCII overflow notice
  // into Binary or mOTA after the owner has discarded the terminal epoch.
  host.clear();
  assert(put(mesh::usbMotaPort(), std::string(11, 'M')) == 11);
  drain_all();
  assert(host == std::string(11, 'M'));
  mesh::setUsbLoggingEnabled(true);
  fresh_session();
}
#endif

int main() {
#if MESH_ESP32_TINYUSB_NONBLOCKING
  mesh::beginUsbLoggingPort();
  mesh::beginUsbLoggingPort();
  mesh::setUsbLoggingEnabled(true);
  assert(Serial.registrations == 1);
  assert(!Serial.debug_enabled);
  mesh::serviceUsbLoggingPort();
  assert(&mesh::usbConsolePort() == &mesh::usbTerminalPort());
  check_logging_watchdog_transport_observations_and_recovery();
  check_independent_debug_gate();
  check_native_short_writes_and_mota();
  check_ordered_text_and_functional_reserve();
  check_stalled_host_and_visible_overflow();
  check_disconnect_cleanup_keeps_new_host_input();
  check_debug_formatter_and_reentrancy();
  check_cached_logging_gate_and_isr();
  check_protocol_switch_cancels_text_and_overflow_marker();
  assert(Serial.blocking_calls == 0);
#else
  assert(&mesh::usbConsolePort() == &Serial);
  assert(mesh::canAcceptUsbConsoleCommand());
  assert(mesh::usbTerminalDroppedBytes() == 0);
  assert(!mesh::observeUsbLoggingTransport().supported);
  assert(mesh::recoverUsbLoggingTransport(1) == mesh::UsbLoggingRecoveryResult::Unsupported);
  mesh::probeUsbLoggingTransport();
#endif
  std::cout << "ESP32 TinyUSB transport checks passed\n";
}
