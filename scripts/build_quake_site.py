#!/usr/bin/env python3
"""Assemble the Quake Repeater documentation site and build it with VitePress.

The documents themselves stay in docs/ (where the rest of the repository links to them). This
copies the ones that belong on the Mesh America site, together with the hand-written pages in
quake-docs/, into quake-site/src/, then runs `vitepress build` in quake-site/. Run `npm ci` in
quake-site/ first. The result is quake-site/.vitepress/dist.

Two fix-ups are applied to the copied documents, because they are written for GitHub and not for a
Vue-based site generator:
- A link to a docs/ file that is not on the site (a Keymind page, say) is pointed at the file on
  GitHub, so it does not break.
- Angle-bracket placeholders outside code, such as <epoch seconds>, would be read as HTML/Vue
  tags, so they are escaped.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "quake-site"
SRC = SITE / "src"
REPO_BLOB = "https://github.com/Mesh-America/mesh-america-quake-repeater/blob/main/docs/"

# Documents taken from docs/ (apart from the fix-ups above).
FROM_DOCS = [
    "earthquake-alerts.md",
    "reading-the-sensor.md",
    "placement-and-testing.md",
    "clock-floor.md",
    "d7s-integration.md",
    "d7s-measurement-contract.md",
]

LINK = re.compile(r"\]\(([A-Za-z0-9_.\-]+\.md)((?:#[^)]*)?)\)")
FENCE = re.compile(r"^(```|~~~)")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
# A "<" that starts a placeholder like <epoch seconds> or <#name|off> (not a real tag, URL or comment).
PLACEHOLDER = re.compile(r"<(?![/!]|https?:|[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z-]+=|\s*/?>))([^<>\n]*)>")


def escape_placeholders(text: str) -> str:
    out, in_fence = [], False
    for line in text.split("\n"):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        # Leave inline code alone: split on it, escape only the prose between.
        pieces, last = [], 0
        for m in INLINE_CODE.finditer(line):
            pieces.append(PLACEHOLDER.sub(r"&lt;\1&gt;", line[last : m.start()]))
            pieces.append(m.group(0))
            last = m.end()
        pieces.append(PLACEHOLDER.sub(r"&lt;\1&gt;", line[last:]))
        out.append("".join(pieces))
    return "\n".join(out)


def main() -> int:
    if SRC.exists():
        shutil.rmtree(SRC)
    SRC.mkdir()

    # Static files (logos, favicon, screenshots) live in quake-site/public; VitePress wants them
    # beside the pages.
    shutil.copytree(SITE / "public", SRC / "public")

    for page in (ROOT / "quake-docs").glob("*.md"):
        shutil.copy(page, SRC / page.name)

    on_site = {p.name for p in SRC.glob("*.md")} | set(FROM_DOCS)
    for name in FROM_DOCS:
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")

        def fix(m: re.Match) -> str:
            target = m.group(1)
            if target in on_site:
                return m.group(0)
            return f"]({REPO_BLOB}{target}{m.group(2)})"

        text = LINK.sub(fix, text)
        (SRC / name).write_text(escape_placeholders(text), encoding="utf-8")

    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    return subprocess.call([npx, "vitepress", "build"], cwd=SITE)


if __name__ == "__main__":
    sys.exit(main())
