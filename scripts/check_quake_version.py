#!/usr/bin/env python3
"""Release-metadata checks for the Mesh America Quake Repeater images.

Run by the `release-metadata` job of .github/workflows/quake-ci.yml, on the manifests the build
job wrote (scripts/quake_release_manifest.py), not on platformio.ini: an environment that loses
its FIRMWARE_VERSION define silently falls back to a header default, which a text search of the
ini would not see and the built manifest does.

Rules
  1. At least two manifests (one per image), all with the same version.
  2. Versions compare numerically as four fields, never as strings.
  3. The version is never lower than the highest existing quake-v* tag.
  4. On a pull request whose version differs from the base branch's, it must be strictly greater
     than the highest tag (a bump must be a real bump). A merge-back pull request
     (head ref merge/main-into-next-*) is exempt from the strict rule, because it carries main's
     version, which equals the newest tag.
  5. On push and tag events the strict rule does not apply: on a push to main the release job
     creates the tag for that very version after these checks pass.
"""
import argparse
import glob
import json
import re
import subprocess
import sys

INI = "variants/meshamerica_quake/platformio.ini"
VERSION_DEFINE = re.compile(r"""FIRMWARE_VERSION='"v?(\d+(?:\.\d+){0,3})"'""")


def parse_version(text):
    parts = [int(p) for p in str(text).lstrip("v").split(".")]
    if not 1 <= len(parts) <= 4 or any(p > 255 for p in parts):
        raise ValueError(f"not a packable version: {text!r}")
    return tuple(parts + [0] * (4 - len(parts)))


def format_version(v):
    return ".".join(str(p) for p in v)


def highest_tag(tags):
    versions = []
    for tag in tags:
        m = re.fullmatch(r"quake-v(\d+(?:\.\d+){0,3})", tag.strip())
        if m:
            versions.append(parse_version(m.group(1)))
    return max(versions) if versions else None


def ini_versions(text):
    return sorted({parse_version(v) for v in VERSION_DEFINE.findall(text)})


def check(manifest_versions, tags, base_version, event, merge_back=False, manifest_count=None):
    """Return a list of error strings (empty when everything holds)."""
    errors = []
    count = len(manifest_versions) if manifest_count is None else manifest_count
    if count < 2:
        errors.append(f"expected a manifest for each of the two images, found {count}")
    try:
        parsed = {parse_version(v) for v in manifest_versions}
    except ValueError as e:
        return errors + [str(e)]
    if len(parsed) != 1:
        errors.append("the images carry different versions: "
                      + ", ".join(sorted(format_version(v) for v in parsed)))
        return errors
    version = next(iter(parsed))
    top = highest_tag(tags)
    if top is not None and version < top:
        errors.append(f"version {format_version(version)} is lower than the existing tag "
                      f"quake-v{format_version(top)}")
    elif (event == "pull_request" and not merge_back and top is not None
          and base_version is not None and version != base_version and version <= top):
        errors.append(f"this pull request changes the version to {format_version(version)}, which "
                      f"is not greater than the existing tag quake-v{format_version(top)}")
    return errors


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifests", default="dist", help="folder holding manifest*.json")
    ap.add_argument("--event", required=True, choices=["pull_request", "push", "tag", "other"])
    ap.add_argument("--base-ref", help="base branch name of a pull request (origin/<name> is read)")
    ap.add_argument("--head-ref", default="", help="head branch name of a pull request")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(f"{args.manifests}/manifest*.json"))
    versions = [json.load(open(p, encoding="utf-8"))["version"] for p in paths]
    tags = git("tag", "--list", "quake-v*").split()

    base_version = None
    if args.event == "pull_request" and args.base_ref:
        base_versions = ini_versions(git("show", f"origin/{args.base_ref}:{INI}"))
        base_version = base_versions[-1] if base_versions else None

    errors = check(versions, tags, base_version, args.event,
                   merge_back=args.head_ref.startswith("merge/main-into-next-"),
                   manifest_count=len(paths))
    top = highest_tag(tags)
    print(f"manifests: {len(paths)}; versions: {sorted(set(versions))}; "
          f"highest tag: {format_version(top) if top else 'none'}; "
          f"base version: {format_version(base_version) if base_version else 'n/a'}")
    for e in errors:
        print(f"::error::{e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
