#!/usr/bin/env python3
"""Compare the workflow inventory (.github/WORKFLOWS.md) with GitHub and with the files on disk.

Reports, as errors:
  * a workflow GitHub lists that the inventory does not (a new upstream workflow arrives enabled),
  * a workflow file on disk that the inventory does not list,
  * an inventory row whose file is not on disk (and is not a default-setup workflow),
  * a workflow whose live state differs from the expected state in the inventory.

Reports, as warnings only: a file on disk that GitHub does not list yet. GitHub registers a
workflow once the file exists on the default branch, so a file that is only on a pull request branch
legitimately has no live entry.

usage: check_workflow_inventory.py [--repo OWNER/NAME] [--window FILE ...] [--inventory PATH]
  --window  workflows deliberately enabled right now (a Keymind merge window); their expected state
            is treated as "active" for this run.
Needs the gh CLI (read-only calls only).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([a-z_]+)\s*\|")


def parse_inventory(text):
    """{path: expected_state} from the table rows."""
    rows = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def compare(inventory, live, disk, window=()):
    """inventory {path: state}, live {path: state}, disk set of paths. Returns (errors, warnings)."""
    errors, warnings = [], []
    window_paths = {w if "/" in w else f".github/workflows/{w}" for w in window}
    for path, state in sorted(live.items()):
        if path not in inventory:
            errors.append(f"{path} is listed by GitHub ({state}) but missing from the inventory")
    for path in sorted(disk):
        if path not in inventory:
            errors.append(f"{path} is on disk but missing from the inventory")
        elif path not in live:
            warnings.append(f"{path} is on disk but GitHub does not list it yet (not on the default branch?)")
    for path, expected in sorted(inventory.items()):
        if path.startswith("dynamic/"):
            if path not in live:
                errors.append(f"{path} is in the inventory but GitHub does not list it")
        elif path not in disk:
            errors.append(f"{path} is in the inventory but not on disk")
        if path in live:
            want = "active" if path in window_paths else expected
            if live[path] != want:
                errors.append(f"{path}: state is {live[path]}, inventory expects {want}")
    return errors, warnings


def live_workflows(repo):
    cmd = ["gh", "workflow", "list", "--all", "--json", "path,state", "--limit", "100"]
    if repo:
        cmd += ["--repo", repo]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return {w["path"]: w["state"] for w in json.loads(out)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo")
    ap.add_argument("--window", nargs="*", default=[])
    ap.add_argument("--inventory", default=str(ROOT / ".github/WORKFLOWS.md"))
    args = ap.parse_args(argv)
    inventory = parse_inventory(Path(args.inventory).read_text(encoding="utf-8"))
    disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / ".github/workflows").glob("*.y*ml")}
    errors, warnings = compare(inventory, live_workflows(args.repo), disk, args.window)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"::error::{e}")
    print(f"{len(inventory)} inventory rows, {len(disk)} files on disk, "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
