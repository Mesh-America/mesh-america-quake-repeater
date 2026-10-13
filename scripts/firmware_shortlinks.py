#!/usr/bin/env python3
"""Mirror pinned release firmware as immutable, version-specific short URLs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler


REPOSITORY = "mikecarper/MeshCore"
EXTENSIONS = {".bin", ".uf2", ".zip", ".hex", ".mota"}
MAX_ASSET_SIZE = 32 * 1024 * 1024
IMMUTABLE_FIELDS = ("version", "releaseTag", "asset", "sha256", "size")
DELIVERY_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def _version_in(value, version):
    return re.search(r"(?<![0-9.])" + re.escape(version) + r"(?![0-9]|\.[0-9])", value) is not None


def _validate_manifest(manifest):
    if (not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int
            or manifest["schemaVersion"] != 1 or manifest.get("repository") != REPOSITORY):
        raise ValueError("expected schemaVersion 1 and repository " + REPOSITORY)
    links = manifest.get("links")
    if not isinstance(links, list) or not links or len(links) > 128:
        raise ValueError("links must contain 1..128 firmware aliases")
    names = set()
    for link in links:
        if not isinstance(link, dict):
            raise ValueError("firmware link must be an object")
        filename, version = link.get("filename"), link.get("version")
        if (not isinstance(filename, str)
                or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,159}", filename) is None
                or "latest" in filename):
            raise ValueError("alias must be a safe flat filename without latest")
        if (not isinstance(version, str)
                or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?", version) is None
                or not _version_in(filename, version)):
            raise ValueError(filename + ": alias must contain its exact numeric version")
        asset, tag = link.get("asset"), link.get("releaseTag")
        for field, value in (("asset", asset), ("releaseTag", tag)):
            if (not isinstance(value, str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,239}", value) is None
                    or not _version_in(value, version) or "latest" in value.lower()):
                raise ValueError(filename + ": invalid version-specific " + field)
        extension = Path(filename).suffix
        if extension not in EXTENSIONS or Path(asset).suffix != extension:
            raise ValueError(filename + ": alias and source need matching firmware extensions")
        if (not isinstance(link.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", link["sha256"]) is None):
            raise ValueError(filename + ": invalid SHA-256")
        if type(link.get("size")) is not int or not 1 <= link["size"] <= MAX_ASSET_SIZE:
            raise ValueError(filename + ": size must be 1..32 MiB")
        label = link.get("label")
        if (not isinstance(label, str) or not label.strip() or len(label) > 160
                or any(ord(char) < 32 or ord(char) > 126 for char in label)):
            raise ValueError(filename + ": label must be printable ASCII")
        if filename in names:
            raise ValueError("duplicate firmware alias: " + filename)
        names.add(filename)
    return manifest


def load_manifest(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("firmware registry exceeds 1 MiB")
    return _validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def validate_immutable(previous, current):
    """Keep published aliases present and pinned; display labels may change."""
    _validate_manifest(current)
    if previous is None:
        return
    _validate_manifest(previous)
    by_name = {link["filename"]: link for link in current["links"]}
    for old in previous["links"]:
        new = by_name.get(old["filename"])
        if new is None or any(new[field] != old[field] for field in IMMUTABLE_FIELDS):
            raise ValueError("published firmware alias removed or retargeted: " + old["filename"])


def download_url(manifest, link):
    _validate_manifest(manifest)
    if link not in manifest["links"]:
        raise ValueError("link is not in the firmware registry")
    return ("https://github.com/" + REPOSITORY + "/releases/download/"
            + quote(link["releaseTag"], safe="") + "/" + quote(link["asset"], safe=""))


def _delivery_url_allowed(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in DELIVERY_HOSTS
            and parsed.port in (None, 443) and not parsed.username and not parsed.password)


class _ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        if not _delivery_url_allowed(url):
            raise ValueError("release download redirected outside GitHub HTTPS delivery")
        return super().redirect_request(request, response, code, message, headers, url)


def _open_release(url):
    return build_opener(_ReleaseRedirect()).open(url, timeout=30)


def _check_content(head, extension):
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith((b"<!doctype html", b"<html", b"<script", b"window.location", b"location.href")):
        raise ValueError("firmware download contains an HTML or JavaScript redirect")
    if extension in {".bin", ".mota"} and head and all(
            byte in b"\t\r\n" or 32 <= byte <= 126 for byte in head):
        raise ValueError("binary firmware download contains only text")
    if extension == ".uf2" and head[:8] != struct.pack("<II", 0x0A324655, 0x9E5D5157):
        raise ValueError("firmware download lacks a UF2 header")
    if extension == ".zip" and not head.startswith(b"PK\x03\x04"):
        raise ValueError("firmware download lacks an application ZIP header")
    if extension == ".hex" and not text.startswith(b":"):
        raise ValueError("firmware download lacks an Intel HEX header")


def _verify_file(path, link):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != link["size"]:
        raise ValueError("firmware size or file type mismatch: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as source:
        _check_content(source.read(1024), Path(link["filename"]).suffix)
        source.seek(0)
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    if digest.hexdigest() != link["sha256"]:
        raise ValueError("firmware SHA-256 mismatch: " + str(path))


def _download(url, link, destination, opener):
    with opener(url) as response, destination.open("wb") as output:
        if hasattr(response, "geturl") and not _delivery_url_allowed(response.geturl()):
            raise ValueError("release response is outside GitHub HTTPS delivery")
        content_type = getattr(response, "headers", {}).get("Content-Type", "").lower()
        if any(kind in content_type for kind in ("html", "javascript")):
            raise ValueError("release response is HTML or JavaScript")
        total = 0
        while True:
            chunk = response.read(min(65536, link["size"] - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > link["size"]:
                raise ValueError("release download exceeds its pinned size")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    _verify_file(destination, link)


def mirror(manifest, output_dir, cache_dir, opener=None):
    """Validate cache and existing aliases before publishing real firmware files."""
    _validate_manifest(manifest)
    output_dir, cache_dir = Path(output_dir), Path(cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for link in manifest["links"]:
        output = output_dir / link["filename"]
        if output.exists() or output.is_symlink():
            _verify_file(output, link)  # An alias is immutable even across builds.
    outputs = []
    for link in manifest["links"]:
        output = output_dir / link["filename"]
        cached = cache_dir / (link["sha256"] + Path(link["filename"]).suffix)
        try:
            _verify_file(cached, link)
        except ValueError:
            with tempfile.TemporaryDirectory(prefix=".firmware-", dir=cache_dir) as temporary:
                candidate = Path(temporary) / "download"
                _download(download_url(manifest, link), link, candidate, opener or _open_release)
                os.replace(candidate, cached)
        if not output.exists():
            with tempfile.TemporaryDirectory(prefix=".firmware-", dir=output_dir) as temporary:
                candidate = Path(temporary) / "publish"
                shutil.copyfile(cached, candidate)
                _verify_file(candidate, link)
                try:
                    os.link(candidate, output)  # Atomic publication without overwriting a racing alias.
                except FileExistsError:
                    _verify_file(output, link)
        _verify_file(output, link)
        outputs.append(output)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        previous = load_manifest(args.previous) if args.previous is not None else None
        validate_immutable(previous, manifest)
        if not args.check_only:
            if args.output is None or args.cache is None:
                parser.error("--output and --cache are required unless --check-only")
            mirror(manifest, args.output, args.cache)
        print("Firmware shortlinks validated: " + str(len(manifest["links"])))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, "Firmware shortlink validation failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
