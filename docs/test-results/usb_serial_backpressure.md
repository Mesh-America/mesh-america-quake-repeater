# Native USB backpressure and radio liveness

ESP32-S2/S3 builds using native TinyUSB CDC (`ARDUINO_USB_MODE=0` and
CDC-on-boot) must not wait for a computer to read USB output. In the bundled
Arduino-ESP32 2.0.17 core, `USBCDC::write()` can wait indefinitely for transmit
space; its configured timeout bounds a mutex, not that wait. This can stop the
same loop that services LoRa, even while the USB connection still appears open.

## Firmware behavior

- Native CDC output uses a single FIFO attempt, not Arduino's wait-for-space
  write or flush. TinyUSB's internal short mutex operations still apply; this
  is a no-host-progress-wait guarantee, not a lock-free driver replacement.
- Functional text and diagnostics share one ordered 4 KiB queue. Diagnostics
  leave 3 KiB reserved for commands. A diagnostic backlog alone does not prevent
  command input. A stalled host may lose diagnostic records; radio work continues.
- A connected terminal that exceeds its bounded output capacity gets an explicit
  dropped-byte notice when transmission resumes. Large local file dumps and
  recent-repeater listings advance between radio service passes instead.
- File dumps stop at their initial file size and emit `-> EOF` only after the
  final accepted record. Corrupt stored lines exceeding 640 bytes are omitted
  with a visible notice. Recent-repeater output is a live, bounded-cursor view;
  incoming packets can change its ordering while it is being printed.
- Disconnects discard pending old-session text and reset the role's partial
  command/listing state. Binary/mOTA transitions suppress pending text notices.
  Bytes already transmitted cannot be recalled.
- Companion frames retain and retry short writes. An mOTA request is admitted
  only when its complete, at-most-11-byte record fits.
- nRF52, UART, and USB-Serial-JTAG behavior is not changed by this native-CDC path.

Host software must also keep reading independently of command writes. A serial
relay should start its reader before the first command, use finite write and
response deadlines, avoid discarding received packet logs, and cancel I/O during
shutdown. A response timeout must not allow a late reply to satisfy another
command: the CLI has no transaction identifiers. Updating firmware alone does
not correct an indefinite host-side serial write.

## Regression checks

Run only one PlatformIO process in the checkout at a time.

```sh
python test/test_esp32_tinyusb_nonblocking.py
python test/test_esp32_usb_session_fix.py
python test/test_esp32_tinyusb_role_hygiene.py
python test/test_esp32_tinyusb_cooperative_output.py
python test/test_esp32_usb_serial_hygiene.py
python test/test_nrf52_usb_logging_contract.py
python test/test_nrf52_usb_lifecycle.py
python test/test_common_cli_logging_transaction.py
python test/test_companion_usb_logging_reply.py
python test/test_usb_diagnostic_logging.py
pio test -e native -f test_nrf52_debug_output -f test_serial_packet_log -f test_serial_mode_switch -f test_mesh_tables
```

The first test compiles the real USB facade against a simulated 64-byte FIFO,
including stopped readers, reconnects, protocol transitions, and other-platform
fallbacks. Host simulations cannot establish that every real USB driver or
endpoint failure has recovered.

A Full Station G2 validation build with USA Cascadia radio settings and the Cascade
profile can be made using the normal build entry point. The portable `standard`
recipe preserves the deployed partition layout but omits LoRa OTA; it still has
the browser firmware uploader. The `auto`/`full` recipe instead enables the
expanded feature set and partition layout: its merged image is **not** an
app-only update for a device with the legacy layout.

```sh
MESHDEBUG_OVERRIDE=on PACKET_LOGGING_OVERRIDE=on \
  bash build.sh build-firmware Station_G2_repeater --build-profile full \
  --radio-preset usa-cascadia --profile cascade
```

Before installing on hardware, preserve the device identity, preferences, and
existing partition layout. Then verify USB command responses and repeated LoRa
logins with the relay running, paused, and stopped, including a host that leaves
USB open without reading. Check LoRa recovery separately from USB OUT recovery;
fixing transmit backpressure does not prove an unrelated OUT endpoint fault is
resolved. Do not erase or repartition the radio as part of this test.

## USB logging ownership and session recovery

On a single-port Companion, enabling USB logging parks framed USB traffic
before opening the diagnostic gate. A TCP/browser terminal retains its CLI
ownership; USB is log-only during that session. Disabling logging restores USB
traffic without accepting bytes typed during the log-only interval. A dedicated
nRF52 logging port does not park the separate Companion port.

A framed USB logging command retains its original requester and queues its
acknowledgement before changing ownership. The handoff advances without waiting
for the host: live logging stays unchanged while the complete USB reply is
backpressured. Disconnect/reset cancels that session's pending handoff; an
already-saved preference can still take effect at the next boot. BLE/WiFi replies
are never used as a fallback for a refused USB acknowledgement.

On native ESP32 TinyUSB, build-local framework hooks capture DTR and USB session
boundaries synchronously in the USB owner task, before Arduino's delayed events.
They purge old input at the boundary and reject late input while DTR is low,
without deleting a new host's first query during main-loop cleanup. An armed
old IN packet (or a racing writer) triggers immediate soft-disconnect, a minimum
20 ms detached interval, and quarantine until fresh enumeration. Shared SDK
files are not modified; a changed native-CDC descriptor fails the build closed
until the hook is reviewed. This path is specific to the pinned Arduino-ESP32
2.0.17 native CDC implementation; hardware Serial/JTAG and UART are unchanged.

Disabling diagnostics is not itself a protocol change and does not discard
functional replies from the shared ESP32 text queue. Actual Binary/mOTA changes
use the explicit terminal-output barrier. Touch and invalid-Ethernet-hostname
diagnostics also honor the runtime logging gate and bounded USB stream.

Ethernet and enabled MQTT diagnostics honor the runtime logging gate and use
the bounded USB facade. Infrastructure logging setters commit preferences
before changing live output; failed saves leave previous settings unchanged.
A successful save with a failed MQTT runtime change reports those two outcomes
separately.

ESP32 native-USB repeater and room ACL listings retain short-write suffixes and
advance one row per service pass, using their existing output buffer. Reconnect
cancels the old listing. The listing is a bounded live view, not an immutable
snapshot of clients changed during output.

Stored dumps make progress even when HWCDC falls back to 256/512-byte TX rings.
Recent-repeater headers/rows and EOF retain every unwritten suffix; a short
write never causes their accepted prefix to be retried.

nRF52 FIFO cleanup also checks for an already-armed IN packet. If one exists
at a session boundary (including a pending zero-length packet), both USB ports
briefly detach and re-enumerate: a FIFO clear alone cannot recall endpoint RAM.
Reattachment waits for the local unplug event and a 20 ms minimum interval,
without blocking the mesh loop. Dedicated CDC descriptors are added while
detached even if the host has not yet completed enumeration. These recovery
paths have native regression coverage; real host/board timing still requires
hardware qualification.

The nRF52 callback only drops the pull-up and closes producer gates. The
application loop sends the stack's unplug event afterward, so a full owner-task
event queue cannot make its consumer wait on itself. The detach interval starts
when that application-side stack detach actually occurs. A regression models a
full finite event queue as well as the separate armed endpoint packet.

## Local qualification (2026-10-03)

- All 112 USB Python regression methods passed, plus nine logging-transaction,
  Bluetooth-control, and WiFi-status methods. The native facade includes a
  threaded close-versus-writer race and an unmount-with-reset-endpoints check.
- `Xiao_S3_companion_radio_usb` built successfully with its default hardware
  Serial/JTAG transport: 880,709 flash bytes and 73,244 static RAM bytes.
- A native-TinyUSB Xiao S3 USB Companion qualification build passed with debug
  and packet logging enabled: 928,133 flash bytes and 89,312 static RAM bytes.
  Its linked ELF contains the synchronous session hooks and endpoint query.
- A RAK4631 Full Companion qualification build with two CDCs, debug/packet
  logging, and USB/BLE mOTA sources passed: 678,092 flash bytes and 154,428
  static RAM bytes. The runtime RAM and Bluetooth DFU safety checks also passed.

The two custom qualification builds used the lab profile
`909.5 MHz / 500 kHz / SF5 / CR5`. No board was flashed, and no physical
disconnect/reconnect or hardware endpoint recovery was claimed by these checks.
