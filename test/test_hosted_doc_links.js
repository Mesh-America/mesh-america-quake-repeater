"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { hideHostedDocLinks } = require("../docs/_javascript/hosted_doc_links.js");

function documentWith(banners) {
  return { querySelectorAll(selector) {
    assert.equal(selector, ".meshcore-hosted-doc-link");
    return banners;
  } };
}

for (const hostname of ["localhost", "127.0.0.1", "github.com", "example.org", "meshcore-dev.github.io",
  "mikecarper.github.io.example.org", "notmikecarper.github.io", ""]) {
  const banners = [{ hidden: false }, { hidden: false }];
  assert.equal(hideHostedDocLinks(documentWith(banners), hostname), 0);
  assert.equal(banners.some(banner => banner.hidden), false, hostname);
}
const banners = [{ hidden: false }, { hidden: false }];
assert.equal(hideHostedDocLinks(documentWith(banners), "mikecarper.github.io"), 2);
assert.equal(banners.every(banner => banner.hidden), true);
assert.equal(hideHostedDocLinks(documentWith([]), "mikecarper.github.io"), 0);

const script = fs.readFileSync(path.join(__dirname, "../docs/_javascript/hosted_doc_links.js"), "utf8");
const loadingBanners = [{ hidden: false }];
let ready;
let navigation;
const loadingDocument = Object.assign(documentWith(loadingBanners), {
  readyState: "loading",
  addEventListener(name, callback, options) {
    assert.equal(name, "DOMContentLoaded");
    assert.equal(options.once, true);
    ready = callback;
  }
});
vm.runInNewContext(script, {
  window: { location: { hostname: "mikecarper.github.io" } }, document: loadingDocument,
  document$: { subscribe(callback) { navigation = callback; } }
});
assert.equal(loadingBanners[0].hidden, false);
ready();
assert.equal(loadingBanners[0].hidden, true);
loadingBanners.push({ hidden: false });
navigation();
assert.equal(loadingBanners.every(banner => banner.hidden), true);

const readyBanners = [{ hidden: false }];
vm.runInNewContext(script, {
  window: { location: { hostname: "mikecarper.github.io" } },
  document: Object.assign(documentWith(readyBanners), { readyState: "complete" })
});
assert.equal(readyBanners[0].hidden, true);
const localBanners = [{ hidden: false }];
vm.runInNewContext(script, {
  window: { location: { hostname: "localhost" } },
  document: Object.assign(documentWith(localBanners), { readyState: "complete" })
});
assert.equal(localBanners[0].hidden, false);
console.log("Hosted documentation link domain, startup and navigation tests passed.");
