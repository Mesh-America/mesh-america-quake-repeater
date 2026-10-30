int main() {
  for (unsigned failure : {1,2}) {
    RadioLibWrapper driver; nothrow_calls=0; fail_nothrow_call=failure;
    assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Failed);
    assert(!driver._morse_rx && !driver._morse_trace);
    assert(!driver.chip.standby_calls && !driver.board.before && !driver.chip.starts);
    assert(!driver._cw_active && !driver.board.awake);
  }
  fail_nothrow_call=0;
  RadioLibWrapper driver; g_mock_millis=0xfffffff0U;
  assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Started);
  assert(driver._morse_trace && !driver.morseTraceLength());
  receive_e(driver); driver.stopMorseRx(); packet_receive_restored(driver);
  assert(driver.morseTraceLength()==2 && driver.morseTraceTotal()==2);
  mesh::MorseRssiTraceEntry original;
  assert(driver.readMorseTrace(0,original) && original.millis<1000 && (original.flags&2));
  const auto capture=std::string(driver.morseCaptureText());
  for (int reason : {0,1,2}) {
    if (reason==0) driver.receiver_allocation_ok=false;
    if (reason==1) driver.board.frequency_ok=false;
    if (reason==2) driver.rssi=NAN;
    assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Failed);
    mesh::MorseRssiTraceEntry retained;
    assert(driver.morseCaptureText()==capture && driver.morseTraceLength()==2);
    assert(driver.readMorseTrace(0,retained) && retained.millis==original.millis && retained.flags==original.flags);
    driver.receiver_allocation_ok=true; driver.board.frequency_ok=true; driver.rssi=-110;
  }
  assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Started);
  assert(driver.morseCaptureLength()==0 && driver.morseTraceLength()==0);
  driver.stopMorseRx(); driver.clearMorseCapture();
  assert(!driver._morse_rx && !driver._morse_trace && !driver.morseTraceLength());
}
