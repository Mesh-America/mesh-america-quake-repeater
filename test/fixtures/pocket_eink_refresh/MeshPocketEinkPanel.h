#pragma once
#include <GxEPD2_BW.h>

// This fixture checks the adapter's decisions. test_pocket_panel_spi.py runs
// the production profile against the real GxEPD2 register/bitmap implementation.
struct MeshPocketEinkPanel : GxEPD2_213_B74 {
  using GxEPD2_213_B74::GxEPD2_213_B74;
  void prepareRefresh(bool partial) {
    panel::calls.push_back(partial ? panel::Call::PreparePartial : panel::Call::PrepareFull);
  }
  void finishRefresh() {
    assert(!panel::calls.empty());
    const auto previous = panel::calls.back();
    assert(previous == panel::Call::Full || previous == panel::Call::Partial
           || previous == panel::Call::WriteWhite);
    panel::calls.push_back(panel::Call::Finish);
  }
};
