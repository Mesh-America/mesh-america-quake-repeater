# Upgrading from 1.17.1.8 to 1.17.1.9 over WiFi

For a supported ESP32 node that already has compatible application slots,
use its own `MeshCore-OTA` access point and the matching application-only
image. This measured V4 route avoids dependence on the site's WiFi credentials
and LAN reachability. USA Cascade defaults remain 910.525 MHz, 62.5 kHz, SF7 and CR5; existing saved radio settings take
precedence after an update.

Select the exact board, hardware variant and role in the
[firmware picker](firmware_picker.md). Download the image before connecting
to the node's update network. The release's manifests and SHA-256 inventory
identify the exact files. Preserve identity and settings using the tools
appropriate to the installed role before an upgrade.

## Choose the installation route

| Installed node | File and route |
| --- | --- |
| Exact ESP32 board/role with compatible dual-OTA slots | Matching application-only `.bin` through its working browser updater. |
| Supported legacy dual-OTA layout needing expansion | Exact board/role migration ZIP from the selected release's utility page; follow its README and use its supplied Full application. |
| Layout without a matching migration package, single application slot, or no working supported updater | Matching `-merged.bin` through that board's USB/serial flashing procedure. |
| nRF52 | Matching application UF2/DFU ZIP or a separately documented LoRa OTA route; this ESP32 browser procedure does not apply. |

An application-only update cannot replace a partition table. Where available,
`get storage.layout` reports the live layout; a version label does not establish
it. For older firmware, use the [partition lookup guide](esp32_partition_catalog.md).
The tested V4 already had two 6.25 MiB slots in the expanded 16 MiB layout.
That result does not qualify a migration from legacy 1.25 MiB slots.

Never upload a `-merged.bin` or `target-partitions.bin` to an application-only
browser updater. A merged image includes bootloader and partition-table
offsets for USB/serial installation. A migration package's target table is
a verification artifact, not an application.

## Recommended 1.17.1.8 V4 example: use the node's AP

The actual published Full V4 build tested was `9053038f`. From an authenticated
USB, Bluetooth or LoRa command session, send these commands one at a time,
waiting for each reply:

```text
stop webconfig
stop ota
start ota ap
```

Stopping WebConfig explicitly is needed for this old build's HTTP-port
handoff. Stopping a previously running uploader ensures the old `start ota ap`
starts the AP route. The new 1.17.1.9 startup behavior should not be assumed
on the old receiver.

Join the node's `MeshCore-OTA` WiFi network. Open the exact URL returned by
the command, normally `http://192.168.4.1/update` for an infrastructure node.
Confirm that the page identifies the intended node, select its matching
1.17.1.9 application-only `.bin`, and upload once. Keep the node powered
through the transfer and its automatic restart.

After restart, reconnect with the normal configuration app or console and
run:

```text
ver
get storage.layout
```

Compare `ver` with the selected image and confirm identity, ACL, radio settings
and the other saved settings used by the node. A command unsupported by the
installed image is not proof of an incorrect layout; use the lookup guide
when necessary.

The old 1.17.1.8 page can remain at 100% or miss HTTP completion even after
the new application installs and the node restarts. Check the running version
before repeating an upload. Browser transmission progress alone does not
prove successful installation.

For 1.17.1.9 receivers, `start ota` starts WiFi when needed, stops WebConfig
to free its HTTP port, and reports the IP address and network to use.
`start ota ap` explicitly selects the node AP even if a LAN uploader is
already running. WebConfig's own terminal explains that the handoff closes
the portal; send it through USB, Bluetooth or LoRa instead. On a compatible
two-slot Full Companion, use the returned port-8080 URL; single-slot Full
Companions require USB for self-update. Use `stop ota` if abandoning an update.

## LAN and phone examples

If an old 1.17.1.8 infrastructure node is already reachable on the intended
WiFi LAN, retain that connection. Otherwise configure it through its existing
WebConfig UI, then verify the live address with `get webui`. From a separate
USB, Bluetooth or LoRa session:

```text
stop webconfig
stop ota
start ota
```

Open the exact returned LAN URL, for example `http://192.168.1.40/update`.
The upload computer or phone must be able to reach that address. On
1.17.1.8, confirm the actual connection after changing credentials; a serial
WiFi setter alone does not prove that WebConfig uses the new pair. If the LAN
is weak or blocks client-to-client traffic, use the node AP route above.

A phone near the node can download the correct application while it has
Internet access, join `MeshCore-OTA`, and use its browser at the returned
address. Keep that WiFi connection even if the phone warns it has no Internet.
This is the same intended node-AP route, but an actual phone browser upload
was not physically tested in this run.

A phone hotspot is useful only if the node and uploading device can both
join it and reach one another. Confirm the node's reported LAN URL before
uploading; hotspot client isolation can prevent this. The controlled shared
LAN test used a Pi access point, not a real phone hotspot, so a phone hotspot
is not the qualified default recommendation. For a node with only LoRa
reachability, use the [LoRa OTA guide](lora_ota_automation.md) and exact matching
target/storage package.

## When partition expansion is required

Use the exact migration ZIP selected for this board and role. Its README
defines the supported old updater, live-source checks and preservation set:

1. Upload that package's `wifi-bridge.bin` through the supported old updater.
2. Join the migration network described in its README and wait for
   **Expanded layout ready**.
3. Upload the same package's `full-application.bin` through its `/update` page.
4. Verify the new layout, version, identity, ACL and supported saved settings.

Do not substitute a loose release application for the ZIP's supplied Full
application: migration packages can carry a required older target identity.
Do not combine stages from different packages. The bridge writes the
partition-table sector; loss of power during that write can require cable
recovery. See the [complete migration directions](esp32_wifi_partition_migration.md)
for the exact preservation limits and supported WiFi/LoRa routes. Actual
legacy-layout V4 migration was not physically tested in this run.

## Stock G2 migration limitation

The separate stock 1.14.1 G2 trial reached the `1e421ff4` Full application
over WiFi after partition expansion, but its final isolated
network check reached the client/DHCP deadline without a verified G2 client
or any HTTP request. The complete cable-free migration is therefore not
qualified. Plan for USB recovery if starting from that stock image.

The G2 was subsequently updated and verified through separate USB maintenance
on release source `88c851080`, with its original identity, ACLs, 22 common
settings and saved extras preserved. That result does not qualify the failed
WiFi-only final check. A legacy RX-gain loading correction preserves an
unambiguous saved gain of on from compact stock preferences; ambiguous older
zero padding retains the board default.

The [detailed test report](test-results/hardware_validation_esp32_web_console_ota_2026-10-05.md#release-candidate-follow-up-recorded-2026-10-07)
retains the original failures, host/network recovery and exact source revisions.
Latest-source physical V4 testing was unavailable; the measured older upgrade
routes below do not establish every board or starting version.

## Measured upgrade scope

The published 1.17.1.8 Full V4 installed newer applications over node AP and
a controlled shared LAN, with automatic restart and preserved identity and
ACL, despite missing old-page HTTP completion. On the earlier `c5fe8a0e` source,
the unchanged native AP pages returned HTTP 200/OK for G2 and V4 uploads;
the V4 upload completed in 16.392 seconds and its first ordinary clock reply
took 1.010 seconds against the unchanged 5-second console deadline. These
tests used compatible expanded layouts and do not qualify every board,
browser, phone or starting version. See the
[1.17.1.9 verification scope](releases/1.17.1.9.md#verification-scope).
