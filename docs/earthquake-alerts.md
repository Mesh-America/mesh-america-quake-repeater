# Earthquake channel alerts

When the D7S feels strong shaking, the repeater can post one short message to a hashtag channel you choose. Nothing is sent unless you set that channel **and** the repeater's location (and its clock is valid).

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
3. **Check the clock.** `clock` should show today's date (UTC). If it shows 1970, set it with `time <epoch seconds>`, or `gps sync` with a GPS fitted. Without a battery-backed clock module or GPS the time is lost whenever power is lost, and alerts are held until it is set again.
4. **Send a test.** `earthquake test` posts a message that starts with `TEST:` (at most one every 30 seconds). If it is refused, the reply says which setting is missing.
5. **Check readiness any time** with `earthquake status`.

## What it does

- **Trigger:** the D7S's own strong-shaking decision (the manufacturer's threshold, roughly JMA intensity 5 Upper, damaging-shaking territory). There is no lower-sensitivity setting yet; that is waiting for real-world recordings.
- **One message per shake.** After sending, further reports are ignored for `earthquake.cooldown` minutes (default 10, range 1 to 1440).
- **Final numbers.** The sensor takes about two minutes to finish measuring, so the message waits for the final values (up to four minutes, then sends without them), plus a random 0 to 30 second delay so neighbouring repeaters do not all transmit at once.
- **Nothing queued for later.** If a requirement is missing at that moment (no channel, no location, no valid clock, a sensor fault) the alert is dropped and `earthquake status` counts it as held. Fixing the setting does not resend an old event.
- **Scope.** The message is flooded with the repeater's own default region (the same one its adverts use), so whatever scoping you have already set up applies. There is no separate alert region.
- Reports present at power-up are history and are ignored.

## The message

```
Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. This does not necessarily indicate an earthquake.
```

Coordinates are rounded to two decimals (about 1 km). Strength is the sensor's spectrum intensity (SI) and peak acceleration its PGA. The text is built to fit after the repeater's name; if the name is very long, detail is shortened (`peak 148 gal`, then values dropped) but the closing sentence is never cut. It is a vibration reading from one sensor, not an earthquake report.

## Commands

| Command | Meaning |
|---|---|
| `get` / `set earthquake.channel <#name\|off>` | Channel to post to; unset means no messages |
| `get` / `set earthquake.cooldown <minutes>` | Quiet period after a message |
| `earthquake test` | Send a `TEST:` message now |
| `earthquake status` | Ready or what is missing; sensor state; events, sent and held counts |

Settings are stored in `/quake_prefs`, separate from the shared preferences file.

## Not in this version

- No de-duplication across repeaters: two repeaters that both feel a shake each post once. Repeaters do not decode channel traffic, so they cannot see each other's alerts.
- Sensor-trigger only; no lower threshold and no severity bands (the measurement contract forbids inventing them).

## Code

`src/helpers/sensors/SeismicAlert.h/.cpp` hold all the decisions and the message text with no hardware dependency (`test/test_seismic_alert`). `examples/simple_repeater/MyMeshQuake.cpp` supplies the repeater's state and sends the packet. `D7S::Snapshot::shakingCount` counts significant-shaking reports so each is handled once.
