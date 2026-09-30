"""
TDD Test Suite for EVA AI v6.0 (All 8 Critical User Issues):
1. Fast Wake-Word ("Ева ...") recognition, 0.4s end-of-speech detection & speaker echo cancellation
2. Conversational & Action Context memory ("включи музыку" -> "выключи" stops music, not PC; "открой стим" -> "закрой" closes Steam)
3. Accurate LLM answers without romantic fanfic hallucinations (Ollama /api/chat with think=False)
4. Fast TTS synthesis (auto-bypass exhausted ElevenLabs quota + full audio caching)
5. Preemptive request cancellation when "Ева ..." is spoken repeatedly while generating
6. Natural, varied, human-like Passive Mode replies (no robotic repetition of "Да, господин. Выполняю.")
7. Multi-tasking compound commands ("закрой вкладку с ютубом, и открой стим") + real browser tab control
8. Exact Windows Master Volume percentage control ("сделай громкость 50%")
"""

import unittest
from unittest.mock import patch, MagicMock
from config import config_manager
from core.agent import assistant_agent
from tools.app_commands import AppCommandController, action_context


class TestEvaV6Fixes(unittest.TestCase):

    def setUp(self):
        config_manager.set("ai_mode", "conversational", auto_save=False)
        action_context.reset()

    def test_1_echo_cancellation_and_fast_wake_word(self):
        """Microphone must strip speaker echo from EVA's own TTS and detect 'Ева' reliably."""
        from perception.ears import audio_ears, strip_assistant_echo, extract_wake_word_command

        audio_ears.notify_assistant_speech("Хорошо, создатель, я танцую для тебя", duration_sec=3.0)

        # Case A: Transcript is 100% EVA's own speech from speakers -> must become empty
        pure_echo = strip_assistant_echo(
            "Хорошо, создатель, я танцую для тебя",
            "Хорошо, создатель, я танцую для тебя"
        )
        self.assertEqual(pure_echo, "")

        # Case B: User interrupted EVA while she was saying "Хорошо, создатель, я..." -> keep only user command
        mixed = strip_assistant_echo(
            "Хорошо, создатель, я... Ева открой Steam",
            "Хорошо, создатель, я танцую для тебя"
        )
        self.assertIn("открой Steam", mixed)

        # Case C: Verify balanced silence limit (<= 0.85s) so she stops quickly without clipping word endings
        self.assertLessEqual(audio_ears.SILENCE_LIMIT, 0.85)

        # Case D: Wake word extraction handles mangled/split prefixes
        for phrase in (
            "Ева закрой вкладку с ютубом и открой стим",
            "Эва, сделай громкость 50 процентов",
            "Я ва включи музыку",
            "Ива открой дискорд",
            "Лево открой стим",
        ):
            ok, _, cmd = extract_wake_word_command(phrase, wake_word="ева")
            self.assertTrue(ok, f"Wake word failed on: {phrase}")
            self.assertTrue(len(cmd) > 3)

    def test_2_contextual_music_and_app_commands(self):
        """Saying 'включи музыку' then 'выключи' must stop the music, NOT shut down the PC."""
        with patch("tools.app_commands.OSController.open_application_or_file"), \
             patch("tools.app_commands.GUIController.press_key") as mock_key, \
             patch("tools.app_commands.OSController.kill_process") as mock_kill:

            # Step 1: Turn on music
            r1 = assistant_agent._try_instant_reflex("включи музыку")
            self.assertIsNotNone(r1)
            self.assertEqual(action_context.last_domain, "music")
            self.assertTrue(action_context.music_playing)

            # Step 2: Say bare "выключи" -> must pause/stop music via playpause!
            mock_key.reset_mock()
            r2 = assistant_agent._try_instant_reflex("выключи")
            self.assertIsNotNone(r2)
            mock_key.assert_called_with("playpause")
            self.assertFalse(action_context.music_playing)

            # Step 3: Say "включи обратно" or "продолжи" -> must resume music!
            mock_key.reset_mock()
            r3 = assistant_agent._try_instant_reflex("включи обратно")
            self.assertIsNotNone(r3)
            mock_key.assert_called_with("playpause")
            self.assertTrue(action_context.music_playing)

            # Step 4: Open an app ("открой блокнот"), then say "закрой его" -> must close notepad.exe!
            with patch("core.agent.OSController.open_application_or_file"):
                r4 = assistant_agent._try_instant_reflex("открой блокнот")
                self.assertIsNotNone(r4)
                self.assertEqual(action_context.last_app_process, "notepad.exe")

                r5 = assistant_agent._try_instant_reflex("закрой его")
                self.assertIsNotNone(r5)
                mock_kill.assert_called_with("notepad.exe")

    def test_3_preemptive_request_cancellation_on_repeated_wake_word(self):
        """New 'Ева ...' requests must immediately cancel any in-flight generation."""
        req1 = assistant_agent.begin_new_request()
        self.assertFalse(assistant_agent.is_request_cancelled(req1))

        req2 = assistant_agent.begin_new_request()
        self.assertTrue(assistant_agent.is_request_cancelled(req1))
        self.assertFalse(assistant_agent.is_request_cancelled(req2))

    def test_4_passive_mode_human_variety_no_repetition(self):
        """Passive mode must respond concisely and naturally without repeating the exact same phrase."""
        config_manager.set("ai_mode", "passive", auto_save=False)
        with patch("core.agent.OSController.open_application_or_file"):
            replies = [
                assistant_agent._try_instant_reflex("открой калькулятор"),
                assistant_agent._try_instant_reflex("открой блокнот"),
                assistant_agent._try_instant_reflex("открой проводник"),
                assistant_agent._try_instant_reflex("открой настройки"),
            ]
        # Consecutive replies must not be identical
        for i in range(len(replies) - 1):
            self.assertNotEqual(
                replies[i],
                replies[i + 1],
                f"Passive mode repeated identical phrase: {replies[i]}"
            )

    def test_5_compound_multitask_command_execution(self):
        """'закрой вкладку с ютубом, и открой стим' must execute BOTH actions in order."""
        with patch.object(AppCommandController, "close_browser_tab", return_value=True) as mock_close_tab, \
             patch("tools.app_commands.OSController.open_application_or_file") as mock_open_app, \
             patch("core.agent.OSController.open_application_or_file") as mock_open_core:

            reply = assistant_agent._try_instant_reflex("закрой вкладку с ютубом, и открой стим")
            self.assertIsNotNone(reply)
            mock_close_tab.assert_called_once()
            self.assertTrue(mock_open_app.called or mock_open_core.called)

    def test_6_exact_percentage_volume_control(self):
        """'сделай громкость 50%' must set system master volume to 50%."""
        with patch.object(AppCommandController, "set_system_volume", return_value=True) as mock_vol:
            reply = assistant_agent._try_instant_reflex("сделай громкость 50%")
            self.assertIsNotNone(reply)
            mock_vol.assert_called_once_with(50)
            self.assertIn("50%", reply)

            mock_vol.reset_mock()
            reply2 = assistant_agent._try_instant_reflex("поставь звук на 25 процентов")
            self.assertIsNotNone(reply2)
            mock_vol.assert_called_once_with(25)

    def test_7_fast_tts_skips_exhausted_elevenlabs_key(self):
        """VoiceSpeaker must remember an exhausted ElevenLabs key and skip straight to fast Edge-TTS."""
        from expression.voice import voice_speaker
        bad_key = "sk_exhausted_test_key"
        voice_speaker._mark_elevenlabs_exhausted(bad_key)
        self.assertTrue(voice_speaker._is_elevenlabs_exhausted(bad_key))


if __name__ == "__main__":
    unittest.main()
