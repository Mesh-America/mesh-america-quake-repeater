# Linux Chromium Web Serial after pyserial

A Station G2 browser timeout on firmware source
`1e421ff4fc6a3b56d43db7a18aab94a72129b527` was traced to the Linux host's
inherited TTY read settings. Chromium `139.0.7258.127` closed its receive stream
with `NetworkError` / device lost before the first `ver` request. The radio was
still running and an exclusive pyserial query answered in 21.330 ms without a
reset or replug. This finding explains this controlled host failure; it does
not establish that every reported USB hang has the same cause.

## Why an idle port looked disconnected

pyserial normally sets `VMIN=0, VTIME=0` and performs its timeout handling with
`select`. These kernel TTY attributes survive closing the port. With those
settings, an idle nonblocking Linux `read()` can return zero bytes.
[pyserial's POSIX implementation](https://github.com/pyserial/pyserial/blob/v3.5/serial/serialposix.py)
sets these values and closes without restoring the previous attributes.

In the exact
[Chromium 139 serial implementation](https://github.com/chromium/chromium/blob/139.0.7258.127/services/device/serial/serial_io_handler_posix.cc#L152),
port configuration preserves the prior `VMIN` and `VTIME`. Its
[receive handler](https://github.com/chromium/chromium/blob/139.0.7258.127/services/device/serial/serial_io_handler_posix.cc#L300)
interprets a zero-byte read as device loss. Setting `VMIN=1, VTIME=0` makes an
idle nonblocking read return `EAGAIN`, so the browser waits for data instead.

Upstream Chromium fixed this in
[commit 45ccdf6e](https://github.com/chromium/chromium/commit/45ccdf6e7af9b56473ab9588c44d9048a8aaf7fb)
on 2026-09-18, under bug 559872992. The change explicitly configures both read
settings and adds a real Linux pseudoterminal regression for inherited settings.
The presence of this fix upstream does not prove a particular installed browser
contains it; the Pi's tested Chromium 139 predates the fix.

## Controlled G2 comparison

The same firmware, native Pi Chromium, and unmodified official flasher console
were used for both attempts. Console source SHA-256 was
`107d3ad867915aea8b2454c324327397a0f9e2f0469656046054011bc64475f9`.
Instrumentation observed and forwarded existing native API calls.

| Attempt | Host settings and observation | Result |
| --- | --- | --- |
| 203 | `VMIN=0, VTIME=0`. The receive stream was already lost before Enter. The native five-byte `ver\r\n` write nevertheless completed in 28.1 ms. | FAIL. No displayed reply by the unchanged 5,000 ms deadline. |
| 204 | Only host `VMIN` changed to 1; `VTIME` stayed 0. The receive stream remained open. | PASS. First ordinary `ver` reply was displayed in 154.1 ms. |

No firmware or website patch, modem-signal change, reset, replug, added command
retry, keepalive, or longer deadline was used to obtain the passing comparison.
Before this comparison, `stats-core` reported uptime 1,728 seconds and error
bitmask 2; this is evidence of continued operation, not an error-free radio
qualification. The comparison does not qualify a fresh flash, a long idle
window, another host OS/browser, or every USB transport.

Safe receipt names and hashes are retained for the comparison:

| Receipt | SHA-256 |
| --- | --- |
| `stock-browser-diagnostic-203-safe.json` | `e41b0f009b8dce42ad9ee23ad843032b97a47fc2cfc5385aefbf093ac46a9788` |
| `controlled-browser-host-setting-safe.json` | `88527690ca8d8740fd415831123c45ac3249134aec3929f7fd2b0224ddbe8fce` |
| `stock-browser-diagnostic-204-safe.json` | `6ba3249a23364a589653a0a1a4abb7e453a1cb2f095cec6138f3cebc171d5f39` |

## Hardware-test preflight

The tracked
[Linux Web Serial helper](https://github.com/mikecarper/MeshCore/blob/keymindCascade/tools/hil/linux_web_serial.py)
changes and verifies only `VMIN=1, VTIME=0` immediately before a native browser
test. It requires an explicit absolute TTY path and restores the complete
original termios attributes after the browser closes, including on a Python
exception or interrupt. Failed preparation also restores the original state.
It sends no serial data and makes no DTR/RTS or USB-reset calls.

Pause other serial clients and finish all pyserial preflight queries before
entering the context. Another opener can overwrite the read settings, and a
second reader can consume the radio's reply. The helper closes its preparation
descriptor before the trial, so it does not keep the port open across the
stock browser's Disconnect action. Controllers must close their native reader,
writer and port in their own `finally` cleanup before the context exits, and
route termination into that cleanup. If the endpoint is replaced or disappears,
restoration fails explicitly rather than applying old attributes to a different
device.

Record browser version, TTY settings, native stream state/error, native write
completion, raw receive-byte count and rendered reply separately. A zero-byte
console display alone does not prove that the USB endpoint received no bytes.
For example, the stock console buffers input until a complete CRLF line arrives.
See the [HIL instructions](https://github.com/mikecarper/MeshCore/blob/keymindCascade/test/README.md#linux-native-web-serial-preflight)
for the context-manager example and the hardware-free pseudoterminal test.
