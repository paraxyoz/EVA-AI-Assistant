"""
EVA AI — Internal Real-Time IPC & Asset Server for Native Desktop Application.
Provides bidirectional WebSocket sync between the Transparent 3D Avatar Desktop Window
and the Control Center (Settings + Prompt History) Window, plus Ollama model discovery.
"""

import os
import re
import json
import base64
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import config_manager
from core.agent import assistant_agent
from core.events import agent_signals
from expression.voice import voice_speaker
from perception.ears import audio_ears
from memory.system_profiler import SystemProfiler
from memory.db import memory_db
from tools.os_control import OSController


server_loop: Optional[asyncio.AbstractEventLoop] = None


class ConnectionManager:
    """Manages active IPC WebSockets across the Avatar Window and Control Center Window with per-socket locks."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._locks: Dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._locks[websocket] = asyncio.Lock()
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)

    def ensure_registered(self, websocket: WebSocket):
        if websocket not in self._locks:
            self._locks[websocket] = asyncio.Lock()
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self._locks.pop(websocket, None)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._safe_close(websocket))
        except RuntimeError:
            pass

    async def _safe_close(self, websocket: WebSocket):
        try:
            await websocket.close()
        except Exception:
            pass

    async def send_personal_json(self, websocket: WebSocket, data: Dict[str, Any]) -> bool:
        lock = self._locks.setdefault(websocket, asyncio.Lock())
        try:
            async with lock:
                await websocket.send_json(data)
            return True
        except Exception:
            self.disconnect(websocket)
            return False

    async def broadcast_json(self, data: Dict[str, Any]):
        for connection in list(self.active_connections):
            await self.send_personal_json(connection, data)


manager = ConnectionManager()


def schedule_broadcast(data: Dict[str, Any]):
    """Thread-safe helper to broadcast JSON from any worker thread to connected windows."""
    global server_loop
    if server_loop and server_loop.is_running() and manager.active_connections:
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast_json(data), server_loop)
        except RuntimeError:
            pass


def on_thought_logged(msg: str):
    schedule_broadcast({"type": "thought", "content": msg})

def on_state_changed(state: str):
    schedule_broadcast({"type": "state", "state": state})

def on_response_chunk(partial_text: str):
    schedule_broadcast({"type": "response_chunk", "text": partial_text})

def on_response_generated(text: str):
    schedule_broadcast({"type": "response", "text": text})

def on_wake_word(word: str):
    schedule_broadcast({"type": "wake_word", "word": word})

def on_avatar_action(payload: Dict[str, Any]):
    schedule_broadcast({"type": "avatar_action", **payload})

def on_mic_state(active: bool):
    schedule_broadcast({"type": "mic_state", "active": bool(active)})

def on_mic_muted(muted: bool):
    schedule_broadcast({"type": "mic_muted", "muted": bool(muted)})

def on_voice_eq_changed(eq: Dict[str, Any]):
    schedule_broadcast({"type": "voice_eq_changed", "eq": eq})

def on_cmd_confirmation_required(payload: Dict[str, Any]):
    schedule_broadcast({"type": "command_confirmation_required", **payload})

def on_cmd_confirmation_resolved(payload: Dict[str, Any]):
    schedule_broadcast({"type": "command_confirmation_resolved", **payload})

def on_macro_recording_state(payload: Dict[str, Any]):
    schedule_broadcast({"type": "macro_recording_state", **payload})

def on_voice_command(transcript_text: str):
    global server_loop
    schedule_broadcast({"type": "user_message", "text": transcript_text})
    if server_loop and server_loop.is_running():
        asyncio.run_coroutine_threadsafe(process_user_message_async(transcript_text), server_loop)


def on_search_state(data):
    payload = data if isinstance(data, dict) else {"text": str(data)}
    schedule_broadcast({"type": "search_state", **payload})

def on_speech_stopped(_data=None):
    schedule_broadcast({"type": "speech_stopped"})

agent_signals.on("thought_logged", on_thought_logged)
agent_signals.on("state_changed", on_state_changed)
agent_signals.on("response_chunk", on_response_chunk)
agent_signals.on("response_generated", on_response_generated)
agent_signals.on("wake_word_triggered", on_wake_word)
agent_signals.on("avatar_action", on_avatar_action)
agent_signals.on("mic_state", on_mic_state)
agent_signals.on("mic_muted", on_mic_muted)
agent_signals.on("voice_eq_changed", on_voice_eq_changed)
agent_signals.on("command_confirmation_required", on_cmd_confirmation_required)
agent_signals.on("command_confirmation_resolved", on_cmd_confirmation_resolved)
agent_signals.on("macro_recording_state", on_macro_recording_state)
agent_signals.on("voice_command_received", on_voice_command)
agent_signals.on("search_state", on_search_state)
agent_signals.on("speech_stopped", on_speech_stopped)


def get_installed_ollama_models() -> List[str]:
    """Discovers locally installed Ollama models via HTTP API or silent CLI without console popups."""
    models: List[str] = []
    try:
        res = httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.5)
        if res.status_code == 200:
            data = res.json()
            for m in data.get("models", []):
                name = m.get("name")
                if name and name not in models:
                    models.append(name)
    except Exception:
        pass

    if not models:
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=creationflags
            )
            if proc.returncode == 0:
                lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
                for ln in lines[1:]:
                    parts = ln.split()
                    if parts and parts[0] not in models:
                        models.append(parts[0])
        except Exception:
            pass

    return models


def initialize_clean_session() -> None:
    """Clears dialogue history on app startup while keeping long-term user facts."""
    import uuid
    try:
        memory_db.clear_history()
        assistant_agent.session_id = str(uuid.uuid4())
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global server_loop
    server_loop = asyncio.get_running_loop()
    server_loop.run_in_executor(None, SystemProfiler.get_full_system_context)
    yield


app = FastAPI(title="EVA AI Desktop Core", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/static/", "/api/", "/models/")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


BASE_DIR = Path(__file__).parent.resolve()
WEB_DIR = BASE_DIR / "web"
MODELS_DIR = BASE_DIR / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount("/models", StaticFiles(directory=str(MODELS_DIR)), name="models")


@app.get("/avatar", response_class=HTMLResponse)
async def serve_avatar():
    """Serves Window 1: Transparent Desktop 3D Avatar Companion (Model Only)."""
    p = WEB_DIR / "avatar.html"
    if p.exists():
        return HTMLResponse(
            content=p.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return HTMLResponse("")


@app.get("/control", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def serve_control():
    """Serves Window 2: Control Center (Settings + Prompt History + Avatar Studio)."""
    p = WEB_DIR / "control.html"
    if not p.exists():
        p = WEB_DIR / "index.html"
    if p.exists():
        return HTMLResponse(
            content=p.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return HTMLResponse("")


@app.post("/api/history/clear")
async def api_clear_history():
    """Clears conversation history and notifies connected windows."""
    initialize_clean_session()
    await manager.broadcast_json({"type": "history_cleared", "history": []})
    return {"success": True, "history": []}


@app.get("/api/chat/history")
async def api_get_chat_history():
    """Returns current dialogue history and live agent/microphone state for real-time UI sync."""
    return {
        "success": True,
        "history": memory_db.get_recent_messages(limit=30),
        "state": getattr(assistant_agent, "state", "IDLE"),
        "mic_active": bool(getattr(audio_ears, "is_active_listening", False)),
        "mic_muted": bool(audio_ears.is_muted),
        "ai_mode": config_manager.get("ai_mode", "conversational"),
        "avatar_visible": bool(config_manager.get("avatar.show_on_desktop", True)),
    }


@app.post("/api/chat/send")
async def api_send_chat_message(payload: Dict[str, Any]):
    """Processes a text command or chat message over HTTP and broadcasts updates to all windows."""
    user_text = str(payload.get("text", "")).strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    await manager.broadcast_json({"type": "user_message", "text": user_text})
    asyncio.create_task(process_user_message_async(user_text))
    return {"success": True, "text": user_text}


@app.post("/api/mic/toggle")
async def api_toggle_mic():
    """Toggles active voice listening window over HTTP."""
    loop = asyncio.get_running_loop()
    active = await loop.run_in_executor(None, audio_ears.toggle_manual_listen)
    await manager.broadcast_json({"type": "mic_state", "active": bool(active)})
    return {"success": True, "active": bool(active)}


@app.post("/api/speech/stop")
async def api_stop_speech():
    """Stops ongoing TTS speech immediately over HTTP."""
    voice_speaker.stop()
    audio_ears.set_web_audio_playing(False)
    await manager.broadcast_json({"type": "speech_stopped"})
    return {"success": True}


@app.post("/api/avatar/action")
async def api_avatar_action(payload: Dict[str, Any]):
    """Broadcasts pose, camera, emotion, or clothing layer actions to the 3D/Live2D Avatar Window."""
    if isinstance(payload.get("layers"), dict):
        assistant_agent._layers.update(payload["layers"])
    msg = {"type": "avatar_action", **{k: v for k, v in payload.items() if k != "type"}}
    await manager.broadcast_json(msg)
    return {"success": True}


@app.post("/api/window/action")
async def api_window_action(payload: Dict[str, Any]):
    """Triggers native desktop window actions (hide_control, show_control, toggle_control, hide_avatar, show_avatar)."""
    action = str(payload.get("action", "")).strip()
    if action:
        if action == "hide_avatar":
            config_manager.set("avatar.show_on_desktop", False, auto_save=True)
            await manager.broadcast_json({"type": "avatar_visibility", "visible": False})
        elif action == "show_avatar":
            config_manager.set("avatar.show_on_desktop", True, auto_save=True)
            await manager.broadcast_json({"type": "avatar_visibility", "visible": True})
        agent_signals.emit_safe("window_action", action)
    return {"success": True, "action": action}


@app.post("/api/models/select")
async def api_select_model(payload: Dict[str, Any]):
    """Switches the active 3D VRM or 2D Live2D model over HTTP and notifies both windows."""
    model_name = str(payload.get("model_name", "")).strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="Не указано имя модели")
    config_manager.set("vrm.active_model", model_name, auto_save=True)
    all_models = list_available_models()
    await manager.broadcast_json({
        "type": "model_changed",
        "model_name": model_name,
        "models": all_models
    })
    return {"success": True, "model_name": model_name, "models": all_models}


@app.get("/api/ollama/models")
async def api_ollama_models():
    """Returns installed local Ollama models for the dropdown selector."""
    loop = asyncio.get_running_loop()
    models = await loop.run_in_executor(None, get_installed_ollama_models)
    return {"success": True, "models": models}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Bidirectional IPC WebSocket between Avatar Window, Control Window, and Core Agent."""
    global server_loop
    if server_loop is None:
        server_loop = asyncio.get_running_loop()

    await manager.connect(websocket)
    try:
        loop = asyncio.get_running_loop()
        ollama_models = await loop.run_in_executor(None, get_installed_ollama_models)
        output_devs = await loop.run_in_executor(None, voice_speaker.list_output_devices)
        input_devs = await loop.run_in_executor(None, audio_ears.list_input_devices)
        hw_info = await loop.run_in_executor(None, SystemProfiler.get_hardware_info)

        active_model = config_manager.get("vrm.active_model", "sample_vrm1.vrm")
        if not (MODELS_DIR / active_model).exists():
            active_model = "sample_vrm1.vrm" if (MODELS_DIR / "sample_vrm1.vrm").exists() else "alicia.vrm"

        from tools.app_commands import custom_commands_store
        from tools.macro_recorder import macro_recorder

        full_tree = custom_commands_store.get_full_commands_tree()
        await manager.send_personal_json(websocket, {
            "type": "init",
            "assistant_name": config_manager.get("assistant_name", "Ева"),
            "user_name": config_manager.get("user_name", "Создатель"),
            "ai_mode": config_manager.get("ai_mode", "conversational"),
            "avatar_visible": bool(config_manager.get("avatar.show_on_desktop", True)),
            "mic_muted": bool(audio_ears.is_muted),
            "github_url": config_manager.get("project_github_url", "https://github.com/paraxyoz/EVA-AI-Assistant"),
            "llm_provider": config_manager.get("llm_provider", "ollama"),
            "providers": config_manager.get("providers", {}),
            "ollama_models": ollama_models,
            "voice_profile": config_manager.get("audio.voice_profile", "aoede"),
            "voice_eq": voice_speaker.get_voice_eq(),
            "output_device": config_manager.get("audio.output_device", "auto"),
            "input_device_index": config_manager.get("audio.input_device_index", 1),
            "output_devices": output_devs,
            "input_devices": input_devs,
            "custom_commands": custom_commands_store.list_commands(),
            "commands_tree": full_tree,
            "command_folders": full_tree,
            "macros": macro_recorder.list_macros(),
            "elevenlabs_key": (
                config_manager.get("audio.elevenlabs.api_key", "")
                or config_manager.get("audio.elevenlabs_api_key", "")
            ),
            "has_elevenlabs_key": bool(
                config_manager.get("audio.elevenlabs.api_key", "")
                or config_manager.get("audio.elevenlabs_api_key", "")
            ),
            "elevenlabs_voice_id": (
                config_manager.get("audio.elevenlabs.voice_id", "")
                or config_manager.get("audio.elevenlabs_voice_id", "cgSgspJ2msm6clMCkdW9")
            ),
            "wake_word": config_manager.get("audio.wake_word", "ева"),
            "models": list_available_models(),
            "active_model": active_model,
            "history": memory_db.get_recent_messages(limit=30),
            "system_info": hw_info
        })

        while True:
            data = await websocket.receive_json()
            manager.ensure_registered(websocket)
            event_type = data.get("type", "")

            try:
                if event_type == "ping":
                    await manager.send_personal_json(websocket, {
                        "type": "pong",
                        "state": getattr(assistant_agent, "state", "IDLE"),
                        "mic_muted": bool(audio_ears.is_muted)
                    })

                elif event_type == "user_message":
                    user_text = data.get("text", "").strip()
                    if user_text:
                        await manager.broadcast_json({"type": "user_message", "text": user_text})
                        asyncio.create_task(process_user_message_async(user_text))

                elif event_type == "clear_history":
                    initialize_clean_session()
                    await manager.broadcast_json({"type": "history_cleared", "history": []})

                elif event_type == "avatar_action":
                    if isinstance(data.get("layers"), dict):
                        assistant_agent._layers.update(data["layers"])
                    await manager.broadcast_json(data)

                elif event_type == "window_action":
                    action = data.get("action", "")
                    if action:
                        if action == "hide_avatar":
                            config_manager.set("avatar.show_on_desktop", False, auto_save=True)
                            await manager.broadcast_json({"type": "avatar_visibility", "visible": False})
                        elif action == "show_avatar":
                            config_manager.set("avatar.show_on_desktop", True, auto_save=True)
                            await manager.broadcast_json({"type": "avatar_visibility", "visible": True})
                        agent_signals.emit_safe("window_action", action)

                elif event_type == "set_voice":
                    v_prof = data.get("voice_profile")
                    if v_prof:
                        config_manager.set("audio.voice_profile", v_prof, auto_save=True)
                        await manager.broadcast_json({"type": "config_updated", "voice_profile": v_prof})

                elif event_type == "set_model":
                    model_name = data.get("model_name")
                    if model_name:
                        config_manager.set("vrm.active_model", model_name, auto_save=True)
                        await manager.broadcast_json({
                            "type": "model_changed",
                            "model_name": model_name,
                            "models": list_available_models()
                        })

                elif event_type == "stop_speaking":
                    voice_speaker.stop()
                    audio_ears.set_web_audio_playing(False)
                    await manager.broadcast_json({"type": "speech_stopped"})

                elif event_type == "speech_started":
                    audio_ears.set_web_audio_playing(True)

                elif event_type == "speech_stopped":
                    audio_ears.set_web_audio_playing(False)

                elif event_type == "mic_toggle":
                    active = await loop.run_in_executor(None, audio_ears.toggle_manual_listen)
                    await manager.broadcast_json({"type": "mic_state", "active": bool(active)})

                elif event_type == "mic_mute_toggle":
                    muted = await loop.run_in_executor(None, audio_ears.toggle_mute)
                    await manager.broadcast_json({"type": "mic_muted", "muted": bool(muted)})

                elif event_type == "open_github":
                    import webbrowser
                    gh_url = str(data.get("url") or config_manager.get("project_github_url", "https://github.com/paraxyoz/EVA-AI-Assistant")).strip()
                    webbrowser.open(gh_url)
            except Exception:
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


async def process_user_message_async(user_text: str):
    """Processes user input through the assistant, plays audio natively, and streams lip-sync data to the 3D Avatar Window."""
    loop = asyncio.get_running_loop()

    # Stop any ongoing speech when a new user request starts
    voice_speaker.stop()
    audio_ears.set_web_audio_playing(False)
    await manager.broadcast_json({"type": "speech_stopped"})

    response_text = await loop.run_in_executor(
        None,
        lambda: assistant_agent.process_user_input(
            user_text,
            blocking=True,
            play_local_audio=False
        )
    )

    my_req_id = assistant_agent.active_request_id
    if not response_text or assistant_agent.is_request_cancelled(my_req_id):
        return

    if config_manager.get("audio.play_response_audio", True) and response_text:
        voice_prof = config_manager.get("audio.voice_profile", "aoede")
        audio_bytes = await loop.run_in_executor(
            None,
            lambda: voice_speaker._synthesize_audio(response_text, voice_prof)
        )
        if audio_bytes and not assistant_agent.is_request_cancelled(my_req_id):
            voice_speaker.play_audio_bytes_async(audio_bytes, text=response_text)
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
            await manager.broadcast_json({
                "type": "audio_playback",
                "audio_base64": b64_audio,
                "text": response_text,
                "voice_eq": voice_speaker.get_voice_eq(),
                "played_by_backend": True
            })


def _extract_vrm_title(vrm_path: Path) -> Optional[str]:
    """Reads the VRM0/VRM1 title metadata from the GLB JSON chunk header if available."""
    import struct
    try:
        with open(vrm_path, "rb") as fp:
            header = fp.read(20)
            if len(header) < 20 or header[:4] != b"glTF":
                return None
            c0_len = struct.unpack("<I", header[12:16])[0]
            json_bytes = fp.read(min(c0_len, 5 * 1024 * 1024))
        gltf = json.loads(json_bytes)
        ext = gltf.get("extensions", {})
        if "VRMC_vrm" in ext:
            return ext["VRMC_vrm"].get("meta", {}).get("name")
        if "VRM" in ext:
            return ext["VRM"].get("meta", {}).get("title")
    except Exception:
        pass
    return None


def list_available_models() -> List[Dict[str, Any]]:
    """Returns list of all 3D (.vrm) and 2D Live2D (.model3.json / .model.json) models in data/models."""
    labels = {
        "sample_vrm1.vrm": "[3D VRM] Eva Classic VRM1",
        "alicia.vrm": "[3D VRM] Alicia Solid",
        "shizuku_live2d/shizuku.model.json": "[Live2D] Shizuku Sample (Cubism 2D)"
    }
    models = []
    # 1. Discover 3D VRM models
    for f in sorted(MODELS_DIR.glob("*.vrm"), key=lambda x: x.name):
        if f.name in labels:
            display_name = labels[f.name]
        else:
            vrm_title = _extract_vrm_title(f)
            display_name = f"[3D VRM] {vrm_title} ({f.stem})" if vrm_title else f"[3D VRM] {f.stem}"
        models.append({
            "name": display_name,
            "filename": f.name,
            "type": "vrm",
            "url": f"/models/{f.name}",
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
        })

    # 2. Discover Live2D models (.model3.json and .model.json) recursively in subfolders
    seen_rel = set()
    live2d_files = list(MODELS_DIR.rglob("*.model3.json")) + list(MODELS_DIR.rglob("*.model.json"))
    for f in sorted(live2d_files, key=lambda x: x.as_posix()):
        rel_path = f.relative_to(MODELS_DIR).as_posix()
        if rel_path in seen_rel:
            continue
        seen_rel.add(rel_path)
        parent_dir = f.parent
        if parent_dir.name.lower() in ("runtime", "model", "assets") and parent_dir.parent != MODELS_DIR:
            folder_name = parent_dir.parent.name
            size_root = parent_dir.parent
        else:
            folder_name = parent_dir.name if parent_dir != MODELS_DIR else f.stem
            size_root = parent_dir
        model_stem = f.name.replace(".model3.json", "").replace(".model.json", "")
        default_label = f"[Live2D] {folder_name} ({model_stem})"
        try:
            folder_bytes = sum(p.stat().st_size for p in size_root.rglob("*") if p.is_file())
        except Exception:
            folder_bytes = f.stat().st_size
        models.append({
            "name": labels.get(rel_path, default_label),
            "filename": rel_path,
            "type": "live2d",
            "url": f"/models/{rel_path}",
            "size_mb": round(folder_bytes / (1024 * 1024), 2)
        })

    return models


@app.get("/api/models")
async def get_models():
    return {
        "success": True,
        "models": list_available_models(),
        "models_dir": str(MODELS_DIR)
    }


@app.post("/api/models/open_dir")
async def open_models_dir():
    """Opens data/models in Windows Explorer so user can drop Live2D folders directly."""
    try:
        if os.name == "nt":
            os.startfile(str(MODELS_DIR))
        return {"success": True, "path": str(MODELS_DIR)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _pick_and_install_live2d_folder_sync() -> Dict[str, Any]:
    """Opens native Windows Folder Picker dialog and copies selected Live2D folder into data/models/."""
    import shutil
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected_dir = filedialog.askdirectory(
        title="Выберите папку с моделью Live2D (.model3.json / .model.json)"
    )
    root.destroy()

    if not selected_dir:
        return {"success": False, "cancelled": True}

    src_path = Path(selected_dir).resolve()
    if not src_path.exists() or not src_path.is_dir():
        return {"success": False, "detail": "Выбранная папка не существует"}

    # Check if folder contains a Live2D or VRM model file
    candidates = (
        list(src_path.rglob("*.model3.json"))
        + list(src_path.rglob("*.model.json"))
        + list(src_path.rglob("*.vrm"))
    )
    if not candidates:
        return {
            "success": False,
            "detail": f"В папке «{src_path.name}» не найден файл .model3.json или .model.json"
        }

    dest_dir = MODELS_DIR / src_path.name
    if src_path != dest_dir and not str(src_path).startswith(str(MODELS_DIR)):
        shutil.copytree(src_path, dest_dir, dirs_exist_ok=True)
    else:
        dest_dir = src_path

    installed_candidates = (
        list(dest_dir.rglob("*.model3.json"))
        + list(dest_dir.rglob("*.model.json"))
        + list(dest_dir.rglob("*.vrm"))
    )
    installed_candidates.sort(key=lambda p: (not p.name.lower().endswith(".model3.json"), len(p.parts)))
    chosen = installed_candidates[0]
    rel_model = chosen.relative_to(MODELS_DIR).as_posix()
    total_bytes = sum(p.stat().st_size for p in dest_dir.rglob("*") if p.is_file())

    return {
        "success": True,
        "filename": rel_model,
        "url": f"/models/{rel_model}",
        "size_mb": round(total_bytes / (1024 * 1024), 2)
    }


@app.post("/api/models/pick_folder")
async def pick_live2d_folder():
    """Opens native OS folder dialog to install a Live2D model directory with 1 click."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _pick_and_install_live2d_folder_sync)
    if not result.get("success"):
        return result

    rel_model = result["filename"]
    config_manager.set("vrm.active_model", rel_model, auto_save=True)
    all_models = list_available_models()
    result["models"] = all_models
    await manager.broadcast_json({
        "type": "model_changed",
        "model_name": rel_model,
        "models": all_models
    })
    return result


@app.post("/api/models/upload")
async def upload_model(file: UploadFile = File(...)):
    import zipfile
    import io

    fname = file.filename or "model.vrm"
    lower = fname.lower()
    content = await file.read()
    models_root = MODELS_DIR.resolve()

    if lower.endswith(".vrm"):
        safe_name = Path(fname).name
        dest = (MODELS_DIR / safe_name).resolve()
        if not dest.is_relative_to(models_root):
            raise HTTPException(status_code=400, detail="Некорректное имя файла модели")
        dest.write_bytes(content)
        rel_model = dest.name
    elif lower.endswith(".zip"):
        folder_stem = re.sub(r'[<>:"/\\|?*]+', "_", Path(fname).stem).strip(". ") or "live2d_model"
        target_dir = (MODELS_DIR / folder_stem).resolve()
        if not target_dir.is_relative_to(models_root):
            raise HTTPException(status_code=400, detail="Некорректное имя архива")
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for member in zf.infolist():
                member_dest = (target_dir / member.filename).resolve()
                if not member_dest.is_relative_to(target_dir):
                    raise HTTPException(status_code=400, detail="Обнаружен небезопасный путь внутри ZIP-архива")
            zf.extractall(target_dir)
        found = list(target_dir.rglob("*.model3.json")) + list(target_dir.rglob("*.model.json")) + list(target_dir.rglob("*.vrm"))
        if not found:
            raise HTTPException(status_code=400, detail="Внутри ZIP-архива не найден файл .model3.json, .model.json или .vrm")
        rel_model = found[0].relative_to(models_root).as_posix()
    else:
        raise HTTPException(status_code=400, detail="Поддерживаются файлы .vrm или .zip архив с папкой Live2D")

    config_manager.set("vrm.active_model", rel_model, auto_save=True)
    all_models = list_available_models()
    await manager.broadcast_json({
        "type": "model_changed",
        "model_name": rel_model,
        "models": all_models
    })

    return {
        "success": True,
        "filename": rel_model,
        "url": f"/models/{rel_model}",
        "size_mb": round(len(content) / (1024 * 1024), 2),
        "models": all_models
    }


@app.post("/api/models/upload_folder")
async def upload_live2d_folder(
    files: List[UploadFile] = File(...),
    paths: List[str] = Form(...)
):
    """Uploads an entire Live2D model directory from folder picker (webkitdirectory)."""
    if not files or not paths or len(files) != len(paths):
        raise HTTPException(status_code=400, detail="Некорректный список файлов папки Live2D")

    total_bytes = 0
    saved_paths: List[Path] = []
    models_root = MODELS_DIR.resolve()

    for upload_file, rel_str in zip(files, paths):
        clean_rel = rel_str.replace("\\", "/").lstrip("/")
        # Prevent path traversal and Windows drive specifiers
        parts = [p for p in clean_rel.split("/") if p and p not in (".", "..") and ":" not in p]
        if not parts:
            continue
        dest_path = MODELS_DIR.joinpath(*parts).resolve()
        if not dest_path.is_relative_to(models_root):
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        data = await upload_file.read()
        dest_path.write_bytes(data)
        total_bytes += len(data)
        saved_paths.append(dest_path)

    # Locate the Live2D model definition file (.model3.json or .model.json)
    model_candidates = [
        p for p in saved_paths
        if p.name.lower().endswith(".model3.json") or p.name.lower().endswith(".model.json") or p.name.lower().endswith(".vrm")
    ]
    if not model_candidates:
        raise HTTPException(
            status_code=400,
            detail="В выбранной папке не найден файл модели Live2D (.model3.json или .model.json)"
        )

    # Prefer .model3.json if multiple exist
    model_candidates.sort(key=lambda p: (not p.name.lower().endswith(".model3.json"), len(p.parts)))
    chosen = model_candidates[0]
    rel_model = chosen.relative_to(MODELS_DIR).as_posix()

    config_manager.set("vrm.active_model", rel_model, auto_save=True)
    all_models = list_available_models()
    await manager.broadcast_json({
        "type": "model_changed",
        "model_name": rel_model,
        "models": all_models
    })

    return {
        "success": True,
        "filename": rel_model,
        "url": f"/models/{rel_model}",
        "size_mb": round(total_bytes / (1024 * 1024), 2),
        "models": all_models
    }


@app.get("/api/system/status")
async def get_system_status():
    hw = SystemProfiler.get_hardware_info()
    time_info = OSController.get_system_time_info()
    return {
        "success": True,
        "hardware": hw,
        "time": time_info,
        "disks": SystemProfiler.get_disks_info()
    }


@app.post("/api/voice/test")
async def test_voice(
    profile: str = Form(...),
    eleven_voice_id: Optional[str] = Form(None),
    eleven_key: Optional[str] = Form(None)
):
    config_manager.set("audio.voice_profile", profile, auto_save=False)
    if eleven_key and eleven_key.strip():
        config_manager.set("audio.elevenlabs.api_key", eleven_key.strip(), auto_save=False)
        config_manager.set("audio.elevenlabs_api_key", eleven_key.strip(), auto_save=False)
    if eleven_voice_id and eleven_voice_id.strip():
        config_manager.set("audio.elevenlabs.voice_id", eleven_voice_id.strip(), auto_save=False)
        config_manager.set("audio.elevenlabs_voice_id", eleven_voice_id.strip(), auto_save=False)
    config_manager.save_config()

    is_jarvis = profile == "jarvis" or str(config_manager.get("ai_mode", "conversational")).strip().lower() in ("jarvis", "passive")
    effective_prof = "jarvis" if is_jarvis else profile
    test_phrase = (
        "Да, сэр. Все системы функционируют в штатном режиме. Голосовой модуль Джарвиса готов к работе."
        if is_jarvis
        else "Привет! Я Ева. Голосовой профиль и эквалайзер успешно применены."
    )
    loop = asyncio.get_running_loop()
    audio_bytes = await loop.run_in_executor(
        None,
        lambda: voice_speaker._synthesize_audio(test_phrase, effective_prof, bypass_cache=True)
    )
    if audio_bytes:
        voice_speaker.play_audio_bytes_async(audio_bytes, text=test_phrase)
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        await manager.broadcast_json({
            "type": "audio_playback",
            "audio_base64": b64,
            "text": test_phrase,
            "voice_eq": voice_speaker.get_voice_eq(),
            "played_by_backend": True
        })
        return {"success": True, "audio_base64": b64, "text": test_phrase}
    return {"success": False, "error": "Не удалось синтезировать голос"}


@app.post("/api/voice/eq")
async def update_voice_eq(payload: Dict[str, Any]):
    """Saves Voice Equalizer settings (pitch, speed, bass, treble, volume) and broadcasts to Avatar AudioSyncEngine."""
    current_eq = voice_speaker.get_voice_eq()
    pitch = max(-12, min(12, int(round(float(payload.get("pitch", current_eq.get("pitch", 0)))))))
    speed = max(0.7, min(1.4, round(float(payload.get("speed", current_eq.get("speed", 1.0))), 2)))
    bass = max(-12, min(12, int(round(float(payload.get("bass", current_eq.get("bass", 0)))))))
    treble = max(-12, min(12, int(round(float(payload.get("treble", current_eq.get("treble", 0)))))))
    volume = max(0, min(150, int(round(float(payload.get("volume", current_eq.get("volume", 100)))))))

    eq = {"pitch": pitch, "speed": speed, "bass": bass, "treble": treble, "volume": volume}
    config_manager.set("audio.eq", eq, auto_save=True)
    voice_speaker.update_live_volume(volume)
    await manager.broadcast_json({"type": "voice_eq_changed", "eq": eq})
    return {"success": True, "eq": eq}


@app.post("/api/avatar/visibility")
async def set_avatar_visibility(payload: Dict[str, Any]):
    """Toggles or sets whether the 3D/Live2D Avatar Desktop Window is visible on screen."""
    if "visible" in payload:
        visible = bool(payload["visible"])
    else:
        visible = not bool(config_manager.get("avatar.show_on_desktop", True))

    config_manager.set("avatar.show_on_desktop", visible, auto_save=True)
    agent_signals.emit_safe("window_action", "show_avatar" if visible else "hide_avatar")
    await manager.broadcast_json({"type": "avatar_visibility", "visible": visible})
    return {"success": True, "visible": visible}


@app.post("/api/ai_mode")
@app.post("/api/ai/mode")
async def set_ai_mode(payload: Dict[str, Any]):
    """Switches AI Personality Mode between 'conversational' (Ева) and 'jarvis' / 'passive' (J.A.R.V.I.S.)."""
    raw_mode = str(payload.get("ai_mode") or payload.get("mode") or "conversational").strip().lower()
    if raw_mode not in ("conversational", "jarvis", "passive"):
        raw_mode = "conversational"
    config_manager.set("ai_mode", raw_mode, auto_save=True)
    await manager.broadcast_json({"type": "ai_mode_changed", "ai_mode": raw_mode})
    return {"success": True, "ai_mode": raw_mode}


@app.post("/api/mic/mute")
async def set_mic_mute(payload: Dict[str, Any]):
    """Mutes or unmutes the microphone completely so EVA does not listen when muted."""
    if "muted" in payload:
        muted = audio_ears.set_muted(bool(payload["muted"]))
    else:
        muted = audio_ears.toggle_mute()
    await manager.broadcast_json({"type": "mic_muted", "muted": bool(muted)})
    return {"success": True, "muted": bool(muted)}


@app.get("/api/audio/devices")
async def get_audio_devices():
    return {
        "success": True,
        "output_device": config_manager.get("audio.output_device", "auto"),
        "input_device_index": config_manager.get("audio.input_device_index", 1),
        "output_devices": voice_speaker.list_output_devices(),
        "input_devices": audio_ears.list_input_devices(),
    }


@app.post("/api/audio/devices")
async def update_audio_devices(payload: Dict[str, Any]):
    if "output_device" in payload:
        out_dev = str(payload["output_device"] or "auto").strip()
        config_manager.set("audio.output_device", out_dev, auto_save=True)
    if "input_device_index" in payload and payload["input_device_index"] is not None:
        try:
            in_idx = int(payload["input_device_index"])
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: audio_ears.restart_with_device(in_idx))
        except Exception:
            pass
    return {
        "success": True,
        "output_device": config_manager.get("audio.output_device", "auto"),
        "input_device_index": config_manager.get("audio.input_device_index", 1),
    }


@app.get("/api/commands/tree")
async def get_commands_tree():
    from tools.app_commands import custom_commands_store
    from tools.macro_recorder import macro_recorder
    folders = custom_commands_store.get_full_commands_tree()
    return {
        "success": True,
        "folders": folders,
        "packs": [f for f in folders if f.get("scope") == "packs"],
        "commands": custom_commands_store.list_commands(),
        "macros": macro_recorder.list_macros()
    }


@app.get("/api/custom_commands")
async def get_custom_commands():
    from tools.app_commands import custom_commands_store, AppCommandController
    from tools.macro_recorder import macro_recorder
    installed_games = AppCommandController.discover_installed_steam_games()
    games_list = [{"appid": appid, "name": title} for _, (appid, title) in sorted(installed_games.items())]
    folders = custom_commands_store.get_full_commands_tree()
    return {
        "success": True,
        "commands": custom_commands_store.list_commands(),
        "folders": folders,
        "packs": [f for f in folders if f.get("scope") == "packs"],
        "macros": macro_recorder.list_macros(),
        "steam_games": games_list
    }


@app.post("/api/custom_commands")
async def create_custom_command(payload: Dict[str, Any]):
    from tools.app_commands import custom_commands_store
    trigger = str(payload.get("trigger", "")).strip()
    action_type = str(payload.get("action_type", "open_app")).strip()
    target = str(payload.get("target", "")).strip()
    response = str(payload.get("response", "")).strip()
    name = str(payload.get("name", "")).strip()
    folder = str(payload.get("folder", "Мои команды")).strip()
    scope = str(payload.get("scope", "pc")).strip()
    steps = payload.get("steps")
    require_confirmation = bool(payload.get("require_confirmation", False))
    confirm_timeout_sec = int(payload.get("confirm_timeout_sec", 10) or 10)
    cmd_id = payload.get("id")

    has_steps = isinstance(steps, list) and len(steps) > 0
    if not trigger or (not target and not has_steps):
        raise HTTPException(status_code=400, detail="Укажите ключевую фразу-триггер и хотя бы одно действие")

    item = custom_commands_store.add_command(
        trigger=trigger,
        action_type=action_type,
        target=target,
        response=response,
        name=name,
        folder=folder,
        scope=scope,
        steps=steps if has_steps else None,
        require_confirmation=require_confirmation,
        confirm_timeout_sec=confirm_timeout_sec,
        cmd_id=str(cmd_id) if cmd_id else None,
    )
    all_cmds = custom_commands_store.list_commands()
    all_folders = custom_commands_store.get_full_commands_tree()
    await manager.broadcast_json({
        "type": "custom_commands_updated",
        "commands": all_cmds,
        "folders": all_folders
    })
    return {"success": True, "command": item, "commands": all_cmds, "folders": all_folders}


@app.delete("/api/custom_commands/{cmd_id}")
async def remove_custom_command(cmd_id: str):
    from tools.app_commands import custom_commands_store
    deleted = custom_commands_store.delete_command(cmd_id)
    all_cmds = custom_commands_store.list_commands()
    all_folders = custom_commands_store.get_full_commands_tree()
    await manager.broadcast_json({
        "type": "custom_commands_updated",
        "commands": all_cmds,
        "folders": all_folders
    })
    return {"success": deleted, "commands": all_cmds, "folders": all_folders}


@app.put("/api/custom_commands/{cmd_id}")
async def update_custom_command_endpoint(cmd_id: str, payload: Dict[str, Any]):
    from tools.app_commands import custom_commands_store
    item = custom_commands_store.update_command(cmd_id, payload)
    all_cmds = custom_commands_store.list_commands()
    all_folders = custom_commands_store.get_full_commands_tree()
    await manager.broadcast_json({
        "type": "custom_commands_updated",
        "commands": all_cmds,
        "folders": all_folders
    })
    return {"success": True, "command": item, "commands": all_cmds, "folders": all_folders}


@app.post("/api/custom_commands/{cmd_id}/toggle")
async def toggle_custom_command_endpoint(cmd_id: str, payload: Optional[Dict[str, Any]] = None):
    from tools.app_commands import custom_commands_store
    desired_enabled = payload.get("enabled") if payload and isinstance(payload, dict) and "enabled" in payload else None
    res = custom_commands_store.toggle_command(cmd_id, enabled=desired_enabled)
    all_cmds = custom_commands_store.list_commands()
    all_folders = custom_commands_store.get_full_commands_tree()
    await manager.broadcast_json({
        "type": "custom_commands_updated",
        "commands": all_cmds,
        "folders": all_folders
    })
    return {"success": True, "result": res, "commands": all_cmds, "folders": all_folders}


@app.post("/api/custom_commands/restore_defaults")
async def restore_default_commands_endpoint():
    from tools.app_commands import custom_commands_store
    res = custom_commands_store.restore_builtin_commands()
    all_cmds = custom_commands_store.list_commands()
    all_folders = custom_commands_store.get_full_commands_tree()
    await manager.broadcast_json({
        "type": "custom_commands_updated",
        "commands": all_cmds,
        "folders": all_folders
    })
    return {"success": True, "result": res, "commands": all_cmds, "folders": all_folders}


@app.post("/api/commands/execute/{cmd_id}")
async def execute_command_by_id_endpoint(cmd_id: str):
    from tools.app_commands import custom_commands_store
    loop = asyncio.get_running_loop()
    reply = await loop.run_in_executor(None, lambda: custom_commands_store.execute_by_id(cmd_id))
    if reply:
        agent_signals.emit_safe("response_generated", reply)
        if config_manager.get("audio.play_response_audio", True):
            voice_prof = config_manager.get("audio.voice_profile", "aoede")
            audio_bytes = await loop.run_in_executor(
                None,
                lambda: voice_speaker._synthesize_audio(reply, voice_prof)
            )
            if audio_bytes:
                voice_speaker.play_audio_bytes_async(audio_bytes, text=reply)
                b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                await manager.broadcast_json({
                    "type": "audio_playback",
                    "audio_base64": b64_audio,
                    "text": reply,
                    "voice_eq": voice_speaker.get_voice_eq(),
                    "played_by_backend": True
                })
    return {"success": bool(reply), "reply": reply or "Команда не найдена"}


@app.post("/api/custom_commands/confirm/{confirm_id}")
async def resolve_command_confirmation(confirm_id: str, payload: Dict[str, Any]):
    from tools.app_commands import custom_commands_store
    approved = bool(payload.get("approved", False))
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None,
        lambda: custom_commands_store.resolve_confirmation(confirm_id, approved)
    )
    if res.get("executed") and res.get("reply"):
        reply_txt = res["reply"]
        voice_prof = config_manager.get("audio.voice_profile", "aoede")
        audio_bytes = await loop.run_in_executor(
            None,
            lambda: voice_speaker._synthesize_audio(reply_txt, voice_prof)
        )
        if audio_bytes:
            voice_speaker.play_audio_bytes_async(audio_bytes, text=reply_txt)
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
            await manager.broadcast_json({
                "type": "audio_playback",
                "audio_base64": b64_audio,
                "text": reply_txt,
                "voice_eq": voice_speaker.get_voice_eq(),
                "played_by_backend": True
            })
    return res


@app.get("/api/macros")
async def list_recorded_macros():
    from tools.macro_recorder import macro_recorder
    return {"success": True, "macros": macro_recorder.list_macros()}


@app.post("/api/macros/record/start")
async def start_macro_recording(payload: Dict[str, Any]):
    from tools.macro_recorder import macro_recorder
    name = str(payload.get("name", "Запись действий")).strip()
    countdown = float(payload.get("countdown_sec", 2.0))
    started = macro_recorder.start_recording(name=name, countdown_sec=countdown)
    return {"success": started, "recording": macro_recorder.is_recording}


@app.post("/api/macros/record/stop")
async def stop_macro_recording():
    from tools.macro_recorder import macro_recorder
    loop = asyncio.get_running_loop()
    saved = await loop.run_in_executor(None, macro_recorder.stop_recording)
    all_macros = macro_recorder.list_macros()
    await manager.broadcast_json({"type": "macros_updated", "macros": all_macros, "macro": saved})
    return {"success": True, "macro": saved, "macros": all_macros}


@app.delete("/api/macros/{macro_id}")
async def delete_recorded_macro(macro_id: str):
    from tools.macro_recorder import macro_recorder
    deleted = macro_recorder.delete_macro(macro_id)
    all_macros = macro_recorder.list_macros()
    await manager.broadcast_json({"type": "macros_updated", "macros": all_macros})
    return {"success": deleted, "macros": all_macros}


@app.post("/api/github/open")
async def open_github_repository(payload: Optional[Dict[str, Any]] = None):
    import webbrowser
    url = str((payload or {}).get("url") or config_manager.get("project_github_url", "https://github.com/paraxyoz/EVA-AI-Assistant")).strip()
    webbrowser.open(url)
    return {"success": True, "url": url}


def _pick_exe_or_shortcut_sync() -> Dict[str, Any]:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askopenfilename(
        title="Выберите программу (.exe), ярлык (.lnk) или файл",
        filetypes=[("Программы и ярлыки", "*.exe *.lnk *.bat *.cmd *.url"), ("Все файлы", "*.*")]
    )
    root.destroy()
    if not selected:
        return {"success": False, "cancelled": True}
    return {"success": True, "path": str(Path(selected).resolve())}


@app.post("/api/custom_commands/pick_app")
async def pick_custom_command_app():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _pick_exe_or_shortcut_sync)


@app.post("/api/llm/test")
async def test_llm_connection(payload: Dict[str, Any]):
    from core.llm_provider import llm_client

    prov = payload.get("provider", config_manager.get("llm_provider", "ollama"))
    api_base = payload.get("api_base", "").strip()
    api_key = payload.get("api_key", "").strip()
    model = payload.get("model", "").strip()

    config_manager.set("llm_provider", prov, auto_save=False)
    if api_base:
        config_manager.set(f"providers.{prov}.api_base", api_base, auto_save=False)
    if api_key:
        config_manager.set(f"providers.{prov}.api_key", api_key, auto_save=False)
    if model:
        config_manager.set(f"providers.{prov}.model", model, auto_save=False)
        config_manager.set(f"providers.{prov}.vision_model", model, auto_save=False)
    config_manager.save_config()

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, llm_client.test_connection)
    return result


@app.post("/api/config")
async def update_config(payload: Dict[str, Any]):
    for k, v in payload.items():
        config_manager.set(k, v, auto_save=False)
    config_manager.save_config()
    await manager.broadcast_json({
        "type": "config_updated",
        "voice_profile": config_manager.get("audio.voice_profile", "aoede"),
        "elevenlabs_voice_id": config_manager.get("audio.elevenlabs_voice_id", "cgSgspJ2msm6clMCkdW9"),
        "llm_provider": config_manager.get("llm_provider", "ollama"),
        "ai_mode": config_manager.get("ai_mode", "conversational")
    })
    return {"success": True}


def run_server(host: str = "127.0.0.1", port: int = 7865):
    uvicorn.run(app, host=host, port=port, log_level="error", log_config=None)
