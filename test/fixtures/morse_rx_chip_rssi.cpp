#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <initializer_list>
#define RADIOLIB_ERR_NONE 0
#define RADIOLIB_SX126X_CMD_GET_RSSI_INST 0x15
#define RADIOLIB_SX127X_FSK_OOK 0
#define RADIOLIB_SX1278_CHIP_VERSION 0x12
#define RADIOLIB_SX1278_CHIP_VERSION_ALT 0x13
#define RADIOLIB_SX1278_CHIP_VERSION_RFM9X 0x11
#define RADIOLIB_SX127X_REG_RSSI_VALUE_FSK 0x24
struct MockModule {
  int result = 0;
  uint8_t raw = 220, command = 0;
  size_t length = 0;
  unsigned reads = 0;
  int16_t SPIreadStream(uint8_t cmd, uint8_t* out, size_t size) {
    ++reads; command = cmd; length = size;
    *out = raw; return result;
  }
  int16_t SPIgetRegValue(uint8_t address) {
    ++reads; assert(address==RADIOLIB_SX127X_REG_RSSI_VALUE_FSK);
    return result ? result : raw;
  }
};
struct Chip {
  MockModule module;
  float rssi = -110;
  int rssi_result = 0;
  unsigned rssi_reads = 0;
  MockModule* getMod() { return &module; }
  int16_t getRssiInst(float* out) { ++rssi_reads; *out = rssi; return rssi_result; }
  @SX1262_GETTER@
};
using LR11x0 = Chip;
using LR2021 = Chip;
using CustomSX1262 = Chip;
using CustomSX1268 = Chip;
using CustomLLCC68 = Chip;
using CustomSTM32WLx = Chip;
struct SX1276Chip : Chip {
  MockModule* mod=&module;
  uint8_t version=0x12, modem=0;
  uint8_t getChipVersion() { return version; }
  uint8_t getActiveModem() { return modem; }
  @SX1276_GETTER@
};
using CustomSX1276 = SX1276Chip;
struct Base {
  Chip chip; Chip* _radio = &chip;
  virtual float readMorseRssi() { return 0; }
  @DEFAULT_BANDWIDTH@
};
struct SX1262Probe : Base { @SX1262@ };
struct SX1268Probe : Base { @SX1268@ };
struct LLCC68Probe : Base { @LLCC68@ };
struct STM32WLxProbe : Base { @STM32WLx@ };
struct LR1110Probe : Base { @LR1110@ };
struct LR1121Probe : Base { @LR1121@ };
struct LR2021Probe : Base { @LR2021@ };
struct SX1276Probe {
  SX1276Chip chip; SX1276Chip* _radio=&chip;
  virtual float readMorseRssi() { return 0; }
  virtual float morseReceiverBandwidthKHz() const { return 0; }
};
struct SX1276Actual : SX1276Probe { @SX1276@ };

template <typename Probe> static void native(float bandwidth) {
  Probe probe;
  assert(probe.morseReceiverBandwidthKHz() == bandwidth);
  assert(probe.readMorseRssi() == -110);
  assert(probe.chip.module.reads == 1 && probe.chip.module.length == 1);
  assert(probe.chip.module.command == RADIOLIB_SX126X_CMD_GET_RSSI_INST);
  probe.chip.module.result = -705; probe.chip.module.raw = 0;
  assert(std::isnan(probe.readMorseRssi())); // failed SPI must not look like a 0dBm carrier
}
template <typename Probe> static void lr(float bandwidth) {
  Probe probe;
  assert(probe.morseReceiverBandwidthKHz() == bandwidth && probe.readMorseRssi() == -110);
  assert(probe.chip.rssi_reads == 1);
  probe.chip.rssi_result = -705; probe.chip.rssi = 0;
  assert(std::isnan(probe.readMorseRssi()));
}
int main() {
  native<SX1262Probe>(4.8f); native<SX1268Probe>(4.8f);
  native<LLCC68Probe>(4.8f); native<STM32WLxProbe>(4.8f);
  lr<LR1110Probe>(4.8f); lr<LR1121Probe>(4.8f); lr<LR2021Probe>(4.8f);
  SX1276Actual sx;
  assert(sx.morseReceiverBandwidthKHz()==2.6f && sx.readMorseRssi()==-110);
  sx.chip.modem=1; assert(std::isnan(sx.readMorseRssi()));
  sx.chip.modem=0; sx.chip.version=0xff; assert(std::isnan(sx.readMorseRssi()));
  for (uint8_t version : {uint8_t(0x12),uint8_t(0x13),uint8_t(0x11)}) {
    sx.chip.version=version; assert(sx.readMorseRssi()==-110);
  }
  sx.chip.module.result=-705; assert(std::isnan(sx.readMorseRssi()));
}
