# Heltec V4 scan-first AP validation - 2026-10-06

The expanded-partition Full repeater is the recommended image for these V4s.
Minimal remains a compatibility profile for the smaller portable OTA slot;
expanded nodes do not need a second minimal variant.

Source base: `8d31b3932de614ac38d238f1a01010bc5f362fe8`, with the working changes
described below. `git pull --ff-only` reported already up to date. The tested
version is `v1.17.1.9-halo-keymind-cascade-dev-v4fix8-8d31b393`.
PlatformIO commands ran sequentially in a native WSL checkout.

## Failures and corrections

The original latest-source check reproduced a WebConfig AP that reported
startup but could not be discovered by a normal WiFi client. Earlier simulated
tests and CLI status had not proved beacon discovery, association, or the full
browser flow. Those were material coverage gaps against the reported problem.

WebConfig now removes the previous AP while preserving a shared STA/ESP-NOW
driver, scans in STA-only mode, and retains the results for the first picker
request. Startup verifies live SDK SSID, visibility, authentication, channel,
b/g/n protocol, AP-start event, IP, and absence of a STA association before
reporting success. Startup failures remain bounded by the five-second console
deadline. A failed scan is canceled before AP startup; ordinary picker requests
then return an empty result and permit manual SSID entry. Only explicit Rescan
starts another scan on that setup AP.

The pinned Arduino 2.0.17 scanner used an uninitialized `wifi_scan_config_t`.
Its active path left passive dwell and home-channel dwell fields indeterminate.
A source/version-checked middleware now zero-initializes the structure in a
private build copy. The shared PlatformIO framework remains unchanged. Before
this correction, channel-zero scans were still running after 3.6 seconds and
were canceled. Afterward, repeated all-channel scans completed in approximately
2.4 seconds and supplied cached results. This hardware comparison supports the
uninitialized configuration as the cause of that timeout.

The standard ESP32 minimal LoRa OTA profile uses the existing compact Ed25519,
SHA-512, and target-name implementations to fit its portable slot. Full and
ordinary standard profiles retain their existing implementations.

## Builds and host regressions

| Check | Result |
| --- | --- |
| Full repeater app | PASS, 2,098,744 bytes in each 6,553,600-byte A/B slot; 10 capability markers and internal memory gate passed. |
| Full SHA-256 | `d534c9d79796886fb84690c784ae985bfef6d808d5e7879409f139e9463f126d` |
| Full running body hash | `8C8A7ADBDA25501E` |
| Minimal app | PASS, 1,281,576 bytes; 29,144 bytes spare in the 1,310,720-byte portable slot; 6 capability markers and memory gate passed. |
| Minimal SHA-256 | `4f0d55aa3c0c85e76c50a2ba60738294515552dafa5e9496d6a33d73f1072e27` |
| Minimal running body hash | `060106D2CA3CA669` |
| Focused host suite | PASS, 65 Python tests, including four compiled AP fixture variants: Arduino 2/3 x open/password AP. |
| Build profile tests | PASS, `test/test_build_profiles.sh`. |

New AP fixtures exercise stale independent SDK state despite successful facade
returns, setter/readback failures, delayed AP events, shared ESP-NOW ownership,
LAN promotion, scan timeout/cancellation, cached picker results, explicit
rescans, and failed-scan manual-entry behavior. Worst modeled startup failure
is 4.59 seconds. A very slow scan can consume the retry budget, so a transient
first AP failure in that case returns a bounded failure rather than retrying.

Five new middleware tests execute the actual patched `scanNetworks` method
against an SDK capture. A poisoned-local negative control fails with the old
uninitialized source. Tests cover caller parameters, active/passive defaults,
already-running scans, private-copy isolation, and source/version guards.
Eleven existing crypto and target-name tests verify signature compatibility and
preservation of all target names/IDs.

## Physical checks

Mercerwood's Heltec V4.3 OLED repeater was identified by its exact USB serial.
Its expanded partition geometry was checked before each application-only OTA
upload. No partition table, bootloader, identity, or ACL was replaced.

| Boundary | Result |
| --- | --- |
| WebConfig, ESP-NOW off | PASS: fresh discovery, association, gzip loader, full UI, setup API, cached all-channel results, explicit rescan. Startup reply approximately 2.70 seconds. |
| WebConfig, ESP-NOW on | PASS: discovery, association, full UI/API, cached shared-channel results, explicit rescan. Startup reply approximately 0.44 seconds. |
| 2.4 GHz off/on | PASS: master off rejects individual WiFi-on; master on restores WiFi/ESP-NOW; subsequent WebConfig AP works. |
| OTA after master off and repeated startup | PASS: discovery, association, and update page. Subsequent WebConfig AP also works. |
| Actual browser JavaScript | PASS: the unmodified setup wizard opened populated networks automatically; Rescan repopulated them; manual unsaved SSID entry and picker close/reopen worked. |
| Automatic startup after reboot | PASS with WebUI temporarily enabled and no saved SSID: AP discovered/joined and setup API returned cached scan results before any manual start command. Original disabled WebUI setting restored. |
| Minimal WiFi OTA | PASS for three start/stop cycles, completed raw scans with fresh beacon age, exact-BSSID association, and the lightweight uploader page. Its raw uploader installed the supplied Full app and rebooted into its exact hash. |

Full's seven-case manual run completed without an unexpected CPU reboot.
Minimal cycles also completed without an unexpected reboot. The final node is
back on the Full hash above. All original saved preferences, public identity,
ACL, and runtime radio states were compared after restoration. The Pi's original
WiFi profile and wired route are restored, temporary profiles are removed,
serial ownership is released, and the original service states are unchanged.

The minimal profile omits manual WiFi/ESP-NOW group controls; their unavailable
responses are recorded rather than counted as master-off recovery. Full carries
that recovery qualification.

Two test-runner errors are retained in the raw evidence: an early minimal run
could not find `iw` outside sudo's path; the corrected run then incorrectly
expected automatic AP startup while the saved WebUI master was disabled. Its
five minimal/AP/upload checks and Full/settings restoration passed. A separate
enabled fresh-boot run correctly qualified automatic startup. An earlier update
and verification overlap was also corrected by a lock covering the entire Pi
test and cleanup transaction. These failures were not firmware acceptance passes.

Sanitized physical evidence is in
[`heltec_v4_scan_first_ap_2026-10-06.safe.json`](heltec_v4_scan_first_ap_2026-10-06.safe.json).
Private credentials, scanned network names, and saved secret values are excluded.

## Remaining boundaries

- 11-14 mA current consumption is unmeasured. There is no current meter in this
  setup; attached native USB and enabled USB logging inhibit light sleep.
- Requested ESP-NOW state was checked, but actual packet exchange needs a known
  second peer.
- The reported iPhone client was not available. Linux association and the desktop
  browser were tested.
- Saved-network LAN recovery after WiFi off/on was not physically retested;
  existing ownership/reconnect host tests cover that branch. This node has no
  saved SSID, and no deployment credentials were changed.
- This qualifies one V4 and its pinned Arduino 2.0.17 build. Known Arduino 3
  recipes remain unchanged by the narrow scanner middleware.

Future acceptance must include fresh discovery, association, usable UI/API,
first cached picker results, explicit rescan, and cleanup on actual hardware;
CLI success and simulated state alone are insufficient.
