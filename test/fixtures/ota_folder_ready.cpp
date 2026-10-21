#include <helpers/ota/OtaManager.h>
#include <helpers/ota/MotaSourceSerial.h>
#include <helpers/ota/MotaSeederProto.h>
#include <helpers/ota/OtaByteIO.h>
#include <helpers/ota/OtaTiming.h>
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <vector>

using namespace mesh::ota;
namespace ota = mesh::ota;

// One ordinary data stream answers the real device COUNT/DESCRIBE protocol.
// No text CLI, second socket or explicit announcement command exists here.
class FolderHost : public Stream {
  std::vector<uint8_t> response;
  size_t position = 0;
public:
  using Stream::write;
  std::vector<uint32_t> mids = {0x12345678};
  std::vector<uint8_t> operations;
  int failed_descriptor = -1;
  bool fail_count = false;
  bool invalid_geometry = false;
  unsigned flushes = 0;

  size_t write(const uint8_t* request, size_t length) override {
    assert(length >= 4 && request[0] == 'M' && request[1] == 'S');
    uint8_t checksum = 0;
    for (size_t i = 2; i < length; ++i) checksum ^= request[i];
    assert(checksum == 0);
    const uint8_t op = request[2];
    operations.push_back(op);
    std::vector<uint8_t> payload;
    bool ok = true;
    if (op == MS_OP_COUNT) {
      assert(length == 4);
      ok = !fail_count;
      payload.push_back(static_cast<uint8_t>(mids.size()));
    } else {
      assert(op == MS_OP_DESCRIBE && length == 5);
      const uint8_t index = request[3];
      ok = index < mids.size() && index != failed_descriptor;
      if (ok) {
        payload.assign(MOTA_DESC_WIRE, 0);
        wr_u32le(payload.data(), mids[index]);
        wr_u32le(payload.data() + 4, 1234);
        wr_u32le(payload.data() + 8, 0x01120001);
        payload[12] = CODEC_FULL; payload[13] = MFLAG_FULL;
        wr_u32le(payload.data() + 14, 8 + MOTA_MFL + 4 + 128 + 5);
        wr_u32le(payload.data() + 18, 8 + MOTA_MFL);
        wr_u32le(payload.data() + 22, invalid_geometry ? 0 : 1);
        wr_u32le(payload.data() + 26, 8 + MOTA_MFL + 4);
        wr_u32le(payload.data() + 30, 128);
        payload[34] = 7;
      }
    }
    response = {'m', 's', op, uint8_t(ok ? MS_STATUS_OK : MS_STATUS_ERR)};
    if (ok) response.insert(response.end(), payload.begin(), payload.end());
    checksum = 0;
    for (uint8_t value : response) checksum ^= value;
    response.push_back(checksum);
    position = 0;
    return length;
  }
  int available() override { return static_cast<int>(response.size() - position); }
  int read() override {
    if (position < response.size()) return response[position++];
    ++g_mock_millis;
    return -1;
  }
  void flush() override { ++flushes; }
};

struct Sent {
  std::vector<std::vector<uint8_t>> frames;
  std::vector<uint32_t> times;
  uint32_t now = 0;
};
static bool capture(void* pointer, const uint8_t* data, uint16_t length, bool) {
  auto& sent = *static_cast<Sent*>(pointer);
  sent.frames.emplace_back(data, data + length);
  sent.times.push_back(sent.now);
  return true;
}

namespace mesh { namespace ota {
struct OtaContext {
  OtaManager manager;
  bool self_serve_supported = false, serving = false;
};
static OtaContext* active_context = nullptr;
OtaContext& ota_ctx() { assert(active_context); return *active_context; }
bool ota_serve_self(OtaContext&, unsigned) { return false; }
}}

// @PRODUCTION_DEFINES@
struct Clock { uint32_t now; uint32_t getMillis() const { return now; } };
struct Fixture {
  ota::OtaContext context;
  Sent sent;
  Clock clock;
  Clock* _ms = &clock;
  uint8_t _ota_announce_count = OTA_ANNOUNCE_BURST;
  ota::LongTimer _ota_announce_timer;
  float speed;
  bool active = true;
  Fixture(uint32_t start, float rate) : clock{start}, speed(rate) {
    ota::active_context = &context;
    context.manager.begin(1234, capture, &sent);
    const uint8_t sid[4] = {1, 2, 3, 4};
    context.manager.set_seeder_id(sid);
    context.manager.set_advert_mins(0);
    _ota_announce_timer.arm(start, OTA_ANNOUNCE_DISABLED_POLL_MS, speed);
  }
  void step() {
    if (!active) return;  // Same admission boundary as the production Mesh loop.
    sent.now = clock.now;
    context.manager.set_clock(clock.now);
    const float ota_speed = speed;
    // @PRODUCTION_READY@
    // @PRODUCTION_ANNOUNCE@
  }
  void advance(uint32_t milliseconds) { clock.now += milliseconds; step(); }
};

static void four_ready_beacons(MotaStreamWritePolicy policy, uint32_t start, float speed) {
  Fixture f(start, speed);
  FolderHost host;
  SerialMotaSource source(host, policy, 5);
  // Host preparation can outlast the entire existing boot burst.
  f.advance(120000);
  assert(f.sent.frames.empty());
  assert(f.context.manager.add_source(&source));
  assert((host.operations == std::vector<uint8_t>{MS_OP_COUNT, MS_OP_DESCRIBE}));
  assert(f.sent.frames.empty());  // Nothing is emitted from the data callback.
  f.step();
  assert(f.sent.frames.size() == 1 && "ready catalog must discover without a control channel");
  AdvMsg advert{};
  assert(decode_adv(f.sent.frames[0].data(), f.sent.frames[0].size(), advert));
  assert(advert.n_motas == 1);
  const uint32_t gap = scaleDelay(OTA_ANNOUNCE_BURST_MS, speed);
  for (unsigned count = 1; count < OTA_ANNOUNCE_BURST; ++count) {
    f.advance(gap - 1);
    assert(f.sent.frames.size() == count);
    f.context.manager.refresh_sources();  // Unchanged polls must not restart it.
    f.advance(1);
    assert(f.sent.frames.size() == count + 1);
    assert(f.sent.times.back() - f.sent.times[f.sent.times.size() - 2] == gap);
  }
  f.context.manager.refresh_sources();
  f.advance(gap);
  f.advance(OTA_ANNOUNCE_DISABLED_POLL_MS);
  assert(f.sent.frames.size() == OTA_ANNOUNCE_BURST);
  assert(host.flushes == (policy == MotaStreamWritePolicy::FlushTransmit ? host.operations.size() : 0));

  // A fresh receiver with no known source learns and retrieves the exact MID.
  OtaManager receiver;
  Sent requests;
  receiver.begin(1234, capture, &requests);
  receiver.queryAll();
  assert(requests.frames.empty());
  receiver.on_message(f.sent.frames[0].data(), f.sent.frames[0].size());
  receiver.queryAll();
  assert(requests.frames.size() == 1);
  const size_t before = f.sent.frames.size();
  f.context.manager.on_message(requests.frames[0].data(), requests.frames[0].size());
  assert(f.sent.frames.size() == before + 1);
  receiver.on_message(f.sent.frames.back().data(), f.sent.frames.back().size());
  assert(receiver.catalogCount() == 1 && rd_u32le(receiver.catalogRow(0)->mid) == host.mids[0]);
}

static void readiness_and_coalescing() {
  Fixture f(1000, 1);
  FolderHost host;
  host.mids.clear();
  SerialMotaSource source(host, MotaStreamWritePolicy::NoFlush, 5);
  assert(f.context.manager.add_source(&source));
  f.step();
  assert(f.sent.frames.empty());
  host.mids = {17, 18}; host.failed_descriptor = 1;
  f.context.manager.refresh_sources();
  assert(f.context.manager.servedCount() == 1 && !f.context.manager.sourceCatalogComplete());
  f.step();
  assert(f.sent.frames.empty());
  // A complete rescan may have exactly the same deduplicated MID set.
  host.mids = {17, 17}; host.failed_descriptor = -1;
  f.context.manager.refresh_sources();
  assert(f.context.manager.sourceCatalogComplete());
  f.step();
  assert(f.sent.frames.size() == 1);
  // Multiple changes before the next mesh tick collapse onto the newest set.
  host.mids = {19}; f.context.manager.refresh_sources();
  host.mids = {20, 21}; f.context.manager.refresh_sources();
  f.step();
  assert(f.sent.frames.size() == 2);
  std::reverse(host.mids.begin(), host.mids.end());
  f.context.manager.refresh_sources(); f.advance(1);
  assert(f.sent.frames.size() == 2);  // Canonical digest ignores enumeration order.
  // Metadata failure cancels an unsent ready signal and automatic burst sends.
  host.mids = {22, 23}; f.context.manager.refresh_sources();
  host.failed_descriptor = 1; f.context.manager.refresh_sources();
  f.advance(OTA_ANNOUNCE_BURST_MS);
  assert(f.sent.frames.size() == 2);
  host.failed_descriptor = -1; f.context.manager.refresh_sources();
  f.step();
  assert(f.sent.frames.size() == 3);
  // Empty or invalid offerings never announce an empty ready catalog.
  host.mids.clear(); f.context.manager.refresh_sources();
  f.advance(OTA_ANNOUNCE_BURST_MS);
  assert(f.sent.frames.size() == 3);
  host.mids = {24}; host.invalid_geometry = true; f.context.manager.refresh_sources();
  f.advance(OTA_ANNOUNCE_BURST_MS);
  assert(f.sent.frames.size() == 3);
  host.invalid_geometry = false; f.context.manager.refresh_sources();
  f.active = false; f.advance(120000);
  assert(f.sent.frames.size() == 3);  // Normal-radio admission retains readiness.
  f.active = true; f.step();
  assert(f.sent.frames.size() == 4);
  // Removing the source before admission must retire its pending signal.
  host.mids = {25}; f.context.manager.refresh_sources();
  f.context.manager.clear_sources(); f.step();
  assert(f.sent.frames.size() == 4 && !f.context.manager.takeSourceReadyAnnouncement());
}

int main() {
  for (auto policy : {MotaStreamWritePolicy::FlushTransmit, MotaStreamWritePolicy::NoFlush})
    for (uint32_t start : {0U, 0xffff0000U})
      for (float speed : {0.05f, 1.0f, 3.0f}) four_ready_beacons(policy, start, speed);
  readiness_and_coalescing();
  puts("PASS: single-data-session folder readiness, exact four-beacon bursts, cold peer discovery and coalescing");
}
