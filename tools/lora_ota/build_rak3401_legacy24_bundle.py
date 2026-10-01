#!/usr/bin/env python3
"""Package and independently validate a RAK3401 application-only legacy route.

This builder does not qualify hardware. Its output remains an offline-validated
candidate until the exact chain has passed the MercerWoodMesh radio test.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import rak3401_route_search as search
import build_rak3401_compact_bundle as validation

START_SHA = "4301fc63ebd661c70f9bc40e7eca44d3cb8a358cb3c0075e700d9676a57478cb"
BOOTSTRAP_SHA = "8364257a2b3a219905e870fad6fbb2040a96ca4b4bb7201b2867534cc2b45530"
BOOTSTRAP_PACKAGE_SHA = "74e7195efff24fa2fc75fa0cc7fb15803273b5e7e02c4df2391645ea3e882dfa"
# Built from OTAFIX2.4 release source d73de8372e89b8ef352747c8bc7a1aaeab80fbfe.
# A different host build needs a separately reviewed provenance update.
APPLY_SIM_SHA = "b35d1a5c7a646aee382d6ca14f147408dde5ae690812e286a64e36e3d8a46a96"
ENDPOINT_VERSION = "1.17.1.7"
ENDPOINT_SHA = "c9e63a94f58f881b1853fc5d9d348cd75a6cdd454c5b572341d652a6141e3157"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(command: list[str], log: Path) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    require(completed.returncode == 0, f"Command failed; see {log}")


def validate_manifest(manifest, source: dict, target: dict, block: int) -> None:
    """Bind a generated container to its exact application-only transition."""
    require(not manifest.is_full and not manifest.is_bootloader and manifest.codec_id == 2,
            "Only CRLE in-place application deltas are allowed")
    require(manifest.target_id == search.EXPECTED_TARGET_ID
            and manifest.hw_id.rstrip(b"\0") == b"RAK_3401", "Wrong manifest hardware")
    require(manifest.base_hash.hex().lower() == str(source["body_hash"]).lower(), "Wrong base hash")
    require(manifest.image_hash.hex() == target["sha256"], "Wrong target hash")
    require(manifest.fw_version == search.motalib.pack_version(target["version"]), "Wrong target version")
    require(manifest.image_size == int(target["size"]), "Wrong target size")
    require(manifest.block_size == block, "Wrong signed block geometry")


def validate_workspace(source: dict, target: dict, memory: int, container_size: int,
                       expected_margin: int) -> int:
    stage = search.align_down(search.STAGE_CEILING - container_size)
    margin = stage - search.APP_BASE - memory
    require(memory % 4096 == 0, "Workspace must be page aligned")
    require(margin >= 0 and margin == expected_margin, "Legacy staging overlap")
    require(memory >= search.align_up(max(int(source["size"])+8192, int(target["size"]))),
            "Unsafe workspace")
    return margin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("inventory", "route", "bootstrap", "motatool", "detools", "apply-sim", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Output must be a new directory")
    require(search.sha256_file(args.bootstrap) == BOOTSTRAP_PACKAGE_SHA, "Wrong physical bootstrap package")
    require(search.sha256_file(args.apply_sim) == APPLY_SIM_SHA, "Unqualified bootloader simulator")
    route = json.loads(args.route.read_text(encoding="utf-8"))
    require(route.get("status") == "reachable" and route.get("search_complete") is True,
            "Route must be reachable and complete within its declared inventory")
    images = search.load_inventory(args.inventory)
    require(images[0]["sha256"] == START_SHA, "Wrong deployed starting image")
    require(images[1]["sha256"] == BOOTSTRAP_SHA, "Wrong pinned bootstrap image")
    require(images[-1]["version"] == ENDPOINT_VERSION, "Wrong endpoint version")
    require(images[-1]["sha256"] == ENDPOINT_SHA,
            "Endpoint must be the application-only legacy24 build, not the hybrid stock image")
    nodes = route["nodes"]
    require(all(type(node) is int and 0 <= node < len(images) for node in nodes), "Invalid route node")
    require(nodes[0:2] == [0, 1] and nodes[-1] == len(images)-1,
            "Route does not join the pinned start to the endpoint")
    require(len(route["steps"]) == len(nodes)-1, "Inconsistent route length")
    args.output.mkdir(parents=True)
    output = args.output.resolve()
    (output / "motas").mkdir()
    logs = output / "validation"
    logs.mkdir()
    rows = []
    tools = {}
    with tempfile.TemporaryDirectory(prefix="legacy24-build-") as temporary:
        work = Path(temporary)
        frozen = []
        for record in images:
            payload = Path(record["path"]).read_bytes()
            require(hashlib.sha256(payload).hexdigest() == record["sha256"],
                    "Inventory changed while freezing images")
            path = work / (record["sha256"] + ".bin")
            path.write_bytes(payload)
            frozen.append(path)
        for name in ("motatool", "detools", "apply_sim"):
            original = getattr(args, name).resolve()
            # detools can be a Python launcher whose adjacent venv is required.
            tools[name] = {"path": str(original), "sha256": search.sha256_file(original)}
        for number, (source, target, step) in enumerate(zip(nodes, nodes[1:], route["steps"]), 1):
            require((source, target) == (step["source_node"], step["target_node"]), "Broken chain adjacency")
            require(search.is_forward_progress(images, source, target), "Non-increasing update version")
            require(step["expected_target_version"] == images[target]["version"], "Route version pin mismatch")
            memory = int(str(step["inplace_memory"]), 0)
            block = search.source_block_size(images, source)
            require(block == int(step["block_size"]), "Block size exceeds running receiver contract")
            name = f"step-{number:02d}__{images[source]['version']}-to-{images[target]['version']}.mota"
            package = output / "motas" / name
            if number == 1:
                require(step["reuse_baseline_package"] is True, "Bootstrap must be byte-identical")
                shutil.copyfile(args.bootstrap, package)
                require(package.stat().st_size == 89844, "Wrong bootstrap container size")
            else:
                require(not step["reuse_baseline_package"], "Unexpected bootstrap reuse")
                run([str(args.motatool), "build", "--base", str(frozen[source]),
                     "--fw", str(frozen[target]), "--patch-type", "in-place",
                     "--inplace-memory", hex(memory), "--segment-size", "4096",
                     "--block-size", str(block), "--out", str(package)], logs / f"{number:02d}-build.log")
            run([str(args.motatool), "verify", str(package)], logs / f"{number:02d}-verify.log")
            parsed = search.motalib.parse_container(package.read_bytes())
            manifest = parsed.manifest
            validate_manifest(manifest, images[source], images[target], block)
            require(manifest.image_hash.hex() == step["expected_target_sha256"], "Wrong route target hash")
            require(package.stat().st_size == int(step["expected_container_size"]), "Package size changed from search")
            margin = validate_workspace(images[source], images[target], memory,
                                        package.stat().st_size, int(step["expected_staging_margin"]))
            patch = work / "payload.patch"
            patch.write_bytes(parsed.payload)
            require(validation.patch_geometry(args.detools, patch, name) ==
                    (memory, 4096, int(images[source]["size"]), int(images[target]["size"])), "Patch geometry mismatch")
            base, expected = frozen[source].read_bytes(), frozen[target].read_bytes()
            for fill in (0, 255):
                rebuilt = validation.apply_in_place(args.detools, base, parsed.payload, len(expected), memory, work, f"step-{number}", fill)
                require(rebuilt == expected, "Independent patch reconstruction failed")
            run([str(args.apply_sim), str(frozen[source]), str(package), str(frozen[target])], logs / f"{number:02d}-otafix24.log")
            if "transport" in step:
                row = dict(source=source, target=target, payload=len(parsed.payload),
                           block_size=block, container=package.stat().st_size)
                if search.source_uses_deflate(images, source):
                    row.update(search.measure_transport_size(args.motatool, patch, block))
                    require(row["payload_sha256"] == step["transport"]["payload_sha256"], "Encoded payload changed")
                    require(row["transport_encoder_sha256"] == step["transport"]["encoder_sha256"], "Route used another encoder")
                cost = search.edge_transport_cost(row, images, int(route["transport_accounting"]["relay_hops"]))
                require({"packets", "origin_mesh_bytes", "linear_path_bytes"}.issubset(step["transport"]),
                        "Route lacks transport totals")
                for key, value in step["transport"].items():
                    if key not in ("payload_sha256", "encoder_sha256"):
                        require(cost.get(key) == value, "Transport count changed: " + key)
            rows.append(dict(step=number, from_version=images[source]["version"],
                to_version=images[target]["version"], mota_file="motas/"+name,
                mota_size=package.stat().st_size, mota_sha256=search.sha256_file(package),
                base_body_hash=manifest.base_hash.hex().upper(),
                target_body_hash=str(images[target]["body_hash"]).upper(),
                target_sha256=images[target]["sha256"], target_image_size=manifest.image_size,
                inplace_memory=hex(memory), staging_margin=margin, block_size=block,
                manifest_id=manifest.merkle_root.hex().upper()))
            print(f"Validated {number}/{len(route['steps'])}: {name}", flush=True)
    with (output / "CHAIN.csv").open("w", newline="", encoding="ascii") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (output / "ROUTE.json").write_text(json.dumps(route, indent=2) + "\n", encoding="ascii")
    (output / "VALIDATION.json").write_text(json.dumps(dict(status="offline-validated; hardware qualification pending",
        bootloader="0.9.2-OTAFIX2.4, unchanged", tools=tools, steps=rows), indent=2) + "\n", encoding="ascii")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
