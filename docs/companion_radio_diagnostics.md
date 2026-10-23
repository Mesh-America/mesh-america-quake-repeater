# Companion radio diagnostics

Companion exposes these commands through USB terminal, the app's framed CLI
(command `0x42`, including Bluetooth), and its existing admitted admin CLI.

| Command | Result |
| --- | --- |
| `get rxps.wd` | RX power-saving recovery history: `soft=<count>,hard=<count>`. |
| `get radio.rxps.rfrx_disabled` | Whether duty-cycle receive suppresses the radio's external RXEN output. Unsupported radios report an error. |
| `set radio.rxps.rfrx_disabled on` / `off` | Changes that RXEN policy for this boot. The radio must have a supported RXEN pin and admit a safe reconfiguration. |
| `get cad` / `get radio.cad` | Existing CAD scan/retry/deadline information, followed by `busy=<count>` for busy-channel observations. |
| `clear stats` | Resets the same statistics as infrastructure roles: radio packet/error counts, mesh flood/direct packet counts, sticky mesh error flags, and table duplicate counters. |

RXEN changes preserve the configured receive power-saving policy and timings.
A carrier/Morse transmission, beacon, BUSY interval, transmission, or unread
packet can reject the change. If receive restoration fails, the old RXEN policy
is restored for the normal bounded receive-retry path and the command reports
an error. The setting is not saved across reboot.

`clear stats` retains watchdog recovery counts, airtime totals, receive activity
timestamps, queued packets, duplicate-detection history, and all saved settings.
Record a failure's statistics before clearing them; the command deliberately
clears the sticky error flags shown by `stats-core`.
