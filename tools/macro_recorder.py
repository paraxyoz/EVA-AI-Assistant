"""
Mouse & Keyboard Action Macro Recorder & Player for EVA AI Assistant (v8.0).
Allows users to record real mouse clicks (coordinates + button) and keyboard keystrokes
into a JSON macro file (`data/macros/<id>.json`) and replay them automatically inside
any voice/text command chain.
"""

import os
import json
import time
import uuid
import ctypes
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
import pyautogui
from core.events import agent_signals


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# Virtual-Key codes mapped to PyAutoGUI key names
VK_TO_KEY_NAME: Dict[int, str] = {
    0x08: "backspace",
    0x09: "tab",
    0x0D: "enter",
    0x10: "shift",
    0x11: "ctrl",
    0x12: "alt",
    0x14: "capslock",
    0x20: "space",
    0x21: "pageup",
    0x22: "pagedown",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2D: "insert",
    0x2E: "delete",
    # Digits 0-9
    **{0x30 + i: str(i) for i in range(10)},
    # Letters A-Z
    **{0x41 + i: chr(ord("a") + i) for i in range(26)},
    # Function keys F1-F12
    **{0x70 + i: f"f{i + 1}" for i in range(12)},
}


class MacroRecorder:
    """Records and replays mouse clicks and keyboard actions stored in data/macros/."""

    def __init__(self):
        self.macros_dir = Path(__file__).parent.parent / "data" / "macros"
        self.macros_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.is_recording = False
        self._stop_event = threading.Event()
        self._recorded_events: List[Dict[str, Any]] = []
        self._current_macro_name = ""
        self._last_saved_macro: Optional[Dict[str, Any]] = None

    def list_macros(self) -> List[Dict[str, Any]]:
        """Returns metadata for all saved macros."""
        macros: List[Dict[str, Any]] = []
        for f in sorted(self.macros_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "id" in data:
                    macros.append({
                        "id": data["id"],
                        "name": data.get("name", f.stem),
                        "events_count": len(data.get("events", [])),
                        "duration_sec": round(sum(float(e.get("dt", 0)) for e in data.get("events", [])), 1),
                        "created_at": data.get("created_at", 0)
                    })
            except Exception:
                pass
        return macros

    def get_macro(self, macro_id: str) -> Optional[Dict[str, Any]]:
        clean_id = os.path.basename(str(macro_id).strip()).replace(".json", "")
        path = self.macros_dir / f"{clean_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_macro(self, name: str, events: List[Dict[str, Any]], macro_id: Optional[str] = None) -> Dict[str, Any]:
        """Saves a sequence of mouse/keyboard events to disk."""
        m_id = macro_id or f"macro_{str(uuid.uuid4())[:8]}"
        clean_name = (name or "Запись действий").strip()
        payload = {
            "id": m_id,
            "name": clean_name,
            "created_at": int(time.time()),
            "count": len(events),
            "events": events,
        }
        path = self.macros_dir / f"{m_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._last_saved_macro = payload
        return payload

    def delete_macro(self, macro_id: str) -> bool:
        clean_id = os.path.basename(str(macro_id).strip()).replace(".json", "")
        path = self.macros_dir / f"{clean_id}.json"
        if path.exists():
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return False

    def start_recording(self, name: str = "Запись действий", countdown_sec: float = 2.0, max_duration_sec: float = 45.0) -> bool:
        """Starts asynchronous Win32 mouse & keyboard recording until ESC is pressed or stop_recording() is called."""
        with self._lock:
            if self.is_recording:
                return False
            self.is_recording = True
            self._stop_event.clear()
            self._recorded_events = []
            self._current_macro_name = (name or "Запись действий").strip()

        t = threading.Thread(
            target=self._record_worker,
            args=(countdown_sec, max_duration_sec),
            daemon=True
        )
        t.start()
        return True

    def stop_recording(self) -> Optional[Dict[str, Any]]:
        """Stops ongoing recording and returns the saved macro object."""
        self._stop_event.set()
        for _ in range(30):
            if not self.is_recording:
                break
            time.sleep(0.02)
        return self._last_saved_macro

    def _record_worker(self, countdown_sec: float, max_duration_sec: float):
        try:
            if countdown_sec > 0:
                agent_signals.emit_safe("macro_recording_state", {
                    "state": "countdown",
                    "countdown": countdown_sec,
                    "name": self._current_macro_name
                })
                time.sleep(countdown_sec)

            if self._stop_event.is_set():
                self.is_recording = False
                return

            agent_signals.emit_safe("macro_recording_state", {
                "state": "recording",
                "name": self._current_macro_name
            })

            user32 = ctypes.windll.user32 if os.name == "nt" else None
            start_ts = time.perf_counter()
            last_event_ts = start_ts

            prev_mouse = {"left": False, "right": False, "middle": False}
            prev_keys: Dict[int, bool] = {vk: False for vk in VK_TO_KEY_NAME}

            # Clear initial key states so already-held buttons don't trigger immediately
            if user32:
                for vk in list(prev_keys.keys()) + [0x01, 0x02, 0x04, 0x1B]:
                    user32.GetAsyncKeyState(vk)

            while not self._stop_event.is_set() and (time.perf_counter() - start_ts) < max_duration_sec:
                now = time.perf_counter()
                if user32:
                    # Check ESC (0x1B) to finish recording immediately
                    if user32.GetAsyncKeyState(0x1B) & 0x8000:
                        break

                    pt = POINT()
                    user32.GetCursorPos(ctypes.byref(pt))

                    # Mouse buttons: Left (0x01), Right (0x02), Middle (0x04)
                    for btn_name, vk_code in (("left", 0x01), ("right", 0x02), ("middle", 0x04)):
                        is_down = bool(user32.GetAsyncKeyState(vk_code) & 0x8000)
                        if is_down and not prev_mouse[btn_name]:
                            dt = round(min(5.0, now - last_event_ts), 3)
                            last_event_ts = now
                            self._recorded_events.append({
                                "type": "mouse_click",
                                "button": btn_name,
                                "x": int(pt.x),
                                "y": int(pt.y),
                                "dt": dt
                            })
                        prev_mouse[btn_name] = is_down

                    # Check modifier states for combos
                    ctrl_down = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
                    shift_down = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
                    alt_down = bool(user32.GetAsyncKeyState(0x12) & 0x8000)

                    for vk, key_name in VK_TO_KEY_NAME.items():
                        if vk in (0x10, 0x11, 0x12):
                            # Skip bare modifier press; record when combined or non-modifier pressed
                            continue
                        is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                        if is_down and not prev_keys[vk]:
                            dt = round(min(5.0, now - last_event_ts), 3)
                            last_event_ts = now
                            mods = []
                            if ctrl_down:
                                mods.append("ctrl")
                            if shift_down:
                                mods.append("shift")
                            if alt_down:
                                mods.append("alt")
                            if mods:
                                self._recorded_events.append({
                                    "type": "hotkey",
                                    "keys": mods + [key_name],
                                    "dt": dt
                                })
                            else:
                                self._recorded_events.append({
                                    "type": "key_tap",
                                    "key": key_name,
                                    "dt": dt
                                })
                        prev_keys[vk] = is_down

                time.sleep(0.01)

            saved = self.save_macro(self._current_macro_name, self._recorded_events)
            self.is_recording = False
            agent_signals.emit_safe("macro_recording_state", {
                "state": "completed",
                "macro": saved
            })
        except Exception as e:
            self.is_recording = False
            agent_signals.emit_safe("macro_recording_state", {
                "state": "error",
                "error": str(e)
            })

    def play_macro(self, macro_id: str) -> bool:
        """Replays a saved mouse & keyboard macro sequence."""
        macro = self.get_macro(macro_id)
        if not macro:
            return False

        events = macro.get("events", [])
        if not events:
            return True

        try:
            for ev in events:
                dt = float(ev.get("dt", 0.05))
                if dt > 0:
                    time.sleep(min(3.0, dt))

                ev_type = ev.get("type", "")
                if ev_type == "mouse_click":
                    x = int(ev.get("x", 0))
                    y = int(ev.get("y", 0))
                    btn = str(ev.get("button", "left"))
                    pyautogui.click(x=x, y=y, button=btn)
                elif ev_type == "key_tap":
                    key = str(ev.get("key", ""))
                    if key:
                        pyautogui.press(key)
                elif ev_type == "hotkey":
                    keys = ev.get("keys", [])
                    if isinstance(keys, list) and keys:
                        pyautogui.hotkey(*[str(k) for k in keys])
            return True
        except Exception as e:
            print(f"[MacroRecorder] Playback error: {e}")
            return False


macro_recorder = MacroRecorder()
