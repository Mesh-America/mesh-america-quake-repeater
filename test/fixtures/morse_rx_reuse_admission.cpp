int main() {
  advance(0);
  total_free=65536; largest_free=65536;
  RadioLibWrapper driver;
  assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Started);
  receive_e(driver); assert(driver.stopMorseRx()==RXResult::Stopped);
  const auto capture=std::string(driver.morseCaptureText());
  auto* receiver=driver._morse_rx;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  auto* trace=driver._morse_trace;
  const auto trace_length=driver.morseTraceLength();
  mesh::MorseRssiTraceEntry first;
  assert(trace && trace_length && driver.readMorseTrace(0,first));
#endif
  const auto generation=driver.morseCaptureGeneration(),standbys=driver.chip.standby_calls;
  total_free=4095; largest_free=0; largest_queries=0;
  assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Failed);
  assert(driver.morseCaptureText()==capture && driver._morse_rx==receiver);
  assert(driver.morseCaptureGeneration()==generation && driver.chip.standby_calls==standbys && !largest_queries);
  total_free=4096;
  driver.chip.rx_result=-705; driver.fail_tune=true;
  assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Failed);
  assert(driver.morseCaptureText()==capture && driver._morse_rx==receiver && !largest_queries);
  assert(driver._cw_active && driver._cw_stopping && driver.board.awake);
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  mesh::MorseRssiTraceEntry retained;
  assert(driver._morse_trace==trace && driver.morseTraceLength()==trace_length && driver.readMorseTrace(0,retained));
  assert(retained.millis==first.millis && retained.flags==first.flags);
#endif
  driver.fail_tune=false; driver.chip.rx_result=0;
  advance(100); driver.serviceCarrierWave(); packet_receive_restored(driver);
  assert(driver.morseCaptureText()==capture && driver.morseCaptureGeneration()==generation);
  assert(driver.startMorseRx(902.1f,25,60000)==RXResult::Started);
  assert(driver._morse_rx==receiver && driver.morseCaptureGeneration()==generation+1 && !driver.morseCaptureLength());
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  assert(driver._morse_trace==trace && !driver.morseTraceLength());
#endif
  assert(!largest_queries); // existing buffers do not need any new contiguous block
  assert(driver.stopMorseRx()==RXResult::Stopped);
}
