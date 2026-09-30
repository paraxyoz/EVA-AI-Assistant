"""
Comprehensive TDD Test Suite for EVA AI v5.0:
1. Session history auto-reset on startup & manual clear API
2. Superior Speech Recognition: bilingual normalization & fuzzy 'Ева' wake-word detection
3. Deep App Automation (Spotify, Steam, Discord, YouTube) & Easy Custom Commands Builder
4. Avatar Visibility Toggle (1-click hide/show 3D & Live2D model window)
5. Two AI Personality Modes ('conversational' vs 'passive' executive mode)
6. Clean UI without duplicate status chips and without redundant 'СВЕРНУТЬ' titlebar button
7. Live2D parameter control & 3D VRM natural procedural idle animations
8. Voice Equalizer (Pitch, Speed, Bass, Treble) in backend TTS & Web Audio API
"""

import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from config import config_manager
from memory.db import memory_db
from server import app, initialize_clean_session
from core.agent import assistant_agent
from core.prompts import build_system_prompt


class TestEvaV5Features(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        config_manager.set("ai_mode", "conversational", auto_save=False)

    def test_initialize_clean_session_clears_messages_but_preserves_facts(self):
        """On every app launch, prompt history must be cleared while user facts remain intact."""
        memory_db.remember_fact("test_cat", "favorite_editor", "VS Code")
        memory_db.log_message("sess-1", "user", "Старый запрос из прошлой сессии")
        memory_db.log_message("sess-1", "assistant", "Старый ответ из прошлой сессии")

        self.assertGreaterEqual(len(memory_db.get_recent_messages(limit=10)), 2)
        initialize_clean_session()
        self.assertEqual(memory_db.get_recent_messages(limit=10), [])

        facts = {f["key"]: f["value"] for f in memory_db.get_all_facts()}
        self.assertEqual(facts.get("favorite_editor"), "VS Code")
        memory_db.forget_fact("favorite_editor")

    def test_clear_history_api_endpoint(self):
        """POST /api/history/clear should wipe conversation history at any time."""
        memory_db.log_message("sess-2", "user", "Тестовое сообщение")
        res = self.client.post("/api/history/clear")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("success"))
        self.assertEqual(memory_db.get_recent_messages(limit=10), [])

    def test_voice_transcript_bilingual_normalization_and_fuzzy_wake_word(self):
        """Speech recognizer should normalize mangled English app/game names and reliably detect 'Ева'."""
        from perception.ears import normalize_voice_transcript, extract_wake_word_command

        norm1 = normalize_voice_transcript("Ева вруби споти фай пожалуйста")
        self.assertIn("spotify", norm1.lower())

        norm2 = normalize_voice_transcript("запусти контр страйк в стиме")
        self.assertIn("cs2", norm2.lower())
        self.assertIn("steam", norm2.lower())

        norm3 = normalize_voice_transcript("открой дискорт и позвони другу")
        self.assertIn("discord", norm3.lower())

        # Wake word fuzzy detection for common Whisper misrecognitions of "Ева"
        for phrase in (
            "Ева открой калькулятор",
            "Эва, открой калькулятор",
            "Дева открой калькулятор",
            "Ива открой калькулятор",
            "Слушай Ева открой калькулятор",
            "Евочка, открой калькулятор",
        ):
            triggered, trig_word, cmd = extract_wake_word_command(phrase, wake_word="ева")
            self.assertTrue(triggered, f"Failed to trigger wake word on: {phrase}")
            self.assertIn("открой калькулятор", cmd.lower())

    def test_deep_app_commands_spotify_steam_discord(self):
        """AppCommandController should execute Spotify, Steam, Discord, and YouTube commands."""
        from tools.app_commands import AppCommandController

        with patch("tools.app_commands.OSController.open_application_or_file") as mock_open, \
             patch("tools.app_commands.GUIController.press_key") as mock_key, \
             patch("tools.app_commands.GUIController.press_hotkey") as mock_hotkey:

            # Spotify play music
            res_spotify = AppCommandController.try_execute("включи музыку в спотифай")
            self.assertIsNotNone(res_spotify)

            # Spotify next track
            res_next = AppCommandController.try_execute("следующий трек")
            self.assertIsNotNone(res_next)
            mock_key.assert_called()

            # Spotify search
            res_search = AppCommandController.try_execute("найди в спотифай Linkin Park")
            self.assertIsNotNone(res_search)

            # Steam launch CS2 / Dota 2
            res_cs = AppCommandController.try_execute("запусти кс 2 в стиме")
            self.assertIsNotNone(res_cs)
            mock_open.assert_any_call("steam://rungameid/730")

            res_dota = AppCommandController.try_execute("запусти доту в стиме")
            self.assertIsNotNone(res_dota)
            mock_open.assert_any_call("steam://rungameid/570")

            # Discord mute mic
            res_disc = AppCommandController.try_execute("выключи микрофон в дискорде")
            self.assertIsNotNone(res_disc)
            mock_hotkey.assert_any_call(["ctrl", "shift", "m"])

    def test_custom_commands_crud_and_instant_execution(self):
        """Users should be able to create simple custom commands via API and trigger them by voice/text."""
        # Create a custom command
        create_res = self.client.post("/api/custom_commands", json={
            "trigger": "режим стрима",
            "action_type": "open_url",
            "target": "https://studio.youtube.com",
            "response": "Включаю режим стрима, удачного эфира!"
        })
        self.assertEqual(create_res.status_code, 200)
        data = create_res.json()
        self.assertTrue(data.get("success"))
        cmd_id = data["command"]["id"]

        # Verify listing
        list_res = self.client.get("/api/custom_commands")
        self.assertEqual(list_res.status_code, 200)
        cmds = list_res.json().get("commands", [])
        self.assertTrue(any(c["id"] == cmd_id for c in cmds))

        # Verify execution through AssistantAgent reflex
        with patch("tools.app_commands.OSController.open_application_or_file") as mock_open:
            reply = assistant_agent._try_instant_reflex("Ева, режим стрима")
            self.assertEqual(reply, "Включаю режим стрима, удачного эфира!")
            mock_open.assert_called_with("https://studio.youtube.com")

        # Cleanup custom command
        del_res = self.client.delete(f"/api/custom_commands/{cmd_id}")
        self.assertEqual(del_res.status_code, 200)

    def test_two_ai_personality_modes_conversational_and_passive(self):
        """J.A.R.V.I.S. mode ('jarvis'/'passive') should produce crisp 'Да, сэр' / 'Выполняю, сэр' replies and use the 'jarvis' baritone voice."""
        from expression.voice import voice_speaker

        with patch("core.agent.OSController.open_application_or_file"), patch("core.agent.OSController.kill_process"):
            config_manager.set("ai_mode", "conversational", auto_save=False)
            reply_conv = assistant_agent._try_instant_reflex("открой блокнот")
            self.assertIn("Блокнот", reply_conv)

            config_manager.set("ai_mode", "jarvis", auto_save=False)
            self.assertEqual(voice_speaker.get_effective_voice_profile(), "jarvis")

            # Greeting in J.A.R.V.I.S. mode must be crisp and never contain 'Приветик' or 'Да, господин'
            reply_greet = assistant_agent._try_instant_reflex("привет")
            self.assertIn("сэр", reply_greet.lower())
            self.assertNotIn("Приветик", reply_greet)
            self.assertNotIn("господин", reply_greet)

            # Action command in J.A.R.V.I.S. mode
            reply_pass = assistant_agent._try_instant_reflex("открой блокнот")
            self.assertIn("сэр", reply_pass.lower())
            self.assertTrue(
                any(p in reply_pass for p in ("Да, сэр", "Выполняю", "Сделано", "Будет сделано")),
                f"Unexpected Jarvis reply: {reply_pass}"
            )

            # Masculine verb form in J.A.R.V.I.S. mode ("Закрыл", never "Закрыла")
            reply_close = assistant_agent._try_instant_reflex("закрой стим")
            self.assertIn("Закрыл", reply_close)
            self.assertNotIn("Закрыла", reply_close)

        prompt_passive = build_system_prompt()
        self.assertIn("J.A.R.V.I.S.", prompt_passive.upper())
        self.assertIn("ПАССИВНЫЙ", prompt_passive.upper())
        config_manager.set("ai_mode", "conversational", auto_save=False)

    def test_avatar_visibility_toggle_api(self):
        """POST /api/avatar/visibility should toggle 3D/Live2D avatar window visibility."""
        res_hide = self.client.post("/api/avatar/visibility", json={"visible": False})
        self.assertEqual(res_hide.status_code, 200)
        self.assertFalse(res_hide.json().get("visible"))
        self.assertFalse(config_manager.get("avatar.show_on_desktop"))

        res_show = self.client.post("/api/avatar/visibility", json={"visible": True})
        self.assertEqual(res_show.status_code, 200)
        self.assertTrue(res_show.json().get("visible"))
        self.assertTrue(config_manager.get("avatar.show_on_desktop"))

    def test_voice_equalizer_settings_and_prosody(self):
        """Voice Equalizer should persist pitch, speed, bass, treble and convert to valid edge-tts prosody."""
        from expression.voice import voice_speaker

        res = self.client.post("/api/voice/eq", json={
            "pitch": 4,
            "speed": 1.15,
            "bass": 3,
            "treble": 2
        })
        self.assertEqual(res.status_code, 200)
        eq = res.json().get("eq", {})
        self.assertEqual(eq.get("pitch"), 4)
        self.assertAlmostEqual(eq.get("speed"), 1.15)

        rate_str, pitch_str = voice_speaker.get_effective_prosody("+5%", "+0Hz")
        self.assertTrue(rate_str.startswith("+") and rate_str.endswith("%"))
        self.assertTrue(pitch_str.startswith("+") and pitch_str.endswith("Hz"))

        # Reset EQ
        self.client.post("/api/voice/eq", json={"pitch": 0, "speed": 1.0, "bass": 0, "treble": 0})

    def test_ui_no_duplicate_badges_and_titlebar_no_minimize_button(self):
        """Control UI should not duplicate AI/Model badges in header, and desktop_app should only have СКРЫТЬ В ФОН."""
        res = self.client.get("/control")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Sidebar telemetry remains, duplicate header chips are removed
        self.assertIn("id=\"sidebar-llm-label\"", html)
        self.assertNotIn("id=\"badge-active-llm\"", html)
        self.assertNotIn("id=\"badge-active-avatar\"", html)

        # New UI sections exist: Custom Commands tab, AI mode toggle, Avatar visibility toggle, Voice Equalizer
        self.assertIn("id=\"tab-commands\"", html)
        self.assertIn("id=\"btn-toggle-avatar-vis\"", html)
        self.assertIn("id=\"select-ai-mode\"", html)
        self.assertIn("id=\"eq-pitch\"", html)
        self.assertIn("id=\"eq-speed\"", html)
        self.assertIn("id=\"eq-bass\"", html)
        self.assertIn("id=\"eq-treble\"", html)

        # Check desktop_app.py has no 'СВЕРНУТЬ' button in CustomTitleBar
        desktop_code = Path("desktop_app.py").read_text(encoding="utf-8")
        self.assertNotIn('QPushButton("СВЕРНУТЬ"', desktop_code)
        self.assertIn('QPushButton("СКРЫТЬ В ФОН"', desktop_code)

        # Check vrm_viewer.js has Live2D pose parameters & procedural VRM micro-animations
        vrm_js = Path("web/vrm_viewer.js").read_text(encoding="utf-8")
        self.assertIn("_applyLive2DPoseParameters", vrm_js)
        self.assertIn("leftUpperArm", vrm_js)
        self.assertIn("lookAt", vrm_js)


if __name__ == "__main__":
    unittest.main()
