# What the sensor readings mean

The Quake Repeater has an Omron D7S seismic sensor. It measures how hard the repeater's own enclosure is being shaken and decides, by itself, whether the shaking is strong enough to matter. This page explains what its numbers and flags mean, and what they do not. For the exact registers and conversions see the [measurement contract](d7s-measurement-contract.md).

## The short version

- An alert means **one sensor, at one spot, felt strong shaking**. It is not an earthquake report. It does not say how big the earthquake was, where it started, or whether anything was damaged.
- Two numbers come with it: **strength (SI)**, how damaging the shaking could be to buildings, and **peak acceleration (PGA)**, the hardest single jolt.
- Higher numbers mean harder shaking *at that repeater*. Compare readings from the same sensor; do not compare them with magnitudes.
- Check an official source (USGS, your national seismic network, local emergency management) before concluding that an earthquake happened.

## The two numbers

### Strength: spectrum intensity (SI), in cm/s

SI summarises how much energy the shaking carries at the speeds that matter to buildings and other structures. The sensor calculates it itself and reports it in centimetres per second (the unit is also called a kine). A message that says `Strength 43.3 cm/s` is reporting SI 43.3.

SI is the better number for judging whether the shaking was dangerous. A short sharp jolt can have a high peak acceleration and a low SI, because it does not last long enough to move a structure much.

### Peak acceleration (PGA), in gal

PGA is the largest acceleration the sensor measured during the event, in gal (1 gal is 1 cm/s²). To compare with the familiar unit, divide by 980.665 to get g, so `148 gal` is about 0.15 g, roughly 15% of the pull of gravity.

PGA is a good measure of the hardest single moment, such as how hard things were thrown. It says less about how long the shaking lasted.

### Reading them together

| SI | PGA | What it usually means |
|---|---|---|
| High | High | Strong, sustained shaking |
| Low | High | A short, sharp jolt: an impact, a dropped object, a passing heavy vehicle |
| High | Moderate | Longer, slower shaking, which is the kind that tends to affect larger structures |

These are rules of thumb for interpreting two readings from one sensor, not categories the firmware assigns. The firmware does not rate shaking as mild, moderate or severe, because there is no validated way to turn these numbers into such labels.

## Why an alert only appears for strong shaking

The sensor makes its own decision. It raises a **significant shaking** flag when shaking passes the manufacturer's threshold, which is described as equivalent to **Japan Meteorological Agency (JMA) intensity 5 Upper**: strong shaking in which people find it hard to stay upright and furniture can move. That is a judgement about the shaking at the sensor, not a measured JMA reading and not a magnitude.

The practical effects:

- **Weak and moderate shaking never produces an alert.** A small earthquake that you can feel, or a truck going past, stays below the threshold. There is no lower-sensitivity setting yet.
- **Every alert is a strong-shaking event** for that sensor, so a sent alert is worth taking seriously, but see the limits below.
- **The numbers in an alert are final values.** The sensor spends about two minutes measuring an event and the repeater waits for the finished result. If the sensor has not finished after two and a half minutes the alert goes out without numbers.

## What the readings are not

| Not this | Because |
|---|---|
| Richter or moment magnitude | Magnitude describes the energy released at the source. These readings describe shaking at one location. The same earthquake gives very different readings at different distances and on different ground. |
| An epicenter or distance | One sensor cannot locate an earthquake. The location in the message is where the *repeater* is, rounded to about 1 km. |
| A damage assessment | The sensor cannot tell whether a building was damaged. A tilt flag does not mean anything collapsed. |
| A calibrated ground-motion measurement | The sensor measures its own enclosure. Where it is mounted, what it is mounted on, and whether the enclosure was knocked or moved all change the reading. |

## Things that can set the sensor off

The sensor responds to vibration of any cause, not just earthquakes:

- Wind moving the repeater, or the mast, pole or cable it hangs from
- Hitting, dropping or moving the repeater or the mast it is on
- Construction, blasting, heavy machinery, trains
- A sensor that has itself reported a fault

Most of these come down to how and where the repeater is mounted: see [placement, mounting and testing](placement-and-testing.md), and run a new repeater on a test channel for a week or two before it reaches a channel people rely on.

This is why every message ends with "This does not necessarily indicate an earthquake." If several repeaters in different places report at about the same moment, that is much stronger evidence than a single report. The repeaters do not compare notes with each other, so that comparison is up to the people reading the channel.

## How to use an alert

1. Treat it as "someone's repeater just felt a big shake near here".
2. Look at the strength and peak acceleration. Values well above the others you have seen from that repeater are more significant than ones near the usual trigger level.
3. Look for other reports, from other repeaters or from people on the channel.
4. Confirm with an official source before acting on it. Official agencies can give a magnitude and a location; this sensor cannot.
5. If it was clearly local (someone hit the mast), say so on the channel.

## Telemetry readings

Besides alerts, the repeater reports the sensor's readings in its telemetry, for apps that read them. Telemetry shows more than an alert does, and some of it needs care:

| Reading | What it tells you | Watch out for |
|---|---|---|
| **Sensor health** | 1 means the repeater has talked to the sensor recently; 0 means it has not | Check this first. Other readings are only meaningful when health is 1. |
| **Sensor state** | 0 standby (normal), 1 processing an event, 2 to 4 installation, offset acquisition and self-test | State 1 alone does not mean an earthquake. |
| **Live SI** and **Live PGA** | Values while the sensor is measuring an event | They return to zero when the measurement ends. Live PGA is reported as a raw count whose scale the manufacturer has not confirmed, so do not read it as gal. |
| **Recorded events** | Flags seen since the repeater started: significant shaking, tilt, self-test error, baseline error | A bit mask, not a count, and it clears only on reboot. A flag from last week is still shown. |
| **Stored SI** and **Stored PGA** | The most recent record kept inside the sensor | This is history. It may predate the repeater's last restart and has no timestamp, so it does not mean something just happened. Divide by 10 for cm/s and gal. |

A **tilt** flag means the sensor was tilted past its limit, as if its mounting had moved or fallen. It does not establish that a building collapsed.

## Typical questions

**The alert said 43.3 cm/s. Is that big?** It is above the sensor's strong-shaking threshold, so it counts as strong shaking for that location. There is no scale on this page that turns it into a magnitude, and one reading cannot say how it compares with an earthquake you may have heard about.

**Why did I get an alert for something I did not feel?** The sensor sits at one place, possibly on a tower or a roof, where shaking can be stronger than on the ground nearby. It may also have been knocked.

**Why did I feel an earthquake and get no alert?** The shaking at that repeater stayed below the sensor's threshold, which is high. Distance, ground type and where the repeater is mounted all matter.

**Why does the message have no numbers?** The sensor had not finished measuring after two and a half minutes, so the repeater sent the alert without waiting any longer.

**Are the stored values from the shake I just felt?** Not necessarily. The sensor keeps history across power cycles, and the repeater cannot tell how old a stored record is.

See also: [earthquake channel alerts](earthquake-alerts.md) for setup and the message format, and [D7S integration](d7s-integration.md) for the hardware and telemetry channel details.
