# Clock floor: the clock never goes backwards across a restart

## The problem

A repeater with no clock module or GPS loses the time when power is lost or an update (a Bluetooth OTA, for example) is installed. On this board the clock then falls back to **1 March 2026**, the firmware's built-in starting date. It survives only a *soft* reset (it is held in retained RAM).

Peers that already saw a later timestamp from the repeater treat its lower ones as replays (see "A backward correction is intentionally allowed" in the clock sync section of [cli_commands.md](cli_commands.md)). In practice the MeshCore app could not log in to a repeater after an OTA update until its clock was set by hand.

## What it does

The repeater saves, in flash, the last time its clock was known to have reached (`renewed at`) and renews it every **interval** (default 360 minutes, so four writes a day). The clock cannot have run more than one interval past that. After a restart that left the clock **clearly behind** the saved time, the clock is set to `renewed at + interval + 20 minutes`:

- never behind anything the repeater sent before the restart, so peers accept it;
- at most about one interval **ahead** of real time after a quick restart, and behind real time (but still ahead of what peers saw) after a long outage;
- a clock that survived the restart (retained RAM after a soft reset, a real RTC chip, GPS) is already right and is left alone.

Setting the clock by hand, or mesh clock sync, takes over as before. If the clock is set **earlier**, the saved time is lowered at once, so an old future value cannot drag the clock forward at the next restart. Just before a planned `reboot`, `clkreboot` or `start ota`, the time is saved first (only if the saved time is more than ten minutes old).

A damaged, wrong-version or implausible file is ignored, never trusted.

## Why only four writes a day

The internal filesystem is 28 KB (seven flash pages), and each atomic file replace erases and rewrites several 4 KB pages, each rated for about 10,000 erases. At four writes a day that is roughly thirteen years in the worst case (an estimate; `get clock.floor` counts writes so it can be checked). A shorter interval means less clock error after a power cut but more wear.

## Commands

| Command | Meaning |
|---|---|
| `get clock.floor` | On or off, the interval, the saved time, writes made (and failed), and whether the clock was restored at boot |
| `set clock.floor <on\|off>` | Turn it on or off (default on) |
| `get clock.floor.interval` / `set clock.floor.interval <minutes>` | Minutes between saves, 10 to 1440 (default 360) |

Example: `> on, every 360 min; saved 2026-10-04 18:00 UTC; 3 writes (0 failed); boot: restored 2026-03-01 00:12 -> 2026-10-05 00:21`.

The setting is stored in `/clock_floor` together with the saved time.

## Hardware test

1. `get clock.floor` on a repeater that has been running for a while: it shows `saved …` within the last interval.
2. Pull power for a minute, restore it, and run `clock` and `get clock.floor`: the clock should be near the real time, no earlier than before the cut, and `boot: restored …` is shown.
3. Log in from the MeshCore app without setting the clock by hand.
4. After a Bluetooth OTA update, repeat 2 and 3: the time was saved just before the update started.
5. Set the clock to an earlier time and check `saved` moves back to it, then cut power and confirm the clock does not come back in the future.

## Where the code is

`src/helpers/sensors/ClockFloor.h/.cpp` hold the decisions with no hardware dependency; `test/test_clock_floor` tests them, including a 60-day simulation with random power cuts that checks the clock never goes backwards across a restart. `examples/simple_repeater/MyMeshQuake.cpp` reads and writes the file and adds the commands, with small hooks in `MyMesh.cpp` and `MyMesh.h` guarded by `ENV_INCLUDE_D7S`.
