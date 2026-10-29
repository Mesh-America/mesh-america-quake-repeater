"""Backport NimBLE-Arduino PR1185 without changing the shared dependency.

The 2.5.1 host clears its timer event callback while that event may still be
queued during shutdown. Keep the callout alive until ble_hs_deinit(), which
already releases it after host shutdown. Upstream fix:
https://github.com/h2zero/NimBLE-Arduino/pull/1185
"""
from pathlib import Path
import hashlib
import re


PINNED_VERSION = "2.5.1"
PINNED_SHA256 = "c5677503b264738b692d0e688672011206a308d20c5ca1aa5e32a649443bd48a"
PATCHED_SHA256 = "8232c5a8721f8a75dc08dd93a7b7a1690c16a57f0c8f4660029c45e5a27be324"
SOURCE_SUFFIX = ("src", "nimble", "nimble", "host", "src", "ble_hs.c")
ORIGINAL = """    if (!ble_hs_is_enabled()) {
        ble_npl_callout_stop(&ble_hs_timer);
        ble_npl_callout_deinit(&ble_hs_timer);
    } else {
"""
REPAIRED = """    if (!ble_hs_is_enabled()) {
        ble_npl_callout_stop(&ble_hs_timer);
    } else {
"""


def patched_nimble_source(source, version):
    if version != PINNED_VERSION:
        raise RuntimeError("ESP32 NimBLE timer fix: unreviewed library version")
    source = source.replace("\r\n", "\n")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest == PATCHED_SHA256:
        return source
    if digest != PINNED_SHA256 or source.count(ORIGINAL) != 1:
        raise RuntimeError("ESP32 NimBLE timer fix: changed pinned source; review library update")
    patched = source.replace(ORIGINAL, REPAIRED, 1)
    if hashlib.sha256(patched.encode("utf-8")).hexdigest() != PATCHED_SHA256:
        raise RuntimeError("ESP32 NimBLE timer fix: unexpected transform result")
    return patched


def library_version(source):
    metadata = source.parents[5] / "library.properties"
    try:
        text = metadata.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError("ESP32 NimBLE timer fix: missing library metadata") from error
    names = re.findall(r"^name=(.*)$", text, re.MULTILINE)
    versions = re.findall(r"^version=(.*)$", text, re.MULTILINE)
    if names != ["NimBLE-Arduino"] or len(versions) != 1:
        raise RuntimeError("ESP32 NimBLE timer fix: malformed library metadata")
    return versions[0]


def replace_nimble_source(build_env, node):
    source = Path(node.srcnode().get_abspath())
    if source.parts[-6:] != SOURCE_SUFFIX or source.parents[5].name != "NimBLE-Arduino":
        return node
    original = source.read_text(encoding="utf-8")
    patched = patched_nimble_source(original, library_version(source))
    if patched == original:
        return node
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-esp32-nimble" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    # ble_hs_priv.h is a quoted sibling include in the original C source.
    build_env.AppendUnique(CPPPATH=[str(source.parent)])
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_nimble_source, "*NimBLE-Arduino*ble_hs.c")


if "Import" in globals():
    Import("env")
    install(env)
