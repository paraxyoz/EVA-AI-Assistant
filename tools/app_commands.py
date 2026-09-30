"""
Universal Application Automation, Contextual State Tracker & Custom Commands Engine for EVA AI.
Supports:
- 100+ Popular Windows Applications Catalog (Browsers, Messengers, Games/Launchers, IDE/Dev, Adobe/3D/Design, Office, Media, Utilities)
- Automatic Start Menu & Desktop Shortcut Scanner (`discover_installed_shortcuts` & `smart_launch_app`)
- Universal In-App Actions (Save Ctrl+S, Undo Ctrl+Z, Redo Ctrl+Y, Copy/Paste, Find Ctrl+F, Type text, Incognito, Fullscreen, Window management)
- ActionContextTracker (`action_context`): remembers whether music is playing and which app/tab was last opened
- Exact Windows CoreAudio Master Volume percentage control (0%..100% via pycaw + Win32 fallback)
- No-code Custom Commands Builder stored in data/custom_commands.json + data/commands_state.json
- Edit, toggle (enable/disable), and delete ANY command (custom or built-in)
"""

import copy
import ctypes
import json
import os
import re
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR, config_manager
from core.events import agent_signals
from perception.ears import normalize_voice_transcript
from tools.gui_control import GUIController
from tools.os_control import OSController


CUSTOM_COMMANDS_FILE = DATA_DIR / "custom_commands.json"
COMMANDS_STATE_FILE = DATA_DIR / "commands_state.json"


class ActionContextTracker:
    """
    Tracks recent user commands and active media/app state so follow-up phrases
    ('выключи', 'включи обратно', 'закрой его', 'дальше') resolve in context.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_domain: str = ""          # "music" | "app" | "browser" | "steam" | "discord" | "volume"
        self.music_playing: bool = False
        self.last_app_name: str = ""
        self.last_app_process: str = ""
        self.last_action_summary: str = ""
        self.updated_at: float = 0.0

    def record_music(self, playing: bool, summary: str = ""):
        self.last_domain = "music"
        self.music_playing = playing
        self.last_app_name = "Spotify"
        self.last_app_process = "Spotify.exe"
        self.last_action_summary = summary or ("Играет музыка" if playing else "Музыка на паузе")
        self.updated_at = time.time()

    def record_app(self, app_name: str, process_name: str = "", domain: str = "app", summary: str = ""):
        self.last_domain = domain
        self.last_app_name = app_name
        self.last_app_process = process_name
        self.last_action_summary = summary or f"Открыто приложение {app_name}"
        self.updated_at = time.time()

    def get_prompt_context(self) -> str:
        """Returns a concise summary of recent action state for the LLM system prompt."""
        parts = []
        if self.music_playing:
            parts.append("сейчас включена музыка (Spotify/медиаплеер)")
        elif self.last_domain == "music":
            parts.append("недавно управляли музыкой (сейчас на паузе)")
        if self.last_app_name:
            parts.append(f"последнее открытое/упомянутое приложение: {self.last_app_name} ({self.last_app_process})")
        if self.last_action_summary:
            parts.append(f"последнее действие: {self.last_action_summary}")
        return "; ".join(parts) if parts else "нет недавних действий"


action_context = ActionContextTracker()


# Built-in Hierarchical Command Tree & Rich App Packs (PC, 3D Avatar, Ready-Made App Packs)
BUILTIN_COMMAND_FOLDERS: List[Dict[str, Any]] = [
    # ================= 1. PC SCENARIOS & WINDOWS SYSTEM =================
    {
        "id": "folder_scenarios",
        "title": "Утренние и вечерние сценарии (Цепочки)",
        "scope": "pc",
        "icon": "sparkles",
        "commands": [
            {
                "id": "builtin_good_morning",
                "name": "Утренний запуск («Доброе утро»)",
                "trigger": "доброе утро, утренний режим",
                "response": "Доброе утро! Запускаю браузер, открываю ваши сайты и ставлю комфортную громкость 50%.",
                "require_confirmation": False,
                "confirm_timeout_sec": 10,
                "steps": [
                    {"action_type": "open_app", "target": "chrome", "label": "1. Запустить браузер Chrome"},
                    {"action_type": "open_url", "target": "https://www.youtube.com, https://github.com", "label": "2. Открыть YouTube и GitHub"},
                    {"action_type": "set_volume", "target": "50", "label": "3. Установить громкость Windows на 50%"}
                ]
            },
            {
                "id": "builtin_cozy_evening",
                "name": "Уютный вечер",
                "trigger": "уютный вечер, вечерний режим",
                "response": "Включаю режим уютного вечера: запускаю YouTube, Steam и спокойную музыку!",
                "require_confirmation": False,
                "confirm_timeout_sec": 10,
                "steps": [
                    {"action_type": "open_url", "target": "https://www.youtube.com/results?search_query=lofi+hip+hop+relax", "label": "1. Открыть спокойную музыку на YouTube"},
                    {"action_type": "open_app", "target": "steam", "label": "2. Запустить Steam"},
                    {"action_type": "set_volume", "target": "40", "label": "3. Сделать мягкую громкость Windows (40%)"}
                ]
            },
            {
                "id": "builtin_work_focus",
                "name": "Режим работы / Фокус",
                "trigger": "режим работы, пора работать, фокус",
                "response": "Включаю рабочий режим: открываю VS Code, закрываю лишнее и ставлю фокусную музыку.",
                "require_confirmation": False,
                "confirm_timeout_sec": 10,
                "steps": [
                    {"action_type": "open_app", "target": "vscode", "label": "1. Запустить VS Code"},
                    {"action_type": "open_url", "target": "https://music.yandex.ru", "label": "2. Открыть фоновые треки"},
                    {"action_type": "set_volume", "target": "30", "label": "3. Поставить негромкий звук (30%)"}
                ]
            }
        ]
    },
    {
        "id": "folder_system",
        "title": "Управление системой Windows",
        "scope": "pc",
        "icon": "cpu",
        "commands": [
            {
                "id": "sys_vol_50",
                "name": "Громкость на 50%",
                "trigger": "громкость на 50%, звук на 50%",
                "response": "Громкость Windows установлена на 50%.",
                "steps": [{"action_type": "set_volume", "target": "50", "label": "Установить системную громкость 50%"}]
            },
            {
                "id": "sys_vol_100",
                "name": "Громкость на максимум (100%)",
                "trigger": "громкость на максимум, звук на полную, громкость 100",
                "response": "Громкость Windows на максимуме.",
                "steps": [{"action_type": "set_volume", "target": "100", "label": "Установить громкость 100%"}]
            },
            {
                "id": "sys_vol_mute",
                "name": "Выключить звук (Mute)",
                "trigger": "выключи звук, без звука, мут звука",
                "response": "Звук системы выключен.",
                "steps": [{"action_type": "set_volume", "target": "0", "label": "Установить громкость 0%"}]
            },
            {
                "id": "sys_minimize",
                "name": "Свернуть все окна",
                "trigger": "сверни все окна, покажи рабочий стол",
                "response": "Сворачиваю все окна.",
                "steps": [{"action_type": "hotkey", "target": "win+d", "label": "Нажать Win + D"}]
            },
            {
                "id": "sys_screenshot",
                "name": "Сделать скриншот",
                "trigger": "сделай скриншот, сфоткай экран",
                "response": "Открываю инструмент создания скриншота.",
                "steps": [{"action_type": "hotkey", "target": "win+shift+s", "label": "Открыть ножницы Windows (Win+Shift+S)"}]
            },
            {
                "id": "sys_screen_look",
                "name": "Осмотреть экран",
                "trigger": "посмотри на экран, что сейчас открыто, осмотри экран",
                "response": "Анализирую открытые окна и приложения на экране.",
                "steps": [{"action_type": "system", "target": "screen_inspect", "label": "Мгновенный анализ открытых окон (<5 мс)"}]
            },
            {
                "id": "sys_taskmgr",
                "name": "Открыть Диспетчер задач",
                "trigger": "открой диспетчер задач, запусти диспетчер задач",
                "response": "Открываю Диспетчер задач.",
                "steps": [{"action_type": "open_app", "target": "taskmgr", "label": "Запустить Taskmgr.exe"}]
            },
            {
                "id": "sys_explorer",
                "name": "Открыть Проводник (Мой компьютер)",
                "trigger": "открой проводник, открой этот компьютер",
                "response": "Открываю Проводник Windows.",
                "steps": [{"action_type": "hotkey", "target": "win+e", "label": "Нажать Win + E"}]
            }
        ]
    },
    {
        "id": "folder_chrome",
        "title": "Управление Chrome и Браузером",
        "scope": "pc",
        "icon": "globe",
        "commands": [
            {
                "id": "chr_open",
                "name": "Открыть браузер",
                "trigger": "открой браузер, открой хром",
                "response": "Открываю браузер.",
                "steps": [{"action_type": "open_app", "target": "chrome", "label": "Запустить Google Chrome"}]
            },
            {
                "id": "chr_new_tab",
                "name": "Новая вкладка",
                "trigger": "открой новую вкладку, новая вкладка",
                "response": "Открываю новую вкладку.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+t", "label": "Нажать Ctrl + T в браузере"}]
            },
            {
                "id": "chr_close_tab",
                "name": "Закрыть вкладку",
                "trigger": "закрой вкладку, закрыть вкладку",
                "response": "Закрываю текущую вкладку.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+w", "label": "Нажать Ctrl + W в браузере"}]
            },
            {
                "id": "chr_restore_tab",
                "name": "Вернуть закрытую вкладку",
                "trigger": "верни вкладку, восстанови вкладку",
                "response": "Восстанавливаю закрытую вкладку.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+t", "label": "Нажать Ctrl + Shift + T"}]
            },
            {
                "id": "chr_incognito",
                "name": "Режим инкогнито",
                "trigger": "открой режим инкогнито, окно инкогнито",
                "response": "Открываю окно в режиме инкогнито.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+n", "label": "Нажать Ctrl + Shift + N"}]
            },
            {
                "id": "chr_reload",
                "name": "Обновить страницу",
                "trigger": "обнови страницу, перезагрузи страницу",
                "response": "Обновляю страницу.",
                "steps": [{"action_type": "hotkey", "target": "f5", "label": "Нажать F5"}]
            },
            {
                "id": "chr_history",
                "name": "История браузера",
                "trigger": "открой историю браузера, история браузера",
                "response": "Открываю историю браузера.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+h", "label": "Нажать Ctrl + H"}]
            },
            {
                "id": "chr_downloads",
                "name": "Загрузки браузера",
                "trigger": "открой загрузки, покажи скачанное",
                "response": "Открываю список загрузок браузера.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+j", "label": "Нажать Ctrl + J"}]
            }
        ]
    },
    {
        "id": "folder_spotify",
        "title": "Управление Spotify и Музыкой",
        "scope": "pc",
        "icon": "music",
        "commands": [
            {
                "id": "sp_play",
                "name": "Включить музыку в Spotify",
                "trigger": "включи музыку в спотифай, включи музыку",
                "response": "Включаю музыку в Spotify.",
                "steps": [
                    {"action_type": "open_app", "target": "spotify:", "label": "1. Открыть Spotify"},
                    {"action_type": "media_control", "target": "playpause", "label": "2. Нажать Play/Pause"}
                ]
            },
            {
                "id": "sp_pause",
                "name": "Пауза / Выключить музыку",
                "trigger": "поставь музыку на паузу, выключи музыку, стоп музыка",
                "response": "Ставлю музыку на паузу.",
                "steps": [{"action_type": "media_control", "target": "playpause", "label": "Остановить воспроизведение"}]
            },
            {
                "id": "sp_next",
                "name": "Следующий трек",
                "trigger": "следующий трек, переключи песню, дальше трек",
                "response": "Переключаю на следующий трек.",
                "steps": [{"action_type": "media_control", "target": "nexttrack", "label": "Переключить на следующий трек"}]
            },
            {
                "id": "sp_prev",
                "name": "Предыдущий трек",
                "trigger": "предыдущий трек, верни песню, прошлый трек",
                "response": "Возвращаю предыдущий трек.",
                "steps": [{"action_type": "media_control", "target": "prevtrack", "label": "Вернуть предыдущий трек"}]
            }
        ]
    },
    {
        "id": "folder_obs",
        "title": "Управление OBS Studio и Стримом",
        "scope": "pc",
        "icon": "video",
        "commands": [
            {
                "id": "obs_start_stream_chain",
                "name": "Начать стрим (Цепочка)",
                "trigger": "начать стрим, запусти трансляцию, начни стрим",
                "response": "Запускаю OBS Studio, включаю трансляцию и открываю панель стрима!",
                "require_confirmation": True,
                "confirm_timeout_sec": 10,
                "steps": [
                    {"action_type": "open_app", "target": "obs", "label": "1. Открыть OBS Studio"},
                    {"action_type": "wait", "target": "1.0", "label": "2. Подождать 1 сек"},
                    {"action_type": "hotkey", "target": "ctrl+shift+f11", "label": "3. Нажать хоткей начала трансляции"},
                    {"action_type": "open_url", "target": "https://dashboard.twitch.tv", "label": "4. Открыть сайт со своим стримом"}
                ]
            },
            {
                "id": "obs_rec_start",
                "name": "Начать запись в OBS",
                "trigger": "начни запись в обс, запись экрана обс",
                "response": "Включаю запись видео в OBS.",
                "steps": [
                    {"action_type": "open_app", "target": "obs", "label": "1. Фокус на OBS Studio"},
                    {"action_type": "hotkey", "target": "ctrl+shift+r", "label": "2. Старт записи (Ctrl+Shift+R)"}
                ]
            },
            {
                "id": "obs_rec_stop",
                "name": "Остановить запись в OBS",
                "trigger": "останови запись в обс, выключи запись в обс",
                "response": "Останавливаю запись в OBS.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+r", "label": "Остановить запись (Ctrl+Shift+R)"}]
            }
        ]
    },
    {
        "id": "folder_steam_discord",
        "title": "Управление Steam и Discord",
        "scope": "pc",
        "icon": "gamepad",
        "commands": [
            {
                "id": "stm_cs2",
                "name": "Запустить Counter-Strike 2",
                "trigger": "запусти кс 2, открой контр страйк",
                "response": "Запускаю Counter-Strike 2 в Steam.",
                "steps": [{"action_type": "open_url", "target": "steam://rungameid/730", "label": "Запуск CS2 через Steam (AppID 730)"}]
            },
            {
                "id": "stm_dota2",
                "name": "Запустить Dota 2",
                "trigger": "запусти доту, открой дота 2",
                "response": "Запускаю Dota 2 в Steam.",
                "steps": [{"action_type": "open_url", "target": "steam://rungameid/570", "label": "Запуск Dota 2 через Steam (AppID 570)"}]
            },
            {
                "id": "dsc_mute",
                "name": "Мут микрофона в Discord",
                "trigger": "выключи микрофон в дискорде, замуть в дискорде, замути дискорд",
                "response": "Переключаю микрофон в Discord.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+m", "label": "Нажать Ctrl + Shift + M"}]
            },
            {
                "id": "dsc_deafen",
                "name": "Выключить звук в Discord",
                "trigger": "выключи звук в дискорде, задефань в дискорде",
                "response": "Отключаю звук в Discord.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+d", "label": "Нажать Ctrl + Shift + D"}]
            }
        ]
    },

    # ================= 2. 3D & LIVE2D MODEL FOLDERS =================
    {
        "id": "folder_avatar_poses",
        "title": "3D Модель: Позы и Жесты",
        "scope": "avatar",
        "icon": "user",
        "commands": [
            {
                "id": "av_stand",
                "name": "Встать прямо (Живая стойка)",
                "trigger": "встань, встань прямо",
                "response": "Выпрямляюсь и стою ровно!",
                "steps": [{"action_type": "avatar_pose", "target": "stand", "label": "Переключить позу 3D модели: stand"}]
            },
            {
                "id": "av_sit",
                "name": "Сесть поудобнее",
                "trigger": "сядь, присядь, садись",
                "response": "Присаживаюсь рядом с вами.",
                "steps": [{"action_type": "avatar_pose", "target": "sit", "label": "Переключить позу 3D модели: sit"}]
            },
            {
                "id": "av_wave",
                "name": "Помахать рукой",
                "trigger": "помаши рукой, подними руку, дай пять",
                "response": "Привет-привет! Рада вас видеть!",
                "steps": [{"action_type": "avatar_pose", "target": "raise_hand", "label": "Приветственный взмах рукой"}]
            },
            {
                "id": "av_lean",
                "name": "Наклониться ближе",
                "trigger": "наклонись, подойди ближе",
                "response": "Слушаю вас внимательно.",
                "steps": [{"action_type": "avatar_pose", "target": "lean", "label": "Наклон корпуса вперёд"}]
            },
            {
                "id": "av_pose_model",
                "name": "Принять модельную позу",
                "trigger": "попозируй, прими позу, красивая поза",
                "response": "Как вам такой ракурс?",
                "steps": [{"action_type": "avatar_pose", "target": "pose_model", "label": "Модельная стойка"}]
            }
        ]
    },
    {
        "id": "folder_avatar_dance",
        "title": "3D Модель: Танцы, Эмоции и Отображение",
        "scope": "avatar",
        "icon": "heart",
        "commands": [
            {
                "id": "av_dance",
                "name": "Танцевать",
                "trigger": "станцуй, потанцуй, танец",
                "response": "Танцую под ваш ритм!",
                "steps": [{"action_type": "avatar_pose", "target": "dance", "label": "Включить анимацию танца"}]
            },
            {
                "id": "av_spin",
                "name": "Покрутиться на 360°",
                "trigger": "покрутись, повернись, кружись",
                "response": "Один оборот на 360 градусов!",
                "steps": [{"action_type": "avatar_pose", "target": "spin", "label": "Плавный оборот вокруг оси"}]
            },
            {
                "id": "av_shy",
                "name": "Смутиться",
                "trigger": "постесняйся, смутись",
                "response": "Ой, вы меня смущаете...",
                "steps": [{"action_type": "avatar_pose", "target": "shy", "label": "Скромная поза + румянец"}]
            },
            {
                "id": "av_hide",
                "name": "Скрыть 3D модель с экрана",
                "trigger": "скрой аватар, убери модель, спрячь модель",
                "response": "Скрываю 3D модель. Я остаюсь на связи голосом!",
                "steps": [{"action_type": "avatar_pose", "target": "hide_avatar", "label": "Скрыть оверлей модели"}]
            },
            {
                "id": "av_show",
                "name": "Показать 3D модель на экране",
                "trigger": "покажи аватар, верни модель, покажи модель",
                "response": "Я снова здесь!",
                "steps": [{"action_type": "avatar_pose", "target": "show_avatar", "label": "Показать оверлей модели"}]
            }
        ]
    },

    # ================= 3. 15+ RICH APP PACKS (TRAINABLE) =================
    {
        "id": "pack_blender",
        "title": "Пак: Blender 3D (Моделирование и Рендер)",
        "scope": "packs",
        "icon": "box",
        "commands": [
            {
                "id": "blender_open",
                "name": "Открыть Blender",
                "trigger": "открой блендер, запусти blender",
                "response": "Запускаю Blender 3D.",
                "steps": [{"action_type": "open_app", "target": "blender", "label": "Запустить Blender"}]
            },
            {
                "id": "blender_render_frame",
                "name": "Рендер кадра (F12)",
                "trigger": "отрендери кадр, рендер кадра в блендере, срендери картинку",
                "response": "Запускаю рендеринг кадра в Blender (F12).",
                "steps": [{"action_type": "hotkey", "target": "f12", "label": "Рендер текущего кадра (F12)"}]
            },
            {
                "id": "blender_render_anim",
                "name": "Рендер анимации (Ctrl+F12)",
                "trigger": "отрендери анимацию, рендер анимации в блендере",
                "response": "Запускаю рендеринг анимации в Blender.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+f12", "label": "Рендер всей анимации (Ctrl+F12)"}]
            },
            {
                "id": "blender_shade_smooth",
                "name": "Сгладить модель (Shade Smooth)",
                "trigger": "сгладь модель в блендере, шейд смуз",
                "response": "Применяю Shade Smooth к выбранному объекту.",
                "steps": [
                    {"action_type": "hotkey", "target": "w", "label": "Контекстное меню объекта"},
                    {"action_type": "wait", "target": "0.1", "label": "Пауза 0.1с"},
                    {"action_type": "type_text", "target": "Shade Smooth", "label": "Выбрать Shade Smooth"}
                ]
            },
            {
                "id": "blender_apply_transforms",
                "name": "Применить все трансформации (Ctrl+A)",
                "trigger": "примени трансформации, применить скейл в блендере",
                "response": "Применяю все трансформации объекта (Apply All Transforms).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+a", "label": "Нажать Ctrl + A (Apply Transforms)"}]
            },
            {
                "id": "blender_edit_mode",
                "name": "Переключить Edit Mode (Tab)",
                "trigger": "режим редактирования, переключи эдит мод",
                "response": "Переключаю режим редактирования (Tab).",
                "steps": [{"action_type": "hotkey", "target": "tab", "label": "Нажать Tab (Edit Mode)"}]
            },
            {
                "id": "blender_subsurf",
                "name": "Добавить Subdivision Surface (Ctrl+2)",
                "trigger": "добавь сабдив, сглаживание сабдив в блендере",
                "response": "Добавляю модификатор Subdivision Surface уровня 2.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+2", "label": "Нажать Ctrl + 2"}]
            },
            {
                "id": "blender_xray",
                "name": "Режим X-Ray (Alt+Z)",
                "trigger": "включи рентген в блендере, переключи x-ray",
                "response": "Переключаю режим прозрачности X-Ray.",
                "steps": [{"action_type": "hotkey", "target": "alt+z", "label": "Нажать Alt + Z"}]
            }
        ]
    },
    {
        "id": "pack_photoshop",
        "title": "Пак: Adobe Photoshop (Графика и Ретушь)",
        "scope": "packs",
        "icon": "layers",
        "commands": [
            {
                "id": "ps_open",
                "name": "Открыть Photoshop",
                "trigger": "открой фотошоп, запусти photoshop",
                "response": "Открываю Adobe Photoshop.",
                "steps": [{"action_type": "open_app", "target": "photoshop", "label": "Запустить Adobe Photoshop"}]
            },
            {
                "id": "ps_new_doc",
                "name": "Новый холст в Photoshop (Ctrl+N)",
                "trigger": "новый холст в фотошопе, создай проект в фотошопе",
                "response": "Создаю новый документ в Photoshop.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+n", "label": "Нажать Ctrl + N"}]
            },
            {
                "id": "ps_new_layer",
                "name": "Новый слой (Ctrl+Shift+N)",
                "trigger": "новый слой в фотошопе, создай слой",
                "response": "Создаю новый слой в Photoshop.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+n", "label": "Нажать Ctrl + Shift + N"}]
            },
            {
                "id": "ps_stamp_visible",
                "name": "Объединить видимые слои Stamp (Ctrl+Alt+Shift+E)",
                "trigger": "слепи видимые слои, создай отпечаток слоев в фотошопе",
                "response": "Создаю объединенный видимый слой (Stamp Visible).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+alt+shift+e", "label": "Нажать Ctrl+Alt+Shift+E"}]
            },
            {
                "id": "ps_export_web",
                "name": "Быстрый экспорт PNG / Web (Ctrl+Alt+Shift+W)",
                "trigger": "экспортируй картинку, сохрани для web в фотошопе",
                "response": "Открываю окно быстрого экспорта для Web.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+alt+shift+w", "label": "Экспорт (Ctrl+Alt+Shift+W)"}]
            },
            {
                "id": "ps_free_transform",
                "name": "Свободная трансформация (Ctrl+T)",
                "trigger": "трансформируй слой, свободная трансформация в фотошопе",
                "response": "Включаю свободную трансформацию слоя (Ctrl+T).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+t", "label": "Нажать Ctrl + T"}]
            },
            {
                "id": "ps_curves",
                "name": "Кривые цветокоррекции Curves (Ctrl+M)",
                "trigger": "открой кривые в фотошопе, цветокоррекция кривые",
                "response": "Открываю окно кривых Curves.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+m", "label": "Нажать Ctrl + M"}]
            }
        ]
    },
    {
        "id": "pack_premiere",
        "title": "Пак: Adobe Premiere Pro (Видеомонтаж)",
        "scope": "packs",
        "icon": "film",
        "commands": [
            {
                "id": "pr_open",
                "name": "Открыть Premiere Pro",
                "trigger": "открой премьер, запусти premiere pro",
                "response": "Запускаю Adobe Premiere Pro.",
                "steps": [{"action_type": "open_app", "target": "premiere", "label": "Запустить Premiere Pro"}]
            },
            {
                "id": "pr_cut",
                "name": "Разрезать клип на таймлайне (Ctrl+K)",
                "trigger": "разрежь видео, разрежь клип в премьере, резка видео",
                "response": "Разрезаю клип на курсоре таймлайна (Ctrl+K).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+k", "label": "Нажать Ctrl + K (Razor Cut)"}]
            },
            {
                "id": "pr_ripple_delete",
                "name": "Удалить со сдвигом Ripple Delete (Shift+Delete)",
                "trigger": "удали со сдвигом, рипл делит в премьере",
                "response": "Удаляю выделенный фрагмент со сдвигом трека (Ripple Delete).",
                "steps": [{"action_type": "hotkey", "target": "shift+delete", "label": "Нажать Shift + Delete"}]
            },
            {
                "id": "pr_export",
                "name": "Экспорт видео Media (Ctrl+M)",
                "trigger": "экспортируй видео, рендер видео в премьере",
                "response": "Открываю меню экспорта медиа (Ctrl+M).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+m", "label": "Нажать Ctrl + M (Export Media)"}]
            },
            {
                "id": "pr_new_seq",
                "name": "Создать новую секвенцию (Ctrl+N)",
                "trigger": "новая секвенция в премьере, создай секвенцию",
                "response": "Создаю новую последовательность/секвенцию.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+n", "label": "Нажать Ctrl + N"}]
            },
            {
                "id": "pr_default_transition",
                "name": "Применить переход по умолчанию (Ctrl+D)",
                "trigger": "добавь переход в премьере, сделай плавный переход",
                "response": "Применяю видеопереход по умолчанию на стык клипов.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+d", "label": "Нажать Ctrl + D"}]
            }
        ]
    },
    {
        "id": "pack_after_effects",
        "title": "Пак: Adobe After Effects (VFX и Моушн)",
        "scope": "packs",
        "icon": "zap",
        "commands": [
            {
                "id": "ae_open",
                "name": "Открыть After Effects",
                "trigger": "открой афтер эффектс, запусти after effects",
                "response": "Запускаю Adobe After Effects.",
                "steps": [{"action_type": "open_app", "target": "after effects", "label": "Запустить After Effects"}]
            },
            {
                "id": "ae_new_comp",
                "name": "Новая композиция (Ctrl+N)",
                "trigger": "новая композиция в афтере, создай композицию",
                "response": "Создаю новую композицию в After Effects.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+n", "label": "Нажать Ctrl + N"}]
            },
            {
                "id": "ae_easy_ease",
                "name": "Плавные ключи анимации Easy Ease (F9)",
                "trigger": "сделай плавные ключи, изи из в афтере, f9 ключи",
                "response": "Применяю плавную интерполяцию ключей Easy Ease (F9).",
                "steps": [{"action_type": "hotkey", "target": "f9", "label": "Нажать F9 (Easy Ease)"}]
            },
            {
                "id": "ae_split_layer",
                "name": "Разрезать слой (Ctrl+Shift+D)",
                "trigger": "разрежь слой в афтере, сплит слой",
                "response": "Разрезаю выбранный слой на таймлайне (Ctrl+Shift+D).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+d", "label": "Нажать Ctrl + Shift + D"}]
            },
            {
                "id": "ae_precompose",
                "name": "Прекомпоз Pre-compose (Ctrl+Shift+C)",
                "trigger": "сделай прекомпоз, сгруппируй слои в афтере",
                "response": "Упаковываю слои в отдельную пре-композицию (Pre-compose).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+c", "label": "Нажать Ctrl + Shift + C"}]
            },
            {
                "id": "ae_render_queue",
                "name": "Добавить в очередь рендера (Ctrl+Alt+M)",
                "trigger": "отправь на рендер в афтере, очередь рендера",
                "response": "Добавляю композицию в очередь рендеринга Adobe Media Encoder.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+alt+m", "label": "Нажать Ctrl + Alt + M"}]
            }
        ]
    },
    {
        "id": "pack_illustrator",
        "title": "Пак: Adobe Illustrator (Векторная графика)",
        "scope": "packs",
        "icon": "pen-tool",
        "commands": [
            {
                "id": "ai_open",
                "name": "Открыть Illustrator",
                "trigger": "открой иллюстратор, запусти illustrator",
                "response": "Запускаю Adobe Illustrator.",
                "steps": [{"action_type": "open_app", "target": "illustrator", "label": "Запустить Illustrator"}]
            },
            {
                "id": "ai_group",
                "name": "Сгруппировать объекты (Ctrl+G)",
                "trigger": "сгруппируй в иллюстраторе, группировка объектов",
                "response": "Группирую выбранные объекты (Ctrl+G).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+g", "label": "Нажать Ctrl + G"}]
            },
            {
                "id": "ai_outlines",
                "name": "Преобразовать текст в кривые (Ctrl+Shift+O)",
                "trigger": "текст в кривые, окриви текст в иллюстраторе",
                "response": "Преобразую шрифт в векторные контуры (Create Outlines).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+o", "label": "Нажать Ctrl + Shift + O"}]
            },
            {
                "id": "ai_outline_mode",
                "name": "Режим контуров Outline (Ctrl+Y)",
                "trigger": "покажи контуры в иллюстраторе, режим каркаса",
                "response": "Переключаю режим отображения контуров (Ctrl+Y).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+y", "label": "Нажать Ctrl + Y"}]
            },
            {
                "id": "ai_artboards",
                "name": "Инструмент монтажных областей (Shift+O)",
                "trigger": "монтажные области в иллюстраторе, артборды",
                "response": "Выбираю инструмент редактирования монтажных областей Artboards.",
                "steps": [{"action_type": "hotkey", "target": "shift+o", "label": "Нажать Shift + O"}]
            }
        ]
    },
    {
        "id": "pack_davinci_capcut",
        "title": "Пак: DaVinci Resolve & CapCut (Монтаж и Shorts)",
        "scope": "packs",
        "icon": "scissors",
        "commands": [
            {
                "id": "davinci_open",
                "name": "Открыть DaVinci Resolve",
                "trigger": "открой давинчи, запусти davinci resolve",
                "response": "Запускаю DaVinci Resolve.",
                "steps": [{"action_type": "open_app", "target": "davinci", "label": "Запустить DaVinci Resolve"}]
            },
            {
                "id": "capcut_open",
                "name": "Открыть CapCut",
                "trigger": "открой капкат, запусти capcut",
                "response": "Запускаю CapCut для создания Reels и Shorts.",
                "steps": [{"action_type": "open_app", "target": "capcut", "label": "Запустить CapCut"}]
            },
            {
                "id": "davinci_blade",
                "name": "Разрезать клип Blade (Ctrl+B)",
                "trigger": "разрежь в давинчи, лезвие в давинчи",
                "response": "Разрезаю клип лезвием в DaVinci Resolve.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+b", "label": "Нажать Ctrl + B"}]
            },
            {
                "id": "davinci_add_node",
                "name": "Добавить серийную ноду (Alt+S)",
                "trigger": "добавь ноду в давинчи, новая нода цветокора",
                "response": "Добавляю серийную ноду цветокоррекции (Alt+S).",
                "steps": [{"action_type": "hotkey", "target": "alt+s", "label": "Нажать Alt + S"}]
            },
            {
                "id": "davinci_cinema",
                "name": "Полноэкранный кинопросмотр (Ctrl+F)",
                "trigger": "кинотеатр в давинчи, полноэкранный превью видео",
                "response": "Включаю полноэкранный кинотеатральный просмотр (Cinema Viewer).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+f", "label": "Нажать Ctrl + F"}]
            }
        ]
    },
    {
        "id": "pack_figma",
        "title": "Пак: Figma Design (UI/UX Проектирование)",
        "scope": "packs",
        "icon": "pen",
        "commands": [
            {
                "id": "fig_open",
                "name": "Открыть Figma",
                "trigger": "открой фигму, запусти figma",
                "response": "Открываю Figma Desktop.",
                "steps": [{"action_type": "open_app", "target": "figma", "label": "Запустить Figma Desktop"}]
            },
            {
                "id": "fig_autolayout",
                "name": "Создать Auto Layout (Shift+A)",
                "trigger": "автолейаут в фигме, создай auto layout",
                "response": "Оборачиваю элементы в Auto Layout (Shift+A).",
                "steps": [{"action_type": "hotkey", "target": "shift+a", "label": "Нажать Shift + A"}]
            },
            {
                "id": "fig_component",
                "name": "Создать компонент (Ctrl+Alt+K)",
                "trigger": "создай компонент в фигме, сделай компонентом",
                "response": "Создаю переиспользуемый мастер-компонент в Figma.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+alt+k", "label": "Нажать Ctrl + Alt + K"}]
            },
            {
                "id": "fig_actions",
                "name": "Быстрый поиск действий и плагинов (Ctrl+/)",
                "trigger": "поиск плагинов в фигме, меню действий фигма",
                "response": "Открываю палитру быстрых действий Quick Actions.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+/", "label": "Нажать Ctrl + /"}]
            },
            {
                "id": "fig_export",
                "name": "Экспорт фрейма в Figma (Ctrl+Shift+E)",
                "trigger": "экспортируй фрейм в фигме, меню экспорта фигма",
                "response": "Открываю меню экспорта фреймов и ассетов.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+e", "label": "Нажать Ctrl + Shift + E"}]
            }
        ]
    },
    {
        "id": "pack_fl_ableton",
        "title": "Пак: FL Studio & Ableton Live (Создание музыки)",
        "scope": "packs",
        "icon": "sliders",
        "commands": [
            {
                "id": "fl_open",
                "name": "Открыть FL Studio",
                "trigger": "открой фл студио, запусти fl studio",
                "response": "Запускаю цифровую звуковую станцию FL Studio.",
                "steps": [{"action_type": "open_app", "target": "fl studio", "label": "Запустить FL Studio"}]
            },
            {
                "id": "fl_playlist",
                "name": "Открыть Плейлист / Аранжировку (F5)",
                "trigger": "открой плейлист в фл студио, окно аранжировки",
                "response": "Открываю плейлист аранжировки (F5).",
                "steps": [{"action_type": "hotkey", "target": "f5", "label": "Нажать F5"}]
            },
            {
                "id": "fl_pianoroll",
                "name": "Открыть Piano Roll (F7)",
                "trigger": "открой пиано ролл, нотный редактор в фл студио",
                "response": "Открываю Piano Roll для редактирования нот (F7).",
                "steps": [{"action_type": "hotkey", "target": "f7", "label": "Нажать F7"}]
            },
            {
                "id": "fl_mixer",
                "name": "Открыть Микшер (F9)",
                "trigger": "открой микшер в фл студио, окно микшера",
                "response": "Открываю микшер эффектов и каналов (F9).",
                "steps": [{"action_type": "hotkey", "target": "f9", "label": "Нажать F9"}]
            },
            {
                "id": "fl_metronome",
                "name": "Включить / Выключить Метроном (Ctrl+M)",
                "trigger": "включи метроном в фл студио, переключи метроном",
                "response": "Переключаю звук метронома (Ctrl+M).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+m", "label": "Нажать Ctrl + M"}]
            },
            {
                "id": "fl_export_mp3",
                "name": "Экспорт трека в MP3 (Ctrl+Shift+R)",
                "trigger": "экспортируй трек в мп3, рендер песни в фл",
                "response": "Открываю окно рендеринга трека в MP3.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+r", "label": "Нажать Ctrl + Shift + R"}]
            }
        ]
    },
    {
        "id": "pack_github_vscode",
        "title": "Пак: GitHub, VS Code & Cursor (Разработка)",
        "scope": "packs",
        "icon": "code",
        "commands": [
            {
                "id": "gh_open",
                "name": "Режим кодинга: VS Code + GitHub",
                "trigger": "режим кодинга, открой гитхаб и вс код",
                "response": "Запускаю Visual Studio Code и открываю GitHub.",
                "steps": [
                    {"action_type": "open_app", "target": "vscode", "label": "1. Запустить Visual Studio Code"},
                    {"action_type": "open_url", "target": "https://github.com", "label": "2. Открыть GitHub в браузере"}
                ]
            },
            {
                "id": "cursor_open",
                "name": "Открыть Cursor IDE",
                "trigger": "открой курсор, запусти cursor",
                "response": "Открываю Cursor AI IDE.",
                "steps": [{"action_type": "open_app", "target": "cursor", "label": "Запустить Cursor"}]
            },
            {
                "id": "vsc_palette",
                "name": "Палитра команд VS Code (Ctrl+Shift+P)",
                "trigger": "палитра команд, открой команды вс код",
                "response": "Открываю командную строку IDE.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+p", "label": "Нажать Ctrl + Shift + P"}]
            },
            {
                "id": "vsc_terminal",
                "name": "Открыть встроенный терминал (Ctrl+`)",
                "trigger": "открой терминал в коде, терминал в вс код",
                "response": "Открываю терминал разработки в VS Code.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+`", "label": "Нажать Ctrl + `"}]
            },
            {
                "id": "vsc_format",
                "name": "Автоформатирование кода (Shift+Alt+F)",
                "trigger": "отформатируй код, выровняй код в вс код",
                "response": "Форматирую активный файл кода по правилам линтера.",
                "steps": [{"action_type": "hotkey", "target": "shift+alt+f", "label": "Нажать Shift + Alt + F"}]
            },
            {
                "id": "vsc_save_all",
                "name": "Сохранить проект (Ctrl+S)",
                "trigger": "сохрани проект, сохрани файл",
                "response": "Сохраняю изменения в файле.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+s", "label": "Нажать Ctrl + S"}]
            }
        ]
    },
    {
        "id": "pack_obs",
        "title": "Пак: OBS Studio и Стриминг",
        "scope": "packs",
        "icon": "video",
        "commands": [
            {
                "id": "pk_obs_stream",
                "name": "Полный старт стрима",
                "trigger": "запусти эфир в обс, режим стримера",
                "response": "Запускаю трансляцию и панель Twitch.",
                "require_confirmation": True,
                "confirm_timeout_sec": 10,
                "steps": [
                    {"action_type": "open_app", "target": "obs", "label": "1. Открыть OBS Studio"},
                    {"action_type": "wait", "target": "1.5", "label": "2. Подождать 1.5 сек"},
                    {"action_type": "hotkey", "target": "ctrl+shift+f11", "label": "3. Старт трансляции"},
                    {"action_type": "open_url", "target": "https://dashboard.twitch.tv", "label": "4. Открыть панель стрима"}
                ]
            },
            {
                "id": "pk_obs_stop",
                "name": "Остановить стрим",
                "trigger": "заверши стрим, останови стрим",
                "response": "Завершаю прямую трансляцию.",
                "require_confirmation": True,
                "confirm_timeout_sec": 10,
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+f11", "label": "Остановить стрим (Ctrl+Shift+F11)"}]
            },
            {
                "id": "pk_obs_replay",
                "name": "Сохранить повтор хайлайта (Replay Buffer)",
                "trigger": "сохрани хайлайт, сохрани повтор клипа",
                "response": "Сохраняю игровой повтор последних секунд через Replay Buffer.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+f10", "label": "Сохранить повтор (Ctrl+Shift+F10)"}]
            }
        ]
    },
    {
        "id": "pack_spotify",
        "title": "Пак: Spotify & Яндекс Музыка",
        "scope": "packs",
        "icon": "music",
        "commands": [
            {
                "id": "pk_sp_play",
                "name": "Запустить Spotify и включить трек",
                "trigger": "включи спотифай, запусти музыку в спотифае",
                "response": "Включаю воспроизведение в Spotify.",
                "steps": [
                    {"action_type": "open_app", "target": "spotify:", "label": "1. Открыть клиент Spotify"},
                    {"action_type": "media_control", "target": "playpause", "label": "2. Включить воспроизведение"}
                ]
            },
            {
                "id": "pk_ym_open",
                "name": "Открыть Яндекс Музыку",
                "trigger": "открой яндекс музыку, включи яндекс музыку",
                "response": "Открываю веб-плеер Яндекс Музыки.",
                "steps": [{"action_type": "open_url", "target": "https://music.yandex.ru", "label": "Открыть Яндекс Музыку"}]
            },
            {
                "id": "pk_sp_next",
                "name": "Следующий трек",
                "trigger": "скипни трек, следующая песня",
                "response": "Переключаю на следующий трек.",
                "steps": [{"action_type": "media_control", "target": "nexttrack", "label": "Нажать Next Track"}]
            },
            {
                "id": "pk_sp_like",
                "name": "Добавить трек в Любимые",
                "trigger": "лайкни трек в спотифае, добавь песню в избранное",
                "response": "Ставлю лайк текущей композиции (Alt+Shift+B).",
                "steps": [{"action_type": "hotkey", "target": "alt+shift+b", "label": "Нажать Alt + Shift + B в Spotify"}]
            }
        ]
    },
    {
        "id": "pack_games_steam",
        "title": "Пак: Игры, Steam и Discord",
        "scope": "packs",
        "icon": "gamepad",
        "commands": [
            {
                "id": "pk_gm_cs2",
                "name": "Игровой запуск Counter-Strike 2",
                "trigger": "го в кс, запусти каэс",
                "response": "Запускаю CS2, Discord и комфортную громкость!",
                "steps": [
                    {"action_type": "open_url", "target": "steam://rungameid/730", "label": "1. Запустить CS2 в Steam"},
                    {"action_type": "open_app", "target": "discord://", "label": "2. Открыть Discord"},
                    {"action_type": "set_volume", "target": "70", "label": "3. Громкость Windows на 70%"}
                ]
            },
            {
                "id": "pk_gm_dota2",
                "name": "Игровой запуск Dota 2",
                "trigger": "го в доту, запусти дотку",
                "response": "Запускаю Dota 2 и Discord.",
                "steps": [
                    {"action_type": "open_url", "target": "steam://rungameid/570", "label": "1. Запустить Dota 2 в Steam"},
                    {"action_type": "open_app", "target": "discord://", "label": "2. Открыть Discord"}
                ]
            },
            {
                "id": "pk_gm_overlay",
                "name": "Оверлей Steam в игре (Shift+Tab)",
                "trigger": "открой оверлей стим, оверлей стима",
                "response": "Открываю оверлей Steam (Shift+Tab).",
                "steps": [{"action_type": "hotkey", "target": "shift+tab", "label": "Нажать Shift + Tab"}]
            },
            {
                "id": "pk_gm_clip",
                "name": "Записать последние 30 сек клипа (Win+Alt+G)",
                "trigger": "запиши клип, запиши последние 30 секунд",
                "response": "Сохраняю клип последних 30 секунд геймплея.",
                "steps": [{"action_type": "hotkey", "target": "win+alt+g", "label": "Нажать Win + Alt + G"}]
            }
        ]
    },
    {
        "id": "pack_office_notion",
        "title": "Пак: Офис, Заметки и Презентации",
        "scope": "packs",
        "icon": "file-text",
        "commands": [
            {
                "id": "off_word",
                "name": "Открыть Microsoft Word",
                "trigger": "открой ворд, запусти word",
                "response": "Открываю Microsoft Word.",
                "steps": [{"action_type": "open_app", "target": "winword", "label": "Запустить Word"}]
            },
            {
                "id": "off_excel",
                "name": "Открыть Microsoft Excel",
                "trigger": "открой эксель, запусти excel",
                "response": "Открываю Microsoft Excel.",
                "steps": [{"action_type": "open_app", "target": "excel", "label": "Запустить Excel"}]
            },
            {
                "id": "off_notion",
                "name": "Открыть Notion",
                "trigger": "открой ноушен, запусти notion",
                "response": "Открываю рабочее пространство Notion.",
                "steps": [{"action_type": "open_app", "target": "notion", "label": "Запустить Notion"}]
            },
            {
                "id": "off_obsidian",
                "name": "Открыть Obsidian",
                "trigger": "открой обсидиан, запусти obsidian",
                "response": "Открываю базу знаний Obsidian.",
                "steps": [{"action_type": "open_app", "target": "obsidian", "label": "Запустить Obsidian"}]
            },
            {
                "id": "off_ppt_slideshow",
                "name": "Начать показ слайдов PowerPoint (F5)",
                "trigger": "запусти презентацию, начни показ слайдов",
                "response": "Запускаю показ слайдов на весь экран (F5).",
                "steps": [{"action_type": "hotkey", "target": "f5", "label": "Нажать F5"}]
            }
        ]
    },
    {
        "id": "pack_lightroom",
        "title": "Пак: Adobe Lightroom & Фотообработка",
        "scope": "packs",
        "icon": "image",
        "commands": [
            {
                "id": "lr_open",
                "name": "Открыть Lightroom",
                "trigger": "открой лайтрум, запусти lightroom",
                "response": "Запускаю Adobe Lightroom.",
                "steps": [{"action_type": "open_app", "target": "lightroom", "label": "Запустить Lightroom"}]
            },
            {
                "id": "lr_develop",
                "name": "Модуль обработки Develop (D)",
                "trigger": "модуль обработки, девелоп в лайтруме",
                "response": "Перехожу в модуль обработки Develop (D).",
                "steps": [{"action_type": "hotkey", "target": "d", "label": "Нажать D"}]
            },
            {
                "id": "lr_compare",
                "name": "Сравнить До/После (Y)",
                "trigger": "сравни до после, покажи оригинал в лайтруме",
                "response": "Переключаю режим сравнения До и После (Y).",
                "steps": [{"action_type": "hotkey", "target": "y", "label": "Нажать Y"}]
            },
            {
                "id": "lr_import",
                "name": "Импорт фото (Ctrl+Shift+I)",
                "trigger": "импортируй фото в лайтрум, загрузи фото",
                "response": "Открываю диалог импорта фотографий.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+i", "label": "Нажать Ctrl + Shift + I"}]
            },
            {
                "id": "lr_export",
                "name": "Экспорт фото (Ctrl+Shift+E)",
                "trigger": "экспортируй фото из лайтрума, сохрани фото",
                "response": "Открываю экспорт фотографий.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+e", "label": "Нажать Ctrl + Shift + E"}]
            }
        ]
    },
    {
        "id": "pack_gamedev",
        "title": "Пак: Unity & Unreal Engine (Геймдев)",
        "scope": "packs",
        "icon": "box",
        "commands": [
            {
                "id": "unity_open",
                "name": "Открыть Unity Hub",
                "trigger": "открой юнити, запусти unity hub",
                "response": "Запускаю Unity Hub.",
                "steps": [{"action_type": "open_app", "target": "unity", "label": "Запустить Unity Hub"}]
            },
            {
                "id": "unreal_open",
                "name": "Открыть Unreal Engine",
                "trigger": "открой анрил, запусти unreal engine",
                "response": "Запускаю Unreal Engine Editor.",
                "steps": [{"action_type": "open_app", "target": "unreal engine", "label": "Запустить Unreal Engine"}]
            },
            {
                "id": "engine_play",
                "name": "Запустить сцену Play в движке (Ctrl+P)",
                "trigger": "запусти сцену в движке, нажми плей в юнити",
                "response": "Запускаю тестирование сцены Play (Ctrl+P).",
                "steps": [{"action_type": "hotkey", "target": "ctrl+p", "label": "Нажать Ctrl + P"}]
            },
            {
                "id": "engine_build",
                "name": "Собрать билд проекта (Ctrl+Shift+B)",
                "trigger": "собери билд, билд проекта в движке",
                "response": "Открываю меню сборки проекта Build Settings.",
                "steps": [{"action_type": "hotkey", "target": "ctrl+shift+b", "label": "Нажать Ctrl + Shift + B"}]
            }
        ]
    }
]


class CustomCommandsStore:
    """
    Manages user-defined voice/text commands & multi-step scenarios grouped by folders,
    with persistent editing, toggling (enable/disable), and deletion of both custom
    and built-in commands.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._commands: List[Dict[str, Any]] = self._load_custom()
        self._state: Dict[str, Any] = self._load_state()
        self._pending_confirmations: Dict[str, Dict[str, Any]] = {}

    def _load_custom(self) -> List[Dict[str, Any]]:
        if not CUSTOM_COMMANDS_FILE.exists():
            return []
        try:
            with open(CUSTOM_COMMANDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_custom(self) -> None:
        try:
            with open(CUSTOM_COMMANDS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._commands, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CustomCommandsStore] Save error: {e}")

    def _load_state(self) -> Dict[str, Any]:
        default_state = {
            "disabled_ids": [],
            "deleted_builtin_ids": [],
            "builtin_overrides": {}
        }
        if not COMMANDS_STATE_FILE.exists():
            return default_state
        try:
            with open(COMMANDS_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    default_state.update(data)
                return default_state
        except Exception:
            return default_state

    def _save_state(self) -> None:
        try:
            with open(COMMANDS_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CustomCommandsStore] State save error: {e}")

    def list_commands(self) -> List[Dict[str, Any]]:
        self._commands = self._load_custom()
        self._state = self._load_state()
        disabled_set = set(self._state.get("disabled_ids", []))
        result = []
        for cmd in self._commands:
            c = dict(cmd)
            c["enabled"] = c.get("id") not in disabled_set
            c["is_custom"] = True
            result.append(c)
        return result

    @staticmethod
    def _describe_step(action_type: str, target: str) -> str:
        labels = {
            "open_app": f"Запустить программу: {target}",
            "open_url": f"Открыть ссылку/игру: {target}",
            "set_volume": f"Громкость Windows: {target}%",
            "set_eva_volume": f"Громкость голоса Евы: {target}%",
            "hotkey": f"Нажать клавиши: {target}",
            "type_text": f"Напечатать текст: «{target}»",
            "wait": f"Пауза {target} сек",
            "macro_play": f"Воспроизвести запись действий ({target})",
            "avatar_pose": f"Движение 3D модели: {target}",
            "media_control": f"Медиа-клавиша: {target}",
            "close_app": f"Закрыть процесс: {target}",
            "shell": f"Системная команда: {target}",
            "system": f"Системное действие: {target}",
        }
        return labels.get(action_type, f"{action_type}: {target}")

    def add_command(
        self,
        trigger: str,
        action_type: str = "open_app",
        target: str = "",
        response: str = "",
        *,
        name: str = "",
        folder: str = "Мои команды",
        scope: str = "pc",
        steps: Optional[List[Dict[str, Any]]] = None,
        require_confirmation: bool = False,
        confirm_timeout_sec: int = 10,
        cmd_id: Optional[str] = None
    ) -> Dict[str, Any]:
        clean_trigger = (trigger or "").strip().lower()
        clean_target = (target or "").strip()
        clean_type = (action_type or "open_app").strip().lower()
        clean_resp = (response or "").strip()
        clean_name = (name or clean_trigger.capitalize()).strip()
        clean_folder = (folder or "Мои команды").strip()
        clean_scope = (scope or "pc").strip().lower()
        if clean_scope not in ("pc", "avatar", "packs"):
            clean_scope = "pc"

        normalized_steps: List[Dict[str, str]] = []
        if steps and isinstance(steps, list):
            for idx, s in enumerate(steps, 1):
                if not isinstance(s, dict):
                    continue
                st_type = str(s.get("action_type", "open_app")).strip().lower()
                st_target = str(s.get("target", "")).strip()
                if not st_target and st_type not in ("media_control", "system"):
                    continue
                st_label = str(s.get("label", "")).strip() or f"{idx}. {self._describe_step(st_type, st_target)}"
                normalized_steps.append({
                    "action_type": st_type,
                    "target": st_target,
                    "label": st_label
                })

        if not normalized_steps and clean_target:
            normalized_steps.append({
                "action_type": clean_type,
                "target": clean_target,
                "label": f"1. {self._describe_step(clean_type, clean_target)}"
            })

        first_type = normalized_steps[0]["action_type"] if normalized_steps else clean_type
        first_target = normalized_steps[0]["target"] if normalized_steps else clean_target

        if not clean_resp:
            clean_resp = f"Выполняю команду «{clean_name}»."

        item_id = cmd_id or str(uuid.uuid4())[:8]
        item = {
            "id": item_id,
            "name": clean_name,
            "trigger": clean_trigger,
            "folder": clean_folder,
            "scope": clean_scope,
            "action_type": first_type,
            "target": first_target,
            "steps": normalized_steps,
            "response": clean_resp,
            "require_confirmation": bool(require_confirmation),
            "confirm_timeout_sec": max(2, min(120, int(confirm_timeout_sec or 10))),
        }

        # Check if cmd_id matches a built-in command; if so, store as override!
        is_builtin = any(b_cmd.get("id") == item_id for f in BUILTIN_COMMAND_FOLDERS for b_cmd in f.get("commands", []))
        if is_builtin:
            self._state = self._load_state()
            overrides = self._state.setdefault("builtin_overrides", {})
            overrides[item_id] = item
            self._save_state()
            item["is_builtin"] = True
            item["enabled"] = item_id not in set(self._state.get("disabled_ids", []))
            return item

        self._commands = self._load_custom()
        replaced = False
        if cmd_id:
            for i, existing in enumerate(self._commands):
                if existing.get("id") == cmd_id:
                    self._commands[i] = item
                    replaced = True
                    break
        if not replaced:
            self._commands.append(item)
        self._save_custom()
        item["is_custom"] = True
        item["enabled"] = True
        return item

    def update_command(self, cmd_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Edits an existing custom command OR saves an override for a built-in command."""
        return self.add_command(
            trigger=payload.get("trigger", ""),
            action_type=payload.get("action_type", "open_app"),
            target=payload.get("target", ""),
            response=payload.get("response", ""),
            name=payload.get("name", ""),
            folder=payload.get("folder", "Мои команды"),
            scope=payload.get("scope", "pc"),
            steps=payload.get("steps"),
            require_confirmation=payload.get("require_confirmation", False),
            confirm_timeout_sec=payload.get("confirm_timeout_sec", 10),
            cmd_id=cmd_id
        )

    def toggle_command(self, cmd_id: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Enables or disables ANY command (custom or built-in)."""
        self._state = self._load_state()
        disabled = set(self._state.setdefault("disabled_ids", []))
        if enabled is None:
            if cmd_id in disabled:
                disabled.remove(cmd_id)
                now_enabled = True
            else:
                disabled.add(cmd_id)
                now_enabled = False
        else:
            if enabled:
                disabled.discard(cmd_id)
                now_enabled = True
            else:
                disabled.add(cmd_id)
                now_enabled = False
        self._state["disabled_ids"] = list(disabled)
        self._save_state()
        return {"id": cmd_id, "enabled": now_enabled}

    def delete_command(self, cmd_id: str) -> bool:
        """Deletes a custom command or marks a built-in command as deleted."""
        self._commands = self._load_custom()
        before_len = len(self._commands)
        self._commands = [c for c in self._commands if c.get("id") != cmd_id]
        if len(self._commands) < before_len:
            self._save_custom()
            return True

        # Check if it is a built-in command
        is_builtin = any(b_cmd.get("id") == cmd_id for f in BUILTIN_COMMAND_FOLDERS for b_cmd in f.get("commands", []))
        if is_builtin:
            self._state = self._load_state()
            del_set = set(self._state.setdefault("deleted_builtin_ids", []))
            del_set.add(cmd_id)
            self._state["deleted_builtin_ids"] = list(del_set)
            if "builtin_overrides" in self._state and cmd_id in self._state["builtin_overrides"]:
                self._state["builtin_overrides"].pop(cmd_id, None)
            self._save_state()
            return True
        return False

    def restore_builtin_commands(self) -> Dict[str, Any]:
        """Restores all deleted built-in commands and clears user overrides."""
        self._state = self._load_state()
        self._state["deleted_builtin_ids"] = []
        self._state["builtin_overrides"] = {}
        # Also remove built-in commands from disabled_ids
        builtin_ids = {b_cmd.get("id") for f in BUILTIN_COMMAND_FOLDERS for b_cmd in f.get("commands", [])}
        self._state["disabled_ids"] = [cid for cid in self._state.get("disabled_ids", []) if cid not in builtin_ids]
        self._save_state()
        return {"success": True, "restored": True}

    def get_full_commands_tree(self) -> List[Dict[str, Any]]:
        """Returns the complete folder tree combining built-in folders, 15+ App Packs, and user commands."""
        self._state = self._load_state()
        disabled_set = set(self._state.get("disabled_ids", []))
        deleted_set = set(self._state.get("deleted_builtin_ids", []))
        overrides = self._state.get("builtin_overrides", {})

        folders = copy.deepcopy(BUILTIN_COMMAND_FOLDERS)
        folder_by_title: Dict[str, Dict[str, Any]] = {
            f["title"].lower(): f for f in folders
        }

        # Apply built-in overrides and deletion filters
        for folder in folders:
            kept_cmds = []
            for cmd in folder.get("commands", []):
                cid = cmd.get("id")
                if cid in deleted_set:
                    continue
                if cid in overrides:
                    cmd.update(overrides[cid])
                cmd["enabled"] = cid not in disabled_set
                cmd["is_builtin"] = True
                cmd["is_custom"] = False
                kept_cmds.append(cmd)
            folder["commands"] = kept_cmds

        # Add user's custom commands
        for cmd in self.list_commands():
            f_title = (cmd.get("folder") or "Мои команды").strip()
            f_key = f_title.lower()
            scope = cmd.get("scope", "pc")
            if f_key not in folder_by_title:
                new_f = {
                    "id": f"custom_folder_{uuid.uuid5(uuid.NAMESPACE_DNS, f_key).hex[:6]}",
                    "title": f_title,
                    "scope": scope,
                    "icon": "folder",
                    "commands": []
                }
                folders.insert(0, new_f)
                folder_by_title[f_key] = new_f

            target_folder = folder_by_title[f_key]
            cmd_copy = dict(cmd)
            cmd_copy["is_custom"] = True
            cmd_copy["is_builtin"] = False
            cmd_copy["enabled"] = cmd_copy.get("id") not in disabled_set
            if not cmd_copy.get("steps"):
                cmd_copy["steps"] = [{
                    "action_type": cmd_copy.get("action_type", "open_app"),
                    "target": cmd_copy.get("target", ""),
                    "label": f"1. {self._describe_step(cmd_copy.get('action_type', 'open_app'), cmd_copy.get('target', ''))}"
                }]
            target_folder["commands"].append(cmd_copy)

        # Remove empty folders if all commands inside were deleted
        folders = [f for f in folders if len(f.get("commands", [])) > 0 or f.get("scope") == "pc"]
        return folders

    def get_command_by_id(self, cmd_id: str) -> Optional[Dict[str, Any]]:
        for folder in self.get_full_commands_tree():
            for cmd in folder.get("commands", []):
                if cmd.get("id") == cmd_id:
                    return cmd
        return None

    def execute_by_id(self, cmd_id: str) -> Optional[str]:
        cmd = self.get_command_by_id(cmd_id)
        if cmd:
            return self.execute_command_item(cmd)
        return None

    def _execute_single_step(self, step: Dict[str, Any], parent_item: Optional[Dict[str, Any]] = None) -> Optional[str]:
        action_type = str(step.get("action_type", "open_app")).strip().lower()
        target = str(step.get("target", "")).strip()

        if action_type == "open_app":
            t_low = target.lower().strip()
            if t_low in AppCommandController.POPULAR_APPS_CATALOG:
                spec, title, proc_exe, dom = AppCommandController.POPULAR_APPS_CATALOG[t_low]
                AppCommandController.smart_launch_app(spec, title)
                action_context.record_app(title, proc_exe, domain=dom)
            else:
                AppCommandController.smart_launch_app(target, target)

        elif action_type in ("open_url", "steam_game"):
            urls = [u.strip() for u in re.split(r"[,;\r\n]+", target) if u.strip()]
            for u in urls:
                if u.startswith(("http://", "https://", "www.")):
                    full_u = u if u.startswith(("http://", "https://")) else f"https://{u}"
                    if len(urls) > 1:
                        webbrowser.open(full_u)
                    else:
                        OSController.open_application_or_file(full_u)
                else:
                    OSController.open_application_or_file(u)

        elif action_type == "set_volume":
            m = re.search(r"(\d{1,3})", target)
            if m:
                lvl = max(0, min(100, int(m.group(1))))
                OSController.set_system_volume(lvl)
                action_context.last_domain = "volume"
                action_context.last_action_summary = f"Громкость установлена на {lvl}%"

        elif action_type == "set_eva_volume":
            m = re.search(r"(\d{1,3})", target)
            if m:
                from expression.voice import voice_speaker
                lvl = max(0, min(150, int(m.group(1))))
                config_manager.set("audio.eq.volume", lvl, auto_save=True)
                agent_signals.emit_safe("voice_eq_changed", voice_speaker.get_voice_eq())

        elif action_type == "hotkey":
            if parent_item and parent_item.get("id") == "chr_close_tab":
                AppCommandController.close_browser_tab()
            else:
                keys = [k.strip().lower() for k in re.split(r"[+\s,]+", target) if k.strip()]
                if len(keys) == 1:
                    GUIController.press_key(keys[0])
                elif len(keys) > 1:
                    GUIController.press_hotkey(keys)

        elif action_type == "type_text":
            GUIController.type_text(target, press_enter=True)

        elif action_type == "wait":
            try:
                sec = min(10.0, max(0.05, float(target.replace(",", "."))))
                time.sleep(sec)
            except Exception:
                time.sleep(0.5)

        elif action_type == "macro_play":
            from tools.macro_recorder import macro_recorder
            macro_recorder.play_macro(target)

        elif action_type == "avatar_pose":
            if target == "hide_avatar":
                config_manager.set("avatar.show_on_desktop", False, auto_save=True)
                agent_signals.emit_safe("window_action", "hide_avatar")
            elif target == "show_avatar":
                config_manager.set("avatar.show_on_desktop", True, auto_save=True)
                agent_signals.emit_safe("window_action", "show_avatar")
            else:
                agent_signals.emit_safe("avatar_action", {"pose": target, "emotion": "joy"})

        elif action_type == "media_control":
            GUIController.press_key(target or "playpause")
            item_meta = ""
            if parent_item:
                item_meta = f"{parent_item.get('id', '')} {parent_item.get('name', '')} {parent_item.get('trigger', '')} {parent_item.get('response', '')}".lower()
            is_pause = any(w in item_meta for w in ("пауз", "останов", "выключ", "выруб", "pause", "stop"))
            summary = parent_item.get("name", "Медиа") if parent_item else "Медиа"
            action_context.record_music(not is_pause, summary)

        elif action_type == "close_app":
            OSController.kill_process(target)

        elif action_type == "shell":
            OSController.execute_cmd(target)

        elif action_type == "system":
            if target == "screen_inspect":
                from perception.eyes import screen_eyes
                rep = screen_eyes.get_instant_screen_report()
                if isinstance(rep, dict):
                    return rep.get("summary", str(rep))
                return str(rep) if rep else None

        return None

    def get_pending_confirmations(self) -> List[Dict[str, Any]]:
        now = time.time()
        expired_ids = [cid for cid, entry in self._pending_confirmations.items() if now > entry["expires_at"]]
        for cid in expired_ids:
            self._pending_confirmations.pop(cid, None)
            agent_signals.emit_safe("command_confirmation_resolved", {"confirm_id": cid, "status": "expired"})
        return list(self._pending_confirmations.values())

    def resolve_confirmation(self, confirm_id: str, approved: bool) -> Dict[str, Any]:
        """Approves or cancels a pending command confirmation before its timer expires."""
        entry = self._pending_confirmations.pop(confirm_id, None)
        if not entry or time.time() > entry.get("expires_at", 0):
            agent_signals.emit_safe("command_confirmation_resolved", {"confirm_id": confirm_id, "status": "expired"})
            return {"success": False, "expired": True, "executed": False, "cancelled": True}

        if not approved:
            agent_signals.emit_safe("command_confirmation_resolved", {"confirm_id": confirm_id, "status": "cancelled"})
            return {"success": True, "executed": False, "cancelled": True, "message": "Выполнение команды отменено."}

        reply = self.execute_command_item(entry["command"], bypass_confirmation=True)
        agent_signals.emit_safe("command_confirmation_resolved", {
            "confirm_id": confirm_id,
            "status": "approved",
            "reply": reply
        })
        agent_signals.emit_safe("response_generated", reply)
        return {"success": True, "executed": True, "cancelled": False, "reply": reply}

    def execute_command_item(self, item: Dict[str, Any], bypass_confirmation: bool = False) -> str:
        """Executes a single or multi-step command item, or queues a confirmation popup if required."""
        if item.get("require_confirmation") and not bypass_confirmation:
            confirm_id = f"conf_{uuid.uuid4().hex[:8]}"
            timeout_sec = max(2, min(120, int(item.get("confirm_timeout_sec", 10))))
            cmd_title = item.get("name") or item.get("trigger") or "Команда"
            steps = item.get("steps") or [{
                "action_type": item.get("action_type", "open_app"),
                "target": item.get("target", ""),
                "label": self._describe_step(item.get("action_type", "open_app"), item.get("target", ""))
            }]
            pending_payload = {
                "confirm_id": confirm_id,
                "command_id": item.get("id", ""),
                "command_name": cmd_title,
                "trigger": item.get("trigger", ""),
                "steps": steps,
                "timeout_sec": timeout_sec,
                "expires_at": time.time() + timeout_sec,
                "command": item
            }
            self._pending_confirmations[confirm_id] = pending_payload
            agent_signals.emit_safe("command_confirmation_required", {
                k: v for k, v in pending_payload.items() if k != "command"
            })
            return f"Подтвердите выполнение команды «{cmd_title}» на экране ({timeout_sec} сек)."

        dynamic_report = None
        steps = item.get("steps")
        if steps and isinstance(steps, list):
            for idx, step in enumerate(steps):
                if idx > 0 and step.get("action_type") != "wait":
                    time.sleep(0.08)
                rep = self._execute_single_step(step, parent_item=item)
                if rep:
                    dynamic_report = rep
        else:
            rep = self._execute_single_step({
                "action_type": item.get("action_type", "open_app"),
                "target": item.get("target", "")
            }, parent_item=item)
            if rep:
                dynamic_report = rep

        if dynamic_report:
            return dynamic_report
        return item.get("response", "Готово!")

    def match_and_execute(self, user_clean: str) -> Optional[str]:
        """Checks if `user_clean` matches ANY enabled command across all folders and executes it."""
        u_norm = re.sub(r"""[.,!?;:"'()]+""", "", user_clean.lower()).replace("ё", "е").strip()
        for ww in ("ева ", "эва ", "дева ", "ива ", "ассистент ", "джарвис ", "слушай "):
            if u_norm.startswith(ww):
                u_norm = u_norm[len(ww):].strip()
        u_polite = re.sub(r"\b(пожалуйста|плиз|быстро|сейчас|мне)\b", "", u_norm).strip()
        u_polite = re.sub(r"\s{2,}", " ", u_polite)

        all_folders = self.get_full_commands_tree()

        # 1. Check user custom commands first
        for folder in all_folders:
            for item in folder.get("commands", []):
                if not item.get("is_custom"):
                    continue
                if not item.get("enabled", True):
                    continue
                raw_triggers = str(item.get("trigger", "")).lower().replace("ё", "е")
                triggers = [t.strip() for t in raw_triggers.split(",") if t.strip()]
                for trig in triggers:
                    if u_norm == trig or u_polite == trig or (len(trig) >= 4 and trig in u_norm):
                        return self.execute_command_item(item)

        # 2. Check all built-in commands across ALL folders and packs (exact trigger match)
        for folder in all_folders:
            for item in folder.get("commands", []):
                if item.get("is_custom"):
                    continue
                if not item.get("enabled", True):
                    continue
                raw_triggers = str(item.get("trigger", "")).lower().replace("ё", "е")
                triggers = [t.strip() for t in raw_triggers.split(",") if t.strip()]
                for trig in triggers:
                    if u_norm == trig or u_polite == trig:
                        return self.execute_command_item(item)

        return None


custom_commands_store = CustomCommandsStore()


class AppCommandController:
    """
    Universal Automation for 100+ Popular Windows Programs, Games, Browsers, Media & In-App Actions.
    """

    # Catalog of popular apps: alias -> (launch_target, display_name, process_exe, domain)
    POPULAR_APPS_CATALOG: Dict[str, Tuple[str, str, str, str]] = {
        # Streaming & Recording
        "обс": ("obs64.exe", "OBS Studio", "obs64.exe", "app"),
        "obs": ("obs64.exe", "OBS Studio", "obs64.exe", "app"),
        "obs studio": ("obs64.exe", "OBS Studio", "obs64.exe", "app"),
        "обс студио": ("obs64.exe", "OBS Studio", "obs64.exe", "app"),
        "стримлабс": ("Streamlabs OBS.exe", "Streamlabs", "Streamlabs OBS.exe", "app"),
        "streamlabs": ("Streamlabs OBS.exe", "Streamlabs", "Streamlabs OBS.exe", "app"),
        "джифорс": ("NVIDIA App.exe", "NVIDIA App", "NVIDIA Overlay.exe", "app"),
        "нвидиа": ("NVIDIA App.exe", "NVIDIA App", "NVIDIA Overlay.exe", "app"),
        "nvidia": ("NVIDIA App.exe", "NVIDIA App", "NVIDIA Overlay.exe", "app"),
        "geforce experience": ("NVIDIA GeForce Experience.exe", "GeForce Experience", "NVIDIA Share.exe", "app"),

        # Design, 3D, Photo, Video & Audio Production
        "фотошоп": ("Photoshop.exe", "Adobe Photoshop", "Photoshop.exe", "app"),
        "photoshop": ("Photoshop.exe", "Adobe Photoshop", "Photoshop.exe", "app"),
        "адоб фотошоп": ("Photoshop.exe", "Adobe Photoshop", "Photoshop.exe", "app"),
        "иллюстратор": ("Illustrator.exe", "Adobe Illustrator", "Illustrator.exe", "app"),
        "illustrator": ("Illustrator.exe", "Adobe Illustrator", "Illustrator.exe", "app"),
        "премьер": ("Adobe Premiere Pro.exe", "Adobe Premiere Pro", "Adobe Premiere Pro.exe", "app"),
        "премьер про": ("Adobe Premiere Pro.exe", "Adobe Premiere Pro", "Adobe Premiere Pro.exe", "app"),
        "premiere": ("Adobe Premiere Pro.exe", "Adobe Premiere Pro", "Adobe Premiere Pro.exe", "app"),
        "premiere pro": ("Adobe Premiere Pro.exe", "Adobe Premiere Pro", "Adobe Premiere Pro.exe", "app"),
        "афтер эффектс": ("AfterFX.exe", "After Effects", "AfterFX.exe", "app"),
        "after effects": ("AfterFX.exe", "After Effects", "AfterFX.exe", "app"),
        "лайтрум": ("Lightroom.exe", "Adobe Lightroom", "Lightroom.exe", "app"),
        "lightroom": ("Lightroom.exe", "Adobe Lightroom", "Lightroom.exe", "app"),
        "блендер": ("blender.exe", "Blender", "blender.exe", "app"),
        "blender": ("blender.exe", "Blender", "blender.exe", "app"),
        "фигма": ("figma://", "Figma", "Figma.exe", "app"),
        "фигму": ("figma://", "Figma", "Figma.exe", "app"),
        "figma": ("figma://", "Figma", "Figma.exe", "app"),
        "канва": ("https://www.canva.com", "Canva", "chrome.exe", "browser"),
        "канву": ("https://www.canva.com", "Canva", "chrome.exe", "browser"),
        "canva": ("https://www.canva.com", "Canva", "chrome.exe", "browser"),
        "давинчи": ("Resolve.exe", "DaVinci Resolve", "Resolve.exe", "app"),
        "давинчи резолв": ("Resolve.exe", "DaVinci Resolve", "Resolve.exe", "app"),
        "davinci": ("Resolve.exe", "DaVinci Resolve", "Resolve.exe", "app"),
        "davinci resolve": ("Resolve.exe", "DaVinci Resolve", "Resolve.exe", "app"),
        "капкат": ("CapCut.exe", "CapCut", "CapCut.exe", "app"),
        "кэпкат": ("CapCut.exe", "CapCut", "CapCut.exe", "app"),
        "capcut": ("CapCut.exe", "CapCut", "CapCut.exe", "app"),
        "крита": ("krita.exe", "Krita", "krita.exe", "app"),
        "криту": ("krita.exe", "Krita", "krita.exe", "app"),
        "krita": ("krita.exe", "Krita", "krita.exe", "app"),
        "гимп": ("gimp-2.10.exe", "GIMP", "gimp-2.10.exe", "app"),
        "gimp": ("gimp-2.10.exe", "GIMP", "gimp-2.10.exe", "app"),
        "аудасити": ("audacity.exe", "Audacity", "audacity.exe", "app"),
        "audacity": ("audacity.exe", "Audacity", "audacity.exe", "app"),
        "фл студио": ("FL64.exe", "FL Studio", "FL64.exe", "app"),
        "эфэл студио": ("FL64.exe", "FL Studio", "FL64.exe", "app"),
        "fl studio": ("FL64.exe", "FL Studio", "FL64.exe", "app"),
        "аблетон": ("Ableton Live.exe", "Ableton Live", "Ableton Live.exe", "app"),
        "ableton": ("Ableton Live.exe", "Ableton Live", "Ableton Live.exe", "app"),
        "юнити": ("Unity Hub.exe", "Unity Hub", "Unity Hub.exe", "app"),
        "unity": ("Unity Hub.exe", "Unity Hub", "Unity Hub.exe", "app"),
        "анрил": ("UnrealEditor.exe", "Unreal Engine", "UnrealEditor.exe", "app"),
        "unreal engine": ("UnrealEditor.exe", "Unreal Engine", "UnrealEditor.exe", "app"),

        # Development & IT
        "вс код": ("vscode://", "Visual Studio Code", "Code.exe", "app"),
        "vscode": ("vscode://", "Visual Studio Code", "Code.exe", "app"),
        "vs code": ("vscode://", "Visual Studio Code", "Code.exe", "app"),
        "вижуал студио код": ("vscode://", "Visual Studio Code", "Code.exe", "app"),
        "курсор": ("Cursor.exe", "Cursor", "Cursor.exe", "app"),
        "cursor": ("Cursor.exe", "Cursor", "Cursor.exe", "app"),
        "пайчарм": ("pycharm64.exe", "PyCharm", "pycharm64.exe", "app"),
        "pycharm": ("pycharm64.exe", "PyCharm", "pycharm64.exe", "app"),
        "интеллидж": ("idea64.exe", "IntelliJ IDEA", "idea64.exe", "app"),
        "идея": ("idea64.exe", "IntelliJ IDEA", "idea64.exe", "app"),
        "intellij": ("idea64.exe", "IntelliJ IDEA", "idea64.exe", "app"),
        "вебшторм": ("webstorm64.exe", "WebStorm", "webstorm64.exe", "app"),
        "webstorm": ("webstorm64.exe", "WebStorm", "webstorm64.exe", "app"),
        "вижуал студио": ("devenv.exe", "Visual Studio", "devenv.exe", "app"),
        "visual studio": ("devenv.exe", "Visual Studio", "devenv.exe", "app"),
        "саблайм": ("sublime_text.exe", "Sublime Text", "sublime_text.exe", "app"),
        "sublime": ("sublime_text.exe", "Sublime Text", "sublime_text.exe", "app"),
        "нотпад++": ("notepad++.exe", "Notepad++", "notepad++.exe", "app"),
        "notepad++": ("notepad++.exe", "Notepad++", "notepad++.exe", "app"),
        "докер": ("Docker Desktop.exe", "Docker Desktop", "Docker Desktop.exe", "app"),
        "docker": ("Docker Desktop.exe", "Docker Desktop", "Docker Desktop.exe", "app"),
        "постман": ("Postman.exe", "Postman", "Postman.exe", "app"),
        "postman": ("Postman.exe", "Postman", "Postman.exe", "app"),
        "гит баш": ("git-bash.exe", "Git Bash", "git-bash.exe", "app"),
        "git bash": ("git-bash.exe", "Git Bash", "git-bash.exe", "app"),
        "виндовс терминал": ("wt.exe", "Windows Terminal", "WindowsTerminal.exe", "app"),
        "windows terminal": ("wt.exe", "Windows Terminal", "WindowsTerminal.exe", "app"),

        # Office, Notes & Productivity
        "ворд": ("winword", "Microsoft Word", "WINWORD.EXE", "app"),
        "майкрософт ворд": ("winword", "Microsoft Word", "WINWORD.EXE", "app"),
        "word": ("winword", "Microsoft Word", "WINWORD.EXE", "app"),
        "эксель": ("excel", "Microsoft Excel", "EXCEL.EXE", "app"),
        "ексель": ("excel", "Microsoft Excel", "EXCEL.EXE", "app"),
        "excel": ("excel", "Microsoft Excel", "EXCEL.EXE", "app"),
        "пауэрпоинт": ("powerpnt", "PowerPoint", "POWERPNT.EXE", "app"),
        "поверпоинт": ("powerpnt", "PowerPoint", "POWERPNT.EXE", "app"),
        "powerpoint": ("powerpnt", "PowerPoint", "POWERPNT.EXE", "app"),
        "презентацию": ("powerpnt", "PowerPoint", "POWERPNT.EXE", "app"),
        "аутлук": ("outlook", "Microsoft Outlook", "OUTLOOK.EXE", "app"),
        "outlook": ("outlook", "Microsoft Outlook", "OUTLOOK.EXE", "app"),
        "ноушен": ("notion://", "Notion", "Notion.exe", "app"),
        "ноушн": ("notion://", "Notion", "Notion.exe", "app"),
        "notion": ("notion://", "Notion", "Notion.exe", "app"),
        "обсидиан": ("obsidian://", "Obsidian", "Obsidian.exe", "app"),
        "obsidian": ("obsidian://", "Obsidian", "Obsidian.exe", "app"),
        "гугл докс": ("https://docs.google.com", "Google Документы", "chrome.exe", "browser"),
        "гугл документы": ("https://docs.google.com", "Google Документы", "chrome.exe", "browser"),
        "google docs": ("https://docs.google.com", "Google Документы", "chrome.exe", "browser"),
        "гугл таблицы": ("https://sheets.google.com", "Google Таблицы", "chrome.exe", "browser"),
        "google sheets": ("https://sheets.google.com", "Google Таблицы", "chrome.exe", "browser"),

        # Messengers, Social & Streaming Platforms
        "телеграм": ("tg://", "Telegram", "Telegram.exe", "app"),
        "телегу": ("tg://", "Telegram", "Telegram.exe", "app"),
        "телега": ("tg://", "Telegram", "Telegram.exe", "app"),
        "тг": ("tg://", "Telegram", "Telegram.exe", "app"),
        "telegram": ("tg://", "Telegram", "Telegram.exe", "app"),
        "дискорд": ("discord://", "Discord", "Discord.exe", "discord"),
        "discord": ("discord://", "Discord", "Discord.exe", "discord"),
        "ватсап": ("whatsapp:", "WhatsApp", "WhatsApp.exe", "app"),
        "вотсап": ("whatsapp:", "WhatsApp", "WhatsApp.exe", "app"),
        "whatsapp": ("whatsapp:", "WhatsApp", "WhatsApp.exe", "app"),
        "вайбер": ("viber:", "Viber", "Viber.exe", "app"),
        "viber": ("viber:", "Viber", "Viber.exe", "app"),
        "зум": ("zoommtg://", "Zoom", "Zoom.exe", "app"),
        "zoom": ("zoommtg://", "Zoom", "Zoom.exe", "app"),
        "скайп": ("skype:", "Skype", "Skype.exe", "app"),
        "skype": ("skype:", "Skype", "Skype.exe", "app"),
        "тимс": ("ms-teams:", "Microsoft Teams", "ms-teams.exe", "app"),
        "teams": ("ms-teams:", "Microsoft Teams", "ms-teams.exe", "app"),
        "вк": ("https://vk.com", "ВКонтакте", "chrome.exe", "browser"),
        "вконтакте": ("https://vk.com", "ВКонтакте", "chrome.exe", "browser"),
        "vk": ("https://vk.com", "ВКонтакте", "chrome.exe", "browser"),
        "твич": ("https://www.twitch.tv", "Twitch", "chrome.exe", "browser"),
        "twitch": ("https://www.twitch.tv", "Twitch", "chrome.exe", "browser"),
        "реддит": ("https://www.reddit.com", "Reddit", "chrome.exe", "browser"),
        "reddit": ("https://www.reddit.com", "Reddit", "chrome.exe", "browser"),
        "чат гпт": ("https://chatgpt.com", "ChatGPT", "chrome.exe", "browser"),
        "chatgpt": ("https://chatgpt.com", "ChatGPT", "chrome.exe", "browser"),
        "кинопоиск": ("https://hd.kinopoisk.ru", "Кинопоиск", "chrome.exe", "browser"),
        "нетфликс": ("https://www.netflix.com", "Netflix", "chrome.exe", "browser"),
        "netflix": ("https://www.netflix.com", "Netflix", "chrome.exe", "browser"),
        "яндекс музыку": ("https://music.yandex.ru", "Яндекс Музыка", "chrome.exe", "music"),
        "яндекс музыка": ("https://music.yandex.ru", "Яндекс Музыка", "chrome.exe", "music"),

        # Browsers
        "яндекс браузер": ("browser.exe", "Яндекс Браузер", "browser.exe", "browser"),
        "опера": ("opera.exe", "Opera", "opera.exe", "browser"),
        "оперу": ("opera.exe", "Opera", "opera.exe", "browser"),
        "опера гх": ("opera.exe", "Opera GX", "opera.exe", "browser"),
        "opera": ("opera.exe", "Opera", "opera.exe", "browser"),
        "opera gx": ("opera.exe", "Opera GX", "opera.exe", "browser"),
        "фаерфокс": ("firefox.exe", "Mozilla Firefox", "firefox.exe", "browser"),
        "мозила": ("firefox.exe", "Mozilla Firefox", "firefox.exe", "browser"),
        "мозилу": ("firefox.exe", "Mozilla Firefox", "firefox.exe", "browser"),
        "firefox": ("firefox.exe", "Mozilla Firefox", "firefox.exe", "browser"),
        "эдж": ("msedge.exe", "Microsoft Edge", "msedge.exe", "browser"),
        "edge": ("msedge.exe", "Microsoft Edge", "msedge.exe", "browser"),
        "брейв": ("brave.exe", "Brave", "brave.exe", "browser"),
        "brave": ("brave.exe", "Brave", "brave.exe", "browser"),

        # Game Launchers, Media Players & System Utilities
        "стим": ("steam://open/main", "Steam", "steam.exe", "steam"),
        "steam": ("steam://open/main", "Steam", "steam.exe", "steam"),
        "эпик геймс": ("com.epicgames.launcher://", "Epic Games Launcher", "EpicGamesLauncher.exe", "app"),
        "эпик": ("com.epicgames.launcher://", "Epic Games Launcher", "EpicGamesLauncher.exe", "app"),
        "epic games": ("com.epicgames.launcher://", "Epic Games Launcher", "EpicGamesLauncher.exe", "app"),
        "баттл нет": ("Battle.net.exe", "Battle.net", "Battle.net.exe", "app"),
        "батл нет": ("Battle.net.exe", "Battle.net", "Battle.net.exe", "app"),
        "battle net": ("Battle.net.exe", "Battle.net", "Battle.net.exe", "app"),
        "юбисофт": ("uplay://", "Ubisoft Connect", "upc.exe", "app"),
        "ubisoft": ("uplay://", "Ubisoft Connect", "upc.exe", "app"),
        "гог": ("GalaxyClient.exe", "GOG Galaxy", "GalaxyClient.exe", "app"),
        "gog": ("GalaxyClient.exe", "GOG Galaxy", "GalaxyClient.exe", "app"),
        "риот": ("RiotClientServices.exe", "Riot Client", "RiotClientServices.exe", "app"),
        "riot": ("RiotClientServices.exe", "Riot Client", "RiotClientServices.exe", "app"),
        "майнкрафт": ("TLauncher.exe", "Minecraft", "javaw.exe", "app"),
        "тлаунчер": ("TLauncher.exe", "TLauncher", "javaw.exe", "app"),
        "minecraft": ("TLauncher.exe", "Minecraft", "javaw.exe", "app"),
        "роблокс": ("roblox://", "Roblox", "RobloxPlayerBeta.exe", "app"),
        "roblox": ("roblox://", "Roblox", "RobloxPlayerBeta.exe", "app"),
        "фейсит": ("https://www.faceit.com", "FACEIT", "chrome.exe", "browser"),
        "faceit": ("https://www.faceit.com", "FACEIT", "chrome.exe", "browser"),
        "торрент": ("qbittorrent.exe", "Торрент", "qbittorrent.exe", "app"),
        "кьюбитторрент": ("qbittorrent.exe", "qBittorrent", "qbittorrent.exe", "app"),
        "уторрент": ("uTorrent.exe", "uTorrent", "uTorrent.exe", "app"),
        "qbittorrent": ("qbittorrent.exe", "qBittorrent", "qbittorrent.exe", "app"),
        "utorrent": ("uTorrent.exe", "uTorrent", "uTorrent.exe", "app"),
        "torrent": ("qbittorrent.exe", "Торрент", "qbittorrent.exe", "app"),
        "влц": ("vlc.exe", "VLC Media Player", "vlc.exe", "app"),
        "vlc": ("vlc.exe", "VLC Media Player", "vlc.exe", "app"),
        "аимп": ("AIMP.exe", "AIMP", "AIMP.exe", "music"),
        "aimp": ("AIMP.exe", "AIMP", "AIMP.exe", "music"),
        "анидеск": ("AnyDesk.exe", "AnyDesk", "AnyDesk.exe", "app"),
        "энидеск": ("AnyDesk.exe", "AnyDesk", "AnyDesk.exe", "app"),
        "anydesk": ("AnyDesk.exe", "AnyDesk", "AnyDesk.exe", "app"),
        "тимвьюер": ("TeamViewer.exe", "TeamViewer", "TeamViewer.exe", "app"),
        "teamviewer": ("TeamViewer.exe", "TeamViewer", "TeamViewer.exe", "app"),
        "винрар": ("WinRAR.exe", "WinRAR", "WinRAR.exe", "app"),
        "winrar": ("WinRAR.exe", "WinRAR", "WinRAR.exe", "app"),
        "7zip": ("7zFM.exe", "7-Zip", "7zFM.exe", "app"),
        "7 зип": ("7zFM.exe", "7-Zip", "7zFM.exe", "app"),
        "настройки звука": ("ms-settings:sound", "Параметры звука", "SystemSettings.exe", "app"),
        "микшер громкости": ("ms-settings:apps-volume", "Микшер громкости", "SystemSettings.exe", "app"),
        "блютуз": ("ms-settings:bluetooth", "Параметры Bluetooth", "SystemSettings.exe", "app"),
        "bluetooth": ("ms-settings:bluetooth", "Параметры Bluetooth", "SystemSettings.exe", "app"),
        "настройки экрана": ("ms-settings:display", "Параметры экрана", "SystemSettings.exe", "app"),
        "центр обновления": ("ms-settings:windowsupdate", "Центр обновления Windows", "SystemSettings.exe", "app"),
        "реестр": ("regedit", "Редактор реестра", "regedit.exe", "app"),
        "редактор реестра": ("regedit", "Редактор реестра", "regedit.exe", "app"),
        "диспетчер устройств": ("devmgmt.msc", "Диспетчер устройств", "mmc.exe", "app"),
        "службы": ("services.msc", "Службы Windows", "mmc.exe", "app"),
    }

    STEAM_GAMES_MAP: Dict[str, tuple[str, str]] = {
        "cs2": ("730", "Counter-Strike 2"),
        "counter-strike 2": ("730", "Counter-Strike 2"),
        "counter strike": ("730", "Counter-Strike 2"),
        "контр страйк": ("730", "Counter-Strike 2"),
        "кс 2": ("730", "Counter-Strike 2"),
        "кс2": ("730", "Counter-Strike 2"),
        "кс": ("730", "Counter-Strike 2"),
        "каэс": ("730", "Counter-Strike 2"),
        "dota 2": ("570", "Dota 2"),
        "dota": ("570", "Dota 2"),
        "дота 2": ("570", "Dota 2"),
        "дота": ("570", "Dota 2"),
        "доту": ("570", "Dota 2"),
        "дотку": ("570", "Dota 2"),
        "gta 5": ("271590", "Grand Theft Auto V"),
        "gta v": ("271590", "Grand Theft Auto V"),
        "гта 5": ("271590", "Grand Theft Auto V"),
        "гта": ("271590", "Grand Theft Auto V"),
        "cyberpunk 2077": ("1091500", "Cyberpunk 2077"),
        "cyberpunk": ("1091500", "Cyberpunk 2077"),
        "киберпанк": ("1091500", "Cyberpunk 2077"),
        "pubg": ("578080", "PUBG: BATTLEGROUNDS"),
        "пабг": ("578080", "PUBG: BATTLEGROUNDS"),
        "пубг": ("578080", "PUBG: BATTLEGROUNDS"),
        "apex legends": ("1172470", "Apex Legends"),
        "apex": ("1172470", "Apex Legends"),
        "апекс": ("1172470", "Apex Legends"),
        "rust": ("252490", "Rust"),
        "раст": ("252490", "Rust"),
        "witcher 3": ("292030", "Ведьмак 3: Дикая Охота"),
        "ведьмак 3": ("292030", "Ведьмак 3: Дикая Охота"),
        "ведьмак": ("292030", "Ведьмак 3: Дикая Охота"),
        "baldurs gate 3": ("1086940", "Baldur's Gate 3"),
        "балдурс гейт": ("1086940", "Baldur's Gate 3"),
        "elden ring": ("1245620", "Elden Ring"),
        "элден ринг": ("1245620", "Elden Ring"),
        "terraria": ("105600", "Terraria"),
        "террария": ("105600", "Terraria"),
        "террарию": ("105600", "Terraria"),
        "stardew valley": ("413150", "Stardew Valley"),
        "deadlock": ("1422450", "Deadlock"),
        "дедлок": ("1422450", "Deadlock"),
        "tf2": ("440", "Team Fortress 2"),
        "team fortress 2": ("440", "Team Fortress 2"),
        "left 4 dead 2": ("550", "Left 4 Dead 2"),
        "garrys mod": ("4000", "Garry's Mod"),
        "гаррис мод": ("4000", "Garry's Mod"),
        "warframe": ("230410", "Warframe"),
        "варфрейм": ("230410", "Warframe"),
        "path of exile": ("238960", "Path of Exile"),
        "destiny 2": ("1085660", "Destiny 2"),
        "wallpaper engine": ("431960", "Wallpaper Engine"),
        "волпейпер энджин": ("431960", "Wallpaper Engine"),
    }

    _installed_steam_cache: Optional[Dict[str, tuple[str, str]]] = None
    _installed_shortcuts_cache: Optional[Dict[str, str]] = None

    @classmethod
    def discover_installed_shortcuts(cls) -> Dict[str, str]:
        """Scans Windows Start Menu and Desktop for .lnk/.url shortcuts so any installed program can be launched."""
        if cls._installed_shortcuts_cache is not None:
            return cls._installed_shortcuts_cache

        shortcuts: Dict[str, str] = {}
        appdata = os.environ.get("APPDATA", "")
        progdata = os.environ.get("PROGRAMDATA", "C:/ProgramData")
        userprofile = os.path.expanduser("~")

        dirs = [
            Path(appdata) / "Microsoft/Windows/Start Menu/Programs",
            Path(progdata) / "Microsoft/Windows/Start Menu/Programs",
            Path(userprofile) / "Desktop",
            Path("C:/Users/Public/Desktop"),
        ]
        for d in dirs:
            if not d.exists():
                continue
            try:
                for p in d.rglob("*"):
                    if p.suffix.lower() in (".lnk", ".url") and "uninstall" not in p.stem.lower():
                        shortcuts[p.stem.lower()] = str(p.resolve())
            except Exception:
                pass

        cls._installed_shortcuts_cache = shortcuts
        return shortcuts

    @classmethod
    def smart_launch_app(cls, target_spec: str, display_name: str = "") -> bool:
        """
        Launches an application by URI, Start Menu shortcut match, Registry App Path, or OSController.
        """
        if not target_spec:
            return False

        # 1. If URI scheme or web URL, launch directly
        if "://" in target_spec or target_spec.startswith(("ms-settings:", "spotify:", "whatsapp:", "viber:", "skype:", "ms-teams:")):
            res = OSController.open_application_or_file(target_spec)
            if res.get("success"):
                return True

        # 2. Check Start Menu & Desktop shortcuts by display_name or target stem
        shortcuts = cls.discover_installed_shortcuts()
        search_keys = []
        if display_name:
            search_keys.append(display_name.lower())
        stem = Path(target_spec).stem.lower()
        if stem and stem not in search_keys:
            search_keys.append(stem)

        for sk in search_keys:
            if sk in shortcuts:
                res = OSController.open_application_or_file(shortcuts[sk])
                if res.get("success"):
                    return True
            for lnk_name, lnk_path in shortcuts.items():
                if len(sk) >= 3 and sk in lnk_name:
                    res = OSController.open_application_or_file(lnk_path)
                    if res.get("success"):
                        return True

        # 3. Direct OSController launch
        res = OSController.open_application_or_file(target_spec)
        return bool(res.get("success", True))

    @classmethod
    def set_system_volume(cls, percent: int) -> bool:
        """Sets Windows Master Volume to exact `percent` (0..100) via CoreAudio (pycaw) or Win32 fallback."""
        target = max(0, min(100, int(percent)))
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
            speakers = AudioUtilities.GetSpeakers()
            ep = speakers.EndpointVolume
            if target == 0:
                ep.SetMasterVolumeLevelScalar(0.0, None)
            else:
                ep.SetMute(0, None)
                ep.SetMasterVolumeLevelScalar(float(target) / 100.0, None)
            return True
        except Exception:
            try:
                user32 = ctypes.windll.user32
                for _ in range(50):
                    user32.keybd_event(0xAE, 0, 0, 0)
                    user32.keybd_event(0xAE, 0, 2, 0)
                steps = int(round(target / 2.0))
                for _ in range(steps):
                    user32.keybd_event(0xAF, 0, 0, 0)
                    user32.keybd_event(0xAF, 0, 2, 0)
                return True
            except Exception as e:
                print(f"[AppCommandController] Volume error: {e}")
                return False

    @classmethod
    def focus_browser_window(cls, hint: str = "") -> bool:
        """Brings an open web browser window (optionally matching `hint` like 'youtube') to foreground."""
        try:
            import win32gui
            import win32con
            windows = GUIController.list_visible_windows()
            browser_markers = (
                "chrome", "edge", "firefox", "opera", "brave", "yandex", "яндекс",
                "youtube", "ютуб", "браузер", "google", "вкладка"
            )
            hint_low = (hint or "").lower().strip()

            if hint_low:
                for w in windows:
                    title_low = w["title"].lower()
                    if hint_low in title_low and "eva ai" not in title_low:
                        win32gui.ShowWindow(w["hwnd"], win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(w["hwnd"])
                        time.sleep(0.10)
                        return True

            for w in windows:
                title_low = w["title"].lower()
                if any(b in title_low for b in browser_markers) and "eva ai" not in title_low:
                    win32gui.ShowWindow(w["hwnd"], win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(w["hwnd"])
                    time.sleep(0.10)
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def close_browser_tab(cls, target_hint: str = "") -> bool:
        """Focuses the browser window (matching `target_hint` if given) and sends Ctrl+W to close the tab."""
        cls.focus_browser_window(target_hint)
        GUIController.press_hotkey(["ctrl", "w"])
        action_context.record_app("Браузер", "chrome.exe", domain="browser", summary="Закрыта вкладка браузера")
        return True

    @classmethod
    def discover_installed_steam_games(cls) -> Dict[str, tuple[str, str]]:
        """Scans local Steam libraries for appmanifest_*.acf files and returns {lower_name: (appid, display_name)}."""
        if cls._installed_steam_cache is not None:
            return cls._installed_steam_cache

        found: Dict[str, tuple[str, str]] = {}
        candidate_roots = [
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Steam",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Steam",
            Path("C:/Steam"),
            Path("D:/Steam"),
            Path("D:/SteamLibrary"),
            Path("E:/SteamLibrary"),
            Path("F:/SteamLibrary"),
        ]

        steamapps_dirs = []
        for root in candidate_roots:
            sa = root / "steamapps"
            if sa.exists():
                steamapps_dirs.append(sa)
                vdf = sa / "libraryfolders.vdf"
                if vdf.exists():
                    try:
                        text = vdf.read_text(encoding="utf-8", errors="ignore")
                        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                            lib_path = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
                            if lib_path.exists() and lib_path not in steamapps_dirs:
                                steamapps_dirs.append(lib_path)
                    except Exception:
                        pass

        for sa_dir in steamapps_dirs:
            try:
                for acf in sa_dir.glob("appmanifest_*.acf"):
                    content = acf.read_text(encoding="utf-8", errors="ignore")
                    appid_m = re.search(r'"appid"\s+"(\d+)"', content)
                    name_m = re.search(r'"name"\s+"([^"]+)"', content)
                    if appid_m and name_m:
                        appid = appid_m.group(1)
                        gname = name_m.group(1)
                        if "redistributable" not in gname.lower() and "proton" not in gname.lower():
                            found[gname.lower()] = (appid, gname)
            except Exception:
                pass

        cls._installed_steam_cache = found
        return found

    @classmethod
    def try_execute(cls, raw_text: str) -> Optional[str]:
        """
        Attempts to match and execute:
        - User-defined custom commands
        - Context-dependent follow-ups ('выключи', 'включи обратно', 'закрой его')
        - EVA's own voice volume control ('говори тише', 'громкость голоса 80%')
        - Universal in-app actions (Save, Undo, Redo, Copy, Paste, Find, Type text, Incognito, Fullscreen)
        - Spotify, Steam, Discord, Browser, System Volume, and 100+ Popular Apps
        """
        if not raw_text or not raw_text.strip():
            return None

        # 1. Check user's custom commands first
        custom_reply = custom_commands_store.match_and_execute(raw_text)
        if custom_reply is not None:
            return custom_reply

        # 2. Normalize bilingual transcript
        norm = normalize_voice_transcript(raw_text)
        u_clean = re.sub(r"[.,!?;:\"'()]+", "", norm.lower()).strip()
        for ww in ("ева ", "эва ", "дева ", "ива ", "лево ", "ассистент ", "джарвис ", "слушай "):
            if u_clean.startswith(ww):
                u_clean = u_clean[len(ww):].strip()

        u_clean = re.sub(
            r"\b(пожалуйста|плиз|пж|будь добра|сейчас|быстренько|давай|ну ка|ну-ка|мне)\b",
            "",
            u_clean
        )
        u_clean = re.sub(r"\s+", " ", u_clean).strip()

        # ================= 0. CONTEXT-AWARE FOLLOW-UP COMMANDS =================
        if u_clean in (
            "выключи", "выруби", "останови", "стоп", "пауза", "хватит",
            "выключи ее", "выключи её", "останови ее", "останови её", "поставь на паузу"
        ):
            if action_context.music_playing or action_context.last_domain == "music":
                GUIController.press_key("playpause")
                action_context.record_music(False, "Музыка поставлена на паузу")
                return "Поставила музыку на паузу."
            if action_context.last_app_process:
                proc = action_context.last_app_process
                app_title = action_context.last_app_name or proc
                OSController.kill_process(proc)
                action_context.last_app_process = ""
                return f"Закрыла {app_title}."
            GUIController.press_key("playpause")
            action_context.record_music(False, "Воспроизведение остановлено")
            return "Остановила воспроизведение."

        if u_clean in ("включи обратно", "вруби обратно", "продолжи", "сними с паузы", "играй дальше") or (
            u_clean == "включи" and action_context.last_domain == "music"
        ):
            GUIController.press_key("playpause")
            action_context.record_music(True, "Музыка продолжена")
            return "Продолжаю воспроизведение музыки."

        if u_clean in ("закрой", "закрой его", "закрой ее", "закрой её", "выключи его", "заверши его"):
            if action_context.last_domain == "browser":
                cls.close_browser_tab()
                return "Закрыла вкладку."
            if action_context.last_app_process:
                proc = action_context.last_app_process
                app_title = action_context.last_app_name or proc
                OSController.kill_process(proc)
                action_context.last_app_process = ""
                return f"Закрыла {app_title}."

        if u_clean in ("дальше", "следующий", "следующую", "пропусти", "скип", "скипни"):
            GUIController.press_key("nexttrack")
            action_context.record_music(True, "Переключен следующий трек")
            return "Переключила на следующий трек."

        # ================= 0b. EVA VOICE VOLUME CONTROL =================
        from config import config_manager
        from expression.voice import voice_speaker
        from core.events import agent_signals

        eva_vol_m = re.search(
            r"(?:громкость\s+голоса|громкость\s+евы|свой\s+голос|голос\s+на)\s*(?:на\s+)?(\d{1,3})\s*(?:%|процент[а-я]*)?",
            u_clean
        )
        if eva_vol_m:
            new_v = max(0, min(150, int(eva_vol_m.group(1))))
            config_manager.set("audio.eq.volume", new_v, auto_save=True)
            agent_signals.emit_safe("voice_eq_changed", voice_speaker.get_voice_eq())
            return f"Установила громкость своего голоса на {new_v}%."

        if any(p in u_clean for p in ("говори тише", "будь тише", "сделай себя тише", "убавь свой голос")):
            cur_v = int(voice_speaker.get_voice_eq().get("volume", 100))
            new_v = max(10, cur_v - 25)
            config_manager.set("audio.eq.volume", new_v, auto_save=True)
            agent_signals.emit_safe("voice_eq_changed", voice_speaker.get_voice_eq())
            return f"Стала говорить тише ({new_v}%)."

        if any(p in u_clean for p in ("говори громче", "сделай себя громче", "прибавь свой голос")):
            cur_v = int(voice_speaker.get_voice_eq().get("volume", 100))
            new_v = min(150, cur_v + 25)
            config_manager.set("audio.eq.volume", new_v, auto_save=True)
            agent_signals.emit_safe("voice_eq_changed", voice_speaker.get_voice_eq())
            return f"Стала говорить громче ({new_v}%)."

        # ================= A. BROWSER TAB & WINDOW MANAGEMENT =================
        if any(p in u_clean for p in (
            "закрой вкладку", "закрыть вкладку", "закрой эту вкладку",
            "закрой текущую вкладку", "убери вкладку"
        )) or re.match(r"^закрой\s+(?:вкладку\s+)?(?:с\s+|на\s+|в\s+)?youtube$", u_clean):
            hint = "youtube" if "youtube" in u_clean else ""
            cls.close_browser_tab(target_hint=hint)
            if hint == "youtube":
                return "Закрыла вкладку с YouTube."
            return "Закрыла вкладку в браузере."

        if any(p in u_clean for p in ("новая вкладка", "открой новую вкладку", "создай вкладку")):
            cls.focus_browser_window()
            GUIController.press_hotkey(["ctrl", "t"])
            action_context.record_app("Браузер", "chrome.exe", domain="browser", summary="Открыта новая вкладка")
            return "Открыла новую вкладку в браузере."

        if any(p in u_clean for p in ("верни вкладку", "открой закрытую вкладку", "восстанови вкладку")):
            cls.focus_browser_window()
            GUIController.press_hotkey(["ctrl", "shift", "t"])
            action_context.record_app("Браузер", "chrome.exe", domain="browser", summary="Восстановлена вкладка")
            return "Вернула закрытую вкладку."

        if any(p in u_clean for p in ("следующая вкладка", "переключи вкладку")):
            cls.focus_browser_window()
            GUIController.press_hotkey(["ctrl", "tab"])
            return "Переключила вкладку."

        if any(p in u_clean for p in ("предыдущая вкладка", "прошлая вкладка")):
            cls.focus_browser_window()
            GUIController.press_hotkey(["ctrl", "shift", "tab"])
            return "Переключила на предыдущую вкладку."

        if any(p in u_clean for p in ("режим инкогнито", "открой режим инкогнито", "окно инкогнито", "вкладка инкогнито", "открой инкогнито")):
            cls.focus_browser_window()
            GUIController.press_hotkey(["ctrl", "shift", "n"])
            action_context.record_app("Браузер (Инкогнито)", "chrome.exe", domain="browser")
            return "Открыла окно в режиме инкогнито."

        if any(p in u_clean for p in ("история браузера", "открой историю браузера")):
            cls.focus_browser_window()
            GUIController.press_hotkey(["ctrl", "h"])
            return "Открыла историю браузера."

        if any(p in u_clean for p in ("обнови страницу", "обнови вкладку", "перезагрузи страницу")):
            cls.focus_browser_window()
            GUIController.press_key("f5")
            return "Обновила страницу."

        # ================= B. UNIVERSAL IN-APP ACTIONS =================
        if u_clean in ("сохрани", "сохрани файл", "сохрани проект", "сохрани документ", "сохранить"):
            GUIController.press_hotkey(["ctrl", "s"])
            return "Сохранила текущий документ."

        if u_clean in ("отмени", "отмени действие", "шаг назад", "верни как было", "отменить действие"):
            GUIController.press_hotkey(["ctrl", "z"])
            return "Отменила последнее действие."

        if u_clean in ("верни действие", "шаг вперед", "повтори действие"):
            GUIController.press_hotkey(["ctrl", "y"])
            return "Вернула отменённое действие."

        if u_clean in ("скопируй", "скопируй выделенное", "копировать"):
            GUIController.press_hotkey(["ctrl", "c"])
            return "Скопировала в буфер обмена."

        if u_clean in ("вставь", "вставь из буфера", "вставить"):
            GUIController.press_hotkey(["ctrl", "v"])
            return "Вставила текст из буфера."

        if u_clean in ("выдели все", "выдели всё", "выбрать все"):
            GUIController.press_hotkey(["ctrl", "a"])
            return "Выделила всё содержимое."

        if u_clean in ("создай новый файл", "новый документ", "новый проект", "создай документ"):
            GUIController.press_hotkey(["ctrl", "n"])
            return "Создала новый документ."

        if u_clean in ("на весь экран", "полный экран", "полноэкранный режим", "выйди из полного экрана", "сделай на весь экран"):
            GUIController.press_key("f11")
            return "Переключила полноэкранный режим."

        if u_clean in ("переключи окно", "другое окно", "альт таб", "предыдущее окно"):
            GUIController.press_hotkey(["alt", "tab"])
            return "Переключила активное окно."

        if u_clean in ("закрой окно", "закрой активное окно", "закрой текущее окно"):
            GUIController.press_hotkey(["alt", "f4"])
            return "Закрыла активное окно."

        if u_clean in ("разверни окно", "окно на весь экран"):
            GUIController.press_hotkey(["win", "up"])
            return "Развернула окно."

        if u_clean in ("сверни окно", "сверни текущее окно"):
            GUIController.press_hotkey(["win", "down"])
            return "Свернула активное окно."

        # Type text directly into active app: "напечатай ...", "напиши текст ...", "введи текст ..."
        type_m = re.match(r"^(?:напечатай|напиши\s+текст|введи\s+текст|набери\s+текст)\s+(.+)$", raw_text.strip(), flags=re.IGNORECASE)
        if type_m:
            txt_to_type = type_m.group(1).strip()
            if txt_to_type:
                GUIController.type_text(txt_to_type, press_enter=False)
                return f"Напечатала: «{txt_to_type}»."

        # Find on page / in program: "найди на странице ...", "поиск по странице ..."
        find_m = re.match(r"^(?:найди\s+на\s+странице|поиск\s+по\s+странице|найди\s+в\s+тексте)\s+(.+)$", u_clean)
        if find_m:
            q_find = find_m.group(1).strip()
            GUIController.press_hotkey(["ctrl", "f"])
            time.sleep(0.08)
            GUIController.type_text(q_find, press_enter=True)
            return f"Ищу «{q_find}» на открытой странице."

        # ================= C. EXACT SYSTEM VOLUME & AUDIO CONTROLS =================
        vol_m = re.search(
            r"(?:громкост[ьи]|звук)\s*(?:на\s+|в\s+)?(\d{1,3})\s*(?:%|процент[а-я]*)?",
            u_clean
        )
        if not vol_m:
            vol_m = re.search(
                r"(?:сделай|поставь|установи|включи)\s+(?:громкость|звук)?\s*(?:на\s+)?(\d{1,3})\s*(?:%|процент[а-я]+)",
                u_clean
            )
        if vol_m:
            lvl = max(0, min(100, int(vol_m.group(1))))
            cls.set_system_volume(lvl)
            action_context.last_domain = "volume"
            action_context.last_action_summary = f"Громкость установлена на {lvl}%"
            return f"Установила громкость на {lvl}%."

        if any(p in u_clean for p in ("сделай громче", "прибавь звук", "прибавь громкость", "увеличь громкость", "погромче", "громче")):
            for _ in range(5):
                GUIController.press_key("volumeup")
            action_context.last_domain = "volume"
            return "Сделала звук громче."

        if any(p in u_clean for p in ("сделай тише", "убавь звук", "убавь громкость", "уменьши громкость", "потише", "тише")):
            for _ in range(5):
                GUIController.press_key("volumedown")
            action_context.last_domain = "volume"
            return "Сделала звук тише."

        if any(p in u_clean for p in ("выключи звук", "включи звук", "без звука", "заглуши звук пк", "муть звук")):
            GUIController.press_key("volumemute")
            action_context.last_domain = "volume"
            return "Переключила системный звук."

        # ================= D. SPOTIFY & MEDIA CONTROLS =================
        spotify_search_m = re.match(
            r"^(?:найди|включи|поставь|запусти|поищи)\s+(?:в\s+spotify|на\s+spotify|spotify)\s+(?:песню\s+|трек\s+|группу\s+|музыку\s+)?(.+)$",
            u_clean
        )
        if spotify_search_m:
            query = spotify_search_m.group(1).strip()
            if query and query not in ("музыку", "песню", "трек"):
                encoded = urllib.parse.quote(query)
                OSController.open_application_or_file(f"spotify:search:{encoded}")
                action_context.record_music(True, f"Поиск в Spotify: {query}")
                return f"Открываю поиск «{query}» в Spotify."

        if any(p in u_clean for p in (
            "включи музыку в spotify", "запусти музыку в spotify", "вруби музыку в spotify",
            "включи spotify", "запусти spotify", "открой spotify", "вруби spotify",
            "продолжи музыку в spotify"
        )):
            OSController.open_application_or_file("spotify:")
            if "музык" in u_clean or "включи" in u_clean or "вруби" in u_clean or "продолжи" in u_clean:
                GUIController.press_key("playpause")
                action_context.record_music(True, "Включена музыка в Spotify")
                return "Включаю музыку в Spotify!"
            action_context.record_app("Spotify", "Spotify.exe", domain="music")
            return "Запускаю Spotify."

        if u_clean in (
            "включи музыку", "вруби музыку", "запусти музыку", "продолжи музыку",
            "продолжи воспроизведение", "поставь музыку"
        ):
            GUIController.press_key("playpause")
            action_context.record_music(True, "Включена музыка")
            return "Включаю музыку."

        if any(p in u_clean for p in (
            "поставь музыку на паузу", "останови музыку", "пауза музыки",
            "выключи музыку", "выруби музыку", "останови воспроизведение", "пауза в spotify"
        )):
            GUIController.press_key("playpause")
            action_context.record_music(False, "Музыка поставлена на паузу")
            return "Поставила музыку на паузу."

        if any(p in u_clean for p in (
            "следующий трек", "следующая песня", "переключи трек", "переключи песню",
            "скипни трек", "скипни песню", "дальше трек", "следующий в spotify"
        )):
            GUIController.press_key("nexttrack")
            action_context.record_music(True, "Следующий трек")
            return "Переключила на следующий трек."

        if any(p in u_clean for p in (
            "предыдущий трек", "предыдущая песня", "верни трек", "прошлый трек", "верни песню"
        )):
            GUIController.press_key("prevtrack")
            action_context.record_music(True, "Предыдущий трек")
            return "Вернула предыдущий трек."

        # ================= E. STEAM, DISCORD & POPULAR APPS LAUNCHER =================
        if any(p in u_clean for p in ("открой библиотеку steam", "библиотека steam", "мои игры в steam", "открой игры в steam")):
            OSController.open_application_or_file("steam://open/games")
            action_context.record_app("Steam", "steam.exe", domain="steam")
            return "Открываю библиотеку игр Steam."

        if any(p in u_clean for p in ("открой друзей в steam", "друзья в steam", "список друзей steam")):
            OSController.open_application_or_file("steam://friends/")
            action_context.record_app("Steam", "steam.exe", domain="steam")
            return "Открываю список друзей в Steam."

        if any(p in u_clean for p in ("открой магазин steam", "магазин steam")):
            OSController.open_application_or_file("steam://store")
            action_context.record_app("Steam", "steam.exe", domain="steam")
            return "Открываю магазин Steam."

        if any(p in u_clean for p in ("открой загрузки в steam", "загрузки steam")):
            OSController.open_application_or_file("steam://open/downloads")
            action_context.record_app("Steam", "steam.exe", domain="steam")
            return "Открываю загрузки Steam."

        # Discord actions
        if any(p in u_clean for p in (
            "выключи микрофон в discord", "замуть меня в discord", "замуть микрофон в discord",
            "включи микрофон в discord", "размуть меня в discord", "размуть микрофон в discord",
            "переключи микрофон в discord", "замуть микрофон", "размуть микрофон"
        )):
            GUIController.press_hotkey(["ctrl", "shift", "m"])
            action_context.record_app("Discord", "Discord.exe", domain="discord")
            return "Переключила микрофон в Discord."

        if any(p in u_clean for p in (
            "выключи звук в discord", "заглуши звук в discord", "задефань в discord",
            "включи звук в discord", "переключи звук в discord"
        )):
            GUIController.press_hotkey(["ctrl", "shift", "d"])
            action_context.record_app("Discord", "Discord.exe", domain="discord")
            return "Переключила звук в Discord."

        discord_call_m = re.match(
            r"^(?:позвони|набери|открой чат с|напиши)\s+(?:другу\s+|пользователю\s+)?(.+?)(?:\s+в\s+discord)?$",
            u_clean
        )
        if discord_call_m and ("discord" in u_clean or "другу" in raw_text.lower()):
            friend_name = discord_call_m.group(1).replace("в discord", "").replace("другу", "").strip()
            OSController.open_application_or_file("discord://")
            action_context.record_app("Discord", "Discord.exe", domain="discord")
            if friend_name and friend_name not in ("discord", "в discord"):
                GUIController.press_hotkey(["ctrl", "k"])
                GUIController.type_text(friend_name, press_enter=True)
                return f"Открываю Discord и перехожу к диалогу с {friend_name}."
            return "Открываю Discord для звонка."

        # YouTube & Google Search
        yt_m = re.match(
            r"^(?:найди|включи|открой|поищи|посмотри)\s+(?:на\s+|в\s+)?youtube\s+(?:видео\s+|ролик\s+)?(.+)$",
            u_clean
        )
        if yt_m:
            q = yt_m.group(1).strip()
            encoded = urllib.parse.quote(q)
            OSController.open_application_or_file(f"https://www.youtube.com/results?search_query={encoded}")
            action_context.record_app("YouTube", "chrome.exe", domain="browser", summary=f"Поиск на YouTube: {q}")
            return f"Ищу «{q}» на YouTube."

        google_m = re.match(
            r"^(?:открой\s+в\s+гугле|загугли\s+в\s+браузере|поищи\s+в\s+браузере)\s+(.+)$",
            u_clean
        )
        if google_m:
            q = google_m.group(1).strip()
            encoded = urllib.parse.quote(q)
            OSController.open_application_or_file(f"https://www.google.com/search?q={encoded}")
            action_context.record_app("Google", "chrome.exe", domain="browser", summary=f"Поиск в Google: {q}")
            return f"Открываю поиск «{q}» в браузере."

        # Universal App & Game Launch ("открой обс", "запусти фотошоп", "открой блендер", "запусти кс 2", etc.)
        launch_m = re.match(
            r"^(?:запусти|открой|включи|вруби)\s+(?:программу\s+|приложение\s+|игру\s+)?(.+?)(?:\s+в\s+steam|\s+через\s+steam)?$",
            u_clean
        )
        if launch_m:
            candidate = launch_m.group(1).strip()

            # 1. Check 100+ Popular Apps Catalog
            if candidate in cls.POPULAR_APPS_CATALOG:
                target_spec, title, proc_exe, dom = cls.POPULAR_APPS_CATALOG[candidate]
                cls.smart_launch_app(target_spec, title)
                action_context.record_app(title, proc_exe, domain=dom, summary=f"Запущено приложение {title}")
                return f"Запускаю {title}."

            # 2. Check built-in Steam games
            if candidate in cls.STEAM_GAMES_MAP:
                appid, title = cls.STEAM_GAMES_MAP[candidate]
                OSController.open_application_or_file(f"steam://rungameid/{appid}")
                action_context.record_app(title, "steam.exe", domain="steam", summary=f"Запущена игра {title}")
                return f"Запускаю {title} в Steam!"

            # 3. Check locally installed Steam games from appmanifest_*.acf
            installed_steam = cls.discover_installed_steam_games()
            for g_key, (appid, title) in installed_steam.items():
                if candidate == g_key or (len(candidate) >= 3 and candidate in g_key):
                    OSController.open_application_or_file(f"steam://rungameid/{appid}")
                    action_context.record_app(title, "steam.exe", domain="steam", summary=f"Запущена игра {title}")
                    return f"Запускаю установленную игру {title} в Steam!"

            # 4. Check Start Menu / Desktop shortcuts dynamically for any installed program
            shortcuts = cls.discover_installed_shortcuts()
            if candidate in shortcuts:
                OSController.open_application_or_file(shortcuts[candidate])
                action_context.record_app(candidate.title(), "", domain="app")
                return f"Запускаю {candidate.title()}."
            for lnk_name, lnk_path in shortcuts.items():
                if len(candidate) >= 4 and candidate in lnk_name:
                    OSController.open_application_or_file(lnk_path)
                    action_context.record_app(lnk_name.title(), "", domain="app")
                    return f"Запускаю {lnk_name.title()}."

        # Universal App Close ("закрой обс", "закрой фотошоп", "закрой блендер", "закрой ворд", etc.)
        close_m = re.match(r"^(?:закрой|выключи|заверши|убей)\s+(?:программу\s+|приложение\s+|игру\s+)?(.+)$", u_clean)
        if close_m:
            candidate = close_m.group(1).strip()
            if candidate in cls.POPULAR_APPS_CATALOG:
                _, title, proc_exe, _ = cls.POPULAR_APPS_CATALOG[candidate]
                if proc_exe:
                    OSController.kill_process(proc_exe)
                    return f"Закрыла {title}."

        if any(p in u_clean for p in ("сделай скриншот", "скриншот экрана", "сфоткай экран")):
            GUIController.press_hotkey(["win", "shift", "s"])
            return "Запустила создание скриншота."

        return None
