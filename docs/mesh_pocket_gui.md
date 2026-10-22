# MeshPocket Full Companion display

Full Companion on MeshPocket includes a channel message board, a worldwide
coastline map and display settings. Other boards keep their existing home UI.
USB, Bluetooth and notifications remain available.

Use the Pocket's user button:

| Page | One click | Two clicks | Hold |
| --- | --- | --- | --- |
| Normal pages | Next page | Previous page | Page action |
| Message board, browsing | Older message | Newer message | Finish browsing |
| Map, zooming | Zoom in | Zoom out | Save and finish |
| Settings, editing | Change value | Next setting | Save and finish |

Hold on the message board, map or settings page to enter its mode. Three or
four clicks on the board select the next or previous configured channel.
The inbox still opens individual messages, including direct messages.

The board shares the existing 32-message history, showing the selected channel
with sender names and local timestamps. Successfully sent app messages appear
there too. History is held in RAM; it is not a permanent message archive.

Settings cover channel, text size, sender name length, screen orientation,
light/dark theme, return-to-board delay, full refresh interval and map zoom.
They use a separate checked, atomically replaced record in primary storage.
Existing node, channel and contact formats are unchanged. Timezone comes from
the existing node preferences.

Changing pages or map zoom uses a full clean refresh to clear the previous
image. Updates within the same page keep the faster partial refresh, with a
clean refresh after at most ten partial updates. Settings allow shorter
intervals of one, three or five updates.

The idle screen-off timer defaults to 15 minutes on battery and USB. Existing
saved timeouts are retained; set `display.timeout` and `display.usb.timeout` to
`900` to use 15 minutes. The return-to-board delay is a separate setting.

The map centres on this node's location, or the first contact with a location.
With no locations it shows a world overview. Contacts appear as dots, with
nearby names at closer zooms. The view spans 20,000 km down to 5 km vertically;
coastline detail stays coarse at close zooms. It contains no streets, terrain,
regional downloads or ocean tiles. See the [map data notes](../tools/meshpocket_map/README.md)
for resolution, storage and reproducible generation.

The UI is adapted from [MeshCore-Mesh-Pocket-MessageBoard](https://github.com/jackywashere/MeshCore-Mesh-Pocket-MessageBoard).
Include [PocketGui-NOTICE.txt](../tools/meshpocket_map/PocketGui-NOTICE.txt) alongside
distributed firmware for the UI and font notices. The application DFU ZIP keeps
its required manifest, binary and metadata entries; the notice is a sidecar.

Build with `Mesh_pocket_companion_radio_full`. Defining `UI_POCKET_GUI=0`
retains the standard Pocket display.
