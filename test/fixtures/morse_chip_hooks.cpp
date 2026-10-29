using CustomSX1262 = Chip;
using CustomSX1268 = Chip;
using CustomLLCC68 = Chip;
using CustomSTM32WLx = Chip;
using CustomLR1110 = Chip;
using CustomLR1121 = Chip;
using CustomLR2021 = Chip;
using SX126x = Chip;
#include <helpers/radiolib/SX126xMorseRamp.h>
#include <helpers/radiolib/RadioPowerLimits.h>

struct SX1262Driver : RadioLibWrapper { @SX1262@ };
struct SX1268Driver : RadioLibWrapper { @SX1268@ };
struct LLCC68Driver : RadioLibWrapper { @LLCC68@ };
struct STM32WLxDriver : RadioLibWrapper { @STM32WLx@ };
struct LR1110Driver : RadioLibWrapper { @LR1110@ };
struct LR1121Driver : RadioLibWrapper { @LR1121@ };
struct LR2021Driver : RadioLibWrapper { @LR2021@ };

struct SX1276LowLevel {
  RoutedModule module;
  RoutedModule* mod = &module;
  @SX1276_RAMP@
};

struct MappedSX1262Driver : SX1262Driver {
  int16_t applyCachedTxPower(int8_t dbm) override {
#ifdef SX126X_PA_RAMP_TIME
    return chip.setTxParams(dbm - 28, SX126X_PA_RAMP_TIME);
#else
    return chip.setOutputPower(dbm - 28);
#endif
  }
};

template <typename Driver> static void sx_hooks(float carrier, float packet) {
  assert(sx126xMorsePaRamp()==EXPECTED_MORSE_RAMP);
  Driver w; w.supported = false;
  w._profiles.primary.freq = w.frequency = w._cur_freq = packet;
  w._profiles.primary.bw = 125;
  w._profiles.secondary.params.freq = packet + 10;
  const auto primary = w._profiles.primary;
  assert(w.startMorseTx(carrier, 25, "SOS") == mesh::MorseTxResult::Started);
  assert(w.chip.frequency == carrier && w.chip.ramp_time == EXPECTED_MORSE_RAMP && w.chip.power == 17);
  assert(w.chip.ramp_calls == 1 && w.chip.starts == 1 && w.board.awake);
  while (w.isMorseTxActive() && !w._cw_stopping) {
    g_mock_millis = w._morse.nextDeadline(); w.serviceCarrierWave();
  }
  assert(!w._cw_active && !w.chip.carrier && !w.board.awake && w.isInRecvMode());
  assert(w.chip.starts == 9 && w.chip.ramp_calls == 2);
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_WARM_TX) && MESH_MORSE_HIL_WARM_TX
  assert(w.chip.warm_standby_calls==9 && w.chip.last_standby_mode==RADIOLIB_SX126X_STANDBY_XOSC);
#else
  assert(!w.chip.warm_standby_calls);
#endif
  assert(!w.chip.standbyXOSC); // never overwrite scanner policy for a temporary CW experiment
  assert(w.chip.frequency == packet && w._profiles.primary == primary);
  assert(w.board.before == 9 && w.board.after == 9);
  for (int fault : {0, 1, 2}) {
    Driver bad;
    bad._profiles.primary.freq = bad.frequency = bad._cur_freq = packet;
    bad._profiles.secondary.params.freq = packet + 10;
    if (fault == 0) bad.chip.ramp_result = -705;
    if (fault == 1) bad.chip.frequency_result = -705;
    if (fault == 2) bad.chip.power_result = -705;
    assert(bad.startMorseTx(carrier, 25, "E") == mesh::MorseTxResult::Failed);
    assert(!bad.chip.starts && !bad.board.before);
    assert(bad._cw_active && bad._cw_stopping && bad.board.awake);
    bad.chip.ramp_result = bad.chip.frequency_result = bad.chip.power_result = 0;
    advance(100); bad.serviceCarrierWave();
    assert(!bad._cw_active && !bad.chip.carrier && !bad.board.awake && bad.isInRecvMode());
  }
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_WARM_TX) && MESH_MORSE_HIL_WARM_TX
  {
    Driver bad; bad._profiles.primary.freq=packet; bad._cur_freq=packet;
    bad._profiles.secondary.params.freq=packet+10; bad.chip.warm_standby_result=-705;
    assert(bad.startMorseTx(carrier,25,"EE")==mesh::MorseTxResult::Failed);
    assert(!bad.chip.starts && !bad.chip.carrier && !bad._cw_active && !bad.board.awake);
  }
  {
    Driver bad; bad._profiles.primary.freq=packet; bad._cur_freq=packet;
    bad._profiles.secondary.params.freq=packet+10;
    assert(bad.startMorseTx(carrier,25,"EE")==mesh::MorseTxResult::Started);
    bad.chip.warm_standby_result=-705; advance(48); bad.serviceCarrierWave();
    assert(!bad.chip.carrier && !bad._cw_active && !bad.board.awake && bad.isInRecvMode());
    assert(bad.chip.starts==1 && bad.board.before==1 && bad.board.after==1);
  }
#endif
}

template <typename Driver> static void lr11_hooks() {
  Driver w; w.supported = false; w._cur_dbm = 21;
  assert(w.startMorseTx(902.1f, 25, "SOS") == mesh::MorseTxResult::Started);
  assert(w.chip.ramp_time == 304 && w.chip.ramp_power_calls == 1 && w.chip.power == 21);
  assert(!w.chip.rfo && w.chip.frequency == 902.1f);
  while (w.isMorseTxActive()) { g_mock_millis = w._morse.nextDeadline(); w.serviceCarrierWave(); }
  assert(w.chip.ramp_time != 304 && w.chip.ramp_power_calls == 1);
  assert(w.chip.frequency == 909.5f && w.chip.power == 21 && !w.chip.carrier && w.isInRecvMode());
  // The public three-argument API must receive 304, not an already-encoded
  // uint8_t value or truncated 48. RadioLib owns its LR11xx ramp encoding.
  for (int fault : {0, 1, 2}) {
    Driver bad;
    if (fault == 0) bad.board.frequency_ok = false;
    if (fault == 1) bad.chip.frequency_result = -705;
    if (fault == 2) bad.chip.power_result = -705;
    assert(bad.startMorseTx(902.1f, 25, "E") == mesh::MorseTxResult::Failed);
    assert(!bad.chip.starts && !bad.board.before);
    bad.board.frequency_ok = true; bad.chip.frequency_result = bad.chip.power_result = 0;
    if (bad._cw_active) { advance(100); bad.serviceCarrierWave(); }
    assert(!bad._cw_active && !bad.board.awake && !bad.chip.carrier && bad.isInRecvMode());
  }
}

int main() {
  sx_hooks<SX1262Driver>(902.1f, 909.5f);
  sx_hooks<SX1268Driver>(433.5f, 433.0f);
  sx_hooks<LLCC68Driver>(902.1f, 909.5f);
  sx_hooks<STM32WLxDriver>(902.1f, 909.5f);
  {
    SX1268Driver w;
    assert(w.startMorseTx(902.1f, 25, "E") == mesh::MorseTxResult::InvalidFrequency);
    assert(!w.chip.starts && !w.chip.standby_calls);
  }
  {
    MappedSX1262Driver w; w._cur_dbm = 30;
    assert(w.startMorseTx(902.1f, 25, "E") == mesh::MorseTxResult::Started);
    assert(w.chip.power == 2 && w.chip.ramp_time == EXPECTED_MORSE_RAMP); // ramp retains mapped drive power
    assert(w.stopMorseTx() == mesh::MorseTxResult::Stopped && w.chip.power == 2);
#ifdef SX126X_PA_RAMP_TIME
    assert(w.chip.ramp_time == SX126X_PA_RAMP_TIME);
#else
    assert(w.chip.ramp_time == 4);
#endif
  }
  lr11_hooks<LR1110Driver>(); lr11_hooks<LR1121Driver>();
  for (float frequency : {902.1f, 2400.0f}) {
    LR2021Driver w; w._cur_dbm = 22;
    assert(w.startMorseTx(frequency, 25, "SOS") == mesh::MorseTxResult::Started);
    const bool high = mesh::lr2021::isHighBand(frequency);
    assert(w.chip.ramp_time == 304 && w.chip.frequency == frequency);
    assert(w.chip.power == (high ? 12 : 22));
    assert(w.chip.routed_module.switch_mode == (high ? LR2021::MODE_TX_HF : LR2021::MODE_TX));
    assert(w.chip.cw_test_mode == RADIOLIB_LR2021_TX_TEST_MODE_CW);
    while (w.isMorseTxActive()) { g_mock_millis = w._morse.nextDeadline(); w.serviceCarrierWave(); }
    assert(w.chip.frequency == 909.5f && w.chip.power == 22 && w.chip.ramp_time != 304);
    assert(w.chip.routed_module.switch_calls == 9 && !w.chip.carrier && w.isInRecvMode());
  }
  for (float frequency : {149.0f, 1100.0f, 1899.0f, 2501.0f, NAN, INFINITY}) {
    LR2021Driver w;
    assert(w.startMorseTx(frequency, 25, "E") == mesh::MorseTxResult::InvalidFrequency);
    assert(!w.chip.starts);
  }
  {
    LR2021Driver w;
    assert(w.startMorseTx(2400.0f, 25, "E") == mesh::MorseTxResult::Started);
    w.board.frequency_ok = false;
    assert(w.stopMorseTx() == mesh::MorseTxResult::Failed);
    assert(w._cw_active && w._cw_stopping && w.board.awake && !w.chip.carrier);
    w.board.frequency_ok = true; advance(100); w.serviceCarrierWave();
    assert(!w._cw_active && !w.board.awake && w.chip.frequency == 909.5f && w.isInRecvMode());
  }
  {
    SX1276LowLevel low;
    assert(low.setMorsePaRamp() == 0);
    assert(low.module.register_address == RADIOLIB_SX127X_REG_PA_RAMP);
    assert(low.module.register_value == 0 && low.module.register_msb == 3 && low.module.register_lsb == 0);
    low.module.register_result = -705;
    assert(low.setMorsePaRamp() == -705);
  }
}
