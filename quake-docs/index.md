# Mesh America Quake Repeater

A LoRa mesh repeater with an earthquake sensor. When the sensor feels strong shaking, the repeater posts one short message to a channel you choose, so people on your mesh hear about it within seconds, with no internet connection involved.

It is firmware for a RAK3401 repeater with an Omron D7S sensor (RAK12027), built from [Keymind Cascade](https://github.com/mikecarper/MeshCore), a MeshCore variant. It works as an ordinary repeater whether or not a sensor is fitted.

## Start here

- **[Get started](getting-started.md)**: flash a repeater, set its location and alert channel, and test it.
- **[What the sensor readings mean](reading-the-sensor.md)**: what the strength and peak-acceleration numbers tell you, and what they do not. Worth reading before you rely on an alert.
- **[Earthquake channel alerts](earthquake-alerts.md)**: how alerts behave, the message format and the commands.

## Reference

- **[The repeater's clock](clock-floor.md)**: why a repeater that loses power can confuse the MeshCore app, and how the firmware prevents it.
- **[D7S sensor integration](d7s-integration.md)**: hardware notes, behaviour and telemetry channels.
- **[Measurement contract](d7s-measurement-contract.md)**: the verified definition of every sensor register, with sources.

## An alert is not an earthquake report

One sensor, in one place, felt strong shaking. It does not say how big an earthquake was, where it started, or whether anything was damaged, and a knocked mast can set it off. Confirm with an official source before acting. [Details](reading-the-sensor.md).

## Links

- Flasher: <https://apps.meshamerica.com/quake-repeater/>
- Firmware releases: <https://github.com/Mesh-America/mesh-america-quake-repeater/releases>
- Source: <https://github.com/Mesh-America/mesh-america-quake-repeater>
