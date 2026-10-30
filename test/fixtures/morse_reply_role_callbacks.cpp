int main() {
  const uint8_t actor[32] = {1, 2, 3, 4};
  for (unsigned successes = 0; successes < 4; ++successes) {
    @ROLE@ node; TestRadio radio; radio.rx_supported = true;
    mesh::Packet first, second, unrelated;
    auto& handoff = node._cli.morseReply();
    handoff.beginCommand(actor); assert(handoff.stage(902100, 25, 60000, now_ms));
    handoff.endCommand(); handoff.prepareReply(&first);
    node.onRadioProfileCopyQueued(&second, &first, 0); handoff.armReply(&first, true);
    node.onSendComplete(&unrelated);
    assert(handoff.pending() && handoff.contains(&first) && handoff.contains(&second));
    if (successes & 1) node.onSendComplete(&first); else node.onSendFail(&first);
    assert(!handoff.service(&radio, now_ms, true, true, 902100, 25));
    assert(!radio.rx_starts && !handoff.ownsReply(&first) && handoff.ownsReply(&second));
    if (successes & 2) node.onSendComplete(&second); else node.onSendFail(&second);
    assert(handoff.service(&radio, now_ms, true, true, 902100, 25) == (successes != 0));
    assert(radio.rx_starts == unsigned(successes != 0) && !handoff.pending());
    node.onSendComplete(&first); node.onSendFail(&second);
    assert(!handoff.service(&radio, now_ms, true, true, 902100, 25));
    assert(radio.rx_starts == unsigned(successes != 0));
  }
}
