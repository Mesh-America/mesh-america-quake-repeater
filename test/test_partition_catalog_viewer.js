"use strict";

const assert = require("assert");
const viewer = require("../docs/_javascript/esp32_partition_catalog.js");
const catalog = require("../firmware/esp32_partition_catalog.json");

assert.strictEqual(viewer.validateCatalog(catalog), catalog);
const layouts = JSON.parse(viewer.jsonView(catalog, "layouts"));
assert.deepStrictEqual(layouts.layouts, catalog.layouts);
assert.strictEqual(layouts.counts.builds, catalog.builds.length);
assert.strictEqual(layouts.counts.releases, catalog.releases.length);
assert.strictEqual(layouts.counts.unresolved, catalog.unresolved.length);
assert.strictEqual(layouts.builds, undefined);
assert.strictEqual(layouts.releases, undefined);
assert(viewer.jsonView(catalog, "layouts").length < 50000);
const releases = JSON.parse(viewer.jsonView(catalog, "releases"));
assert.deepStrictEqual(releases.releases, catalog.releases);
assert.strictEqual(releases.builds, undefined);
assert.deepStrictEqual(JSON.parse(viewer.jsonView(catalog, "all")), catalog);
assert.throws(() => viewer.jsonView(catalog, "unknown"), /Unknown catalog view/);
assert.throws(() => viewer.validateCatalog({ schema: 2 }), /Unsupported/);
assert.throws(() => viewer.validateCatalog(Object.assign({}, catalog, { layouts: [] })), /Unsupported/);

const minimums = viewer.boardMinimums(catalog);
assert.strictEqual(minimums.length, new Set(catalog.builds.map((build) => build.board.toLowerCase())).size);
const v3 = minimums.find((row) => row.board.toLowerCase() === "heltec_v3");
assert.strictEqual(v3.smallestBytes, 3342336);
assert.strictEqual(viewer.formatSize(v3.smallestBytes), "3.1875 MiB");
assert.strictEqual(viewer.otaLayouts(v3), "Dual-slot OTA");
assert.strictEqual(viewer.formatSize(null), "Unknown");

const sample = {
  schema: 1, repositories: [], releases: [], unresolved: [],
  layouts: {
    large: { dualOta: true, partitions: [[1, 2, 0x9000, 4096, "nvs", 0],
      [0, 16, 0x10000, 2097152, "app0", 0], [0, 17, 0x210000, 2097152, "app1", 0]] },
    small: { dualOta: true, partitions: [[0, 16, 0x10000, 2097152, "app0", 0],
      [0, 17, 0x210000, 1310720, "app1", 0]] },
    single: { dualOta: false, slotBytes: null,
      partitions: [[0, 0, 0x10000, 3145728, "factory", 0]] },
    noApps: { dualOta: false, partitions: [[1, 2, 0x9000, 4096, "nvs", 0]] },
  },
  builds: [
    { board: "Board_A", layout: "large" },
    { board: "board_a", layout: "small" },
    { board: "Board_B", layout: "single" },
    { board: "Board_C", layout: "single" },
    { board: "Board_C", layout: "large" },
    { board: "Board_D", layout: "missing" },
    { board: "Board_E", layout: "noApps" },
    { board: "Board_F", layout: "large" },
    { board: "Board_F", layout: "missing" },
  ],
};
const expectedSample = JSON.stringify(sample);
const sampleRows = viewer.boardMinimums(sample);
assert.strictEqual(JSON.stringify(sample), expectedSample);
assert.strictEqual(sampleRows.length, 6);
assert.strictEqual(sampleRows[0].smallestBytes, 1310720); // Smaller inactive slot, not NVS.
assert.strictEqual(sampleRows[1].smallestBytes, 3145728); // A single-app layout still has an app size.
assert.strictEqual(viewer.otaLayouts(sampleRows[1]), "No dual-slot OTA");
assert.strictEqual(viewer.otaLayouts(sampleRows[2]), "Mixed (some lack dual OTA)");
assert.strictEqual(sampleRows[3].smallestBytes, null);
assert.strictEqual(sampleRows[4].smallestBytes, null);
assert.strictEqual(sampleRows[5].smallestBytes, 2097152);
assert.strictEqual(viewer.otaLayouts(sampleRows[5]), "Unknown layouts present");

function element() {
  return {
    dataset: {}, children: [], hidden: false, textContent: "",
    addEventListener: function (event, handler) { this[event] = handler; },
    appendChild: function (child) { this.children.push(child); child.parentElement = this; },
  };
}

function fakePage() {
  const elements = {
    "partition-catalog": { dataset: {} },
    "partition-catalog-view": {
      value: "layouts", disabled: true,
      addEventListener: function (event, handler) { this[event] = handler; },
    },
    "partition-catalog-status": { textContent: "Loading..." },
    "partition-catalog-json": { textContent: "" },
    "partition-catalog-open": {
      href: "https://example.test/MeshCore/_data/esp32_partition_catalog.json",
    },
    "partition-catalog-raw": Object.assign(element(), { open: false }),
    "partition-catalog-search": Object.assign(element(), { value: "", disabled: true }),
    "partition-catalog-boards": element(),
    "partition-catalog-count": element(),
  };
  elements.table = Object.assign(element(), { hidden: true });
  elements["partition-catalog-table"] = elements.table;
  global.document = { getElementById: (id) => elements[id], createElement: element };
  return elements;
}

async function testBrowser() {
  const oldFetch = global.fetch;
  const oldDocument = global.document;
  try {
    let calls = 0;
    global.fetch = async function (url) {
      calls++;
      assert.strictEqual(url, "https://example.test/MeshCore/_data/esp32_partition_catalog.json");
      return { ok: true, json: async () => catalog };
    };
    const page = fakePage();
    await viewer.initializeViewer();
    assert.strictEqual(page["partition-catalog-view"].disabled, false);
    assert.strictEqual(page["partition-catalog-json"].textContent, ""); // Details are lazy.
    assert.strictEqual(page.table.hidden, false);
    assert.strictEqual(page["partition-catalog-boards"].children.length, minimums.length);
    assert.strictEqual(page["partition-catalog-search"].disabled, false);
    page["partition-catalog-search"].value = "HELTEC_V3";
    page["partition-catalog-search"].input();
    assert.strictEqual(page["partition-catalog-count"].textContent, "Showing 1 of " + minimums.length + " boards.");
    const visible = page["partition-catalog-boards"].children.filter((row) => !row.hidden);
    assert.strictEqual(visible[0].children[0].textContent, v3.board);
    assert.strictEqual(visible[0].children[1].textContent, "3.1875 MiB");
    assert.strictEqual(visible[0].children[1].children[0].textContent, "3,342,336 bytes");
    page["partition-catalog-search"].value = "no matching board";
    page["partition-catalog-search"].input();
    assert.strictEqual(page["partition-catalog-count"].textContent, "Showing 0 of " + minimums.length + " boards.");
    page["partition-catalog-raw"].open = true;
    page["partition-catalog-raw"].toggle();
    assert.deepStrictEqual(JSON.parse(page["partition-catalog-json"].textContent).layouts, catalog.layouts);
    assert(page["partition-catalog-status"].textContent.includes(
      catalog.builds.length.toLocaleString("en-US") + " builds"));
    page["partition-catalog-view"].value = "all";
    page["partition-catalog-view"].change();
    assert.deepStrictEqual(JSON.parse(page["partition-catalog-json"].textContent), catalog);
    await viewer.initializeViewer();
    assert.strictEqual(calls, 1);

    global.fetch = async () => ({ ok: false, status: 404 });
    const missing = fakePage();
    await viewer.initializeViewer();
    assert(missing["partition-catalog-status"].textContent.includes("HTTP 404"));
    assert(missing["partition-catalog-status"].textContent.includes("Open JSON"));
    assert.strictEqual(missing["partition-catalog-view"].disabled, true);
    assert.strictEqual(missing.table.hidden, true);

    global.fetch = async () => ({ ok: true, json: async () => ({ schema: 2 }) });
    const invalid = fakePage();
    await viewer.initializeViewer();
    assert(invalid["partition-catalog-status"].textContent.includes("Unsupported"));

    global.document = { getElementById: () => null };
    global.fetch = async () => { throw new Error("Other pages must not fetch the catalog"); };
    await viewer.initializeViewer();
  } finally {
    global.fetch = oldFetch;
    global.document = oldDocument;
  }
}

testBrowser().then(() => {
  console.log("board minima, OTA warnings, search, JSON views, loading and error states passed");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
