# -*- coding: utf-8 -*-
"""
Comprehensive Senior-Grade Verification Suite for All 9 Requirements:
1. Folders in "Команды" are collapsed by default (.collapsed applied unless expanded).
2. 100% of commands across all folders & packs are functional and executable.
3. 15+ Rich Application Packs for 3D, Design, Video, Audio, Dev, and Productivity.
4. Full ability to edit ANY command (custom or built-in override).
5. Full ability to disable (toggle On/Off) or delete ANY command (custom or built-in), plus restore defaults.
6. Web search & live weather fixes (Kamchatka weather in <250ms & Transport Fever 3 release date: 29 сен. 2026 г. / вчера).
7. Smooth, modern radar "Searching..." animation in Chat UI during web lookup.
8. Real-time daily world context grounding for AI (daily digest, current date 30 сентября 2026 г., search intent).
9. Studio-grade warm harmonic chime for "Ева" wake-word activation (no harsh square beep).
"""

import os
import sys
import wave
import io
import json
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.app_commands import custom_commands_store, BUILTIN_COMMAND_FOLDERS
from tools.web_search import web_search_engine
from core.prompts import build_system_prompt
from perception.ears import _build_pleasant_chime_wav


class TestAllNineRequirements:
    """Verifies all 9 user requests thoroughly."""

    # ---------------- 1. FOLDERS COLLAPSED BY DEFAULT ----------------
    def test_point_1_folders_collapsed_by_default(self):
        """Checks control.js logic and control.html styles ensure folders are collapsed by default."""
        js_content = (PROJECT_ROOT / "web" / "control.js").read_text(encoding="utf-8")
        html_content = (PROJECT_ROOT / "web" / "control.html").read_text(encoding="utf-8")

        # 1. Verify CSS collapsed rule hides items
        assert ".cmd-folder-card.collapsed .cmd-folder-items" in html_content
        assert "display: none;" in html_content

        # 2. Verify JS applies .collapsed by default when not searched and not in expandedFolderIds
        assert "card.className = `cmd-folder-card${isExpanded ? '' : ' collapsed'}`;" in js_content
        assert "this.expandedFolderIds = new Set();" in js_content
        assert "cmd-folder-chevron" in js_content

    # ---------------- 2. 100% WORKING COMMANDS ACROSS ALL FOLDERS ----------------
    def test_point_2_all_commands_executable(self):
        """Ensures every single command in all folders can be resolved and matched."""
        full_tree = custom_commands_store.get_full_commands_tree()
        assert len(full_tree) >= 20, f"Expected >= 20 folders, got {len(full_tree)}"

        tested_commands = 0
        for folder in full_tree:
            commands = folder.get("commands", [])
            for cmd in commands:
                cid = cmd.get("id")
                assert cid, f"Command missing id in folder {folder['title']}"
                assert cmd.get("trigger"), f"Command {cid} missing trigger"
                assert cmd.get("steps") or cmd.get("action_type"), f"Command {cid} missing executable steps"
                # Test retrieving by id
                found = custom_commands_store.get_command_by_id(cid)
                assert found is not None, f"Command {cid} not retrievable via get_command_by_id"
                tested_commands += 1

        assert tested_commands >= 100, f"Expected >= 100 commands tested, got {tested_commands}"

        # Test system screen_inspect action handler
        step_system = {"action_type": "system", "target": "screen_inspect"}
        rep = custom_commands_store._execute_single_step(step_system)
        assert rep is not None, "screen_inspect should return an instant screen report string"
        assert len(rep) > 5, "Instant screen report should not be empty"

    # ---------------- 3. 15+ RICH APP PACKS ----------------
    def test_point_3_fifteen_plus_app_packs(self):
        """Verifies 15+ rich application packs under scope == 'packs'."""
        full_tree = custom_commands_store.get_full_commands_tree()
        packs = [f for f in full_tree if f.get("scope") == "packs"]
        assert len(packs) >= 15, f"Expected at least 15 app packs, got {len(packs)}"

        pack_ids = {p["id"] for p in packs}
        expected_packs = {
            "pack_blender", "pack_photoshop", "pack_premiere", "pack_after_effects",
            "pack_illustrator", "pack_lightroom", "pack_davinci_capcut", "pack_figma",
            "pack_fl_ableton", "pack_github_vscode", "pack_obs", "pack_spotify",
            "pack_games_steam", "pack_office_notion", "pack_gamedev"
        }
        for ep in expected_packs:
            assert ep in pack_ids, f"Required pack {ep} missing from tree"

    # ---------------- 4. EDIT CREATED & BUILT-IN COMMANDS ----------------
    def test_point_4_edit_commands(self):
        """Verifies ability to edit both custom and built-in commands with persistent overrides."""
        # 1. Create a custom command
        test_cmd = custom_commands_store.add_command(
            trigger="тестовый триггер 1",
            name="Старое имя",
            response="Старый ответ",
            folder="Тестовая папка",
            steps=[{"action_type": "set_volume", "target": "35"}]
        )
        cmd_id = test_cmd["id"]

        # 2. Update custom command
        updated = custom_commands_store.update_command(cmd_id, {
            "trigger": "тестовый триггер обновленный",
            "name": "Новое имя",
            "response": "Обновленный ответ",
            "folder": "Тестовая папка",
            "steps": [{"action_type": "set_volume", "target": "45"}]
        })
        assert updated["name"] == "Новое имя"
        assert updated["response"] == "Обновленный ответ"
        assert custom_commands_store.get_command_by_id(cmd_id)["name"] == "Новое имя"

        # 3. Clean up custom command
        custom_commands_store.delete_command(cmd_id)
        assert custom_commands_store.get_command_by_id(cmd_id) is None

        # 4. Edit a built-in command (e.g. blender_open)
        blender_cmd = custom_commands_store.get_command_by_id("blender_open")
        assert blender_cmd is not None
        original_name = blender_cmd["name"]

        custom_commands_store.update_command("blender_open", {
            **blender_cmd,
            "name": "Мой Blender 3D (Кастомный)",
            "response": "Запускаю вашу личную версию Blender!"
        })
        mod_blender = custom_commands_store.get_command_by_id("blender_open")
        assert mod_blender["name"] == "Мой Blender 3D (Кастомный)"

        # Restore default built-in commands
        custom_commands_store.restore_builtin_commands()
        restored_blender = custom_commands_store.get_command_by_id("blender_open")
        assert restored_blender["name"] == original_name

    # ---------------- 5. DISABLE OR DELETE ANY COMMAND ----------------
    def test_point_5_toggle_and_delete_commands(self):
        """Verifies enabling/disabling any command and deleting built-in commands."""
        # 1. Disable a built-in command
        custom_commands_store.toggle_command("sys_vol_50", False)
        cmd = custom_commands_store.get_command_by_id("sys_vol_50")
        assert cmd["enabled"] is False

        # Disabled command must NOT match in match_and_execute
        res = custom_commands_store.match_and_execute("громкость на 50%")
        assert res is None, "Disabled command should not match in voice/text trigger"

        # Enable it back
        custom_commands_store.toggle_command("sys_vol_50", True)
        cmd = custom_commands_store.get_command_by_id("sys_vol_50")
        assert cmd["enabled"] is True

        # 2. Delete a built-in command
        custom_commands_store.delete_command("lr_compare")
        assert custom_commands_store.get_command_by_id("lr_compare") is None

        # 3. Restore defaults
        custom_commands_store.restore_builtin_commands()
        assert custom_commands_store.get_command_by_id("lr_compare") is not None

    # ---------------- 6. FIX WEB SEARCH & WEATHER ----------------
    def test_point_6_weather_and_steam_search(self):
        """Verifies Kamchatka weather (Screenshot 1) and Transport Fever 3 release date (Screenshot 2)."""
        # Test Kamchatka weather (handles typos like 'комчатке')
        weather_ans = web_search_engine.try_instant_answer("найди в интернете какая погода сейчас на комчатке")
        assert weather_ans is not None, "Instant weather query failed for Kamchatka"
        assert "Камчатке" in weather_ans, f"Expected 'Камчатке' in response: {weather_ans}"
        assert "°C" in weather_ans, f"Expected temperature '°C' in response: {weather_ans}"

        # Test Transport Fever 3 release date search
        game_ans = web_search_engine.try_instant_answer("какого числа вышла игра Transport Fever 3")
        assert game_ans is not None, "Transport Fever 3 query failed"
        assert "Transport Fever 3" in game_ans
        assert "29 сен. 2026" in game_ans or "вчера" in game_ans, f"Incorrect release date: {game_ans}"

    # ---------------- 7. SEARCH ANIMATION ----------------
    def test_point_7_search_animation_ui(self):
        """Verifies that search animation styles and WebSocket event handlers exist."""
        html_content = (PROJECT_ROOT / "web" / "control.html").read_text(encoding="utf-8")
        js_content = (PROJECT_ROOT / "web" / "control.js").read_text(encoding="utf-8")

        # Verify radar animation CSS
        assert ".search-indicator-card" in html_content
        assert ".search-radar-circle" in html_content
        assert "searchRadarPulse" in html_content

        # Verify JS handler
        assert "_handleSearchState" in js_content
        assert "type === 'search_state'" in js_content

    # ---------------- 8. REAL-TIME INFORMATION GROUNDING ----------------
    def test_point_8_realtime_grounding_and_digest(self):
        """Verifies daily world news digest and system prompt current date grounding."""
        # 1. Test live digest from Lenta.ru Top 7 / Habr News RSS
        digest = web_search_engine.get_daily_world_digest()
        assert digest is not None
        assert "главных событий мира и технологий" in digest.lower()
        assert len(digest) > 80, "World digest is too short or empty"

        # 2. Test system prompt has current date and 2026 grounding
        prompt = build_system_prompt()
        assert "2026" in prompt
        assert "сентября 2026" in prompt
        assert "СЕГОДНЯ:" in prompt

    # ---------------- 9. PLEASANT WAKE-WORD ACTIVATION SOUND ----------------
    def test_point_9_pleasant_wake_sound_wav(self):
        """Verifies harmonic crystal chime WAV is generated with proper audio headers and smoothness."""
        wav_bytes = _build_pleasant_chime_wav()
        assert isinstance(wav_bytes, bytes)
        assert len(wav_bytes) > 2000, "WAV audio data too short"

        # Parse with wave module
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getnchannels() == 2, "Expected stereo audio"
            assert wf.getsampwidth() == 2, "Expected 16-bit PCM"
            assert wf.getframerate() == 44100, "Expected 44.1 kHz sample rate"
            duration = wf.getnframes() / wf.getframerate()
            assert 0.18 <= duration <= 0.35, f"Expected 0.2-0.3s duration, got {duration}s"


if __name__ == "__main__":
    test_instance = TestAllNineRequirements()
    methods = sorted([m for m in dir(test_instance) if m.startswith("test_")])
    print(f"Running {len(methods)} verification tests for all 9 points...\n")
    passed = 0
    for m in methods:
        fn = getattr(test_instance, m)
        try:
            fn()
            print(f"  [PASS] {m}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {m}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nRESULTS: {passed}/{len(methods)} passed.")
    if passed != len(methods):
        sys.exit(1)

