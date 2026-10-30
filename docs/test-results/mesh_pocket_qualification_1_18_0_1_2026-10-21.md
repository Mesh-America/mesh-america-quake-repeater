<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/mesh_pocket_qualification_1_18_0_1_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# MeshPocket Companion qualification, 21 October 2026

Status: **PASS for the automated Companion bench checks below**. The user's
request to test MeshPocket lifted its earlier bootloader-work exclusion.
The board now runs Full Companion built from
`21a0f318da26bdb1fa5257471c3d7a68a0684337`, version
`v1.18.0.1-halo-keymind-cascade-dev-21a0f318`, protocol 14.
Its measured application body is `54411895235BE9C4`; application ZIP SHA256 is
`7841c4e7e8bbb8695ba0e796fa811efa41112367641c2790f22cc9085ba00da6`.
No firmware change was needed for these checks.

| Check | Measured result |
| --- | --- |
| Build and application update | Full capability/memory checks passed; identity-bound USB application-only DFU succeeded; exact version and EndF body verified after boot |
| USB | 100 query cycles, 10 reopens, owned contact CRUD and persistence through one verified warm restart passed; no framing errors or core error flags |
| Bluetooth | Three authenticated sessions held for 30.269 / 30.271 / 30.271 seconds; saved bond, exact USB identity/version and three clean controller lifecycles; no bond deletion |
| Full contact refresh | All 64 owned records verified in a 65-record stream, including the original contact; request to END: 2.491665 seconds |
| Incremental refresh | Exact 32 owned timestamp-selected records in a 33-record stream; request to END: 1.305048 seconds |
| Contact cleanup | All 64 synthetic contacts removed; zero remained after reopen; original contact fingerprint unchanged |
| Two-way LoRa | Three rounds, six exact direct nonce-bound datagrams, six send commands; every round passed |
| Handback | Owned channels removed; both radios' original modem settings, TX power and saved routes restored; ports closed; final Pocket core errors and outbound queue both zero |

Bluetooth passed while the USB data cable remained connected. Each contact
refresh used the existing bond and a separately verified clean controller
lifecycle. USB persistence covers one owned contact across a warm restart;
the 64-record fixture separately covers a seven-second save allowance and
exact reopen readback. Neither is a cold-power persistence measurement.

The RF partner was the already restored XIAO ESP32-S3 Full Companion, retained
at `ebb59d48292de4a573250cf4c6a2ed7cf5f7ef69`, body `4EEB12667E5E554B`.
Both identities and actual versions were verified before the three rounds.
The temporary test tuple was 910.525 MHz / BW62.5 / SF7 / CR5, preamble 32.
Exact source, destination, nonce, zero-hop route and physical packet counters
were checked. This is an explicitly mixed-source pair, not a claim that every
radio runs the new Pocket artifact. The RAK3401 gateway was not touched.

The existing bootloader and SoftDevice were preserved: the verified DFU ZIP
contained only application BIN/DAT components. Its exact installed bootloader
revision remains unverified because this Full Companion returns an unknown
command for `get bootloader.ver`. Successful application DFU and subsequent
runtime checks do not establish the independent bootloader's revision.

The first updater attempt failed before its DFU touch because the newer
flasher's pinned USB helpers depend on startup globals absent from the
definitions-only bench adapter. The compatible, previously reviewed updater
then installed the app successfully. The adapter now validates and privately
stages both bundled helpers and resolves them locally without running flasher
startup. Fourteen adapter tests and five application-ZIP verifier tests passed;
shell syntax and diff checks passed. This tooling-only fix did not trigger
another firmware installation or repeated hardware campaign. The preinstall
0865 application's core flag 8 and the failed updater attempt remain in the
private evidence; no causal firmware fix is inferred from the clean new boot.

The [safe receipt](mesh_pocket_qualification_1_18_0_1_2026-10-21.safe.json)
binds every measured axis to its source, artifact, interval and evidence
digest. Earlier Pocket results and the temporary exclusion remain historical
in the [20 October fleet report](hardware_validation_mercerwood_1_18_0_1_2026-10-20.md).
The other twelve boards retain their accepted source-bound measurements;
unchanged hardware tests were not repeated.

These finite checks do not establish RF range, long-duration reliability,
phone interoperability, battery current or physical cold starts. Screen/page
rendering awaits operator observation. MeshPocket has no native WiFi.
Bluetooth DFU is build-verified but a physical wireless update was not run in
this task. This Companion can seed LoRa firmware transfers; local LoRa firmware
installation is disabled and was not claimed tested.
