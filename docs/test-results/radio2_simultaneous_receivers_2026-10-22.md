<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/radio2_simultaneous_receivers_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Simultaneous radio2 receiver comparison, 2026-10-22

The matched-PHY five-receiver test **passed**: **915.000 and 916.000 MHz, both
SF7 / BW 62.5 kHz / CR4/5 (RadioLib value 5) / preamble 32**. Every applicable
packet arrived, and all six radios passed final preservation and session
checks. The preceding mixed-PHY
915/916 campaign stopped cleanly at a case boundary under user steering;
its measurements remain a separate cohort. Historical 910.525 results are
not current test frequencies and are not merged into either 915 cohort.

## Latest campaign: three scanners and two fixed witnesses

One Xiao S3 sender sent **one fresh 40-packet case**, with **20 primary and
20 secondary** packets at preamble 32. Five receivers listen to the same
physical packets concurrently. This is not separate unicast delivery to each
receiver. No earlier packet is resent or replaced by this new measurement.

| Role | Board | Source | Applicable packets per case |
| --- | --- | --- | --- |
| Scanning receiver | Heltec V3 | `9b70827d` | 20 primary + 20 secondary |
| Scanning receiver | Heltec V4.3 OLED | `9b70827d` | 20 primary + 20 secondary |
| Scanning receiver | Heltec T096 | `4773ac42` | 20 primary + 20 secondary |
| Fixed primary witness | Tag | `08650f64` | 20 primary; secondary not applicable |
| Fixed secondary witness | SenseCAP Indicator | `08650f64` | 20 secondary; primary not applicable |
| Sender | Xiao S3 WIO | `ebb59d48` | One direct TX per planned packet |

All six nodes matched their bound identity and full firmware version. The
controller rejected a recorded saved baseline other than 915.000 MHz before
opening hardware. V3 and V4 used normal firmware. The older T096 lacked the
later shared RX fixes.
Board hardware and firmware both differ, so this comparison cannot isolate
either as a cause.

Primary is **915.000 MHz / BW 62.5 kHz / SF7 / CR5**; secondary is
**916.000 MHz / BW 62.5 kHz / SF7 / CR5**, both at **preamble 32**.
Sender power is **2 dBm**. The three
scanners enable radio2; each fixed witness disables scanning and stays on its
assigned tuple. Receiver power saving and RXPS are off. All five USB receive
collectors operate concurrently. The seeded shuffled profile order uses
minimum gaps after the prior physical TX_DONE confirmation; retuning can
lengthen a gap. There are no RF retries or replacement packets.

Both profiles now have the same 2.048 ms symbol duration. Scanner-derived
visit policy and receive ownership still apply; matched SF/BW/preamble does
not assert identical measured visits or an acquisition guarantee. This new
cohort cannot be treated as another preamble-only row of the mixed-PHY test.

The migration **passed on all six radios**: saved primary readback was
915.000 MHz / BW 62.5 kHz / SF7 / CR5, and each physical-apply command returned
ACK 00. This confirms configuration acceptance, not an RF frequency
measurement. The migration explicitly saved **preamble 32**; earlier effective
32-symbol status did not distinguish saved auto from explicit 32. Channels,
credential hashes and all other compared saved settings were retained.
No test datagrams were requested by migration.

The new baseline was taken after migration. Cleanup must retain 915.000 and
must not restore 910.525 on these radios, while preserving the other compared
settings. This frequency change prevents treating earlier 910.525 data and
the new 915.000 cases as one preamble-only comparison.

Each 92-byte DEV application payload contains `MCHILGR1`, the sender public
key, a common group digest, a fresh 16-byte nonce and a global ordinal. The
digest binds all six role-ordered public keys, witness profile assignments,
the campaign nonce and exact preamble/PHY/packet plan. Keys, raw identities
and payload bytes are excluded from this report. Each ordinal requires one
local acceptance and exactly one physical direct TX, without a flood.

Receivers independently match exact application bytes, their owned local
channel slot, DEV type and direct route. Logical profile comes from the
sender ledger, not an RX-origin field in the Companion response. Queue drain,
duplicates, wrong-profile witness receipts, receiver transmissions and core
health are checked separately from application delivery.

## Latest matched-PHY results

Test: **COMPLETE, VALID, PASS**. The single RF case and all six final
preservation/session proofs passed, with no reported errors.

| Preamble | V3 P / S | V4.3 P / S | T096 P / S | Tag primary / 20 | Indicator secondary / 20 | Evidence status |
| --- | --- | --- | --- | --- | --- | --- |
| 32, both SF7/BW62.5 | 20 / 20 | 20 / 20 | 20 / 20 | 20 | 20 | Complete, valid; finite delivery PASS |

Packet labels are one-based within each profile: `P01`-`P20`, `S01`-`S20`.
All applicable missing sets are empty. Each scanner received the same 40
packets and each fixed witness received its assigned 20. The case has no
reported evidence or collection errors. All 40 requests were accepted once,
with 40 confirmed direct transmissions, zero floods and zero retries. All five
collectors completed, with zero duplicates, wrong-profile receipts or receiver
transmissions; every before/after core error flag was zero.
Every applicable pair has Jaccard 1.000. The
fixed witnesses have no common applicable frequency; their opposite-profile
entries remain not applicable, not a 40-packet expectation.

Masks use V3, V4.3, T096, Tag, Indicator order. The opposite-frequency witness
is `NA`, never a miss. Complete primary reception is `1|1|1|1|NA`; complete
secondary reception is `1|1|1|NA|1`. An owned wrong-profile witness receipt is
a confound. The observed masks are `1|1|1|1|NA` for all 20 primary packets
and `1|1|1|NA|1` for all 20 secondary packets: 40 all-applicable receptions
and no fixed-witness/scanner discrepancy. A fixed-witness receipt with a scanner miss confirms delivery at
that witness, not a cause of the scanner miss. No applicable receipt does not
prove no RF transmission. Correlated loss alone does not assign a cause.

A valid completed measurement can still fail delivery. A campaign pass
requires every applicable packet plus all evidence and preservation gates.

This finite 20-per-profile result is not a permanent-fix or zero-loss
guarantee. The preceding mixed-PHY 32-symbol case at the same 915/916 MHz had
scanner misses; this case changes the secondary SF/BW, airtime and derived
scan timing. Run time, order and ambient traffic were not controlled between
the cases. Their difference therefore does not isolate a causal setting or
explain a particular earlier missing nonce. The new packets were not retries.

## Latest completion and evidence

Migration and its original six-node saved baseline: **PASS**. All six final
readbacks retained primary 915.000 and passed preservation of the other
compared settings, permissions, leases, channels, credentials and PINs. All
six final session proofs passed. V4 MQTT reconnected with status `(ok)`;
this check did not independently prove a fresh publish acknowledgement.
No production firmware was changed. USB collection remains active, so these
rates are not a repeated measurement of earlier USB-quiet experiments.

The current controller proactively revalidates strict binary mode, public
identity, full version, core health and uptime after 45 seconds of idle time,
only outside RF. It performs final proofs on all six sessions before close
and retains outer-finally errors. These are host measurement changes, not
firmware or watchdog changes. A graceful stop marker replaces signals during
an active CLI operation.

The matched-PHY controller SHA-256 is
`187ab7de2464d1496ddee5235899d115270953e4ae38beaa1b0e1791823b0bb1`;
its comparison core SHA-256 is
`6920179844efe720542368d2ea257d94c18c8c49c063efb18a60ccf6b8204b31`.
The completed matched-PHY raw receipt SHA-256 is
`46ef6da2dabe8ba48f7acb8e8b5aec2370c8b41397787ac78020e044d50c918e`;
its sanitized export SHA-256 is
`3bcc79cc02722c8438340c5fad49b9c9c7921f2b4e8b433669e748388a04a94f`.
Machine-readable evidence is the
[matched-PHY report](radio2_simultaneous_receivers_2026-10-22.safe.json).
The separate saved-frequency migration source SHA-256 is
`a763aec8d1bd692c524f5dee773b3d1663e1eac0cc26308568e8d38153fb7cf0`.
The completed migration receipt SHA-256 is
`c523274d78c9dd3aa7511cb91ef0330866684f7f12bfc54d94967787f0d22257`;
the passed six-node baseline SHA-256 is
`bb6685fa03182395e7a697d4b7b843c023b59d7f12feebe074f2c7de76d26f78`.

## Previous 915/916 cohort: different SF/BW profiles

This cohort uses primary 915.000 / BW 62.5 / SF7 and secondary 916.000 /
BW 125 / SF9, with matched preambles varied across cases. All three executed
cases, at 32, 64 and 128 symbols, completed as valid controlled comparisons.
The user requested a graceful stop after 128; no active case was interrupted.
Preamble 256 was not run. The original four-case experiment is incomplete by
user steering, not a setup failure. Every executed case had 40 accepted and
40 confirmed direct transmissions, zero floods, retries, duplicates,
wrong-profile receipts, receiver transmissions or evidence errors. All five
collectors completed and all before/after core error flags were zero.

| Preamble | V3 P / S | V4.3 P / S | T096 P / S | Tag primary / 20 | Indicator secondary / 20 | Evidence status |
| --- | --- | --- | --- | --- | --- | --- |
| 32 | 19 / 20 | 20 / 20 | 20 / 18 | 20 | 20 | Valid; scanner delivery FAIL |
| 64 | 20 / 20 | 20 / 20 | 20 / 20 | 20 | 20 | Valid; all applicable delivery PASS |
| 128 | 20 / 20 | 20 / 20 | 20 / 20 | 20 | 20 | Valid; all applicable delivery PASS |
| 256 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | Skipped by user steering |

Packet labels are one-based within each profile: `P01`-`P20`, `S01`-`S20`.
At 32, V3 missed **P04** and T096 missed **S02 and S15**;
V4.3 received all 40. Both witnesses received all 20 applicable packets.
Thus each of the three scanner misses had a same-packet fixed-witness
receipt. This proves delivery at that witness, not a cause of the scanner
miss. All applicable receivers received the other 37 packets.

At both 64 and 128, all three scanners received 40/40 and both witnesses received their
20/20 applicable packets. There was no extraneous receiver TX or core/evidence
error. This is a finite sample pass, not proof of a permanent fix or a
guarantee that longer preambles prevent loss.

Masks use role order V3, V4.3, T096, Tag, Indicator, with `NA` for the opposite
frequency witness. For example, complete primary reception is
`1|1|1|1|NA`; complete secondary reception is `1|1|1|NA|1`. `NA` is never a
miss. An owned wrong-profile witness receipt is retained as a confound.

| Preamble | Applicable reception mask | Packet count |
| --- | --- | --- |
| 32 | `1\|1\|1\|1\|NA` | 19 primary |
| 32 | `0\|1\|1\|1\|NA` | 1 primary |
| 32 | `1\|1\|1\|NA\|1` | 18 secondary |
| 32 | `1\|1\|0\|NA\|1` | 2 secondary |
| 64 | `1\|1\|1\|1\|NA` | 20 primary |
| 64 | `1\|1\|1\|NA\|1` | 20 secondary |
| 128 | `1\|1\|1\|1\|NA` | 20 primary |
| 128 | `1\|1\|1\|NA\|1` | 20 secondary |

The 32-symbol witness classifications are 37 all-applicable receptions and
three fixed-witness-received/scanner-missed packets: P04 at V3, S02 and S15
at T096. At both 64 and 128 they are 40 all-applicable receptions. The fixed
witnesses missed no applicable packets in any executed case. The 256-symbol
case was not run.

| Same-packet observation | Supported interpretation |
| --- | --- |
| Fixed witness receives; scanner misses | Delivered at that witness; scanner missed the same packet |
| All applicable receivers receive | Exact shared application delivery to those receivers |
| Scanner receives; fixed witness misses | Witness missed a packet received elsewhere |
| No applicable receiver receives | No local receipt; does not prove no RF transmission |
| Opposite-frequency witness receives | Confound requiring investigation; not clean applicable delivery |

The raw and sanitized closed receipts agree on these counts. Correlated loss
alone does not assign a receive-path cause.
A valid completed measurement can still fail delivery. A campaign pass
requires all applicable packets and all evidence/restoration gates.


Changing the matched preamble also changes the scanner's derived primary
visit duration. At these tuples the primary symbol is 2.048 ms and the
secondary symbol is 4.096 ms. The nominal idle primary visit is the larger of 9.421 ms and
`2.048 * preamble - 18.842 - 2 * guarded_switch_ms`; secondary visit is
18.842 ms. This is a **preamble-plus-derived-dwell comparison**, not an
isolated preamble-only experiment. The actual guarded switch term remains
part of the per-board runtime timing state (`RadioProfiles::listenUs`).
Actual visits can be extended by receive ownership; the formula is not a
timestamped account of an individual packet's reception or miss.

The mixed-PHY private controller/core SHA-256 digests are
`e092276f44f06d714c49befc78ae6a9738efe3cc369ede4a0b4fbe731794455b`
and `3c002da26512ba9324e491adb7fa8595944e921ee5bd841cec6fe8271ab5a504`.
All six nodes' restoration and final session proofs **passed**, with no
reported errors. The planned-four-case aggregate completion/validity fields
remain false because 256 was skipped; each of the three executed cases has
its own completed/valid flags true. The raw receipt SHA-256 is
`5d120a579863ffaf8ba9c29d7463f2d546e82a0ffdd012f599b0208e9908f00a`;
its sanitized export SHA-256 is
`d03d8f65bc974d56c8c49fdddcdd988496b7eca29f5bc401a7ce1196bf00036e`.
Machine-readable evidence is the separate
[mixed-PHY report](radio2_simultaneous_mixed_phy_2026-10-22.safe.json).

## Appendix: earlier three-receiver measurements

These historical runs used V3/V4 `9b70827d`, T096 `4773ac42` and sender
`ebb59d48`, with the old primary **910.525 MHz / BW 62.5 kHz / SF7 / CR5**
and secondary **916.000 MHz / BW 125 kHz / SF9 / CR5**. They used 2 dBm,
matched preambles, power saving/RXPS off and three active USB collectors.
Every scanner case below sent 40 distinct packets once. These are not results
for the new 915.000 MHz primary.

| Preamble | V3 P / S | V4.3 P / S | T096 P / S | Shared scanner masks |
| --- | --- | --- | --- | --- |
| 32 | 16 / 18 | 16 / 18 | 16 / 18 | 000=5, 001=1, 110=1, 111=33 |
| 64 | 20 / 16 | 20 / 16 | 20 / 16 | 000=4, 111=36 |
| 128 | 20 / 16 | 20 / 16 | 20 / 15 | 000=4, 110=1, 111=35 |
| 256 | NOT RUN | NOT RUN | NOT RUN | User-directed stop before RF |

These three-bit masks use V3, V4.3, T096 order; omitted masks have zero count.
All three measured cases were valid controlled comparisons with failed
all-packets delivery. Scanner receipt sets and misses are retained:

- Preamble 32: V3/V4 missed P08, P09, P14, P15 and S15, S19. T096 missed
  P08, P09, P14, P17 and S15, S19. The five common misses were P08, P09,
  P14, S15, S19. 33 packets were received by all three scanners, and 35 by
  at least one.
- Preamble 64: all three missed S01, S07, S10, S12; all primary packets arrived.
- Preamble 128: V3/V4 missed S05, S06, S14, S19. T096 also missed S17.
  All primary packets arrived.

V3/V4 receive sets matched exactly in each earlier case. At preamble 32,
their Jaccard with T096 was 15/17 primary, 18/18 secondary and 33/35 overall.
At 64 all pairs had Jaccard 1. At 128 their Jaccard with T096 was 20/20
primary, 15/16 secondary and 35/36 overall. Empty-union Jaccard is undefined.
These correlations do not establish a loss cause or a preamble remedy.

The preamble-32 window lasted 130.650 seconds. All collectors drained,
reported zero duplicates and core flags 0; no receiver transmitted. Physical
RX deltas were V3 117, V4.3 112, T096 113, each including 34 owned packets;
other RX deltas were 83, 78 and 79, with RX error deltas 1, 3 and 1. These
background totals do not identify why a particular nonce was missed.

The fresh fixed-secondary control delivered **20/20 to all three**, with
zero duplicates, errors or receiver transmissions, over 65.075 seconds.
The later fresh fixed-primary follow-up also delivered 20/20 to all three
with no duplicates and complete drains, but an unaccounted T096 flood TX
made that controlled comparison **INVALID**, not a clean control pass.
Neither control resent a scanner packet or erased its misses.

## Appendix: failed attempts and restoration history

- The preamble-32/fixed-secondary attempt retained a sender cleanup failure:
  restoring the original 22 dBm was rejected as radio busy, leaving test power
  2 dBm. All receivers restored and V4 MQTT status recovered. The subsequent
  fixed-primary follow-up restored all original settings, including sender
  22 dBm; that later preservation pass does not erase the failed cleanup.
- The first longer-preamble setup stopped at T096 RXPS-off's exact radio-busy
  rejection under a five-second/ten-attempt configuration bound. It sent zero
  RF and restored all settings. A new attempt changed only safe exact-busy
  configuration retry to 30 seconds/40 attempts; no RF resend was introduced.
- After the 64/128 measurements, the user-directed stop before 256 interrupted
  a CLI operation and original cleanup failed to clear the owned V3 channel.
  A separate fresh session verified its exact owned name/key digest, cleared
  only that record and proved full settings, channels, PIN and credentials
  preserved, without RF. The original cleanup failure remains retained.
- Initial RAK4631 witness inventory failed binary framing before identity
  qualification. Its failed baseline was retained; the qualified Tag replaced
  it in the five-receiver plan.
- The first five-receiver setup sent zero RF: V3 timed out on the first
  radio2-off setter after 85.74 seconds since prior I/O. V3's watch getter was
  unsupported, so the cause is **UNRESOLVED**, not confirmed idle expiry.
  All six nodes restored successfully. A separate final session-exit 4 KiB
  tail guard then failed; that failure is also retained.
- The next five-receiver attempt was stopped immediately when the user
  prohibited 910.525 MHz. It is **PARTIAL**, not a completed four-case result.
  It made **25 physical transmissions**; this is not a 40-packet completed
  case, and unsent packets must not be reported as receive misses. All five
  receivers restored, but the sender cleanup failed because of framing.
  Detailed partial receive sets are retained privately and are excluded from
  the completed matched-PHY result.
  No result is transferred from it into the new 915.000 matrix. The following
  migration recovered the interrupted state and passed preservation of the
  compared settings, with the intentional saved 915.000/32-symbol setting.

The stopped old-frequency five-receiver attempt's private controller/core
SHA-256 digests were
`7e3dba8ca3c3387e601111714f46741bdd933b6f041f8213aadad8eef69d3cc1`
and `ba0a116f90a17825d1718aef9e4138a27002fdd2ff2127be46815280245ceab2`.

Private failed/measured receipt SHA-256 digests, without raw identifiers:

| Receipt | SHA-256 |
| --- | --- |
| Preamble 32 and fixed-secondary | `c5e7cec34c376c718e936f4a86b21b197bbb2dc4b02dbdc7e079617f2d229511` |
| Fixed-primary original failed comparison | `ffe5a65c17df98b444eb690f9208090637724dc7906b2fb97aedc5f2bc63ee44` |
| First five-receiver setup, zero RF | `b3613de719584be3c033c31a8a973c30c88e22146d9060293aa1ec7fb574a1c9` |
| Stopped old-frequency five-receiver partial, 25 TX | `87026d5c9938ae855983f529906aca09bafa9975e01ce0176d9eef82391eed2f` |

Other detailed earlier attempt/recovery records are retained privately.
Earlier failures and causal limits also remain in the
[ESP32 BLE, radio2 and sleep report](esp32_ble_radio2_sleep_2026-10-21.md).
