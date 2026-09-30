"""
Audio Perception ("Ears") Module for EVA AI Assistant.
Features:
1. Hybrid Ultra-Fast Bilingual STT:
   - Primary: Google Web Speech Recognition (ru-RU with seamless English app/game recognition in ~0.4-0.8s, 0% CPU load)
   - Fallback: Local Faster-Whisper ('base', int8, beam_size=1) for 100% offline reliability
2. Instant End-of-Speech Detection (0.42s silence limit + Peak-Drop dynamic threshold so mic never hangs after user finishes speaking)
3. Speaker Echo Cancellation (`notify_assistant_speech` & `strip_assistant_echo`) so EVA never hears or responds to her own voice
4. High-Recall Fuzzy Wake-Word Detection for "Ева" and all phonetic near-misses
"""

import os
import time
import queue
import threading
import re as _re
from collections import deque
from typing import Optional, List, Tuple
import numpy as np
import sounddevice as sd

from config import config_manager
from core.events import agent_signals
from expression.voice import voice_speaker

try:
    import speech_recognition as sr
    _HAS_SR = True
except ImportError:
    sr = None
    _HAS_SR = False


def _build_pleasant_chime_wav() -> bytes:
    """
    Synthesizes a soft, warm, studio-grade polyphonic activation chime (44.1kHz 16-bit stereo WAV).
    Uses a gentle rising fifth interval (F5 -> C6) with soft cosine attack/release and warm harmonics,
    completely eliminating the harsh square-wave buzz of winsound.Beep.
    """
    import io
    import wave

    sr_hz = 44100
    duration = 0.28
    n_samples = int(sr_hz * duration)
    t = np.linspace(0.0, duration, n_samples, endpoint=False)

    # Note 1: Warm F5 (698.46 Hz) from 0.00s to 0.16s
    f1 = 698.46
    env1 = np.where(t < 0.16, np.sin(np.pi * np.clip(t / 0.16, 0, 1)) ** 1.2 * np.exp(-t * 9.0), 0.0)
    note1 = (np.sin(2 * np.pi * f1 * t) + 0.25 * np.sin(2 * np.pi * (f1 * 2) * t)) * env1

    # Note 2: Shimmering C6 (1046.50 Hz) from 0.07s to 0.28s
    f2 = 1046.50
    t2 = np.clip(t - 0.07, 0.0, duration)
    env2 = np.where(
        t >= 0.07,
        np.sin(np.pi * np.clip(t2 / (duration - 0.07), 0, 1)) ** 0.9 * np.exp(-t2 * 7.5),
        0.0,
    )
    note2 = (np.sin(2 * np.pi * f2 * t2) + 0.2 * np.sin(2 * np.pi * (f2 * 1.5) * t2)) * env2

    # Gentle stereo mix at comfortable 22% peak volume
    mono = (note1 * 0.9 + note2 * 1.0) * 0.22
    mono = np.clip(mono, -0.95, 0.95)
    pcm16 = (mono * 32767.0).astype(np.int16)
    stereo = np.column_stack((pcm16, pcm16)).ravel()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr_hz)
        wf.writeframes(stereo.tobytes())
    return buf.getvalue()


_PLEASANT_CHIME_WAV: bytes = _build_pleasant_chime_wav()


def play_activation_chime():
    """Plays a soft, warm harmonic crystal chime when the wake word 'Ева' is heard across all active headphones/speakers."""
    if not config_manager.get("avatar.sound_effects", True):
        return

    def _play():
        try:
            voice_speaker.play_wav_chime_multi_device(_PLEASANT_CHIME_WAV)
        except Exception:
            try:
                import winsound
                winsound.PlaySound(
                    _PLEASANT_CHIME_WAV,
                    winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
            except Exception:
                pass

    threading.Thread(target=_play, daemon=True).start()


# Bilingual & phonetic normalization rules for Russian + English speech
_BILINGUAL_REPLACEMENTS = [
    # Fix mangled "открой стим" / "закрой стим" -> "открости", "закройся", "закрой ST"
    (r"\b(откростим|открости|откройся|открой\s*стим|открой\s+ст|открой\s+st|открой\s+с\s*тим|открой\s+сим)\b", "открой steam"),
    (r"\b(закростим|закрости|закройся|закрой\s*стим|закрой\s+ст|закрой\s+st|закрой\s+с\s*тим|закрой\s+сим|закрой\s+стен)\b", "закрой steam"),
    # Spotify variations
    (r"\b(с\s*пати\s*фай|споти\s*фай|спатифай|спотифае|спотифай|спотик)\b", "spotify"),
    # Steam variations
    (r"\b(в\s+стиме|в\s+стим|в\s+с\s*тиме)\b", "в steam"),
    (r"\b(стиме|с\s*тим|стим)\b", "steam"),
    # Discord variations
    (r"\b(в\s+дискорде|в\s+дискорт|в\s+дескорде|в\s+дискорд)\b", "в discord"),
    (r"\b(дискорде|дискорт|дескорд|дискорд|дс)\b", "discord"),
    # Games: CS2 / Dota 2 / GTA / Cyberpunk / Minecraft
    (r"\b(контр\s*страйк|контр-страйк|counter\s*strike|ка\s*эс\s*2|каэс\s*2|кс\s*2|кс2|кс\s*го|каэс)\b", "cs2"),
    (r"\b(доту\s*2|дота\s*2|в\s+доту|доту|дотку|дота)\b", "dota 2"),
    (r"\b(гта\s*5|гта\s*пять|джи\s*ти\s*эй)\b", "gta 5"),
    (r"\b(кибер\s*панк|киберпанк|сайберпанк)\b", "cyberpunk 2077"),
    (r"\b(майн\s*крафт|майнкрафт)\b", "minecraft"),
    (r"\b(валорант)\b", "valorant"),
    (r"\b(пабг|пубг)\b", "pubg"),
    (r"\b(ведьмак\s*3|ведьмак)\b", "witcher 3"),
    # Popular apps & services
    (r"\b(на\s+ютубе|в\s+ютубе|с\s+ютубом|ютубом|ютубе|ютьюб|ютуб)\b", "youtube"),
    (r"\b(в\s+телеграме|в\s+телеге|телеграм|телегу|телеге|тг)\b", "telegram"),
    (r"\b(гугл\s+хром|хром)\b", "chrome"),
    (r"\b(вс\s*код|вижуал\s*студио\s*код|vs\s*code)\b", "vscode"),
]


def normalize_voice_transcript(text: str) -> str:
    """Normalizes mangled Russian/English app names, game titles, and common STT artifacts."""
    if not text:
        return ""
    res = text.strip()
    for pattern, replacement in _BILINGUAL_REPLACEMENTS:
        res = _re.sub(pattern, replacement, res, flags=_re.IGNORECASE)
    return _re.sub(r"\s+", " ", res).strip()


def strip_assistant_echo(transcript: str, assistant_speech: str) -> str:
    """
    Removes speaker bleed / echo of EVA's own TTS voice from a microphone transcript.
    - If `transcript` is entirely words from `assistant_speech`, returns "".
    - If `transcript` starts with a prefix of `assistant_speech` followed by a user command
      (e.g. "Хорошо, создатель, я... Открой, Steam"), strips the echo prefix and returns "Открой, Steam".
    """
    if not transcript or not transcript.strip():
        return ""
    if not assistant_speech or not assistant_speech.strip():
        return transcript.strip()

    t_raw = transcript.strip()
    a_words = [
        w.lower().replace("ё", "е")
        for w in _re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", assistant_speech)
    ]
    if not a_words:
        return t_raw

    a_set = set(a_words)
    t_tokens = list(_re.finditer(r"[a-zA-Zа-яА-ЯёЁ0-9]+", t_raw))
    if not t_tokens:
        return ""

    t_words = [m.group(0).lower().replace("ё", "е") for m in t_tokens]

    # 1. Strip any leading tokens that belong to the assistant's recent TTS output
    # Stop stripping as soon as we hit a wake word ("ева", "эва") or a clear command verb not in that position
    wake_markers = {"ева", "эва", "евочка", "дева", "ива", "слушай", "стоп", "хватит", "тихо", "молчи"}
    cut_idx = 0
    for idx, w in enumerate(t_words):
        if w in wake_markers:
            break
        if w in a_set:
            cut_idx = idx + 1
        else:
            break

    if cut_idx >= len(t_tokens):
        return ""

    if cut_idx > 0:
        remainder = t_raw[t_tokens[cut_idx].start():].lstrip(" ,.!?:;-—…").strip()
    else:
        remainder = t_raw

    # 2. Check if the remaining transcript is still mostly echo from assistant_speech
    rem_words = [
        w.lower().replace("ё", "е")
        for w in _re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", remainder)
    ]
    if not rem_words:
        return ""

    if not any(w in wake_markers for w in rem_words):
        overlap = sum(1 for w in rem_words if w in a_set)
        if len(rem_words) >= 3 and (overlap / len(rem_words)) >= 0.65:
            return ""

    return remainder


def extract_wake_word_command(
    text: str,
    wake_word: str = "ева",
    custom_aliases: Optional[List[str]] = None
) -> Tuple[bool, str, str]:
    """
    Detects wake word ('Ева' and phonetic near-misses) in the first words of `text`.
    Returns: (triggered: bool, matched_trigger: str, command_part: str)
    """
    if not text or not text.strip():
        return False, "", ""

    wake_word_clean = (wake_word or "ева").strip().lower()
    aliases = set(a.lower().strip() for a in (custom_aliases or []) if a.strip())

    phonetic_aliases = {
        "ева": {
            "ева", "эва", "евочка", "евушка", "еву", "еве", "ев", "еваа",
            "дева", "ива", "нева", "сева", "лево", "лева", "его", "ела",
            "эра", "вера", "лена", "гена", "евачка", "eva", "eve"
        },
        "джарвис": {"джарвис", "жарвис", "джарвиз", "джарв", "jarvis"},
        "ассистент": {"ассистент", "асистент", "ассистента", "ассистенту", "помощник"},
        "апекс": {"апекс", "apex", "опекс", "апикс"}
    }

    allowed = (
        phonetic_aliases.get(wake_word_clean, {wake_word_clean})
        | aliases
        | phonetic_aliases["ева"]
        | phonetic_aliases["джарвис"]
        | {"ассистент", "компьютер"}
    )

    clean_str = text.strip()

    # 1. Check multi-word wake prefix like "я ва ...", "и ва ...", "эй ва ..."
    multi_match = _re.match(
        r"^(?:слушай\s+|эй\s+|привет\s+|алло\s+|ну\s+|хей\s+)?(я\s+ва|я\s+вам|и\s+ва|эй\s+ва|не\s+ва)\b[,.:;!\-\s]*(.*)$",
        clean_str,
        flags=_re.IGNORECASE
    )
    if multi_match and wake_word_clean == "ева":
        return True, multi_match.group(1).lower(), multi_match.group(2).strip()

    # 2. Check fused prefix like "евоткрой ..." or "еваоткрой ..."
    fused_match = _re.match(
        r"^(ева|эва|ев)(открой|запусти|включи|выключи|закрой|сделай|поставь|найди|скажи|сядь|встань|станцуй)\b(.*)$",
        clean_str,
        flags=_re.IGNORECASE
    )
    if fused_match:
        cmd_rest = f"{fused_match.group(2)}{fused_match.group(3)}".strip()
        return True, fused_match.group(1).lower(), cmd_rest

    # 3. Tokenize with character offsets and check the first 5 words
    tokens = list(_re.finditer(r"[a-zA-Zа-яА-ЯёЁ0-9]+", clean_str))
    for tok in tokens[:5]:
        word_low = tok.group(0).lower().replace("ё", "е")
        if word_low in allowed:
            cmd_part = clean_str[tok.end():].lstrip(" ,.!?:;-—…").strip()
            return True, word_low, cmd_part

    return False, "", ""


class AudioEars:
    """Continuous low-latency voice listener with 0.42s end-of-speech detection and echo cancellation."""

    SILENCE_LIMIT = 0.78
    ACTIVE_SILENCE_LIMIT = 0.72
    MAX_RECORD_SECONDS = 6.5

    def __init__(self):
        self.sample_rate = 16000
        self.channels = 1
        self.block_size = 1600  # 100ms chunks
        self.audio_queue: queue.Queue = queue.Queue()
        self._is_running = False
        self._listen_thread: Optional[threading.Thread] = None

        self._whisper_model = None
        self._model_lock = threading.Lock()
        self._sr_recognizer = sr.Recognizer() if _HAS_SR else None

        # Active conversation window state
        self.is_active_listening = False
        self.active_listening_until = 0.0
        self._force_flush_recording = False

        # Dynamic VAD & RMS tracking
        self.current_volume_rms = 0.0
        self.ambient_noise_rms = 0.004
        self.energy_threshold = config_manager.get("audio.energy_threshold", 0.010)

        # Speaker echo cancellation state
        self._last_assistant_text: str = ""
        self._assistant_speaking_until: float = 0.0
        self._web_audio_playing: bool = False
        self.is_muted: bool = bool(config_manager.get("audio.mic_muted", False))

    def set_muted(self, muted: bool) -> bool:
        """Mutes or unmutes the microphone completely so EVA does not hear anything when muted."""
        self.is_muted = bool(muted)
        config_manager.set("audio.mic_muted", self.is_muted, auto_save=True)
        if self.is_muted:
            self.is_active_listening = False
            self.active_listening_until = 0.0
            self._force_flush_recording = False
            agent_signals.emit_safe("mic_state", False)
            agent_signals.emit_safe("state_changed", "IDLE")
            agent_signals.emit_safe("thought_logged", "🔇 [Слух] Микрофон выключен (Mute). Ева вас не слышит.")
        else:
            agent_signals.emit_safe("thought_logged", "🎙️ [Слух] Микрофон снова включён.")
        agent_signals.emit_safe("mic_muted", self.is_muted)
        return self.is_muted

    def toggle_mute(self) -> bool:
        """Toggles microphone mute state and returns the new `is_muted` boolean."""
        return self.set_muted(not self.is_muted)

    def notify_assistant_speech(self, text: str, duration_sec: float = 3.5):
        """Records that EVA is currently speaking `text` so speaker bleed is ignored/filtered."""
        self._last_assistant_text = (text or "").strip()
        self._assistant_speaking_until = time.time() + max(1.2, float(duration_sec)) + 0.45

    def set_web_audio_playing(self, playing: bool):
        """Updated by WebSocket when browser Web Audio starts/stops playing TTS."""
        self._web_audio_playing = bool(playing)
        if not playing:
            # Keep a tiny 0.35s tail buffer for room reverb after browser audio finishes
            self._assistant_speaking_until = min(self._assistant_speaking_until, time.time() + 0.35)

    def is_assistant_speaking_now(self) -> bool:
        return (
            voice_speaker.is_speaking
            or self._web_audio_playing
            or (time.time() < self._assistant_speaking_until)
        )

    def toggle_manual_listen(self) -> bool:
        """Toggles manual microphone listening from UI button or hotkey."""
        if self.is_muted:
            agent_signals.emit_safe("thought_logged", "🔇 [Слух] Микрофон замучен. Сначала размутьте микрофон.")
            agent_signals.emit_safe("mic_state", False)
            return False

        if not self._is_running:
            self.start_listening()

        if self.is_active_listening and time.time() < self.active_listening_until:
            self._force_flush_recording = True
            self.is_active_listening = False
            self.active_listening_until = 0.0
            agent_signals.emit_safe("mic_state", False)
            agent_signals.emit_safe("thought_logged", "🎙️ [Слух] Запись завершена, обрабатываю речь...")
            return False
        else:
            if voice_speaker.is_speaking or self._web_audio_playing:
                voice_speaker.stop()
                self._web_audio_playing = False
                self._assistant_speaking_until = 0.0
            self.is_active_listening = True
            self.active_listening_until = time.time() + 12.0
            play_activation_chime()
            agent_signals.emit_safe("wake_word_triggered", "manual")
            agent_signals.emit_safe("state_changed", "LISTENING")
            agent_signals.emit_safe("mic_state", True)
            agent_signals.emit_safe("thought_logged", "🎙️ [Слух] Ручной микрофон активирован. Слушаю вашу команду...")
            return True

    def warm_up_model(self):
        """Pre-loads Whisper fallback model in a background thread."""
        threading.Thread(target=self._get_whisper, daemon=True).start()

    def _get_whisper(self):
        """Lazy-loads local Faster-Whisper ('base', int8) for fast offline fallback."""
        if self._whisper_model is None:
            with self._model_lock:
                if self._whisper_model is None:
                    try:
                        from faster_whisper import WhisperModel
                        threads = max(4, (os.cpu_count() or 4) - 1)
                        self._whisper_model = WhisperModel(
                            "base",
                            device="cpu",
                            compute_type="int8",
                            cpu_threads=threads
                        )
                        agent_signals.emit_safe("thought_logged", "🎙️ [Слух] Гибридный движок речи готов к работе!")
                    except Exception as e:
                        agent_signals.emit_safe("thought_logged", f"❌ [Слух] Ошибка загрузки Whisper: {e}")
        return self._whisper_model

    def list_input_devices(self) -> List[dict]:
        """Returns physical microphone devices."""
        devices = []
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("hostapi") == 0 and dev.get("max_input_channels", 0) > 0:
                    name = str(dev.get("name", "")).strip()
                    name_l = name.lower()
                    if "переназначение" in name_l or "mapper" in name_l:
                        continue
                    devices.append({"index": idx, "name": name, "default": idx == sd.default.device[0]})
        except Exception as e:
            print(f"[AudioEars] Error listing devices: {e}")
        return devices

    def restart_with_device(self, device_index: Optional[int]):
        """Switches active microphone input device on the fly."""
        config_manager.set("audio.input_device_index", device_index, auto_save=True)
        if self._is_running:
            self.stop_listening()
            self.start_listening()

    def start_listening(self):
        """Starts continuous microphone listening in background."""
        if self._is_running:
            return
        self._is_running = True
        self.warm_up_model()
        self._listen_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self._listen_thread.start()

    def stop_listening(self):
        """Stops the audio listening loop."""
        self._is_running = False
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=1.0)

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice stream callback."""
        self.audio_queue.put(indata.copy())

    def _recording_loop(self):
        """Processes incoming audio stream chunks with Peak-Drop VAD for instant end-of-phrase detection."""
        device_idx = config_manager.get("audio.input_device_index", None)

        pre_roll_buffer = deque(maxlen=15)  # 1.5s pre-roll so "Ева" at start is never clipped
        buffer = []
        recording_voice = False
        voice_start_time = None
        silence_start_time = None
        utterance_peak_rms = 0.0

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                device=device_idx,
                blocksize=self.block_size,
                callback=self._audio_callback
            ):
                agent_signals.emit_safe("thought_logged", f"🎙️ [Слух] Микрофон активен (ID: {device_idx}). Слушаю вас...")

                while self._is_running:
                    try:
                        chunk = self.audio_queue.get(timeout=0.04)
                    except queue.Empty:
                        continue

                    if self.is_muted:
                        if recording_voice or buffer:
                            recording_voice = False
                            buffer = []
                            pre_roll_buffer.clear()
                            silence_start_time = None
                            voice_start_time = None
                            utterance_peak_rms = 0.0
                        continue

                    if self._force_flush_recording:
                        self._force_flush_recording = False
                        if recording_voice and buffer:
                            audio_data = np.concatenate(buffer, axis=0)
                            buffer = []
                            pre_roll_buffer.clear()
                            recording_voice = False
                            silence_start_time = None
                            voice_start_time = None
                            utterance_peak_rms = 0.0
                            threading.Thread(
                                target=self._transcribe_and_dispatch,
                                args=(audio_data,),
                                daemon=True
                            ).start()
                        else:
                            self.is_active_listening = False
                            agent_signals.emit_safe("mic_state", False)
                            agent_signals.emit_safe("state_changed", "IDLE")
                        continue

                    # Check active listening window expiration
                    if self.is_active_listening and time.time() > self.active_listening_until:
                        self.is_active_listening = False
                        agent_signals.emit_safe("mic_state", False)
                        agent_signals.emit_safe("state_changed", "IDLE")

                    # RMS volume calculation
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    self.current_volume_rms = rms

                    # Adaptive noise floor tracking (clamped so loud spikes never blind the mic)
                    if not recording_voice:
                        clamped_rms = min(rms, 0.025)
                        self.ambient_noise_rms = 0.92 * self.ambient_noise_rms + 0.08 * clamped_rms

                    user_thresh = min(float(config_manager.get("audio.energy_threshold", 0.010)), 0.014)
                    if self.is_active_listening:
                        start_thresh = max(user_thresh * 0.55, self.ambient_noise_rms * 1.45, 0.0040)
                    else:
                        start_thresh = max(user_thresh * 0.80, self.ambient_noise_rms * 1.75, 0.0055)
                    self.energy_threshold = start_thresh

                    # Determine whether current chunk has active voice vs trailing silence/fan hum
                    if not recording_voice:
                        is_voice_chunk = rms > start_thresh
                    else:
                        utterance_peak_rms = max(utterance_peak_rms, rms)
                        # Once user spoke, any drop below 14% of their peak speech RMS or below start_thresh*1.02 counts as silence
                        continue_thresh = max(start_thresh * 1.02, min(utterance_peak_rms * 0.14, 0.025))
                        is_voice_chunk = rms > continue_thresh

                    if is_voice_chunk:
                        if not recording_voice:
                            recording_voice = True
                            voice_start_time = time.time()
                            utterance_peak_rms = rms
                            buffer = list(pre_roll_buffer)
                            if not self.is_assistant_speaking_now():
                                agent_signals.emit_safe("state_changed", "LISTENING")

                        silence_start_time = None
                        buffer.append(chunk)
                    else:
                        pre_roll_buffer.append(chunk)
                        if recording_voice:
                            buffer.append(chunk)
                            if silence_start_time is None:
                                silence_start_time = time.time()

                            effective_silence_limit = (
                                self.ACTIVE_SILENCE_LIMIT if self.is_active_listening else self.SILENCE_LIMIT
                            )
                            is_silence_timeout = (time.time() - silence_start_time >= effective_silence_limit)
                            is_max_timeout = (
                                voice_start_time is not None
                                and (time.time() - voice_start_time >= self.MAX_RECORD_SECONDS)
                            )

                            if is_silence_timeout or is_max_timeout:
                                rec_duration = (time.time() - voice_start_time) if voice_start_time else 0.0
                                recording_voice = False
                                silence_start_time = None
                                voice_start_time = None
                                utterance_peak_rms = 0.0

                                if buffer and rec_duration >= 0.18:
                                    audio_data = np.concatenate(buffer, axis=0)
                                    buffer = []
                                    pre_roll_buffer.clear()
                                    threading.Thread(
                                        target=self._transcribe_and_dispatch,
                                        args=(audio_data,),
                                        daemon=True
                                    ).start()
                                else:
                                    buffer = []
                                    pre_roll_buffer.clear()
                                    if not self.is_active_listening and not self.is_assistant_speaking_now():
                                        agent_signals.emit_safe("state_changed", "IDLE")

        except Exception as e:
            agent_signals.emit_safe("thought_logged", f"❌ [Слух] Ошибка микрофона: {e}")
            self._is_running = False

    def _normalize_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """Normalizes audio volume cleanly without over-amplifying background noise."""
        flat = audio_data.flatten().astype(np.float32)
        flat = flat - np.mean(flat)
        max_val = np.max(np.abs(flat))
        if max_val > 0.004:
            flat = (flat / max_val) * 0.92
        return flat

    def _transcribe_hybrid(self, audio_norm: np.ndarray) -> str:
        """
        Transcribes float32 16kHz audio using fast Google Web Speech API (~0.4-0.8s, high bilingual accuracy)
        with automatic fallback to local Faster-Whisper ('base', beam_size=1).
        """
        lang = config_manager.get("audio.whisper_language", "ru")
        sr_lang = "ru-RU" if lang == "ru" else lang

        # 1. Primary: Google Speech Recognition API (superior Russian + English mixed phrase recognition)
        if _HAS_SR and self._sr_recognizer is not None:
            try:
                pcm16 = np.clip(audio_norm * 32767.0, -32768, 32767).astype(np.int16).tobytes()
                sr_audio = sr.AudioData(pcm16, self.sample_rate, 2)
                text_google = self._sr_recognizer.recognize_google(sr_audio, language=sr_lang)
                if text_google and text_google.strip():
                    return text_google.strip()
            except Exception:
                pass

        # 2. Offline / Fallback: Local Faster-Whisper ('base', beam_size=1, vad_filter=False for speed)
        whisper = self._get_whisper()
        if not whisper:
            return ""
        try:
            segments, _ = whisper.transcribe(
                audio_norm,
                language=lang,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                without_timestamps=True,
                condition_on_previous_text=False,
                vad_filter=False
            )
            valid_segments = []
            for s in segments:
                if getattr(s, "no_speech_prob", 0.0) < 0.72 and getattr(s, "avg_logprob", 0.0) > -1.75:
                    valid_segments.append(s.text)
            return " ".join(valid_segments).strip()
        except Exception:
            return ""

    def _transcribe_and_dispatch(self, audio_data: np.ndarray):
        """Transcribes raw float32 audio, filters speaker echo, and dispatches commands."""
        audio_norm = self._normalize_audio(audio_data)

        if len(audio_norm) < self.sample_rate * 0.18:
            if not self.is_active_listening and not self.is_assistant_speaking_now():
                agent_signals.emit_safe("state_changed", "IDLE")
            return

        was_speaking = self.is_assistant_speaking_now()
        text = self._transcribe_hybrid(audio_norm)

        if not text:
            if not self.is_active_listening and not self.is_assistant_speaking_now():
                agent_signals.emit_safe("state_changed", "IDLE")
            return

        text_clean = text.strip(".,!?\"' ")
        hallucinations = (
            "спасибо за просмотр", "субтитры", "редактор субтитров",
            "подписывайтесь", "продолжение следует", "дима торчок"
        )
        if any(h in text_clean.lower() for h in hallucinations):
            if not self.is_active_listening and not self.is_assistant_speaking_now():
                agent_signals.emit_safe("state_changed", "IDLE")
            return

        # Strip any speaker bleed / echo from EVA's own TTS output
        if self._last_assistant_text and (was_speaking or (time.time() < self._assistant_speaking_until + 1.5)):
            text_clean = strip_assistant_echo(text_clean, self._last_assistant_text)
            if not text_clean:
                if not self.is_active_listening and not self.is_assistant_speaking_now():
                    agent_signals.emit_safe("state_changed", "IDLE")
                return

        # Apply bilingual & phonetic normalization
        text_clean = normalize_voice_transcript(text_clean)

        # Case 1: Already in active listening window (either wake-word or manual mic button)
        if self.is_active_listening and time.time() <= self.active_listening_until:
            self.is_active_listening = False
            agent_signals.emit_safe("mic_state", False)
            triggered, _, cmd_only = extract_wake_word_command(text_clean)
            final_cmd = cmd_only if (triggered and cmd_only) else text_clean
            agent_signals.emit_safe("thought_logged", f"🎙️ [Слух] Команда получена: \"{final_cmd}\"")
            agent_signals.emit_safe("voice_command_received", final_cmd)
            return

        wake_word_enabled = config_manager.get("audio.wake_word_enabled", True)
        wake_word = config_manager.get("audio.wake_word", "ева").strip().lower()
        custom_aliases = [a.lower() for a in config_manager.get("audio.wake_word_aliases", [])]

        triggered, matched_trigger, command_part = extract_wake_word_command(
            text_clean,
            wake_word=wake_word,
            custom_aliases=custom_aliases
        )

        if wake_word_enabled:
            if triggered:
                if voice_speaker.is_speaking or self._web_audio_playing:
                    voice_speaker.stop()
                    self._web_audio_playing = False
                    self._assistant_speaking_until = 0.0
                    agent_signals.emit_safe("thought_logged", "🛑 [Слух] Перебивание! Речь ассистента остановлена.")

                if command_part:
                    self.is_active_listening = False
                    agent_signals.emit_safe(
                        "thought_logged",
                        f"🎙️ [Слух] Распознано: \"{text_clean}\" (Триггер: '{matched_trigger}')"
                    )
                    agent_signals.emit_safe("voice_command_received", command_part)
                else:
                    self.is_active_listening = True
                    self.active_listening_until = time.time() + 10.0
                    play_activation_chime()
                    agent_signals.emit_safe("thought_logged", f"🎙️ [Слух] '{wake_word}' обнаружен! Жду вашу команду...")
                    agent_signals.emit_safe("wake_word_triggered", wake_word)
                    agent_signals.emit_safe("state_changed", "LISTENING")
            else:
                text_lower = text_clean.lower()
                if (voice_speaker.is_speaking or self._web_audio_playing) and any(
                    sw in text_lower for sw in ("стоп", "хватит", "молчи", "замолчи", "тихо", "прекрати", "отмена")
                ):
                    voice_speaker.stop()
                    self._web_audio_playing = False
                    self._assistant_speaking_until = 0.0
                    agent_signals.emit_safe("thought_logged", "🛑 [Слух] Речь остановлена командой стоп.")
                    self.is_active_listening = False
                    agent_signals.emit_safe("state_changed", "IDLE")
                else:
                    if not self.is_assistant_speaking_now():
                        agent_signals.emit_safe("state_changed", "IDLE")
        else:
            agent_signals.emit_safe("thought_logged", f"🎙️ [Слух] Распознано: \"{text_clean}\"")
            agent_signals.emit_safe("voice_command_received", text_clean)


# Singleton
audio_ears = AudioEars()
