# Earthquake channel alerts

When the D7S feels strong shaking, the repeater can post one short message to a hashtag channel you choose. Nothing is sent unless you set that channel **and** the repeater's location.

Status: experimental, first released as an alpha. The alert logic is unit tested on a PC; it has not been exercised against a real shake.

## Set it up

1. **Set the location.** The message names where the shaking was felt, so the repeater must know where it is. Either set `lat` and `lon` or use a GPS fix:

   ```
   set lat 47.61
   set lon -122.33
   ```

   A location of exactly 0,0 (the factory default) counts as not set.
2. **Set the channel.** Any hashtag channel your community uses; letters, digits and dashes only:

   ```
   set earthquake.channel #quake-alerts
   ```

   `set earthquake.channel off` turns alerts off again. `#test`, `#bot` and the Public channel are refused, because bots and every nearby phone answer there.
3. **Send a test.** `earthquake test` posts a message that starts with `TEST:` (at most one every 30 seconds). If it is refused, the reply says which setting is missing.
4. **Check readiness any time** with `earthquake status`.

## What it does

- **Trigger:** the D7S's own strong-shaking decision (the manufacturer's threshold, roughly JMA intensity 5 Upper, damaging-shaking territory). There is no lower-sensitivity setting yet; that is waiting for real-world recordings.
- **One message per shake.** After sending, further reports are ignored for `earthquake.cooldown` minutes (default 10, range 1 to 1440).
- **As fast as the numbers allow.** The sensor takes about two minutes to finish measuring, and the message carries its final values, so it goes out the moment the sensor is done, plus a random delay of up to 2 seconds so neighbouring repeaters do not all transmit in the same instant. If the sensor has not finished after two and a half minutes, the alert is sent without numbers rather than later. `earthquake status` shows where an event is while it waits.
- **Nothing queued for later.** If a requirement is missing at that moment (no channel, no location, a sensor fault) the alert is dropped and `earthquake status` counts it as held. Fixing the setting does not resend an old event.
- **Scope.** The message is flooded with the repeater's own default region (the same one its adverts use), so whatever scoping you have already set up applies. There is no separate alert region.
- Reports present at power-up are history and are ignored.

## The message

```
Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. This does not necessarily indicate an earthquake.
```

Coordinates are rounded to two decimals (about 1 km). Strength is the sensor's spectrum intensity (SI) and peak acceleration its PGA. The text is built to fit after the repeater's name; if the name is very long, detail is shortened (`peak 148 gal`, then values dropped) but the closing sentence is never cut. It is a vibration reading from one sensor, not an earthquake report.

## Telling which firmware a repeater runs

`ver` answers with the product name and version, for example `Mesh America Quake Repeater v1.17.1.3 (Build: 04 Oct 2026)`, so it is clear this is the earthquake firmware and not stock MeshCore or Keymind Cascade. The same text is what a remote admin sees when it asks for the version. Earlier releases (1.17.1.2 and before) answered with the bare version number.

## Commands

| Command | Meaning |
|---|---|
| `get` / `set earthquake.channel <#name\|off>` | Channel to post to; unset means no messages |
| `get` / `set earthquake.cooldown <minutes>` | Quiet period after a message |
| `earthquake test` | Send a `TEST:` message now |
| `earthquake status` | Ready or what is missing; sensor state; events, sent and held counts |

Settings are stored in `/quake_prefs`, separate from the shared preferences file.

## The clock

Alerts do not need the clock. A repeater with no battery-backed clock module or GPS starts at 1970 after every power loss and then sends alerts stamped with that date. Clients still show them (tested), just with the wrong time. Set the time with `time <epoch seconds>` (or `gps sync` with a GPS fitted) if you want proper timestamps.

## Not in this version

- No de-duplication across repeaters: two repeaters that both feel a shake each post once. Repeaters do not decode channel traffic, so they cannot see each other's alerts.
- Sensor-trigger only; no lower threshold and no severity bands (the measurement contract forbids inventing them).

## Code

`src/helpers/sensors/SeismicAlert.h/.cpp` hold all the decisions and the message text with no hardware dependency (`test/test_seismic_alert`). `examples/simple_repeater/MyMeshQuake.cpp` supplies the repeater's state and sends the packet. `D7S::Snapshot::shakingCount` counts significant-shaking reports so each is handled once.
