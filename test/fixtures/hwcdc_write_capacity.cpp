// The Python runner inserts the actual facade and pinned, patched SDK methods.
// Only the RTOS mutex/ring and hardware registers are replaced at this boundary.
#include <Arduino.h>
#include <helpers/NonBlockingWriteStream.h>
#include <helpers/UsbAsciiBinarySwitch.h>
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

static size_t ring_free = 0;
static std::vector<uint8_t> admitted;
static unsigned ring_sends = 0, zero_sends = 0, sdk_calls = 0;
static unsigned semaphore_takes = 0, tx_attempts = 0;
static bool reject_send = false, mutex_available = true;
static bool connected = true, access_allowed = true;
static uint32_t tx_timeout_ms = 99;
static int ring_token, lock_token;
static int* tx_ring_buf = &ring_token;
static int* tx_lock = &lock_token;
static std::function<void()> before_sdk_write;
constexpr int pdPASS = 1, pdTRUE = 1;
constexpr unsigned portTICK_PERIOD_MS = 1;
static int xSemaphoreTake(int*, unsigned ticks) {
  ++semaphore_takes;
  if (mutex_available) return pdPASS;
  delay(ticks);
  return 0;
}
static void xSemaphoreGive(int*) {}
static size_t xRingbufferGetCurFreeSize(int*) { return ring_free; }
static int xRingbufferSend(int*, void* data, size_t size, unsigned) {
  ++ring_sends;
  if (size == 0) { ++zero_sends; return pdTRUE; }
  if (reject_send || size > ring_free) return 0;
  const auto* bytes = static_cast<uint8_t*>(data);
  admitted.insert(admitted.end(), bytes, bytes + size);
  ring_free -= size;
  return pdTRUE;
}
static void usb_serial_jtag_ll_txfifo_flush() {}
static bool usb_serial_jtag_ll_txfifo_writable() { return true; }
static void mesh_hwcdc_enable_tx_intr() {}
static void meshEsp32HwcdcKickTx() {}
static void log_w(const char*) {}
struct mesh_hwcdc_writer_scope { explicit operator bool() const { return true; } };
class HWCDC : public Stream {
 public:
  static bool isCDC_Connected() { return connected; }
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override { assert(false && "guard must suppress flush"); }
  int availableForWrite() override;
  size_t driverWrite(const uint8_t*, size_t);
  size_t write(const uint8_t* bytes, size_t size) override {
    ++sdk_calls;
    if (before_sdk_write) {
      auto callback = std::move(before_sdk_write);
      before_sdk_write = nullptr;
      callback();
    }
    return driverWrite(bytes, size);
  }
  void setTxTimeoutMs(uint32_t timeout) { tx_timeout_ms = timeout; }
  void flushTXBuffer(const uint8_t* bytes, size_t size) {
    assert(size <= ring_free);
    assert(xRingbufferSend(tx_ring_buf, const_cast<uint8_t*>(bytes), size, 0) == pdTRUE);
  }
} Serial;
@SDK_AVAILABLE@
@SDK_WRITE@
#include <helpers/SerialPacketLog.h>
namespace mesh {
static UsbSelfResetBurstGuard esp32_hwcdc_self_reset_guard;
static std::atomic<bool> esp32_hwcdc_tx_kick_pending{false};
static void noteUsbLoggingTxAttempt() { ++tx_attempts; }
@FACADE@
static Esp32HwcdcSessionStream session;
static size_t once(void*, const uint8_t* bytes, size_t size) {
  return session.write(bytes, size);
}
static bool canAccess(void*) { return access_allowed; }
static SingleAttemptNonBlockingStream guarded(session, once, nullptr, canAccess);
}
static const uint8_t bytes[] = "abcdefghijklmnopqrstuvwx";

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string name = argv[1];
  using mesh::guarded;
  mesh::serialLogBegin();
  assert(tx_timeout_ms == 5);
  if (name == "full") {
    ring_free = 0;
    assert(guarded.write(bytes, 24) == 0);
    assert(sdk_calls == 0 && ring_sends == 0 && tx_attempts == 0);
  } else if (name == "oversize") {
    ring_free = 5;
    assert(guarded.write(bytes, 24) == 5);
    assert(g_mock_millis == 0 && zero_sends == 0 && ring_sends == 1);
  } else if (name == "stale") {
    ring_free = 12;
    const int prior = guarded.availableForWrite();
    assert(guarded.write(bytes, 7) == 7);
    assert(guarded.write(bytes + 7, prior) == 5);
    assert(g_mock_millis == 0 && zero_sends == 0);
    assert(admitted == std::vector<uint8_t>(bytes, bytes + 12));
  } else if (name == "contention") {
    ring_free = 24;
    std::mutex mutex;
    std::condition_variable event;
    bool entered = false, proceed = false;
    before_sdk_write = [&] {
      std::unique_lock<std::mutex> lock(mutex);
      entered = true;
      event.notify_all();
      assert(event.wait_for(lock, std::chrono::seconds(2), [&] { return proceed; }));
    };
    std::thread writer([&] { assert(guarded.write(bytes, 7) == 7); });
    {
      std::unique_lock<std::mutex> lock(mutex);
      assert(event.wait_for(lock, std::chrono::seconds(2), [&] { return entered; }));
    }
    assert(guarded.write(bytes + 7, 7) == 0);
    assert(!guarded.tryRunExclusive([](void*) { assert(false); }));
    {
      std::lock_guard<std::mutex> lock(mutex);
      proceed = true;
    }
    event.notify_all();
    writer.join();
    assert(sdk_calls == 1 && admitted.size() == 7 && g_mock_millis == 0);
  } else if (name == "mutex") {
    ring_free = 24;
    mutex_available = false;
    assert(guarded.write(bytes, 24) == 0);
    assert(sdk_calls == 0 && semaphore_takes == 1 && g_mock_millis == 5);
  } else if (name == "isr_drain") {
    ring_free = 5;
    before_sdk_write = [] { ring_free += 8; };
    assert(guarded.write(bytes, 24) == 5);
    assert(ring_free == 8 && g_mock_millis == 0 && zero_sends == 0);
  } else if (name == "short") {
    ring_free = 5;
    reject_send = true;
    assert(guarded.write(bytes, 24) == 0);
    reject_send = false;
    mesh::BufferedNonBlockingWriteStream<32> queued(guarded);
    assert(queued.write(bytes, 24) == 24);
    assert(queued.queuedByteCount() == 19 && admitted.size() == 5);
    ring_free = 7;
    assert(queued.service() == 7);
    ring_free = 12;
    assert(queued.service() == 12 && queued.queuedByteCount() == 0);
    assert(admitted == std::vector<uint8_t>(bytes, bytes + 24));
    assert(g_mock_millis == 0 && zero_sends == 0);
  } else if (name == "mota") {
    mesh::AtomicWholeRecordNonBlockingStream<11> mota(guarded);
    ring_free = 10;
    assert(mota.write(bytes, 11) == 0 && sdk_calls == 0);
    ring_free = 11;
    assert(mota.write(bytes, 11) == 11 && admitted.size() == 11);
    assert(mota.write(bytes, 12) == 0 && sdk_calls == 1);
    assert(g_mock_millis == 0 && zero_sends == 0);
  } else if (name == "timeout") {
    Serial.setTxTimeoutMs(0);
    mesh::serialLogBegin();
    assert(tx_timeout_ms == 5);
  } else if (name == "sdk_fallback") {
    // This intentionally bypasses the cap to exercise the SDK's positive
    // timeout fallback; the application path above never needs this loop.
    ring_free = 5;
    assert(Serial.driverWrite(bytes, 24) == 5);
    assert(g_mock_millis == 5 && zero_sends == 5 && !connected);
  } else {
    assert(false && "unknown fixture case");
  }
  guarded.flush();
  access_allowed = false;
  assert(guarded.write(bytes, 1) == 0);
  return 0;
}
