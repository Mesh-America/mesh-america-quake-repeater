# V4 Picopixel message font trial

This optional V4.2/V4.3 OLED Full Companion build uses Adafruit's Picopixel
font for received message text. Capital letters are 5 pixels high; descenders
can occupy a sixth pixel, so lines advance by 7 pixels. Most characters
advance by 4 pixels horizontally, compared with the normal font's 6 pixels.
The normal font has 7-pixel letters and an 8-pixel line height.

The title, channel/sender, menus, Bluetooth PIN and WiFi QR page retain their
normal font. The message preview buffer increases from 78 bytes (77 text
bytes plus a terminator) to 161 bytes, enough for a complete 160-byte MeshCore
message. The screen retains 32 previews; this is separate from the V4's
512-frame offline queue and its mOTA policy.

Five complete Picopixel message lines fit below the title and sender on the
128 x 64 OLED. A typical message can fit in full; wide letters can still
exceed the available space. The last line then ends with `...`. Text wraps
at character boundaries. Unsupported characters appear as `?`.

## Build and install

Enable `platformio.nimble.ini` in the ignored `platformio.local.ini` as shown
in the [NimBLE trial guide](nimble_companion_trial.md#build), then run:

```sh
OUTPUT_DIR=.releases/v4-pixel5 bash build.sh build-firmware \
  heltec_v4_2_v4_3_companion_radio_full_femon_nimble_pixel5 \
  --firmware-version v1.17.1.5-halo-keymind-cascade-pixel5-trial \
  --radio-preset usa-cascadia --profile cascade --standard --require-ota
```

For a V4 already using the matching 16 MB Full Companion partition layout,
flash the application `.bin` at `0x10000`, or use it for WiFi OTA. A clean
USB install uses the merged image at address 0. The trial preserves NimBLE,
350 contacts, 40 channels, USB mOTA sending and WiFi OTA support.

To restore the normal message font, install
`heltec_v4_2_v4_3_companion_radio_full_femon_nimble`. Both builds use the same
partition layout; erasing settings is unnecessary.

## Verification

```sh
python3 -B test/test_ssd1306_picopixel.py
pio test -e native -f test_display_driver -f test_companion_message_history
```

The font test uses the real SSD1306 driver, Adafruit GFX rendering and
Picopixel bitmaps with a host panel double. It checks a full 160-character
sample, all printable ASCII characters, descenders, rotations, bottom-edge
clipping, overflow markers, unsupported-character placeholders and restoring
the normal font. It runs with address/undefined-behavior sanitizers. It needs
the Adafruit GFX dependency from an existing PlatformIO build; without that
dependency it reports a skip. Run only one PlatformIO command at a time.
