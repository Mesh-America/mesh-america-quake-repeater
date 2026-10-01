# 1.17.1.8 Preview 1 test results

This preview contains USA Cascade builds for RAK3401 Repeater and Heltec V4 OLED Full Companion, Full Repeater, Full Room Server, and Full Sensor. The [GitHub prerelease](https://github.com/mikecarper/MeshCore/releases/tag/rak3401-preview-v1.17.1.8-halo-keymind-cascade-dev-d5853b9c) has the matching firmware assets.

The [RAK3401 source test run](https://github.com/mikecarper/MeshCore/actions/runs/36810565194) and [Heltec V4 source test run](https://github.com/mikecarper/MeshCore/actions/runs/36826971285) passed. The RAK3401 UF2 and DFU application payloads match, with verified DFU CRCs. Both RAK3401 packages passed capability and memory checks. The four Heltec V4 OLED variants passed capability and memory qualification. These are build/package checks, not physical on-device tests of every variant.

## RAK3401 package results

- [Build information](BUILD-INFO.json)
- [UF2, DFU, capability, and memory checks](PACKAGE-CHECKS.json)
- [RAK3401 LoRa OTA capabilities](RAK_3401_repeater_lora_ota_no_external_sensors-ota-v1.17.1.8-halo-keymind-cascade-dev-d5853b9c.capabilities.json)
- [RAK3401 LoRa OTA memory](RAK_3401_repeater_lora_ota_no_external_sensors-ota-v1.17.1.8-halo-keymind-cascade-dev-d5853b9c.memory.json)
- [RAK3401 standard capabilities](RAK_3401_repeater-v1.17.1.8-halo-keymind-cascade-dev-d5853b9c.capabilities.json)
- [RAK3401 standard memory](RAK_3401_repeater-v1.17.1.8-halo-keymind-cascade-dev-d5853b9c.memory.json)

## Heltec V4 OLED reports

- [Full Companion capabilities](heltec_v4_2_v4_3_companion_radio_full_femon-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.capabilities.json)
- [Full Companion memory](heltec_v4_2_v4_3_companion_radio_full_femon-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.memory.json)
- [Full Repeater capabilities](heltec_v4_repeater-full-usb-wifi-ota-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.capabilities.json)
- [Full Repeater memory](heltec_v4_repeater-full-usb-wifi-ota-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.memory.json)
- [Full Room Server capabilities](heltec_v4_room_server-full-usb-wifi-ota-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.capabilities.json)
- [Full Room Server memory](heltec_v4_room_server-full-usb-wifi-ota-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.memory.json)
- [Full Sensor capabilities](heltec_v4_sensor-full-logging-ota-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.capabilities.json)
- [Full Sensor memory](heltec_v4_sensor-full-logging-ota-v1.17.1.8-halo-keymind-cascade-preview1-cab781f9a.memory.json)
