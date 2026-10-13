"""Publish version-pinned firmware downloads at short, real binary URLs."""

import html
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from firmware_shortlinks import download_url, load_manifest, mirror, validate_immutable


MARKER = "<!-- firmware-shortlinks:table -->"


def registry(config):
    return load_manifest(Path(config["docs_dir"]) / "_data/firmware_shortlinks.json")


def on_page_markdown(markdown, page, config, **kwargs):
    if MARKER not in markdown:
        return markdown
    data = registry(config)
    base = config["site_url"].rstrip("/") + "/d/"
    rows = ["<table><thead><tr><th>Firmware</th><th>Short download link</th>"
            "<th>Original release</th></tr></thead><tbody>"]
    for link in data["links"]:
        label = html.escape(link["label"], quote=True)
        alias = base + link["filename"]
        original = download_url(data, link).split("/releases/download/", 1)[0]
        original += "/releases/tag/" + link["releaseTag"]
        rows.append(
            "<tr><td>" + label + "</td><td><a href=\"" + html.escape(alias, quote=True)
            + "\">" + html.escape(link["filename"]) + "</a></td><td><a href=\""
            + html.escape(original, quote=True) + "\">Release</a></td></tr>")
    rows.append("</tbody></table>")
    return markdown.replace(MARKER, "\n".join(rows))


def on_post_build(config, **kwargs):
    data = registry(config)
    previous = os.environ.get("MESHCORE_SHORTLINKS_PREVIOUS")
    if previous:
        validate_immutable(load_manifest(Path(previous)), data)
    cache = Path(os.environ.get(
        "MESHCORE_SHORTLINKS_CACHE",
        str(Path(config.config_file_path).resolve().parent / ".cache/firmware-shortlinks")))
    outputs = mirror(data, Path(config["site_dir"]) / "d", cache)
    logging.getLogger("mkdocs.plugins.firmware_shortlinks").info(
        "Published %d checksum-verified short firmware downloads", len(outputs))
