# How to admin your repeater

The commands an owner needs after flashing, in plain language. Type them into the repeater's serial console, the same place you changed the admin password (the flasher's Configure step does the common ones for you). A command that works answers "OK" or shows the value; one that does not says what is wrong.

This is the same guide as **How to admin your repeater** in the [flasher](https://apps.meshamerica.com/quake-repeater/).

## The basics

| Command | What it does |
|---|---|
| `ver` | Show which firmware this is and its version, for example "Quake Repeater v1.17.1.6". The admin tools show the same text as their version. Releases before 1.17.1.3 show just the version number. |
| `password <new password>` | Change the admin password. |
| `set name <name>` | Name the repeater. Keep it short: the name is part of every alert. |
| `set lat <degrees>` | Set the repeater's latitude, for example 47.61. |
| `set lon <degrees>` | Set its longitude, for example -122.33. |
| `advert` | Announce the repeater to the mesh now. |
| `reboot` | Restart the repeater. |

## The clock

A repeater with no clock module or GPS falls back to a built-in date (1 March 2026) after every restart or update. Until its clock is set, logging in to it from the MeshCore app can fail (setting the clock has fixed that). Alerts do not wait for the clock, but they carry the wrong date, which apps still show.

| Command | What it does |
|---|---|
| `clock` | Show the repeater's time (UTC). If it is not today's date, the clock is not set. |
| `time <epoch seconds>` | Set the time, as a Unix timestamp. |
| `gps sync` | Set the time from GPS, if a GPS module is fitted and on. |
| `get clock.floor` | Show whether the repeater is keeping its clock from going backwards across a restart, the time it last saved, how many saves it has made, and whether the clock was restored at the last boot. |
| `set clock.floor on` | Keep the clock from going backwards across a restart (the default). Use `off` to turn it off. |
| `set clock.floor.interval <minutes>` | Minutes between saves, 10 to 1440. The default is 360, four saves a day: it keeps flash wear low. |

Without a battery-backed clock module or GPS, the time is lost whenever power is lost and has to be set again. The flasher's Configure step warns when the clock is not set and has a button to set it.

From firmware 1.17.1.5 the repeater saves the time it last reached and, after a restart, comes back at that time plus one save interval. That keeps the MeshCore app able to log in without a manual step. After a power cut the clock can read up to one interval (6 hours by default) ahead of real time; set the clock to correct it. [More on the clock](clock-floor.md).

## Region

Alert messages are sent with the repeater's default region, the same one its adverts use. There is no separate alert region: set it the way you would for any repeater.

| Command | What it does |
|---|---|
| `region default` | Show the default region. |
| `region default <name>` | Set the default region. |

## Earthquake alerts

When the sensor reports strong shaking, the repeater posts one short message to a hashtag channel. Nothing is sent until a channel and a location are both set.

| Command | What it does |
|---|---|
| `set earthquake.channel #your-channel` | Choose the channel. Letters, digits and dashes only. `#test`, `#bot` and the Public channel are refused. |
| `set earthquake.channel off` | Turn alerts off. With no channel set, nothing is ever sent. |
| `get earthquake.channel` | Show the channel. |
| `set earthquake.cooldown <minutes>` | Quiet time after a message, 1 to 1440 minutes. The default is 10. |
| `get earthquake.cooldown` | Show the quiet time. |
| `earthquake test` | Post a test message starting with "TEST:". Allowed once every 30 seconds. |
| `earthquake status` | Say whether alerts are ready, or what is missing, where a current event is (about to send, waiting for the sensor's final numbers, or quiet), the sensor state, and how many events were seen, sent and held. |

- The message reads: "Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. This does not necessarily indicate an earthquake." Coordinates are rounded to about 1 km. [What the numbers mean](reading-the-sensor.md).
- The message goes out as soon as the sensor has finished measuring, about two minutes after the shaking starts, so it can carry the final numbers. If the sensor has not finished after two and a half minutes, the message is sent without numbers.
- If the repeater's name is very long, the numbers are shortened first. The closing sentence is never cut.
- An alert is dropped, not saved for later, if something is missing when it is due. Fixing the setting does not resend an old event.
- Two repeaters that both feel the same shaking each post once.

More in [Earthquake channel alerts](earthquake-alerts.md).

## When status says "NOT READY"

| It says | What to do |
|---|---|
| `earthquake.channel is not set` | Run `set earthquake.channel #your-channel`. |
| `location is not set (set lat and lon)` | Run `set lat` and `set lon`. A location of exactly 0,0 counts as not set. |

If the sensor shows "fault" or "not found", check that the RAK12027 sits in sensor slot A, then restart the repeater.
