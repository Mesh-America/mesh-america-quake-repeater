"use strict";

const assert = require("assert");
if (!globalThis.crypto) globalThis.crypto = require("crypto").webcrypto;
const decoder = require("../docs/_javascript/management_decoder.js");

function hex(text) {
  return Uint8Array.from(Buffer.from(text, "hex"));
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

  const groupData = "1A00" + decoder.EXAMPLE_PAGE;
  const packet = await decoder.decodeManagement(groupData, decoder.EXAMPLE_PASSWORD);
  assert.strictEqual(packet.public.envelope.route, "direct");
  assert.strictEqual(packet.public.envelope.pathHops, 0);
  const paddedRouted = "1A0177" + decoder.EXAMPLE_PAGE + "000000";
  const routed = await decoder.decodeManagement(paddedRouted, decoder.EXAMPLE_PASSWORD);
  assert.strictEqual(routed.public.envelope.pathHops, 1);
  assert.strictEqual(routed.acl[0].administrator, true);

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
  console.log("management browser decoder checks passed");
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
