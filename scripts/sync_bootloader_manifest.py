#!/usr/bin/env python3
"""Refresh the web/offline picker snapshot from the published OTAFIX manifest."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

REPO = "mikecarper/Adafruit_nRF52_Bootloader_OTAFIX"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/_data/bootloader_manifest.json")
    args = parser.parse_args()
    release = json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/releases/latest"]))
    assets = [asset for asset in release["assets"] if asset["name"] == "bootloader-manifest.json"]
    if len(assets) != 1 or release.get("draft") or release.get("prerelease"):
        raise ValueError("latest stable bootloader release has no unique download manifest")
    with tempfile.TemporaryDirectory(prefix="otafix-picker-") as directory:
        subprocess.run(["gh", "release", "download", release["tag_name"], "--repo", REPO,
                        "--pattern", "bootloader-manifest.json", "--dir", directory], check=True)
        data = (Path(directory) / "bootloader-manifest.json").read_bytes()
    if assets[0].get("digest") != "sha256:" + hashlib.sha256(data).hexdigest():
        raise ValueError("bootloader download manifest checksum mismatch")
    manifest = json.loads(data.decode("ascii"))
    if (manifest.get("schemaVersion") != 1 or manifest.get("repository") != REPO or
            manifest.get("tag") != release["tag_name"] or
            manifest.get("releaseUrl") != release["html_url"] or manifest.get("prerelease")):
        raise ValueError("bootloader download manifest does not match the latest stable release")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"Synced OTAFIX {manifest['version']} ({len(manifest['profiles'])} bootloader profiles)")


if __name__ == "__main__":
    main()
