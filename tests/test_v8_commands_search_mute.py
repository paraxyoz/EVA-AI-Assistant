"""
TDD Test Suite for EVA AI v8.0:
1. 6-Slot SVG Icon Rail Sidebar (Logo top, Chat/Commands/Studio/Settings middle, GitHub bottom)
2. Microphone Mute Toggle (completely blocks wake-word & voice capture when muted)
3. Hierarchical Folder Tree of Commands (PC vs 3D Model vs App Packs) + Multi-Step Action Chains
   (e.g., "доброе утро" -> 1. Browser, 2. URLs, 3. Windows Volume 50%; "уютный вечер"; "начать стрим")
4. Mouse & Keyboard Action Macro Recorder (record & replay recorded mouse clicks and keystrokes)
5. Command Confirmation Popup with Countdown Timer (cancels if rejected or timed out)
6. Multi-Command Execution in a single request
7. Real-Time Web Search (weather, sports, news, factual queries)
8. Ready-Made App Command Packs (Spotify, Photoshop, GitHub, Steam, OBS, Discord, Figma, Chrome)
"""

import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient


class TestEvaV8Features(unittest.TestCase):

    def test_1_icon_rail_6_sections_and_commands_layout(self):
        """UI must have the 6-button SVG icon rail (Logo, Chat, Commands, Studio, Settings, GitHub) and Commands Tree."""
        from server import app
        client = TestClient(app)
        res = client.get("/control")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 6 rail elements: Logo top, 4 nav tabs middle, GitHub bottom
        self.assertIn('id="rail-logo-btn"', html)
        self.assertIn('data-tab="tab-chat"', html)
        self.assertIn('data-tab="tab-commands"', html)
        self.assertIn('data-tab="tab-wardrobe"', html)
        self.assertIn('data-tab="tab-settings"', html)
        self.assertIn('id="btn-github-repo"', html)

        # Commands page elements: large gray tree container + "Новая команда" button + PC / 3D separation
        self.assertIn('id="commands-tree-container"', html)
        self.assertIn('id="btn-open-new-cmd-modal"', html)
        self.assertIn('data-tree-scope="pc"', html)
        self.assertIn('data-tree-scope="avatar"', html)
        self.assertIn('data-tree-scope="packs"', html)

        # Confirmation modal with countdown
        self.assertIn('id="cmd-confirm-modal"', html)
        # Mic mute button
        self.assertIn('id="btn-mic-mute"', html)

    def test_2_microphone_mute_blocks_eva_hearing(self):
        """When microphone is muted, EVA must not react to voice or wake-words until unmuted."""
        from perception.ears import audio_ears
        from server import app

        client = TestClient(app)
        res_mute = client.post("/api/mic/mute", json={"muted": True})
        self.assertEqual(res_mute.status_code, 200)
        self.assertTrue(res_mute.json()["muted"])
        self.assertTrue(audio_ears.is_muted)

        # While muted, manual listen should refuse to activate
        active = audio_ears.toggle_manual_listen()
        self.assertFalse(active)

        # Unmute
        res_unmute = client.post("/api/mic/mute", json={"muted": False})
        self.assertEqual(res_unmute.status_code, 200)
        self.assertFalse(res_unmute.json()["muted"])
        self.assertFalse(audio_ears.is_muted)

    def test_3_folder_tree_and_multistep_chain_execution(self):
        """User can create a multi-step command ('доброе утро') in a folder and execute all steps in sequence."""
        from tools.app_commands import custom_commands_store
        from core.agent import assistant_agent
        from config import config_manager

        config_manager.set("ai_mode", "conversational", auto_save=False)

        # Create multi-step command "доброе утро тест"
        cmd = custom_commands_store.add_command(
            trigger="доброе утро тест",
            name="Доброе утро (Тест)",
            folder="Утренние и вечерние сценарии",
            scope="pc",
            steps=[
                {"action_type": "open_app", "target": "chrome"},
                {"action_type": "open_url", "target": "https://youtube.com, https://github.com"},
                {"action_type": "set_volume", "target": "50"},
            ],
            response="Доброе утро! Запустила браузер, открыла сайты и выставила громкость на 50%.",
            require_confirmation=False,
        )

        try:
            with patch("tools.app_commands.AppCommandController.smart_launch_app", return_value=True) as mock_launch, \
                 patch("tools.app_commands.webbrowser.open") as mock_web, \
                 patch("tools.os_control.OSController.set_system_volume", return_value=50) as mock_vol:

                reply = assistant_agent._try_instant_reflex("Ева, доброе утро тест")
                self.assertIsNotNone(reply)
                self.assertIn("50%", reply)
                self.assertTrue(mock_launch.called)
                self.assertEqual(mock_web.call_count, 2)
                mock_vol.assert_called_with(50)
        finally:
            custom_commands_store.delete_command(cmd["id"])

    def test_4_confirmation_popup_with_timeout_cancel_and_approve(self):
        """Commands with require_confirmation=True must wait for user approval and abort on cancel or timeout."""
        from tools.app_commands import custom_commands_store
        from server import app

        cmd = custom_commands_store.add_command(
            trigger="опасный стрим тест",
            name="Начать стрим с подтверждением",
            folder="Управление OBS",
            scope="pc",
            steps=[
                {"action_type": "open_app", "target": "obs"},
                {"action_type": "open_url", "target": "https://twitch.tv"},
            ],
            response="Стрим запущен!",
            require_confirmation=True,
            confirm_timeout_sec=2,
        )

        try:
            with patch("tools.app_commands.AppCommandController.smart_launch_app", return_value=True) as mock_launch:
                # 1. Triggering the command should NOT execute immediately; it returns a pending confirmation message
                res_msg = custom_commands_store.match_and_execute("опасный стрим тест")
                self.assertIsNotNone(res_msg)
                self.assertFalse(mock_launch.called)
                pending = custom_commands_store.get_pending_confirmations()
                self.assertEqual(len(pending), 1)
                conf_id = pending[0]["confirm_id"]

                # 2. Cancelling the confirmation aborts execution
                client = TestClient(app)
                cancel_res = client.post(f"/api/custom_commands/confirm/{conf_id}", json={"approved": False})
                self.assertEqual(cancel_res.status_code, 200)
                self.assertTrue(cancel_res.json()["cancelled"])
                self.assertFalse(mock_launch.called)

                # 3. Trigger again and approve before timeout -> executes steps!
                custom_commands_store.match_and_execute("опасный стрим тест")
                pending2 = custom_commands_store.get_pending_confirmations()
                conf_id2 = pending2[0]["confirm_id"]
                approve_res = client.post(f"/api/custom_commands/confirm/{conf_id2}", json={"approved": True})
                self.assertEqual(approve_res.status_code, 200)
                self.assertTrue(approve_res.json()["executed"])
                self.assertTrue(mock_launch.called)
        finally:
            custom_commands_store.delete_command(cmd["id"])

    def test_5_mouse_and_keyboard_macro_recorder(self):
        """MacroRecorder must save recorded mouse/keyboard events to JSON and replay them inside a command step."""
        from tools.macro_recorder import macro_recorder
        from tools.app_commands import custom_commands_store

        macro = macro_recorder.save_macro(
            name="Тестовый клик и хоткей",
            events=[
                {"type": "mouse_click", "button": "left", "x": 500, "y": 400, "dt": 0.05},
                {"type": "key_tap", "key": "space", "dt": 0.05},
            ]
        )
        self.assertIn("id", macro)

        cmd = custom_commands_store.add_command(
            trigger="выполни макрос тест",
            name="Тест макроса",
            folder="Мои макросы",
            scope="pc",
            steps=[
                {"action_type": "macro_play", "target": macro["id"]}
            ],
            response="Макрос выполнен!"
        )
        try:
            with patch.object(macro_recorder, "play_macro", return_value=True) as mock_play:
                reply = custom_commands_store.match_and_execute("выполни макрос тест")
                self.assertEqual(reply, "Макрос выполнен!")
                mock_play.assert_called_once_with(macro["id"])
        finally:
            custom_commands_store.delete_command(cmd["id"])
            macro_recorder.delete_macro(macro["id"])

    def test_6_web_search_weather_and_facts(self):
        """WebSearchEngine must answer weather and real-time search queries."""
        from tools.web_search import web_search_engine

        self.assertTrue(web_search_engine.is_search_intent("какая сейчас погода в Москве"))
        self.assertTrue(web_search_engine.is_search_intent("кто выиграл на последнем матче фифа"))
        self.assertTrue(web_search_engine.is_search_intent("найди в интернете курс биткоина"))

        with patch.object(web_search_engine, "get_weather_report", return_value="Сейчас в Москве +18°C, ясно, ветер 3 м/с."):
            ans = web_search_engine.try_instant_answer("Ева, какая сейчас погода в Москве")
            self.assertIsNotNone(ans)
            self.assertIn("+18°C", ans)

    def test_7_builtin_folder_tree_and_app_packs(self):
        """GET /api/commands/tree must return structured folders for PC, 3D Avatar, and App Packs (Spotify, Photoshop, OBS, GitHub, Figma, Discord, Steam)."""
        from server import app
        client = TestClient(app)
        res = client.get("/api/commands/tree")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        folders = data["folders"]
        folder_names = " ".join(f["title"].lower() for f in folders)
        for expected in ("chrome", "spotify", "obs", "steam", "photoshop", "figma", "github", "discord", "3d"):
            self.assertIn(expected, folder_names)


if __name__ == "__main__":
    unittest.main()
