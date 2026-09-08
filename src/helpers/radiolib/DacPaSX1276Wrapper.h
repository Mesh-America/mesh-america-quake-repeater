#pragma once

#include <Arduino.h>
#include <stdint.h>
#include "CustomSX1276Wrapper.h"

// TX power control for boards whose SX1276 does not drive the antenna
// directly, but feeds an external power amplifier whose gain is set by an
// analog control voltage rather than by the radio.
//
// Such a PA exposes a gain-control input - variously labelled APC, APC1/APC2,
// VAPC or VGA depending on the module - which is driven here from one of the
// MCU's DAC outputs. The radio is parked at a single fixed drive level and
// every power step is made by moving that control voltage, so the only thing
// this class overrides is applyCachedTxPower().
//
// A board supplies a table mapping the power it wants, in dBm at the antenna,
// to the control code that produces it. That table is the board's calibration:
// it is the only thing that knows what the amplifier actually does, so it is
// also what defines the legal range. Requests outside it are refused rather
// than saturated at the nearest end.
//
//   static const DacPaLevel LEVELS[] = { {10, 30}, {17, 50}, {30, 130} };
//   DacPaSX1276Wrapper radio_driver(radio, board, PIN_APC, LEVELS, 3);
//
// Entries must be ordered by ascending dBm. The default drive level of +2 dBm
// is the SX1276's floor on PA_BOOST (RegPaConfig OutputPower = 0), which suits
// an amplifier expecting a small constant input; pass drive_dbm to override it
// for a PA that wants more.
//
// The gain control is written through writeGainControl(), which uses the
// ESP32's DAC by default. A board driving its PA from a PWM pin or an external
// I2C DAC can subclass and override that one method.
//
// ---------------------------------------------------------------------------
// Deriving a table from an ExpressLRS hardware layout
//
// ExpressLRS transmitter modules use this arrangement widely (they call it
// POWER_OUTPUT_DACWRITE), so their published layouts are a convenient source
// of vendor-calibrated tables. The layout's "power_values" array is indexed by
// (PowerLevels_e - power_min), so with power_min = 0 the entries run:
//
//     PWR_10mW  PWR_25mW  PWR_50mW  PWR_100mW  PWR_250mW  PWR_500mW  ...
//       10 dBm    14 dBm    17 dBm     20 dBm     24 dBm     27 dBm
//
// Those are the vendor's nominal labels, not measurements. Treat an entry as
// an index into the amplifier's behaviour until it has been on a power meter.
// ---------------------------------------------------------------------------

struct DacPaLevel {
  int8_t  dbm;   // power at the antenna, after the amplifier
  uint8_t dac;   // gain-control code that produces it
};

// SX1276 PA_BOOST output floor: Pout = 2 + OutputPower, so +2 dBm is
// OutputPower = 0.
#define DAC_PA_DEFAULT_DRIVE_DBM  2

// Sentinel for the max_dbm constructor argument: use the table's top entry.
#define DAC_PA_TABLE_MAX  INT8_MAX

class DacPaSX1276Wrapper : public CustomSX1276Wrapper {
public:
  // max_dbm optionally caps the amplifier below its top table entry, for a
  // deployment that should not use everything the hardware can reach (thermal
  // headroom, or a regulatory limit lower than the PA's capability). It is
  // only ever a reduction; it cannot raise the ceiling above the table.
  DacPaSX1276Wrapper(CustomSX1276& radio, mesh::MainBoard& board,
                     uint8_t ctrl_pin,
                     const DacPaLevel* levels, uint8_t num_levels,
                     int8_t max_dbm = DAC_PA_TABLE_MAX,
                     int8_t drive_dbm = DAC_PA_DEFAULT_DRIVE_DBM)
      : CustomSX1276Wrapper(radio, board),
        _ctrl_pin(ctrl_pin), _levels(levels), _num_levels(num_levels),
        _drive_dbm(drive_dbm) {
    _min_dbm = levels[0].dbm;
    _max_dbm = levels[num_levels - 1].dbm;
    if (max_dbm < _max_dbm) _max_dbm = max_dbm;
    if (_max_dbm < _min_dbm) _max_dbm = _min_dbm;
  }

  // The supported range, taken from the table itself. The amplifier decides
  // what this board can do, so nothing else has to be told separately.
  int8_t minTxPowerDbm() const { return _min_dbm; }
  int8_t maxTxPowerDbm() const { return _max_dbm; }

  // Park the radio at its drive level and set the amplifier to dbm. Call once,
  // after the radio has started. A startup level outside the supported range
  // is brought into it rather than left unset.
  void beginPowerControl(int8_t dbm) {
    ((CustomSX1276 *)_radio)->setOutputPower(_drive_dbm);
    if (dbm < _min_dbm) dbm = _min_dbm;
    if (dbm > _max_dbm) dbm = _max_dbm;
    applyCachedTxPower(dbm);
  }

protected:
  // Emit a gain-control code. Override for a PA driven by PWM or an external
  // DAC instead of the MCU's own.
  virtual void writeGainControl(uint8_t code) {
    dacWrite(_ctrl_pin, code);
  }

  // MeshCore asks for power in dBm at the antenna. The radio register is left
  // where beginPowerControl() put it; only the amplifier moves.
  //
  // Out-of-range requests are refused rather than silently saturated. Without
  // this the top table entry becomes the response to any large number, which
  // on a high-power module is not a failure anyone wants to discover on air.
  int16_t applyCachedTxPower(int8_t dbm) override {
    if (dbm < _min_dbm || dbm > _max_dbm) {
      return RADIOLIB_ERR_INVALID_OUTPUT_POWER;
    }
    writeGainControl(codeForDbm(dbm));
    return RADIOLIB_ERR_NONE;
  }

private:
  // Highest level that does not exceed dbm. Callers have already range-checked.
  uint8_t codeForDbm(int8_t dbm) const {
    uint8_t code = _levels[0].dac;
    for (uint8_t i = 0; i < _num_levels; i++) {
      if (_levels[i].dbm <= dbm) code = _levels[i].dac;
    }
    return code;
  }

  uint8_t _ctrl_pin;
  const DacPaLevel* _levels;
  uint8_t _num_levels;
  int8_t _drive_dbm;
  int8_t _min_dbm;
  int8_t _max_dbm;
};
