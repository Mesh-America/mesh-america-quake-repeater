#!/usr/bin/env python3
"""Verify rendered download URLs and the deployed-link identity guard."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from firmware_shortlinks import load_manifest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


HOOK = module("docs_shortlinks_hook", "docs_firmware_shortlinks.py")
GUARD = module("published_shortlinks_guard", "check_published_firmware_shortlinks.py")
MANIFEST = ROOT / "docs/_data/firmware_shortlinks.json"


class DocsFirmwareShortlinksTests(unittest.TestCase):
    def test_table_uses_site_base_and_versioned_real_file_urls(self):
        config = {"docs_dir": str(ROOT / "docs"), "site_url": "https://example.test/fork/"}
        data = load_manifest(MANIFEST)
        rendered = HOOK.on_page_markdown("Before\n\n" + HOOK.MARKER + "\n\nAfter", None, config)
        self.assertNotIn(HOOK.MARKER, rendered)
        for entry in data["links"]:
            self.assertIn('href="https://example.test/fork/d/' + entry["filename"] + '"', rendered)
            self.assertIn("/releases/tag/" + entry["releaseTag"], rendered)
        self.assertTrue(rendered.startswith("Before"))
        self.assertTrue(rendered.endswith("After"))
        self.assertEqual(HOOK.on_page_markdown("Unrelated page", None, config), "Unrelated page")

    def test_registry_labels_are_plain_text_not_html_or_markdown(self):
        data = load_manifest(MANIFEST)
        data["links"][0]["label"] = '<script>alert("bad")</script>|[bad](javascript:alert(1))'
        with mock.patch.object(HOOK, "registry", return_value=data):
            result = HOOK.on_page_markdown(HOOK.MARKER, None, {"site_url": "https://example.test/"})
        self.assertNotIn("<script>", result)
        self.assertNotIn('href="javascript:', result)
        self.assertIn("&lt;script&gt;", result)

    def test_pages_hook_mirrors_real_files_and_checks_previous_before_publication(self):
        data = load_manifest(MANIFEST)
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / "previous.json"
            previous.write_text(json.dumps(data), encoding="ascii")
            class Config(dict):
                config_file_path = ROOT / "mkdocs.yml"
            config = Config(docs_dir=ROOT / "docs", site_dir=Path(directory) / "site")
            environment = {"MESHCORE_SHORTLINKS_PREVIOUS": str(previous),
                           "MESHCORE_SHORTLINKS_CACHE": str(Path(directory) / "cache")}
            with mock.patch.dict(HOOK.os.environ, environment), mock.patch.object(HOOK, "mirror", return_value=[]) as mirror:
                HOOK.on_post_build(config)
                self.assertEqual(mirror.call_args.args,
                                 (data, Path(directory) / "site/d", Path(directory) / "cache"))
            changed = copy.deepcopy(data)
            changed["links"][0]["sha256"] = "0" * 64
            previous.write_text(json.dumps(changed), encoding="ascii")
            with mock.patch.dict(HOOK.os.environ, environment), mock.patch.object(HOOK, "mirror") as mirror:
                with self.assertRaises(ValueError):
                    HOOK.on_post_build(config)
                mirror.assert_not_called()

    def test_first_pages_deployment_does_not_reuse_an_old_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / "previous.json"
            previous.write_text("stale", encoding="ascii")
            result = subprocess.CompletedProcess([], 2, "", "")
            with mock.patch.object(GUARD.subprocess, "run", return_value=result):
                self.assertFalse(GUARD.check_published(MANIFEST, previous))
            self.assertFalse(previous.exists())

    def test_existing_site_without_registry_is_a_first_shortlink_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / "previous.json"
            with mock.patch.object(GUARD.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "sha", "")) as run, \
                    mock.patch.object(GUARD.subprocess, "check_output", return_value=""):
                self.assertFalse(GUARD.check_published(MANIFEST, previous))
                self.assertEqual(run.call_args_list[1].args[0],
                                 ["git", "fetch", "--depth=1", "--no-tags", "origin", "gh-pages"])
            self.assertFalse(previous.exists())

    def test_published_alias_retarget_and_removal_fail_the_deployment_guard(self):
        original = load_manifest(MANIFEST)
        for changed in (False, True):
            with self.subTest(retarget=changed), tempfile.TemporaryDirectory() as directory:
                current = copy.deepcopy(original)
                if changed:
                    current["links"][0]["sha256"] = "0" * 64
                else:
                    current["links"].pop()
                manifest = Path(directory) / "new.json"
                manifest.write_text(json.dumps(current), encoding="ascii")
                previous = Path(directory) / "previous.json"
                replies = [GUARD.PUBLISHED_PATH + "\n", json.dumps(original).encode("ascii")]
                with mock.patch.object(GUARD.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "sha", "")), \
                        mock.patch.object(GUARD.subprocess, "check_output", side_effect=replies):
                    with self.assertRaises(ValueError):
                        GUARD.check_published(manifest, previous)

    def test_network_failure_is_not_treated_as_an_empty_published_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.CompletedProcess([], 128, "", "Network unavailable")
            with mock.patch.object(GUARD.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "Cannot check"):
                    GUARD.check_published(MANIFEST, Path(directory) / "previous.json")


if __name__ == "__main__":
    unittest.main()
