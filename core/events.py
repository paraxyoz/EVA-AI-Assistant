"""
Thread-safe Event Signals for Personal AI Assistant.
Supports both PyQt6 signals and direct Python async/sync callbacks for FastAPI WebSockets.
"""

from typing import Callable, Dict, List
from PyQt6.QtCore import QObject, pyqtSignal


class AgentSignals(QObject):
    """Qt thread-safe signals + direct callback hooks."""
    state_changed = pyqtSignal(str)
    thought_logged = pyqtSignal(str)
    response_generated = pyqtSignal(str)
    speech_started = pyqtSignal()
    speech_stopped = pyqtSignal()
    voice_command_received = pyqtSignal(str)
    wake_word_triggered = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._callbacks: Dict[str, List[Callable]] = {}

    def on(self, signal_name: str, callback: Callable):
        """Registers a direct Python callback that fires immediately on any thread."""
        if signal_name not in self._callbacks:
            self._callbacks[signal_name] = []
        if callback not in self._callbacks[signal_name]:
            self._callbacks[signal_name].append(callback)

    def emit_safe(self, signal_name: str, *args):
        """Emits signal to both direct callbacks and Qt signals safely."""
        # 1. Fire direct Python callbacks immediately
        for cb in self._callbacks.get(signal_name, []):
            try:
                cb(*args)
            except Exception as e:
                print(f"[Events] Callback error on {signal_name}: {e}")

        # 2. Fire Qt signal if QApplication is active
        try:
            sig = getattr(self, signal_name, None)
            if sig:
                sig.emit(*args)
        except Exception:
            pass


agent_signals = AgentSignals()
