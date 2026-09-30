"""
TDD Test Suite for EVA AI v7.0:
1. Universal Application Support (100+ popular apps, smart Start Menu/Registry discovery, deep in-app actions)
2. Instant Screen Inspection ("посмотри на экран" / "что сейчас открыто на мониторе" in <20ms via Win32 Z-order telemetry)
3. EVA Voice Volume Slider (0%..150% in Backend API, Web Audio GainNode, UI Header + Voice Studio, and voice commands)
"""

import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from server import app
from core.agent import assistant_agent
from tools.app_commands import AppCommandController
from perception.eyes import screen_eyes


class TestEvaV7AppsScreenVolume(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_1_popular_apps_launch_and_in_app_actions(self):
        """EVA must recognize and control popular apps across all categories (OBS, Blender, Photoshop, Telegram, VS Code, etc.)."""
        with patch.object(AppCommandController, "smart_launch_app", return_value=True) as mock_launch, \
             patch("tools.app_commands.GUIController.press_hotkey") as mock_hotkey, \
             patch("tools.app_commands.GUIController.press_key") as mock_key, \
             patch("tools.app_commands.GUIController.type_text") as mock_type:

            # Test launching popular apps across different categories
            for cmd in (
                "открой обс",
                "запусти фотошоп",
                "открой блендер",
                "запусти вс код",
                "открой фигму",
                "запусти ноушен",
                "открой обсидиан",
                "запусти торрент",
                "открой эпик геймс",
                "открой ворд",
                "открой эксель",
            ):
                reply = assistant_agent._try_instant_reflex(cmd)
                self.assertIsNotNone(reply, f"Failed to recognize popular app command: {cmd}")
            self.assertGreaterEqual(mock_launch.call_count, 8)

            # Test universal in-app actions (save, undo, fullscreen, find, type text)
            r_save = assistant_agent._try_instant_reflex("сохрани проект")
            self.assertIsNotNone(r_save)
            mock_hotkey.assert_any_call(["ctrl", "s"])

            r_undo = assistant_agent._try_instant_reflex("отмени действие")
            self.assertIsNotNone(r_undo)
            mock_hotkey.assert_any_call(["ctrl", "z"])

            r_incog = assistant_agent._try_instant_reflex("открой режим инкогнито")
            self.assertIsNotNone(r_incog)
            mock_hotkey.assert_any_call(["ctrl", "shift", "n"])

            r_type = assistant_agent._try_instant_reflex("напечатай привет мир")
            self.assertIsNotNone(r_type)
            mock_type.assert_called()

    def test_2_instant_screen_inspection_under_50ms(self):
        """'посмотри на экран' / 'что сейчас открыто на мониторе' must respond in <50ms without slow vision model lag."""
        with patch.object(screen_eyes, "get_instant_screen_report", return_value={
            "primary_window": "YouTube — Google Chrome",
            "other_windows": ["Steam", "Discord", "Visual Studio Code"],
            "summary": "Сейчас на экране открыт браузер Google Chrome («YouTube»), а на фоне работают Steam, Discord и Visual Studio Code."
        }):
            t0 = time.perf_counter()
            reply = assistant_agent._try_instant_reflex("посмотри на экран")
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            self.assertIsNotNone(reply)
            self.assertLess(elapsed_ms, 50.0, f"Screen inspection took too long: {elapsed_ms:.1f}ms")
            self.assertIn("Google Chrome", reply)
            self.assertIn("Steam", reply)

    def test_3_eva_voice_volume_slider_api_ui_and_voice_commands(self):
        """User must be able to adjust EVA's voice volume via slider API, UI controls, and voice commands."""
        # 1. API endpoint POST /api/voice/eq with volume=65
        res = self.client.post("/api/voice/eq", json={
            "volume": 65,
            "pitch": 0,
            "speed": 1.0,
            "bass": 0,
            "treble": 0
        })
        self.assertEqual(res.status_code, 200)
        eq = res.json().get("eq", {})
        self.assertEqual(eq.get("volume"), 65)

        # 2. Voice command to make EVA quieter/louder ("говори тише", "громкость голоса 80%")
        reply_quiet = assistant_agent._try_instant_reflex("говори тише")
        self.assertIsNotNone(reply_quiet)
        from expression.voice import voice_speaker
        self.assertLess(voice_speaker.get_voice_eq()["volume"], 65)

        reply_set = assistant_agent._try_instant_reflex("громкость голоса 90%")
        self.assertIsNotNone(reply_set)
        self.assertEqual(voice_speaker.get_voice_eq()["volume"], 90)

        # 3. Verify UI has volume slider in header & voice tab, and audio_sync.js has GainNode
        html = self.client.get("/control").text
        self.assertIn('id="header-eva-volume"', html)
        self.assertIn('id="eq-volume"', html)

        audio_js = Path("web/audio_sync.js").read_text(encoding="utf-8")
        self.assertIn("gainNode", audio_js)

        # Reset volume to 100
        self.client.post("/api/voice/eq", json={"volume": 100, "pitch": 0, "speed": 1.0, "bass": 0, "treble": 0})


if __name__ == "__main__":
    unittest.main()
