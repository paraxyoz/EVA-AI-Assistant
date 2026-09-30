"""
GUI Automation and Window Management for Personal AI Assistant.
Controls mouse, keyboard, and Windows GUI elements.
"""

import time
import pyautogui
import win32gui
import win32con
import win32process
from typing import Dict, Any, List, Optional

# Disable PyAutoGUI failsafe delay for speed, but keep failsafe corner
pyautogui.PAUSE = 0.05


class GUIController:
    """Controls mouse, keyboard, and window focus."""

    @staticmethod
    def get_screen_size() -> Dict[str, int]:
        """Returns primary monitor screen resolution."""
        w, h = pyautogui.size()
        return {"width": w, "height": h}

    @staticmethod
    def click(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
        """Moves mouse and clicks at specified coordinate."""
        try:
            pyautogui.click(x=x, y=y, clicks=clicks, button=button)
            return {"success": True, "message": f"Клик ({button}) по ({x}, {y}) выполнен."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def move_mouse(x: int, y: int, duration: float = 0.2) -> Dict[str, Any]:
        """Smoothly moves mouse cursor."""
        try:
            pyautogui.moveTo(x=x, y=y, duration=duration)
            return {"success": True, "message": f"Курсор перемещен в ({x}, {y})."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def type_text(text: str, press_enter: bool = False) -> Dict[str, Any]:
        """
        Types text using clipboard paste to reliably support Russian and Unicode.
        """
        try:
            import subprocess
            # Use PowerShell to set clipboard accurately without extra dependencies
            encoded_text = text.replace("'", "''")
            subprocess.run(
                f"powershell -Command \"Set-Clipboard -Value '{encoded_text}'\"",
                shell=True,
                check=True
            )
            time.sleep(0.05)
            # Paste via Ctrl+V
            pyautogui.hotkey('ctrl', 'v')
            
            if press_enter:
                time.sleep(0.05)
                pyautogui.press('enter')

            return {"success": True, "message": f"Текст введен ({len(text)} символов)."}
        except Exception as e:
            # Fallback to direct write
            try:
                pyautogui.write(text, interval=0.01)
                if press_enter:
                    pyautogui.press('enter')
                return {"success": True, "message": f"Текст введен напрямую."}
            except Exception as e2:
                return {"success": False, "error": f"{e}; {e2}"}

    @staticmethod
    def press_key(key: str) -> Dict[str, Any]:
        """Presses a single keyboard or media key (e.g. 'playpause', 'nexttrack', 'prevtrack', 'enter')."""
        try:
            pyautogui.press(key)
            return {"success": True, "message": f"Клавиша '{key}' нажата."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def press_hotkey(keys: List[str]) -> Dict[str, Any]:
        """Presses a key combination (e.g. ['ctrl', 'c'], ['alt', 'tab'], ['win', 'r'])."""
        try:
            pyautogui.hotkey(*keys)
            return {"success": True, "message": f"Комбинация {keys} нажата."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def list_visible_windows() -> List[Dict[str, Any]]:
        """Returns list of open non-empty windows with their handles and titles."""
        windows = []

        def enum_callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if title and not win32gui.IsIconic(hwnd):
                    rect = win32gui.GetWindowRect(hwnd)
                    # Exclude invisible zero-size overlays
                    if (rect[2] - rect[0] > 50) and (rect[3] - rect[1] > 50):
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]}
                        })
            return True

        win32gui.EnumWindows(enum_callback, None)
        return windows

    @staticmethod
    def focus_window_by_title(title_query: str) -> Dict[str, Any]:
        """Brings the window matching `title_query` to front."""
        windows = GUIController.list_visible_windows()
        for w in windows:
            if title_query.lower() in w["title"].lower():
                hwnd = w["hwnd"]
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    return {"success": True, "message": f"Окно '{w['title']}' выведено на передний план."}
                except Exception as e:
                    return {"success": False, "error": f"Не удалось сфокусировать окно: {e}"}
        return {"success": False, "error": f"Окно с названием '{title_query}' не найдено."}

    @staticmethod
    def get_active_window_info() -> Dict[str, Any]:
        """Returns information about the currently active focused window."""
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return {
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "rect": {"x": rect[0], "y": rect[1], "w": rect[2]-rect[0], "h": rect[3]-rect[1]}
            }
        except Exception:
            return {"title": "Не определено", "hwnd": 0}
