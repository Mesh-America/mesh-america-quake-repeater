using Handoff = mesh::MorseReplyHandoff;
using RXResult = mesh::MorseRxResult;
static uint8_t actor[32] = {1, 2, 3, 4};

static void stage(Handoff& handoff, uint32_t now = 100) {
  handoff.beginCommand(actor);
  assert(handoff.remoteCommand());
  assert(handoff.stage(902100, 25, 60000, now));
  handoff.endCommand();
  assert(handoff.pending() && !handoff.remoteCommand());
  assert(!memcmp(handoff.actor(), actor, 32));
}
static void queued(Handoff& h, const void* packet, const void* copy = nullptr) {
  h.prepareReply(packet);
  if (copy) h.copy(packet, copy);
  assert(h.ownsReply(packet) && (!copy || h.ownsReply(copy)));
  h.armReply(packet, true);
}
static bool service(Handoff& h, TestRadio& radio, uint32_t now = 100,
                    bool authorized = true, bool usable = true,
                    uint32_t frequency = 902100, uint8_t wpm = 25) {
  return h.service(&radio, now, authorized, usable, frequency, wpm);
}

static void exact_phy_barrier() {
  for (unsigned success = 0; success < 4; ++success) {
    Handoff handoff; TestRadio radio; radio.rx_supported = true;
    int packet, copy, unrelated;
    stage(handoff); queued(handoff, &packet, &copy);
    handoff.complete(&unrelated); handoff.fail(&unrelated);
    assert(!service(handoff, radio) && radio.rx_starts == 0 && handoff.pending());
    if (success & 1) handoff.complete(&packet); else handoff.fail(&packet);
    assert(!handoff.ownsReply(&packet) && handoff.ownsReply(&copy)); // pool slot may now be reused
    assert(!service(handoff, radio) && radio.rx_starts == 0 && handoff.pending());
    if (success & 2) handoff.complete(&copy); else handoff.fail(&copy);
    assert(service(handoff, radio) == (success != 0));
    assert(!handoff.pending() && radio.rx_starts == unsigned(success != 0));
    assert(!handoff.ownsReply(&packet) && !handoff.ownsReply(&copy));
    handoff.complete(&packet); handoff.complete(&copy);
    assert(!service(handoff, radio) && radio.rx_starts == unsigned(success != 0));
  }
  {
    Handoff h; TestRadio radio; int packet;
    assert(!h.stage(902100, 25, 60000, 100)); // timestamps do not authorize remote staging
    h.beginCommand(nullptr); assert(!h.stage(902100, 25, 60000, 100));
    stage(h);
    const auto generation = h.generation();
    h.beginCommand(actor); assert(!h.stage(902100, 25, 60000, 100)); h.endCommand();
    assert(h.generation() == generation);
    h.prepareReply(&packet);
    h.fail(&packet); h.complete(&packet); // admission callbacks before arm prove nothing
    assert(h.pending() && !service(h, radio) && !radio.rx_starts);
    h.armReply(&packet, false); assert(!h.pending());
  }
  {
    Handoff h; TestRadio radio; int packet;
    stage(h); h.prepareReply(&packet); h.armReply(nullptr, true);
    assert(!h.pending() && !service(h, radio) && !radio.rx_starts);
  }
}

static void revocation_settings_cancel_and_replays() {
  for (int reason = 0; reason < 5; ++reason) {
    Handoff h; TestRadio radio; int packet;
    stage(h); queued(h, &packet); h.complete(&packet);
    if (reason == 4) h.cancel();
    assert(!service(h, radio, 100, reason != 0, reason != 1,
                    reason == 2 ? 902101 : 902100, reason == 3 ? 26 : 25));
    assert(!h.pending() && !radio.rx_starts);
  }
  {
    Handoff h; TestRadio radio; int old_packet, new_packet;
    stage(h); queued(h, &old_packet); const auto previous = h.generation(); h.cancel();
    stage(h); queued(h, &new_packet);
    assert(h.generation() != previous && !h.contains(&old_packet));
    h.complete(&old_packet); h.fail(&old_packet);
    assert(!service(h, radio) && !radio.rx_starts);
    h.complete(&new_packet); assert(service(h, radio) && radio.rx_starts == 1);
  }
  {
    Handoff h; uint8_t original[32]; memcpy(original, actor, 32);
    stage(h); actor[31] ^= 1;
    assert(!memcmp(h.actor(), original, 32)); // full identity is owned, not an ACL index/pointer
    actor[31] ^= 1; h.cancel();
  }
}

static void deadlines_busy_retry_and_hard_failure() {
  for (uint32_t now : {100U, 0xfffffff0U}) {
    Handoff h; TestRadio radio; int packet;
    stage(h, now); queued(h, &packet);
    assert(!service(h, radio, now + Handoff::ReplyDeadlineMillis - 1) && h.pending());
    assert(!service(h, radio, now + Handoff::ReplyDeadlineMillis) && !h.pending());
    h.complete(&packet); assert(!service(h, radio, now + Handoff::ReplyDeadlineMillis + 1) && !radio.rx_starts);
  }
  for (auto outcome : {RXResult::Unsupported, RXResult::InvalidFrequency,
       RXResult::InvalidSpeed, RXResult::InvalidDuration, RXResult::Failed}) {
    Handoff h; TestRadio radio; int packet;
    stage(h); queued(h, &packet); h.complete(&packet);
    radio.force_rx_result = true; radio.forced_rx = outcome;
    assert(!service(h, radio) && !h.pending() && radio.rx_starts == 1);
    assert(!service(h, radio, 200) && radio.rx_starts == 1);
  }
  for (uint32_t now : {100U, 0xfffffff0U, UINT32_MAX - 99U, UINT32_MAX - 9999U}) {
    Handoff h; TestRadio radio; int packet;
    stage(h, now); queued(h, &packet); h.complete(&packet);
    radio.force_rx_result = true; radio.forced_rx = RXResult::Busy;
    assert(!service(h, radio, now) && h.pending() && radio.rx_starts == 1);
    assert(!service(h, radio, now) && radio.rx_starts == 1);
    assert(!service(h, radio, now + 99) && radio.rx_starts == 1);
    assert(!service(h, radio, now + 100) && radio.rx_starts == 2);
    radio.force_rx_result = false;
    assert(service(h, radio, now + 200) && !h.pending() && radio.rx_starts == 3);
    assert(!service(h, radio, now + 300) && radio.rx_starts == 3);
  }
  {
    const uint32_t now = UINT32_MAX - 9999U; // exactly zero wrapped start deadline
    Handoff h; TestRadio radio; int packet;
    stage(h, now); queued(h, &packet); h.complete(&packet);
    radio.force_rx_result = true; radio.forced_rx = RXResult::Busy;
    assert(!service(h, radio, now));
    assert(!service(h, radio, now + Handoff::StartDeadlineMillis - 1) && h.pending());
    assert(!service(h, radio, now + Handoff::StartDeadlineMillis) && !h.pending());
  }
  {
    Handoff h; TestRadio radio; int packet;
    stage(h); queued(h, &packet); h.complete(&packet);
    radio.force_rx_result = true; radio.forced_rx = RXResult::Busy;
    assert(!service(h, radio) && h.pending());
    assert(!service(h, radio, 101, false) && !h.pending()); // revoke permission during Busy retry
    assert(radio.rx_starts == 1);
  }
}

static void actual_shared_remote_parser() {
  Handoff h; TestRadio radio; radio.rx_supported = true;
  char reply[160];
  const auto command = [&](const char* text, bool remote) {
    if (remote) h.beginCommand(actor);
    const bool intercepted = mesh::handleMorseReplyCommand(h, &radio, text, reply, sizeof(reply), 100);
    h.endCommand();
    if (!intercepted) assert(mesh::handleMorseCommand(&radio, text, reply, sizeof(reply)));
    return std::string(reply);
  };
  assert(command("morse listen 1", false).find("OK - Morse RX") == 0);
  assert(radio.rx_active && radio.rx_starts == 1 && !h.pending());
  command("morse stop", false);
  assert(command("morse listen 1", true).find("starts after this reply transmits") != std::string::npos);
  assert(h.pending() && !radio.rx_active && radio.rx_starts == 1);
  const auto generation = h.generation();
  assert(command("morse listen 1", true).find("handoff pending") != std::string::npos && h.generation() == generation);
  assert(command("get morse", false).find("waiting for command reply") != std::string::npos);
  assert(command("set morse.freq 903", false).find("handoff pending") != std::string::npos);
  assert(command("cw on", false).find("handoff pending") != std::string::npos);
  assert(command("morse send E", false).find("handoff pending") != std::string::npos);
  assert(command("morse read", false).find("> 0000/0000") == 0);
  assert(command("morse stop", false).find("pending Morse RX cancelled") != std::string::npos && !h.pending());
  assert(radio.rx_starts == 1);
  for (const char* spelling : {"morse\tlisten 1", "morse  listen\t1", "morse listen +.5\t",
                              "morse\t\tlisten .0166667"}) {
    assert(command(spelling, true).find("starts after this reply transmits") != std::string::npos);
    assert(h.pending() && radio.rx_starts == 1 && !radio.rx_active);
    assert(command("morse\tstop\t ", false).find("pending Morse RX cancelled") != std::string::npos);
    assert(!h.pending());
  }
  for (bool remote : {false, true}) {
    for (const char* stop : {"morse stop ", "morse  stop  ", "morse\tstop", "morse\t\tstop\t "}) {
      assert(command("morse listen 1", true).find("starts after this reply transmits") != std::string::npos);
      assert(command(stop, remote).find("pending Morse RX cancelled") != std::string::npos);
      assert(!h.pending() && !radio.rx_active && radio.rx_starts == 1);
    }
  }
  for (const char* invalid : {"morse listen", "morse listen 0", "morse listen 6",
      "morse listen 1x", "morse listen nan", "morse listen 1e0", "morse listen .01"}) {
    assert(command(invalid, true).find("Error:") == 0 && !h.pending() && radio.rx_starts == 1);
  }
  mesh::usable = false;
  assert(command("morse listen 1", true).find("saved Morse settings unavailable") != std::string::npos && !h.pending());
  mesh::usable = true;
  radio.rx_supported = false;
  assert(command("morse listen 1", true).find("unsupported") != std::string::npos && !h.pending());
  assert(!mesh::handleMorseReplyCommand(h, &radio, nullptr, reply, sizeof(reply), 100));
  assert(!mesh::handleMorseReplyCommand(h, &radio, "get morse", nullptr, 160, 100));
  assert(!mesh::handleMorseReplyCommand(h, &radio, "get morse", reply, 0, 100));
}

int main() {
  exact_phy_barrier(); revocation_settings_cancel_and_replays();
  deadlines_busy_retry_and_hard_failure(); actual_shared_remote_parser();
}
