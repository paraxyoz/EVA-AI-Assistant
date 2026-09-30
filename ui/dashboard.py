"""
Main Dashboard and Settings Window for Personal AI Assistant.
Provides complete control over models, audio, vision, memory, and desktop avatar.
"""

import sys
from typing import Optional
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, QCheckBox,
    QSlider, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QSplitter, QStatusBar, QFileDialog
)
from PyQt6.QtGui import QFont, QIcon, QColor

from config import config_manager
from core.agent import assistant_agent, AgentState
from core.llm_provider import llm_client
from expression.voice import voice_speaker
from perception.ears import audio_ears
from memory.db import memory_db
from memory.system_profiler import SystemProfiler
from ui.theme import DARK_THEME_QSS


class DashboardWindow(QMainWindow):
    """Main settings and monitoring window."""

    def __init__(self, avatar_ref=None):
        super().__init__()
        self.avatar = avatar_ref
        self.setWindowTitle("Apex AI Assistant — Центр Управления")
        self.resize(960, 680)
        self.setStyleSheet(DARK_THEME_QSS)

        self._init_ui()
        self._load_settings_into_ui()
        self._connect_agent_signals()

    def _init_ui(self):
        main_widget = QWidget(self)
        main_widget.setObjectName("MainContainer")
        self.setCentralWidget(main_widget)

        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # Header Bar
        header = QHBoxLayout()
        title_label = QLabel("⚡ APEX AI ASSISTANT")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #58a6ff;")
        
        self.status_pill = QLabel("● IDLE")
        self.status_pill.setStyleSheet("""
            background-color: #1f6feb20;
            color: #58a6ff;
            border: 1px solid #1f6feb;
            border-radius: 12px;
            padding: 4px 14px;
            font-weight: bold;
        """)

        self.btn_mic_toggle = QPushButton("🎤 Слушать: ВКЛ")
        self.btn_mic_toggle.setObjectName("PrimaryButton")
        self.btn_mic_toggle.clicked.connect(self._toggle_mic)

        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(self.status_pill)
        header.addWidget(self.btn_mic_toggle)
        root_layout.addLayout(header)

        # Tab Widget
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # Build individual tabs
        self._build_tab_chat()
        self._build_tab_providers()
        self._build_tab_audio()
        self._build_tab_memory()
        self._build_tab_avatar()

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готов к работе. Полный доступ к Windows активирован.")

    # TAB 1: Chat & Terminal
    def _build_tab_chat(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        # Log & Thoughts Terminal
        lbl_log = QLabel("Живой терминал мыслей и выполнения команд:")
        self.txt_logs = QTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setStyleSheet("background-color: #0d1117; font-family: 'Consolas', monospace; font-size: 12px; color: #7ee787;")

        # Quick Control Buttons
        btn_layout = QHBoxLayout()
        self.btn_clear_log = QPushButton("Очистить лог")
        self.btn_clear_log.clicked.connect(self.txt_logs.clear)
        self.btn_stop_speech = QPushButton("🔇 Прервать речь")
        self.btn_stop_speech.clicked.connect(voice_speaker.stop)
        btn_layout.addWidget(self.btn_clear_log)
        btn_layout.addWidget(self.btn_stop_speech)
        btn_layout.addStretch()

        # Command Input Box
        input_box = QHBoxLayout()
        self.chk_include_vision = QCheckBox("👁️ Прикрепить снимок экрана")
        self.edt_user_input = QLineEdit()
        self.edt_user_input.setPlaceholderText("Введите команду или вопрос (например: 'Открой блокнот и напиши Привет' или 'Что у меня на экране?')...")
        self.edt_user_input.returnPressed.connect(self._send_text_command)

        self.btn_send = QPushButton("Отправить")
        self.btn_send.setObjectName("PrimaryButton")
        self.btn_send.clicked.connect(self._send_text_command)

        input_box.addWidget(self.chk_include_vision)
        input_box.addWidget(self.edt_user_input, 1)
        input_box.addWidget(self.btn_send)

        layout.addWidget(lbl_log)
        layout.addWidget(self.txt_logs, 1)
        layout.addLayout(btn_layout)
        layout.addLayout(input_box)
        self.tabs.addTab(tab, "💬 Чат и Терминал")

    # TAB 2: AI Providers & Models
    def _build_tab_providers(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        # Provider Selector
        grp_prov = QGroupBox("Выбор провайдера LLM (Без Цензуры)")
        prov_layout = QVBoxLayout(grp_prov)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Активный провайдер:"))
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItems([
            "Google Gemini (Сверхбыстрый + Зрение)",
            "LM Studio (Локально: localhost:1234)",
            "Ollama (Локально: localhost:11434)",
            "OpenRouter (Облако / Любые модели)",
            "Groq (Сверхбыстрый API)",
            "OpenAI (GPT-4o / GPT-4)",
            "Кастомный OpenAI-совместимый сервер"
        ])
        self.cmb_provider.currentIndexChanged.connect(self._on_provider_changed)
        row1.addWidget(self.cmb_provider, 1)
        prov_layout.addLayout(row1)

        # Endpoint & Key
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("API Base URL:"))
        self.edt_api_base = QLineEdit()
        row2.addWidget(self.edt_api_base, 1)
        prov_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("API Key:"))
        self.edt_api_key = QLineEdit()
        self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        row3.addWidget(self.edt_api_key, 1)
        prov_layout.addLayout(row3)

        # Models
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Основная модель (Код/Текст):"))
        self.edt_model = QLineEdit()
        row4.addWidget(self.edt_model, 1)

        row4.addWidget(QLabel("Vision модель (Зрение):"))
        self.edt_vision_model = QLineEdit()
        row4.addWidget(self.edt_vision_model, 1)
        prov_layout.addLayout(row4)

        # Test Connection Button
        row_test = QHBoxLayout()
        self.btn_test_llm = QPushButton("🔍 Проверить подключение к LLM")
        self.btn_test_llm.clicked.connect(self._test_llm_connection)
        self.lbl_llm_status = QLabel("")
        row_test.addWidget(self.btn_test_llm)
        row_test.addWidget(self.lbl_llm_status, 1)
        prov_layout.addLayout(row_test)

        layout.addWidget(grp_prov)

        # System Prompt
        grp_prompt = QGroupBox("Системный промт и Личность (Uncensored)")
        prompt_layout = QVBoxLayout(grp_prompt)
        self.txt_system_prompt = QTextEdit()
        prompt_layout.addWidget(self.txt_system_prompt)
        layout.addWidget(grp_prompt, 1)

        # Save Button
        self.btn_save_providers = QPushButton("💾 Сохранить настройки провайдера")
        self.btn_save_providers.setObjectName("PrimaryButton")
        self.btn_save_providers.clicked.connect(self._save_provider_settings)
        layout.addWidget(self.btn_save_providers)

        self.tabs.addTab(tab, "🧠 ИИ и Модели")

    # TAB 3: Audio & Voice
    def _build_tab_audio(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        # Microphone Box
        grp_mic = QGroupBox("Настройки Микрофона и Слуха")
        mic_layout = QVBoxLayout(grp_mic)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Устройство ввода (Микрофон):"))
        self.cmb_mic_devices = QComboBox()
        self._populate_mic_devices()
        r1.addWidget(self.cmb_mic_devices, 1)
        mic_layout.addLayout(r1)

        # Real-time Volume Level Meter
        from PyQt6.QtWidgets import QProgressBar
        r_vol = QHBoxLayout()
        r_vol.addWidget(QLabel("Уровень звука микрофона:"))
        self.bar_mic_level = QProgressBar()
        self.bar_mic_level.setRange(0, 100)
        self.bar_mic_level.setValue(0)
        self.bar_mic_level.setTextVisible(False)
        self.bar_mic_level.setFixedHeight(12)
        self.bar_mic_level.setStyleSheet("""
            QProgressBar {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #2ea043;
                border-radius: 5px;
            }
        """)
        r_vol.addWidget(self.bar_mic_level, 1)
        mic_layout.addLayout(r_vol)

        # Sensitivity Slider
        r_sens = QHBoxLayout()
        r_sens.addWidget(QLabel("Чувствительность срабатывания:"))
        self.slider_sens = QSlider(Qt.Orientation.Horizontal)
        self.slider_sens.setRange(2, 25) # 0.002 to 0.025
        self.slider_sens.setValue(6)
        self.lbl_sens_val = QLabel("Высокая (0.006)")
        self.slider_sens.valueChanged.connect(self._on_sens_changed)
        r_sens.addWidget(self.slider_sens, 1)
        r_sens.addWidget(self.lbl_sens_val)
        mic_layout.addLayout(r_sens)

        # Flagship Engine Info
        r_model = QHBoxLayout()
        r_model.addWidget(QLabel("Движок распознавания речи:"))
        lbl_engine_info = QLabel("⚡ Флагманский Neural Whisper (Beam Search 5 + Audio Pre-Prompt)")
        lbl_engine_info.setStyleSheet("color: #7ee787; font-weight: bold;")
        r_model.addWidget(lbl_engine_info, 1)
        mic_layout.addLayout(r_model)

        r2 = QHBoxLayout()
        self.chk_wake_word = QCheckBox("Активация по кодовому слову (Wake-Word)")
        self.edt_wake_word = QLineEdit()
        self.edt_wake_word.setPlaceholderText("Например: ассистент, джарвис, апекс")
        r2.addWidget(self.chk_wake_word)
        r2.addWidget(self.edt_wake_word, 1)
        mic_layout.addLayout(r2)

        layout.addWidget(grp_mic)

        # Voice Box
        grp_tts = QGroupBox("Настройки Синтеза Речи (Голос)")
        tts_layout = QVBoxLayout(grp_tts)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Голос озвучки:"))
        self.cmb_tts_voice = QComboBox()
        self.voice_keys = [
            "google_female",
            "google_male",
            "elevenlabs",
            "puck",
            "charon",
            "aoede",
            "kore",
            "fenrir"
        ]
        from expression.voice import VoiceSpeaker
        for k in self.voice_keys:
            self.cmb_tts_voice.addItem(VoiceSpeaker.VOICE_PROFILES.get(k, k), k)
        r3.addWidget(self.cmb_tts_voice, 1)
        tts_layout.addLayout(r3)

        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Скорость речи:"))
        self.slider_speech_rate = QSlider(Qt.Orientation.Horizontal)
        self.slider_speech_rate.setRange(-50, 50)
        self.slider_speech_rate.setValue(10)
        self.lbl_rate_val = QLabel("+10%")
        self.slider_speech_rate.valueChanged.connect(lambda v: self.lbl_rate_val.setText(f"{'+' if v>=0 else ''}{v}%"))
        r4.addWidget(self.slider_speech_rate, 1)
        r4.addWidget(self.lbl_rate_val)
        tts_layout.addLayout(r4)

        r5 = QHBoxLayout()
        self.btn_test_voice = QPushButton("🔊 Протестировать голос")
        self.btn_test_voice.clicked.connect(self._test_voice_playback)
        self.chk_play_audio = QCheckBox("Озвучивать ответы ассистента голосом")
        r5.addWidget(self.btn_test_voice)
        r5.addWidget(self.chk_play_audio)
        r5.addStretch()
        tts_layout.addLayout(r5)

        layout.addWidget(grp_tts)

        # ElevenLabs Custom Voice Box
        grp_el = QGroupBox("👑 Настройки ElevenLabs (Клонирование и Библиотека 10,000+ Голосов)")
        el_layout = QVBoxLayout(grp_el)

        r_el1 = QHBoxLayout()
        r_el1.addWidget(QLabel("ElevenLabs API Key:"))
        self.edt_eleven_key = QLineEdit()
        self.edt_eleven_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edt_eleven_key.setPlaceholderText("Вставьте ваш ключ с сайта elevenlabs.io (xi-api-key)...")
        r_el1.addWidget(self.edt_eleven_key, 1)
        el_layout.addLayout(r_el1)

        r_el2 = QHBoxLayout()
        r_el2.addWidget(QLabel("Voice ID (ID Голоса):"))
        self.edt_eleven_voice_id = QLineEdit()
        self.edt_eleven_voice_id.setPlaceholderText("Например: 21m00Tcm4TlvDq8ikWAM (Rachel) или ID вашего клона...")
        r_el2.addWidget(self.edt_eleven_voice_id, 1)
        
        btn_open_library = QPushButton("🌐 Открыть Voice Library")
        btn_open_library.clicked.connect(lambda: os.system("start https://elevenlabs.io/voice-library"))
        r_el2.addWidget(btn_open_library)
        el_layout.addLayout(r_el2)

        r_el3 = QHBoxLayout()
        r_el3.addWidget(QLabel("Модель ElevenLabs:"))
        self.cmb_eleven_model = QComboBox()
        self.cmb_eleven_model.addItems([
            "eleven_turbo_v2_5 (Ультра-скорость ~200мс / Идеально для диалогов)",
            "eleven_multilingual_v2 (Максимальная кинематографичность и эмоциональность)"
        ])
        r_el3.addWidget(self.cmb_eleven_model, 1)
        el_layout.addLayout(r_el3)

        layout.addWidget(grp_el)
        layout.addStretch()

        btn_save_audio = QPushButton("💾 Сохранить настройки звука")
        btn_save_audio.setObjectName("PrimaryButton")
        btn_save_audio.clicked.connect(self._save_audio_settings)
        layout.addWidget(btn_save_audio)

        self.tabs.addTab(tab, "🎙️ Аудио и Речь")

    # TAB 4: Memory & Hardware
    def _build_tab_memory(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        # Hardware specs snapshot
        grp_hw = QGroupBox("Характеристики вашего ПК (Известно Ассистенту)")
        hw_layout = QVBoxLayout(grp_hw)
        self.lbl_hw_info = QLabel("Загрузка данных о системе...")
        self.lbl_hw_info.setWordWrap(True)
        self.lbl_hw_info.setStyleSheet("color: #7ee787; font-family: 'Consolas', monospace;")
        hw_layout.addWidget(self.lbl_hw_info)
        layout.addWidget(grp_hw)

        # Stored Facts Table
        grp_facts = QGroupBox("Долговременная память о вас (Факты и предпочтения)")
        facts_layout = QVBoxLayout(grp_facts)

        self.tbl_facts = QTableWidget()
        self.tbl_facts.setColumnCount(3)
        self.tbl_facts.setHorizontalHeaderLabels(["Категория", "Ключ / Факт", "Значение"])
        self.tbl_facts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        facts_layout.addWidget(self.tbl_facts)

        # Facts Buttons
        btn_row = QHBoxLayout()
        self.btn_add_fact = QPushButton("➕ Добавить факт")
        self.btn_add_fact.clicked.connect(self._add_fact_dialog)
        self.btn_del_fact = QPushButton("🗑️ Удалить выбранный")
        self.btn_del_fact.clicked.connect(self._delete_selected_fact)
        self.btn_clear_history = QPushButton("🧹 Очистить историю сообщений")
        self.btn_clear_history.setObjectName("DangerButton")
        self.btn_clear_history.clicked.connect(self._clear_conversation_history)

        btn_row.addWidget(self.btn_add_fact)
        btn_row.addWidget(self.btn_del_fact)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_clear_history)
        facts_layout.addLayout(btn_row)

        layout.addWidget(grp_facts, 1)
        self.tabs.addTab(tab, "🧠 Память и ПК")

    # TAB 5: Avatar Settings
    def _build_tab_avatar(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        grp_av = QGroupBox("Внешний вид Аватара на Рабочем Столе")
        av_layout = QVBoxLayout(grp_av)

        self.chk_show_avatar = QCheckBox("Отображать плавающий аватар на рабочем столе")
        self.chk_avatar_top = QCheckBox("Всегда поверх всех окон (Always on Top)")

        # Size slider
        r_size = QHBoxLayout()
        r_size.addWidget(QLabel("Размер аватара (px):"))
        self.slider_avatar_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_avatar_size.setRange(80, 260)
        self.lbl_size_val = QLabel("150px")
        self.slider_avatar_size.valueChanged.connect(lambda v: self.lbl_size_val.setText(f"{v}px"))
        r_size.addWidget(self.slider_avatar_size, 1)
        r_size.addWidget(self.lbl_size_val)

        # Reset position button
        btn_reset_pos = QPushButton("📍 Сбросить позицию в правый нижний угол")
        btn_reset_pos.clicked.connect(self._reset_avatar_pos)

        av_layout.addWidget(self.chk_show_avatar)
        av_layout.addWidget(self.chk_avatar_top)
        av_layout.addLayout(r_size)
        av_layout.addWidget(btn_reset_pos)
        layout.addWidget(grp_av)
        layout.addStretch()

        btn_save_av = QPushButton("💾 Применить настройки аватара")
        btn_save_av.setObjectName("PrimaryButton")
        btn_save_av.clicked.connect(self._save_avatar_settings)
        layout.addWidget(btn_save_av)

        self.tabs.addTab(tab, "✨ Аватар")

    def _on_sens_changed(self, val: int):
        thresh = val / 1000.0
        self.lbl_sens_val.setText(f"{thresh:.3f}")
        config_manager.set("audio.energy_threshold", thresh, auto_save=False)

    def _update_mic_meter(self):
        if hasattr(self, 'bar_mic_level'):
            # Scale rms to 0-100%
            val = int(min(100, audio_ears.current_volume_rms * 3000))
            self.bar_mic_level.setValue(val)

    # UI Helpers & Loading
    def _populate_mic_devices(self):
        self.cmb_mic_devices.clear()
        devs = audio_ears.list_input_devices()
        saved_idx = config_manager.get("audio.input_device_index")
        sel_idx = 0
        for i, d in enumerate(devs):
            self.cmb_mic_devices.addItem(f"{d['name']} (ID: {d['index']})", d["index"])
            if saved_idx is not None and d["index"] == saved_idx:
                sel_idx = i
            elif saved_idx is None and d.get("default"):
                sel_idx = i
        self.cmb_mic_devices.setCurrentIndex(sel_idx)

    def _load_settings_into_ui(self):
        # Provider
        prov_name = config_manager.get("llm_provider", "gemini")
        mapping = {
            "gemini": 0, "lm_studio": 1, "ollama": 2, "openrouter": 3,
            "groq": 4, "openai": 5, "custom": 6
        }
        self.cmb_provider.setCurrentIndex(mapping.get(prov_name, 0))
        self._update_provider_fields(prov_name)

        # System Prompt
        self.txt_system_prompt.setPlainText(config_manager.get("system_prompt", ""))

        # Audio
        self.chk_wake_word.setChecked(config_manager.get("audio.wake_word_enabled", True))
        self.edt_wake_word.setText(config_manager.get("audio.wake_word", "ассистент"))
        self.chk_play_audio.setChecked(config_manager.get("audio.play_response_audio", True))
        
        sens = int(float(config_manager.get("audio.energy_threshold", 0.006)) * 1000)
        self.slider_sens.setValue(max(2, min(25, sens)))
        self.lbl_sens_val.setText(f"{sens/1000.0:.3f}")

        # Start live mic volume meter
        self.mic_timer = QTimer(self)
        self.mic_timer.timeout.connect(self._update_mic_meter)
        self.mic_timer.start(50)

        voice = config_manager.get("audio.voice_profile", "google_female")
        if voice in getattr(self, "voice_keys", []):
            self.cmb_tts_voice.setCurrentIndex(self.voice_keys.index(voice))
        else:
            self.cmb_tts_voice.setCurrentIndex(0)

        # ElevenLabs
        self.edt_eleven_key.setText(config_manager.get("audio.elevenlabs.api_key", ""))
        self.edt_eleven_voice_id.setText(config_manager.get("audio.elevenlabs.voice_id", "21m00Tcm4TlvDq8ikWAM"))
        m_id = config_manager.get("audio.elevenlabs.model_id", "eleven_turbo_v2_5")
        self.cmb_eleven_model.setCurrentIndex(0 if "turbo" in m_id else 1)

        # Avatar
        self.chk_show_avatar.setChecked(config_manager.get("avatar.show_on_desktop", True))
        self.chk_avatar_top.setChecked(config_manager.get("avatar.always_on_top", True))
        av_size = config_manager.get("avatar.size", 150)
        self.slider_avatar_size.setValue(av_size)
        self.lbl_size_val.setText(f"{av_size}px")

        # Hardware & Facts
        self._refresh_hw_and_facts()

    def _update_provider_fields(self, prov_name: str):
        prov_cfg = config_manager.get(f"providers.{prov_name}", {})
        self.edt_api_base.setText(prov_cfg.get("api_base", ""))
        self.edt_api_key.setText(prov_cfg.get("api_key", ""))
        self.edt_model.setText(prov_cfg.get("model", ""))
        self.edt_vision_model.setText(prov_cfg.get("vision_model", ""))

    def _on_provider_changed(self, index: int):
        keys = ["gemini", "lm_studio", "ollama", "openrouter", "groq", "openai", "custom"]
        prov_name = keys[index]
        self._update_provider_fields(prov_name)

    def _refresh_hw_and_facts(self):
        # HW
        hw_text = SystemProfiler.get_full_system_context()
        self.lbl_hw_info.setText(hw_text)

        # Facts
        facts = memory_db.get_all_facts()
        self.tbl_facts.setRowCount(len(facts))
        for row, f in enumerate(facts):
            self.tbl_facts.setItem(row, 0, QTableWidgetItem(f["category"]))
            self.tbl_facts.setItem(row, 1, QTableWidgetItem(f["key"]))
            self.tbl_facts.setItem(row, 2, QTableWidgetItem(f["value"]))

    def _connect_agent_signals(self):
        from core.events import agent_signals
        agent_signals.state_changed.connect(self._on_agent_state_changed_str)
        agent_signals.thought_logged.connect(self._append_log)
        agent_signals.response_generated.connect(self._on_agent_response)

    def _on_agent_state_changed_str(self, state_str: str):
        try:
            state = AgentState(state_str)
        except Exception:
            state = AgentState.IDLE
        self._on_agent_state_changed(state)

    def _on_agent_state_changed(self, state: AgentState):
        color_map = {
            AgentState.IDLE: ("#58a6ff", "#1f6feb20"),
            AgentState.LISTENING: ("#2ea043", "#23863630"),
            AgentState.THINKING: ("#a855f7", "#8957e530"),
            AgentState.SPEAKING: ("#ec4899", "#db61a230"),
            AgentState.WORKING: ("#f59e0b", "#d2992230"),
            AgentState.ERROR: ("#f85149", "#da363330")
        }
        fg, bg = color_map.get(state, ("#58a6ff", "#1f6feb20"))
        self.status_pill.setText(f"● {state.value}")
        self.status_pill.setStyleSheet(f"background-color: {bg}; color: {fg}; border: 1px solid {fg}; border-radius: 12px; padding: 4px 14px; font-weight: bold;")
        
        if self.avatar:
            self.avatar.set_state(state)

    def _append_log(self, text: str):
        self.txt_logs.append(text)

    def _on_agent_response(self, text: str):
        if self.avatar:
            self.avatar.show_speech(text)
        self._refresh_hw_and_facts()

    # User Actions
    def _send_text_command(self):
        text = self.edt_user_input.text().strip()
        if not text:
            return
        self.edt_user_input.clear()
        include_vision = self.chk_include_vision.isChecked()
        self.txt_logs.append(f"\n👤 Вы: {text}")
        assistant_agent.process_user_input(text, include_vision=include_vision)

    def _toggle_mic(self):
        if audio_ears._is_running:
            audio_ears.stop_listening()
            self.btn_mic_toggle.setText("🎤 Слушать: ВЫКЛ")
            self.btn_mic_toggle.setObjectName("")
            self.btn_mic_toggle.setStyleSheet("background-color: #30363d;")
        else:
            audio_ears.start_listening()
            self.btn_mic_toggle.setText("🎤 Слушать: ВКЛ")
            self.btn_mic_toggle.setObjectName("PrimaryButton")
            self.btn_mic_toggle.setStyleSheet("")

    def _test_llm_connection(self):
        self._save_provider_settings()
        self.lbl_llm_status.setText("⏳ Проверка...")
        res = llm_client.test_connection()
        if res.get("success"):
            self.lbl_llm_status.setText(f"✅ {res.get('message')}")
            self.lbl_llm_status.setStyleSheet("color: #7ee787; font-weight: bold;")
        else:
            self.lbl_llm_status.setText(f"❌ {res.get('error')}")
            self.lbl_llm_status.setStyleSheet("color: #f85149; font-weight: bold;")

    def _test_voice_playback(self):
        voice_speaker.speak("Здравствуйте! Голосовой модуль персонального ассистента работает отлично.")

    def _save_provider_settings(self):
        keys = ["gemini", "lm_studio", "ollama", "openrouter", "groq", "openai", "custom"]
        prov_name = keys[self.cmb_provider.currentIndex()]
        
        config_manager.set("llm_provider", prov_name, auto_save=False)
        config_manager.set(f"providers.{prov_name}.api_base", self.edt_api_base.text().strip(), auto_save=False)
        config_manager.set(f"providers.{prov_name}.api_key", self.edt_api_key.text().strip(), auto_save=False)
        config_manager.set(f"providers.{prov_name}.model", self.edt_model.text().strip(), auto_save=False)
        config_manager.set(f"providers.{prov_name}.vision_model", self.edt_vision_model.text().strip(), auto_save=False)
        config_manager.set("system_prompt", self.txt_system_prompt.toPlainText().strip(), auto_save=True)
        
        self.status_bar.showMessage("Настройки провайдера и системный промт сохранены!", 3000)

    def _save_audio_settings(self):
        dev_idx = self.cmb_mic_devices.currentData()
        config_manager.set("audio.input_device_index", dev_idx, auto_save=False)
        config_manager.set("audio.wake_word_enabled", self.chk_wake_word.isChecked(), auto_save=False)
        config_manager.set("audio.wake_word", self.edt_wake_word.text().strip().lower(), auto_save=False)
        config_manager.set("audio.play_response_audio", self.chk_play_audio.isChecked(), auto_save=False)
        
        sens_thresh = self.slider_sens.value() / 1000.0
        config_manager.set("audio.energy_threshold", sens_thresh, auto_save=False)

        sel_voice = self.cmb_tts_voice.currentData()
        config_manager.set("audio.voice_profile", sel_voice, auto_save=False)

        # ElevenLabs Settings
        config_manager.set("audio.elevenlabs.api_key", self.edt_eleven_key.text().strip(), auto_save=False)
        config_manager.set("audio.elevenlabs.voice_id", self.edt_eleven_voice_id.text().strip(), auto_save=False)
        m_str = "eleven_turbo_v2_5" if self.cmb_eleven_model.currentIndex() == 0 else "eleven_multilingual_v2"
        config_manager.set("audio.elevenlabs.model_id", m_str, auto_save=False)

        rate_val = self.slider_speech_rate.value()
        config_manager.set("audio.speech_rate", f"{'+' if rate_val>=0 else ''}{rate_val}%", auto_save=True)
        
        # Live restart of audio stream if active
        if audio_ears._is_running:
            audio_ears.stop_listening()
            audio_ears.start_listening()

        self.status_bar.showMessage("Настройки звука успешно применены!", 3000)

    def _save_avatar_settings(self):
        size = self.slider_avatar_size.value()
        on_top = self.chk_avatar_top.isChecked()
        show = self.chk_show_avatar.isChecked()

        config_manager.set("avatar.size", size, auto_save=False)
        config_manager.set("avatar.always_on_top", on_top, auto_save=False)
        config_manager.set("avatar.show_on_desktop", show, auto_save=True)

        if self.avatar:
            self.avatar.setFixedSize(size, size)
            if show:
                self.avatar.show()
            else:
                self.avatar.hide()

        self.status_bar.showMessage("Настройки аватара применены!", 3000)

    def _reset_avatar_pos(self):
        if self.avatar:
            screen = self.avatar.screen().geometry()
            size = self.avatar.width()
            self.avatar.move(screen.width() - size - 40, screen.height() - size - 100)
            config_manager.set("avatar.position_x", self.avatar.x(), auto_save=False)
            config_manager.set("avatar.position_y", self.avatar.y(), auto_save=True)

    def _add_fact_dialog(self):
        from PyQt6.QtWidgets import QInputDialog
        cat, ok1 = QInputDialog.getText(self, "Новый факт", "Категория (например: user, work, pref):")
        if not ok1 or not cat: return
        key, ok2 = QInputDialog.getText(self, "Новый факт", "Ключ (например: любимый браузер):")
        if not ok2 or not key: return
        val, ok3 = QInputDialog.getText(self, "Новый факт", "Значение (например: Chrome):")
        if not ok3 or not val: return
        
        memory_db.remember_fact(cat.strip(), key.strip(), val.strip())
        self._refresh_hw_and_facts()

    def _delete_selected_fact(self):
        row = self.tbl_facts.currentRow()
        if row >= 0:
            key_item = self.tbl_facts.item(row, 1)
            if key_item:
                memory_db.forget_fact(key_item.text())
                self._refresh_hw_and_facts()

    def _clear_conversation_history(self):
        reply = QMessageBox.question(self, "Подтверждение", "Очистить всю историю диалогов?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            memory_db.clear_history()
            self.status_bar.showMessage("История очищена.", 3000)
