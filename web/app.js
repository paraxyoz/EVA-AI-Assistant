/**
 * AIRI Main Frontend Controller
 * Connects 3D VRM Engine, Audio Lip-Sync, Web Speech STT, and WebSocket Backend.
 */

import { VRMViewer } from './vrm_viewer.js?v=2.5';
import { AudioSyncEngine } from './audio_sync.js';

class AIRIApp {
    constructor() {
        this.vrmViewer = null;
        this.audioSync = null;
        this.ws = null;
        this.isRecording = false;
        this.recognition = null;
        this.activeModel = 'alicia.vrm';
        this.providersConfig = {};

        this._initDOM();
        this._init3D();
        this._initSTT();
        this._initWebSocket();
        this._initEvents();
    }

    _initDOM() {
        this.canvasContainer = document.getElementById('canvas-container');
        this.visualizerCanvas = document.getElementById('visualizer-canvas');
        this.chatStream = document.getElementById('chat-stream');
        this.statusText = document.getElementById('agent-status-text');
        this.micBtn = document.getElementById('btn-mic-toggle');
        this.textInput = document.getElementById('user-input-text');
        this.sendBtn = document.getElementById('btn-send-text');
        this.settingsDrawer = document.getElementById('settings-drawer');
        this.selectLLMProvider = document.getElementById('select-llm-provider');
        this.llmBaseInput = document.getElementById('cfg-llm-base');
        this.llmKeyInput = document.getElementById('cfg-llm-key');
        this.llmModelInput = document.getElementById('cfg-llm-model');
        this.llmModelsDatalist = document.getElementById('llm-models-datalist');
        this.llmTestStatus = document.getElementById('llm-test-status');
        this.selectModel = document.getElementById('select-vrm-model');
        this.selectVoice = document.getElementById('select-voice-profile');
        this.elevenKeyInput = document.getElementById('cfg-eleven-key');
        this.elevenVoiceInput = document.getElementById('cfg-eleven-voice-id');
        this.dropZone = document.getElementById('vrm-drop-zone');
        this.fileInput = document.getElementById('vrm-file-input');
    }

    _populateLLMFields(provName) {
        const defaults = {
            eva_free: { api_base: 'https://text.pollinations.ai/openai', api_key: 'not-needed', model: 'openai' },
            gemini: { api_base: 'https://generativelanguage.googleapis.com/v1beta/openai', api_key: '', model: 'gemini-2.5-flash' },
            lm_studio: { api_base: 'http://localhost:1234/v1', api_key: 'not-needed', model: 'qwen2.5-7b-instruct' },
            ollama: { api_base: 'http://localhost:11434/v1', api_key: 'ollama', model: 'qwen2.5:latest' },
            openrouter: { api_base: 'https://openrouter.ai/api/v1', api_key: '', model: 'google/gemini-2.0-flash-001' },
            groq: { api_base: 'https://api.groq.com/openai/v1', api_key: '', model: 'llama-3.3-70b-versatile' },
            openai: { api_base: 'https://api.openai.com/v1', api_key: '', model: 'gpt-4o' },
            custom: { api_base: 'http://localhost:8000/v1', api_key: '', model: 'default' }
        };
        const cfg = (this.providersConfig && this.providersConfig[provName]) || defaults[provName] || defaults.custom;
        if (this.llmBaseInput) this.llmBaseInput.value = cfg.api_base || (defaults[provName] && defaults[provName].api_base) || '';
        let keyVal = cfg.api_key || '';
        if (keyVal.startsWith('AQ.')) keyVal = '';
        if (this.llmKeyInput) this.llmKeyInput.value = keyVal;
        if (this.llmModelInput) this.llmModelInput.value = cfg.model || (defaults[provName] && defaults[provName].model) || '';
    }

    _init3D() {
        try {
            this.vrmViewer = new VRMViewer(this.canvasContainer);
            this.audioSync = new AudioSyncEngine(this.vrmViewer, this.visualizerCanvas);

            const modelUrl = `/models/${this.activeModel}`;
            this.vrmViewer.loadModel(modelUrl).catch((err) => {
                console.warn('Could not load primary model, trying fallback...', err);
                this.vrmViewer.loadModel('/models/sample_vrm1.vrm').catch(console.error);
            });
        } catch (e) {
            console.error('3D Initialization Error:', e);
        }
    }

    _initSTT() {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRec) {
            this.recognition = new SpeechRec();
            this.recognition.lang = 'ru-RU';
            this.recognition.continuous = false;
            this.recognition.interimResults = true;

            this.recognition.onstart = () => {
                // Stop assistant speech if speaking (Barge-In)
                if (this.audioSync && this.audioSync.isPlaying) {
                    this.audioSync.stop();
                }
                this.isRecording = true;
                this.micBtn.classList.add('active');
                this.statusText.textContent = 'СЛУШАЮ ВАС...';
                if (this.vrmViewer) this.vrmViewer.setEmotion('surprised');
            };

            this.recognition.onresult = (event) => {
                let interimTranscript = '';
                let finalTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                if (interimTranscript) {
                    this.textInput.value = interimTranscript;
                }
                if (finalTranscript) {
                    this.textInput.value = finalTranscript;
                    this.sendMessage(finalTranscript);
                }
            };

            this.recognition.onerror = (event) => {
                console.warn('Speech recognition notice:', event.error);
                this.isRecording = false;
                this.micBtn.classList.remove('active');
                this.statusText.textContent = 'ONLINE';
                if (this.vrmViewer) this.vrmViewer.setEmotion('neutral');
            };

            this.recognition.onend = () => {
                this.isRecording = false;
                this.micBtn.classList.remove('active');
                if (this.statusText.textContent === 'СЛУШАЮ ВАС...') {
                    this.statusText.textContent = 'ONLINE';
                }
            };
        }
    }

    _initWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('⚡ WebSocket Connected to EVA AI Server');
            this.statusText.textContent = 'ONLINE';
        };

        this.ws.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this._handleServerEvent(data);
            } catch (err) {
                console.error('WS parse error:', err);
            }
        };

        this.ws.onclose = () => {
            this.statusText.textContent = 'RECONNECTING...';
            setTimeout(() => this._initWebSocket(), 2000);
        };
    }

    _handleServerEvent(data) {
        const type = data.type;

        if (type === 'init') {
            if (data.providers) {
                this.providersConfig = data.providers;
            }
            if (data.llm_provider && this.selectLLMProvider) {
                this.selectLLMProvider.value = data.llm_provider;
                this._populateLLMFields(data.llm_provider);
            }

            if (data.models && data.models.length > 0) {
                this.selectModel.innerHTML = '';
                data.models.forEach((m) => {
                    const opt = document.createElement('option');
                    opt.value = m.filename;
                    opt.textContent = `${m.name} (${m.size_mb} MB)`;
                    this.selectModel.appendChild(opt);
                });
                if (data.active_model) {
                    this.selectModel.value = data.active_model;
                    if (data.active_model !== this.activeModel && this.vrmViewer) {
                        this.activeModel = data.active_model;
                        this.vrmViewer.loadModel(`/models/${data.active_model}`).catch(console.error);
                    }
                }
            }

            if (data.voice_profile) {
                this.selectVoice.value = data.voice_profile;
            }
            if (data.elevenlabs_key !== undefined && this.elevenKeyInput) {
                this.elevenKeyInput.value = data.elevenlabs_key;
            }
            if (data.elevenlabs_voice_id !== undefined && this.elevenVoiceInput) {
                let vid = data.elevenlabs_voice_id;
                if (!vid || vid === '21m00Tcm4TlvDq8ikWAM' || vid === 'bA58y3FqVI6b6gTNh0oT') {
                    vid = 'cgSgspJ2msm6clMCkdW9';
                }
                this.elevenVoiceInput.value = vid;
                const elPreset = document.getElementById('select-eleven-preset');
                if (elPreset) {
                    const hasOpt = Array.from(elPreset.options).some(o => o.value === vid);
                    elPreset.value = hasOpt ? vid : 'custom';
                }
            }

            if (data.system_info) {
                document.getElementById('tele-cpu').textContent = data.system_info.processor || 'CPU';
                document.getElementById('tele-gpu').textContent = data.system_info.gpu || 'GPU';
                document.getElementById('tele-ram').textContent = data.system_info.ram || 'RAM';
            }
        } else if (type === 'thought') {
            this._renderThoughtBubble(data.content);
        } else if (type === 'state') {
            this.statusText.textContent = data.state;
            if (data.state === 'THINKING' && this.vrmViewer) {
                this.vrmViewer.setEmotion('relaxed');
            }
        } else if (type === 'wake_word') {
            if (this.audioSync && this.audioSync.isPlaying) {
                this.audioSync.stop();
            }
            this.statusText.textContent = 'СЛУШАЮ...';
            if (this.vrmViewer) this.vrmViewer.setEmotion('surprised');
        } else if (type === 'user_message') {
            this._activeStreamBubble = null;
            this._renderUserBubble(data.text);
        } else if (type === 'response_chunk') {
            this._updateStreamingAssistantBubble(data.text);
        } else if (type === 'response') {
            this._renderAssistantBubble(data.text);
            if (this.vrmViewer) this.vrmViewer.setEmotion('happy');
        } else if (type === 'audio_playback') {
            if (data.audio_base64 && this.audioSync) {
                this.statusText.textContent = 'ГОВОРИТ';
                this.audioSync.playAudioBase64(data.audio_base64, () => {
                    this.statusText.textContent = 'ONLINE';
                    if (this.vrmViewer) this.vrmViewer.setEmotion('neutral');
                });
            }
        } else if (type === 'speech_stopped') {
            if (this.audioSync) this.audioSync.stop();
            this.statusText.textContent = 'ONLINE';
        } else if (type === 'model_changed') {
            if (this.vrmViewer && data.model_name) {
                this.activeModel = data.model_name;
                this.vrmViewer.loadModel(`/models/${data.model_name}`);
            }
        } else if (type === 'avatar_action') {
            if (this.vrmViewer) {
                if (data.outfit) this.vrmViewer.setOutfit(data.outfit);
                if (data.pose) this.vrmViewer.setPose(data.pose);
                if (data.emotion) this.vrmViewer.setEmotion(data.emotion);
            }
        }
    }

    sendMessage(text) {
        if (!text || !text.trim()) return;
        const clean = text.trim();
        this.textInput.value = '';

        // Stop any current speech
        if (this.audioSync && this.audioSync.isPlaying) {
            this.audioSync.stop();
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'user_message', text: clean }));
        }
    }

    _renderUserBubble(text) {
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble bubble-user';
        bubble.innerHTML = `
            <div class="bubble-sender">ВЫ</div>
            <div>${this._escapeHTML(text)}</div>
        `;
        this.chatStream.appendChild(bubble);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    _updateStreamingAssistantBubble(text) {
        if (!this._activeStreamBubble) {
            const bubble = document.createElement('div');
            bubble.className = 'chat-bubble bubble-assistant';
            bubble.innerHTML = `
                <div class="bubble-sender">EVA AI</div>
                <div class="bubble-text"></div>
            `;
            this.chatStream.appendChild(bubble);
            this._activeStreamBubble = bubble;
        }
        const textEl = this._activeStreamBubble.querySelector('.bubble-text');
        if (textEl) {
            textEl.innerHTML = this._escapeHTML(text);
        }
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    _renderAssistantBubble(text) {
        if (this._activeStreamBubble) {
            const textEl = this._activeStreamBubble.querySelector('.bubble-text');
            if (textEl) {
                textEl.innerHTML = this._escapeHTML(text);
            }
            this._activeStreamBubble = null;
            this.chatStream.scrollTop = this.chatStream.scrollHeight;
            return;
        }
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble bubble-assistant';
        bubble.innerHTML = `
            <div class="bubble-sender">EVA AI</div>
            <div class="bubble-text">${this._escapeHTML(text)}</div>
        `;
        this.chatStream.appendChild(bubble);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    _renderThoughtBubble(msg) {
        if (msg.includes('[Инструмент]') || msg.includes('[Результат]')) {
            const badge = document.createElement('div');
            badge.className = 'tool-badge';
            badge.textContent = msg;
            this.chatStream.appendChild(badge);
            this.chatStream.scrollTop = this.chatStream.scrollHeight;
        }
    }

    _escapeHTML(str) {
        return str.replace(/[&<>'"]/g, 
            tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
        );
    }

    _initEvents() {
        this.sendBtn.addEventListener('click', () => this.sendMessage(this.textInput.value));
        this.textInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.sendMessage(this.textInput.value);
        });

        this.micBtn.addEventListener('click', () => {
            if (!this.recognition) {
                alert('Голосовой ввод браузера поддерживается в Chrome / Edge.');
                return;
            }
            if (this.isRecording) {
                this.recognition.stop();
            } else {
                try {
                    this.recognition.start();
                } catch (e) {
                    console.warn(e);
                }
            }
        });

        document.querySelectorAll('.chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const cmd = chip.getAttribute('data-cmd');
                this.sendMessage(cmd);
            });
        });

        // Camera Presets
        document.getElementById('btn-camera-portrait')?.addEventListener('click', () => this.vrmViewer?.setCameraPreset('portrait'));
        document.getElementById('btn-camera-bust')?.addEventListener('click', () => this.vrmViewer?.setCameraPreset('bust'));
        document.getElementById('btn-camera-full')?.addEventListener('click', () => this.vrmViewer?.setCameraPreset('full'));
        document.querySelectorAll('.cam-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const p = btn.getAttribute('data-cam');
                this.vrmViewer?.setCameraPreset(p);
            });
        });

        // Direct 3D Pose & Outfit Controls
        document.querySelectorAll('[data-pose]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const pose = btn.getAttribute('data-pose');
                if (pose && this.vrmViewer) this.vrmViewer.setPose(pose);
            });
        });
        document.querySelectorAll('[data-outfit]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const outfit = btn.getAttribute('data-outfit');
                if (outfit && this.vrmViewer) this.vrmViewer.setOutfit(outfit);
            });
        });

        // Settings Drawer Toggle
        document.getElementById('btn-open-settings')?.addEventListener('click', () => this.settingsDrawer.classList.add('open'));
        document.getElementById('btn-close-settings')?.addEventListener('click', () => this.settingsDrawer.classList.remove('open'));

        // LLM Provider Switcher
        this.selectLLMProvider?.addEventListener('change', (e) => {
            const newProv = e.target.value;
            this._populateLLMFields(newProv);
            if (this.llmTestStatus) this.llmTestStatus.style.display = 'none';
        });

        // Show / Hide API Key Button
        document.getElementById('btn-toggle-key-vis')?.addEventListener('click', () => {
            if (!this.llmKeyInput) return;
            this.llmKeyInput.type = this.llmKeyInput.type === 'password' ? 'text' : 'password';
        });

        // Test LLM Connection & Discover Local Models Button
        document.getElementById('btn-test-llm')?.addEventListener('click', async () => {
            const prov = this.selectLLMProvider?.value || 'eva_free';
            const apiBase = this.llmBaseInput?.value.trim() || '';
            const apiKey = this.llmKeyInput?.value.trim() || '';
            const model = this.llmModelInput?.value.trim() || '';

            if (this.llmTestStatus) {
                this.llmTestStatus.style.display = 'block';
                this.llmTestStatus.style.color = 'var(--neon-cyan)';
                this.llmTestStatus.textContent = '⏳ Проверка соединения и поиск моделей...';
            }

            try {
                const res = await fetch('/api/llm/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: prov, api_base: apiBase, api_key: apiKey, model: model })
                });
                const text = await res.text();
                let json = {};
                try {
                    json = JSON.parse(text);
                } catch (_) {
                    throw new Error(`HTTP ${res.status}: ${text.slice(0, 100)}`);
                }

                if (json.success) {
                    if (!this.providersConfig[prov]) this.providersConfig[prov] = {};
                    if (apiBase) this.providersConfig[prov].api_base = apiBase;
                    if (apiKey) this.providersConfig[prov].api_key = apiKey;
                    if (model) this.providersConfig[prov].model = model;

                    if (this.llmTestStatus) {
                        this.llmTestStatus.style.color = '#4ade80';
                        this.llmTestStatus.textContent = `✅ ${json.message}`;
                    }
                    if (json.models && json.models.length > 0 && this.llmModelsDatalist) {
                        this.llmModelsDatalist.innerHTML = '';
                        json.models.forEach((mId) => {
                            const opt = document.createElement('option');
                            opt.value = mId;
                            this.llmModelsDatalist.appendChild(opt);
                        });
                        if (this.llmModelInput && (!this.llmModelInput.value || this.llmModelInput.value === 'default')) {
                            this.llmModelInput.value = json.models[0];
                        }
                    }
                } else {
                    if (this.llmTestStatus) {
                        this.llmTestStatus.style.color = '#ff5252';
                        this.llmTestStatus.textContent = `❌ ${json.error || 'Ошибка подключения'}`;
                    }
                }
            } catch (err) {
                if (this.llmTestStatus) {
                    this.llmTestStatus.style.color = '#ff5252';
                    this.llmTestStatus.textContent = `❌ Ошибка соединения: ${err.message}`;
                }
            }
        });

        // Helper to trigger voice synthesis preview
        const playVoicePreview = async (profile, elevenVoiceId, elevenKey) => {
            const btn = document.getElementById('btn-test-voice-btn');
            const origText = '🔊 Тест выбранного голоса';
            if (btn) btn.textContent = '⏳ Синтез голоса...';
            try {
                const formData = new FormData();
                formData.append('profile', profile);
                formData.append('eleven_voice_id', elevenVoiceId || '');
                formData.append('eleven_key', elevenKey || '');
                const res = await fetch('/api/voice/test', { method: 'POST', body: formData });
                const json = await res.json();
                if (json.audio_base64 && this.audioSync) {
                    if (btn) btn.textContent = '🔊 Звучит!';
                    this.audioSync.playAudioBase64(json.audio_base64, () => {
                        if (btn) btn.textContent = origText;
                    });
                } else {
                    if (btn) btn.textContent = '❌ Ошибка озвучки';
                    setTimeout(() => { if (btn) btn.textContent = origText; }, 2000);
                }
            } catch (err) {
                console.error('Voice test failed:', err);
                if (btn) btn.textContent = origText;
            }
        };

        // Save Settings Button
        document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
            const btn = document.getElementById('btn-save-settings');
            const prov = this.selectLLMProvider?.value || 'eva_free';
            const apiBase = this.llmBaseInput?.value.trim() || '';
            const apiKey = this.llmKeyInput?.value.trim() || '';
            const modelName = this.llmModelInput?.value.trim() || 'default';

            if (!this.providersConfig[prov]) this.providersConfig[prov] = {};
            this.providersConfig[prov].api_base = apiBase;
            this.providersConfig[prov].api_key = apiKey;
            this.providersConfig[prov].model = modelName;

            const elPreset = document.getElementById('select-eleven-preset');
            let elevenVid = this.elevenVoiceInput?.value.trim() || '';
            if (!elevenVid && elPreset && elPreset.value !== 'custom') {
                elevenVid = elPreset.value;
            }
            if (!elevenVid) elevenVid = 'cgSgspJ2msm6clMCkdW9';

            const voiceProfile = this.selectVoice?.value || 'aoede';
            const elevenKey = this.elevenKeyInput?.value.trim() || '';

            const payload = {
                'llm_provider': prov,
                [`providers.${prov}.api_base`]: apiBase,
                [`providers.${prov}.api_key`]: apiKey,
                [`providers.${prov}.model`]: modelName,
                [`providers.${prov}.vision_model`]: modelName,
                'audio.voice_profile': voiceProfile,
                'audio.elevenlabs.api_key': elevenKey,
                'audio.elevenlabs.voice_id': elevenVid,
                'audio.elevenlabs_api_key': elevenKey,
                'audio.elevenlabs_voice_id': elevenVid,
                'vrm.active_model': this.selectModel?.value || 'AvatarSample_B.vrm'
            };

            if (btn) btn.textContent = '⏳ Сохранение...';
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const json = await res.json();
                if (json.success) {
                    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send(JSON.stringify({ type: 'set_voice', voice_profile: voiceProfile }));
                    }
                    if (btn) {
                        btn.textContent = '✅ СОХРАНЕНО!';
                        setTimeout(() => { btn.textContent = '💾 Сохранить настройки'; }, 2500);
                    }
                    // Immediately play a short preview of the saved voice so the user hears the change
                    playVoicePreview(voiceProfile, elevenVid, elevenKey);
                } else {
                    if (btn) {
                        btn.textContent = `❌ Ошибка: ${json.error || 'не сохранено'}`;
                        setTimeout(() => { btn.textContent = '💾 Сохранить настройки'; }, 3000);
                    }
                }
            } catch (e) {
                console.error('Save config error:', e);
                if (btn) {
                    btn.textContent = '❌ Ошибка сохранения';
                    setTimeout(() => { btn.textContent = '💾 Сохранить настройки'; }, 3000);
                }
            }
        });

        // Transparent Overlay Mode Toggle & Exit
        document.getElementById('btn-toggle-overlay')?.addEventListener('click', () => {
            document.body.classList.toggle('overlay-mode');
        });
        document.getElementById('btn-exit-overlay')?.addEventListener('click', () => {
            document.body.classList.remove('overlay-mode');
        });
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && document.body.classList.contains('overlay-mode')) {
                document.body.classList.remove('overlay-mode');
            }
        });

        // Model Switcher
        this.selectModel.addEventListener('change', (e) => {
            const m = e.target.value;
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'set_model', model_name: m }));
            }
        });

        // Voice Switcher
        this.selectVoice.addEventListener('change', async (e) => {
            const v = e.target.value;
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'set_voice', voice_profile: v }));
            }
            try {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 'audio.voice_profile': v })
                });
            } catch (_) {}
        });

        // ElevenLabs Free Preset Selector
        const elPreset = document.getElementById('select-eleven-preset');
        elPreset?.addEventListener('change', (e) => {
            if (e.target.value !== 'custom' && this.elevenVoiceInput) {
                this.elevenVoiceInput.value = e.target.value;
                if (this.selectVoice && this.elevenKeyInput?.value.trim()) {
                    this.selectVoice.value = 'elevenlabs';
                }
            }
        });

        // ElevenLabs Voice Catalog Link
        document.getElementById('btn-open-eleven-catalog')?.addEventListener('click', () => {
            window.open('https://elevenlabs.io/voice-library', '_blank');
        });

        // Test Voice Button
        document.getElementById('btn-test-voice-btn')?.addEventListener('click', async () => {
            const prof = this.selectVoice?.value || 'aoede';
            const vid = this.elevenVoiceInput?.value.trim() || 'cgSgspJ2msm6clMCkdW9';
            const eKey = this.elevenKeyInput?.value.trim() || '';
            await playVoicePreview(prof, vid, eKey);
        });

        // Drag and Drop .vrm Model Uploader
        this.dropZone.addEventListener('click', () => this.fileInput.click());
        this.fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) this._uploadVRM(e.target.files[0]);
        });

        ['dragenter', 'dragover'].forEach((name) => {
            window.addEventListener(name, (e) => {
                e.preventDefault();
                this.dropZone.classList.add('dragover');
            });
        });

        ['dragleave', 'drop'].forEach((name) => {
            window.addEventListener(name, (e) => {
                e.preventDefault();
                this.dropZone.classList.remove('dragover');
            });
        });

        window.addEventListener('drop', (e) => {
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                if (file.name.toLowerCase().endsWith('.vrm')) {
                    this._uploadVRM(file);
                }
            }
        });
    }

    async _uploadVRM(file) {
        const formData = new FormData();
        formData.append('file', file);
        this.statusText.textContent = 'ЗАГРУЗКА VRM...';

        try {
            const res = await fetch('/api/models/upload', { method: 'POST', body: formData });
            const json = await res.json();
            if (json.success) {
                this.statusText.textContent = 'ONLINE';
                this.vrmViewer.loadModel(json.url);
                const opt = document.createElement('option');
                opt.value = json.filename;
                opt.textContent = `${json.filename} (${json.size_mb} MB)`;
                opt.selected = true;
                this.selectModel.appendChild(opt);
            }
        } catch (err) {
            console.error('Failed to upload VRM:', err);
            this.statusText.textContent = 'ONLINE';
        }
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.airiApp = new AIRIApp();
});
