// Execute unmodified functions extracted from the SHA-pinned official web app.
// Only Dart runtime, scheduler, widget state and transport boundaries are mocked.
// This is a protocol contract witness, not an iOS/BLE UI automation test.
"use strict";
const assert = require("assert/strict");
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const source = fs.readFileSync(input.bundle, "utf8");

function extract(needle, at = 0) {
  const begin = source.indexOf(needle, at);
  assert(begin >= 0, `Missing pinned app function: ${needle}`);
  const open = source.indexOf("{", begin);
  let depth = 0, quote = null, escaped = false;
  for (let end = open; end < source.length; ++end) {
    const ch = source[end];
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "{") ++depth;
    else if (ch === "}" && --depth === 0) return source.slice(begin, end + 1);
  }
  throw Error(`Unclosed app function: ${needle}`);
}

let now = 0, timers = [], radioConnection;
const errors = [];
const type = {a: value => value, b: value => value instanceof Uint8Array,
              h() { return this; }};
const t = new Proxy({}, {get: () => type});
const $ = {cT: () => new Uint8Array(0), cqf() {}, dF() {}, ay() {}, fQ() {},
           vI: () => ({Ia: () => 0x78563412})};
const B = {
  e: {aN: (a, b) => a >> b, qP: (a, b) => Math.trunc(a / b)},
  j: {c8: (a, start, end, b) => a.set(b.subarray(0, end - start), start),
      gcc: a => a.buffer, gS: a => a[0]},
  be: {gcc: a => a.buffer},
  d: {bc: (a, b) => a.includes(b), iV: (a, b, c) => a.split(b).join(c)}
};
const J = {
  a3: () => ({gt: a => a.length, gap: a => a.length === 0, i: (a, i) => a[i]}),
  i2: (a, b, c) => new Uint8Array(a, b, c),
  po: a => new Uint8Array(a), lx: (a, b, c) => new DataView(a, b, c),
  c6: (a, b) => a.push(b), aaW: (a, predicate) => {
    for (let i = a.length - 1; i >= 0; --i) if (predicate.$1(a[i])) a.splice(i, 1);
  },
  bf: a => { let i = -1; return {v: () => ++i < a.length, gM: () => a[i]}; },
  cTH: a => a.a, kz: (a, b) => a.split(b), aA: a => a.length,
  a1: (a, i) => a[i], p: (a, b) => a === b, cri: (a, n) => a.toFixed(n)
};
function deferred() {
  const result = {a: 0};
  result.promise = new Promise((resolve, reject) => {
    result.resolve = resolve; result.reject = reject;
  });
  result.then = result.promise.then.bind(result.promise);
  return result;
}
const A = {
  k: deferred, f: fn => fn,
  j: (fn, result) => { fn(0, null); return result.promise; },
  e: (value, fn) => Promise.resolve(value).then(v => fn(0, v), e => fn(1, e)),
  i: (value, result) => result.resolve(value), h: (error, result) => result.reject(error),
  V: function() { return deferred(); },
  am: function(value) {
    this.a = value;
    this.bK = (_, result) => { value.a = 30; value.resolve(result); };
    this.bD = error => { value.a = 30; value.reject(error); };
  },
  a: value => value, aX: value => value,
  ew: (start, end, length) => {
    const result = end === null ? length : end;
    assert(start >= 0 && result >= start && result <= length); return result;
  },
  en: (bytes, start, end) => ({cS: () => bytes.slice(start, end)}), cj: () => type,
  b3: () => ({$1() {}}), b6() {},
  bF: (_, __, ___, ms) => ({a: ms * 1000}), bT: function(a) { this.a = a; },
  fh: (duration, callback) => timers.push({due: now + duration.a / 1000, callback}),
  csH: callback => queueMicrotask(() => callback.$0()),
  wc: function() {}, an: () => radioConnection,
  kY: value => { const number = Number(value); assert(Number.isFinite(number)); return number; },
  cS: value => { const number = Number(value); assert(Number.isInteger(number)); return number; },
  c: () => ({glp: () => "invalid radio fields", glb: () => "radio error"}),
  av: (...args) => errors.push(args), L: error => error,
  aH: (_, error) => errors.push(error)
};
const context = vm.createContext({A, B, J, t, $, u: {AD: "tag mismatch", b1: "CLI mismatch"},
                                 Uint8Array, DataView, ArrayBuffer, Math, Date});
function constructor(name) {
  const code = extract(`${name}:function ${name}(`).replace(`${name}:`, `A.${name}=`);
  vm.runInContext(code, context);
}
for (const name of ["cZ", "d3", "fo", "ab7", "U1", "aba", "PS", "acs",
                    "aSq", "aSp", "aSr", "aSs", "aSf", "pK", "b0Z", "b0Y",
                    "b0X", "b1_", "b0W"]) constructor(name);
for (const name of ["cZ", "d3", "fo", "aba", "aSq", "aSp", "aSr", "aSs", "aSf",
                    "b0V", "b0Z", "b0Y", "b0X", "b1_", "b0W", "wc"]) {
  if (!A[name]) A[name] = function() {};
  vm.runInContext(extract(`A.${name}.prototype={`), context);
}
Object.assign(A, vm.runInContext(`({${extract("eD(a){")},${extract("d_f(a){")},${extract("bO(a,b){")}})`, context));

function connection() {
  const connection = new A.wc();
  const map = new Map();
  connection.a = {
    cu(_, key, factory) { if (!map.has(key)) map.set(key, factory.$0()); },
    i: (_, key) => map.get(key), Z: (_, key) => map.has(key),
    ey: (_, fn) => { for (const [key, value] of map) fn.$2(key, value); }
  };
  for (const name of ["eY", "N", "bCk", "bu", "dT", "W7"])
    connection[name] = A.b0V.prototype[name];
  connection.writes = [];
  connection.d6 = async bytes => { connection.writes.push(Buffer.from(bytes)); };
  return connection;
}
async function settle() { for (let i = 0; i < 20; ++i) await Promise.resolve(); }
async function advance(ms) {
  now += ms;
  for (const timer of timers.filter(timer => timer.due <= now)) timer.callback.$0();
  timers = timers.filter(timer => timer.due > now); await settle();
}
function sent(tag, estimate = 2000) {
  const bytes = Buffer.alloc(10); bytes[0] = 6;
  bytes.writeUInt32LE(tag, 2); bytes.writeUInt32LE(estimate, 6); return bytes;
}
function binary(tag, hex) {
  const prefix = Buffer.alloc(6); prefix[0] = 140; prefix.writeUInt32LE(tag, 2);
  return Buffer.concat([prefix, Buffer.from(hex, "hex")]);
}
const key = Uint8Array.from({length: 32}, (_, i) => i + 1);

async function main() {
  const builder = connection();
  const pending = builder.aQ1(key); pending.catch(() => {}); await settle();
  assert.equal(builder.writes.length, 1);
  assert.equal(builder.writes[0].length, 40);
  assert.equal(builder.writes[0][0], 50);
  assert.equal(builder.writes[0].subarray(1, 33).toString("hex"), Buffer.from(key).toString("hex"));
  assert.equal(builder.writes[0].subarray(33).toString("hex"), "05000012345678");
  if (input.mode === "build") {
    console.log(JSON.stringify({command: builder.writes[0].toString("hex"),
                               request: builder.writes[0].subarray(33).toString("hex")}));
    return;
  }
  let decoded = 0;
  for (const reply of input.acl) {
    const client = connection(); const promise = client.aQ1(key); await settle();
    assert.equal(client.writes[0].toString("hex"), builder.writes[0].toString("hex"));
    client.aL9(Buffer.from(reply.sent, "hex")); await settle();
    const timer = timers[timers.length - 1]; assert.equal(timer.due - now, 7000);
    // Valid matching ACL data remains accepted past the old 2400ms deadline.
    await advance(3000); client.aL9(Buffer.from(reply.frame, "hex")); await settle();
    const result = await promise;
    assert.equal(result.a.length, reply.entries);
    for (let index = 0; index < result.a.length; ++index) {
      const entry = result.a[index]; assert.equal(entry.b.a, 3);
      assert.equal(Buffer.from(entry.a).toString("hex"), reply.body.slice(index * 14, index * 14 + 12));
    }
    ++decoded;
  }
  // Retain the stock app's global SENT-listener race as an explicit witness.
  // This demonstrates a mechanism and does not identify an observed iOS cause.
  const raced = connection(); let failure;
  const request = raced.aQ1(key).catch(error => { failure = error; }); await settle();
  raced.aL9(sent(50)); await settle(); raced.aL9(sent(51)); await settle();
  raced.aL9(binary(51, input.acl.find(reply => reply.entries === 1).body)); await settle();
  await advance(7000); await request; assert.equal(failure, "timeout");

  // Feed actual firmware CLI output through the stock response stripping
  // callback, then through every stock radio screen's unmodified HH parser.
  let screens = 0;
  const radioNeedle = 'return A.e(A.an().d5(m.a.c,"get radio"),$async$HH)';
  let at = 0;
  while ((at = source.indexOf(radioNeedle, at)) >= 0) {
    const begin = source.lastIndexOf("\nHH(){", at) + 1;
    assert(begin > 0); const code = extract("HH(){", begin);
    const method = vm.runInContext(`({${code}}).HH`, context);
    for (const name of code.matchAll(/new A\.(\w+)\(m\)/g)) constructor(name[1]);
    for (const radio of input.radio) {
      const state = {y: false, a: {c: key}, c: {}, m() {}};
      const values = [];
      for (const field of ["CW", "ax", "ay"])
        state[field] = {sav: (_, value) => values.push(value)};
      const completion = deferred(); const completer = new A.am(completion);
      const listener = new A.aSf({a: null, b: null, c: null}, {N() {}}, key.slice(0, 6), "ab", completer);
      listener.$1({a: key.slice(0, 6), e: `ab|${radio}`});
      radioConnection = {d5: async () => completion.promise};
      errors.length = 0; await method.call(state);
      assert.deepEqual(values, ["909.500"]); assert.equal(errors.length, 0);
      const fields = code.match(/m\.(\w+)=i\nm\.(\w+)=h\nm\.(\w+)=g/);
      assert(fields); assert.equal(state[fields[1]], 62.5);
      assert.equal(state[fields[2]], 7); assert.equal(state[fields[3]], 5);
    }
    // The exact previously broken fifth field must reach the app's error path.
    const state = {y: false, a: {c: key}, c: {}, m() {}};
    radioConnection = {d5: async () => "909.5,62.5,7,5,48"};
    errors.length = 0; await method.call(state); assert.equal(errors.length, 1);
    ++screens; at += radioNeedle.length;
  }
  assert.equal(screens, 3);
  console.log(JSON.stringify({acl_cases: decoded, radio_screens: screens,
                             stock_sent_race_witness: true, actual_ios_cause_proven: false}));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
