#!/usr/bin/env python3
"""Build the canonical MeshCore ESP32 partition LUT from published firmware.

Requires an authenticated gh CLI for release enumeration. Binary prefixes are
public, bounded HTTP range reads. A table checksum authenticates consistency,
not the complete asset: GitHub digests are provenance, not locally verified SHA.
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import struct
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPOSITORIES = (
    "meshcore-dev/MeshCore",
    "IoTThinks/EasySkyMesh",
    "mikecarper/MeshCore",
)
PREFIX_BYTES = 0x9000


def is_merged_asset(name):
    return name.lower().endswith(("-merged.bin", "-cleaninstall.bin"))


def parse_table(prefix):
    """Merged images may start at flash 0 or 0x1000. Reject corrupt tables."""
    for position in (0x8000, 0x7000):
        data = prefix[position:position + 0x1000]
        if not data.startswith(b"\xaa\x50"):
            continue
        entries = []
        end = 0
        for index in range(0, len(data) - 31, 32):
            row = data[index:index + 32]
            if row[:2] == b"\xeb\xeb":
                if row[2:16] != b"\xff" * 14:
                    raise ValueError("Malformed table MD5 record")
                if hashlib.md5(data[:index]).digest() != row[16:32]:
                    raise ValueError("Partition table MD5 mismatch")
                end = index + 32
                break
            if row == b"\xff" * 32:
                end = index
                break
            magic, kind, subtype, offset, size, label, flags = struct.unpack(
                "<HBBII16sI", row
            )
            if magic != 0x50AA or not size or offset < 0x9000:
                raise ValueError("Invalid partition entry")
            if offset + size > 0x1000000:
                raise ValueError("Partition exceeds supported 16 MB flash")
            name = label.split(b"\0", 1)[0].decode("ascii")
            entries.append([kind, subtype, offset, size, name, flags])
        if not end or not entries:
            raise ValueError("Unterminated partition table")
        ordered = sorted(entries, key=lambda entry: entry[2])
        if any(a[2] + a[3] > b[2] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Overlapping partitions")
        if len({(e[0], e[1]) for e in entries if e[0] == 0}) != sum(
            e[0] == 0 for e in entries
        ):
            raise ValueError("Duplicate app subtype")
        slots = [e[3] for e in entries if e[0] == 0 and 0x10 <= e[1] < 0x20]
        dual = len(slots) >= 2 and any(e[0:2] == [1, 0] for e in entries)
        return {
            "partitions": entries,
            "slotBytes": min(slots) if dual else None,
            "dualOta": dual,
            "tableSha256": hashlib.sha256(data[:end]).hexdigest(),
        }
    raise ValueError("No partition table at known merged-image offsets")


def asset_identity(name):
    # Preserve profile suffixes and complete versions; PowerSaving release tags
    # sometimes contain several distinct patch versions.
    name = re.sub(r"-cleanInstall\.bin$", "-merged.bin", name, flags=re.I)
    old_power = re.match(
        r"^repeater-(.+)-(powersaving\d+)-merged\.bin$", name, re.I
    )
    if old_power:
        return old_power.group(1), "repeater", old_power.group(2)
    match = re.match(
        r"^(.+?)_(repeater|repeatr|room_server|room_svr|companion_radio|"
        r"comp_radio|companion|sensor|kiss_modem|terminal_chat)"
        r"(.*?)-((?:v?\d|powersaving).+)-merged\.bin$", name, re.I
    )
    if not match:
        raise ValueError("Unrecognized board/role/version filename")
    board, role, profile, version = match.groups()
    role = {"repeatr": "repeater", "room_svr": "room_server",
            "comp_radio": "companion_radio", "companion": "companion_radio"}.get(
                role.lower(), role.lower())
    profile = profile.replace("-", "_")
    version = re.sub(r"-freshInstall$", "", version, flags=re.I)
    version = re.sub(r"-[0-9a-f]{7,40}$", "", version, flags=re.I)
    return board, role + profile, version


def read_prefix(url):
    if not url.startswith("https://github.com/"):
        raise ValueError("Not a GitHub release asset URL")
    request = urllib.request.Request(
        url, headers={"Range": f"bytes=0-{PREFIX_BYTES - 1}",
                      "User-Agent": "meshcore-partition-catalog/1"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("Insecure asset redirect")
                if response.status == 206 and not response.headers.get(
                    "Content-Range", ""
                ).startswith("bytes 0-"):
                    raise ValueError("Range response starts at wrong offset")
                # Also bounded if a server ignores Range and returns HTTP 200.
                return response.read(PREFIX_BYTES)
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def releases(repository, cache, cached_inventory=False):
    path = cache / (repository.replace("/", "_") + ".json")
    if cached_inventory and path.exists():
        return json.loads(path.read_text())
    for attempt in range(4):
        result = subprocess.run(
            ["gh", "api", f"repos/{repository}/releases?per_page=20",
             "--paginate", "--jq", ".[] | @json"], capture_output=True, text=True
        )
        if result.returncode == 0:
            items = [json.loads(line) for line in result.stdout.splitlines()]
            items = [item for item in items if not item["draft"]]
            path.write_text(json.dumps(items, ensure_ascii=True))
            return items
        if attempt == 3:
            raise RuntimeError(f"Cannot enumerate {repository}: {result.stderr}")
        time.sleep(2 ** attempt)


def inspect_asset(job, cache):
    release_index, asset = job
    record = {"release": release_index, "asset": asset["name"],
              "assetId": asset["id"], "assetSize": asset["size"],
              "assetDigest": asset.get("digest")}
    try:
        board, role, version = asset_identity(asset["name"])
        fingerprint = hashlib.sha256(json.dumps(
            [asset["id"], asset["updated_at"], asset["size"], asset.get("digest")]
        ).encode()).hexdigest()
        path = cache / (fingerprint + ".prefix")
        if path.exists():
            prefix = path.read_bytes()
        else:
            prefix = read_prefix(asset["browser_download_url"])
            path.write_bytes(prefix)
        layout = parse_table(prefix)
        record.update(board=board, role=role, version=version,
                      layout=layout["tableSha256"])
        embedded = re.search(r"-((?:v?\d|powersaving).*)-(?:merged|cleanInstall)\.bin$",
                             asset["name"], re.I)
        record["buildVersion"] = re.sub(
            r"-freshInstall$", "", embedded.group(1), flags=re.I
        ) if embedded else version
        return record, layout, None
    except Exception as error:
        record["reason"] = str(error)
        return None, None, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--copy-to", type=Path, action="append", default=[],
                        help="Also write an identical offline app snapshot")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--cached-inventory", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    catalog = {"schema": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
               "repositories": list(REPOSITORIES), "releases": [], "layouts": {},
               "builds": [], "unresolved": []}
    jobs = []
    for repository in REPOSITORIES:
        items = releases(repository, args.cache_dir, args.cached_inventory)
        print(f"{repository}: {len(items)} published releases", flush=True)
        for release in items:
            assets = release["assets"]
            merged = [a for a in assets if is_merged_asset(a["name"])]
            index = len(catalog["releases"])
            catalog["releases"].append({
                "repository": repository, "tag": release["tag_name"],
                "publishedAt": release["published_at"],
                "assetCount": len(assets), "mergedCount": len(merged),
                "note": None if merged else "No standalone ESP32 merged images",
            })
            jobs.extend((index, asset) for asset in merged)
    print(f"Inspecting {len(jobs)} merged images (cached ranges reused)", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for done, result in enumerate(pool.map(
            lambda job: inspect_asset(job, args.cache_dir), jobs
        ), 1):
            record, layout, error = result
            if error:
                catalog["unresolved"].append(error)
            else:
                catalog["builds"].append(record)
                catalog["layouts"][layout["tableSha256"]] = layout
            if done % 100 == 0 or done == len(jobs):
                print(f"{done}/{len(jobs)} inspected; "
                      f"{len(catalog['unresolved'])} unresolved", flush=True)
    content = json.dumps(catalog, ensure_ascii=True, separators=(",", ":")) + "\n"
    for output in [args.output, *args.copy_to]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    print(f"Wrote {len(catalog['builds'])} builds, {len(catalog['layouts'])} layouts; "
          f"{len(catalog['unresolved'])} unresolved to {args.output}", flush=True)


if __name__ == "__main__":
    main()
