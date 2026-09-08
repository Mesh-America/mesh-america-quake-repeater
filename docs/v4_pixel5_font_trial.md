# Small-screen Picopixel message font

Small-screen Companion builds use Picopixel for received message text and the
channel/sender line, including `Ch 0 Public`. This covers SSD1306 and SH1106
OLEDs, ST7735 small TFTs, and the U8g2 T-Echo Card display. The shared renderer
uses the same font data on every driver. Larger displays keep their existing
font. Menus, Bluetooth PINs and WiFi setup QR codes keep their normal layout.

Capital letters are 5 logical pixels high; descenders can occupy a sixth
pixel, so lines advance by 7 pixels. Most characters advance by 4 pixels
horizontally. The normal OLED font uses 7-pixel letters, 8-pixel line spacing
and 6-pixel character advances. Small TFTs retain their existing logical to
physical scaling.

On a 128 x 64 OLED, compacting the channel/sender line moves message text from
y=25 to y=21. Six complete small-font rows fit instead of five, roughly 30
additional characters depending on the letters. Text wraps at character
boundaries; the last line ends with `...` if it still cannot fit. Unsupported
characters appear as `?`. Long channel/sender names are ellipsized so they
cannot overlap the message.

The preview buffer holds a complete 160-byte MeshCore message plus its
terminator. Previously the main message UI allocated 78 bytes, leaving room
for only 77 bytes of text. It still retains 32 previews; larger records add
about 2.8 KB of RAM. The firmware RAM guard includes that increase. This
history is separate from the offline queue and its mOTA policy.

The tiny 72 x 40 T-Echo Card interface now previews the latest received
message below its status bar, with three small-font message rows. A button
press dismisses it. It stores one full message, and shows `...` when the
screen fills. Incoming text does not replace an active Bluetooth pairing PIN.

## V4 hardware trial

Enable `platformio.nimble.ini` in the ignored `platformio.local.ini` as shown
in the [NimBLE trial guide](nimble_companion_trial.md#build), then run:

```sh
OUTPUT_DIR=.releases/v4-pixel5 bash build.sh build-firmware \
  heltec_v4_2_v4_3_companion_radio_full_femon_nimble_pixel5 \
  --firmware-version v1.17.1.5-halo-keymind-cascade-pixel5-trial \
  --radio-preset usa-cascadia --profile cascade --standard --require-ota
```

The named trial keeps NimBLE, 350 contacts, 40 channels, the V4's 512-frame
PSRAM queue, USB mOTA sending and WiFi OTA support. The smaller font is also
the default in ordinary small-screen Companion builds from this source.

For a V4 already using the matching 16 MB Full Companion partition layout,
flash the application `.bin` at `0x10000`, or use it for WiFi OTA. A clean
USB install uses the merged image at address 0.

A custom build can set `-D UI_SMALL_MESSAGE_FONT=0` to restore the old font
and spacing. Remove any explicit `UI_MSG_PREVIEW_SIZE` flag too if the old
preview capacity is desired. These are compile-time options, not CLI commands.
No settings erase is necessary when changing between matching V4 layouts.

## Verification

```sh
python3 -B test/test_ssd1306_picopixel.py
python3 -B test/test_firmware_ram.py
pio test -e native -f test_display_driver -f test_companion_message_history
```

The native tests exercise the shared renderer, five-pixel capitals, complete
rows at display edges, long sender lines, overflow markers and tiny/rotated
screen geometry. The additional Adafruit comparison checks all 95 printable
ASCII glyphs pixel for pixel against the original Picopixel font, under
address/undefined-behavior sanitizers. That comparison needs a cached
PlatformIO Adafruit GFX library; set `MESHCORE_GFX_LIBRARY` to its directory
if needed. It reports a skip when the library is absent. The native tests do
not require that dependency. Run only one PlatformIO command at a time.
