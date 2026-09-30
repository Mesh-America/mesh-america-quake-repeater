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
    window.previewAudioStats = { plays: 0, rms: 0, tones: [] };
    // Attach before playback: late MediaElementSource wiring is silent in WebKit.
    const context = new AudioContext(), analyser = context.createAnalyser(), gate = context.createGain();
    context.createMediaElementSource(audio).connect(gate); gate.connect(analyser);
    analyser.connect(context.destination);
    const samples = new Float32Array(analyser.fftSize);
    let collectingAfter = Infinity;
    setInterval(() => {
        // Analyser windows can retain the previous play's final samples.
        if (context.currentTime < collectingAfter) return;
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
        previewAudioStats.rms = Math.max(previewAudioStats.rms, rms);
        if (rms > 0.05) {
            let crossings = 0;
            for (let i = 1; i < samples.length; i++) if (samples[i] > 0 && samples[i - 1] <= 0) crossings++;
            previewAudioStats.tones.push({hz: crossings * context.sampleRate / samples.length, ms: audio.currentTime * 1000});
        }
    }, 10);
    audio.addEventListener('playing', () => {
        previewAudioStats.plays++;
        previewAudioStats.rms = 0; previewAudioStats.tones = [];
        const now = context.currentTime;
        collectingAfter = now + Math.max((window.previewMuteStartupMs || 0) / 1000, samples.length / context.sampleRate);
        gate.gain.cancelScheduledValues(now);
        gate.gain.setValueAtTime(window.previewMuteStartupMs ? 0 : 1, now);
        gate.gain.setValueAtTime(1, now + (window.previewMuteStartupMs || 0) / 1000);
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
            self.assertTrue(self.page.evaluate("document.querySelector('audio').paused && document.querySelector('audio').ended"))

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

    def test_cold_output_preserves_all_opening_notes_on_repeated_starts(self):
        # A successful play() does not tell us when a cold output becomes audible.
        # Drop its first 750 ms, enough to lose several unprotected opening notes.
        self.page.evaluate("window.previewMuteStartupMs = 750")
        for attempt in range(3):
            self.page.evaluate("previewAudioStats.rms = 0; previewAudioStats.tones = []")
            self.click("preview")
            self.page.wait_for_function("previewAudioStats.plays === " + str(attempt + 1))
            self.page.wait_for_function("document.querySelector('audio').currentTime >= 0.3")
            self.assertEqual(self.page.locator('[data-role="preview-time"]').inner_text(), "0 / 910 ms")
            self.assertEqual(self.page.locator('[data-role="preview-sound"]').inner_text(), "Warming up audio...")
            self.assertEqual(self.page.evaluate("previewAudioStats.rms"), 0)
            for indicator in ("vibration", "led", "gpio", "screen"):
                self.assertEqual(self.page.locator('[data-indicator="' + indicator + '"]').get_attribute("data-on"), "false")
            self.audible()
            self.page.wait_for_function("document.querySelector('[data-role=preview-sound]').textContent === 'Cycle finished'")
            tones = self.page.evaluate("previewAudioStats.tones")
            # Check every pitch, especially the initial C/E/G and final C6,
            # rather than treating any later sound as proof of a complete tune.
            for hz in (523.25, 659.25, 783.99, 1046.50):
                self.assertTrue(any(abs(tone["hz"] - hz) < 25 for tone in tones), (attempt, hz, tones))
            self.assertEqual(self.page.evaluate("previewAudioStats.plays"), attempt + 1)

    def test_stop_during_warmup_never_plays_the_first_note(self):
        self.click("preview")
        self.page.wait_for_function("document.querySelector('audio').currentTime >= 0.2")
        self.click("preview-stop")
        self.page.wait_for_timeout(1100)
        self.assertEqual(self.page.evaluate("previewAudioStats.rms"), 0)
        self.assertEqual(self.page.locator('[data-role="preview-sound"]').inner_text(), "Stopped")
        self.assertEqual(self.page.locator('[data-role="error"]').inner_text(), "")

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
