<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/v4_mqtt_bellevue_g2_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# V4 MQTT setup and Bellevue G2 Full Repeater, 21 October 2026

Status: **PASS for the requested setup and deployment**. The Mercerwood V4
is left connected to its saved US analyzer MQTT preset. Bellevue's Station G2
now runs the current Full Repeater application, with repeating enabled and its
USB gateway service restored. No firmware source change was needed.

## V4 MQTT

The V4 retains its measured `2bd4cb4d` Full Companion application. Its saved
MQTT switch was already on, while WiFi was off and the MQTT region was empty.
The setup saved region `SEA`, enabled the existing WiFi configuration and kept
the `analyzer-us` preset. This preset uses WSS and device-signed JWT
authentication. WiFi and admin passwords were not changed.

The first connection obtained two broker PUBACKs. A subsequent 137.367-second
held observation recorded PUBACK growth from 3 to 5, uptime from 29,881 to
30,017 seconds, zero core errors and empty core queues. Every sample had an
empty MQTT outbox and zero queue/drop counters. Free DMA memory stayed at
50,056 bytes or more, with a largest block of 49,140 bytes.

The one-minute test status interval was restored to its original five minutes.
That setting restarts the MQTT worker; a separate final check confirmed WiFi,
MQTT and a new broker acknowledgment after the restart. WiFi and MQTT remain
enabled. Other saved broker slots and radio settings were not changed.

PUBACK verifies that the broker accepted a publication. An independent
subscriber payload receipt was not measured because no subscriber account was
available. This finite observation does not replace a long-duration WSS soak.

## Bellevue Station G2

| Item | Result |
| --- | --- |
| Canonical target | `Station_G2_repeater_observer_mqtt`, built through the Full release profile |
| Installed version | `v1.18.0.1-halo-keymind-cascade-dev-observer-a926341f` |
| Application body / target | `4233FACEB6C44EAE` / `DBB6A855` |
| Application SHA256 | `459f2e1de20460b54ac00cd545dfe11490b13081072c3aed47b1398dd276dcf5` |
| Build gates | Full capability and memory gates passed; 200,432 available internal bytes versus 192,656 required heap bytes |
| Installation | Actual ESP32-S3 identity and 16 MiB layout verified; CRC-valid OTA metadata selected the active slot at `0x650000`, size `0x640000` |
| Readback | All 2,118,264 application bytes verified; partition table, OTA metadata and NVS hashes unchanged during the write |
| Persistence | Original public identity, name, radio, TX power, WiFi SSID, MQTT settings and power-saving choice preserved |
| Repeater mode | Role-specific getter accepted; repeating was already on and remains on |
| Final health | Core errors 0, outbound queue 0; local packet counters showed 84 received and 18 sent |
| Service handback | Original `mctomqtt.service` is active and again owns the exact G2 USB endpoint |

The combined Full recipe retains `observer` in its version string and includes
the repeater implementation, MQTT, ESP-NOW, USB logging, WiFi OTA and LoRa OTA.
The build's Full overlay enables the LoRa update path. Saved operating settings
remain 910.525 MHz / BW62.5 / SF7 / CR5 and TX 19 dBm.

The application-only update preserved the existing expanded layout. It made no
whole-chip erase or full-flash backup. Small protected NVS reads were hashed
and removed; after boot, saved logical settings and the full public identity
were independently compared with the original observations.

The first postboot check had zero core errors and one in-flight radio packet
at uptime 13 seconds. The initial harness required an immediately empty queue
and stopped handback at that check. A bounded follow-up on the same installed
firmware verified the exact version, body, identity and repeater role, then
recorded an empty queue with zero errors at uptime 149 seconds and restored
the original USB gateway. That early failed gate is retained in the evidence;
no second firmware installation was performed.

The [safe receipt](v4_mqtt_bellevue_g2_2026-10-21.safe.json) records artifact
bindings, timings and evidence hashes. The local packet counters demonstrate
observed radio activity; independent peer delivery, RF range, physical OTA
installation and long-duration behavior were not tested in this deployment.
