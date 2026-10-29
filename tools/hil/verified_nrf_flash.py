#!/usr/bin/env python3
"""Check a Pi-connected nRF52's *physical* serial before selecting a flash image.

USB product names are not board identities: several Heltec nRF52 boards expose
the same ``HT-n5262`` product string.  This gate requires a reviewed inventory
entry for the stable chip serial and checks the selected artifact against it.
Run it before either serial DFU or a UF2 copy.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import zipfile
import zlib


def verify(inventory, serial_number, board, artifact_name):
    devices = inventory.get("devices", {})
    serial_key = serial_number.upper()
    device = next((entry for key, entry in devices.items()
                   if key.upper() == serial_key), None)
    if device is None:
        raise ValueError(f"unrecorded USB serial {serial_number}; identify the physical board first")
    actual_board = device["board"]
    if board != actual_board:
        raise ValueError(f"serial {serial_number} is {actual_board}, not {board}")
    artifact = Path(artifact_name).name.lower()
    if artifact.startswith("update-"):
        artifact = artifact[len("update-"):]
    kind = "bootloader" if "_bootloader" in artifact else "firmware"
    allowed = device.get(f"{kind}_prefixes", [])
    if not any(artifact.startswith(prefix.lower() + "_") or
               artifact.startswith(prefix.lower() + "-") for prefix in allowed):
        raise ValueError(f"{artifact_name} is not a {actual_board} {kind} artifact; expected one of {allowed}")
    return actual_board


def verify_port(port_path, serial_number):
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise ValueError("pyserial is required to verify the connected USB port") from exc
    expected = os.path.realpath(port_path)
    matches = [port for port in list_ports.comports()
               if os.path.realpath(port.device) == expected]
    if len(matches) != 1:
        raise ValueError(f"USB port {port_path} is absent or ambiguous")
    observed = (matches[0].serial_number or "").upper()
    if observed != serial_number.upper():
        raise ValueError(f"USB port {port_path} has serial {observed!r}, expected {serial_number}")


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate manifest key {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value):
    raise ValueError(f"invalid manifest JSON constant {value}")


def verify_application_zip(artifact):
    """Reject every DFU component except one application and its init packet.

    This checks the package's DFU selection, not firmware authenticity. The
    existing reviewed board/artifact identity gate remains mandatory too.
    Nothing is extracted and no hardware is queried by this check.
    """
    try:
        with zipfile.ZipFile(artifact) as package:
            entries = package.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) != 3 or len(set(names)) != 3 or "manifest.json" not in names:
                raise ValueError("application-only ZIP must contain exactly manifest.json, one BIN and one DAT")
            for entry in entries:
                if (entry.is_dir() or entry.flag_bits & 1
                        or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                        or stat.S_IFMT(entry.external_attr >> 16) not in {0, stat.S_IFREG}):
                    raise ValueError("application-only ZIP contains an unsupported or unsafe member")
                limit = 1024 * 1024 if entry.filename.lower().endswith(".bin") else 65536
                if entry.file_size <= 0 or entry.file_size > limit:
                    raise ValueError("application-only ZIP members are empty or exceed the size limit")
            document = json.loads(package.read("manifest.json").decode("utf-8"),
                                  object_pairs_hook=_unique_json_object,
                                  parse_constant=_reject_json_constant)
            if not isinstance(document, dict) or set(document) != {"manifest"}:
                raise ValueError("application-only ZIP has an invalid manifest root")
            manifest = document["manifest"]
            if (not isinstance(manifest, dict) or "application" not in manifest
                    or set(manifest) - {"application", "dfu_version"}):
                raise ValueError("application-only ZIP forbids bootloader, SoftDevice and unknown DFU components")
            if "dfu_version" in manifest:
                version = manifest["dfu_version"]
                if (type(version) not in {int, float} or not math.isfinite(version)
                        or version <= 0):
                    raise ValueError("application-only ZIP has an invalid DFU version")
            application = manifest["application"]
            if (not isinstance(application, dict)
                    or not {"bin_file", "dat_file"}.issubset(application)
                    or set(application) - {"bin_file", "dat_file", "init_packet_data"}):
                raise ValueError("application-only ZIP has an invalid application entry")
            if ("init_packet_data" in application
                    and not isinstance(application["init_packet_data"], dict)):
                raise ValueError("application-only ZIP has invalid init-packet metadata")
            selected = []
            for key, extension in (("bin_file", "bin"), ("dat_file", "dat")):
                name = application[key]
                if (not isinstance(name, str)
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\." + extension, name,
                                            flags=re.IGNORECASE)):
                    raise ValueError("application BIN/DAT references must be safe root-level filenames")
                selected.append(name)
            if set(names) != {"manifest.json", *selected}:
                raise ValueError("application-only ZIP members do not match the application BIN/DAT references")
            if package.testzip() is not None:
                raise ValueError("application-only ZIP has a corrupt member")
            return tuple(selected)
    except (zipfile.BadZipFile, UnicodeDecodeError, NotImplementedError, RuntimeError,
            EOFError, zlib.error) as exc:
        raise ValueError(f"invalid or unreadable application-only ZIP: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--serial", required=True, help="Stable USB chip serial")
    parser.add_argument("--board", required=True, help="Reviewed physical board name")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--application-only", action="store_true",
                        help="Require a ZIP with only one application BIN/DAT; reject bootloader/SoftDevice updates")
    parser.add_argument("--port", required=True, help="Current application or DFU serial port")
    args = parser.parse_args(argv)
    try:
        inventory = json.loads(args.inventory.read_text())
        verify(inventory, args.serial, args.board, args.artifact.name)
        if not args.artifact.is_file():
            raise ValueError(f"artifact does not exist: {args.artifact}")
        if args.application_only:
            verify_application_zip(args.artifact)
        verify_port(args.port, args.serial)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"REFUSED: {exc}\n")
    print(f"VERIFIED: {args.serial} = {args.board}; {args.artifact.name}; {args.port}")


if __name__ == "__main__":
    main()
