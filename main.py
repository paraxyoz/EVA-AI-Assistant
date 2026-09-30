"""
EVA AI — Native Dual-Window 3D Desktop Application Entrypoint.
Runs without any browser or console window:
- Window 1: Transparent 3D Avatar living directly on the Windows desktop.
- Window 2: Control Center (Settings, Installed Ollama Models Dropdown, Clothing Layers + NSFW, Prompt History).
"""

import sys
import os
import time
import socket
import threading
import ctypes
import psutil

# Ensure sys.stdout and sys.stderr exist when running under pythonw.exe (where they are None)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Immediately hide any console window if launched via python.exe instead of pythonw.exe
if os.name == "nt" and "--show-console" not in sys.argv:
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

def free_port(port: int = 7865):
    """Terminates any previous stale process occupying the internal IPC port."""
    my_pid = os.getpid()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN" and conn.pid and conn.pid != my_pid:
                try:
                    p = psutil.Process(conn.pid)
                    p.terminate()
                    try:
                        p.wait(timeout=1.5)
                    except Exception:
                        p.kill()
                        p.wait(timeout=1.0)
                except Exception:
                    pass
    except Exception:
        pass


if __name__ == "__main__":
    free_port(7865)

from config import config_manager
from perception.ears import audio_ears
from expression.voice import voice_speaker
from server import run_server, initialize_clean_session
from desktop_app import EVADesktopSuite


def wait_for_ipc_ready(port: int = 7865, timeout: float = 5.0):
    """Waits until the internal IPC server is accepting connections before showing native windows."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                return True
        except Exception:
            time.sleep(0.05)
    return False


def main():
    port = 7865
    free_port(port)

    # Clear prompt history on every fresh app launch (long-term facts remain intact)
    initialize_clean_session()

    # Ensure a valid default model is active if none or archived model is set
    if config_manager.get("vrm.active_model") in (None, "", "eva_layered_nsfw.vrm"):
        config_manager.set("vrm.active_model", "sample_vrm1.vrm", auto_save=True)

    # 1. Start internal IPC & Asset Engine in background daemon thread
    server_thread = threading.Thread(
        target=run_server,
        kwargs={"host": "127.0.0.1", "port": port},
        daemon=True
    )
    server_thread.start()

    # 2. Start background microphone wake-word listener ("Ева")
    if config_manager.get("audio.enabled", True):
        try:
            audio_ears.start_listening()
        except Exception:
            pass

    # 3. Wait ~150ms for IPC socket readiness, then launch Native Dual-Window Desktop Suite
    wait_for_ipc_ready(port=port, timeout=4.0)

    suite = EVADesktopSuite(port=port)
    suite.run()


if __name__ == "__main__":
    main()
