#!/usr/bin/env bash
# Identity-bound nRF52 bench adapter for the unchanged mcfirmware.sh DFU path.
# No startup, dependency installation, service stopping, erase, or port recovery.
set -euo pipefail
umask 077
[[ $# == 7 ]] || { echo 'Usage: morse_nrf_flash.sh FLASHER BY_ID SERIAL BOARD ZIP INVENTORY WORKDIR' >&2; exit 2; }
bench_flasher=$(realpath -e -- "$1")
bench_link=$2 bench_serial=$3 bench_board=$4
bench_image=$(realpath -e -- "$5")
bench_inventory=$(realpath -e -- "$6")
bench_workdir=$(realpath -e -- "$7")
[[ "$bench_link" == /dev/serial/by-id/* && -L "$bench_link" ]]
[[ "$bench_workdir" == /home/mikec/hwtest/runs/morse-* ]]
bench_port=$(readlink -f -- "$bench_link")
morse_assert_unowned() {
  local output status
  if output=$(sudo -n fuser "$1" 2>&1); then
    echo 'Selected port is busy; no owner will be stopped.' >&2
    return 1
  else status=$?; fi
  [[ "$status" == 1 && -z "$output" ]] || {
    echo 'Cannot verify that the selected port is unowned.' >&2
    return 1
  }
}
python3 "$(dirname "$bench_inventory")/verified_nrf_flash.py" \
  --inventory "$bench_inventory" --serial "$bench_serial" --board "$bench_board" \
  --artifact "$bench_image" --port "$bench_port"
morse_assert_unowned "$bench_port"
sha256sum -- "$bench_image"
bench_state=$(mktemp -d "$bench_workdir/mcfirmware-session.XXXXXX")
bench_functions="$bench_state/functions.sh"
awk '
  { sub(/\r$/, "") }
  /^[A-Za-z_][A-Za-z0-9_]*\(\)[[:space:]]*\{[[:space:]]*$/ {
    if (capture) exit 2
    capture=1; count++
  }
  capture { print }
  capture && /^}[[:space:]]*$/ { capture=0; print "" }
  END { if (capture || count < 100) exit 3 }
' "$bench_flasher" > "$bench_functions"
bash -n "$bench_functions"
source "$bench_functions"
# Do not source the interactive program's globals or unattended cleanup.
PWD_SCRIPT=$(dirname "$bench_flasher")
FIRMWARE_ROOT=$bench_state
DOWNLOAD_DIR="$bench_state/downloads"
mkdir -- "$DOWNLOAD_DIR"
DEVICE_PORT=$bench_port
DEVICE_PORT_FILE="$bench_state/selected-port"
DEVICE_PORT_NAME_FILE="$bench_state/selected-port-name"
MESHFIRMWARE_SERIAL_BY_ID_FILE="$bench_state/by-id"
printf '%s\n' "$bench_link" > "$MESHFIRMWARE_SERIAL_BY_ID_FILE"
NRF52_BOARD_GUARD_PASSED=1
NRF52_SELECTED_BY_ID=$bench_link
NRF52_RUNTIME_SERIAL=$(udev_device_property "$bench_port" ID_SERIAL_SHORT)
NRF52_RUNTIME_PATH_STEM=$(nrf52_usb_path_stem "$(udev_device_property "$bench_port" ID_PATH)")
NRF52_RUNTIME_INSTANCE=$(nrf52_port_instance "$bench_port")
NRF52_LAST_DFU_PORT='' NRF52_LAST_DFU_INSTANCE=''
NRF52_ALLOW_UNMATCHED_DFU=0
NRF52_DFU_REENUMERATE_TIMEOUT_SECONDS=30
NRF52_DFU_REENUMERATE_POLL_SECONDS=0.25
MCFIRMWARE_NO_SUDO=1
# A mismatch, occupied port or failed flash must not trigger broad recovery.
nrf52_confirm_unmatched_dfu_override() { return 1; }
prepare_serial_port_for_flash() { morse_assert_unowned "$1"; }
recover_busy_serial_port() { return 1; }
offer_serial_port_recovery() { return 1; }
offer_identity_safe_1200_touch() { return 1; }
manual_reboot_choice() { return 1; }
run_nrf52_dfu_package_buttonless "$bench_image" "$bench_port"
printf 'Application-only mcfirmware DFU completed for %s (%s).\n' "$bench_board" "$bench_serial"
