# Companion notification builder

Make a rule, preview it here, then copy the CLI commands or apply and test it
over USB. The device needs firmware containing the new notification commands.
The programmable alert engine is enabled on ESP32, nRF52 and RP2040 builds.
Compact STM32WL Companions retain their existing alerts because the engine
does not fit their 224 KiB application partition.
Browser previews show one cycle; device tests use the configured repeat and
stop policy. USB testing uses Binary Companion mode at 115200 baud.

<div class="notification-builder" data-notification-builder>
  <div class="notification-examples">
    <button type="button" data-example="find">Find my node</button>
    <button type="button" data-example="food">Food order ready</button>
    <button type="button" data-example="vip">VIP chat</button>
    <button type="button" data-example="channel9">Only channel 9</button>
  </div>
  <form data-role="form" onsubmit="return false">
    <section class="notification-card">
      <h2>Who should trigger the alert?</h2>
      <div class="notification-grid">
        <label>Messages from<select name="kind"><option value="all">All contacts and channels</option><option value="contact">One contact</option><option value="room">One room server</option><option value="channel">One channel</option></select></label>
        <label>Contact/room key or channel slot<input name="id" autocomplete="off" placeholder="Full contact/room public key, or channel slot such as 3"></label>
        <label>Companion client status<select name="when"><option value="any">Connected or disconnected</option><option value="connected">Connected</option><option value="disconnected">Disconnected</option></select></label>
      </div>
      <label class="notification-checkbox"><input type="checkbox" name="quietOthers" value="on">Silence other message alerts (channel exception)</label>
      <p data-role="quiet-warning" hidden>This saves a silent default plus the selected channel's rule.
      It also silences ordinary DMs and room-message alerts. Existing specific/state rules
      and authorized <code>!notify</code> strings can still alert; review the
      <a href="#only-channel-9-alerts-all-other-channels-silent">channel 9 example and caveats</a>.
      Copy commands and USB Save include both rules; preview only plays the exception.</p>
      <p>Connected means an active phone/app, USB, WiFi, Ethernet or serial
      companion client. It selects a message rule; connecting or disconnecting
      alone does not create an alert. Contact matching uses the full public key.
      Channel slots resolve to the channel's key when the rule is saved.</p>
    </section>
    <section class="notification-card">
      <h2>What should the device do?</h2>
      <div class="notification-grid">
        <label>Vibration pattern<input name="vibration" value="50,300,40,20,500" spellcheck="false"><small>Millisecond on/off durations, or off / inherit</small></label>
        <label>LED pattern<input name="led" value="100,100,100,500" spellcheck="false"><small>Starts on, alternates off/on, finishes off</small></label>
        <label class="notification-wide">Sound melody<input name="sound" value="order:d=8,o=5,b=180:c,e,g,4c6" spellcheck="false"><small>RTTTL: note letters a-g, # for sharp, p for rest; off / inherit also work</small></label>
        <label>Screen<select name="screen"><option value="inherit">Use normal screen policy</option><option value="on">On during alert</option><option value="off">Off during alert</option></select></label>
        <label>GPIO output<input name="gpio" value="off" spellcheck="false"><small>off / inherit, or an approved pin and pattern: 22:50,300,50</small></label>
      </div>
      <p><code>50,300,40,20,500</code> means on for 50 ms, off for 300 ms,
      on for 40 ms, off for 20 ms, then on for 500 ms. A rule controls only
      outputs physically supported by its firmware. The USB connection reports
      the supported outputs and approved GPIO pins before applying anything.</p>
    </section>
    <section class="notification-card">
      <h2>Repeating and stopping</h2>
      <div class="notification-grid">
        <label>Repeat count<input name="repeat" value="1"><small>A number, or forever</small></label>
        <label>Gap between cycles (ms)<input name="gap" value="500" inputmode="numeric"></label>
        <label>Stop alert<select name="stop"><option value="button">Button</option><option value="connected">Node connected</option><option value="never">Never automatically dismiss</option></select></label>
      </div>
      <p>Node connected stops an active alert when a companion client connects.
      Never disables button/connection dismissal; a finite repeat count still
      finishes. <code>notify.stop</code> always stops playback. A new matching
      message replaces the current alert.</p>
    </section>
    <section class="notification-card">
      <h2>Allow notification strings from this contact or room</h2>
      <label>Permission<select name="remote"><option value="inherit">Leave permission unchanged</option><option value="on">Allow this contact or room</option><option value="off">Revoke this contact or room</option></select></label>
      <p>Only applies to a contact or room server's full public key, without a connection
      condition. An allowed contact can DM the notification string below, or
      it can be posted in an allowed room. Trusting a room allows its posters
      to send alerts through that server.
      GPIO, stop-policy and permission changes are forbidden in DMs or room posts. The device
      stops playback after at most 15 seconds, including infinite repeats.
      Incoming strings do not save settings and obey the recipient's master switches.</p>
    </section>
  </form>
  <p data-role="error" class="notification-error" role="alert" aria-live="polite"></p>
  <section class="notification-card">
    <h2>Preview one cycle</h2>
    <div class="notification-indicators"><span data-indicator="vibration" data-on="false">Vibration</span><span data-indicator="led" data-on="false">LED</span><span data-indicator="gpio" data-on="false">GPIO</span><span data-indicator="screen" data-on="false">Screen</span></div>
    <p data-role="preview-time" aria-live="off">Ready</p>
    <p data-role="preview-sound" aria-live="polite">Ready to play the melody</p>
    <audio data-role="preview-audio" preload="none"></audio>
    <button type="button" data-action="preview">Preview with sound</button>
    <button type="button" data-action="preview-stop">Stop preview</button>
    <p>The melody plays on this device after a one-second audio warmup, then
    the timer and output indicators start together. No contact or room key is needed to
    preview an example. Sound set to off or inherit plays no melody here.</p>
    <p>Timing here is a visual approximation. Firmware schedules outputs using
    millisecond timestamps without blocking radio work; loop and hardware
    latency can delay an edge. A haptic motor also takes time to start/stop.</p>
  </section>
  <section class="notification-card">
    <h2>Device commands</h2>
    <pre><code data-role="commands"></code></pre>
    <button type="button" data-action="copy">Copy commands</button><span data-role="copy-status" aria-live="polite"></span>
    <h3>Notification DM or room post</h3>
    <pre><code data-role="dm"></code></pre>
    <p>The recipient must first grant your contact or room permission. Send the string
    as an ordinary DM or room post; it contains no GPIO action. Long patterns may need
    shortening to fit 159 characters for a DM, or 150 for a room post.</p>
  </section>
  <section class="notification-card">
    <h2>Try it on your device</h2>
    <p data-role="device-status" aria-live="polite">No device connected</p>
    <div class="notification-buttons">
      <button type="button" data-action="connect">Connect USB</button>
      <button type="button" data-action="disconnect">Disconnect USB</button>
      <button type="button" data-action="apply">Save rule</button>
      <button type="button" data-action="apply-test">Save and test</button>
      <button type="button" data-action="test">Test saved rule</button>
      <button type="button" data-action="stop">Stop device alert</button>
      <button type="button" data-action="delete">Delete selected rule</button>
    </div>
    <p>Save writes the generated commands in order and stops at the first device
    error; earlier successful settings remain saved. A test with a connection
    suffix selects that profile even over USB. Stop-on-connect still watches
    real subsequent connections. The silence-other-alerts option saves both
    the silent default and the selected channel rule. Deleting the selected
    rule does not delete that default. USB testing requires Chrome or Edge.</p>
    <pre data-role="device-log" class="notification-log" aria-live="polite"></pre>
  </section>
</div>

## CLI reference

Settings apply immediately and survive reboot and filesystem-preserving
updates. They live in a separate checked file, `/notify_prefs`, with an atomic
replacement and backup. There are 12 rule slots. Existing alerts stay in use
until a rule or master control enables the new system. Unmatched messages keep
their existing alert behavior, subject to the master switches.

### Master controls

```text
get notify
set notify.enabled on
set notify.sound on
set notify.vibration on
set notify.led on
set notify.screen on
set notify.gpio off
get notify.gpio.pins
```

Each output has `get notify.<output>` and `set notify.<output> on|off`. Master
off cannot be overridden by a contact, channel or incoming notification DM.
`set notify.enabled off` disables custom rules and DM actions and returns to
the existing alert behavior. Supported-output bits in `get notify` are
vibration=1, sound=2, LED=4, screen=8 and GPIO=16. GPIO uses the same board pin
approval as repeater GPIO control and is inactive by default.

### Rules

Targets are `all`, `contact:<64 hexadecimal public-key digits>`,
`room:<64 hexadecimal room server public-key digits>`, and
`channel:<slot>`. A channel's 32-digit key also works. Add `@connected` or
`@disconnected` to select the client state; no suffix matches either state.

```text
set notify.vibration channel:3 50,300,40,20,500
set notify.sound channel:3 order:d=8,o=5,b=180:c,e,g,4c6
set notify.led channel:3 100,100,100,500
set notify.screen channel:3 on
set notify.gpio channel:3 22:50,300,50
set notify.repeat channel:3 forever
set notify.gap channel:3 2000
set notify.stop channel:3 button
get notify.vibration channel:3
notify.test channel:3
notify.stop
notify.delete channel:3
get notify.rules
get notify.rules 0
```

The GPIO example works only if pin 22 appears in `get notify.gpio.pins`.
Pulse lists have up to 12 positive durations of 1-60000 ms each. GPIO output is
active-high, inactive-low. Sound is one note at a time, not chords. RTTTL
requires `name:d=<1|2|4|8|16|32>,o=<4..7>,b=<25..900>:notes`; names use up to
12 ASCII letters/digits/underscores. Melodies are at most 63 characters and
60 seconds. Notes use `a` through `g`, `p` for rest, optional duration/octave,
`#` for sharps on a/c/d/f/g, and one `.` for a dotted duration. For example
`16c#6` and `4g.5` are valid. Invalid melodies are rejected before the buzzer
library sees them. This ASCII format matches the installed NonBlockingRTTTL
driver's pitch table; musical staff symbols and polyphony are not supported.

For any rule output, `off` explicitly disables it and `inherit` removes that
field's override. Rules combine per field: shared `all`, shared state rule,
contact/channel rule, then contact/channel state rule. A matching rule replaces
the old message sound/vibration; unspecified outputs are off unless inherited
from a shared rule. An unspecified screen keeps its normal display policy.
`screen on|off` temporarily overrides that policy and restores it when the
alert ends. A selected LED pattern temporarily takes ownership from the usual
status heartbeat; the master LED switch also controls that heartbeat.

Finite repeats are `1..65535`; `forever` loops until dismissed. Gap is
`1..60000` ms after the longest output sequence. Stop modes are `button`,
`connected`, and `never`. Triple-press sound/vibration mute controls also
update their notification master switch where those buttons are supported.
Continuous alerts prevent MCU sleep so their timers can run.

### Contact and room permission for notification strings

On the recipient, replace `PUBLIC_KEY` with the sender's complete public key:

```text
set notify.remote contact:PUBLIC_KEY on
get notify.remote contact:PUBLIC_KEY
set notify.remote contact:PUBLIC_KEY off
set notify.remote room:ROOM_PUBLIC_KEY on
```

Permission defaults to off, is saved per contact or room key, and cannot be granted
to `all`, channels or connection-state variants. The identity comes from the
authenticated received DM, not a key written inside its text. The permission
alone does not replace the contact's normal message alerts. A trusted room's
forwarded `!notify` posts use the room server's complete key for permission,
not the post author's four-byte prefix. Trusting a room allows its posters to
send notifications; trusting a chat contact alone does not authorize their
posts forwarded by an untrusted room. Both plain DMs and signed room posts
pass through the same validation and 15-second playback cap.

The allowed sender can send:

```text
!notify vibration=50,300,40,20,500 led=100,100,100,500 sound=order:d=8,o=5,b=180:c,e,g screen=on repeat=forever gap=2000
```

Allowed fields are `vibration`, `sound`, `led`, `screen`, `repeat` and `gap`.
The whole notification string is validated before any output changes.
Unknown/duplicate fields, GPIO, stop modes, permission changes and `inherit`
are rejected. The command cannot change saved rules. Button dismissal is
always allowed, `notify.stop` works, and playback stops at 15000 ms even when
the requested pattern or repeat count is longer. Unapproved or invalid
notification strings remain ordinary message text. Repeated delivery of the
same recently received post or DM does not restart its playback deadline.
Channel messages cannot execute
notification strings. Receiver master switches apply even while connected.

## Examples

- **Find my node:** use an allowed sender to DM a short sound/LED pattern, or
  use authorized remote CLI to run a saved `notify.test all@disconnected` rule.
  A local saved find rule can repeat until a companion client connects. A
  notification DM always ends within 15 seconds.
- **Food truck pager:** use a private order channel rule that repeats until
  the customer presses the button, or let the customer grant the order desk's
  contact permission and send the notification DM when the order is ready.
- **VIP chat:** match the VIP's full public key and set a distinctive melody
  and vibration. Add a connected profile with sound/vibration off if the phone
  should handle notifications while attached. Permission to send notification
  strings is separate from a VIP's ordinary message rule.

### Only channel 9 alerts; all other channels silent

This example makes message alerts silent by default, then plays one short
melody for channel 9. It works both with and without a connected companion
client and requires a device with a buzzer. Messages still arrive normally;
this changes the node's alerts, not the phone app's notification settings.
Use the **Only channel 9** button above to load this setup into the builder.
You can change the channel slot or alert pattern before copying or saving.
Uncheck **Silence other message alerts** to generate only the selected rule;
this does not remove a silent default already saved on the node.

`channel:9` means the firmware's **zero-based slot 9** (the tenth slot), not
a channel named `ch9`. Configure that slot before running these commands.
The rule follows its saved channel key; recreate it if you replace the channel
in that slot.

Start with no conflicting custom rules. Use `get notify.rules`, then
`get notify.rules <rule-slot>` to inspect existing selectors. Remove only
unwanted rules with `notify.delete <selector>`: existing state-specific and
contact/channel rules can override the silent default below.

```text
set notify.enabled on
set notify.vibration all off
set notify.sound all off
set notify.led all off
set notify.screen all off
set notify.gpio all off
set notify.repeat all 1
set notify.gap all 500
set notify.stop all button
set notify.sound on
set notify.sound channel:9 ch9:d=8,o=5,b=180:c,e,g
```

Keep the sound **master** on: `set notify.sound all off` silences the default
rule, while `set notify.sound off` would also block the channel 9 exception.
The other outputs remain silent, including screen wake-ups for messages.
To add vibration for channel 9 on a device with a vibration motor:

```text
set notify.vibration on
set notify.vibration channel:9 100,100,300
```

Test the saved exception with `notify.test channel:9`; stop it with
`notify.stop`. Send a message on another configured channel to verify that
it stays quiet.

**Scope:** there is no channels-only wildcard: `all` also silences ordinary
DM and room-message alerts unless a more specific rule enables them.
Previously authorized contact/room `!notify` strings can still request alerts.
If those should stay quiet too, revoke their permission with
`set notify.remote contact:PUBLIC_KEY off` or
`set notify.remote room:ROOM_PUBLIC_KEY off`, using the full sender/server key.
