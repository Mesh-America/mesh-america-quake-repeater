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

Use the application `.bin` for WiFi OTA. A clean USB install uses the merged
image at address 0. When manually writing the application at `0x10000`, an
existing OTA selector may still boot app1. Check the running `ver` afterward.
On the matching V4 16 MB layout only, clearing the 8 KB `otadata` partition at
`0xe000` selects the newly written app0 without clearing NVS/settings. Confirm
the partition table and verify the app write before changing that selector.

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

## Hardware and build results, 2026-09-08

Source revision `eeea15ef` passed seven representative firmware builds:

| Hardware/profile | Display | RAM beyond the required startup budget, bytes |
| --- | --- | ---: |
| V4.2/V4.3 Full NimBLE Picopixel | SSD1306 | 88,072 |
| T096 Full, FEM on | ST7735 | 24,778 |
| Station G3 ESP32 Full | SH1106 | 82,080 |
| RAK3401 Full | SSD1306 | 46,108 |
| Wireless Tracker Full NimBLE capacity trial | ST7735 | 28,022 |
| Wio Tracker L1 Full | SH1106 | 45,744 |
| T-Echo Card BLE Companion | U8g2 | 30,992 |

These are linked-capacity checks before runtime allocation, not live free
heap measurements. The six Full profiles also passed their required OTA
packaging checks. The T-Echo Card row is a BLE Companion build.

Both physical V4.3 nodes, `NimBLE-V4-VM` and `NimBLE-V4-Trial`, were flashed,
their image hashes verified, and their running versions confirmed. Each
passed 201 USB protocol requests with zero reported error flags. The
Mercerwood V4 also reconnected over authenticated, bonded Bluetooth with
MTU 179 and the existing factory-address policy.

A private XIAO-to-V4 LoRa test delivered all 160 message bytes. The V4
continued responding during 20 seconds of message redraws, with zero error
flags. Both temporary channel configurations were restored. Free internal
heap after that interval was 147,200 bytes, minimum 146,340 bytes, and the
largest free block was 139,252 bytes. These are short functional checks;
physical readability remains a user judgment.

A matching pre/post-boot Mercerwood measurement showed the longer preview
using 2,816 additional PSRAM bytes, with unchanged internal free heap. Boards
without PSRAM use their ordinary RAM for the larger preview records.

The native display/history suites passed 31 tests. The Python font, RAM,
pairing, display-profile, queue and QR checks passed 38 tests. The Adafruit
comparison covers all 95 printable ASCII glyphs.

V4 application SHA-256:
`d914d80124b499d7b719f8427f3794ab1b6d15fd0112e3ef89ba2fac26b5a974`.
