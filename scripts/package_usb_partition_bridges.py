#!/usr/bin/env python3
"""Package all six USB-safe bridges without rebuilding or relabeling Full apps.

This utility set is paired by the host with the exact original Full migration
package. It carries its own source provenance, not that Full image's commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from package_esp32_partition_migration import (
    USB_BRIDGE_PROFILES, resolve_pio_build_dir, validate_usb_bridge,
)


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "meshcore-usb-partition-bridges-v1"
SOURCE_FILES = (
    "examples/esp32_partition_migrator/main.cpp",
    "src/helpers/ESP32PartitionMigrationPolicy.h",
    "src/helpers/ESP32PartitionMigrationUsbRecovery.h",
    "scripts/esp32_partition_migration_nvs_guard.py",
    "scripts/esp32_wifi_scan_fix.py",
    "scripts/check_firmware_ram.py",
    "variants/esp32_partition_migrator/platformio.ini",
    "platformio.ini",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_provenance(root: Path = ROOT) -> dict:
    source = subprocess.check_output(
        ["git", "-c", "core.autocrlf=input", "rev-parse", "HEAD"],
        cwd=root, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{8,40}", source):
        raise ValueError("invalid USB bridge source commit")
    dirty = bool(subprocess.check_output(
        ["git", "-c", "core.autocrlf=input", "status", "--porcelain",
         "--untracked-files=normal"], cwd=root, text=True).strip())
    files = {name: sha256((root / name).read_bytes().replace(b"\r\n", b"\n"))
             for name in SOURCE_FILES}
    # Pin both paths and bytes, making provenance portable across line-ending
    # conversions while recording a dirty source build truthfully.
    tree = "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items())).encode()
    return {"source_commit": source, "working_tree_dirty": dirty,
            "source_tree_sha256": sha256(tree), "source_files": files}


def guide() -> bytes:
    return b"""# USB-safe ESP32 partition bridge set

Six chip/capacity profiles: original ESP32 4/8 MiB, ESP32-C3 4 MiB,
and ESP32-S3 4/8/16 MiB. These are intermediate applications, NOT final
MeshCore firmware, bootloaders, merged images, or partition-table binaries.

Use an identity-bound host flasher with the exact original Full migration
package. Do not relabel an older Full app as built from this utility source.
Native S3/C3 bridges keep application USB CDC disabled while writing flash
and return to ROM automatically after restoration settles. Classic ESP32
reports matching-MAC settled UART status before host DTR/RTS bootloader entry;
its USB-UART automatic reset circuit must work. No physical BOOT is required.

The host must verify exact target table, CRC-valid NVS restored/no-pending
markers, current OTA metadata, physical USB identity, original chip MAC, and
the unchanged final image before writing that app inactive-first/active-last.
USB reappearance, elapsed time, or settled status alone is NOT recovery proof.
Keep stable power. Partition-table writes are not power-loss atomic and
unsupported stored files may not survive. No full-chip erase is required.
"""


def verify_set(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError("USB bridge ZIP integrity check failed")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError("invalid USB bridge set format")
        expected_profiles = {(chip, mib * 1048576) for chip, mib in USB_BRIDGE_PROFILES}
        rows = manifest.get("bridges", [])
        if len(rows) != 6 or {(row["chip"], row["flash_bytes"]) for row in rows} != expected_profiles:
            raise ValueError("USB bridge set must contain every reviewed chip/capacity profile exactly once")
        names = set(manifest["files"]) | {"manifest.json", "SHA256SUMS.txt"}
        if set(archive.namelist()) != names or len(archive.namelist()) != len(names):
            raise ValueError("USB bridge set inventory is not exact")
        for name, record in manifest["files"].items():
            data = archive.read(name)
            if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
                raise ValueError("USB bridge set payload hash mismatch")
        sums = "".join(f"{sha256(archive.read(name))}  {name}\n"
                       for name in sorted(names - {"SHA256SUMS.txt"})).encode()
        if archive.read("SHA256SUMS.txt") != sums:
            raise ValueError("USB bridge set checksum inventory mismatch")
        for row in rows:
            chip = row["chip"]
            if (row.get("automatic_rom_return") is not (chip != 0)
                    or row.get("uart_completion_status") is not (chip == 0)
                    or row.get("host_software_bootloader_entry") is not True
                    or row.get("application_usb_cdc") is not False):
                raise ValueError("invalid USB bridge completion capability")
            environment = USB_BRIDGE_PROFILES[chip, row["flash_bytes"] // 1048576]
            validate_usb_bridge(archive.read(row["file"]), {
                "wifi_bridge": environment.removesuffix("_usb"),
                "flash_bytes": row["flash_bytes"],
            })
        return manifest


def package_set(build_dir: Path, output_file: Path, provenance: dict) -> Path:
    if (not re.fullmatch(r"[0-9a-f]{8,40}", provenance.get("source_commit", ""))
            or not isinstance(provenance.get("working_tree_dirty"), bool)
            or not re.fullmatch(r"[0-9a-f]{64}", provenance.get("source_tree_sha256", ""))):
        raise ValueError("USB bridge set requires honest source provenance")
    files = {"README.md": guide()}
    bridges = []
    # Read and validate all six before creating any output path: no partial set.
    for (chip, mib), environment in sorted(USB_BRIDGE_PROFILES.items()):
        image = (build_dir / environment / "firmware.bin").read_bytes()
        flash_bytes = mib * 1048576
        validate_usb_bridge(image, {"wifi_bridge": environment.removesuffix("_usb"),
                                    "flash_bytes": flash_bytes})
        filename = environment + ".bin"
        files[filename] = image
        bridges.append({"chip": chip, "flash_bytes": flash_bytes, "file": filename,
                        "environment": environment, "automatic_rom_return": chip != 0,
                        "uart_completion_status": chip == 0,
                        "host_software_bootloader_entry": True,
                        "application_usb_cdc": False})
    manifest = {"format": FORMAT, **provenance, "bridges": bridges,
                "files": {name: {"bytes": len(data), "sha256": sha256(data)}
                          for name, data in sorted(files.items())}}
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    files["SHA256SUMS.txt"] = "".join(
        f"{sha256(data)}  {name}\n" for name, data in sorted(files.items())).encode()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="usb-bridges-", suffix=".zip",
                                     dir=output_file.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), data)
        verify_set(temporary)
        if output_file.exists():
            if sha256(output_file.read_bytes()) != sha256(temporary.read_bytes()):
                raise ValueError("existing USB bridge set differs; choose a new output file")
        else:
            temporary.replace(output_file)
    finally:
        temporary.unlink(missing_ok=True)
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pio-build-dir", type=Path)
    parser.add_argument("--output-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_dir = resolve_pio_build_dir(args.pio_build_dir)
        result = package_set(build_dir, args.output_file.resolve(), source_provenance())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(f"USB bridge set: {result} ({result.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
