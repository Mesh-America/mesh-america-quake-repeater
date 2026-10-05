# ESP32 native browser console startup - 2026-10-05

This is a local validation report, not a release approval. No GitHub upload,
website deployment, or release publication is part of these results. The GUI
time-sync connection timeout was reproduced on native USB. After the boot
filesystem correction, the unchanged GUI's first fresh-flash connection passed
on both the Heltec V4 and XIAO ESP32-S3. The final V4 600-second idle run also
passed with power saving on, logging off, and no transmitted command during
idle. Earlier terminal runs establish different boundaries and are recorded
separately. The V4 core error counter increased during idle and is retained
below; this is not a claim of error-free radio operation.

A later user screenshot identifies the affected surface as the Repeater / Room
server USB setup GUI at `config.meshcore.io`, with `Cannot connect: Command
timeout: time <epoch>`. The initial physical observations used the terminal at
`flasher.meshcore.io/console`. Native tests of the actual GUI were added after
identifying that mismatch and are recorded separately below.

## Native test boundary

The physical target was a Heltec V4 ESP32-S3 Repeater attached to Mercerwood.
Chromium 154.0.8037.92 ran on the Pi and used its actual OS Web Serial backend,
native SerialPort objects, and native readable/writable streams. Playwright
drove the full Vue website and recorded the UI and loader lifecycle. This is
additional coverage beyond the physical Linux serial/Node Web Streams tests in
[the earlier OTA report](hardware_validation_esp32_web_console_ota_2026-10-05.md).

The baseline firmware source was `7821329851f69b6b945f061bc4d15212d43c3198`.
The unchanged website was pinned to upstream commit
`45a5257bf792b11a83f4c51c18d4f312addfb677`. Source hashes were checked before
flashing, including these production files:

| File | SHA-256 |
| --- | --- |
| `lib/console.js` | `107d3ad867915aea8b2454c324327397a0f9e2f0469656046054011bc64475f9` |
| `js/flash.js` | `e9762a29f6a91f8e33736e02ff41a81cd49e7b96fe253a5d71cba7daefd46d5b` |
| `lib/esp32.js` | `2a896d5e520ea9b6ea9900223c2460df797c3b2287f441daa4e50168a50b17e6` |

Only the unavailable headless permission chooser was replaced with selection
of the single, already granted V4. Before each application-only flash, native
ROM reads checked the 4096-byte partition table and OTA metadata. The table
hash was `9af3af2b74e944337ba85f2b0027ee80df160579a1ab746ba0f95853f618cd60`;
valid OTA sequences 3 and 4 selected `app1` at `0x650000`. The UI's application
address was changed to that verified active slot. Full erase was disabled.
The actual stock loader write, native reset sequence, and disconnect remained
unchanged. No filesystem erase or additional backup was needed.

In the initial terminal experiments, the first command was sent after native
open resolved with a 30-second deadline. The actual setup GUI kept its stock
5000 ms command deadline. No arbitrary startup sleep, extra reset, unplug/replug, keepalive,
or automatic command retry was added to turn a failure into a pass. A first
failure would remain a failure even if a separately recorded reopen recovered.
USB-open readiness and firmware reply latency are separate measurements.

## Completed physical observations

| Check | Observation |
| --- | --- |
| Baseline fresh application flash, same native port handle | PASS. The first `ver` reply took 9398 ms. Subsequent power-saving and core-stat queries passed. No unplug or additional reset was needed. Progress 100 preceded `flashEsp32` completion by 604 ms. |
| Baseline power saving on, logging output off, 600 seconds idle | PASS with no transmitted command or keepalive during the idle interval. The post-idle `ver` reply took 5544 ms. Uptime advanced from 119 to 741 seconds, so the MCU did not reboot. Power saving remained on and logging remained off; temporary settings were restored afterward. |
| Stock website Close clicked immediately at the success heading, live site | PASS after reload; first `ver` took 1558 ms. The heading appeared 61.8 ms after progress 100, while both native streams were still locked. The original document continued through reset and disconnect; disconnect finished 987.3 ms after progress 100. |
| Same Close test with identical pinned HTML served locally at the official origin | PASS after reload; first `ver` took 1418 ms. The heading appeared 33.5 ms after progress 100 with both streams locked. Reset/disconnect still completed before navigation replaced the original document. The served index, app, and console hashes matched the unchanged pinned source. |
| Actual browser tab closed at the stock success heading, new tab in the same profile | PASS; first `ver` took 1575 ms. The tab-close request was emitted 126.5 ms after progress 100 with both streams locked. Reset and disconnect had not completed before that request. This used normal `Page.close(run_before_unload=False)`, not the website Close/reload handler, browser shutdown, or a renderer kill. |
| Local fixed terminal UI `452e6e7`, final startup firmware `163364e52`, actual tab close and 600 seconds idle | PASS. Completion was exposed only after reset/disconnect, with native readable/writable streams already absent. First `ver` took 1408 ms; the post-idle reply took 1064 ms with power saving on and logging output off. Core-stat queries and preference restoration passed. This is terminal qualification, not GUI qualification. |

The stock completion display is demonstrably premature: progress 100 does not
mean the loader has finished its tail, reset, and port release. However, both
site Close tests and the actual tab-close test passed on this physical V4.
The mock's canceled-tail ordering is not evidence that the physical device was
left permanently hung. In particular, the tab-close request time is not the
same as the time Chromium finished closing the target.

The qualified fresh-flash application SHA-256 was
`912c1c5d80497de04a4ebd5d3a81b9275181ab2bb3bfb7f22e74c692ef0c5d8a`.
The three completion/close experiments used the 2,093,336-byte application
`ebee70b05528b21aaaeddf8bc80f2762b7ad767ff5b6f29eadf8e2a78e90859d`.
Those terminal-only baseline passes did not establish a failing-baseline /
passing-fix comparison for the affected GUI. The later unchanged-GUI comparison
below provides that first-connect evidence.

## Firmware startup correction and synthetic coverage

The startup changes are local firmware commits:

- `68a27a2eb`: preserve initial HWCDC enumeration and the first console session
  on the pinned Arduino-ESP32 2.0.17 C3/S3 driver.
- `a4e3a530c`: capture startup reset classification in the pinned 3.3.11 ISR.
- `163364e52`: apply the same capture-only classification to the pinned 3.1.3
  ISR used by the built XIAO C6 environment.
- `c8c5f87ab`: make ESP32 GPS discovery cooperative instead of blocking setup.
- `0b9a80d7e`: avoid repeated missing SPIFFS scans with a boot-only validated
  absence inventory; existing-file reads and mutations use the native backend.
- `631f2ad97`: check inventory lifetime and ordinary ESP32 build inclusion.

The startup predicate is captured when the native reset interrupt occurs,
before delayed framework delivery can reclassify an initial enumeration as an
active-session reset. Boot diagnostics and early RX do not end startup. The
first application command-service loop ends startup; resets afterward retain
the existing quarantine, queue purge, and session cleanup. Early command RX is
retained until that loop can service it.

Delaying hardware USB data attachment through application setup is not a safe
way to hide this startup boundary from the stock flasher. After progress 100,
the unchanged loader still needs the native interface for RTS/reset and port
cleanup. Withdrawing that interface during its tail can break the handoff.
The selected correction keeps the transport available and retains first RX
until command service is ready instead of forcing another physical reconnect.

Synthetic tests execute the pinned real driver ISR, production owner predicate,
event handling, and session cleanup against host peripheral/RTOS stubs. They
cover early and delayed enumeration, boot TX, boot RX, first-command retention,
and a real reset after application readiness. Negative controls remove the
startup gate, remove capture-time classification, arm on boot traffic, or leave
startup suppression active forever. The removed protections cause the expected
failures. Driver source pins, mode/version scope, unchanged SDK files, and
idempotent build-local transforms are also checked.

The startup synthetic suites and V4/C6 builds passed. The earlier V4 full
Repeater build at `163364e52` passed its linked capability and memory checks.
Its application hash is
`41ed8598aa2fb1b7aa5d320157249dc03a6e543051257c8b1d7d34d8e4c26df6`.
The 3.x transforms only add startup reset classification; they do not import
the 2.0.17 TX/PHY backport or claim its guarantees. Unreviewed framework
versions keep their existing driver. C6 ISR tests and compilation do not
substitute for physical C6 qualification.

Five sequential qualified builds passed at source base `631f2ad97`, with the
local test version `v1.17.1.9-hil-bootfs-631f2ad9-631f2ad9`. Their generated
capability/memory reports and application artifacts were retained privately.
This test version is not a published release.

| Requested build | Resolved environment and scope |
| --- | --- |
| Full `heltec_v4_repeater` | `heltec_v4_repeater_observer_mqtt`, PASS |
| Full `Xiao_S3_WIO_repeater` | `Xiao_S3_WIO_repeater_observer_mqtt`, PASS |
| Full `heltec_v4_room_server` | `heltec_v4_room_server_observer_mqtt`, PASS |
| Ordinary `Xiao_C6_repeater_` | Complete supported profile with pinned Arduino-ESP32 3.1.3, PASS |
| Explicit Full XIAO S3 Companion | `Xiao_S3_WIO_companion_radio_full`, PASS |

The two physical unchanged-GUI first-connect passes below used the S3 Repeater
images. The Room server and C6 results in this table qualify compilation and
packaged capabilities, not physical GUI operation on those targets.

## Local website correction and browser tests

Website commit `452e6e7` is local in a separate flasher checkout; the pinned
baseline source remains unchanged and the website has not been deployed.
Its three production changes are limited to `index.html`, `js/app.js`, and
`lib/console.js`:

- Show completion and expose Close only after the complete flash helper has
  finished reset/disconnect. Progress 100 alone shows restart in progress.
- Disable input until native open provides usable streams; report open,
  command, and disconnect failures explicitly.
- Recover a documented nonfatal RX error only when Web Serial supplies a fresh
  readable stream. Fatal errors disable input and require explicit reconnect.
- Release writers in `finally` and await actual read/write cleanup before
  closing. An uncancelable write reports a busy port rather than claiming
  success; the timeout is bounded per operation, not guaranteed cancellation.

All 16 full Vue/Chromium lifecycle tests passed, including five negative
controls. They run the production UI, console, Web Streams, and flash/reset
wrappers with mocked USB peripherals and loader data transfer. The immediate
Close test uses a DOM MutationObserver so locator delay cannot miss the early
completion race. Coverage includes delayed/failed open, nonfatal RX recovery,
fatal RX, rejected writes, cancelable and uncancelable pending writes, slow
reader cancellation, close errors, and flash-tail failure. The five controls
restore progress-only completion, early editable input, missing RX recovery,
missing writer cleanup, and the old fixed 50 ms close delay. Each fails for
the intended missing protection. These tests establish client lifecycle
behavior; they do not reproduce the user's physical hang.

## Actual setup GUI handshake and regression comparison

The live setup GUI matches upstream `meshcore-dev/config.meshcore.io` commit
`aff42ad8ef2b332f24d644ff6a783f8272a88ff2`. The initial path is GUI Connect ->
native port open at 115200 -> held reader/writer -> `time <epoch>` -> getData.
There is no explicit DTR/RTS call on GUI open. The command is ASCII followed by
CR only. Its 5000 ms timer is armed before awaiting native writer.write, so both
write completion and response parsing must fit that deadline. The firmware
Repeater parser accepts CR and ignores LF; CR-only is a supported input path.

| GUI source | SHA-256 |
| --- | --- |
| `index.html` | `efd64d1b56d57988fc4108f3f84efc943ed4c42ade4e4dbf8139c46fb3c0476d` |
| `src/gui.js` | `919034806e903fbc41e29a367a7d854837f6520f47aa34e5d0618f5dd3d29800` |
| `lib/serial-cli.js` | `fbfbdcfa8bf1a372a0396d342e018ba8ee83d33b7b98c3a546fd37cd7e8ce870` |

The actual GUI page is preloaded before a separate tab runs the unchanged stock
flash backend. After that backend returns, the GUI Connect button is clicked
without reloading the GUI, inserting a settle delay, or changing its timeout.
Each official origin is granted only the single intended native device. Raw GUI
debug output and app.device are not retained: getData reads private keys and
passwords. Lifecycle observations record command categories, byte counts, locks,
timeouts, and safe numeric statistics without secret values.

Completed GUI configuration reads mean the unchanged getData flow returned and
the GUI became connected. They do not exhaustively validate every field: the
stock GUI can catch optional private-key, region, and ACL errors or skip an
unsupported variable. The final XIAO run recorded no command-error events and
completed its radio, region/default, and ACL commands as well as initial time.

| Actual GUI run | First attempt and separate recovery |
| --- | --- |
| V4 `163364e52`, fresh flash | FAIL. Initial time timed out at 5022 ms, and explicit stock cli.disconnect followed by GUI reconnect timed out at 5007.3 ms. Writes themselves completed in 4.7 and 29.3 ms. Only 147 boot RX bytes arrived; no command echo or reply marker was observed. Both locks remained held and GUI connected remained false. |
| Same V4 source, separate settled no-flash control | PASS. Initial time completed in 50.2 ms and the full GUI configuration read completed. This was a separate control, not a successful first fresh-flash attempt. |
| V4 cooperative GPS source `c8c5f87ab`, fresh flash | FAIL. Initial time timed out at 5024 ms. A separately recorded clean reopen completed time in 3336.2 ms and the full GUI read passed. Recovery does not change the first-attempt result. |
| Local XIAO ESP32-S3 Repeater, fresh flash | FAIL. Initial time timed out at 5001 ms. Separate clean reopen completed time in 3983.4 ms and the full GUI read passed. Native local Chromium and the target's own verified partition/active slot were used. |
| Same local XIAO, separate settled no-flash GUI control with 600 seconds idle | PASS. The initial GUI time completed in 9.9 ms and the full configuration read passed. With power saving on and logging off, no native writes occurred during the 600-second idle interval. Uptime advanced from 177 to 777 seconds, errors stayed at 0, and a visible GUI disconnect/reconnect reread passed. Original preferences were restored. This does not change the failed fresh-flash first attempt. |
| V4 normal, untraced firmware `631f2ad97`, fresh flash and 600 seconds idle | PASS. Initial time completed in 420.7 ms and the full unchanged GUI read flow completed. With power saving on and logging off, zero native writes occurred during 600 seconds idle and uptime advanced from 18 to 618 seconds. Core errors increased from 0 to 8. Visible GUI Disconnect/Connect completed a full reread, original preferences were restored, and final awaited Disconnect left port/reader/writer absent. |
| XIAO normal, untraced firmware `631f2ad97`, fresh flash | PASS. Initial time completed in 3110.6 ms and the full unchanged GUI read passed. Core statistics reported uptime 4 seconds, errors 0, and queue length 1. No diagnostic reopen, extra reset, unplug/replug or timeout change was used. Final visible Disconnect completed with port, reader and writer absent. |

The native V4 failure is not just a pending write: both writes completed quickly.
The second attempt began about 10.48 seconds after the stock flash backend had
returned and still failed on `163364e52`. A five-second GPS wait alone therefore
does not explain every observation. Cooperative GPS discovery removes that real
startup block, but its first GUI attempt still failed physically. That remaining
gap required the direct startup-phase diagnosis below.
The short GUI deadline and the terminal's 30-second test deadline are material
differences in coverage.

The final driver preserved the original command order and native calls. Source
checks, permission selection, and ROM preflight occurred before application
flashing; no settle sleep or additional USB operation was inserted after the
stock flash backend returned. Automation and native-open latency are separate
from the time command's elapsed response measurement: the final XIAO time began
about 71 ms after backend return, while the V4 time began about 3586 ms later.
Their 3110.6 ms and 420.7 ms reply times begin at command entry. Passing these
cases does not claim that native port open or first command always occurs at
zero elapsed time after a flash.

The final V4 application SHA-256 was
`ffb0a00b97b382038db758954a38af464efe6b00bb88784936f9cc7c4b54db39`.
Its final run recorded no client command-error events and no diagnostic reopen.
The final XIAO application SHA-256 was
`b00ffbd0b7154f29741c3d93110705b33d3d34dcfa392ba7bd0e8e03d8cac9ce`.
Its verified partition table hash was
`f4e3b6cfe370c81dca210d57f3c463f924a539842a19fff6eda4615278ee97a2`,
with parsed active `app0` at `0x10000`; the image fit that slot. Native Chromium
140.0.7339.186 ran locally on the VM. The V4 used the Pi's native Chromium.

In the stock GUI, a failed handshake alerts without disconnecting. The visible
connected state stays false, while the native reader and writer remain owned.
Retrying Connect can therefore encounter its own still-open port. The explicit
cli.disconnect/reopen in these experiments is separately labeled diagnostic
recovery, not an automatic retry added to the user's first handshake.

The hardware-free full Vue reproducer also shows the exact time alert when the
mock initial write is delayed 9400 ms. The stock 5000 ms deadline fails while
the native-style writer is pending; a separate runtime 15000 ms deadline control
completes the same time command. That control is an ordering proof, not an
unchanged-client fix or a reproduction of the native cause.

New CI coverage in `test/test_official_config_gui.py` executes the full SHA-pinned
stock SerialCLI and the exact GUI connect/disconnect functions in Node. Actual
production GPS init elapsed time controls command admission, and the production
Repeater command pump/CommonCLI time branch generate byte-fragmented replies.
The actual boot filesystem inventory and production recovery/presence paths
also supply a deterministic metadata-cost workload. Its absent native scans
cost 129 ms each plus 1000 ms setup settle: one inventory scan yields 1129 ms,
while the same workload without inventory performs 40 scans and yields 6160 ms.
These are modeled readiness costs, not predicted full physical boot times.
All six tests passed in local commit `b259b1055`. The four negative controls
restore blocking GPS, omit inventory, replace the CRLF reply with LF, or regress
CR command recognition. Each fails at the stock client-visible 5000 ms
initial-time boundary. getData is a callback witness there; full Vue fields,
enumeration, and other physical setup latency still require the native tests.
No complete third-party bundle is vendored.

The diagnostic V4 phase run retained its first time failure at 5026.1 ms and
separate recovery at 2136.8 ms. Recovery core statistics reported uptime 16
seconds, errors 0, and queue length 1. The firmware's own millisecond phase
timestamps locate setup work before the first CLI service:

| Measured startup phase | MCU interval and elapsed time |
| --- | --- |
| Sensors | 2815 -> 2829 ms, 14 ms |
| Dispatcher | 2829 -> 3714 ms, 885 ms |
| Preferences | 3714 -> 8261 ms, 4547 ms |
| Management state | 8261 -> 9941 ms, 1680 ms |
| ACL | 9941 -> 11104 ms, 1163 ms |
| Regions | 11104 -> 11362 ms, 258 ms |
| Filters | 11362 -> 12781 ms, 1419 ms |
| First CLI entry, ready admission, and available RX | All at 12796 ms |

No blocked CLI admission was reported before that first readiness; the first
blocked-gate marker was later, at 14147 ms. The measured setup duration, rather
than a new reset requirement or the GPS block alone, was the baseline first-time
deadline problem. These trace intervals identify where to investigate; they do
not by themselves prove a particular filesystem or CPU cause, or qualify an
faster startup path. Qualification of that correction came from the subsequent
unchanged-GUI first passes, rather than from trace intervals alone.

A qualified second run of the same granular trace application recorded the
inner preference and management phases. It retained the initial time failure
at 5024.1 ms and a separate recovery at 1787 ms; recovery core statistics were
uptime 17 seconds, errors 0, and queue length 1. Its first CLI service was at
12805 ms. The earlier trace does not contain these inner markers.

| Qualified inner phase | MCU interval and elapsed time |
| --- | --- |
| Radio profile lookup | 3714 -> 4232 ms, 518 ms |
| OTA speed lookup | 4233 -> 4492 ms, 259 ms |
| Display settings lookup | 4492 -> 5010 ms, 518 ms |
| Common preference recovery | 5010 -> 6571 ms, 1561 ms |
| Existing common preference image, open through completed load | 6572 -> 6576 ms, 4 ms |
| MQTT preference recovery/read | 6577 -> 8266 ms, 1689 ms |
| Management route lookup | 8267 -> 9043 ms, 776 ms |
| Absent management reporter probes | 9043 -> 9561 ms, 518 ms |

These measurements separate slow missing-path metadata scans from the quick
read of an existing preference image. No management reporter was allocated.
The correction is a boot-only validated absence inventory, so known
absent files can avoid repeated scans while existing-file reads, recovery,
and mutation invalidation keep their native behavior. A failed or incomplete
inventory falls back to native probes; existing-file errors remain delegated.
Known absence is witnessed by the completed enumeration, so those cached
negative lookups intentionally perform no later per-path metadata operation.
The actual inventory negative controls and both normal-firmware unchanged-GUI
first fresh-flash passes qualify the tested startup boundary.

## Final XIAO role restoration

The local XIAO was restored to the latest tested Full Companion image at source
`631f2ad97`, application SHA-256
`cf77ff2824f8359ab5e690424e5d6181911f401f0fe7b9a827550f13c0610e2c`.
Native ROM preflight checked the target, partition table and OTA CRC selection
of `app0`. The filesystem and partition table were preserved.

Settled USB verification passed 60 requests with zero missed 2-second deadlines
and maximum reply latency 7.152 ms. It covered ten held app/core pairs, ten
reopen pairs, and ten seconds idle. The identity hash matched the recorded
original, settings hashes remained stable, no input flush was used, and all
serial handles closed. This restore check includes the helper's existing
250 ms open-handshake wait; it is not the fresh GUI's 5000 ms startup proof.

## Qualification and limits

The affected first-connect timeout has a failing baseline and passing corrected
normal-firmware result on both tested S3 boards. Diagnostic HIL_BOOT tracing was
off in those passing images. The GUI timer and reset/reconnect behavior remained
unchanged.

The final V4 fresh-flash 600-second idle test completed its uptime checks,
configuration reread, preference restoration, and awaited final disconnect.
The core errors counter increased by 8 while USB remained responsive; these
results do not establish zero radio errors or diagnose that counter's origin.
The XIAO Full Companion restoration is complete.

The local XIAO unchanged-GUI 600-second no-transmit idle control completed
successfully with power saving on and logging off. Its successful initial
settled handshake, uptime/error checks, full GUI reread, and preference
restoration are separate from the failed first fresh-flash handshake. The
already completed fixed-terminal 600-second run is also separate evidence.

These results do not qualify every host OS, USB adapter, cold power cycle,
firmware role, high logging volume, or physical ESP32 board. A matching initial
GUI timeout was reproduced and the tested first fresh-flash boundary now passes;
idle results apply only to their measured configurations and intervals.

## Evidence retention

The completed sanitized reports are retained privately under
`/tmp/meshcore-hil-20261004/web-console-investigation`. This document contains
no credentials, device identities, or raw console logs. Completed native reports
and their SHA-256 hashes are:

| Safe report | SHA-256 |
| --- | --- |
| `pi-chromium-baseline-fresh-flash-qualified-safe.json` | `d01b18ce6a467f704605832d7a8adc1653999718f7cb4e23d11a9dd9d7bbc414` |
| `pi-chromium-baseline-power-idle-600-safe.json` | `100d609d7a448ee223a86ec4ac6b2e14362f86d44ee2670b407815eff7c1b66d` |
| `pi-chromium-stock-ui-immediate-close-safe.json` | `32bcc0a67ea7716e2a0a0f60bf9081c4d2800bac3a8fe61f3595ee5d34b077c0` |
| `pi-chromium-stock-ui-fast-reload-close-qualified-safe.json` | `b44e5d4885bb598596d021342692292c55c3f6f7a426c532845742caf8cb7e18` |
| `pi-chromium-stock-ui-tab-close-safe.json` | `13557189ba0b68bb28837cc88b108d2df1536e583b96199027edeef307a7cadc` |
| `pi-chromium-fixed-ui-final-firmware-idle-600-safe.json` | `e1b3f14e5ae6d0762fc44ab4dc28b4b41a231415cae54b4cc5332f75bd46d926` |
| `pi-chromium-config-gui-baseline-fresh-flash-qualified-safe.json` | `7abf519696c55d5af14d59c6781c644d7016d36f13d7c05833c23ce82b16f041` |
| `pi-chromium-config-gui-baseline-settled-control-safe.json` | `da85499cebfddac700696cdfdf9ad6d96970932801af469552a2d91899c3a637` |
| `pi-chromium-config-gui-gps-fixed-fresh-flash-safe.json` | `06c5525d66134cbbb460bf9e4e37e7ec74275559f1727f52cef889f074829e40` |
| `local-chromium-xiao-config-gui-fresh-flash-safe.json` | `aa6c945f3d2c40b0db3e368a905ba38ab1a4d966f0d15b4d5848fccc88ff4f2b` |
| `local-chromium-xiao-config-gui-settled-idle-600-safe.json` | `3e7b996f13978574c77819ab80132d5c4452f8c7490ebb55333c124887f903bb` |
| `pi-chromium-config-gui-startup-trace-fresh-flash-safe.json` | `8062dfcdb202a2320c430e9f013f9510392f090a0883dc8fadbc296c92a46eed` |
| `pi-chromium-config-gui-startup-granular-qualified-fresh-flash-safe.json` | `10b269c68ef1e56a6104376d6c0b4f671bbe230ec005425a09cc7805953e07b0` |
| `local-chromium-xiao-config-gui-bootfs-fixed-fresh-flash-safe.json` | `b94a53a4d017e95688c0231474c0aa0c67bc091b5738e0100173441d108db262` |
| `pi-chromium-config-gui-bootfs-fixed-fresh-flash-idle-600-safe.json` | `8419f294aeeed087a43c1f062a109da2770f2dcfa79c52ac8aae72d82250cb05` |
| `bootfs-xiao-companion-restoration/flash-safe.json` | `ae72ae2e3645735e44d46cb4d4a21920b7f669edb5571151e3a28ebafb89848c` |
| `bootfs-xiao-companion-restoration/strict-USB-safe.json` | `a8c56c8b7030ca5b5d18eed55f012e7227c9d234427e9e7df7e261b9cabb4dfa` |

The host reproductions are `browser-console-lifecycle-mock-safe.json` and
`browser-flash-ui-early-completion-safe.json`. Their mocked peripheral and
write-tail boundaries are recorded separately from native physical evidence.
The GUI timing control is
`config-gui-investigation/gui-startup-timeout-mock-safe.json`. Earlier GUI safe
reports used an overly strict observational `time_reply_ok` equality check for
plain `OK`; production returns `OK - clock set: ...`. That metadata flag was
corrected to accept the prefix and never controlled first-connect PASS/FAIL.
