#!/usr/bin/env python3
"""Bind an embedded bootloader claim to the actual packaged application."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from nrf52_embedded_bootloader import (ROOT, BOOT_SIZE, VERSION, MANIFEST_SHA256,
    LEGACY_SHA256, load_manifest, select_profile, download_zip, validate_candidate_zip)

sys.path.insert(0, str(ROOT / "tools/mota"))
from motalib import parse_endf, parse_endf_ident, parse_nrf52_layout, target_id_for_env


def qualify(directory, manifest_path):
    directory, manifest_path = Path(directory), Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("platform") != "NRF52_PLATFORM" or manifest.get("verified") is not True:
        raise ValueError("embedded bootloader requires qualified nRF52 firmware")
    profile, _ = select_profile(load_manifest(), manifest["target"])
    candidate, identity = validate_candidate_zip(download_zip(profile, ROOT / ".pio/otafix-cache"), profile)
    resource = directory / "bootloader-migration-resource"
    metadata = json.loads((resource / "BootloaderMigrationResource.json").read_text())
    if (metadata.get("profile") != profile["id"] or metadata.get("release") != VERSION
            or metadata.get("manifest_sha256") != MANIFEST_SHA256
            or metadata.get("asset_sha256") != profile["files"]["zip"]["sha256"]
            or metadata.get("candidate_sha256") != hashlib.sha256(candidate).hexdigest()
            or metadata.get("legacy_sha256") not in (None, LEGACY_SHA256)
            or (resource / "BootloaderMigrationResource.bin").read_bytes() != candidate):
        raise ValueError("embedded bootloader build resource differs from its pinned release")
    with zipfile.ZipFile(directory / "firmware.zip") as package:
        entry = json.loads(package.read("manifest.json"))["manifest"]["application"]
        application = package.read(entry["bin_file"])
    body, _ = parse_endf(application)
    app_identity = parse_endf_ident(application)
    layout = parse_nrf52_layout(application)
    offset = body.find(candidate)
    if (not app_identity or app_identity.target_id != target_id_for_env(manifest["target"])
            or not layout or layout.app_base != identity.app_base
            or len(application) > layout.linked_app_end - layout.app_base
            or offset < 0 or offset % 4 or body.find(candidate, offset + 1) >= 0
            or offset + BOOT_SIZE > len(body)
            or b"BL embedded 2.4.12" not in body):
        raise ValueError("packaged application lacks the complete aligned embedded bootloader or activation code")
    manifest["embedded_bootloader"] = {
        "release": VERSION, "profile": profile["id"],
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "asset_sha256": profile["files"]["zip"]["sha256"],
        "manifest_sha256": MANIFEST_SHA256,
        "legacy_sha256": metadata.get("legacy_sha256"),
        "app_offset": offset, "image_bytes": BOOT_SIZE,
        "activation": "ota bootloader update",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest["embedded_bootloader"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = qualify(args.directory, args.manifest)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Embedded bootloader qualification failed: {exc}\n")
    print(f"Verified embedded OTAFIX {result['release']}: {result['profile']}; {result['image_bytes']} bytes")
