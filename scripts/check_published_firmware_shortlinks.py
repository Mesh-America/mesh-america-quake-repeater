#!/usr/bin/env python3
"""Keep short download identities unchanged from the deployed Pages registry."""

import argparse
import os
from pathlib import Path
import subprocess

from firmware_shortlinks import load_manifest, validate_immutable


PUBLISHED_PATH = "_data/firmware_shortlinks.json"


def check_published(manifest, previous):
    current = load_manifest(manifest)
    previous = Path(previous)
    previous.unlink(missing_ok=True)
    found = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "gh-pages"],
        capture_output=True, text=True, check=False)
    if found.returncode == 2:
        return False  # First Pages deployment: no published branch exists.
    if found.returncode:
        raise RuntimeError("Cannot check published Pages branch: " + found.stderr.strip())
    subprocess.run(["git", "fetch", "--depth=1", "--no-tags", "origin", "gh-pages"], check=True)
    names = subprocess.check_output(
        ["git", "ls-tree", "--name-only", "FETCH_HEAD", "--", PUBLISHED_PATH], text=True)
    if not names.strip():
        return False  # Existing site predates short firmware links.
    data = subprocess.check_output(["git", "show", "FETCH_HEAD:" + PUBLISHED_PATH])
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_bytes(data)
    validate_immutable(load_manifest(previous), current)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    args = parser.parse_args()
    try:
        existing = check_published(args.manifest, args.previous)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Firmware short-link deployment rejected: " + str(error) + "\n")
    if existing and os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as environment:
            environment.write("MESHCORE_SHORTLINKS_PREVIOUS=" + str(args.previous.resolve()) + "\n")
    print("Published firmware links preserved." if existing else "First firmware short-link deployment.")


if __name__ == "__main__":
    main()
