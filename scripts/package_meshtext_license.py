#!/usr/bin/env python3
"""Ship the adapted Meshtext MIT notice only for actually linked code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from firmware_elf import FirmwareElf

ROOT = Path(__file__).resolve().parents[1]
NOTICE_PATH = ROOT / "licenses/ESPP-Meshtext-MIT.txt"
SIDECAR_SUFFIX = ".meshtext-license.txt"
CAPABILITY = "companion.meshtext.channel_text"
COMPONENT = "espp-meshtext"


def notice_bytes():
    data = NOTICE_PATH.read_bytes()
    if not valid_notice(data):
        raise ValueError("Meshtext MIT source notice is incomplete")
    return data


def valid_notice(data):
    return (0 < len(data) <= 262144 and all(text in data for text in (
        b"Copyright (c) 2022 esp-cpp", b"Permission is hereby granted, free of charge",
        b"included in all", b"copies or substantial portions of the Software",
        b'THE SOFTWARE IS PROVIDED "AS IS"', b"OTHER DEALINGS IN THE", b"SOFTWARE.")))


def linked_symbols(path):
    """Only allocated executable definitions qualify; debug strings do not."""
    if Path(path).read_bytes()[:4] != b"\x7fELF":
        return []  # Existing marker-only test fixtures are not linked ELFs.
    elf = FirmwareElf(path)
    result = []
    for name, (_address, size, index) in elf.symbols.items():
        if size <= 0 or index >= len(elf.sections):
            continue
        section = elf.sections[index]
        if section[1] != 8 and section[2] & 6 == 6:
            result.append(name)
    return sorted(result)


def meshtext_evidence(path):
    symbols = linked_symbols(path)
    # Match the Itanium namespace prefix, not arbitrary names containing MT.
    codec = [name for name in symbols if name.startswith("_ZN4mesh2mt")]
    required = ("_ZN4mesh2mt10encodeTextE", "_ZN4mesh2mt10decodeTextE",
                "_ZN6MyMesh16sendMeshtextTextE", "_ZN6MyMesh19onForeignRadioFrameE",
                "_ZN4mesh10Dispatcher22queueForeignRadioFrameE")
    selected = []
    for operation in required:
        matches = [name for name in symbols if name.startswith(operation)]
        if not matches:
            return codec, []
        selected.append(matches[0])
    return codec, selected if codec else []


def notice_record(stem, data):
    return {"component": COMPONENT, "license": "MIT",
            "file": Path(stem).name + SIDECAR_SUFFIX,
            "sha256": hashlib.sha256(data).hexdigest()}


def sidecar(stem):
    stem = Path(stem)
    return stem.parent / (stem.name + SIDECAR_SUFFIX)


def manifest_record(stem):
    stem = Path(stem)
    manifest = json.loads((stem.parent / (stem.name + ".capabilities.json")).read_text())
    records = [record for record in manifest.get("third_party_notices", [])
               if record.get("component") == COMPONENT]
    if len(records) > 1:
        raise ValueError(f"{stem}: duplicate Meshtext license declarations")
    if not records:
        if CAPABILITY in manifest.get("capabilities", []):
            raise ValueError(f"{stem}: Meshtext capability lacks its MIT notice")
        return None
    record = records[0]
    if (record.get("file") != sidecar(stem).name or record.get("license") != "MIT"
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))):
        raise ValueError(f"{stem}: invalid Meshtext license declaration")
    return record


def validate_artifact_notice(stem):
    record = manifest_record(stem)
    output = sidecar(stem)
    if record is None:
        if output.exists():
            raise ValueError(f"{output}: stale notice for an unaffected firmware")
        return None
    if not output.is_file():
        raise ValueError(f"{output}: missing Meshtext MIT notice")
    data = output.read_bytes()
    if not valid_notice(data) or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError(f"{output}: incomplete or mismatched Meshtext MIT notice")
    return output


def collect_build_notice(directory, stem):
    codec, _chat = meshtext_evidence(Path(directory) / "firmware.elf")
    record = manifest_record(stem)
    if bool(codec) != bool(record):
        raise ValueError("Meshtext license declaration does not match the linked ELF")
    if not codec:
        return validate_artifact_notice(stem)
    data = notice_bytes()
    if record != notice_record(stem, data):
        raise ValueError("Meshtext license declaration does not match this build's source notice")
    output = sidecar(stem)
    if output.exists():
        return validate_artifact_notice(stem)
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
        parser.exit(1, f"Meshtext license qualification failed: {error}\n")


if __name__ == "__main__":
    main()
