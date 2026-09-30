## Halo Keymind Cascade Branch Changes over Stock

* **Two parallel LoRa radio settings on one device at the same time.** Alternate rx & tx between two frequencies and/or modulation settings. Choose transmission profiles per contact or channel, enable or isolate crossover traffic, schedule profiles, and use a temporary update profile alongside the normal network. Includes timing calibration and separate R2 screen pages. These are time-shared profiles on one transceiver.
* **Firmware updates over LoRa.** Update repeaters/rooms/sensors over LoRa.
* **Repeater forwarding policies.** Actions include dropping, rate limiting, assigning scopes, selecting retries, and controlling forwarding priority. Separate policies cover ordinary radio forwarding, bridges, and profile crossover.
* **Flood retries that account for network topology.** Configure retry counts, path limits, packet-type limits, target prefixes, ignored repeaters, and channel-specific eligibility. Bridge buckets keep retrying until traffic is heard on the intended sides of a relay or the retry budget expires. Qualifying echoes cancel unnecessary attempts.
* **Enhanced direct-message and direct-route retries.** Dynamic coding-rate, keep trying until echo hear.
* **Enhanced Telemetry.** Single LoRa packet supports multiple days of temperature or battery voltage or GPS history.
* **Unified Full Companion firmware.** Combines USB, BLE, WiFi, and Ethernet/serial transports in one image; with runtime controls and a LoRa firmware-serving mode. Most supported targets can operate multiple transports together; some boards have explicit transport restrictions.
* **Operational reporting and alerts.** Adds optional management reports with firmware version, bootloader version, LoRa update capabilities, uptime, and historical voltage and temperature ranges.
* **Set time using LoRa Network.** Automatically set the clock based off the LoRa network. Better than 2024.
* **Companion Bluetooth privacy and recovery improvements.** Configurable mac address policies, paired-peer stealth behavior, and changes to reconnect, subscription, and startup handling.
* **Single Key DMs.** Allow for you to send your advert in the initial DM. Makes DMing a bot/bbs/etc a lot easier if they're also running this firmware. 
* **agessaman Observer - ESP32 Integrated MQTT observation.** Send directly from the node to the observer api endpoint.
* **IoTThinks PowerSaving - Broader power-saving controls.** Integrates device sleep, LoRa receive duty cycling, WiFi modem-sleep policies, and GPS acquisition/cache schedules across supported roles. These controls are independently configurable; actual savings depend on hardware and workload.

Get the correct firmware file here for your hardware:
**https://mikecarper.github.io/MeshCore/firmware_picker/**

---

## About MeshCore

MeshCore is a lightweight, portable C++ library that enables multi-hop packet routing for embedded projects using LoRa and other packet radios. It is designed for developers who want to create resilient, decentralized communication networks that work without the internet.

## What is MeshCore?

MeshCore now supports a range of LoRa devices, allowing for easy flashing without the need to compile firmware manually. Users can flash a pre-built binary using tools like Adafruit ESPTool and interact with the network through a serial console.
MeshCore provides the ability to create wireless mesh networks, similar to Meshtastic and Reticulum but with a focus on lightweight multi-hop packet routing for embedded projects. Unlike Meshtastic, which is tailored for casual LoRa communication, or Reticulum, which offers advanced networking, MeshCore balances simplicity with scalability, making it ideal for custom embedded solutions, where devices (nodes) can communicate over long distances by relaying messages through intermediate nodes. This is especially useful in off-grid, emergency, or tactical situations where traditional communication infrastructure is unavailable.

> **Upstream Observer WiFi and MQTT** - Observer firmware, release notes, and browser-based
> flashing are available at [observer.gessaman.com](https://observer.gessaman.com/).
> See [WiFi and MQTT by Firmware Type](./docs/WiFi.md) for the
> role/build matrix and setup overview. For the complete MQTT command and
> broker reference, see the [MQTT Implementation Guide](./MQTT_IMPLEMENTATION.md).

## Key Features

* Multi-Hop Packet Routing
  * Devices can forward messages across multiple nodes, extending range beyond a single radio's reach.
  * Supports up to a configurable number of hops to balance network efficiency and prevent excessive traffic.
  * Companion nodes do not repeat by default. Supported Companion builds can opt into bounded client repeating on permitted frequencies, while dedicated repeaters remain the normal way to extend coverage.
* Supports LoRa Radios - Works with Heltec, RAK Wireless, and other LoRa-based hardware.
* Decentralized & Resilient - No central server or internet required; the network is self-healing.
* Low Power Consumption - Ideal for battery-powered or solar-powered devices.
* Simple to Deploy - Pre-built example applications make it easy to get started.

## What Can You Use MeshCore For?

* Off-Grid Communication: Stay connected even in remote areas.
* Emergency Response & Disaster Recovery: Set up instant networks where infrastructure is down.
* Outdoor Activities: Hiking, camping, and adventure racing communication.
* Tactical & Security Applications: Military, law enforcement, and private security use cases.
* IoT & Sensor Networks: Collect data from remote sensors and relay it back to a central location.

## How to Get Started

- Watch the [MeshCore QuickStart Playlist](https://www.youtube.com/watch?v=iaFltojJrAc&list=PLshzThxhw4O4WU_iZo3NmNZOv6KMrUuF9) by The Comms Channel
- Watch the [MeshCore Technical Presentation](https://www.youtube.com/watch?v=OwmkVkZQTf4) by Liam Cottle.
- Read through our [Frequently Asked Questions](./docs/faq.md) and [Documentation](https://docs.meshcore.io).
- Flash the MeshCore firmware on a supported device.
- Connect with a supported client.

For developers:

- Install [PlatformIO](https://docs.platformio.org) in [Visual Studio Code](https://code.visualstudio.com).
- Clone and open the MeshCore repository in Visual Studio Code.
- Install the pinned build-time compressors with `python -m pip install -r requirements-build.txt`.
- See the example applications you can modify and run:
  - [Companion Radio](./examples/companion_radio) - For use with an external chat app, over BLE, USB or Wi-Fi.
  - [KISS Modem](./examples/kiss_modem) - Serial KISS protocol bridge for host applications. ([protocol docs](./docs/kiss_modem_protocol.md))
  - [Simple Repeater](./examples/simple_repeater) - Extends network coverage by relaying messages.
  - [Simple Room Server](./examples/simple_room_server) - A simple BBS server for shared Posts.
  - [Simple Secure Chat](./examples/simple_secure_chat) - Secure terminal based text communication between devices.
  - [Simple Sensor](./examples/simple_sensor) - Remote sensor node with telemetry and alerting.

The Simple Secure Chat example can be interacted with through the Serial Monitor in Visual Studio Code, or with a Serial USB Terminal on Android.

## MeshCore Flasher

We have prebuilt firmware ready to flash on supported devices.

- Launch https://meshcore.io/flasher
- Select a supported device
- Flash one of the firmware types:
  - Companion, Repeater or Room Server
- Once flashing is complete, you can connect with one of the MeshCore clients below.

## MeshCore Clients

**Companion Firmware**

The companion firmware can be connected to via BLE, USB or Wi-Fi depending on the firmware type you flashed.

- Web: https://app.meshcore.nz
- Android: https://play.google.com/store/apps/details?id=com.liamcottle.meshcore.android
- iOS: https://apps.apple.com/us/app/meshcore/id6742354151?platform=iphone
- NodeJS: https://github.com/meshcore-dev/meshcore.js
- Python: https://github.com/meshcore-dev/meshcore-cli

**Repeater and Room Server Firmware**

The repeater and room server firmware can be set up via USB in the web config tool.

- https://config.meshcore.io

They can also be managed via LoRa in the mobile app by using the Remote Management feature.

## Hardware Compatibility

MeshCore is designed for devices listed in the [MeshCore Flasher](https://meshcore.io/flasher)

## License

MeshCore is open-source software released under the MIT License. You are free to use, modify, and distribute it for personal and commercial projects.

## Contributing

Please submit PR's using 'dev' as the base branch!
For minor changes just submit your PR and we'll try to review it, but for anything more 'impactful' please open an Issue first and start a discussion. It is better to sound out what it is you want to achieve first, and try to come to a consensus on what the best approach is, especially when it impacts the structure or architecture of this codebase.

Here are some general principles you should try to adhere to:
* Keep it simple. Please, don't think like a high-level lang programmer. Think embedded, and keep code concise, without any unnecessary layers.
* No dynamic memory allocation, except during setup/begin functions.
* Follow the repository's `.clang-format` and the surrounding source style. Do not retroactively reformat unrelated code; that creates noisy diffs and makes functional changes harder to review.

Help us prioritize! Please react with thumbs-up to issues/PRs you care about most. We look at reaction counts when planning work.

### Running unit tests

To run unit tests, run the following command:

```bash
pio test --environment native --verbose
```

Run only one PlatformIO process in a checkout at a time. Do not overlap
`pio test`, `pio run`, uploads, cleans, or scripts that invoke PlatformIO, even
for different environments: they share and may clean `.pio/build`, which can
interrupt another build and produce misleading failures.

## Road-Map / To-Do

There are a number of fairly major features in the pipeline, with no particular time-frames attached yet. In very rough chronological order:
- [X] Companion radio: UI redesign
- [X] Repeater + Room Server: add ACL's (like Sensor Node has)
- [X] Standardise Bridge mode for repeaters
- [ ] Repeater/Bridge: Standardise the Transport Codes for zoning/filtering
- [X] Core + Repeater: enhanced zero-hop neighbour discovery
- [X] Core + Full Companion: round-trip trace and manual path support
- [X] Companion: opt-in off-grid client repeat mode
- [ ] Companion + Apps: support for multiple sub-meshes
- [ ] Core + Apps: support for LZW message compression
- [X] Core: adaptive CR (Coding Rate) for direct retries using recently heard SNR
- [ ] Core: new framework for hosting multiple virtual nodes on one physical device
- [ ] V2 protocol spec: discussion and consensus around V2 packet protocol, including path hashes, new encryption specs, etc

## Get Support

- Report bugs and request features on the [GitHub Issues](https://github.com/meshcore-dev/MeshCore/issues) page.
- Find additional guides and components on [my site](https://buymeacoffee.com/ripplebiz).
- Join [MeshCore Discord](https://meshcore.gg) to chat with the developers and get help from the community.
