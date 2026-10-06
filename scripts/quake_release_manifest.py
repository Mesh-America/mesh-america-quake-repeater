#!/usr/bin/env python3
"""Verify a Quake Repeater DFU package and write the manifest the flasher's catalog is built from.

    quake_release_manifest.py --zip firmware.zip --env MeshAmerica_Quake_Repeater_RAK3401 \
        --commit <sha> --tag quake-v1.17.1.0 --out dist/

Writes dist/manifest.json (or the name given with --manifest-name, for the second and later images
of one release) and copies the package to dist/<env>-<version>.zip. Refuses to produce
anything unless the package is a plain application update, its image carries a consistent MeshCore
identity block (the 56-byte "EndF" trailer: docs/ota_protocol.md section 2), the OTA target id is
the one the environment name implies, and the tag (when given) names the version in the image.
Standard library only, so it runs anywhere the build does.
"""

import argparse
import hashlib
import json
import shutil
import struct
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ENDF_LENGTH = 56
MAX_ZIP_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 1024 * 1024  # nRF52840 flash
TAG_PREFIX = "quake-v"
SCHEMA_VERSION = 1


class ManifestError(Exception):
    """The package or its identity is not acceptable for release."""


def target_id_for_env(env_name: str) -> int:
    """OTA target id: first 4 bytes, little endian, of sha256(environment name)."""
    return struct.unpack("<I", hashlib.sha256(env_name.encode()).digest()[:4])[0]


def format_version(packed: int) -> str:
    return ".".join(str((packed >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def read_endf(image: bytes) -> dict:
    if len(image) < ENDF_LENGTH or image[-ENDF_LENGTH:-ENDF_LENGTH + 4] != b"EndF":
        raise ManifestError("the image has no identity block (EndF trailer)")
    trailer = image[-ENDF_LENGTH:]
    body_len, = struct.unpack_from("<I", trailer, 4)
    if body_len != len(image) - ENDF_LENGTH:
        raise ManifestError("the identity block does not match the image size")
    body_hash = trailer[8:16]
    if hashlib.sha256(image[:body_len]).digest()[:8] != body_hash:
        raise ManifestError("the image does not match its identity hash")
    fw_version, target_id = struct.unpack_from("<II", trailer, 16)
    hw_id = trailer[24:56].split(b"\0", 1)[0].decode("ascii", "replace")
    return {"body_length": body_len, "fw_version": fw_version, "target_id": target_id, "hardware_id": hw_id}


def read_package(zip_path: Path) -> tuple[bytes, dict]:
    """Return (application image, parsed manifest) after refusing anything but an app-only update."""
    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        raise ManifestError("the package is too large to be a firmware package")
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ManifestError("the package lists the same file twice")
            if "manifest.json" not in names:
                raise ManifestError("the package has no manifest.json")
            manifest = json.loads(archive.read("manifest.json"))
            entries = manifest.get("manifest") if isinstance(manifest, dict) else None
            if not isinstance(entries, dict):
                raise ManifestError("the package manifest is not in the expected format")
            for forbidden in ("softdevice", "bootloader", "softdevice_bootloader"):
                if forbidden in entries:
                    raise ManifestError(f"the package contains a {forbidden} image; only application updates are released")
            app = entries.get("application")
            if not isinstance(app, dict) or not isinstance(app.get("bin_file"), str):
                raise ManifestError("the package has no application image")
            info = archive.getinfo(app["bin_file"])
            if info.file_size == 0 or info.file_size > MAX_IMAGE_BYTES:
                raise ManifestError("the application image has an impossible size")
            return archive.read(app["bin_file"]), app
    except zipfile.BadZipFile as error:
        raise ManifestError("the file is not a valid zip archive") from error
    except KeyError as error:
        raise ManifestError(f"the package is missing {error}") from error


def read_hex_image(hex_path: Path) -> bytes:
    """Flatten an Intel HEX file into the bytes it describes, from its lowest address to its highest."""
    memory: dict[int, int] = {}
    base = 0
    try:
        lines = hex_path.read_text(encoding="ascii").splitlines()
    except (UnicodeDecodeError, OSError) as error:
        raise ManifestError("the hex file cannot be read") from error
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            if not line.startswith(":"):
                raise ValueError
            record = bytes.fromhex(line[1:])
            count, offset, kind = record[0], (record[1] << 8) | record[2], record[3]
            data = record[4:4 + count]
            if len(record) != count + 5 or sum(record) & 0xFF:
                raise ValueError
        except (ValueError, IndexError) as error:
            raise ManifestError(f"the hex file has a damaged record on line {number}") from error
        if kind == 0:
            for index, value in enumerate(data):
                memory[base + offset + index] = value
        elif kind == 2 and len(data) == 2:
            base = ((data[0] << 8) | data[1]) << 4
        elif kind == 4 and len(data) == 2:
            base = ((data[0] << 8) | data[1]) << 16
    if not memory:
        raise ManifestError("the hex file holds no data")
    low, high = min(memory), max(memory)
    return bytes(memory.get(address, 0xFF) for address in range(low, high + 1))


def build_manifest(zip_path: Path, env_name: str, commit: str, tag: str | None, built_at: str,
                   hex_path: Path | None = None) -> dict:
    image, _app = read_package(zip_path)
    if hex_path is not None and read_hex_image(hex_path) != image:
        raise ManifestError("the hex file does not hold the same application image as the package")
    identity = read_endf(image)
    expected_target = target_id_for_env(env_name)
    if identity["target_id"] != expected_target:
        raise ManifestError(
            f"OTA target id is 0x{identity['target_id']:08x}, but {env_name} implies 0x{expected_target:08x}"
        )
    if not identity["hardware_id"]:
        raise ManifestError("the image has an empty hardware id")
    if identity["fw_version"] == 0:
        raise ManifestError("the image has no firmware version")
    version = format_version(identity["fw_version"])
    if tag is not None and tag != f"{TAG_PREFIX}{version}":
        raise ManifestError(f"tag {tag} does not match the version in the image; expected {TAG_PREFIX}{version}")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "env": env_name,
        "version": version,
        "tag": tag,
        "commit": commit,
        "builtAt": built_at,
        "package": {
            "file": f"{env_name}-{version}.zip",
            "size": zip_path.stat().st_size,
            "sha256": digest,
        },
        "targetId": f"0x{identity['target_id']:08x}",
        "hardwareId": identity["hardware_id"],
    }
    if hex_path is not None:
        # The exact firmware.hex of this release. A LoRa OTA update is built from the new hex and, for
        # a delta, from the hex the node is running now (docs/ota_easy.md), so every release keeps it.
        manifest["hex"] = {
            "file": f"{env_name}-{version}.hex",
            "size": hex_path.stat().st_size,
            "sha256": hashlib.sha256(hex_path.read_bytes()).hexdigest(),
        }
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--hex", type=Path, help="the build's firmware.hex, checked against the package and published with it")
    parser.add_argument("--env", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", help="release tag; checked against the version inside the image")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest-name", default="manifest.json",
                        help="file name for the manifest (default manifest.json); a release with several images "
                             "keeps the first board's as manifest.json and names the others manifest-<env>.json")
    args = parser.parse_args(argv)
    if "/" in args.manifest_name or "\\" in args.manifest_name or not args.manifest_name.endswith(".json"):
        parser.error("--manifest-name must be a plain .json file name")
    try:
        built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = build_manifest(args.zip, args.env, args.commit, args.tag, built_at, args.hex)
    except ManifestError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.zip, args.out / manifest["package"]["file"])
    if args.hex is not None:
        shutil.copyfile(args.hex, args.out / manifest["hex"]["file"])
    (args.out / args.manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
