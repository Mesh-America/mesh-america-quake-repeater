---
layout: home
title: Mesh America Quake Repeater

hero:
  name: Quake Repeater
  text: A mesh repeater that can feel the ground move.
  tagline: When the sensor feels strong shaking, your repeater posts one short alert to a channel you choose, so your mesh hears about it in seconds. No internet involved.
  image:
    light: /emblem-light.svg
    dark: /emblem-dark.svg
    alt: Quake Repeater emblem
  actions:
    - theme: brand
      text: Get started
      link: /getting-started
    - theme: alt
      text: What the readings mean
      link: /reading-the-sensor
    - theme: alt
      text: Open the flasher
      link: https://apps.meshamerica.com/quake-repeater/

features:
  - iconName: bell-01
    title: Alerts in seconds
    details: The repeater sends its alert the moment the sensor finishes measuring, with the final strength and peak-acceleration numbers.
  - iconName: wifi
    title: Works when the internet is down
    details: The alert travels over your LoRa mesh like any other channel message. Nothing depends on a connection to the outside world.
  - iconName: target-05
    title: Honest numbers
    details: Strength (SI) and peak acceleration (PGA) from one sensor, labelled for what they are. Never a magnitude, never a guess at damage.
  - iconName: shield-tick
    title: Careful by design
    details: Only strong shaking sends anything. One message per shake, a quiet period after it, and a closing line that says it may not be an earthquake.
  - iconName: clock
    title: Keeps good time
    details: A restart or update will not set the repeater's clock back, which would otherwise stop the MeshCore app logging in.
  - iconName: cpu-chip-01
    title: A normal repeater first
    details: Built on Keymind Cascade for the RAK3401. It repeats like any other node, with or without a sensor fitted.
---

## What an alert looks like

<div class="alert-sample">
  <p class="alert-sample__meta">Channel #quake-alerts</p>
  <p>Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. This does not necessarily indicate an earthquake.</p>
</div>

The numbers come from an Omron D7S sensor on the repeater. The location is where the *repeater* is, rounded to about 1 km. [What each part means](reading-the-sensor.md).

## An alert is a local report, not an earthquake announcement

One sensor, in one place, felt strong shaking. It does not say how big an earthquake was, where it started, or whether anything was damaged, and a knocked mast can set it off. Confirm with an official source before acting.

## Where to go next

- **[Get started](getting-started.md)**: flash a repeater, set its location and alert channel, and test it.
- **[Earthquake channel alerts](earthquake-alerts.md)**: how alerts behave, the message format and the commands.
- **[What the sensor readings mean](reading-the-sensor.md)**: read this before you share the channel with others.
- **Reference**: [the repeater's clock](clock-floor.md), [D7S sensor integration](d7s-integration.md) and the [measurement contract](d7s-measurement-contract.md).

Firmware releases are on [GitHub](https://github.com/Mesh-America/mesh-america-quake-repeater/releases), and the source is in the [repository](https://github.com/Mesh-America/mesh-america-quake-repeater).
