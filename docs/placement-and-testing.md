# Placement, mounting and testing

Where and how you mount the repeater matters more than any setting. The sensor measures how hard **its own enclosure** is being shaken, so anything that moves the enclosure looks like shaking to it. A repeater in the wrong spot will send false alerts, or none that mean anything. Read this before you mount one, and before you point it at a channel other people rely on.

## Mount it solidly

Choose a position that is rigid and stays put:

- **Fix it to something solid.** A masonry or concrete wall, a structural post, or a rigid steel or timber frame fixed to the building works well. The enclosure should not be able to rock, rattle or shift, so use proper fixings and tighten them.
- **Keep it out of the wind's reach.** Wind that moves the enclosure, the pole it is on or the cable it hangs from is the most common cause of false readings. A repeater on the end of a tall or thin mast that sways, or on a pole with a large antenna acting as a sail, will move with every gust.
- **Secure everything attached to it.** Antenna cables, solar panel cables and the antenna itself must not swing or flap against the enclosure. Support cables so they cannot whip, and fix the antenna firmly.
- **Mount it level and leave it alone.** The sensor also notices if it is tilted (RAK's description of the RAK12027 says the sensor reports a change of more than 20 degrees from its horizontal position, meant as a sign that the structure it is mounted on has collapsed). The sensor calibrates itself when it is powered up, so mount it first, then power it up, and avoid knocking it afterwards.

## Where not to mount it

Do not mount a repeater anywhere that movement is normal:

- vehicles, trailers, boats and RVs
- trees, tall flexible masts and anything that visibly sways
- fences, gates, doors, hatches and loose roof panels
- lightweight or thin structures that flex in the wind
- directly on or beside machinery, air handlers or generators
- places that people, animals or equipment will bump, or where heavy traffic, trains or construction shake the structure

It does not matter that the movement is small. A sensor that reports "strong shaking" at a threshold designed for damaging earthquakes can still be triggered by the knocks and sway of an unsuitable site, and one false alert is enough to make people stop trusting a channel. If you are unsure whether a spot is steady enough, it is probably not.

## Test on a test channel first

Do not point a new repeater at a production channel straight away. Run it on a **test channel** for **one to two weeks**, then move it:

1. Set a test channel, for example `#seismic-test`:

   ```
   set earthquake.channel #seismic-test
   ```

2. Check the delivery path with `earthquake test` (it posts a message starting with `TEST:`), and check `earthquake status` to see whether the repeater is ready.
3. Leave it running in its final position for the whole period, through the windiest weather you can. Watch the test channel, and use `earthquake status` to see whether the sensor has seen any events.
4. If **any** alert arrives that was not an earthquake, treat it as a mounting problem, not a one-off. Find what moved (wind, a loose fixing, a swinging cable, a vibrating structure), fix it, and start the period again.
5. When it has run quietly for the full period, switch to the production channel, for example `#seismic`:

   ```
   set earthquake.channel #seismic
   ```

The test channel keeps false alerts away from the people who rely on the real one, and gives you a record of how your site behaves.

::: tip A quiet test does not prove it works
The sensor only alerts on strong shaking, so a quiet fortnight is the expected result, and says your repeater was not disturbed, not that it would catch an earthquake. `earthquake test` proves the message reaches the channel, and the telemetry's sensor health reading shows the sensor is answering. Neither is a calibrated measurement of ground motion. See [What the sensor readings mean](reading-the-sensor.md).
:::

## Related

- [Get started](getting-started.md)
- [Earthquake channel alerts](earthquake-alerts.md)
- [What the sensor readings mean](reading-the-sensor.md), including what can set the sensor off
