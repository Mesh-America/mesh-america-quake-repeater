#!/usr/bin/env python3
"""Assemble the Quake Repeater documentation site and build it with MkDocs.

The documents themselves stay in docs/ (where the rest of the repository links to them). This
copies the ones that belong on the Mesh America site, together with the hand-written pages in
quake-docs/, into .quake-site/, then runs `mkdocs build --strict -f mkdocs-quake.yml`. Links from
a copied page to a docs/ file that is not on the site (a Keymind page, say) are pointed at the
file on GitHub instead of breaking.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_SRC = ROOT / ".quake-site"
REPO_BLOB = "https://github.com/Mesh-America/mesh-america-quake-repeater/blob/main/docs/"

# Documents taken from docs/ unchanged (apart from the link fix-up).
FROM_DOCS = [
    "earthquake-alerts.md",
    "reading-the-sensor.md",
    "clock-floor.md",
    "d7s-integration.md",
    "d7s-measurement-contract.md",
]

LINK = re.compile(r"\]\(([A-Za-z0-9_.\-]+\.md)((?:#[^)]*)?)\)")


def main() -> int:
    if SITE_SRC.exists():
        shutil.rmtree(SITE_SRC)
    SITE_SRC.mkdir()

    for page in (ROOT / "quake-docs").glob("*.md"):
        shutil.copy(page, SITE_SRC / page.name)

    on_site = {p.name for p in SITE_SRC.glob("*.md")} | set(FROM_DOCS)
    for name in FROM_DOCS:
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")

        def fix(m: re.Match) -> str:
            target = m.group(1)
            if target in on_site:
                return m.group(0)
            return f"]({REPO_BLOB}{target}{m.group(2)})"

        (SITE_SRC / name).write_text(LINK.sub(fix, text), encoding="utf-8")

    cmd = [sys.executable, "-m", "mkdocs", "build", "--strict", "-f", str(ROOT / "mkdocs-quake.yml")]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
