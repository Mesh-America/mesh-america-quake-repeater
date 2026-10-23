<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/nrf52_embedded_bootloader/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Embedded nRF52 bootloader update

An opt-in Repeater or Room Server build can carry its application firmware and
the exact board's [OTAFIX 2.4.12 bootloader](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/v0.11.0-OTAFIX2.4.12)
in one application image. Install that application first, then activate the
bootloader replacement with an authenticated admin command. Booting the image
does not flash the bootloader automatically.

This follows the internal-flash bridge in
[MeshEnvy firmware PR #2](https://github.com/MeshEnvy/meshcore-firmware/pull/2).
The replacement stays inside the running application's verified image until
Nordic's MBR copies it to the bootloader region. It needs no external staging
storage and does not replace the SoftDevice or change the filesystem layout.

## Build

From the repository root, replace `TARGET` with the exact OTA-enabled nRF52840
Repeater or Room Server target:

```sh
bash build.sh build-firmware TARGET --with-bootloader 2.4.12 \
  --firmware-version v1.18.0.1-halo-keymind-cascade-dev
```

For direct PlatformIO builds, the equivalent opt-in is:

```sh
MESHCORE_NRF52_EMBED_BOOTLOADER=2.4.12 pio run -e TARGET
```

The generator matches the board and storage to the 2.4.12 catalog and verifies
the release asset before embedding only its 40 KiB bootloader region. Host
validation covers 22 profiles. SenseCAP Solar P1 is excluded because its shared
XIAO board ID and different device name need separate identity support.
Unsupported profiles are refused. The usual application,
capacity and memory checks still apply: the resource adds 40 KiB plus update
code, so some profiles will not fit. The build does not remove features or
shrink the filesystem to make room.

Opt-in outputs include `-with-bootloader-2.4.12` in their names. Ordinary builds
and their output names stay unchanged. The embedded image remains an
application UF2/DFU package, not a combined SoftDevice/bootloader DFU package.

An installed bootloader with valid compatible identity metadata must match the
candidate's board and runtime layout. For the explicitly qualified legacy
RAK4631 transition, also supply the exact installed bootloader image:

```sh
MESHCORE_NRF52_LEGACY_BOOTLOADER=/absolute/path/full.hex \
  bash build.sh build-firmware RAK_4631_repeater --with-bootloader 2.4.12
```

The legacy exception binds the entire padded bootloader region by SHA-256.
It accepts the qualified MeshEnvy `0.9.2-ev1` RAK4631 image, whose full-region
SHA-256 is `64bfe69d56eefc2d0fe51770902aff70ea0cc06cad261d3d219e4a3c0efac8dc`.
A matching version string alone is insufficient; another board's image or an
unknown stock bootloader is not accepted by that exception.

## Install and activate

1. Install the application through its normal USB UF2 or serial/Bluetooth DFU
   route. LoRa delivery requires an already working, compatible application OTA
   updater. An internal-only legacy receiver needs a delta from its exact
   installed application; this image does not give a stock bootloader its first
   LoRa update capability.
2. After the new application is running, use the local CLI or authenticated
   remote admin CLI:

   ```text
   ota bootloader embedded status
   ota bootloader embedded audit
   ota bootloader embedded install HASH16
   ```

   Replace `HASH16` with the image confirmation shown by `status`. Save the audit
   before installation. The acknowledgment means armed; replacement waits for
   the reply and queued/in-flight radio transmissions to drain.
3. After reboot, check `get bootloader.ver` and repeat the audit. Confirm 2.4.12
   and compare the application, filesystem, settings and SoftDevice hashes.
   Check status before repeating a command whose reply was lost.

The bridge validates the live application, candidate hash, installed identity,
chip/layout, MBR addresses, watchdog and flash protection before copying. A
protected region is refused; the bridge does not unlock it. Existing staged
`ota bootloader status` and `ota bootloader install MID8 HASH16` commands keep
their separate signed-package behavior. See
[bootloader updates over LoRa](ota_nrf52_bootloader_update.md) for that path.

## Qualification

The source PR documents one successful RAK4631 migration with unchanged
application, filesystem, settings and SoftDevice hashes. Its later guards have
host checks, but the recorded hardware run predates the final PR build.
Other boards and power-cut recovery are not hardware-qualified by that test.
Keep local recovery access when qualifying a new transition; an older loader's
initial application-delta stage may itself be destructive. The MBR parameter
page is intentionally used during the bootloader copy and is outside the
unchanged-settings claim.
