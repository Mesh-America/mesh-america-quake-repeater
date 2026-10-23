<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/companion_radio_diagnostics/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Companion radio diagnostics

Companion exposes these commands through USB terminal, the app's framed CLI
(command `0x42`, including Bluetooth), and its existing admitted admin CLI.

| Command | Result |
| --- | --- |
| `get rxps.wd` | Radio-driver recovery attempts: `soft=<count>,hard=<count>`. |
| `get radio.rxps.rfrx_disabled` | Whether duty-cycle receive suppresses the radio's external RXEN output. Unsupported radios report an error. |
| `set radio.rxps.rfrx_disabled on` / `off` | Changes that RXEN policy for this boot. The radio must have a supported RXEN pin and admit a safe reconfiguration. |
| `get cad` / `get radio.cad` | Existing CAD scan/retry/deadline information, followed by `busy=<count>` for busy-channel observations. |
| `clear stats` | Resets the same statistics as infrastructure roles: radio packet/error counts, mesh flood/direct packet counts, sticky mesh error flags, and table duplicate counters. |

RXEN changes preserve the configured receive power-saving policy and timings.
A carrier/Morse transmission, beacon, BUSY interval, transmission, or unread
packet can reject the change. If receive restoration fails, the old RXEN policy
is restored for the normal bounded receive-retry path and the command reports
an error. The setting is not saved across reboot.

Radio2 scanning suspends RX duty cycling while preserving the saved RXPS
policy. Scanning can therefore run with a saved RXPS setting of `on`; the
policy resumes after radio2 stops. CPU power saving is a separate control.

The recovery counters also include continuous-receive and liveness recovery
paths. They count attempts, not confirmed successful recoveries or CPU watchdog
resets. Compare fresh before/after readings and capture debug messages to
identify the reason for an increase.

`clear stats` retains watchdog recovery counts, airtime totals, receive activity
timestamps, queued packets, duplicate-detection history, and all saved settings.
Record a failure's statistics before clearing them; the command deliberately
clears the sticky error flags shown by `stats-core`.
