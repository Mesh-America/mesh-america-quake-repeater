<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/other_board_radio2_fast_switch_2026-10-23/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Other-board radio2 fast switching, 23 October 2026

Status: **PARTIAL. Buffered SPI improved switching, but the 500 us maximum
objective remains unmet. XIAO's witnessed RF test missed one packet.**
MeshTower and Tag passed their finite 200-packet RF tests. Final-source XIAO
and Tag Companion command and Bluetooth tests passed while both receive
profiles remained active. XIAO was restored to the final Repeater image.
The RAK Full build correction and its capacity checks passed.

This campaign covers five baseline/DUT boards, additional fixed witnesses,
and three explicitly enabled nRF52 fast-SPI candidates. It does not qualify
all 13 radios, CPU sleep, electrical power consumption, or every firmware role. MeshPocket and SenseCAP Indicator
are excluded. The new XIAO, Tag and MeshTower fast transports remain opt-in;
these results do not promote them to production defaults.

## Candidate transport scope

| Board | Tested role | Explicit candidate | Controller ownership |
| --- | --- | --- | --- |
| Seeed XIAO nRF52 | Repeater, then Full Companion | Buffered 8 MHz on SPIM2 | Global SPI remapped together with its driver; QSPI flash remains separate |
| RAK WisMesh Tag | Full Companion | Buffered 8 MHz on SPIM1 | Dedicated audited radio mapping |
| Heltec MeshTower V2 SD | Full Repeater with SD and no external sensors | Buffered 8 MHz radio on SPIM1 | SD remains on SPI1/SPIM2; SD features retained |
| RAK4631 | Existing Repeater baseline | Prior 2 MHz byte transfers retained | Other peripherals can own the proposed alternate controller |
| Heltec T096 | Existing Full Companion baseline | Prior 2 MHz byte transfers retained | Display/controller ownership still needs a separate safe mapping |

Retained ELF inspection verifies the actual SPI controller, buffered transfer,
8 MHz descriptor and absence of the global protected SPIM3 anomaly-198
workaround in the candidate images. These proofs establish linked behavior;
they do not replace the physical tests below. See also the separate
[RAK3401 campaign](rak3401_radio2_fast_switch_2026-10-23.md).

## Timing observations

Every short timing observation used these same two RX profiles:

| Profile | Frequency, MHz | BW, kHz | SF | CR | Preamble, symbols |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary | 917 | 62.5 | 7 | 5 | 32 |
| Secondary | 918 | 500 | 5 | 5 | 200 |

The measurements cover the complete RX-to-RX switch path, including admission,
standby, changed modem parameters and restarting receive. They are not bare
PLL-lock measurements. Each short window lasted 20 seconds and reached four
self-test samples in each direction; the firmware still labelled the timing
self-test pending. The displayed guarded budgets below were provisional and
include a rounded-up 10% margin. Larger samples occurred during longer RF
campaigns, so the short maxima are not worst-case guarantees.

| Original installed board / role | Source | Maximum, us | Provisional budget, us |
| --- | --- | ---: | ---: |
| XIAO Repeater | `8b5660b0` | 916 | 1008 |
| RAK4631 Repeater | `adb11e7b` | 916 | 1008 |
| Tag Full Companion | `08650f64` | 947 | 1042 |
| T096 Full Companion | `4773ac42` | 947 | 1042 |
| MeshTower Full Repeater SD | `ebb59d48` | 947 | 1042 |

RAK4631, Tag and T096 retained pre-existing core flags of 8 during those old
baseline observations; MeshTower retained 2. No new flags appeared in those
windows. The new XIAO, Tag and MeshTower candidate observations began and ended
with core flags zero. Baseline timing completion is not a full health pass.

| Candidate observation | Source | Transport | Maximum, us | Provisional budget, us |
| --- | --- | --- | ---: | ---: |
| XIAO matched baseline | `1b9fcf2a` | 2 MHz byte transfers, SPIM3 | 855 | 941 |
| XIAO fast candidate | `1b9fcf2a` | Buffered 8 MHz, SPIM2 | 550 | 605 |
| Tag fast candidate | `61a536c6` | Buffered 8 MHz, SPIM1 | 580 | 638 |
| MeshTower fast candidate | `61a536c6` | Buffered 8 MHz, SPIM1 | 550 | 605 |

XIAO's 855-to-550 us comparison uses the same source checkpoint and isolates
the transport/controller configuration change. Tag's 947-to-580 us and
MeshTower's 947-to-550 us comparisons also cross older source checkpoints;
their improvements cannot be attributed solely to SPI speed. None meets the
requested 500 us sampled maximum.

## Witnessed RF delivery

Each campaign sent 200 unique, one-shot physical test packets: 100 on each
profile, with one sender and two fixed-profile witnesses. There was no
retransmission of a test packet. The scanner and fixed witness were checked
against the same packet ledger, and an offline audit reconstructed delivery
and cleanup from retained receipts.

| Scanner / source | Primary received / sent | Secondary received / sent | Fixed primary witness | Fixed secondary witness | Delivery result |
| --- | ---: | ---: | ---: | ---: | --- |
| XIAO Repeater, `1b9fcf2a` | 99 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | Failed |
| MeshTower Full Repeater SD, `61a536c6` | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | Passed this finite run |
| Tag Full Companion, `807343de` | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | Passed this finite run |

All three runs recorded zero new scanner receive errors, core flags,
radio-driver recovery attempts, switch errors, duplicate test packets,
wrong-profile receipts or collector drops. Uptime progressed without a detected
reboot. The longer XIAO and MeshTower runs reported a 673 us guarded switch budget both before
and after RF, larger than their short-window budgets. Tag retained a 638 us
guarded budget before and after RF. Its pre-existing radio-driver attempt
counters remained `soft=1,hard=0`. Settings for all four participants and the
gateway service were restored.

The XIAO missing primary packet remains an unresolved failure despite its
fixed witness receiving all 100. MeshTower's delivery pass does not satisfy
the separate speed objective or prove loss-free operation beyond this finite
run. These RF runs do not qualify CPU sleep or Bluetooth.

## Bluetooth and SD compatibility

On Tag Full Companion from `61a536c6`, all three bonded Bluetooth NUS sessions
passed, each held for at least 30 seconds with MTU 247. Public identity,
complete version, device information and the original Bluetooth getters
matched the USB peer. Dual-profile switching continued, core flags remained
zero, and the temporary leases and saved settings were restored. This receipt
precedes the new diagnostic getters in `807343de`; final-source results are
recorded separately below.

MeshTower from `61a536c6` passed a separate SD compatibility test while radio2
remained enabled and its switch counter advanced. The existing archive-cache
command physically wrote a four-byte marker, acknowledged file and card
synchronization, and directory pagination verified the marker's path and size.
The original cache policy, other directory entries and radio settings were
restored. **This is marker write/sync plus directory metadata verification;
it is not a byte-content readback or a full SD payload I/O qualification.**
Enabling the original cache policy can emit normal OTA metadata queries; the
test did not stage, apply or reset firmware.

The final MeshTower `807343de` image passed the same bounded marker/directory
check, plus the newly shared SD history, history selectors, alias and free-space
getters. Original cache policy and radio leases were restored. This adds
command coverage without extending the SD payload/readback claim.

## Final diagnostics checkpoint

Source `807343de8d77adc4f61dbb260bdb499c04fa0211` adds the shared Companion
power, hardware-watchdog, RXPS-watchdog, RXEN, CAD and statistics diagnostics,
and shares the guarded SD command path. Focused native tests execute the real
helpers and relevant radio admission, rollback and reset paths, including
sanitizer checks. These tests cover nonzero statistics reset semantics that
were not observably exercised by zero counters on the physical XIAO.

The final XIAO Full Companion was installed through application-only DFU;
its body is `7EC2F4BF2A80CFC1`, and no fallback was used. Its first radio setup
and post-preference-load setup are constrained to 917 MHz by a narrow,
default-off test-image guard. Its saved Companion frequency is then explicitly
written to 917 MHz. This prevents old role-specific preferences from briefly
returning the radio to an excluded frequency during the role change.

XIAO's source/body-bound new-command USB test passed, including RXEN changes
and restoration with one profile and with RXPS suspended by radio2. Cleanup
and gateway ownership checks passed. A physical nonzero
`clear stats` reset was not observed; native fault-injection coverage provides
that check. XIAO had one pre-existing soft RXPS-watchdog attempt and zero
hard attempts; all three USB reads retained `soft=1,hard=0`, including after
`clear stats`. No new attempt was observed in this command campaign. The
first new-source Bluetooth wrapper stopped in preflight because it incorrectly
required zero history. A later trial also established that the historical USB
reference was stale: XIAO's soft count had increased from 1 to 3 before the
measured Bluetooth window. The cause of that pretrial increase is unexplained.
The final controller preserved those receipts and bound an additional fresh,
hashed USB-before snapshot; it did not reset counters or the device.

Retained Full ELF SHA-256 values for the final checkpoint are:

| Artifact | ELF SHA-256 |
| --- | --- |
| XIAO Full Companion | `3324de701d8159bbf626e08ea1adfc91634db6191ace4d0898fc76e513884cb4` |
| XIAO Full Repeater | `2266a1d669e96c70f8e5dd695613a6eb621f80c3422d17da37801d62cb970786` |
| Tag Full Companion | `be9c73e78b073b8942a0aa84b25dd08c49d6e6cf30fb606c0e18f12988d11a12` |
| MeshTower Full Repeater SD | `785ee10d5c6fd67a728fd3126c8daf03b435b0dfe2d383582d4aaa48d605bab0` |

Their memory-capacity and relevant controller proofs passed. Tag's
application-only final install passed with body `6115C6802E1AFC50` and no
fallback. Its USB command test passed, including the correct unsupported RXEN
capability response; nonzero physical statistics reset was not observed. The
final MeshTower install also passed without fallback, with body
`E5324C388E987A8E`. XIAO was restored by application-only DFU to the final
Repeater image with body `83C09F44589332D6`, without fallback. Two fresh
checks confirmed its Repeater role, unchanged identity and retained 917 MHz
settings. Its original Repeater settings and gateway ownership were preserved.

Final XIAO and Tag Full Companion each passed three additional bonded NUS
sessions of at least 30 seconds at MTU 247. Every session verified all original
identity/version/Bluetooth checks and ten new read-only diagnostic getters.
The latter covered bootloader metadata, RXEN capability, power-management
support/source/boot voltage, actual system-watchdog state, power, both CAD
aliases and radio-driver recovery attempts. Dual-profile switching continued,
core flags stayed zero, and settings/leases were restored.

XIAO held its fresh `soft=3,hard=0` baseline unchanged through arming, all
Bluetooth sessions and final USB cleanup. Tag held `soft=1,hard=0`; its earlier
USB diagnostic reference had been `soft=0,hard=0`, so it too had a pretrial
increase whose cause is not established. These counters include continuous-RX
and liveness recovery attempts. They do not count CPU watchdog resets or
necessarily successful recoveries. Passing the measured windows does not
explain or erase the earlier increases.

A separate RAK4631 Full Companion build initially exceeded the linker's text
region by 524 bytes. Once linking succeeded, the complete OTA image check also
counted initialized data and its trailer. Source `0cdf6f9a` passes all build,
capability, RAM and OTA image gates: the application is 712,684 of 712,704 bytes,
leaving **20 bytes**. Runtime capacity is 81,220 bytes against 72,528 required.
The tight flash margin remains specific to this exact build.

The size fix retains every help byte, feature, contact/channel limit and
storage boundary. Compile-time LZSS stores 4,222 help bytes in 2,159 bytes; its
streaming decoder uses a 2 KiB history and 64-byte output chunk without a heap
allocation. Only the isolated packing source uses C++17; the application and
framework keep C++11. Native checks cover byte-for-byte output across four
profiles, mixed-language linkage, overlap, ring wrap, malformed references and
short/zero writes. Extracting and decoding the actual linked ELF reproduces
the retained original help exactly; the uncompressed copy is absent. This
size-only follow-up was not flashed for another hardware campaign.

After merging remote `fd47fe0b1`, source `86ef1e89` passed the same canonical
build and linked-help proof with the same application size and RAM capacity.
The incoming display and dynamic-WiFi regression suites also passed. The
hardware receipts above remain bound to their explicitly recorded images.

## Remaining work

- Resolve XIAO's witnessed missing packet and the unmet 500 us maximum goal.
- Investigate the unexplained pretrial radio-driver recovery attempts.
- Audit controller ownership before extending buffered SPI to RAK4631 or T096.

At this checkpoint, production-default promotion, all-board release
qualification and CPU-sleep qualification remained open. The machine-readable
[sanitized results](other_board_radio2_fast_switch_2026-10-23.safe.json) retain
separate delivery, speed, compatibility and build states.

## Saved controls follow-up

Code `4c0f2acf` adds saved `radio.fast` controls across the shared CLI roles.
Supported features default on, including boards awaiting physical testing.
Individual controls cover SPI speed, buffered transfers, batched modulation,
warm receive ownership, FS, packet, IQ and modem reuse. Plain SX1262 board
transports now default to 8 MHz byte transfers. Compiled buffered transports
can select byte transfers without moving their SPI controller. Indicator keeps
its existing transport and compile-time exclusions.

The wired RAK3401 passed 19 control cases and two software-reboot persistence
cases on the final Full repeater. Twenty-one read-only SWD samples confirmed
the SPIM2 frequency register at 2, 4 and 8 MHz. Both profiles continued
switching, core errors stayed zero, and no new radio-watchdog attempts were
observed. Its original settings and gateway service were restored. The
application update preserved its bootloader. These checks cover configuration,
startup persistence and switching liveness; packet delivery, BLE, CPU sleep and
the earlier XIAO loss remain separate qualifications.

Sequential builds passed for V4 Full Companion, RAK4631 Full Companion,
RAK3401 Full and Reduced OTA repeaters, and the standard T1000 BLE Companion.
The RAK4631 application including EndF is 711,400 of 712,704 bytes, leaving
1,304 bytes. Runtime RAM available is 81,140 bytes against 72,528 required.

To retain Full features, the offline Reader now uses a word dictionary before
DEFLATE. All 879 verses retain their exact wording; its pinned source and 4 KiB
scratch capacity are unchanged. Data and all dictionary/index tables total
33,399 bytes, saving 5,086 bytes. Corpus, malformed-token, C++11 compatibility,
sanitizer and ARM stack checks passed. The merged Meshtext retry-limit and
beacon tests also passed.

The [saved-control results](radio_switch_saved_controls_2026-10-23.safe.json)
record the build sizes and physical test scope. Command details are in
[Saved switching controls](../radio_profiles.md#saved-switching-controls).
