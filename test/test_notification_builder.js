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
  "x:d=8,o=5,b=120:b#7", "x:d=8,o=5,b=120:c,", "x:d=8,o=5,b=120:c..", "x:d=8,o=5,b=120:p#"])
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
