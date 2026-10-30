#pragma once

#include <Dispatcher.h>
#include <stdint.h>
#if MESH_ENABLE_MORSE_RX
#include <helpers/TempRadioReplyBarrier.h>
#include <string.h>
#endif

namespace mesh {

// A remote listen command must acknowledge on the packet radio before giving
// that radio to Morse RX. Keep exact packet ownership with Dispatcher; never
// infer delivery from a timestamp, ciphertext, a queue delay or another reply.
#if MESH_ENABLE_MORSE_RX
class MorseReplyHandoff {
  TempRadioReplyBarrier barrier_;
  const void* prepared_reply_ = nullptr;
  const void* prepared_copy_ = nullptr;
  const uint8_t* command_actor_ = nullptr;  // valid only inside the authenticated callback
  uint8_t actor_[32] = {};
  uint32_t frequency_khz_ = 0, duration_ms_ = 0, deadline_ = 0, generation_ = 0;
  uint32_t start_deadline_ = 0, retry_at_ = 0;
  uint8_t wpm_ = 0;
  bool pending_ = false, delivered_ = false;
  bool start_wait_ = false, retry_pending_ = false;

public:
  static constexpr uint32_t ReplyDeadlineMillis = 30000;
  static constexpr uint32_t StartDeadlineMillis = 10000;
  void beginCommand(const uint8_t* actor) { command_actor_ = actor; }
  void endCommand() { command_actor_ = nullptr; }
  bool remoteCommand() const { return command_actor_ != nullptr; }
  bool pending() const { return pending_; }
  uint32_t generation() const { return generation_; }
  const uint8_t* actor() const { return actor_; }
  bool contains(const void* packet) const { return barrier_.contains(packet); }
  bool ownsReply(const void* packet) const {
    return pending_ && packet && (packet == prepared_reply_ || packet == prepared_copy_);
  }

  bool stage(uint32_t frequency_khz, uint8_t wpm, uint32_t duration_ms, uint32_t now) {
    if (!command_actor_ || pending_) return false;
    memcpy(actor_, command_actor_, sizeof(actor_));
    frequency_khz_ = frequency_khz;
    wpm_ = wpm;
    duration_ms_ = duration_ms;
    deadline_ = now + ReplyDeadlineMillis;
    ++generation_;
    pending_ = true;
    delivered_ = false;
    start_deadline_ = retry_at_ = 0;
    start_wait_ = retry_pending_ = false;
    barrier_.clear();
    prepared_reply_ = prepared_copy_ = nullptr;
    return true;
  }
  void prepareReply(const void* packet) {
    if (pending_) {
      prepared_reply_ = packet;
      prepared_copy_ = nullptr;
      barrier_.prepare(packet);
    }
  }
  void armReply(const void* packet, bool queued) {
    if (!pending_) return;
    if (!queued || !packet) { cancel(); return; }
    barrier_.arm(packet);
  }
  void copy(const void* original, const void* packet) {
    if (pending_) {
      if (original && original == prepared_reply_) prepared_copy_ = packet;
      barrier_.trackCopy(original, packet);
    }
  }
  void complete(const void* packet) {
    if (barrier_.contains(packet)) {
      if (packet == prepared_reply_) prepared_reply_ = nullptr;
      if (packet == prepared_copy_) prepared_copy_ = nullptr;
    }
    if (pending_ && barrier_.complete(packet) && !barrier_.waiting()) delivered_ = true;
  }
  void fail(const void* packet) {
    if (!pending_) return;
    if (barrier_.contains(packet)) {
      if (packet == prepared_reply_) prepared_reply_ = nullptr;
      if (packet == prepared_copy_) prepared_copy_ = nullptr;
    }
    if (barrier_.fail(packet)) cancel();
    else if (!barrier_.waiting() && barrier_.succeeded()) delivered_ = true;
  }
  void cancel() {
    pending_ = delivered_ = false;
    barrier_.clear();
    prepared_reply_ = prepared_copy_ = nullptr;
  }

  // Recheck the complete identity, saved settings and driver admission after
  // acknowledgement, not the possibly compacted ACL slot from command parsing.
  // The driver revalidates both live profiles before any hardware transition.
  bool service(Radio* radio, uint32_t now, bool authorized, bool settings_usable,
               uint32_t current_frequency_khz, uint8_t current_wpm) {
    if (!pending_) return false;
    if (!authorized || !settings_usable
        || current_frequency_khz != frequency_khz_ || current_wpm != wpm_
        || int32_t(now - deadline_) >= 0) {
      cancel();
      return false;
    }
    if (!delivered_) return false;
    if (!start_wait_) {
      start_deadline_ = now + StartDeadlineMillis;
      start_wait_ = true;
    }
    if (int32_t(now - start_deadline_) >= 0) { cancel(); return false; }
    if (retry_pending_ && int32_t(now - retry_at_) < 0) return false;
    const auto result = radio
        ? radio->startMorseRx(frequency_khz_ / 1000.0f, wpm_, duration_ms_)
        : MorseRxResult::Failed;
    if (result == MorseRxResult::Busy) {
      retry_at_ = now + 100;
      retry_pending_ = true;
      return false;
    }
    // Completion already drained the exact barrier, so a late callback or
    // cached replay cannot start another session. Hard admission failures do
    // not retry; transient packet-radio Busy is bounded and reauthorized.
    cancel();
    return result == MorseRxResult::Started;
  }
};
#else
// Preserve the role callback API without retaining RX state or ACK handoff
// machinery on small-flash builds whose receiver is explicitly disabled.
// No command can stage a listen; Morse TX and unrelated replies are unchanged.
class MorseReplyHandoff {
public:
  static constexpr uint32_t ReplyDeadlineMillis = 30000;
  static constexpr uint32_t StartDeadlineMillis = 10000;
  void beginCommand(const uint8_t*) {}
  void endCommand() {}
  bool remoteCommand() const { return false; }
  bool pending() const { return false; }
  uint32_t generation() const { return 0; }
  const uint8_t* actor() const { return nullptr; }
  bool contains(const void*) const { return false; }
  bool ownsReply(const void*) const { return false; }
  bool stage(uint32_t, uint8_t, uint32_t, uint32_t) { return false; }
  void prepareReply(const void*) {}
  void armReply(const void*, bool) {}
  void copy(const void*, const void*) {}
  void complete(const void*) {}
  void fail(const void*) {}
  void cancel() {}
  bool service(Radio*, uint32_t, bool, bool, uint32_t, uint8_t) { return false; }
};
#endif  // MESH_ENABLE_MORSE_RX

}  // namespace mesh
