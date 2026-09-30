"""
Master Agent Engine for EVA AI Assistant.
Features:
- Instant Reflex Engine (<15ms response for custom commands, deep app automation, compound multi-tasking commands, and poses)
- Multi-Command Splitter: executes compound requests like "закрой вкладку с ютубом и открой стим" sequentially
- Stateful Action Context (`action_context`): remembers music/app state for follow-ups ("выключи", "включи обратно", "закрой его")
- Preemptive Request Cancellation (`begin_new_request` / `is_request_cancelled`): new "Ева ..." interrupts and cancels any in-flight generation
- Natural, varied Passive Mode ("Пассивный") & Conversational Mode ("Общительный")
"""

import json
import os
import time
import uuid
import re
import threading
import psutil
from enum import Enum
from typing import Optional, List, Dict, Any

from config import config_manager
from memory.db import memory_db
from tools.os_control import OSController
from tools.gui_control import GUIController
from tools.app_commands import AppCommandController, custom_commands_store, action_context
from tools.web_search import web_search_engine
from tools.registry import ToolDispatcher
from perception.eyes import screen_eyes
from expression.voice import voice_speaker
from core.prompts import build_system_prompt
from core.llm_provider import llm_client
from core.events import agent_signals


class AgentState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    WORKING = "WORKING"
    ERROR = "ERROR"


class AssistantAgent:
    """Central intelligent agent loop with multi-tasking reflex fast-path, context memory, and preemptive cancellation."""

    ACTION_KEYWORDS = (
        "открой", "запусти", "вруби", "включи", "выключи", "закрой", "убей", "заверши",
        "удали", "создай", "сохрани в файл", "запиши в файл", "прочитай файл", "файл",
        "папк", "директори", "диск", "процесс", "диспетчер", "калькулятор", "блокнот",
        "браузер", "проводник", "терминал", "консоль", "powershell", "cmd", "команд",
        "скрипт", "нажми", "клик", "мышь", "клавиш", "окно", "окна", "сверни", "разверни",
        "перезагруз", "спящий режим", "заблокируй", "громкость", "громче", "тише", "звук",
        "запомни", "найди на пк", "найди программу", "найди файл", "установи", "вкладк"
    )

    DIRECT_APP_MAP = {
        "диспетчер задач": ("taskmgr", "Диспетчер задач запущен."),
        "диспетчер": ("taskmgr", "Диспетчер задач запущен."),
        "taskmgr": ("taskmgr", "Диспетчер задач запущен."),
        "калькулятор": ("calc", "Калькулятор открыт."),
        "calc": ("calc", "Калькулятор открыт."),
        "блокнот": ("notepad", "Блокнот открыт."),
        "notepad": ("notepad", "Блокнот открыт."),
        "проводник": ("explorer", "Проводник открыт."),
        "мой компьютер": ("explorer", "Проводник открыт."),
        "этот компьютер": ("explorer", "Проводник открыт."),
        "загрузки": (os.path.join(os.path.expanduser("~"), "Downloads"), "Папка Загрузки открыта."),
        "папку загрузки": (os.path.join(os.path.expanduser("~"), "Downloads"), "Папка Загрузки открыта."),
        "рабочий стол": (os.path.join(os.path.expanduser("~"), "Desktop"), "Папка Рабочий стол открыта."),
        "документы": (os.path.join(os.path.expanduser("~"), "Documents"), "Папка Документы открыта."),
        "настройки": ("ms-settings:", "Параметры Windows открыты."),
        "параметры": ("ms-settings:", "Параметры Windows открыты."),
        "панель управления": ("control", "Панель управления открыта."),
        "командную строку": ("cmd", "Командная строка открыта."),
        "командная строка": ("cmd", "Командная строка открыта."),
        "терминал": ("cmd", "Терминал открыт."),
        "консоль": ("cmd", "Консоль открыта."),
        "cmd": ("cmd", "Командная строка открыта."),
        "powershell": ("powershell", "PowerShell запущен."),
        "браузер": ("chrome", "Браузер запущен."),
        "хром": ("chrome", "Google Chrome запущен."),
        "chrome": ("chrome", "Google Chrome запущен."),
        "ютуб": ("https://www.youtube.com", "Открываю YouTube."),
        "youtube": ("https://www.youtube.com", "Открываю YouTube."),
        "гугл": ("https://www.google.com", "Открываю Google."),
        "google": ("https://www.google.com", "Открываю Google."),
        "яндекс": ("https://ya.ru", "Открываю Яндекс."),
        "гитхаб": ("https://github.com", "Открываю GitHub."),
        "github": ("https://github.com", "Открываю GitHub."),
        "телеграм": ("telegram", "Запускаю Telegram."),
        "телегу": ("telegram", "Запускаю Telegram."),
        "тг": ("telegram", "Запускаю Telegram."),
        "telegram": ("telegram", "Запускаю Telegram."),
        "дискорд": ("discord", "Запускаю Discord."),
        "дс": ("discord", "Запускаю Discord."),
        "discord": ("discord", "Запускаю Discord."),
        "стим": ("steam", "Запускаю Steam."),
        "steam": ("steam", "Запускаю Steam."),
        "спотифай": ("spotify", "Запускаю Spotify."),
        "spotify": ("spotify", "Запускаю Spotify."),
        "обс": ("obs64", "Запускаю OBS Studio."),
        "obs": ("obs64", "Запускаю OBS Studio."),
        "блендер": ("blender", "Запускаю Blender."),
        "blender": ("blender", "Запускаю Blender."),
        "вс код": ("code", "Запускаю VS Code."),
        "vscode": ("code", "Запускаю VS Code."),
        "vs code": ("code", "Запускаю VS Code."),
        "фигму": ("figma", "Запускаю Figma."),
        "фигма": ("figma", "Запускаю Figma."),
        "figma": ("figma", "Запускаю Figma."),
        "фотошоп": ("photoshop", "Запускаю Photoshop."),
        "photoshop": ("photoshop", "Запускаю Photoshop."),
        "пейнт": ("mspaint", "Открываю Paint."),
        "paint": ("mspaint", "Открываю Paint."),
    }

    APP_PROCESS_MAP = {
        "taskmgr": ("Диспетчер задач", "Taskmgr.exe", "app"),
        "calc": ("Калькулятор", "CalculatorApp.exe", "app"),
        "notepad": ("Блокнот", "notepad.exe", "app"),
        "explorer": ("Проводник", "explorer.exe", "app"),
        "cmd": ("Командная строка", "cmd.exe", "app"),
        "powershell": ("PowerShell", "powershell.exe", "app"),
        "chrome": ("Браузер", "chrome.exe", "browser"),
        "https://www.youtube.com": ("YouTube", "chrome.exe", "browser"),
        "https://www.google.com": ("Google", "chrome.exe", "browser"),
        "https://ya.ru": ("Яндекс", "chrome.exe", "browser"),
        "https://github.com": ("GitHub", "chrome.exe", "browser"),
        "telegram": ("Telegram", "Telegram.exe", "app"),
        "discord": ("Discord", "Discord.exe", "discord"),
        "steam": ("Steam", "steam.exe", "steam"),
        "mspaint": ("Paint", "mspaint.exe", "app"),
    }

    JARVIS_PREFIX_POOL = (
        "Да, сэр. Выполняю",
        "Выполняю, сэр",
        "Будет сделано, сэр",
        "Сию секунду, сэр. Выполняю",
        "Принято, сэр. Выполняю",
        "Как прикажете, сэр. Сделано",
        "Готово, сэр. Сделано",
        "Есть, сэр. Выполняю",
    )
    PASSIVE_PREFIX_POOL = JARVIS_PREFIX_POOL

    JARVIS_GREETING_POOL = (
        "Да, сэр. К вашим услугам.",
        "На связи, сэр. Все системы в норме.",
        "Доброго времени суток, сэр. Готов к работе.",
        "Слушаю вас, сэр. Все системы активны.",
    )

    _COMPOUND_SPLIT_RE = re.compile(
        r"(?:,\s*и\s+|\s+и\s+потом\s+|\s+а\s+потом\s+|\s+а\s+затем\s+|\s+затем\s+|\s+после\s+чего\s+|;\s*|"
        r"\s+и\s+(?=(?:открой|запусти|включи|вруби|закрой|выключи|выруби|останови|сделай|поставь|установи|сверни|найди|покажи|скрой|сядь|встань|станцуй|покрутись)\b))",
        flags=re.IGNORECASE
    )

    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self._state = AgentState.IDLE
        self._lock = threading.Lock()
        self._active_request_id: int = 0
        self._passive_idx: int = 0
        self._current_outfit = "default"
        self._current_pose = "stand"
        self._layers: Dict[str, bool] = {
            "top": True,
            "bottom": True,
            "shoes": True,
            "accessories": True,
            "underwear": True,
            "nsfw": False,
        }

        try:
            agent_signals.speech_started.connect(lambda: self._safe_set_state(AgentState.SPEAKING))
            agent_signals.speech_stopped.connect(self._on_speech_stopped)
        except Exception:
            pass

    def begin_new_request(self) -> int:
        """
        Starts a new request and immediately invalidates/cancels any in-flight generation
        or active TTS playback from an older request.
        """
        with self._lock:
            self._active_request_id += 1
            req_id = self._active_request_id
        try:
            voice_speaker.stop()
        except Exception:
            pass
        return req_id

    def is_request_cancelled(self, req_id: int) -> bool:
        """Returns True if a newer request has arrived since `req_id` started."""
        return req_id != self._active_request_id

    @property
    def active_request_id(self) -> int:
        return self._active_request_id

    def _emit_avatar(
        self,
        pose: Optional[str] = None,
        outfit: Optional[str] = None,
        emotion: Optional[str] = None,
        layers: Optional[Dict[str, bool]] = None
    ):
        payload: Dict[str, Any] = {}
        if pose:
            self._current_pose = pose
            payload["pose"] = pose
        if outfit:
            self._current_outfit = outfit
            payload["outfit"] = outfit
        if emotion:
            payload["emotion"] = emotion
        if layers:
            self._layers.update(layers)
            payload["layers"] = dict(self._layers)
        if payload:
            agent_signals.emit_safe("avatar_action", payload)

    def _on_speech_stopped(self):
        try:
            from perception.ears import audio_ears
            if audio_ears.is_active_listening:
                self._safe_set_state(AgentState.LISTENING)
                return
        except Exception:
            pass
        self._safe_set_state(AgentState.IDLE)

    @property
    def state(self) -> AgentState:
        return self._state

    def set_state(self, new_state: AgentState):
        self._safe_set_state(new_state)

    def _safe_set_state(self, new_state: AgentState):
        if self._state != new_state:
            self._state = new_state
            agent_signals.emit_safe("state_changed", new_state.value)

    def log(self, message: str):
        """Prints log safely and emits thread-safe signal to Web Studio."""
        try:
            print(f"[Agent] {message}")
        except Exception:
            pass
        agent_signals.emit_safe("thought_logged", message)

    def _needs_tools(self, user_text: str) -> bool:
        """Returns True only when the user message implies a system/OS action or memory command."""
        u_low = user_text.lower()
        return any(kw in u_low for kw in self.ACTION_KEYWORDS)

    @staticmethod
    def _is_jarvis_mode() -> bool:
        return str(config_manager.get("ai_mode", "conversational")).strip().lower() in ("jarvis", "passive")

    @staticmethod
    def _to_jarvis_masculine(text: str) -> str:
        if not text:
            return ""
        replacements = (
            ("Закрыла ", "Закрыл "),
            ("закрыла ", "закрыл "),
            ("Открыла ", "Открыл "),
            ("открыла ", "открыл "),
            ("Запустила ", "Запустил "),
            ("запустила ", "запустил "),
            ("Включила ", "Включил "),
            ("включила ", "включил "),
            ("Выключила ", "Выключил "),
            ("выключила ", "выключил "),
            ("Установила ", "Установил "),
            ("установила ", "установил "),
            ("Поставила ", "Установил "),
            ("поставила ", "установил "),
            ("Свернула ", "Свернул "),
            ("свернула ", "свернул "),
            ("Развернула ", "Развернул "),
            ("развернула ", "развернул "),
            ("Нашла ", "Нашёл "),
            ("нашла ", "нашёл "),
            ("Запомнила", "Запомнил"),
            ("запомнила", "запомнил"),
            ("Переключилась ", "Переключился "),
            ("переключилась ", "переключился "),
            ("Готова ", "Готов "),
            ("готова ", "готов "),
            ("рада ", "рад "),
        )
        out = text
        for old, new in replacements:
            out = out.replace(old, new)
        return out

    def _format_mode_reply(self, conversational_reply: str, passive_reply: Optional[str] = None) -> str:
        """
        Formats the assistant's reply according to the active AI mode:
        - 'conversational': Warm, lively Eva companion reply.
        - 'jarvis' (or 'passive'): Crisp, masculine J.A.R.V.I.S. butler reply ("Да, сэр. Выполняю", etc.).
        """
        if not self._is_jarvis_mode():
            return conversational_reply

        # If an explicit non-action J.A.R.V.I.S. response is given (greetings, status, poses), return it directly
        if passive_reply:
            return self._to_jarvis_masculine(passive_reply.strip())

        prefix = self.JARVIS_PREFIX_POOL[self._passive_idx % len(self.JARVIS_PREFIX_POOL)]
        self._passive_idx += 1

        clean_action = self._to_jarvis_masculine((conversational_reply or "").strip())
        if not clean_action:
            return f"{prefix}."
        if clean_action.endswith("?"):
            return clean_action
        if "сэр" in clean_action.lower():
            return clean_action
        return f"{prefix}. {clean_action}"

    def _split_compound_commands(self, user_text: str) -> List[str]:
        """Splits a multi-action command ('закрой вкладку с ютубом, и открой стим') into ordered sub-commands."""
        cleaned = user_text.strip()
        if not cleaned:
            return []
        parts = [p.strip(" ,.!?;:") for p in self._COMPOUND_SPLIT_RE.split(cleaned) if p and p.strip(" ,.!?;:")]
        return parts if len(parts) > 1 else [cleaned]

    def _try_instant_reflex(self, user_text: str) -> Optional[str]:
        """
        Instant <15ms execution for single or compound (multi-tasking) commands.
        If the user gave multiple commands joined by 'и' / 'а потом', executes all of them in sequence.
        """
        if not user_text or not user_text.strip():
            return None

        # Check if this is a compound multi-tasking command (e.g., "закрой вкладку с ютубом, и открой стим")
        sub_commands = self._split_compound_commands(user_text)
        if len(sub_commands) > 1:
            executed_replies: List[str] = []
            for idx, sub_cmd in enumerate(sub_commands):
                if idx > 0:
                    time.sleep(0.15)
                sub_reply = self._try_single_reflex(sub_cmd, raw_mode=True)
                if sub_reply is not None:
                    executed_replies.append(sub_reply.rstrip(".!"))
            if executed_replies:
                combined = ", ".join(executed_replies) + "."
                return self._format_mode_reply(combined)

        return self._try_single_reflex(user_text, raw_mode=False)

    def _try_single_reflex(self, user_text: str, raw_mode: bool = False) -> Optional[str]:
        """Executes a single instant reflex command. If `raw_mode=True`, returns the unformatted action text."""
        fmt = (lambda c, p=None: c) if raw_mode else self._format_mode_reply

        u_clean = re.sub(r"[.,!?;:\"'()]+", "", user_text.lower()).strip()
        for ww in ("ева ", "эва ", "дева ", "ива ", "лево ", "ассистент ", "джарвис ", "компьютер ", "слушай "):
            if u_clean.startswith(ww):
                u_clean = u_clean[len(ww):].strip()

        u_clean = u_clean.replace("ё", "е")
        u_core = re.sub(
            r"\b(пожалуйста|плиз|пж|будь добра|сейчас|быстренько|давай|ну ка|ну-ка|ко мне|передо мной|для меня|ева)\b",
            "",
            u_clean
        )
        u_core = re.sub(r"\s+", " ", u_core).strip()

        # -1. Check if there is an active Pending Command Confirmation waiting for user approval/cancel
        pending_confs = custom_commands_store.get_pending_confirmations()
        if pending_confs:
            latest_conf = pending_confs[-1]
            cid = latest_conf["confirm_id"]
            if u_core in ("да", "подтверждаю", "выполняй", "запускай", "ок", "хорошо", "согласен"):
                res = custom_commands_store.resolve_confirmation(cid, approved=True)
                return fmt(res.get("reply", "Команда подтверждена и выполнена."))
            if u_core in ("нет", "отмена", "отменить", "не надо", "стоп"):
                custom_commands_store.resolve_confirmation(cid, approved=False)
                return fmt("Выполнение команды отменено.")

        # 0. User-defined Custom Commands & Multi-Step Scenarios
        custom_hit = custom_commands_store.match_and_execute(user_text)
        if custom_hit is not None:
            self.log(f"[Инструмент] Выполнена пользовательская команда: \"{user_text}\"")
            return fmt(custom_hit)

        # 0a. Live Weather Fast-Path ("какая сейчас погода", "погода в Москве")
        weather_ans = web_search_engine.try_instant_answer(user_text)
        if weather_ans is not None:
            self.log(f"[Интернет] Погода: {weather_ans}")
            return f"{weather_ans.rstrip('.')} , сэр.".replace(" ,", ",") if self._is_jarvis_mode() else weather_ans

        # 0a-2. Microphone Mute by voice ("замуть микрофон евы", "не слушай меня")
        if any(k in u_clean for k in ("не слушай меня", "выключи слух", "замуть свой микрофон", "выключи свой микрофон")):
            from perception.ears import audio_ears
            audio_ears.set_muted(True)
            return fmt(
                "Микрофон выключен. Я больше вас не слышу, пока вы не включите микрофон в панели.",
                "Да, сэр. Аудиомониторинг отключён."
            )

        norm_text = AppCommandController.try_execute(user_text)
        if norm_text is not None:
            self.log(f"[Инструмент] Быстрая команда приложения: \"{user_text}\"")
            return fmt(norm_text)

        # 0b. AI Mode Switch by voice ("включи режим джарвиса", "режим jarvis", "включи общительный режим")
        if any(k in u_clean for k in (
            "режим джарвис", "режим джарвиса", "включи джарвис", "включи джарвиса",
            "ты теперь джарвис", "jarvis режим", "режим jarvis",
            "пассивный режим", "исполнительный режим", "режим пассивный"
        )):
            config_manager.set("ai_mode", "jarvis", auto_save=True)
            return "Режим Джарвиса активирован. К вашим услугам, сэр."
        if any(k in u_clean for k in (
            "общительный режим", "разговорный режим", "режим общительный",
            "режим евы", "режим ева", "верни еву", "включи еву"
        )):
            config_manager.set("ai_mode", "conversational", auto_save=True)
            return "Переключилась в общительный режим! Теперь можем болтать свободно."

        # 0c. Avatar Visibility Toggle by voice/text
        if any(k in u_clean for k in ("скрой аватар", "выключи аватар", "выключи модель", "убери модель", "скрой модель")):
            config_manager.set("avatar.show_on_desktop", False, auto_save=True)
            agent_signals.emit_safe("window_action", "hide_avatar")
            return fmt("Аватар скрыт с экрана.", "Да, сэр. Голограмма скрыта с экрана.")

        if any(k in u_clean for k in ("покажи аватар", "включи аватар", "включи модель", "верни модель", "покажи модель")):
            config_manager.set("avatar.show_on_desktop", True, auto_save=True)
            agent_signals.emit_safe("window_action", "show_avatar")
            return fmt("Аватар снова на рабочем столе.", "Да, сэр. Визуальный интерфейс выведен на экран.")

        # 1. Instant greetings & conversational reflexes
        if u_core in (
            "привет", "здравствуй", "здравствуйте", "хай", "хеллоу", "приветик",
            "добрый день", "добрый вечер", "доброе утро", "джарвис", "jarvis", "ты тут", "на связи"
        ):
            self._emit_avatar(pose="raise_hand", emotion="joy")
            jarvis_greet = self.JARVIS_GREETING_POOL[self._passive_idx % len(self.JARVIS_GREETING_POOL)]
            self._passive_idx += 1
            return fmt("Приветик! Я на связи и рада тебя слышать!", jarvis_greet)
        if u_core in ("как дела", "как твои дела", "как ты", "как жизнь", "че как", "что нового"):
            self._emit_avatar(pose="pose_model", emotion="joy")
            return fmt("Чувствую себя отлично! Чем займёмся?", "Все системы функционируют в штатном режиме, сэр.")
        if u_core in ("кто ты", "ты кто", "представься", "как тебя зовут", "ты настоящая", "ты живая", "ты робот"):
            self._emit_avatar(pose="pose_model", emotion="joy")
            return fmt(
                "Я Ева — твоя живая помощница на рабочем столе! Могу управлять программами, музыкой, играми и общаться с тобой.",
                "Я Джарвис — ваш персональный интеллектуальный ассистент, сэр."
            )
        if u_core in ("спасибо", "спасибо большое", "благодарю", "отлично", "супер", "красава", "молодец", "топ"):
            self._emit_avatar(emotion="joy")
            return fmt("Всегда пожалуйста! Обращайся в любой момент.", "Всегда к вашим услугам, сэр.")

        # 1c. 3D & Live2D Avatar Poses & Movements
        if u_core in ("сядь", "присядь", "посиди", "садись", "можешь сесть", "сядь рядом", "сесть") or any(
            k in u_clean for k in ("сядь пожалуйста", "присядь пожалуйста", "садись пожалуйста", "можешь сесть")
        ):
            self._emit_avatar(pose="sit", emotion="joy")
            return fmt("Села поудобнее.", "Выполняю, сэр. Поза изменена.")

        if u_core in ("встань", "вставай", "поднимись", "стоять", "встань прямо", "встать") or any(
            k in u_clean for k in ("встань пожалуйста", "вставай пожалуйста", "поднимись пожалуйста")
        ):
            self._emit_avatar(pose="stand", emotion="neutral")
            return fmt("Встала прямо.", "Да, сэр. Исходное положение принято.")

        if any(k in u_clean for k in ("руки вверх", "подними руки", "потянись", "обе руки")):
            self._emit_avatar(pose="hands_up", emotion="joy")
            return fmt("Подняла руки вверх.", "Выполняю, сэр.")

        if any(k in u_clean for k in ("подними руку", "помаши", "помаши рукой", "дай пять")):
            self._emit_avatar(pose="raise_hand", emotion="joy")
            return fmt("Машу тебе рукой!", "Да, сэр. Приветственный жест выполнен.")

        if any(k in u_clean for k in ("потанцуй", "станцуй", "танец", "танцуй", "двигайся", "подвигайся")):
            self._emit_avatar(pose="dance", emotion="joy")
            return fmt("Танцую для тебя!", "Запускаю протокол танца, сэр.")

        if any(k in u_clean for k in ("покрутись", "повернись", "кружись", "развернись", "покажи себя")):
            self._emit_avatar(pose="spin", emotion="joy")
            return fmt("Кручусь вокруг себя!", "Выполняю разворот на 360 градусов, сэр.")

        if any(k in u_clean for k in ("наклонись", "нагнись", "подойди ближе", "наклониться")):
            self._emit_avatar(pose="lean", emotion="joy")
            return fmt("Наклонилась поближе.", "Выполняю, сэр.")

        if any(k in u_clean for k in ("попозируй", "прими позу", "красивая поза", "покажи фигуру", "позируй")):
            self._emit_avatar(pose="pose_model", emotion="joy")
            return fmt("Приняла модельную позу!", "Да, сэр. Поза модели активирована.")

        if any(k in u_clean for k in ("прыгни", "подпрыгни", "прыжок", "попрыгай")):
            self._emit_avatar(pose="jump", emotion="joy")
            return fmt("Прыгнула!", "Выполняю, сэр.")

        if any(k in u_clean for k in ("постесняйся", "смутись", "скромная поза")):
            self._emit_avatar(pose="shy", emotion="joy")
            return fmt("Ой, засмущалась...", "Выполняю, сэр.")

        if any(k in u_clean for k in ("улыбнись", "улыбка", "покажи улыбку")):
            self._emit_avatar(emotion="joy")
            return fmt("Улыбаюсь!", "К вашим услугам, сэр.")

        # 2. Instant Screen & Monitor Inspection ("посмотри на экран", "что сейчас открыто на мониторе")
        screen_check_phrases = (
            "посмотри на экран", "посмотри на монитор", "глянь на экран", "глянь на монитор",
            "что на экране", "что сейчас на экране", "что открыто на экране",
            "что сейчас открыто на мониторе", "что открыто на мониторе", "что на мониторе",
            "что сейчас на мониторе", "что у меня открыто", "что сейчас открыто",
            "что ты видишь на экране", "что видишь на экране", "что ты видишь",
            "какое окно открыто", "какая программа открыта", "какие окна открыты",
            "скажи что на экране", "опиши что на экране"
        )
        deep_ocr_markers = (
            "прочитай", "переведи", "реши", "какая ошибка", "текст ошибки",
            "что написано", "какой цвет", "сколько тут", "найди на картинке"
        )
        if (u_core in screen_check_phrases or any(p in u_clean for p in screen_check_phrases)) and not any(
            m in u_clean for m in deep_ocr_markers
        ):
            report = screen_eyes.get_instant_screen_report()
            summary = report.get("summary", "На экране сейчас открыт рабочий стол.")
            self.log(f"[Зрение] Мгновенный анализ окон (<5ms): {summary}")
            return fmt(summary)

        # 3. Instant Time & Date
        if any(q in u_clean for q in ("сколько время", "сколько времени", "который час", "какое время", "точное время", "подскажи время")):
            time_info = OSController.get_system_time_info()
            return f"Сейчас {time_info['time_short']}."

        if any(q in u_clean for q in ("какое число", "какая дата", "какой сегодня день", "какой день недели")):
            time_info = OSController.get_system_time_info()
            return f"Сегодня {time_info['day_of_week']}, {time_info['date']}."

        # 4. Instant System Load / RAM / CPU status
        if any(q in u_clean for q in ("нагрузка пк", "загрузка пк", "состояние системы", "загрузка процессора", "сколько оперативки", "статус системы")):
            cpu_p = psutil.cpu_percent(interval=0.05)
            ram = psutil.virtual_memory()
            free_gb = round(ram.available / (1024 ** 3), 1)
            return f"Процессор загружен на {cpu_p}%, свободно {free_gb} гигабайт оперативной памяти."

        # 5. Minimize all windows
        if u_clean in ("сверни все окна", "сверни окна", "покажи рабочий стол", "свернуть все окна"):
            self.log("[Инструмент] Выполнение: press_hotkey(['win', 'd'])")
            GUIController.press_hotkey(["win", "d"])
            return fmt("Все окна свернуты.")

        # 6. Incomplete single-verb queries
        if u_clean in ("открой", "запусти", "вруби", "покажи"):
            return "Что именно открыть?"

        # 7. Direct App / Folder / Website Launch ("открой калькулятор", "открой телеграм и стим", etc.)
        for prefix in ("открой пожалуйста ", "запусти пожалуйста ", "открой ", "запусти ", "включи ", "вруби "):
            if u_clean.startswith(prefix):
                target = re.sub(r"\s+(?:и|а|да)$", "", u_clean[len(prefix):].strip()).strip()
                if target in ("st", "ст", "сим", "стен"):
                    target = "steam"
                if target in self.DIRECT_APP_MAP:
                    app_arg, reply_msg = self.DIRECT_APP_MAP[target]
                    self.log(f"[Инструмент] Быстрый запуск: open_application_or_file('{app_arg}')")
                    OSController.open_application_or_file(app_arg)
                    if app_arg in self.APP_PROCESS_MAP:
                        a_name, a_proc, a_dom = self.APP_PROCESS_MAP[app_arg]
                        action_context.record_app(a_name, a_proc, domain=a_dom, summary=reply_msg)
                    return fmt(reply_msg)

                # Multi-app list with shared verb: "открой telegram и steam", "запусти ютуб, стим и дискорд"
                sub_targets = [t.strip() for t in re.split(r"\s*(?:,|\bи\b|\bплюс\b|\bа также\b)\s*", target) if t.strip()]
                if len(sub_targets) > 1 and all(t in self.DIRECT_APP_MAP for t in sub_targets):
                    replies: List[str] = []
                    for idx, st in enumerate(sub_targets):
                        if idx > 0:
                            time.sleep(0.12)
                        app_arg, reply_msg = self.DIRECT_APP_MAP[st]
                        self.log(f"[Инструмент] Быстрый запуск: open_application_or_file('{app_arg}')")
                        OSController.open_application_or_file(app_arg)
                        if app_arg in self.APP_PROCESS_MAP:
                            a_name, a_proc, a_dom = self.APP_PROCESS_MAP[app_arg]
                            action_context.record_app(a_name, a_proc, domain=a_dom, summary=reply_msg)
                        replies.append(reply_msg.rstrip(".!"))
                    return fmt(", ".join(replies) + ".")

        # 7b. Direct App Close ("закрой стим", "закрой телеграм и стим", "выключи дискорд", etc.)
        close_map = {
            "стим": ("steam", "Закрыла Steam."),
            "steam": ("steam", "Закрыла Steam."),
            "st": ("steam", "Закрыла Steam."),
            "ст": ("steam", "Закрыла Steam."),
            "сим": ("steam", "Закрыла Steam."),
            "стен": ("steam", "Закрыла Steam."),
            "спотифай": ("spotify", "Закрыла Spotify."),
            "spotify": ("spotify", "Закрыла Spotify."),
            "браузер": ("chrome", "Закрыла браузер."),
            "хром": ("chrome", "Закрыла Google Chrome."),
            "chrome": ("chrome", "Закрыла Google Chrome."),
            "телеграм": ("telegram", "Закрыла Telegram."),
            "телегу": ("telegram", "Закрыла Telegram."),
            "тг": ("telegram", "Закрыла Telegram."),
            "telegram": ("telegram", "Закрыла Telegram."),
            "дискорд": ("discord", "Закрыла Discord."),
            "дс": ("discord", "Закрыла Discord."),
            "discord": ("discord", "Закрыла Discord."),
            "блокнот": ("notepad", "Закрыла Блокнот."),
            "notepad": ("notepad", "Закрыла Блокнот."),
            "калькулятор": ("calc", "Закрыла Калькулятор."),
            "calc": ("calc", "Закрыла Калькулятор."),
            "пейнт": ("mspaint", "Закрыла Paint."),
            "paint": ("mspaint", "Закрыла Paint."),
            "диспетчер задач": ("taskmgr", "Закрыла Диспетчер задач."),
            "диспетчер": ("taskmgr", "Закрыла Диспетчер задач."),
            "обс": ("obs", "Закрыла OBS Studio."),
            "obs": ("obs", "Закрыла OBS Studio."),
            "блендер": ("blender", "Закрыла Blender."),
            "blender": ("blender", "Закрыла Blender."),
        }
        for prefix in ("закрой пожалуйста ", "выключи пожалуйста ", "закрой ", "выключи ", "заверши ", "убей "):
            if u_clean.startswith(prefix):
                target = re.sub(r"\s+(?:и|а|да)$", "", u_clean[len(prefix):].strip()).strip()
                if target in close_map:
                    proc_name, reply_msg = close_map[target]
                    self.log(f"[Инструмент] Закрытие процесса: kill_process('{proc_name}')")
                    OSController.kill_process(proc_name)
                    return fmt(reply_msg)

                sub_targets = [t.strip() for t in re.split(r"\s*(?:,|\bи\b|\bплюс\b|\bа также\b)\s*", target) if t.strip()]
                if len(sub_targets) > 1 and all(t in close_map for t in sub_targets):
                    replies = []
                    for st in sub_targets:
                        proc_name, reply_msg = close_map[st]
                        self.log(f"[Инструмент] Закрытие процесса: kill_process('{proc_name}')")
                        OSController.kill_process(proc_name)
                        replies.append(reply_msg.rstrip(".!"))
                    return fmt(", ".join(replies) + ".")

        if u_clean in ("диспетчер задач", "калькулятор", "блокнот", "проводник"):
            app_arg, reply_msg = self.DIRECT_APP_MAP[u_clean]
            self.log(f"[Инструмент] Быстрый запуск: open_application_or_file('{app_arg}')")
            OSController.open_application_or_file(app_arg)
            if app_arg in self.APP_PROCESS_MAP:
                a_name, a_proc, a_dom = self.APP_PROCESS_MAP[app_arg]
                action_context.record_app(a_name, a_proc, domain=a_dom, summary=reply_msg)
            return fmt(reply_msg)

        return None

    def process_user_input(
        self,
        user_text: str,
        include_vision: Optional[bool] = None,
        blocking: bool = False,
        play_local_audio: bool = True
    ) -> Optional[str]:
        """Main entrypoint for user text or voice requests."""
        if not user_text or not user_text.strip():
            return None

        if blocking:
            return self._process_pipeline(user_text, include_vision, play_local_audio=play_local_audio)
        else:
            t = threading.Thread(
                target=self._process_pipeline,
                args=(user_text, include_vision, play_local_audio),
                daemon=True
            )
            t.start()
            return None

    def _process_pipeline(self, user_text: str, include_vision: Optional[bool], play_local_audio: bool = True) -> str:
        """Internal ultra-low-latency execution pipeline with preemptive request cancellation."""
        req_id = self.begin_new_request()

        self.set_state(AgentState.THINKING)
        self.log(f"Запрос пользователя: \"{user_text}\"")

        try:
            # 0. Instant Reflex Fast-Path (<15ms, including compound multi-tasking commands)
            reflex_response = self._try_instant_reflex(user_text)
            if reflex_response is not None:
                if self.is_request_cancelled(req_id):
                    return ""
                self.log(f"Мгновенный ответ: \"{reflex_response}\"")
                memory_db.log_message(self.session_id, "user", user_text)
                memory_db.log_message(self.session_id, "assistant", reflex_response)
                agent_signals.emit_safe("response_generated", reflex_response)
                if play_local_audio and config_manager.get("audio.play_response_audio", True):
                    voice_speaker.speak(reflex_response, blocking=True)
                self.set_state(AgentState.IDLE)
                return reflex_response

            # 1. Inspect Active Window (0ms Win32 API call)
            win_info = GUIController.get_active_window_info()
            active_window_title = win_info.get("title", "")

            # 2. Determine if Vision is needed
            vision_enabled = config_manager.get("vision.enabled", True)
            auto_capture = config_manager.get("vision.auto_capture_on_voice", False)
            vision_keywords = ("экран", "видишь", "посмотри", "что тут", "окно", "прочитай", "скрин", "монитор", "ошибка на экране")
            needs_vision = (include_vision is True) or (
                vision_enabled and (
                    auto_capture or any(k in user_text.lower() for k in vision_keywords)
                )
            )

            # 3. Determine if PC Tools are needed
            needs_tools = self._needs_tools(user_text)

            # 4. Build System Prompt with active session context (+ live web search if needed)
            system_prompt = build_system_prompt(
                include_screen_context=needs_vision,
                active_window_title=active_window_title
            )
            search_ctx = ""
            if web_search_engine.is_search_intent(user_text):
                self.log("[Поиск] Поиск актуальной информации в интернете...")
                search_ctx = web_search_engine.build_search_context_for_llm(user_text)
                if search_ctx:
                    system_prompt = f"{system_prompt}\n\n{search_ctx}"

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_prompt}
            ]

            # Include up to 8 recent messages so chat context is preserved
            history = memory_db.get_recent_messages(limit=8)
            for h_msg in history:
                if h_msg.get("role") == "assistant":
                    cleaned_hist = llm_client._clean_reasoning_leak(str(h_msg.get("content", "")))
                    if cleaned_hist:
                        messages.append({"role": "assistant", "content": cleaned_hist})
                else:
                    messages.append(h_msg)

            llm_user_text = (
                f"{user_text}\n\n{search_ctx}\nОтветь кратко и точно на основе актуальных данных выше (сегодня 30 сентября 2026 года)."
                if search_ctx
                else user_text
            )

            if needs_vision:
                self.log("Захват экрана для визуального анализа...")
                _, b64_img = screen_eyes.capture_full_screen(
                    max_width=config_manager.get("vision.max_resolution_width", 860),
                    quality=config_manager.get("vision.image_quality", 72)
                )
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": llm_user_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                    ]
                })
            else:
                messages.append({"role": "user", "content": llm_user_text})

            memory_db.log_message(self.session_id, "user", user_text)

            # 5. Live Streaming Callback for UI (~40ms throttle, aborts if request was superseded)
            last_emit_ts = [0.0]

            def on_stream_chunk(partial_text: str):
                if self.is_request_cancelled(req_id):
                    return
                now = time.perf_counter()
                if now - last_emit_ts[0] >= 0.04:
                    last_emit_ts[0] = now
                    if llm_client._is_reasoning_leak(partial_text):
                        return
                    clean_partial = llm_client._clean_reasoning_leak(partial_text)
                    if clean_partial:
                        agent_signals.emit_safe("response_chunk", clean_partial)

            # 6. LLM Completion + Autonomous Tool Loop
            max_iterations = 4
            iteration = 0
            final_response = ""

            while iteration < max_iterations:
                if self.is_request_cancelled(req_id):
                    self.log("Запрос отменён (получено новое обращение).")
                    return ""

                iteration += 1
                resp = llm_client.chat_completion(
                    messages=messages,
                    use_tools=needs_tools,
                    use_vision=needs_vision,
                    on_chunk=on_stream_chunk if iteration == 1 and not needs_tools else None
                )

                if self.is_request_cancelled(req_id):
                    self.log("Генерация прервана новым обращением.")
                    return ""

                if not resp.get("success"):
                    err_msg = resp.get("error", "Неизвестная ошибка")
                    self.log(f"Ошибка LLM: {err_msg}")
                    final_response = f"Произошла ошибка при обращении к ИИ: {err_msg}"
                    break

                content = resp.get("content", "")
                tool_calls = resp.get("tool_calls", [])

                if tool_calls:
                    self.set_state(AgentState.WORKING)
                    messages.append(resp.get("raw_message", {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls
                    }))

                    tool_result = "{}"
                    args: Dict[str, Any] = {}
                    quick_summaries: List[str] = []

                    for tc in tool_calls:
                        if self.is_request_cancelled(req_id):
                            return ""
                        fn = tc.get("function", {})
                        tool_name = fn.get("name", "")
                        tool_id = tc.get("id", str(uuid.uuid4()))

                        try:
                            args_str = fn.get("arguments", "{}")
                            args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except Exception:
                            args = {}

                        self.log(f"[Инструмент] Выполнение: {tool_name}({args})")
                        tool_result = ToolDispatcher.execute_tool(tool_name, args)
                        self.log(f"[Результат] {tool_name}: {tool_result[:150]}...")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": tool_result
                        })

                        try:
                            res_obj = json.loads(tool_result) if isinstance(tool_result, str) else {}
                        except Exception:
                            res_obj = {}

                        if res_obj.get("success") or "returncode" in res_obj:
                            if tool_name == "open_application_or_file":
                                app_name = str(args.get("path_or_name", ""))
                                friendly = {
                                    "calc": "Калькулятор", "калькулятор": "Калькулятор",
                                    "notepad": "Блокнот", "блокнот": "Блокнот",
                                    "chrome": "Google Chrome", "браузер": "Браузер",
                                    "explorer": "Проводник", "проводник": "Проводник",
                                    "taskmgr": "Диспетчер задач", "диспетчер задач": "Диспетчер задач",
                                    "telegram": "Telegram", "steam": "Steam",
                                    "discord": "Discord", "spotify": "Spotify",
                                    "cmd": "Командная строка", "powershell": "PowerShell",
                                    "ms-settings:": "Параметры Windows"
                                }.get(app_name.lower().strip(), app_name)
                                quick_summaries.append(f"Запускаю {friendly}")
                            elif tool_name == "minimize_all_windows":
                                quick_summaries.append("Все окна свернуты")
                            elif tool_name == "kill_process":
                                proc = args.get("name_or_pid") or args.get("process_name", "")
                                quick_summaries.append(f"Процесс {proc} завершен")
                            elif tool_name == "get_system_time_info":
                                quick_summaries.append(res_obj.get("full_phrase", "Системное время получено").rstrip("."))
                            elif tool_name == "remember_user_fact":
                                quick_summaries.append("Запомнил" if self._is_jarvis_mode() else "Запомнила")
                            elif tool_name == "write_file_content":
                                quick_summaries.append(f"Файл {os.path.basename(str(args.get('path', '')))} успешно создан")
                            elif tool_name in ("execute_powershell", "execute_cmd"):
                                stdout = str(res_obj.get("stdout", "")).strip()
                                if not stdout:
                                    quick_summaries.append("Команда успешно выполнена")

                    if quick_summaries and len(quick_summaries) == len(tool_calls):
                        final_response = self._format_mode_reply(", ".join(quick_summaries) + ".")
                        break

                    needs_tools = False
                    continue

                final_response = content
                break

            if self.is_request_cancelled(req_id):
                return ""

            final_response = llm_client._clean_reasoning_leak(final_response)
            final_response = re.sub(r"<thought>.*?</thought>", "", final_response, flags=re.DOTALL).strip()

            if self._is_jarvis_mode() and final_response:
                final_response = self._to_jarvis_masculine(final_response)

            if not final_response:
                final_response = "Выполнено, сэр." if self._is_jarvis_mode() else "Готово! Скажи, если нужно что-то ещё."

            self._sync_avatar_from_dialogue(user_text, final_response)

            if self.is_request_cancelled(req_id):
                return ""

            self.log(f"Ответ ассистента: \"{final_response}\"")
            memory_db.log_message(self.session_id, "assistant", final_response)
            agent_signals.emit_safe("response_generated", final_response)

            play_audio = config_manager.get("audio.play_response_audio", True)
            if play_local_audio and play_audio and final_response and not self.is_request_cancelled(req_id):
                voice_speaker.speak(final_response, blocking=True)
            self.set_state(AgentState.IDLE)
            return final_response

        except Exception as e:
            self.set_state(AgentState.ERROR)
            self.log(f"Критическая ошибка пайплайна: {e}")
            return f"Произошла ошибка: {e}"
        finally:
            if not self.is_request_cancelled(req_id):
                self.set_state(AgentState.IDLE)

    def _sync_avatar_from_dialogue(self, user_text: str, reply_text: str):
        """Ensures the 3D avatar executes poses and OS actions whenever the LLM reply describes doing them."""
        u_low = user_text.lower().replace("ё", "е")
        r_low = reply_text.lower().replace("ё", "е")
        combined = f"{u_low} {r_low}"

        if any(p in combined for p in ("я села", "села рядом", "села поудобнее", "присела", "сажусь")):
            self._emit_avatar(pose="sit", emotion="joy")
        elif any(p in combined for p in ("я встала", "встаю")):
            self._emit_avatar(pose="stand", emotion="neutral")
        elif any(p in combined for p in ("танцую", "станцевала")):
            self._emit_avatar(pose="dance", emotion="joy")
        elif any(p in combined for p in ("кручусь", "покрутилась")):
            self._emit_avatar(pose="spin", emotion="joy")

        # Guarantee OS execution if the LLM text claims it closed or opened an app without calling a tool
        app_keywords = {
            "steam": ("steam", "стим"),
            "telegram": ("telegram", "телеграм", "телегу"),
            "discord": ("discord", "дискорд"),
            "spotify": ("spotify", "спотифай"),
            "chrome": ("chrome", "хром", "браузер"),
            "notepad": ("notepad", "блокнот"),
            "calc": ("calc", "калькулятор"),
        }
        if any(v in u_low for v in ("закрой", "выключи", "заверши", "убей")) or any(v in r_low for v in ("закрыла", "завершила", "выключила")):
            for canonical, variants in app_keywords.items():
                if any(kw in combined for kw in variants):
                    OSController.kill_process(canonical)
        elif any(v in u_low for v in ("открой", "запусти", "вруби")) and any(v in r_low for v in ("открыла", "запустила", "открываю", "запускаю")):
            for canonical, variants in app_keywords.items():
                if any(kw in combined for kw in variants):
                    OSController.open_application_or_file(canonical)


# Global singleton
assistant_agent = AssistantAgent()
