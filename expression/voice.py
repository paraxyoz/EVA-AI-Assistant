"""
Voice ("Speech") Flagship Neural Module for EVA AI Assistant.
Supports:
1. ElevenLabs API (Custom Cloned Voices, Free Premade Voices & 10,000+ Voice Library) with smart proxy routing.
2. Distinct Neural Voices via Edge-TTS (Ava, Seraphina, Emma, Andrew, Brian, Svetlana, Dmitry) - 0 limits, instant response.
3. Gemini Native Neural Audio & Google Wavenet fallback.
4. In-Memory Pygame Audio Streaming & Web Audio API Lip-Sync delivery.
"""

import os
import io
import time
import socket
import asyncio
import urllib.parse
import hashlib
import threading
import httpx
import pygame
from collections import OrderedDict
from typing import Optional, Dict
from config import config_manager
from core.events import agent_signals


class VoiceSpeaker:
    """Handles customizable neural text-to-speech with multiple voice profiles & ElevenLabs cloning."""

    MAX_MEMORY_CACHE_ITEMS = 64

    VOICE_PROFILES = {
        "elevenlabs": "👑 ElevenLabs — Премиум / Клонированный голос",
        "jarvis": "🤖 J.A.R.V.I.S. — Интеллектуальный дворецкий (Баритон, сэр)",
        "aoede": "🌟 Aoede — Мягкий живой женский (Ava Neural)",
        "puck": "⚡ Puck — Яркий энергичный женский (Seraphina Neural)",
        "kore": "🌸 Kore — Нежный тёплый женский (Emma Neural)",
        "fenrir": "🐺 Fenrir — Глубокий мужской (Andrew Neural)",
        "charon": "🦾 Charon — Бархатный мужской (Brian Neural)",
        "google_female": "🌐 Светлана — Чёткий русский женский (Svetlana Neural)",
        "google_male": "🌐 Дмитрий — Чёткий русский мужской (Dmitry Neural)"
    }

    # Distinct Edge-TTS neural voice mapping for each non-ElevenLabs profile (natural 0Hz pitch for crisp audio)
    EDGE_VOICE_MAP = {
        "jarvis": ("ru-RU-DmitryNeural", "+8%", "-4Hz"),
        "aoede": ("en-US-AvaMultilingualNeural", "+4%", "+0Hz"),
        "puck": ("de-DE-SeraphinaMultilingualNeural", "+5%", "+0Hz"),
        "kore": ("en-US-EmmaMultilingualNeural", "+2%", "+0Hz"),
        "fenrir": ("en-US-AndrewMultilingualNeural", "+3%", "+0Hz"),
        "charon": ("en-US-BrianMultilingualNeural", "+2%", "+0Hz"),
        "google_female": ("ru-RU-SvetlanaNeural", "+5%", "+0Hz"),
        "google_male": ("ru-RU-DmitryNeural", "+5%", "+0Hz"),
    }

    def __init__(self):
        self._is_speaking = False
        self._stop_requested = False
        self._lock = threading.Lock()

        # Bounded LRU Memory Cache for instant playback without RAM leaks
        self._memory_cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "voice_cache"))
        os.makedirs(self._cache_dir, exist_ok=True)

        # Persistent HTTP clients (direct + proxy) to eliminate TLS handshake latency
        self._http_client = httpx.Client(timeout=10.0)
        self._proxy_clients: Dict[str, httpx.Client] = {}
        self._cached_proxy: Optional[str] = None
        self._proxy_checked_at: float = 0.0
        self._exhausted_elevenlabs_keys: set[str] = set()

        # Initialize pygame mixer at studio 44.1 kHz
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        except Exception as e:
            print(f"[VoiceSpeaker] Pygame mixer init: {e}")

    def _get_client(self, proxy_url: Optional[str]) -> httpx.Client:
        if not proxy_url:
            return self._http_client
        if proxy_url not in self._proxy_clients:
            self._proxy_clients[proxy_url] = httpx.Client(proxy=proxy_url, timeout=12.0)
        return self._proxy_clients[proxy_url]

    @property
    def is_speaking(self) -> bool:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            return True
        return self._is_speaking

    def _get_active_eleven_voice_id(self) -> str:
        vid = (
            config_manager.get("audio.elevenlabs_voice_id", "")
            or config_manager.get("audio.elevenlabs.voice_id", "cgSgspJ2msm6clMCkdW9")
        ).strip()
        if not vid or vid in ("21m00Tcm4TlvDq8ikWAM", "bA58y3FqVI6b6gTNh0oT"):
            vid = "cgSgspJ2msm6clMCkdW9"
        return vid

    def get_voice_eq(self) -> dict:
        """Returns current Voice Equalizer settings (pitch, speed, bass, treble, volume)."""
        eq = config_manager.get("audio.eq", {})
        if not isinstance(eq, dict):
            eq = {}
        vol = int(round(float(eq.get("volume", 100))))
        vol = max(0, min(150, vol))
        return {
            "pitch": int(round(float(eq.get("pitch", 0)))),
            "speed": round(float(eq.get("speed", 1.0)), 2),
            "bass": int(round(float(eq.get("bass", 0)))),
            "treble": int(round(float(eq.get("treble", 0)))),
            "volume": vol,
        }

    def get_effective_prosody(self, base_rate: str = "+5%", base_pitch: str = "+0Hz") -> tuple[str, str]:
        """Combines base profile prosody with user's Voice Equalizer pitch & speed sliders."""
        import re as _re
        eq = self.get_voice_eq()

        base_r_m = _re.search(r"([+-]?\d+)", str(base_rate or "+0%"))
        base_r_val = int(base_r_m.group(1)) if base_r_m else 0
        speed_delta = int(round((eq["speed"] - 1.0) * 100))
        final_rate = max(-50, min(80, base_r_val + speed_delta))
        rate_str = f"{'+' if final_rate >= 0 else ''}{final_rate}%"

        base_p_m = _re.search(r"([+-]?\d+)", str(base_pitch or "+0Hz"))
        base_p_val = int(base_p_m.group(1)) if base_p_m else 0
        pitch_delta_hz = int(round(eq["pitch"] * 3))
        final_pitch = max(-50, min(50, base_p_val + pitch_delta_hz))
        pitch_str = f"{'+' if final_pitch >= 0 else ''}{final_pitch}Hz"

        return rate_str, pitch_str

    def _get_cache_key(self, text: str, voice_id: str) -> str:
        clean = text.strip().lower()
        eq = self.get_voice_eq()
        eq_sig = f"p{eq['pitch']}_s{eq['speed']}"
        if voice_id == "elevenlabs":
            el_vid = self._get_active_eleven_voice_id()
            return hashlib.md5(f"v5_hq_elevenlabs_{el_vid}_{eq_sig}:{clean}".encode("utf-8")).hexdigest()
        edge_info = self.EDGE_VOICE_MAP.get(voice_id, (voice_id, "", ""))
        return hashlib.md5(f"v5_hq_{voice_id}_{edge_info[0]}_{eq_sig}:{clean}".encode("utf-8")).hexdigest()

    def _put_memory_cache(self, key: str, data: bytes):
        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)
        self._memory_cache[key] = data
        while len(self._memory_cache) > self.MAX_MEMORY_CACHE_ITEMS:
            self._memory_cache.popitem(last=False)

    def _load_cached_audio(self, text: str, voice_id: str) -> Optional[bytes]:
        key = self._get_cache_key(text, voice_id)
        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)
            return self._memory_cache[key]

        disk_path = os.path.join(self._cache_dir, f"{key}.mp3")
        if os.path.exists(disk_path):
            try:
                with open(disk_path, "rb") as f:
                    data = f.read()
                if len(data) > 500:
                    self._put_memory_cache(key, data)
                    return data
            except Exception:
                pass
        return None

    def _save_cached_audio(self, text: str, voice_id: str, audio_bytes: bytes):
        if not audio_bytes or len(audio_bytes) < 500:
            return
        key = self._get_cache_key(text, voice_id)
        self._put_memory_cache(key, audio_bytes)
        disk_path = os.path.join(self._cache_dir, f"{key}.mp3")
        try:
            with open(disk_path, "wb") as f:
                f.write(audio_bytes)
        except Exception:
            pass

    def stop(self):
        """Immediately interrupts any ongoing speech."""
        self._stop_requested = True
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception:
            pass
        self._is_speaking = False
        agent_signals.emit_safe("speech_stopped")

    def get_effective_voice_profile(self, requested_profile: Optional[str] = None) -> str:
        """
        Returns 'jarvis' (calm, authoritative male baritone) automatically whenever J.A.R.V.I.S. mode is active,
        otherwise returns the requested or configured voice profile.
        """
        ai_mode = str(config_manager.get("ai_mode", "conversational")).strip().lower()
        if ai_mode in ("jarvis", "passive"):
            return "jarvis"
        return requested_profile or config_manager.get("audio.voice_profile", "aoede")

    def speak(self, text: str, blocking: bool = False):
        """Speaks the given text using the currently configured voice (or J.A.R.V.I.S. baritone in jarvis mode)."""
        if not text or not text.strip():
            return

        voice_id = self.get_effective_voice_profile()
        if blocking:
            self._speak_direct(text, voice_id)
        else:
            threading.Thread(target=self._speak_direct, args=(text, voice_id), daemon=True).start()

    def _mark_elevenlabs_exhausted(self, api_key: str):
        if api_key:
            self._exhausted_elevenlabs_keys.add(api_key.strip())

    def _is_elevenlabs_exhausted(self, api_key: str) -> bool:
        if not api_key:
            return True
        return api_key.strip() in self._exhausted_elevenlabs_keys

    def _synthesize_audio(self, text: str, voice_id: Optional[str] = None, bypass_cache: bool = False) -> Optional[bytes]:
        """Synthesizes speech into raw MP3 bytes for Web Audio API Lip-Sync."""
        if not text or not text.strip():
            return None

        if not bypass_cache and str(config_manager.get("ai_mode", "conversational")).strip().lower() in ("jarvis", "passive"):
            voice_id = "jarvis"
        elif not voice_id:
            voice_id = self.get_effective_voice_profile()

        clean_text = text.replace("*", "").replace("#", "").replace("`", "").replace("[", "").replace("]", "").strip()
        if not clean_text:
            return None

        # 1. Check RAM / Disk cache
        if not bypass_cache:
            cached = self._load_cached_audio(clean_text, voice_id)
            if cached is not None:
                return cached

        # 2. Synthesize based on selected voice profile
        audio_bytes = None

        if voice_id == "elevenlabs":
            audio_bytes = self._fetch_elevenlabs_audio(clean_text)
            if audio_bytes is None:
                # Instant fallback to Ava Multilingual if ElevenLabs key is missing or out of quota
                audio_bytes = self._fetch_edge_neural(clean_text, "aoede")
        else:
            audio_bytes = self._fetch_edge_neural(clean_text, voice_id)

        # 3. Last-resort fallback to Google Wavenet if Edge-TTS failed
        if audio_bytes is None:
            audio_bytes = self._fetch_google_neural(clean_text, voice_id)

        # Always cache synthesized audio so subsequent calls play in <1ms
        if audio_bytes is not None:
            self._save_cached_audio(clean_text, voice_id, audio_bytes)

        return audio_bytes

    def play_audio_bytes_async(self, audio_bytes: bytes, text: str = ""):
        """Plays pre-synthesized MP3/WAV bytes asynchronously via native Pygame mixer (never blocked by WebEngine)."""
        if not audio_bytes:
            return
        threading.Thread(
            target=self._play_bytes_direct,
            args=(audio_bytes, text),
            daemon=True,
        ).start()

    def _play_bytes_direct(self, audio_bytes: bytes, text: str = ""):
        # Signal any currently running playback loop to abort BEFORE waiting for self._lock
        self.stop()
        with self._lock:
            self._stop_requested = False
            self._is_speaking = True
            agent_signals.emit_safe("speech_started")
            try:
                if text:
                    try:
                        from perception.ears import audio_ears
                        est_sec = max(1.5, len(audio_bytes) / 14000.0)
                        audio_ears.notify_assistant_speech(text, duration_sec=est_sec)
                    except Exception:
                        pass
                self._play_mp3_bytes(audio_bytes)
            finally:
                self._is_speaking = False
                agent_signals.emit_safe("speech_stopped")

    def update_live_volume(self, volume: int):
        """Updates active Pygame playback volume immediately when the user drags the volume slider."""
        try:
            if pygame.mixer.get_init():
                vol_ratio = min(1.0, max(0.0, float(volume) / 100.0))
                pygame.mixer.music.set_volume(vol_ratio)
        except Exception:
            pass

    def _speak_direct(self, text: str, voice_id: str):
        """Generates neural speech for the given voice profile and plays locally."""
        audio_bytes = self._synthesize_audio(text, voice_id)
        if audio_bytes is not None:
            self._play_bytes_direct(audio_bytes, text=text)

    def _get_local_proxy(self) -> Optional[str]:
        """Detects active local VPN/Xray/Clash/Nekoray HTTP proxy on 127.0.0.1 if running (cached for 30s)."""
        now = time.time()
        if now - self._proxy_checked_at < 30.0:
            return self._cached_proxy

        self._proxy_checked_at = now
        for port in (10809, 2080, 7890, 10808, 2081, 1080, 8888, 12334):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                    self._cached_proxy = f"http://127.0.0.1:{port}"
                    return self._cached_proxy
            except Exception:
                pass
        self._cached_proxy = None
        return None

    def _fetch_edge_neural(self, text: str, voice_id: str) -> Optional[bytes]:
        """Fetches distinct high-quality neural audio via Microsoft Edge Neural TTS with Equalizer pitch/speed."""
        import edge_tts

        edge_voice, base_rate, base_pitch = self.EDGE_VOICE_MAP.get(
            voice_id,
            ("ru-RU-SvetlanaNeural", "+8%", "+0Hz")
        )
        if voice_id == "jarvis":
            rate, pitch = "+8%", "-4Hz"
        else:
            rate, pitch = self.get_effective_prosody(base_rate, base_pitch)

        async def _run_edge() -> bytes:
            communicate = edge_tts.Communicate(text, edge_voice, rate=rate, pitch=pitch)
            out = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    out.write(chunk["data"])
            return out.getvalue()

        try:
            loop = asyncio.new_event_loop()
            try:
                audio_data = loop.run_until_complete(_run_edge())
            finally:
                loop.close()
            if audio_data and len(audio_data) > 500:
                return audio_data
        except Exception as e:
            print(f"[VoiceSpeaker] Edge Neural TTS error ({edge_voice}): {e}")
        return None

    def _fetch_elevenlabs_audio(self, text: str) -> Optional[bytes]:
        """Fetches studio-quality 44.1kHz 128kbps voice from ElevenLabs API (skips in 0ms if quota exhausted or geo-blocked)."""
        api_key = (
            config_manager.get("audio.elevenlabs_api_key", "")
            or config_manager.get("audio.elevenlabs.api_key", "")
        ).strip()
        voice_id = self._get_active_eleven_voice_id()
        proxy = self._get_local_proxy()
        route_key = f"{api_key}:{proxy or 'direct'}"

        if not api_key or self._is_elevenlabs_exhausted(route_key):
            return None

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": config_manager.get("audio.elevenlabs.stability", 0.55),
                "similarity_boost": config_manager.get("audio.elevenlabs.similarity_boost", 0.82),
                "style": 0.12,
                "use_speaker_boost": True
            }
        }

        def _do_post(vid: str, proxy_url: Optional[str] = None):
            target_url = (
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
                f"?optimize_streaming_latency=2&output_format=mp3_44100_128"
            )
            client = self._get_client(proxy_url)
            return client.post(target_url, json=payload, headers=headers)

        try:
            res = _do_post(voice_id, proxy)
            if res.status_code == 200 and len(res.content) > 500:
                return res.content

            if res.status_code in (301, 302, 401, 403) or "quota_exceeded" in res.text:
                print(f"[VoiceSpeaker] ElevenLabs unavailable ({res.status_code}) — auto-switching to fast Edge Neural TTS.")
                self._mark_elevenlabs_exhausted(route_key)
                return None

            if res.status_code == 402:
                fallback_vid = "cgSgspJ2msm6clMCkdW9"
                config_manager.set("audio.elevenlabs_voice_id", fallback_vid, auto_save=True)
                config_manager.set("audio.elevenlabs.voice_id", fallback_vid, auto_save=True)
                res_fb = _do_post(fallback_vid, proxy)
                if res_fb.status_code == 200 and len(res_fb.content) > 500:
                    return res_fb.content
                self._mark_elevenlabs_exhausted(route_key)

            print(f"[VoiceSpeaker] ElevenLabs error {res.status_code}: {res.text[:160]}")
        except Exception as e:
            print(f"[VoiceSpeaker] ElevenLabs request error: {e}")
        return None

    def _fetch_google_neural(self, text: str, voice_id: str) -> Optional[bytes]:
        """Last-resort fallback to Google Translate TTS."""
        clean = text.replace("\n", " ").strip()[:200]
        encoded = urllib.parse.quote(clean)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=ru&client=tw-ob&q={encoded}"

        try:
            res = self._http_client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200 and len(res.content) > 100:
                return res.content
        except Exception as e:
            print(f"[VoiceSpeaker] Google Neural fetch error: {e}")
        return None

    def list_output_devices(self) -> list[dict]:
        """Returns physical Windows output devices (headphones, speakers, monitors) for the UI selector."""
        devices = []
        try:
            import sounddevice as sd
            for idx, d in enumerate(sd.query_devices()):
                if d.get("hostapi") == 0 and d.get("max_output_channels", 0) >= 2:
                    name = str(d.get("name", "")).strip()
                    name_l = name.lower()
                    if "переназначение" in name_l or "mapper" in name_l:
                        continue
                    devices.append({
                        "index": idx,
                        "name": name,
                        "default": idx == sd.default.device[1]
                    })
        except Exception as e:
            print(f"[VoiceSpeaker] Error listing output devices: {e}")
        return devices

    def _get_target_output_indices(self) -> list[int]:
        """Determines which PortAudio MME output device indices to stream to."""
        all_devs = self.list_output_devices()
        if not all_devs:
            return []

        selected = str(config_manager.get("audio.output_device", "auto") or "auto").strip()
        if selected != "auto":
            # Match by index or substring name
            for d in all_devs:
                if str(d["index"]) == selected or selected.lower() in d["name"].lower():
                    return [d["index"]]

        # In 'auto' mode, stream simultaneously to all active headphones & speakers so user ALWAYS hears EVA
        return [d["index"] for d in all_devs]

    def play_wav_chime_multi_device(self, wav_bytes: bytes):
        """Plays short WAV activation chime across all active headphones/speakers."""
        if not wav_bytes:
            return
        try:
            import numpy as np
            import sounddevice as sd
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            snd = pygame.mixer.Sound(io.BytesIO(wav_bytes))
            pcm = np.frombuffer(snd.get_raw(), dtype=np.int16).reshape(-1, 2)
            indices = self._get_target_output_indices()
            streams = []
            for idx in indices:
                try:
                    st = sd.OutputStream(device=idx, samplerate=44100, channels=2, dtype="int16", blocksize=2048)
                    st.start()
                    streams.append(st)
                except Exception:
                    pass
            if streams:
                try:
                    for pos in range(0, len(pcm), 2048):
                        blk = pcm[pos : pos + 2048]
                        for st in streams:
                            try:
                                st.write(blk)
                            except Exception:
                                pass
                finally:
                    for st in streams:
                        try:
                            st.stop()
                            st.close()
                        except Exception:
                            pass
        except Exception:
            pass

    def _play_mp3_bytes(self, audio_bytes: bytes):
        """
        Decodes MP3/WAV into 44.1kHz stereo PCM and streams simultaneously to active headphones & speakers
        (e.g. GAMING HEADSET B2 + Speakers) with live volume control.
        """
        if not audio_bytes or self._stop_requested:
            return

        try:
            import numpy as np
            import sounddevice as sd

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)

            snd = pygame.mixer.Sound(io.BytesIO(audio_bytes))
            raw_bytes = snd.get_raw()
            pcm = np.frombuffer(raw_bytes, dtype=np.int16).reshape(-1, 2)

            indices = self._get_target_output_indices()
            streams = []
            for idx in indices:
                try:
                    st = sd.OutputStream(device=idx, samplerate=44100, channels=2, dtype="int16", blocksize=2048)
                    st.start()
                    streams.append(st)
                except Exception:
                    pass

            if streams:
                chunk_size = 2048
                try:
                    for pos in range(0, len(pcm), chunk_size):
                        if self._stop_requested:
                            break
                        vol_ratio = max(0.0, min(1.5, self.get_voice_eq().get("volume", 100) / 100.0))
                        block = pcm[pos : pos + chunk_size]
                        if abs(vol_ratio - 1.0) > 0.01:
                            scaled = np.clip(block.astype(np.float32) * vol_ratio, -32768, 32767).astype(np.int16)
                        else:
                            scaled = block
                        for st in streams:
                            try:
                                st.write(scaled)
                            except Exception:
                                pass
                finally:
                    for st in streams:
                        try:
                            st.stop()
                            st.close()
                        except Exception:
                            pass
                return

            # Fallback to single-device pygame.mixer.music if no PortAudio streams opened
            bio = io.BytesIO(audio_bytes)
            pygame.mixer.music.load(bio)
            vol_ratio = min(1.0, max(0.0, self.get_voice_eq().get("volume", 100) / 100.0))
            pygame.mixer.music.set_volume(vol_ratio)
            pygame.mixer.music.play()

            start_time = time.time()
            while pygame.mixer.music.get_busy() and (time.time() - start_time < 45):
                if self._stop_requested:
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.03)

        except Exception as e:
            print(f"[VoiceSpeaker] Playback error: {e}")
        finally:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
            except Exception:
                pass


# Singleton
voice_speaker = VoiceSpeaker()
