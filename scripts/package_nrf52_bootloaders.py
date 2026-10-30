#!/usr/bin/env python3
"""Stage the pinned normal OTAFIX catalog with exact-board standalone assets."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import tempfile
from urllib.request import urlopen

from intelhex import IntelHex

import nrf52_embedded_bootloader as embedded


ROOT = embedded.ROOT
MANIFEST_NAME = "bootloader-manifest.json"
INVENTORY_NAME = "OTAFIX-BOOTLOADERS-" + embedded.VERSION + ".json"
CHECKSUMS_NAME = "OTAFIX-BOOTLOADERS-" + embedded.VERSION + ".SHA256SUMS.txt"
README_NAME = "OTAFIX-BOOTLOADERS-" + embedded.VERSION + ".md"
ASSET_KINDS = ("hex", "uf2", "zip")
MAX_ASSET_SIZE = 2 * 1024 * 1024
BOOTLOADER_UF2_FAMILY = 0xD663823C


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset(profile: dict, kind: str) -> dict:
    asset = profile["files"][kind]
    if not isinstance(asset, dict):
        raise ValueError("invalid bootloader asset metadata")
    name, size, digest = asset.get("name"), asset.get("size"), asset.get("sha256")
    prefix = profile["id"] + "_bootloader-" + embedded.TAG
    expected = (re.escape("update-" + prefix + "_mbr.uf2") if kind == "uf2" else
                re.escape(prefix) + r"_s140_(?:6\.1\.1|7\.3\.0)\." + kind)
    if (not isinstance(name, str) or not re.fullmatch(
            expected, name)
            or type(size) is not int or not 0 < size <= MAX_ASSET_SIZE
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or asset.get("url") !=
            f"https://github.com/{embedded.REPOSITORY}/releases/download/{embedded.TAG}/{name}"):
        raise ValueError("invalid exact-profile bootloader asset metadata")
    return asset


def _validate_catalog(manifest: dict) -> list[dict]:
    profiles = manifest.get("profiles")
    coverage = manifest.get("coverage")
    if not isinstance(profiles, list) or not profiles or not isinstance(coverage, dict):
        raise ValueError("bootloader catalog lacks normal-profile coverage")
    ids, hardware, names = set(), set(), set()
    unavailable = manifest.get("unavailableProfiles", [])
    if not isinstance(unavailable, list):
        raise ValueError("invalid unavailable bootloader catalog")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", item["id"])
           for item in unavailable):
        raise ValueError("invalid unavailable bootloader profile")
    unavailable_ids = {item["id"] for item in unavailable}
    if len(unavailable_ids) != len(unavailable):
        raise ValueError("duplicate unavailable bootloader profile")
    for profile in profiles:
        if (not isinstance(profile, dict)
                or not isinstance(profile.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", profile["id"])
                or profile["id"] in ids or profile["id"] in unavailable_ids
                or profile.get("storage") not in ("internal", "qspi", "sd", "adaptive")
                or not isinstance(profile.get("label"), str) or not profile["label"]
                or not isinstance(profile.get("deviceName"), str)
                or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", profile["deviceName"])
                or not isinstance(profile.get("files"), dict)
                or set(profile["files"]) != set(ASSET_KINDS)):
            raise ValueError("invalid or duplicate normal bootloader profile")
        aliases = profile.get("meshcoreHardware")
        if (not isinstance(aliases, list) or not aliases
                or any(not isinstance(name, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.+-]*", name) for name in aliases)
                or len(set(aliases)) != len(aliases) or hardware.intersection(aliases)):
            raise ValueError("ambiguous bootloader hardware mapping")
        ids.add(profile["id"])
        hardware.update(aliases)
        for kind in ASSET_KINDS:
            asset = _asset(profile, kind)
            if asset["name"] in names:
                raise ValueError("duplicate bootloader asset name")
            names.add(asset["name"])
    if (type(coverage.get("releasedProfiles")) is not int
            or coverage["releasedProfiles"] != len(ids)
            or type(coverage.get("releasedHardware")) is not int
            or coverage["releasedHardware"] != len(hardware)):
        raise ValueError("normal bootloader coverage differs from its catalog")
    return sorted(profiles, key=lambda item: item["id"])


def _verified(data: bytes, asset: dict) -> bool:
    return len(data) == asset["size"] and _digest(data) == asset["sha256"]


def _download_asset(asset: dict, cache_dir: Path) -> bytes:
    """Cache only complete hash-matched files; never expose partial cache data."""
    path = cache_dir / (asset["sha256"] + "-" + asset["name"])
    if path.is_symlink():
        raise ValueError("bootloader cache entry must not be a symlink")
    if path.is_file() and path.stat().st_size == asset["size"]:
        data = path.read_bytes()
        if _verified(data, asset):
            return data
    with urlopen(asset["url"], timeout=60) as response:
        data = response.read(asset["size"] + 1)
    if not _verified(data, asset):
        raise ValueError("downloaded bootloader asset size/SHA-256 mismatch")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache_dir, prefix="otafix-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return data


def _validate_hex(data: bytes, candidate: bytes) -> None:
    try:
        image = IntelHex(io.StringIO(data.decode("ascii")))
        boot = bytes(image.tobinarray(start=embedded.BOOT_BASE, size=embedded.BOOT_SIZE))
    except Exception as error:
        raise ValueError("invalid standalone bootloader HEX") from error
    if boot != candidate:
        raise ValueError("standalone HEX does not contain the exact profile bootloader")


def _validate_uf2(data: bytes, candidate: bytes) -> None:
    if not data or len(data) % 512:
        raise ValueError("invalid standalone bootloader UF2 length")
    count = len(data) // 512
    # Published UF2 files omit erased padding between executable data and CF2.
    # Reconstruct that padding exactly as HEX/Legacy DFU do, rather than
    # requiring writes for bytes whose verified value is already erased.
    boot = bytearray([0xFF]) * embedded.BOOT_SIZE
    written = set()
    previous_end = -1
    for index in range(count):
        offset = index * 512
        magic0, magic1, flags, address, size, block, blocks, family = struct.unpack_from(
            "<8I", data, offset)
        end = address + size
        in_boot = embedded.BOOT_BASE <= address and end <= embedded.BOOT_BASE + embedded.BOOT_SIZE
        allowed = in_boot or (address < 0x1000 and end <= 0x1000) or (
            0x10001000 <= address and end <= 0x10002000)
        if (magic0 != 0x0A324655 or magic1 != 0x9E5D5157
                or struct.unpack_from("<I", data, offset + 508)[0] != 0x0AB16F30
                or flags != 0x2000 or family != BOOTLOADER_UF2_FAMILY
                or size != 256 or address % 256 or address < previous_end
                or block != index or blocks != count or not allowed):
            raise ValueError("invalid standalone bootloader UF2 geometry")
        previous_end = end
        if in_boot:
            position = address - embedded.BOOT_BASE
            boot[position:position + size] = data[offset + 32:offset + 32 + size]
            written.add(position)
    if not written or bytes(boot) != candidate:
        raise ValueError("standalone UF2 does not contain the exact complete profile bootloader")


def _catalog(project_root: Path) -> tuple[dict, bytes, list[dict]]:
    manifest = embedded.load_manifest(project_root)
    raw = (project_root / "docs/_data/bootloader_manifest.json").read_bytes()
    if _digest(raw) != embedded.MANIFEST_SHA256:
        raise ValueError("pinned bootloader manifest changed during staging")
    return manifest, raw, _validate_catalog(manifest)


def _json_bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("ascii")


def _readme() -> bytes:
    return (f"# OTAFIX {embedded.VERSION} standalone bootloaders\n\n"
            f"Source: https://github.com/{embedded.REPOSITORY}/releases/tag/{embedded.TAG}\n\n"
            "These normal, exact-board bootloaders apply to every application role.\n"
            "Select the physical board and storage profile from bootloader-manifest.json.\n"
            "No recovery, retired, blocked or hardware-pending image is included.\n\n"
            "- UF2 updates an existing compatible bootloader and requires valid hash-bound\n"
            "  application EndF metadata for its staging safety checks.\n"
            "- DFU ZIP contains the SoftDevice and bootloader; reinstall the application\n"
            "  afterward. This is not an application DFU ZIP.\n"
            "- HEX is for SWD installation or recovery.\n\n"
            "Historical incompatible identities require their documented local migration.\n"
            "A completed copy is not proof of activation: verify the bootloader version.\n"
            "Ordinary MeshCore firmware does not install these bootloaders automatically.\n"
            "Separate with-bootloader application variants have their own role, identity\n"
            "and layout restrictions; this standalone catalog does not bypass them.\n").encode("ascii")


def _collect(manifest: dict, profiles: list[dict], project_root: Path,
             read_asset, write_asset=None) -> dict:
    inventory = {
        "schema_version": 1,
        "kind": "nrf52-standalone-bootloader-catalog",
        "version": embedded.VERSION,
        "tag": embedded.TAG,
        "source": {"repository": embedded.REPOSITORY,
                   "release_url": manifest["releaseUrl"],
                   "manifest_path": MANIFEST_NAME,
                   "manifest_sha256": embedded.MANIFEST_SHA256},
        "profile_count": len(profiles),
        "hardware_count": manifest["coverage"]["releasedHardware"],
        "profiles": [],
        "assets": [],
        "excluded_profiles": sorted(item["id"] for item in manifest.get("unavailableProfiles", [])),
        "inventory_path": INVENTORY_NAME,
        "checksums_path": CHECKSUMS_NAME,
        "readme_path": README_NAME,
    }
    for profile in profiles:
        archive = read_asset(profile, "zip")
        candidate, identity = embedded.validate_candidate_zip(archive, profile, project_root)
        if len(candidate) != embedded.BOOT_SIZE or identity.device_name != profile["deviceName"]:
            raise ValueError("standalone bootloader profile proof is incomplete")
        record = {"id": profile["id"], "label": profile["label"],
                  "storage": profile["storage"], "device_name": profile["deviceName"],
                  "meshcore_hardware": sorted(profile["meshcoreHardware"]),
                  "bootloader_sha256": _digest(candidate), "image_bytes": len(candidate),
                  "board_id": identity.board_id, "app_base": identity.app_base,
                  "softdevice_fwid": identity.softdevice_fwid, "files": {}}
        for kind in ASSET_KINDS:
            asset = _asset(profile, kind)
            data = archive if kind == "zip" else read_asset(profile, kind)
            if not _verified(data, asset):
                raise ValueError("standalone bootloader asset failed final verification")
            if kind == "hex":
                _validate_hex(data, candidate)
            elif kind == "uf2":
                _validate_uf2(data, candidate)
            if write_asset is not None:
                write_asset(asset["name"], data)
            entry = {"kind": kind, "profile": profile["id"], "name": asset["name"],
                     "path": asset["name"], "size": asset["size"], "sha256": asset["sha256"]}
            inventory["assets"].append(entry)
            record["files"][kind] = dict(entry)
        inventory["profiles"].append(record)
    inventory["assets"].sort(key=lambda entry: entry["path"])
    return inventory


def _checksums(directory: Path) -> bytes:
    return "".join(_digest(path.read_bytes()) + "  " + path.name + "\n"
                   for path in sorted(directory.iterdir(), key=lambda path: path.name)
                   if path.name != CHECKSUMS_NAME).encode("ascii")


def validate_bootloader_catalog(directory: Path, *, project_root: Path = ROOT) -> dict:
    """Recheck an existing catalog against pinned assets without network access."""
    directory, project_root = Path(directory), Path(project_root)
    manifest, raw, profiles = _catalog(project_root)
    expected_names = {MANIFEST_NAME, INVENTORY_NAME, CHECKSUMS_NAME, README_NAME}
    expected_names.update(_asset(profile, kind)["name"]
                          for profile in profiles for kind in ASSET_KINDS)
    if (directory.is_symlink() or not directory.is_dir()
            or {path.name for path in directory.iterdir()} != expected_names
            or any(path.is_symlink() or not path.is_file() for path in directory.iterdir())):
        raise ValueError("standalone bootloader inventory is incomplete or contains unexpected files")
    if (directory / MANIFEST_NAME).read_bytes() != raw:
        raise ValueError("standalone bootloader manifest differs from its pin")

    def read_asset(profile, kind):
        asset = _asset(profile, kind)
        path = directory / asset["name"]
        if path.stat().st_size != asset["size"]:
            raise ValueError("standalone bootloader asset size mismatch")
        data = path.read_bytes()
        if not _verified(data, asset):
            raise ValueError("standalone bootloader asset SHA-256 mismatch")
        return data

    inventory = _collect(manifest, profiles, project_root, read_asset)
    if (directory / INVENTORY_NAME).read_bytes() != _json_bytes(inventory):
        raise ValueError("standalone bootloader metadata differs from verified assets")
    if (directory / README_NAME).read_bytes() != _readme():
        raise ValueError("standalone bootloader installation notes differ")
    if (directory / CHECKSUMS_NAME).read_bytes() != _checksums(directory):
        raise ValueError("standalone bootloader checksum inventory differs")
    return inventory


def stage_bootloader_catalog(destination: Path, *, project_root: Path = ROOT,
                             cache_dir: Path | None = None) -> dict:
    """Publish a complete normal catalog into an empty destination, or no files."""
    project_root, destination = Path(project_root), Path(destination)
    if destination.is_symlink() or (destination.exists() and (
            not destination.is_dir() or any(destination.iterdir()))):
        raise ValueError("bootloader destination must be absent or an empty directory")
    manifest, raw, profiles = _catalog(project_root)
    cache = Path(cache_dir) if cache_dir is not None else project_root / ".pio/otafix-cache"
    if cache.is_symlink():
        raise ValueError("bootloader cache must not be a symlink")
    cache.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def read_asset(profile, kind):
        asset = _asset(profile, kind)
        path = cache / (asset["sha256"] + "-" + asset["name"])
        if path.is_symlink():
            raise ValueError("bootloader cache entry must not be a symlink")
        return (embedded.download_zip(profile, cache) if kind == "zip"
                else _download_asset(asset, cache))

    with tempfile.TemporaryDirectory(prefix="." + destination.name + "-", dir=destination.parent) as work:
        staging = Path(work) / "catalog"
        staging.mkdir()
        (staging / MANIFEST_NAME).write_bytes(raw)
        inventory = _collect(manifest, profiles, project_root, read_asset,
                             lambda name, data: (staging / name).write_bytes(data))
        (staging / INVENTORY_NAME).write_bytes(_json_bytes(inventory))
        (staging / README_NAME).write_bytes(_readme())
        (staging / CHECKSUMS_NAME).write_bytes(_checksums(staging))
        validate_bootloader_catalog(staging, project_root=project_root)
        # Rename the complete directory on the same filesystem. If an existing
        # empty destination changed while downloading, refuse to remove it.
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
    return inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    receipt = stage_bootloader_catalog(args.destination, project_root=args.project_root,
                                       cache_dir=args.cache_dir)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
