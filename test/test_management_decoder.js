"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
if (!globalThis.crypto) globalThis.crypto = require("crypto").webcrypto;
const decoder = require("../docs/_javascript/management_decoder.js");

function hex(text) {
  return Uint8Array.from(Buffer.from(text, "hex"));
}

async function authenticatedAclPages(headerLength, perPage, entries) {
  const root = await decoder.passwordKey(decoder.EXAMPLE_PASSWORD);
  const pages = [];
  for (let page = 0; page < Math.ceil(entries.length / perPage); ++page) {
    const header = Buffer.alloc(headerLength);
    Buffer.from(decoder.EXAMPLE_PAGE, "hex").copy(header, 0, 0, 83);
    header[3] = headerLength === 111 ? 0x32 : 0x31;
    const first = page * perPage;
    const count = Math.min(perPage, entries.length - first);
    header[78] = page; header[79] = Math.ceil(entries.length / perPage);
    header[80] = entries.length; header[81] = first; header[82] = count;
    const plaintext = Buffer.concat(entries.slice(first, first + count));
    const key = await decoder.deriveKey(root, "MeshCore-MGR1-SIV", header.subarray(4, 20));
    const tag = await decoder.s2v(key.subarray(0, 16), new Uint8Array(header),
      new Uint8Array(plaintext));
    const counter = new Uint8Array(tag); counter[8] &= 0x7f; counter[12] &= 0x7f;
    const ctrKey = await globalThis.crypto.subtle.importKey("raw", key.subarray(16),
      { name: "AES-CTR" }, false, ["encrypt"]);
    const ciphertext = await globalThis.crypto.subtle.encrypt(
      { name: "AES-CTR", counter, length: 128 }, ctrKey, plaintext);
    pages.push(Buffer.concat([header, Buffer.from(ciphertext), Buffer.from(tag)]).toString("hex"));
  }
  return pages;
}

// Execute the actual browser entry point against a minimal DOM boundary. All
// cryptography remains Node's real Web Crypto; only one digest can be held to
// deterministically exercise an in-flight decode when the user clears/retries.
function browserFixture() {
  function element() {
    const handlers = new Map();
    const classes = new Set();
    return {
      value: "", hidden: true, disabled: false, textContent: "", children: [],
      classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); } },
      addEventListener(name, callback) { handlers.set(name, callback); },
      emit(name, event = {}) { return handlers.get(name)(event); },
      append(...children) { this.children.push(...children); },
      appendChild(child) { this.children.push(child); },
      replaceChildren(...children) { this.children = children; },
      focus() {},
    };
  }
  const fields = new Map();
  const root = element();
  root.querySelector = (selector) => {
    if (!fields.has(selector)) fields.set(selector, element());
    return fields.get(selector);
  };
  let nextDigest = null;
  const real = globalThis.crypto.subtle;
  const subtle = {};
  for (const name of ["importKey", "encrypt", "decrypt", "sign"]) {
    subtle[name] = (...args) => real[name](...args);
  }
  subtle.digest = async (...args) => {
    const pending = real.digest(...args);
    const gate = nextDigest;
    nextDigest = null;
    if (gate) { gate.started(); await gate.wait; }
    return pending;
  };
  const context = {
    crypto: { subtle }, TextEncoder, Uint8Array, console,
    document: {
      readyState: "complete", querySelector: () => root, createElement: element,
    },
  };
  vm.runInNewContext(fs.readFileSync(require.resolve(
    "../docs/_javascript/management_decoder.js"), "utf8"), context);
  return {
    field(name) { return root.querySelector(`[data-role='${name}']`); },
    holdNextDigest() {
      let started, release;
      const began = new Promise((resolve) => { started = resolve; });
      const wait = new Promise((resolve) => { release = resolve; });
      nextDigest = { started, wait };
      return { began, release };
    },
  };
}

(async function run() {
  // RFC 5297 Appendix A.1: independent known-answer coverage for the exact
  // AES-SIV-CMAC-256 algorithm used to protect an MGR1 ACL page.
  const key = hex("fffefdfcfbfaf9f8f7f6f5f4f3f2f1f0f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff");
  const aad = hex("101112131415161718191a1b1c1d1e1f2021222324252627");
  const ciphertext = hex("40c02b9690c4dc04daef7f6afe5c");
  const tag = hex("85632d07c6e8f37f950acd320a2ecc93");
  assert.strictEqual(
    Buffer.from(await decoder.openSiv(key, aad, ciphertext, tag)).toString("hex"),
    "112233445566778899aabbccddee"
  );

  // Node Buffers implement slice() as a shared view. The exported helpers must
  // leave caller buffers intact and accept the same independent RFC vector.
  const bufferTag = Buffer.from(tag);
  assert.strictEqual(
    Buffer.from(await decoder.openSiv(Buffer.from(key), Buffer.from(aad),
      Buffer.from(ciphertext), bufferTag)).toString("hex"),
    "112233445566778899aabbccddee"
  );
  assert.deepStrictEqual(bufferTag, Buffer.from(tag));
  for (const length of [16, 17, 32]) {
    const plaintext = Buffer.alloc(length, 7);
    const original = Buffer.from(plaintext);
    const expected = await decoder.s2v(key.subarray(0, 16), aad,
      new Uint8Array(plaintext));
    assert.deepStrictEqual(Buffer.from(await decoder.s2v(Buffer.from(key.subarray(0, 16)),
      Buffer.from(aad), plaintext)), Buffer.from(expected));
    assert.deepStrictEqual(plaintext, original);
  }

  const publicOnly = await decoder.decodeManagement(decoder.EXAMPLE_PAGE, "");
  assert.strictEqual(publicOnly.authenticated, false);
  assert.strictEqual(publicOnly.public.radioId, "000102030405060708090A0B0C0D0E0F");
  assert.strictEqual(publicOnly.public.firmware, "1.17.1.5");
  assert.strictEqual(publicOnly.acl.length, 0);
  assert.strictEqual(publicOnly.public.protocol, "MGR1");
  assert.strictEqual(publicOnly.public.usbLogging, null);
  assert.strictEqual(publicOnly.public.usbWatchdogLast, null);

  // MGR2 is the full event-capable layout. The unreleased 98-byte prototype
  // and MGR3 magic have no compatibility fallback. Actual MGR1/MGR2 SIV
  // ciphertext is checked cross-language using the production encoder.
  const legacy = Buffer.from(decoder.EXAMPLE_PAGE, "hex");
  const currentHeader = Buffer.from(legacy.subarray(0, 83)); currentHeader[3] = 0x32;
  const usb = Buffer.alloc(15);
  usb.writeUInt16LE(0x07ff, 0); usb[2] = 2 | (8 << 2);
  usb.writeUInt32LE(604800, 3); usb.writeUInt32LE(0xffffffff, 7);
  usb.writeUInt32LE(1209600, 11);
  const current = Buffer.concat([currentHeader, usb, Buffer.alloc(13), legacy.subarray(83)]);
  const currentPublic = await decoder.decodeManagement(current.toString("hex"), "");
  assert.strictEqual(currentPublic.public.protocol, "MGR2");
  assert.strictEqual(currentPublic.public.usbWatchdogLast, null);
  assert.strictEqual(currentPublic.public.usbLogging.supported, true);
  assert.strictEqual(currentPublic.public.usbLogging.persistenceReady, true);
  assert.strictEqual(currentPublic.public.usbLogging.loggerActive, true);
  assert.strictEqual(currentPublic.public.usbLogging.stage, 2);
  assert.strictEqual(currentPublic.public.usbLogging.backoffStep, 8);
  assert.strictEqual(currentPublic.public.usbLogging.retrySeconds, 604800);
  assert.strictEqual(currentPublic.public.usbLogging.inactiveSeconds, 0xffffffff);
  assert.strictEqual(currentPublic.public.usbLogging.watchdogAuto, true);
  assert.strictEqual(currentPublic.public.usbLogging.autoConnectedSeconds, 1209600);
  const unsupported = Buffer.from(current); unsupported.writeUInt16LE(0, 83);
  assert.strictEqual((await decoder.decodeManagement(unsupported.toString("hex"), "")).public.usbLogging.supported, false);
  const openReaderOnly = Buffer.from(current); openReaderOnly[84] &= ~4;
  const readerWithoutLogger = (await decoder.decodeManagement(openReaderOnly.toString("hex"), "")).public.usbLogging;
  assert.strictEqual(readerWithoutLogger.hostConnected, true);
  assert.strictEqual(readerWithoutLogger.readerConnected, true);
  assert.strictEqual(readerWithoutLogger.loggerActive, false);
  const badCount = Buffer.from(current); badCount[82] = 5;
  await assert.rejects(decoder.decodeManagement(badCount.toString("hex"), ""), /bounds/);
  await assert.rejects(decoder.decodeManagement(current.subarray(0, 99).toString("hex"), ""), /complete/);
  for (const [offset, value] of [[84, 8], [85, 0xc0]]) {
    const reserved = Buffer.from(current); reserved[offset] = value;
    await assert.rejects(decoder.decodeManagement(reserved.toString("hex"), ""), /Reserved/);
  }

  const prototype = Buffer.concat([currentHeader, usb, legacy.subarray(83)]);
  await assert.rejects(decoder.decodeManagement(prototype.toString("hex"), ""), /length|Invalid/);
  const emptyPrototype = Buffer.alloc(98 + 16);
  currentHeader.copy(emptyPrototype); emptyPrototype[80] = 0; emptyPrototype[82] = 0;
  await assert.rejects(decoder.decodeManagement(emptyPrototype.toString("hex"), ""), /complete/);
  const mgr3 = Buffer.from(current); mgr3[3] = 0x33;
  await assert.rejects(decoder.decodeManagement(mgr3.toString("hex"), ""), /No complete/);
  await assert.rejects(decoder.decodeManagement("1A00" + mgr3.toString("hex"), ""), /No complete/);

  // Watchdog fields remain at offsets 98..110 in current MGR2.
  const event = Buffer.alloc(13); event[0] = 0xbf;
  event.writeUInt32LE(1700000001, 1); event.writeUInt32LE(777, 5); event.writeUInt32LE(42, 9);
  const withEvent = Buffer.from(current); event.copy(withEvent, 98);
  const eventPublic = await decoder.decodeManagement(withEvent.toString("hex"), "");
  assert.strictEqual(eventPublic.public.protocol, "MGR2");
  assert.strictEqual(eventPublic.public.usbLogging.loggerActive, true);
  assert.deepStrictEqual(eventPublic.public.usbWatchdogLast, {
    reasons: 15, reasonNames: ["host-absent", "reader-absent", "tx-stalled", "client-inactive"],
    actionCode: 3, action: "reboot-requested", persisted: true,
    epoch: 1700000001, uptimeSeconds: 777, sequence: 42,
  });
  const none = Buffer.from(withEvent); none.fill(0, 98, 111);
  assert.strictEqual((await decoder.decodeManagement(none.toString("hex"), "")).public.usbWatchdogLast, null);
  for (let action = 1; action <= 4; ++action) {
    const ramOnly = Buffer.from(withEvent); ramOnly[98] = 15 | (action << 4); ramOnly.writeUInt32LE(0, 99);
    const decodedEvent = (await decoder.decodeManagement(ramOnly.toString("hex"), "")).public.usbWatchdogLast;
    assert.strictEqual(decodedEvent.actionCode, action);
    assert.strictEqual(decodedEvent.persisted, false);
    assert.strictEqual(decodedEvent.epoch, 0);
  }
  for (const code of [0x80, 0x8f, 0x90, 0xa0, 0xb0, 0xc0, 0xdf, 0xef, 0xff]) {
    const invalid = Buffer.from(withEvent); invalid[98] = code;
    await assert.rejects(decoder.decodeManagement(invalid.toString("hex"), ""), /Invalid/);
  }
  const invalidSequence = Buffer.from(withEvent); invalidSequence.writeUInt32LE(0, 107);
  await assert.rejects(decoder.decodeManagement(invalidSequence.toString("hex"), ""), /Invalid/);
  const fiveEntries = Buffer.from(withEvent); fiveEntries[82] = 5;
  await assert.rejects(decoder.decodeManagement(fiveEntries.toString("hex"), ""), /bounds/);
  for (const size of [99, 110, 126]) {
    await assert.rejects(decoder.decodeManagement(withEvent.subarray(0, size).toString("hex"), ""), /complete/);
  }
  // Thirty-six ACL keys use exactly nine current pages, four entries per
  // page. The unchanged MGR1 layout remains six entries across six pages.
  for (const [source, header, perPage, pageCount] of [
    [withEvent, 111, 4, 9], [legacy, 83, 6, 6],
  ]) {
    const pages = [];
    for (let page = 0; page < pageCount; ++page) {
      const packed = Buffer.alloc(header + perPage * 13 + 16);
      source.copy(packed, 0, 0, header);
      packed[78] = page; packed[79] = pageCount; packed[80] = 36;
      packed[81] = page * perPage; packed[82] = perPage;
      pages.push(packed.toString("hex"));
    }
    const report = await decoder.decodeManagement(pages.join("\n"), "");
    assert.strictEqual(report.complete, true);
    assert.strictEqual(report.pageCount, pageCount);
    assert.strictEqual(report.suppliedPages, pageCount);
    assert.strictEqual(report.public.protocol, header === 111 ? "MGR2" : "MGR1");
    const excessive = Buffer.from(pages[0], "hex"); excessive[79] = pageCount + 1;
    await assert.rejects(decoder.decodeManagement(excessive.toString("hex"), ""), /bounds/);
  }

  // Multi-page assembly cannot mix event/USB snapshots or conflicting copies,
  // even when radio identity and sequence happen to match.
  const twoPages = [];
  for (let page = 0; page < 2; ++page) {
    const count = page === 0 ? 4 : 1;
    const packed = Buffer.alloc(111 + count * 13 + 16);
    withEvent.copy(packed, 0, 0, 111);
    packed[78] = page; packed[79] = 2; packed[80] = 5;
    packed[81] = page * 4; packed[82] = count;
    twoPages.push(packed);
  }
  const joinPages = (...pages) => pages.map((page) => page.toString("hex")).join("\n");
  const ordered = await decoder.decodeManagement(joinPages(twoPages[1], twoPages[0]), "");
  assert.strictEqual(ordered.complete, true);
  assert.strictEqual(ordered.public.page, "1 of 2");
  const partial = await decoder.decodeManagement(twoPages[1].toString("hex"), "");
  assert.strictEqual(partial.complete, false);
  assert.strictEqual(partial.suppliedPages, 1);
  assert.strictEqual((await decoder.decodeManagement(joinPages(
    twoPages[0], twoPages[0]), "")).suppliedPages, 1);
  for (const offset of [24, 83, 99, 103, 107]) {
    const mixed = Buffer.from(twoPages[1]); mixed[offset] ^= 1;
    await assert.rejects(decoder.decodeManagement(joinPages(twoPages[0], mixed), ""), /same snapshot/);
  }
  const conflicting = Buffer.from(twoPages[0]); conflicting[111] ^= 1;
  await assert.rejects(decoder.decodeManagement(joinPages(twoPages[0], conflicting), ""), /Conflicting copies/);
  for (const offset of [4, 20]) {
    const otherReport = Buffer.from(twoPages[1]); otherReport[offset] ^= 1;
    await assert.rejects(decoder.decodeManagement(joinPages(twoPages[0], otherReport), ""), /more than one report/);
  }

  // The production allowlist merges permissions for each keyed fingerprint.
  // Authenticated duplicates, within a page or across pages, are not a unique
  // ACL and must fail instead of appearing as two different administrators.
  for (const [header, perPage] of [[83, 6], [111, 4]]) {
    const admin = Buffer.alloc(13); admin[12] = 1;
    const signer = Buffer.from(admin); signer[12] = 2;
    const withinPage = await authenticatedAclPages(header, perPage, [admin, signer]);
    const publicOnly = await decoder.decodeManagement(withinPage.join("\n"), "");
    assert.strictEqual(publicOnly.authenticated, false);
    assert.strictEqual(publicOnly.acl.length, 0);
    await assert.rejects(decoder.decodeManagement(withinPage.join("\n"),
      decoder.EXAMPLE_PASSWORD), /duplicate fingerprint/);

    const entries = Array.from({ length: perPage + 1 }, (_value, index) => {
      const entry = Buffer.from(admin); entry[0] = index; return entry;
    });
    entries[perPage] = signer;
    const acrossPages = await authenticatedAclPages(header, perPage, entries);
    await assert.rejects(decoder.decodeManagement(acrossPages.join("\n"),
      decoder.EXAMPLE_PASSWORD), /duplicate fingerprint/);
    assert.strictEqual((await decoder.decodeManagement(acrossPages[1],
      decoder.EXAMPLE_PASSWORD)).authenticated, true);

    const combined = Buffer.from(admin); combined[12] = 3;
    const valid = await authenticatedAclPages(header, perPage, [combined]);
    const report = await decoder.decodeManagement(valid[0] + "\n" + valid[0],
      decoder.EXAMPLE_PASSWORD);
    assert.strictEqual(report.complete, true);
    assert.strictEqual(report.acl.length, 1);
    assert(report.acl[0].administrator && report.acl[0].otaSigner);
  }

  const decoded = await decoder.decodeManagement(
    decoder.EXAMPLE_PAGE,
    decoder.EXAMPLE_PASSWORD
  );
  assert.strictEqual(decoded.authenticated, true);
  assert.strictEqual(decoded.public.bootloader, "0.2.4.6");
  assert.strictEqual(decoded.public.target, "1234ABCD");
  assert.strictEqual(decoded.acl.length, 1);
  assert.strictEqual(decoded.acl[0].fingerprint, "AABBCCDDEEFF001122334455");
  assert.strictEqual(decoded.acl[0].administrator, true);
  assert.strictEqual(decoded.acl[0].otaSigner, true);
  const wrapped = decoder.EXAMPLE_PAGE.match(/.{1,64}/g).join("\n");
  assert.strictEqual((await decoder.decodeManagement(wrapped, decoder.EXAMPLE_PASSWORD)).authenticated, true);
  const duplicateLines = decoder.EXAMPLE_PAGE + "\n" + decoder.EXAMPLE_PAGE;
  assert.strictEqual((await decoder.decodeManagement(duplicateLines, decoder.EXAMPLE_PASSWORD)).acl.length, 1);

  const groupData = "1A00" + decoder.EXAMPLE_PAGE + "000000";
  const packet = await decoder.decodeManagement(groupData, decoder.EXAMPLE_PASSWORD);
  assert.strictEqual(packet.public.envelope.route, "direct");
  assert.strictEqual(packet.public.envelope.pathHops, 0);
  const paddedRouted = "1A0177" + decoder.EXAMPLE_PAGE + "000000";
  const routed = await decoder.decodeManagement(paddedRouted, decoder.EXAMPLE_PASSWORD);
  assert.strictEqual(routed.public.envelope.pathHops, 1);
  assert.strictEqual(routed.acl[0].administrator, true);

  // Firmware pads management GroupData on every route, not only flood. Bare
  // canonical pages are still valid pasted input, but not a wire envelope.
  for (const [source, header, perPage] of [[legacy, 83, 6], [current, 111, 4]]) {
    for (let count = 0; count <= perPage; ++count) {
      const canonical = Buffer.alloc(header + count * 13 + 16);
      source.copy(canonical, 0, 0, header);
      canonical[78] = 0; canonical[79] = 1; canonical[80] = count;
      canonical[81] = 0; canonical[82] = count;
      assert.strictEqual((await decoder.decodeManagement(canonical.toString("hex"), "")).pageCount, 1);
      const padded = Buffer.alloc(3 + Math.ceil((canonical.length - 3) / 16) * 16);
      canonical.copy(padded);
      for (let route = 0; route < 4; ++route) {
        const envelope = Buffer.from(route === 0 || route === 3
          ? [0x18 | route, 1, 2, 3, 4, 0] : [0x18 | route, 0]);
        const wire = Buffer.concat([envelope, padded]);
        const result = await decoder.decodeManagement(wire.toString("hex"), "");
        assert.strictEqual(result.public.envelope.routeCode, route);
        if (canonical.length !== padded.length) {
          await assert.rejects(decoder.decodeManagement(Buffer.concat(
            [envelope, canonical]).toString("hex"), ""), /No complete|padding/);
          const badPadding = Buffer.from(wire); badPadding[badPadding.length - 1] = 1;
          await assert.rejects(decoder.decodeManagement(badPadding.toString("hex"), ""), /No complete|padding/);
        }
        await assert.rejects(decoder.decodeManagement(Buffer.concat(
          [wire, Buffer.alloc(16)]).toString("hex"), ""), /No complete|padding/);
      }
    }
  }

  // An empty ACL is a valid, authenticated page. AES-CTR has no padding, so
  // it must also work when the SIV ciphertext has zero bytes.
  const emptyAclPage =
    "4D475231000102030405060708090A0B0C0D0E0F2A00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000A815011F051F4F000001000000DAA550D7FEFAEB13412CF9E457A45F2A";
  const emptyAcl = await decoder.decodeManagement(emptyAclPage, decoder.EXAMPLE_PASSWORD);
  assert.strictEqual(emptyAcl.authenticated, true);
  assert.strictEqual(emptyAcl.acl.length, 0);

  await assert.rejects(
    decoder.decodeManagement(decoder.EXAMPLE_PAGE, "not the right management password"),
    /Password is wrong/
  );
  const altered = decoder.EXAMPLE_PAGE.slice(0, -2) + "00";
  await assert.rejects(
    decoder.decodeManagement(altered, decoder.EXAMPLE_PASSWORD),
    /Password is wrong/
  );
  await assert.rejects(
    decoder.decodeManagement(decoder.EXAMPLE_PAGE, "short"),
    /12 through 96/
  );

  const browser = browserFixture();
  browser.field("input").value = decoder.EXAMPLE_PAGE;
  browser.field("password").value = decoder.EXAMPLE_PASSWORD;
  const clearGate = browser.holdNextDigest();
  const oldDecode = browser.field("decode").emit("click");
  await clearGate.began;
  browser.field("clear").emit("click");
  clearGate.release(); await oldDecode;
  assert.strictEqual(browser.field("results").hidden, true,
    "a decode completed after Clear must not reveal the old report");
  assert.strictEqual(browser.field("error").hidden, true);
  assert.strictEqual(browser.field("input").value, "");
  assert.strictEqual(browser.field("password").value, "");
  assert.strictEqual(browser.field("decode").disabled, false);
  assert.strictEqual(browser.field("summary").children.length, 0);
  assert.strictEqual(browser.field("acl-table").children.length, 0);

  // Clear removes already-rendered secret rows, not only their visibility.
  browser.field("input").value = decoder.EXAMPLE_PAGE;
  browser.field("password").value = decoder.EXAMPLE_PASSWORD;
  await browser.field("decode").emit("click");
  assert.strictEqual(browser.field("results").hidden, false);
  assert(browser.field("acl-table").children.length > 0);
  browser.field("clear").emit("click");
  assert.strictEqual(browser.field("acl-table").children.length, 0);
  assert.strictEqual(browser.field("summary").children.length, 0);
  assert.strictEqual(browser.field("status").textContent, "");

  for (const oldPassword of [decoder.EXAMPLE_PASSWORD, "not the right management password"]) {
    browser.field("input").value = decoder.EXAMPLE_PAGE;
    browser.field("password").value = oldPassword;
    const gate = browser.holdNextDigest();
    const superseded = browser.field("decode").emit("click");
    await gate.began;
    browser.field("password").value = "";
    let prevented = false;
    browser.field("input").emit("keydown", {
      key: "Enter", ctrlKey: true,
      preventDefault() { prevented = true; },
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.strictEqual(prevented, true);
    assert.strictEqual(browser.field("results").hidden, false);
    assert(browser.field("status").textContent.startsWith("Public-only"));
    gate.release(); await superseded;
    assert(browser.field("status").textContent.startsWith("Public-only"),
      "an older success must not overwrite the newer decode");
    assert.strictEqual(browser.field("results").hidden, false);
    assert.strictEqual(browser.field("error").hidden, true,
      "an older error must not hide the newer decode");
    assert.strictEqual(browser.field("decode").disabled, false);
  }
  browser.field("password").value = decoder.EXAMPLE_PASSWORD;
  const olderGate = browser.holdNextDigest();
  const older = browser.field("decode").emit("click");
  await olderGate.began;
  const newerGate = browser.holdNextDigest();
  const newer = browser.field("decode").emit("click");
  await newerGate.began;
  olderGate.release(); await older;
  assert.strictEqual(browser.field("decode").disabled, true,
    "an older completion must not unlock the current in-flight decode");
  assert.strictEqual(browser.field("results").hidden, true);
  newerGate.release(); await newer;
  assert.strictEqual(browser.field("decode").disabled, false);
  assert.strictEqual(browser.field("results").hidden, false);
  assert(browser.field("status").textContent.startsWith("Password-authenticated"));

  console.log("management browser decoder checks passed");
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
