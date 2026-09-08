# Companion Offline Message Queue

Companion firmware keeps received channel data, channel messages, and direct
messages in one pending queue until a Companion client requests them with the
sync-next-message command. This is volatile RAM, not message history in flash.
A reboot clears it.

## Default capacities

| Platform or memory profile | Pending frames |
| --- | ---: |
| ESP32 with configured PSRAM | 512 |
| ESP32 without PSRAM | 256 |
| nRF52840 | 256 |
| T096 Full Companion with the memory correction | 256 normally; 128 while mOTA owns shared storage |
| RP2040 | 256 |
| STM32 | 16 |
| Known constrained classic ESP32 target override | 128 |
| Meshadventurer Full Companion | 16 |
| Constrained Full ESP32 fallback | 16 |

An explicit target `OFFLINE_QUEUE_SIZE` overrides the platform default. The
Heltec V2 and TLora V2 Full Companion profiles, for example, use 16 frames so
their combined WiFi, BLE, and LoRa mOTA image retains enough internal DRAM.
Meshadventurer SX1262 and SX1268 Full Companion use 16 frames together with 100
contacts and 30 group channels; their ordinary transport-specific images keep
128 frames and 40 channels.

The [T096 Full memory correction](releases/1.17.1.5.md#t096-full-companion-bluetooth-and-menu-freeze-report)
keeps 256 frames normally, while retaining 350 contacts, 40 channels, and all
Full transports. The upper 128 slots temporarily hold the mOTA context when
a source or TempRadio discovery session starts. Stopping or disconnecting the
USB/Bluetooth source returns all 256 slots; a discovery-only session returns
them when TempRadio ends. This shares a fixed memory region and avoids heap
fragmentation from resizing.

Existing unread messages retain their order. If more than 128 frames are
pending, mOTA refuses the loan and asks you to sync messages with a Companion
app first. While the loan is active, the overflow policy below applies at 128
frames. The original `26303793` 1.17.1.5 download reserves the queue and mOTA
state separately, leaving too little runtime headroom for its color display
and Bluetooth. The corrected profile recovers about 19 KiB by sharing storage
and requires at least 72 KiB of heap space at link time.

Standard, logging, MQTT, and Cascade build overlays retain the selected target
capacity; they do not silently shrink the queue.

Each queue slot currently costs 177 bytes. A 256-frame queue reserves 45,312
bytes, while a 512-frame queue reserves 90,624 bytes. There is no 256-frame
protocol limit: the queue length and indexes can represent 512 or more. The
practical limit is available RAM and the heap and stack headroom required by
the transports and display.

On ESP32 boards marked with `BOARD_HAS_PSRAM`, the queue is allocated from
PSRAM before WiFi and BLE start. A failed 512-frame allocation retries at 256,
then 128, and finally uses a 16-frame internal fallback. Full Companion prints
the capacity actually allocated in its startup memory line as
`offline_queue=<frames>`.

## Full queue behavior

The capacity is shared across Public, other channels, channel data, and direct
messages. It is not a per-channel count. When the queue is full, firmware
replaces the oldest queued channel frame so newer traffic can still arrive. If
the full queue contains only direct messages, a new frame is dropped rather
than deleting a direct message.

Queue order is preserved. Removal uses a ring index, so delivering one pending
message no longer copies every remaining frame; only the less-common removal
of an old channel frame from a full queue may shift entries.

Capacity is selected when firmware is compiled. There is no CLI or Companion
protocol setting to resize it at runtime.
