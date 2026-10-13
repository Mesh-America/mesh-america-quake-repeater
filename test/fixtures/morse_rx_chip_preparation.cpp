using CustomSX1262=Chip;
using CustomSX1268=Chip;
using CustomLLCC68=Chip;
using CustomSTM32WLx=Chip;
using CustomLR1110=Chip;
using CustomLR1121=Chip;
using CustomLR2021=Chip;
using LR1110=Chip;
using LR1121=Chip;
using LR2021=Chip;
struct SX1262Receive : RadioLibWrapper { @SX1262@ };
struct SX1268Receive : RadioLibWrapper { @SX1268@ };
struct LLCC68Receive : RadioLibWrapper { @LLCC68@ };
struct STM32WLxReceive : RadioLibWrapper { @STM32WLx@ };
struct LR1110Receive : RadioLibWrapper { @LR1110@ };
struct LR1121Receive : RadioLibWrapper { @LR1121@ };
struct LR2021Receive : RadioLibWrapper { @LR2021@ };
struct SX1276Receive : RadioLibWrapper { @SX1276@ };
template<typename T> static void receive(float bandwidth,bool hard_reset) {
  for (int fault=0; fault<5; ++fault) {
    T radio; radio.reset_ok=true;
    radio.fail_morse_params=false;
    if (fault==1) radio.board.frequency_ok=false;
    if (fault==2) radio.chip.fsk_result=-705;
    if (fault==3) radio.board.reset_prepare_ok=false;
    if (fault==4) radio.board.reset_finish_ok=false;
    const bool failure=fault==1 || fault==2 || (hard_reset && fault>=3);
    assert(radio.supportsMorseRx() && radio.morseReceiverBandwidthKHz()==bandwidth);
    assert(radio.startMorseRx(902.1f,25,1000)==(failure ? mesh::MorseRxResult::Failed : mesh::MorseRxResult::Started));
    assert(!radio.chip.starts && !radio.board.before && !radio.board.after);
    if (!failure) {
      assert(radio._morse_rx_fsk_mode && radio.chip.fsk && radio.isMorseRxActive());
      radio.reset_ok=false;
      assert(radio.stopMorseRx()==mesh::MorseRxResult::Failed && radio._morse_rx_fsk_mode);
      assert(radio.isMorseRxActive() && radio.board.awake);
      radio.reset_ok=true; advance(100); radio.serviceCarrierWave();
      assert(!radio._morse_rx_fsk_mode && !radio.chip.fsk && !radio._cw_active && !radio.board.awake);
    } else {
      assert(!radio._morse_rx_fsk_mode && !radio.chip.fsk && !radio._cw_active && !radio.board.awake);
      assert(!radio.morseCaptureLength());
    }
    if (fault==1 || (fault==3 && hard_reset)) assert(!radio.chip.fsk_starts);
    if (hard_reset && !failure) assert(radio.board.reset_prepares==1 && radio.board.reset_finishes==1);
  }
  T unsupported; unsupported.deep_supported=false;
  assert(!unsupported.supportsMorseRx());
  assert(unsupported.startMorseRx(902.1f,25,1000)==mesh::MorseRxResult::Unsupported);
  assert(!unsupported.chip.fsk_starts && !unsupported.chip.standby_calls);
}
int main() {
  receive<SX1262Receive>(4.8f,true); receive<SX1268Receive>(4.8f,true);
  receive<LLCC68Receive>(4.8f,true); receive<STM32WLxReceive>(4.8f,false);
  receive<LR1110Receive>(4.8f,true); receive<LR1121Receive>(4.8f,true);
  receive<LR2021Receive>(4.8f,true); receive<SX1276Receive>(2.6f,true);
}
