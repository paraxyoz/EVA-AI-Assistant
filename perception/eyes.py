"""
Vision ("Eyes") Module for EVA AI Assistant.
Features:
1. Instant Win32 Z-Order Screen Telemetry (`get_instant_screen_report` in <5ms):
   Immediately identifies the topmost active user window on the monitor (ignoring EVA's own overlay/control windows)
   plus all other visible open applications and tabs.
2. High-speed screen capture (`capture_full_screen` / `capture_active_window`) with fast BILINEAR downscaling
   for sub-second multimodal vision queries.
"""

import io
import base64
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import mss
import psutil
import win32gui
import win32process
from PIL import Image, ImageGrab
from tools.gui_control import GUIController


PROCESS_FRIENDLY_NAMES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "opera.exe": "Opera",
    "browser.exe": "Яндекс Браузер",
    "brave.exe": "Brave",
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "devenv.exe": "Visual Studio",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "discord.exe": "Discord",
    "telegram.exe": "Telegram",
    "spotify.exe": "Spotify",
    "obs64.exe": "OBS Studio",
    "blender.exe": "Blender",
    "photoshop.exe": "Adobe Photoshop",
    "illustrator.exe": "Adobe Illustrator",
    "afterfx.exe": "After Effects",
    "adobe premiere pro.exe": "Premiere Pro",
    "vlc.exe": "VLC",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "PowerPoint",
    "notepad.exe": "Блокнот",
    "notepad++.exe": "Notepad++",
    "explorer.exe": "Проводник",
    "taskmgr.exe": "Диспетчер задач",
    "calculatorapp.exe": "Калькулятор",
    "figma.exe": "Figma",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "epicgameslauncher.exe": "Epic Games",
    "cs2.exe": "Counter-Strike 2",
    "dota2.exe": "Dota 2",
    "gta5.exe": "GTA V",
    "cyberpunk2077.exe": "Cyberpunk 2077",
    "javaw.exe": "Minecraft",
}

IGNORED_WINDOW_TITLES = {
    "program manager",
    "windows input experience",
    "microsoft text input application",
    "nvidia geforce overlay",
    "settings",
    "параметры",
    "default ime",
    "msctfime ui",
}


class ScreenEyes:
    """Provides instant Win32 window/screen awareness and fast screenshot capture."""

    def __init__(self):
        self._sct = None

    def _get_sct(self):
        if self._sct is None:
            self._sct = mss.mss()
        return self._sct

    def get_instant_screen_report(self) -> Dict[str, Any]:
        """
        Inspects all visible windows on the monitor in Z-order (top-to-bottom) in <5ms.
        Skips EVA AI's own windows so it accurately reports what the user has open on screen.
        """
        visible_items: List[Dict[str, str]] = []
        seen_labels: set[str] = set()

        def _enum_cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                    return True
                title = (win32gui.GetWindowText(hwnd) or "").strip()
                if not title:
                    return True
                t_low = title.lower()
                if t_low in IGNORED_WINDOW_TITLES or "eva ai" in t_low or "3d & live2d аватар" in t_low:
                    return True
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                if w < 120 or h < 90:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_name = ""
                try:
                    proc_name = psutil.Process(pid).name().lower()
                except Exception:
                    pass

                friendly_app = PROCESS_FRIENDLY_NAMES.get(proc_name, "")
                # Clean noisy browser suffixes if friendly_app is already known
                short_title = title
                for suffix in (
                    " - Google Chrome", " — Google Chrome",
                    " - Microsoft​ Edge", " - Opera",
                    " - Яндекс Браузер", " - Visual Studio Code",
                    " - Discord"
                ):
                    if short_title.endswith(suffix):
                        short_title = short_title[:-len(suffix)].strip()

                if friendly_app and friendly_app.lower() not in short_title.lower():
                    display = f"{friendly_app} («{short_title[:65]}»)"
                else:
                    display = short_title[:75]

                dedup_key = (friendly_app or short_title[:30]).lower()
                if dedup_key not in seen_labels:
                    seen_labels.add(dedup_key)
                    visible_items.append({
                        "title": title,
                        "app": friendly_app or short_title,
                        "display": display,
                    })
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass

        if not visible_items:
            return {
                "primary_window": "Рабочий стол",
                "other_windows": [],
                "summary": "Сейчас на мониторе открыт чистый рабочий стол, активных окон на переднем плане нет."
            }

        primary = visible_items[0]["display"]
        others = [item["app"] for item in visible_items[1:5]]

        if others:
            others_str = ", ".join(others[:-1]) + (f" и {others[-1]}" if len(others) > 1 else others[0])
            summary = f"Сейчас на переднем плане у тебя открыт {primary}, а также запущены {others_str}."
        else:
            summary = f"Сейчас на экране у тебя открыто окно: {primary}."

        return {
            "primary_window": primary,
            "other_windows": others,
            "summary": summary
        }

    def capture_full_screen(self, max_width: int = 860, quality: int = 72) -> Tuple[Image.Image, str]:
        """
        Captures the primary monitor, resizes it rapidly with BILINEAR filtering,
        and returns PIL Image + Base64 JPEG string.
        """
        img = None
        try:
            sct = self._get_sct()
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            try:
                img = ImageGrab.grab()
            except Exception:
                img = Image.new("RGB", (640, 360), color=(30, 30, 30))

        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.BILINEAR)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        base64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return img, base64_str

    def capture_active_window(self, max_width: int = 860, quality: int = 75) -> Optional[Tuple[Image.Image, str, str]]:
        """Captures only the currently focused application window."""
        win_info = GUIController.get_active_window_info()
        title = win_info.get("title", "Неизвестно")
        rect = win_info.get("rect", {})

        if not rect or rect.get("w", 0) <= 0 or rect.get("h", 0) <= 0:
            img, b64 = self.capture_full_screen(max_width, quality)
            return img, b64, title

        bbox = {
            "top": max(0, rect["y"]),
            "left": max(0, rect["x"]),
            "width": rect["w"],
            "height": rect["h"]
        }

        try:
            sct = self._get_sct()
            sct_img = sct.grab(bbox)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            if img.width > max_width:
                ratio = max_width / float(img.width)
                new_height = int(float(img.height) * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.BILINEAR)

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            base64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return img, base64_str, title
        except Exception:
            img, b64 = self.capture_full_screen(max_width, quality)
            return img, b64, title

    def save_snapshot_to_file(self, file_path: Path) -> str:
        """Saves current screen snapshot to a file path."""
        img, _ = self.capture_full_screen(max_width=1920, quality=90)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(file_path, format="JPEG", quality=90)
        return str(file_path)


# Singleton
screen_eyes = ScreenEyes()
