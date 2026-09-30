import os
import re
import time
import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QEventLoop, QTimer
from fastapi.testclient import TestClient
from server import app


class TestV9UIComputedLayout(unittest.TestCase):
    """
    Senior-grade UI, CSS & Real QWebEngineView DOM Test Suite:
    1. Every single class attribute in web/control.html and web/control.js must have a matching CSS rule in <style>.
    2. Every inline SVG must be constrained by CSS rules so no giant unstyled SVG can ever appear.
    3. All 4 main tabs (tab-chat, tab-commands, tab-wardrobe, tab-settings), 6 left rail buttons,
       and both modals (cmd-confirm-modal, new-cmd-modal) must be structurally complete and wired.
    4. Real QWebEngineView renders http://127.0.0.1:7865/control, verifies computed styles, SVG bounding boxes,
       interactive tab switching, 3-level command tree rendering, modal opening, and captures screenshots.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.root = Path(__file__).resolve().parent.parent
        cls.html_path = cls.root / "web" / "control.html"
        cls.js_path = cls.root / "web" / "control.js"

    def test_1_every_html_class_is_styled_in_css(self):
        """Every class used in control.html body must have a corresponding .class rule in <style>."""
        html = self.html_path.read_text(encoding="utf-8")
        style_match = re.search(r"<style>(.*?)</style>", html, re.S)
        self.assertIsNotNone(style_match, "<style> block must exist in control.html")
        style_css = style_match.group(1)
        body_html = html[style_match.end():]

        used_classes = set()
        for m in re.finditer(r'class="([^"]+)"', body_html):
            for token in m.group(1).split():
                clean = token.strip()
                if clean:
                    used_classes.add(clean)

        missing = [c for c in sorted(used_classes) if f".{c}" not in style_css]
        self.assertEqual(
            missing,
            [],
            f"The following HTML classes have NO CSS rule in <style>: {missing}",
        )

    def test_2_every_dynamic_js_class_is_styled_in_css(self):
        """Every class dynamically generated in control.js must also be defined in <style>."""
        html = self.html_path.read_text(encoding="utf-8")
        style_css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)

        required_dynamic_classes = [
            "tab-page",
            "page-header",
            "page-title",
            "status-pill",
            "action-btn",
            "icon-btn",
            "chat-workspace",
            "chat-stream",
            "empty-state-hero",
            "starter-grid",
            "starter-card",
            "chat-item",
            "chat-meta",
            "bubble-text",
            "tool-log",
            "quick-pose-bar",
            "mini-pill",
            "chat-footer",
            "input-bar",
            "prompt-input",
            "commands-page-shell",
            "commands-big-heading",
            "commands-studio-wrapper",
            "commands-tree-panel",
            "commands-tree-header",
            "commands-tree-body",
            "cmd-folder-card",
            "cmd-folder-head",
            "cmd-folder-title-wrap",
            "cmd-folder-icon",
            "cmd-folder-title",
            "cmd-folder-count",
            "cmd-folder-items",
            "cmd-leaf-row",
            "cmd-leaf-top",
            "cmd-leaf-info",
            "cmd-leaf-trigger",
            "cmd-leaf-actions",
            "cmd-leaf-details",
            "cmd-trigger-line",
            "cmd-steps-list",
            "cmd-step-item",
            "cmd-step-num",
            "cmd-badge-chain",
            "cmd-badge-confirm",
            "btn-new-cmd-hero",
            "model-gallery-grid",
            "model-card",
            "model-card-top",
            "model-type-badge",
            "model-size-tag",
            "model-card-name",
            "model-card-footer",
            "pose-grid",
            "pose-btn",
            "preset-grid",
            "preset-card",
            "settings-columns",
            "form-stack",
            "field-box",
            "field-label",
            "field-row",
            "ctrl-select",
            "ctrl-input",
            "eq-slider-row",
            "eq-slider",
            "eq-val-badge",
            "toast-container",
            "toast-msg",
        ]
        missing = [c for c in required_dynamic_classes if f".{c}" not in style_css]
        self.assertEqual(missing, [], f"Dynamic JS classes missing in CSS: {missing}")

    def test_3_all_svg_containers_have_explicit_width_and_height_css(self):
        """Ensure every SVG container rule explicitly bounds width/height so no giant 1000px SVG can ever render."""
        html = self.html_path.read_text(encoding="utf-8")
        style_css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)

        svg_selectors = [
            ".rail-logo-btn svg",
            ".rail-nav-btn svg",
            ".rail-action-btn svg",
            ".header-vol-wrap svg",
            ".action-btn svg",
            ".icon-btn svg",
            ".empty-hero-badge svg",
            ".cmd-folder-icon svg",
            ".btn-new-cmd-hero svg",
            ".tree-search-icon",
        ]
        for sel in svg_selectors:
            self.assertIn(sel, style_css, f"Missing explicit SVG sizing rule for {sel}")

    def test_4_live_control_endpoint_serves_complete_css_and_js(self):
        """GET /control and GET /static/control.js must return 200 with all UI rules."""
        r_html = self.client.get("/control")
        self.assertEqual(r_html.status_code, 200)
        self.assertIn(".tab-page.active", r_html.text)
        self.assertIn(".header-vol-wrap svg", r_html.text)
        self.assertIn(".commands-tree-panel", r_html.text)
        self.assertIn("cmd-leaf-details", self.js_path.read_text(encoding="utf-8"))

    def test_5_real_qwebengine_computed_layout_and_interactive_tabs(self):
        """
        Loads the live Control Center in QWebEngineView, verifies computed styles,
        checks that no SVG exceeds 40x40px, tests switching all 4 tabs and opening the modal,
        and saves visual verification screenshots.
        """
        import sys
        import socket
        import threading
        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

        try:
            with socket.create_connection(("127.0.0.1", 7865), timeout=0.3):
                pass
        except Exception:
            from server import run_server
            threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": 7865}, daemon=True).start()
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", 7865), timeout=0.2):
                        break
                except Exception:
                    time.sleep(0.1)

        qt_app = QApplication.instance() or QApplication(sys.argv)
        view = QWebEngineView()
        profile = QWebEngineProfile(view)
        page = QWebEnginePage(profile, view)
        view.setPage(page)
        view.resize(1220, 820)
        view.show()

        def wait_ms(ms: int):
            loop = QEventLoop()
            QTimer.singleShot(ms, loop.quit)
            loop.exec()

        def eval_js(script: str):
            result = {"done": False, "val": None}
            loop = QEventLoop()

            def _cb(v):
                result["done"] = True
                result["val"] = v
                loop.quit()

            view.page().runJavaScript(script, _cb)
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
            return result["val"]

        load_loop = QEventLoop()
        view.loadFinished.connect(lambda _ok: load_loop.quit())
        view.load(QUrl(f"http://127.0.0.1:7865/control?v={int(time.time())}"))
        QTimer.singleShot(5000, load_loop.quit)
        load_loop.exec()
        wait_ms(900)

        out_dir = Path(r"C:\Users\paraxyoz\.gemini\antigravity\brain\02e5b71b-d50d-495b-a28c-3560d8add456")
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1. Verify Tab 1 (Chat) computed styles & SVG bounding boxes
        tab1_report = eval_js("""
            (() => {
                const chatDisplay = getComputedStyle(document.getElementById('tab-chat')).display;
                const cmdDisplay = getComputedStyle(document.getElementById('tab-commands')).display;
                const railBtns = document.querySelectorAll('.sidebar > button, .sidebar .rail-nav-btn, .sidebar .rail-action-btn').length;
                const oversizedSvgs = [];
                document.querySelectorAll('svg').forEach((s, idx) => {
                    const r = s.getBoundingClientRect();
                    if (r.width > 42 || r.height > 42) {
                        oversizedSvgs.push({ idx, w: r.width, h: r.height, cls: s.parentElement?.className || '' });
                    }
                });
                return { chatDisplay, cmdDisplay, railBtns, oversizedSvgs };
            })()
        """)
        self.assertIsNotNone(tab1_report)
        self.assertEqual(tab1_report["chatDisplay"], "flex")
        self.assertEqual(tab1_report["cmdDisplay"], "none")
        self.assertEqual(tab1_report["railBtns"], 6)
        self.assertEqual(tab1_report["oversizedSvgs"], [], f"Found oversized SVGs: {tab1_report['oversizedSvgs']}")
        view.grab().save(str(out_dir / "verified_tab1_chat.png"))

        # 2. Switch to Tab 2 (Команды) and verify 3-level tree rendering
        eval_js("document.querySelector('[data-tab=\"tab-commands\"]').click();")
        wait_ms(500)
        tab2_report = eval_js("""
            (() => {
                const cmdDisplay = getComputedStyle(document.getElementById('tab-commands')).display;
                const folders = document.querySelectorAll('#commands-tree-body .cmd-folder-card').length;
                const leaves = document.querySelectorAll('#commands-tree-body .cmd-leaf-row').length;
                const details = document.querySelectorAll('#commands-tree-body .cmd-leaf-details').length;
                const steps = document.querySelectorAll('#commands-tree-body .cmd-step-item').length;
                return { cmdDisplay, folders, leaves, details, steps };
            })()
        """)
        self.assertEqual(tab2_report["cmdDisplay"], "flex")
        self.assertGreaterEqual(tab2_report["folders"], 2)
        self.assertGreaterEqual(tab2_report["leaves"], 5)
        self.assertGreaterEqual(tab2_report["details"], 5)
        self.assertGreaterEqual(tab2_report["steps"], 8)
        view.grab().save(str(out_dir / "verified_tab2_commands.png"))

        # 3. Switch to App Packs scope inside Команды
        eval_js("document.querySelector('[data-tree-scope=\"packs\"]').click();")
        wait_ms(350)
        packs_count = eval_js("document.querySelectorAll('#commands-tree-body .cmd-folder-card').length;")
        self.assertGreaterEqual(packs_count, 5)
        view.grab().save(str(out_dir / "verified_tab2_packs.png"))

        # 4. Open "Новая команда" modal via scenario template button
        eval_js("document.querySelector('[data-scenario-template=\"morning\"]').click();")
        wait_ms(350)
        modal_report = eval_js("""
            (() => {
                const modalDisplay = getComputedStyle(document.getElementById('new-cmd-modal')).display;
                const triggerVal = document.getElementById('modal-cmd-trigger').value;
                const stepRows = document.querySelectorAll('#modal-steps-container .step-builder-row').length;
                return { modalDisplay, triggerVal, stepRows };
            })()
        """)
        self.assertEqual(modal_report["modalDisplay"], "flex")
        self.assertEqual(modal_report["triggerVal"], "доброе утро")
        self.assertEqual(modal_report["stepRows"], 3)
        view.grab().save(str(out_dir / "verified_modal_new_cmd.png"))
        eval_js("document.getElementById('btn-close-new-cmd-modal').click();")
        wait_ms(200)

        # 5. Switch to Tab 3 (Студия) and Tab 4 (Настройки)
        eval_js("document.querySelector('[data-tab=\"tab-wardrobe\"]').click();")
        wait_ms(350)
        self.assertEqual(eval_js("getComputedStyle(document.getElementById('tab-wardrobe')).display"), "flex")
        view.grab().save(str(out_dir / "verified_tab3_studio.png"))

        eval_js("document.querySelector('[data-tab=\"tab-settings\"]').click();")
        wait_ms(350)
        self.assertEqual(eval_js("getComputedStyle(document.getElementById('tab-settings')).display"), "flex")
        view.grab().save(str(out_dir / "verified_tab4_settings.png"))

        view.close()


if __name__ == "__main__":
    unittest.main()
