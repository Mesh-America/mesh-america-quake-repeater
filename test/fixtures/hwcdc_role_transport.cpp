// This file is appended to the actual HWCDC facade/SDK host harness.
#include <helpers/ArduinoSerialInterface.h>

@KISS_CONSTANTS@
class KissModem {
  Stream& _serial;
@KISS_FIELDS@
@KISS_DECLARATIONS@
public:
  explicit KissModem(Stream& serial) : _serial(serial) { resetOutputQueue(); }
  bool queue(uint8_t type, const std::vector<uint8_t>& bytes) {
    return queueFrame(type, bytes.data(), bytes.size());
  }
  bool service() { return tryFlushFrames(); }
  bool busy() { return _tx_frame_count != 0 || _tx_busy_error_pending; }
  void serviceBusy() { queuePendingBusyError(); }
};
@KISS_METHODS@

@COMPANION_LEASE_DEFAULTS@
static_assert(USB_FRAME_REPLY_GRACE_MS == 2000, "default frame grace");
static_assert(USB_CLIENT_IDLE_TIMEOUT == 600000, "default idle lease");
static_assert(USB_HOST_LOSS_EDGE_MS == 100, "default host edge");
static_assert(USB_HOST_LOSS_GRACE_MS == 2000, "default host grace");
static mesh::UsbHostPresenceDebouncer usb_hwcdc_host_presence;
static ArduinoSerialInterface usb_serial_interface;
struct Board {
  bool host = true;
  bool isUsbHostConnected() const { return host; }
} board;
struct Mesh {
  bool finite = false;
  bool hasFiniteDelayedReplyForRoute(const ArduinoSerialInterface*) const {
    return finite;
  }
} the_mesh;

// Independent protocol expectations; no production encoder is used here.
static std::vector<uint8_t> companionFrame(const std::vector<uint8_t>& payload) {
  std::vector<uint8_t> result = {'>', uint8_t(payload.size()), uint8_t(payload.size() >> 8)};
  result.insert(result.end(), payload.begin(), payload.end());
  return result;
}
static std::vector<uint8_t> kissFrame(uint8_t type, const std::vector<uint8_t>& payload) {
  std::vector<uint8_t> result = {0xC0};
  auto encode = [&](uint8_t byte) {
    if (byte == 0xC0) result.insert(result.end(), {0xDB, 0xDC});
    else if (byte == 0xDB) result.insert(result.end(), {0xDB, 0xDD});
    else result.push_back(byte);
  };
  encode(type);
  for (uint8_t byte : payload) encode(byte);
  result.push_back(0xC0);
  return result;
}
static void append(std::vector<uint8_t>& dest, const std::vector<uint8_t>& bytes) {
  dest.insert(dest.end(), bytes.begin(), bytes.end());
}

// Consume ring capacity after the protocol's outer availableForWrite sample.
// This represents another serial producer winning before the write. It is a
// one-shot disturbance, and must never make the guarded SDK wait for space.
class StaleCapacityStream : public Stream {
  Stream& _port;
  bool _consume_once = true;
public:
  explicit StaleCapacityStream(Stream& port) : _port(port) {}
  int availableForWrite() override { return _port.availableForWrite(); }
  size_t write(const uint8_t* data, size_t size) override {
    if (_consume_once) {
      _consume_once = false;
      ring_free = ring_free > 2 ? 2 : ring_free;
    }
    return _port.write(data, size);
  }
};

static void setupCompanion(bool activity_check = false) {
  usb_serial_interface.begin(@ROLE_STREAM@);
  usb_serial_interface.enableFlowControl(true);
  usb_serial_interface.enable();
  if (activity_check) {
@COMPANION_CONNECTION@
  }
}
static void drainCompanion(size_t capacity = 7) {
  for (unsigned pass = 0; pass < 1000 && usb_serial_interface.hasPendingIO(); ++pass) {
    ring_free = capacity;
    usb_serial_interface.loop();
  }
  assert(!usb_serial_interface.hasPendingIO());
}
static void drainKiss(KissModem& modem, size_t capacity = 7) {
  for (unsigned pass = 0; pass < 1000 && modem.busy(); ++pass) {
    ring_free = capacity;
    modem.service();
    modem.serviceBusy();
  }
  assert(!modem.busy());
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string name = argv[1];
  mesh::serialLogBegin();
  assert(tx_timeout_ms == 5);
  if (name == "companion_stall" || name == "companion_short") {
    setupCompanion();
    std::vector<uint8_t> payload(MAX_FRAME_SIZE);
    payload[0] = 0x05; // Required protocol response, rather than a best-effort push.
    for (size_t i = 1; i < payload.size(); ++i) payload[i] = uint8_t(i);
    const std::vector<uint8_t> tail = {0x00, 0xC0, 0xDB};
    ring_free = name == "companion_short" ? 5 : 0;
    if (name == "companion_short") reject_send = true;
    assert(usb_serial_interface.writeFrame(payload.data(), payload.size()) == payload.size());
    assert(usb_serial_interface.writeFrame(tail.data(), tail.size()) == tail.size());
    for (unsigned poll = 0; poll < 100; ++poll) usb_serial_interface.loop();
    assert(admitted.empty() && usb_serial_interface.hasPendingIO());
    reject_send = false;
    drainCompanion();
    auto expected = companionFrame(payload);
    append(expected, companionFrame(tail));
    assert(admitted == expected && zero_sends == 0 && g_mock_millis == 0);
  } else if (name == "companion_stale") {
    StaleCapacityStream stale(@ROLE_STREAM@);
    usb_serial_interface.begin(stale);
    usb_serial_interface.enableFlowControl(true);
    usb_serial_interface.enable();
    ring_free = 10;
    const std::vector<uint8_t> payload = {0x05, 1, 2, 3, 4, 5, 6, 7};
    assert(usb_serial_interface.writeFrame(payload.data(), payload.size()) == payload.size());
    assert(admitted.size() == 2 && g_mock_millis == 0 && zero_sends == 0);
    drainCompanion();
    assert(admitted == companionFrame(payload));
  } else if (name == "companion_session") {
    setupCompanion();
    host_input = {'<', 3, 0, 0x01};
    uint8_t received[MAX_FRAME_SIZE] = {};
    assert(usb_serial_interface.checkRecvFrame(received) == 0);
    assert(usb_serial_interface.isReadBusy());
    ring_free = 0;
    const uint8_t stale[] = {0x05, 0xAA};
    assert(usb_serial_interface.writeFrame(stale, sizeof(stale)) == sizeof(stale));
    // A confirmed BUS_RESET owner closes access before purging protocol state.
    access_allowed = false;
    usb_serial_interface.resetSessionState();
    host_input.clear();
    assert(!usb_serial_interface.hasPendingIO());
    ring_free = 32;
    assert(mesh::guarded.write(stale, sizeof(stale)) == 0 && admitted.empty());
    access_allowed = true;
    host_input = {'<', 1, 0, 0x02};
    assert(usb_serial_interface.checkRecvFrame(received) == 1 && received[0] == 0x02);
    const uint8_t fresh[] = {0x00, 0xBB};
    assert(usb_serial_interface.writeFrame(fresh, sizeof(fresh)) == sizeof(fresh));
    assert(admitted == companionFrame({0x00, 0xBB}));
  } else if (name == "companion_activity_lease") {
    setupCompanion(true);
    board.host = false;
    connected = false; // The SDK activity heuristic is not DTR proof.
    assert(!usb_serial_interface.isConnected());
    g_mock_millis = 100;
    host_input = {'<', 1, 0, 0x01};
    uint8_t received[MAX_FRAME_SIZE] = {};
    assert(usb_serial_interface.checkRecvFrame(received) == 1 && received[0] == 0x01);
    assert(usb_serial_interface.isConnected());
    ring_free = 0;
    const uint8_t response[] = {0x00, 0x11, 0x22};
    assert(usb_serial_interface.writeFrame(response, sizeof(response)) == sizeof(response));
    g_mock_millis += 5; // Transient SOF/activity gap must not discard a queued reply.
    drainCompanion(2);
    assert(admitted == companionFrame({0x00, 0x11, 0x22}));
    board.host = true;
    assert(usb_serial_interface.isConnected());
    g_mock_millis = 100 + 120000;
    assert(usb_serial_interface.isConnected());
    ring_free = 2;
    assert(usb_serial_interface.writeFrame(response, sizeof(response)) == sizeof(response));
    drainCompanion(2);
    auto after_idle = companionFrame({0x00, 0x11, 0x22});
    append(after_idle, companionFrame({0x00, 0x11, 0x22}));
    assert(admitted == after_idle && zero_sends == 0);
    g_mock_millis = 100 + USB_CLIENT_IDLE_TIMEOUT;
    assert(!usb_serial_interface.isConnected()); // An idle cable cannot claim USB forever.
    the_mesh.finite = true;
    assert(usb_serial_interface.isConnected());
    the_mesh.finite = false;
    assert(usb_serial_interface.isConnected()); // One bounded final-frame drain lease.
    g_mock_millis += USB_FRAME_REPLY_GRACE_MS;
    assert(!usb_serial_interface.isConnected());
    usb_serial_interface.resetSessionState();
    usb_hwcdc_host_presence.reset();
    assert(!usb_serial_interface.isConnected());
    host_input = {'<', 1, 0, 0x02};
    assert(usb_serial_interface.checkRecvFrame(received) == 1 && received[0] == 0x02);
    assert(usb_serial_interface.isConnected());
    ring_free = 2;
    assert(usb_serial_interface.writeFrame(response, sizeof(response)) == sizeof(response));
    drainCompanion(2);
    append(after_idle, companionFrame({0x00, 0x11, 0x22}));
    assert(admitted == after_idle && zero_sends == 0);
  } else if (name == "kiss_stall" || name == "kiss_short") {
    KissModem modem(@ROLE_STREAM@);
    ring_free = name == "kiss_short" ? 7 : 0;
    reject_send = name == "kiss_short";
    const std::vector<uint8_t> payload = {0xC0, 0xDB, 1, 2, 3, 4};
    assert(modem.queue(0, payload));
    for (unsigned poll = 0; poll < 100; ++poll) modem.service();
    assert(admitted.empty() && modem.busy());
    reject_send = false;
    drainKiss(modem, 2);
    assert(admitted == kissFrame(0, payload) && zero_sends == 0 && g_mock_millis == 0);
  } else if (name == "kiss_escaped_max") {
    KissModem modem(@ROLE_STREAM@);
    std::vector<uint8_t> payload(KISS_MAX_ESCAPABLE_BYTES);
    for (size_t i = 0; i < payload.size(); ++i) payload[i] = i % 2 ? 0xDB : 0xC0;
    // Both the type and each payload byte expand to two bytes. The actual
    // encoder must reject one more byte without retaining an invalid frame.
    assert(!modem.queue(0xC0, payload));
    assert(!modem.busy() && admitted.empty());
    payload.pop_back();
    assert(modem.queue(0xC0, payload));
    assert(modem.busy() && admitted.empty());
    drainKiss(modem, 3);
    const auto expected = kissFrame(0xC0, payload);
    assert(expected.size() == KISS_MAX_ENCODED_FRAME_SIZE);
    assert(admitted == expected && g_mock_millis == 0 && zero_sends == 0);
  } else if (name == "kiss_stale") {
    StaleCapacityStream stale(@ROLE_STREAM@);
    KissModem modem(stale);
    ring_free = 10;
    const std::vector<uint8_t> payload = {0xC0, 0xDB, 1, 2, 3, 4};
    assert(modem.queue(0, payload));
    assert(admitted.size() == 2 && g_mock_millis == 0 && zero_sends == 0);
    drainKiss(modem);
    assert(admitted == kissFrame(0, payload));
  } else if (name == "kiss_busy") {
    KissModem modem(@ROLE_STREAM@);
    const std::vector<uint8_t> first = {0xC0, 1}, second = {0xDB, 2}, discarded = {3};
    assert(modem.queue(0, first));
    assert(modem.queue(0, second));
    assert(!modem.queue(0, discarded));
    assert(admitted.empty() && modem.busy());
    drainKiss(modem, 1);
    auto expected = kissFrame(0, first);
    append(expected, kissFrame(0, second));
    append(expected, kissFrame(0x06, {0xF1, 0x07}));
    assert(admitted == expected && g_mock_millis == 0 && zero_sends == 0);
  } else {
    assert(false && "unknown transport fixture case");
  }
  return 0;
}
