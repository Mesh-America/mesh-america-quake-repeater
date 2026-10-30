#!/usr/bin/env python3
"""Carry MeshPocket GUI and font notices beside firmware containing that code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from firmware_elf import FirmwareElf

ROOT = Path(__file__).resolve().parents[1]
NOTICE_PATH = ROOT / "tools/meshpocket_map/PocketGui-NOTICE.txt"
SIDECAR_SUFFIX = ".pocket-gui-license.txt"
COMPONENT = "meshpocket-gui-and-fonts"
LICENSE = "MIT AND BSD-2-Clause AND LicenseRef-Adobe-X11"
FONTS = {"u8g2_font_helvR08_tf", "u8g2_font_helvB08_tf",
         "u8g2_font_helvR10_tf", "u8g2_font_helvB10_tf"}


def valid_notice(data):
    return (0 < len(data) <= 262144 and all(text in data for text in (
        b"jackywashere/MeshCore-Mesh-Pocket-MessageBoard",
        b"Copyright (c) 2025 Scott Powell", b"Permission is hereby granted, free of charge",
        b"copies or substantial portions of the Software", b'THE SOFTWARE IS PROVIDED "AS IS"',
        b"Copyright (c) 2018, olikraus", b"Redistribution and use in source and binary forms",
        b"Copyright 1984-1989, 1994 Adobe Systems Incorporated.",
        b"Copyright 1988, 1994 Digital Equipment Corporation.",
        b"Permission to use, copy, modify, distribute and sell this software",
        b"without express or implied warranty.")))


def notice_bytes():
    data = NOTICE_PATH.read_bytes()
    if not valid_notice(data):
        raise ValueError("MeshPocket GUI/font source notice is incomplete")
    return data


def pocket_gui_evidence(path):
    """Only allocated definitions qualify, never target names or debug strings."""
    if Path(path).read_bytes()[:4] != b"\x7fELF":
        return []
    elf = FirmwareElf(path)
    evidence = []
    for name, (_address, size, index) in elf.symbols.items():
        if size <= 0 or index >= len(elf.sections):
            continue
        section = elf.sections[index]
        if section[1] == 8 or not section[2] & 2:
            continue
        gui = (section[2] & 4 and name.startswith((
            "_ZN4mesh2ui6pocket9PocketGui", "_ZNK4mesh2ui6pocket9PocketGui")))
        if gui or name in FONTS:
            evidence.append(name)
    return sorted(evidence)


def sidecar(stem):
    stem = Path(stem)
    return stem.parent / (stem.name + SIDECAR_SUFFIX)


def notice_record(stem, data):
    return {"component": COMPONENT, "license": LICENSE,
            "file": sidecar(stem).name, "sha256": hashlib.sha256(data).hexdigest()}


def manifest_record(stem):
    stem = Path(stem)
    manifest = json.loads((stem.parent / (stem.name + ".capabilities.json")).read_text())
    records = [record for record in manifest.get("third_party_notices", [])
               if record.get("component") == COMPONENT]
    if len(records) > 1:
        raise ValueError(f"{stem}: duplicate MeshPocket GUI/font notice declarations")
    if not records:
        return None
    record = records[0]
    if (record.get("file") != sidecar(stem).name or record.get("license") != LICENSE
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))):
        raise ValueError(f"{stem}: invalid MeshPocket GUI/font notice declaration")
    return record


def validate_artifact_notice(stem):
    record = manifest_record(stem)
    output = sidecar(stem)
    if record is None:
        if output.exists():
            raise ValueError(f"{output}: stale notice for unaffected firmware")
        return None
    if not output.is_file():
        raise ValueError(f"{output}: missing MeshPocket GUI/font notice")
    data = output.read_bytes()
    if not valid_notice(data) or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError(f"{output}: incomplete or mismatched MeshPocket GUI/font notice")
    return output


def collect_build_notice(directory, stem):
    evidence = pocket_gui_evidence(Path(directory) / "firmware.elf")
    record = manifest_record(stem)
    if bool(evidence) != bool(record):
        raise ValueError("MeshPocket GUI/font notice declaration does not match the linked ELF")
    if not evidence:
        return validate_artifact_notice(stem)
    data = notice_bytes()
    if record != notice_record(stem, data):
        raise ValueError("MeshPocket GUI/font notice declaration does not match the source notice")
    output = sidecar(stem)
    if not output.exists():
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return validate_artifact_notice(stem)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "validate"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--stem", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "collect":
            if args.stem is None:
                parser.error("collect requires --stem")
            collect_build_notice(args.path, args.stem)
        else:
            validate_artifact_notice(args.path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"MeshPocket GUI/font notice qualification failed: {error}\n")


if __name__ == "__main__":
    main()
