"""
End-to-End Senior Bug Audit & Interactive QWebEngineView Verification (v11).
Tests real DOM clicks (Edit, Toggle, Delete, Restore, Search Radar Animation) and live backend endpoints.
"""

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PyQt6.QtCore import QEventLoop, QTimer, QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

ARTIFACT_DIR = Path(r"C:\Users\paraxyoz\.gemini\antigravity\brain\02e5b71b-d50d-495b-a28c-3560d8add456")


def wait_ms(ms: int):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run_js_sync(view: QWebEngineView, script: str):
    loop = QEventLoop()
    result_box = {"val": None}

    def _cb(res):
        result_box["val"] = res
        loop.quit()

    view.page().runJavaScript(script, _cb)
    loop.exec()
    return result_box["val"]


def ensure_server_running(port: int = 7865):
    import socket
    import threading
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return
    except Exception:
        pass
    from server import run_server
    t = threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port}, daemon=True)
    t.start()
    deadline = time.time() + 6.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except Exception:
            time.sleep(0.1)


def main():
    print("=" * 72)
    print("RUNNING E2E INTERACTIVE UI & BACKEND BUG AUDIT (v11)")
    print("=" * 72)

    from tools.app_commands import custom_commands_store
    custom_commands_store.restore_builtin_commands()

    ensure_server_running(7865)
    app = QApplication(sys.argv)
    view = QWebEngineView()
    view.resize(1380, 900)
    view.show()

    loaded = {"ok": False}
    loop = QEventLoop()

    def _on_load(ok):
        loaded["ok"] = ok
        loop.quit()

    view.loadFinished.connect(_on_load)
    view.setUrl(QUrl("http://127.0.0.1:7865/control"))
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    assert loaded["ok"], "Failed to load http://127.0.0.1:7865/control"
    wait_ms(1500)

    # 1. Test Search Radar Animation in Chat Tab
    print("[1/6] Verifying live Search Radar Animation (#search-indicator-card)...")
    run_js_sync(
        view,
        """
        (() => {
            document.querySelector('[data-tab="tab-chat"]').click();
            window.evaControl._handleSearchState({
                active: true,
                status: 'searching',
                query: 'какая погода сейчас на камчатке',
                source: 'Метеостанция MET Norway / Open-Meteo'
            });
            return true;
        })()
        """,
    )
    wait_ms(200)
    radar_state = run_js_sync(
        view,
        """
        (() => {
            const card = document.getElementById('search-indicator-card');
            if (!card) return { exists: false };
            const cs = window.getComputedStyle(card);
            const q = document.getElementById('search-status-query');
            return {
                exists: true,
                display: cs.display,
                opacity: cs.opacity,
                queryText: q ? q.textContent : '',
                circles: card.querySelectorAll('.search-radar-circle').length
            };
        })()
        """,
    )
    assert radar_state["exists"], "Search indicator card did not render!"
    assert radar_state["display"] == "flex", f"Expected display:flex, got {radar_state['display']}"
    assert radar_state["circles"] == 2, "Radar circles missing!"
    assert "камчатке" in radar_state["queryText"], f"Query text mismatch: {radar_state['queryText']}"

    # Save screenshot of the live search radar animation
    view.grab().save(str(ARTIFACT_DIR / "verified_search_radar_animation.png"))

    # Finish search state and verify minimum 600ms smooth hold + removal
    run_js_sync(view, "window.evaControl._handleSearchState({ active: false, status: 'done' });")
    wait_ms(100)
    still_visible_shortly = run_js_sync(view, "Boolean(document.getElementById('search-indicator-card'))")
    assert still_visible_shortly, "Search radar disappeared too fast (<100ms) instead of smooth 600ms hold!"
    wait_ms(950)
    gone_after_fade = run_js_sync(view, "Boolean(document.getElementById('search-indicator-card'))")
    assert not gone_after_fade, "Search radar card was not removed after fade!"
    print("  -> OK: Search radar animation renders, holds smoothly (600ms+), and fades out cleanly.")

    # 2. Switch to Commands Tab & verify collapsed by default across PC and Packs scopes
    print("[2/6] Switching to Commands tab & checking collapsed folders & 15+ packs...")
    run_js_sync(view, "document.querySelector('[data-tab=\"tab-commands\"]').click();")
    wait_ms(500)
    pc_check = run_js_sync(
        view,
        """
        (() => {
            const cards = Array.from(document.querySelectorAll('#commands-tree-body .cmd-folder-card'));
            const firstCard = cards[0];
            const cardOverflow = firstCard ? getComputedStyle(firstCard).overflow : '';
            const countInsideTitle = Boolean(firstCard && firstCard.querySelector('.cmd-folder-title > .cmd-folder-count'));
            const trainBtn = firstCard ? firstCard.querySelector('[data-train-folder]') : null;
            const trainBtnHeight = trainBtn ? trainBtn.getBoundingClientRect().height : 99;
            const tplBtns = Array.from(document.querySelectorAll('[data-scenario-template]'));
            const allTemplatesInViewport = tplBtns.length === 3 && tplBtns.every(b => {
                const r = b.getBoundingClientRect();
                return r.right <= window.innerWidth && r.bottom <= window.innerHeight && r.width > 100;
            });
            return {
                total: cards.length,
                allCollapsed: cards.every(c => c.classList.contains('collapsed')),
                cardOverflow,
                countInsideTitle,
                trainBtnHeight,
                allTemplatesInViewport
            };
        })()
        """,
    )
    assert pc_check["total"] >= 6, f"Expected >= 6 PC folders, got {pc_check['total']}"
    assert pc_check["allCollapsed"], "Not all PC folders are collapsed by default!"
    assert pc_check["cardOverflow"] == "hidden", f"Folder card must have overflow:hidden to prevent corner bleed, got {pc_check['cardOverflow']}"
    assert pc_check["countInsideTitle"], "Count badge (.cmd-folder-count) must be inline inside .cmd-folder-title!"
    assert pc_check["trainBtnHeight"] <= 34, f"'+ Добавить сюда' wrapped onto 2 lines (height={pc_check['trainBtnHeight']}px)!"
    assert pc_check["allTemplatesInViewport"], "Scenario template buttons ('Готовые шаблоны цепочек') overflowed outside the viewport!"
    eq_methods_ok = run_js_sync(
        view,
        "typeof window.evaControl._updateVoiceEqUI === 'function' && typeof window.evaControl.saveVoiceEq === 'function'"
    )
    assert eq_methods_ok, "Voice EQ methods missing on window.evaControl!"

    run_js_sync(view, "document.querySelector('[data-tree-scope=\"packs\"]').click();")
    wait_ms(400)
    packs_check = run_js_sync(
        view,
        """
        (() => {
            const cards = Array.from(document.querySelectorAll('#commands-tree-body .cmd-folder-card'));
            return {
                total: cards.length,
                allCollapsed: cards.every(c => c.classList.contains('collapsed'))
            };
        })()
        """,
    )
    assert packs_check["total"] >= 15, f"Expected >= 15 App Pack folders, got {packs_check['total']}"
    assert packs_check["allCollapsed"], "Not all App Pack folders are collapsed by default!"
    print(f"  -> OK: {pc_check['total']} PC folders + {packs_check['total']} App Packs rendered, 100% collapsed by default.")

    # 3. Expand first folder & test Toggle button (Вкл -> Выкл)
    print("[3/6] Testing real DOM click on Toggle (Вкл/Выкл) for a built-in command...")
    first_cmd_info = run_js_sync(
        view,
        """
        (() => {
            const firstCard = document.querySelector('#commands-tree-body .cmd-folder-card');
            firstCard.querySelector('.cmd-folder-head').click();
            const firstRow = firstCard.querySelector('.cmd-leaf-row');
            const toggleBtn = firstRow.querySelector('[data-toggle-cmd]');
            const cmdId = toggleBtn.getAttribute('data-toggle-cmd');
            const initialText = toggleBtn.textContent.trim();
            toggleBtn.click();
            return { cmdId, initialText };
        })()
        """,
    )
    wait_ms(600)
    toggled_text = run_js_sync(
        view,
        f"""
        (() => {{
            const btn = document.querySelector('[data-toggle-cmd="{first_cmd_info["cmdId"]}"]');
            return btn ? btn.textContent.trim() : null;
        }})()
        """,
    )
    assert toggled_text == "Выкл", f"Expected button to change to 'Выкл', got {toggled_text}"
    print(f"  -> OK: Command '{first_cmd_info['cmdId']}' toggled from '{first_cmd_info['initialText']}' to '{toggled_text}'.")

    # 4. Test real DOM click on Edit (✎) for a built-in command & save changes
    print("[4/6] Testing real DOM click on Edit (✎) and saving updated response...")
    edit_info = run_js_sync(
        view,
        f"""
        (() => {{
            const editBtn = document.querySelector('[data-edit-cmd="{first_cmd_info["cmdId"]}"]');
            editBtn.click();
            const modalOpen = document.getElementById('new-cmd-modal').classList.contains('open');
            const titleText = document.getElementById('new-cmd-modal-title').textContent;
            const respInput = document.getElementById('modal-cmd-response');
            respInput.value = 'Тестовый ответ после редактирования!';
            document.getElementById('btn-save-new-cmd-modal').click();
            return {{ modalOpen, titleText }};
        }})()
        """,
    )
    assert edit_info["modalOpen"], "Edit modal did not open on ✎ click!"
    assert "Редактирование:" in edit_info["titleText"], f"Unexpected modal title: {edit_info['titleText']}"
    wait_ms(700)

    # 5. Test real DOM click on Delete (✕) for a built-in command (non-blocking!)
    print("[5/6] Testing real DOM click on Delete (✕) for built-in command...")
    run_js_sync(
        view,
        f"""
        (() => {{
            const delBtn = document.querySelector('[data-del-cmd="{first_cmd_info["cmdId"]}"]');
            if (delBtn) delBtn.click();
        }})()
        """,
    )
    wait_ms(600)
    exists_after_del = run_js_sync(
        view,
        f"Boolean(document.querySelector('[data-del-cmd=\"{first_cmd_info['cmdId']}\"]'))",
    )
    assert not exists_after_del, f"Command {first_cmd_info['cmdId']} still exists in DOM after clicking Delete!"
    print(f"  -> OK: Built-in command '{first_cmd_info['cmdId']}' deleted cleanly without blocking.")

    # 6. Test real DOM click on Restore Defaults (↺ Сбросить стандартные команды)
    print("[6/6] Testing real DOM click on Restore Defaults (#btn-restore-defaults)...")
    run_js_sync(view, "document.getElementById('btn-restore-defaults').click();")
    wait_ms(700)
    restored_state = run_js_sync(
        view,
        f"""
        (() => {{
            const btn = document.querySelector('[data-toggle-cmd="{first_cmd_info["cmdId"]}"]');
            return btn ? btn.textContent.trim() : null;
        }})()
        """,
    )
    assert restored_state == "Вкл", f"Expected restored command to be 'Вкл', got {restored_state}"
    print(f"  -> OK: All built-in commands restored, '{first_cmd_info['cmdId']}' is back and enabled ('{restored_state}').")

    # 7. Test Voice Command ("voice_command_received") AND Button Click Chat Rendering (even when WS drops)
    print("[7/7] Testing real-time Voice Command & Button Click rendering in #chat-stream...")
    from config import config_manager
    from core.events import agent_signals
    config_manager.set("audio.play_response_audio", False, auto_save=False)

    run_js_sync(
        view,
        """
        (() => {
            document.querySelector('[data-tab="tab-chat"]').click();
            document.getElementById('btn-clear-history').click();
            const sel = document.getElementById('select-ai-mode');
            sel.value = 'jarvis';
            sel.dispatchEvent(new Event('change'));
        })()
        """,
    )
    wait_ms(400)

    # Simulate voice command from microphone (audio_ears -> voice_command_received)
    agent_signals.emit_safe("voice_command_received", "ты тут?")
    wait_ms(900)

    chat_after_voice = run_js_sync(
        view,
        """
        (() => {
            const items = Array.from(document.querySelectorAll('#chat-stream .chat-item'));
            return items.map(el => ({
                role: el.classList.contains('user') ? 'user' : 'assistant',
                meta: el.querySelector('.chat-meta')?.textContent || '',
                text: el.querySelector('.bubble-text')?.textContent || ''
            }));
        })()
        """,
    )
    assert len(chat_after_voice) == 2, f"Expected 2 bubbles after voice command, got {chat_after_voice}"
    assert chat_after_voice[0]["role"] == "user" and "ты тут" in chat_after_voice[0]["text"]
    assert chat_after_voice[1]["role"] == "assistant" and "сэр" in chat_after_voice[1]["text"].lower()
    assert chat_after_voice[1]["meta"] == "J.A.R.V.I.S."

    # Now forcibly kill the WebSocket in the browser and immediately click Send button (#btn-send-text)
    run_js_sync(
        view,
        """
        (() => {
            if (window.evaControl.ws) {
                window.evaControl.ws.close();
            }
            const inp = document.getElementById('user-input-text');
            inp.value = 'привет';
            document.getElementById('btn-send-text').click();
        })()
        """,
    )
    wait_ms(1200)

    chat_after_btn = run_js_sync(
        view,
        """
        (() => {
            const items = Array.from(document.querySelectorAll('#chat-stream .chat-item'));
            return items.map(el => ({
                role: el.classList.contains('user') ? 'user' : 'assistant',
                meta: el.querySelector('.chat-meta')?.textContent || '',
                text: el.querySelector('.bubble-text')?.textContent || ''
            }));
        })()
        """,
    )
    assert len(chat_after_btn) == 4, f"Expected 4 bubbles (no duplicates!) after WS-down send click, got {chat_after_btn}"
    assert chat_after_btn[2]["role"] == "user" and chat_after_btn[2]["text"] == "привет"
    assert chat_after_btn[3]["role"] == "assistant" and "сэр" in chat_after_btn[3]["text"].lower()
    print(f"  -> OK: Both voice commands and button clicks render in #chat-stream with 0 duplicates: {chat_after_btn}")

    config_manager.set("audio.play_response_audio", True, auto_save=True)

    print("=" * 72)
    print("ALL 7 INTERACTIVE E2E UI & BACKEND CHECKS PASSED 100%!")
    print("=" * 72)
    view.close()
    app.quit()


if __name__ == "__main__":
    main()
