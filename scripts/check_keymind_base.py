#!/usr/bin/env python3
"""Fail when KEYMIND_BASE_VERSION in the quake ini is not the newest Keymind release merged into HEAD.

The quake images report two versions: their own (FIRMWARE_VERSION) and the Keymind Cascade release they
are built on (KEYMIND_BASE_VERSION). The second is a hand-kept string, so after a Keymind merge it would
go stale silently. This reads the Keymind release tags (v<version>-halo-keymind-cascade-dev-<sha>) that
are ancestors of HEAD and compares. It needs full history and tags (fetch-depth 0).
"""
import re
import subprocess
import sys

INI = "variants/meshamerica_quake/platformio.ini"
BASE_DEFINE = re.compile(r"""KEYMIND_BASE_VERSION='"(\d+(?:\.\d+){1,3})"'""")
KEYMIND_TAG = re.compile(r"v(\d+(?:\.\d+){1,3})-halo-keymind-cascade-dev-[0-9a-f]+")


def as_tuple(text):
    return tuple(int(p) for p in text.split("."))


def newest_keymind_tag(tags):
    found = [m.group(1) for t in tags if (m := KEYMIND_TAG.fullmatch(t.strip()))]
    return max(found, key=as_tuple) if found else None


def check(ini_text, tags):
    declared = set(BASE_DEFINE.findall(ini_text))
    if len(declared) != 1:
        return [f"expected exactly one KEYMIND_BASE_VERSION in {INI}, found {sorted(declared) or 'none'}"]
    (declared,) = declared
    newest = newest_keymind_tag(tags)
    if newest is None:
        return ["no Keymind release tag is merged into HEAD (is the checkout shallow? use fetch-depth 0)"]
    if as_tuple(declared) != as_tuple(newest):
        return [f"KEYMIND_BASE_VERSION is {declared} but the newest Keymind release merged into HEAD is {newest}; "
                f"update [quake_version] in {INI}"]
    return []


def main():
    with open(INI, encoding="utf-8", newline=None) as f:
        text = f.read()
    tags = subprocess.run(["git", "tag", "--merged", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.split()
    errors = check(text, tags)
    for e in errors:
        print(f"error: {e}")
    if not errors:
        print("KEYMIND_BASE_VERSION matches the newest merged Keymind release")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
