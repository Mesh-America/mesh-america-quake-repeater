#!/usr/bin/env python3
"""Optional browser checks for notification audio. Requires Playwright and its browser.

Use MESHCORE_PREVIEW_BROWSER=webkit to also check the Safari engine, or set
MESHCORE_NOTIFICATION_PREVIEW_URL to check the deployed editor.
"""

import os
from pathlib import Path
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[1]
TAP_AUDIO = """() => {
    const audio = document.querySelector('[data-role="preview-audio"]');
    window.previewAudioStats = { plays: 0, rms: 0 };
    // Attach before playback: late MediaElementSource wiring is silent in WebKit.
    const context = new AudioContext(), analyser = context.createAnalyser();
    context.createMediaElementSource(audio).connect(analyser);
    analyser.connect(context.destination);
    const samples = new Float32Array(analyser.fftSize);
    setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
        previewAudioStats.rms = Math.max(previewAudioStats.rms, rms);
    }, 10);
    audio.addEventListener('playing', () => {
        previewAudioStats.plays++;
        context.resume();
    });
}"""


@unittest.skipUnless(sync_playwright, "Install Playwright to run browser audio checks")
class NotificationAudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        engine = getattr(cls.playwright, os.environ.get("MESHCORE_PREVIEW_BROWSER", "chromium"))
        try:
            cls.browser = engine.launch(headless=True)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        url = os.environ.get("MESHCORE_NOTIFICATION_PREVIEW_URL")
        if url:
            self.page.goto(url, wait_until="networkidle")
        else:
            source = (ROOT / "docs/notifications.md").read_text(encoding="utf-8")
            editor = '<div class="notification-builder"' + source.split('<div class="notification-builder"', 1)[1].split("\n</div>", 1)[0] + "\n</div>"
            self.page.set_content(editor)
            self.page.add_script_tag(path=str(ROOT / "docs/_javascript/notification_builder.js"))
        self.page.evaluate(TAP_AUDIO)

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def click(self, action):
        self.page.locator('[data-action="' + action + '"]').click()

    def audible(self):
        # Inspect decoded audio at the speaker output, not just a successful play() call.
        self.page.wait_for_function("previewAudioStats.rms > 0.05")

    def test_examples_play_audible_melodies_once_without_a_recipient(self):
        for index, example in enumerate(("food", "find", "vip"), 1):
            self.page.locator('[data-example="' + example + '"]').click()
            self.page.evaluate("previewAudioStats.rms = 0")
            self.click("preview")
            self.audible()
            self.assertEqual(self.page.locator('[data-role="error"]').inner_text(), "")
            self.page.wait_for_function("document.querySelector('[data-role=preview-sound]').textContent === 'Cycle finished'")
            self.assertEqual(self.page.evaluate("previewAudioStats.plays"), index)
            self.assertTrue(self.page.evaluate("document.querySelector('audio').paused && !document.querySelector('audio').hasAttribute('src')"))

    def test_timer_waits_for_audio_and_stop_cancels_pending_start(self):
        self.page.evaluate("""() => {
            const original = HTMLMediaElement.prototype.play;
            const originalLoad = HTMLMediaElement.prototype.load;
            let cancelStart;
            HTMLMediaElement.prototype.play = function() {
                return new Promise((resolve, reject) => {
                    const timer = setTimeout(() => {
                        cancelStart = null;
                        original.call(this).then(resolve, reject);
                    }, 1200);
                    cancelStart = () => {
                        clearTimeout(timer); cancelStart = null;
                        reject(new DOMException('Playback stopped', 'AbortError'));
                    };
                });
            };
            // Native pending play() promises reject when load() cancels the source.
            HTMLMediaElement.prototype.load = function() {
                if (cancelStart) cancelStart();
                return originalLoad.call(this);
            };
        }""")
        self.click("preview")
        self.page.wait_for_timeout(1000)  # Longer than the default 910 ms visual cycle.
        self.assertEqual(self.page.locator('[data-role="preview-time"]').inner_text(), "0 / 910 ms")
        self.assertEqual(self.page.evaluate("previewAudioStats.plays"), 0)
        self.assertTrue(self.page.locator('[data-action="preview"]').is_disabled())
        self.assertTrue(self.page.locator('[data-action="preview-stop"]').is_enabled())
        self.audible()
        self.page.wait_for_function("document.querySelector('[data-role=preview-sound]').textContent === 'Cycle finished'")
        self.click("preview")
        self.click("preview-stop")
        self.page.wait_for_timeout(1500)
        self.assertEqual(self.page.evaluate("previewAudioStats.plays"), 1)
        self.assertEqual(self.page.locator('[data-role="error"]').inner_text(), "")
        self.assertEqual(self.page.locator('[data-role="preview-sound"]').inner_text(), "Stopped")
        self.assertTrue(self.page.locator('[data-action="preview"]').is_enabled())

    def test_off_inherit_stop_and_playback_errors(self):
        for value in ("off", "inherit"):
            self.page.locator('input[name="sound"]').fill(value)
            self.click("preview")
            self.page.wait_for_timeout(80)
            self.assertEqual(self.page.evaluate("previewAudioStats.plays"), 0)
            self.assertIn("ms", self.page.locator('[data-role="preview-time"]').inner_text())
            self.click("preview-stop")
        self.page.locator('[data-example="food"]').click()
        self.page.evaluate("""() => {
            window.originalPlay = HTMLMediaElement.prototype.play;
            HTMLMediaElement.prototype.play = () => Promise.reject(new DOMException('Playback blocked', 'NotAllowedError'));
        }""")
        self.click("preview")
        self.assertIn("Playback blocked", self.page.locator('[data-role="error"]').inner_text())
        self.assertEqual(self.page.locator('[data-role="preview-sound"]').inner_text(), "Sound unavailable")
        self.page.evaluate("() => { HTMLMediaElement.prototype.play = originalPlay; }")
        self.click("preview")
        self.audible()
        self.click("preview-stop")
        self.assertTrue(self.page.evaluate("document.querySelector('audio').paused && !document.querySelector('audio').hasAttribute('src')"))
        self.assertEqual(self.page.locator('[data-role="error"]').inner_text(), "")
        self.assertEqual(self.page.locator('[data-indicator="screen"]').get_attribute("data-on"), "false")


if __name__ == "__main__":
    unittest.main()
