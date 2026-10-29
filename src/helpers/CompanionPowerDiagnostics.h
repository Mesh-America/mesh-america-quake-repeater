#pragma once

#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <helpers/CLICommandUtils.h>

namespace mesh { namespace companion {

// Read-only board diagnostics shared by every Companion transport. A capability
// reply describes the board/build, independently of whether boot setup ran.
template<class Board>
bool handlePowerDiagnosticsCommand(Board& board, const char* command,
                                   char* reply, size_t capacity) {
  if (!command || !reply || !capacity) return false;
  if (strcmp(command, "power") == 0) {
    const char* usb = board.hasUsbPowerDetect()
        ? (board.isUsbPowered() ? "yes" : "no") : "n/a";
    const char* solar = board.hasSolarChargerDetect()
        ? (board.isSolarChargerActive() ? "yes" : "no") : "n/a";
    snprintf(reply, capacity,
        "batt:%u mV usb:%s solar_chg:%s ext:%s charger:%s",
        (unsigned)board.getBattMilliVolts(), usb, solar,
        board.isExternalPowered() ? "yes" : "no",
        board.isChargerActive() ? "yes" : "no");
    return true;
  }
  if (strcmp(command, "get pwrmgt.support") == 0) {
    snprintf(reply, capacity, "> %s",
             board.supportsPowerManagement() ? "supported" : "unsupported");
    return true;
  }
  const bool source = strcmp(command, "get pwrmgt.source") == 0;
  const bool boot_voltage = strcmp(command, "get pwrmgt.bootmv") == 0;
  if (source || boot_voltage) {
    if (!board.supportsPowerManagement()) {
      snprintf(reply, capacity, "ERROR: Power management not supported");
    } else if (source) {
      snprintf(reply, capacity, "> %s",
               board.isExternalPowered() ? "external" : "battery");
    } else {
      snprintf(reply, capacity, "> %u mV", (unsigned)board.getBootVoltage());
    }
    return true;
  }
  if (strcmp(command, "get system.watchdog") == 0) {
    bool running = false;
    if (!board.getSystemWatchdogRunning(running)) {
      cli::formatError(reply, capacity, "unsupported on this platform");
    } else {
      snprintf(reply, capacity, "> %s", running ? "on" : "off");
    }
    return true;
  }
  static const char setter[] = "set system.watchdog";
  if (strncmp(command, setter, sizeof(setter) - 1) == 0
      && (command[sizeof(setter) - 1] == 0
          || command[sizeof(setter) - 1] == ' '
          || command[sizeof(setter) - 1] == '\t')) {
    // Companion has no persisted watchdog preference/feed-loop policy. In
    // particular, claiming "off" without that policy would cause reset loops.
    cli::formatError(reply, capacity,
                     "system watchdog control is unavailable in Companion");
    return true;
  }
  return false;
}

} } // namespace mesh::companion
