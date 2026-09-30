"use strict";
const assert = require("node:assert/strict");
const builder = require("../docs/_javascript/notification_builder.js");

assert.deepEqual(builder.pulse("50,300,40,20,500"), [50,300,40,20,500]);
for (const [time, on] of [[0,true],[49,true],[50,false],[349,false],[350,true],[390,false],[410,true],[910,false]])
  assert.equal(builder.level(builder.pulse("50,300,40,20,500"), time), on);
for (const bad of ["0", "50,", "50,,20", "60001", "-5", "50 20", "1,1,1,1,1,1,1,1,1,1,1,1,1"])
  assert.throws(() => builder.pulse(bad));
assert.equal(builder.melody("vip:d=8,o=5,b=120:c,c#,16p,4g.6").length, 4);
for (const bad of ["abc", "x:d=8,o=3,b=120:c", "x:d=8,o=5,b=0:c", "x:d=3,o=5,b=120:c",
  "x:d=8,o=5,b=120:b#7", "x:d=8,o=5,b=120:c,", "x:d=8,o=5,b=120:c..", "x:d=8,o=5,b=120:p#",
  "x:d=8,o=04,b=120:c", "x:d=8,o=5,b=120:c04", "x:d=8,o=5,b=120:c007", "x:d=08,o=5,b=120:c", "x:d=8,o=5,b=120:04c"])
  assert.throws(() => builder.melody(bad));
for (const config of Object.values(builder.EXAMPLES)) {
  const complete = {...config, id: config.kind === "contact" ? "01".repeat(32) : config.id};
  const commands = builder.commands(complete);
  assert.ok(commands.every(cmd => cmd.length + 4 <= 175));
  const dm = builder.notificationText(complete);
  assert.ok(dm.startsWith("!notify "));assert.ok(!dm.includes("gpio="));assert.ok(dm.length <= 159);
}
const vip = {...builder.EXAMPLES.vip, id: "01".repeat(32), remote: "on"};
assert.ok(builder.commands(vip).includes("set notify.remote contact:" + vip.id + " on"));
const room = {...vip, kind: "room"};
assert.ok(builder.commands(room).includes("set notify.remote room:" + room.id + " on"));
const longPost = {...vip, led: Array(9).fill("60000").join(","), repeat: "65535"};
assert.equal(builder.notificationText(longPost).length, 151);
assert.throws(() => builder.notificationText({...longPost, kind: "room"}), /150 characters for a room post/);
assert.throws(() => builder.commands({...builder.EXAMPLES.food, remote: "on"}));
assert.throws(() => builder.commands({...vip, id: "1234"}));
// Local examples must play before choosing a recipient. Saved rules still need a key.
assert.equal(builder.parseOutputs(builder.EXAMPLES.vip).notes.length, 4);
assert.throws(() => builder.commands(builder.EXAMPLES.vip), /full 64-digit/);
assert.throws(() => builder.parseOutputs({...vip, gpio: "64:50,50"}), /GPIO needs/);
assert.throws(() => builder.parseOutputs({...vip, screen: "invalid"}), /Screen must/);
// Verify the actual PCM file sent to the browser: note pitch, rests, and one cycle.
const wav = builder.melodyWav("test:d=4,o=5,b=120:a,p,a6");
const waveView = new DataView(wav.buffer), rate = waveView.getUint32(24, true);
assert.equal(new TextDecoder().decode(wav.slice(0, 4)), "RIFF");
assert.equal(new TextDecoder().decode(wav.slice(8, 12)), "WAVE");
assert.equal(new TextDecoder().decode(wav.slice(36, 40)), "data");
assert.equal(waveView.getUint32(4, true), wav.length - 8);
assert.equal(waveView.getUint16(20, true), 1); // PCM
assert.equal(waveView.getUint16(22, true), 1); // Mono
assert.equal(waveView.getUint16(34, true), 16);
assert.equal(waveView.getUint32(40, true), rate * 1.5 * 2);
assert.equal(wav.length, 44 + rate * 1.5 * 2);
function samples(from, to) {
  return Array.from({length: Math.round((to - from) * rate)}, (_, i) => waveView.getInt16(44 + (Math.round(from * rate) + i) * 2, true));
}
function frequency(values) {
  const crossings = values.slice(1).filter((sample, i) => sample > 0 && values[i] <= 0).length;
  return crossings * rate / values.length;
}
const firstNote = samples(0.01, 0.49), lastNote = samples(1.01, 1.49);
assert.ok(Math.abs(frequency(firstNote) - 880) < 3);
assert.ok(Math.abs(frequency(lastNote) - 1760) < 3);
assert.ok(Math.sqrt(firstNote.reduce((sum, sample) => sum + sample * sample, 0) / firstNote.length) > 6000);
assert.ok(samples(0.5, 1).every(sample => sample === 0));
assert.equal(waveView.getInt16(44, true), 0);
assert.equal(waveView.getInt16(wav.length - 2, true), 0);
assert.equal(builder.melodyWav("off").length, 44);
assert.equal(builder.melodyWav("inherit").length, 44);
assert.throws(() => builder.melodyWav("invalid"));
// The browser warmup must preserve every sample, including the opening notes.
const warmedWav = builder.melodyWav("test:d=4,o=5,b=120:a,p,a6", 1000);
const leadBytes = rate * 2;
assert.equal(warmedWav.length, wav.length + leadBytes);
assert.ok(warmedWav.slice(44, 44 + leadBytes).every(byte => byte === 0));
assert.deepEqual(warmedWav.slice(44 + leadBytes), wav.slice(44));
assert.equal(new DataView(warmedWav.buffer).getUint32(40, true), warmedWav.length - 44);
assert.equal(builder.melodyWav("off", 1000).length, 44);
for (const lead of [-1, 2001, 0.5, NaN]) assert.throws(() => builder.melodyWav("off", lead));
console.log("Sound preview: audible PCM, note pitch, silence, duration, and recipient-free examples passed");
const encoded = builder.encodeCommand("notify.stop", "A7");
assert.equal(encoded[0], 60);assert.equal(encoded[3], 0x42);
assert.equal(new TextDecoder().decode(encoded.slice(4)), "A7|notify.stop");
const decoder = new builder.FrameDecoder();
const payload = Buffer.from("A7|OK - alerts stopped");
const framed = Uint8Array.from([62,payload.length+1,0,0x1d,...payload]);
assert.deepEqual(decoder.push(framed.slice(0, 2)), []);
assert.deepEqual(decoder.push(framed.slice(2, 8)), []);
const result = decoder.push(framed.slice(8));assert.equal(result.length, 1);
assert.equal(new TextDecoder().decode(result[0].slice(1)), "A7|OK - alerts stopped");
assert.deepEqual(new builder.FrameDecoder().push(Uint8Array.from([62,255,255,...framed])), [result[0]]);
assert.throws(() => builder.encodeCommand("x".repeat(173), "00"));
console.log("Notification builder: pulse, melody, examples, permissions, and fragmented USB frame tests passed");

async function transportTests() {
  let incoming, requestedSignals, opened;
  const seen = [];
  const port = {
    readable: new ReadableStream({start(controller) { incoming = controller; }}),
    writable: new WritableStream({write(bytes) {
      const text = new TextDecoder().decode(bytes.slice(4));
      const tag = text.slice(0, 2), command = text.slice(3);
      seen.push(command);
      const frame = value => {
        const body = new TextEncoder().encode(value);
        return Uint8Array.from([62, body.length + 1, 0, 0x1d, ...body]);
      };
      incoming.enqueue(frame("zz|ignored unrelated reply"));
      const reply = frame(tag + "|OK");
      incoming.enqueue(reply.slice(0, 2));incoming.enqueue(reply.slice(2, 7));incoming.enqueue(reply.slice(7));
    }}),
    async open(options) { opened = options; },
    async setSignals(signals) { requestedSignals = signals; },
    async close() {}
  };
  const client = new builder.SerialClient(port);
  await client.open();assert.equal(opened.baudRate, 115200);assert.equal(requestedSignals.dataTerminalReady, true);
  const first = client.command("notify.test room:" + "02".repeat(32));
  await assert.rejects(client.command("notify.stop"), /Wait for the current command/);
  assert.equal(await first, "OK");
  assert.equal(await client.command("notify.stop"), "OK");
  assert.equal(seen.length, 2);await client.close();
  // A failed write must reject promptly and clear the pending request.
  const failed = new builder.SerialClient({
    ...port, readable: new ReadableStream(),
    writable: new WritableStream({write() { throw new Error("Cable removed"); }})
  });
  await failed.open();await assert.rejects(failed.command("get notify"), /Cable removed/);
  assert.equal(failed.pending, null);await failed.close();
}
transportTests().then(() => console.log("USB transport: tagged round trips, busy rejection, disconnect failure and clean close passed"), error => { console.error(error);process.exitCode = 1; });
