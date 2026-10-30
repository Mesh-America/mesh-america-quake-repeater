<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/companion_power_diagnostics/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Companion power and system-watchdog diagnostics

Companion text commands are available through its existing USB terminal and
framed CLI paths, with the same admission rules as other diagnostics:

```text
power
get pwrmgt.support
get pwrmgt.source
get pwrmgt.bootmv
get system.watchdog
```

`power` reports the current battery millivolts, USB power, solar charging,
external power and charger state. A board without a dedicated USB or solar
detector reports `n/a` for that field. External or charging power does not prove
that USB data is connected.

`get pwrmgt.support` reports whether the board includes nRF52 power management.
On supported builds, `get pwrmgt.source` reports `external` or `battery`, and
`get pwrmgt.bootmv` reports the boot-time voltage sample. The boot sample differs
from the live battery reading. Other builds return an explicit unsupported
reply for the source and boot-voltage queries.

On nRF52, `get system.watchdog` reports the hardware watchdog's actual running
state as `on` or `off`. It does not start or feed the watchdog. This also works
when a build disables normal watchdog feeding or inherits a running watchdog
from its bootloader. Other platforms report unsupported; this command does not
describe an ESP32 task watchdog or the radio-recovery watchdogs.

Companion normally starts and feeds its nRF52 watchdog in the application loop.
Its timeout is normally 60 seconds. Companion has no saved watchdog enable
preference, so `set system.watchdog` returns an explicit error. Infrastructure
roles retain their existing saved on/off policy. Implementing that control in
Companion would also require preference storage and feed-loop integration:
an already running nRF52 watchdog cannot be stopped directly.
