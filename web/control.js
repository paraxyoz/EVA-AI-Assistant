/**
 * EVA AI — Spatial Desktop Studio Control Center (v5.0)
 * Handles:
 * - Automatic & manual session history reset with Empty State Hero
 * - Two AI Personality Modes ('conversational' vs 'passive' executive mode)
 * - 1-Click 3D/Live2D Avatar Visibility Toggle (runs audio fallback when avatar window is hidden)
 * - No-Code Custom Commands Builder + Spotify/Steam/Discord automation triggers
 * - Real-time Voice Equalizer (Pitch, Speed, Bass, Treble + Timbre Presets)
 * - Visual 3D VRM & 2D Live2D Model Gallery + 1-click folder/file import
 */

class EVAControlCenter {
    constructor() {
        this.ws = null;
        this.providersConfig = {};
        this.ollamaModels = [];
        this.availableModels = [];
        this.activeModel = 'sample_vrm1.vrm';
        this.avatarVisible = true;
        this.isMicMuted = false;
        this.aiMode = 'conversational';
        this.customCommands = [];
        this.commandFolders = [];
        this.activeTreeScope = 'pc';
        this.savedMacros = [];
        this.isMacroRecording = false;
        this._macroTimerInterval = null;
        this._macroStartSec = 0;
        this._activeConfirmId = null;
        this._confirmTimerInterval = null;
        this.voiceEq = { pitch: 0, speed: 1.0, bass: 0, treble: 0, volume: 100 };
        this._activeStreamBubble = null;
        this.isRecording = false;
        this._fallbackAudio = null;
        this._wsReconnectTimer = null;
        this._syncInterval = null;

        this._initDOM();
        this._initWebSocket();
        this._initEvents();
        this._startHeartbeatAndSync();
        this.refreshCommandTree();
        this.refreshMacros();
        this.refreshAudioDevices();
    }

    async refreshAudioDevices() {
        try {
            const res = await fetch('/api/audio/devices');
            const data = await res.json();
            if (data.success) {
                this._populateAudioDevices(
                    data.output_devices || [],
                    data.input_devices || [],
                    data.output_device ?? 'auto',
                    data.input_device_index ?? -1
                );
            }
        } catch (_) {}
    }

    _initDOM() {
        this.chatStream = document.getElementById('chat-stream');
        this.emptyHero = document.getElementById('empty-state-hero');
        this.statusText = document.getElementById('agent-status-text');
        this.statusPillBox = document.getElementById('status-pill-box');

        this.micBtn = document.getElementById('btn-mic-toggle');
        this.micMuteBtn = document.getElementById('btn-mic-mute');
        this.svgMicOn = document.getElementById('svg-mic-on');
        this.svgMicOff = document.getElementById('svg-mic-off');
        this.textInput = document.getElementById('user-input-text');
        this.sendBtn = document.getElementById('btn-send-text');
        this.stopSpeechBtn = document.getElementById('btn-stop-speech');
        this.clearHistoryBtn = document.getElementById('btn-clear-history');

        this.sidebarLLMLabel = document.getElementById('sidebar-llm-label');
        this.sidebarAvatarLabel = document.getElementById('sidebar-avatar-label');

        this.toggleAvatarVisBtn = document.getElementById('btn-toggle-avatar-vis');
        this.avatarVisLabel = document.getElementById('avatar-vis-label');
        this.selectAiMode = document.getElementById('select-ai-mode');

        // Commands Tree & Modal DOM
        this.commandsTreeBody = document.getElementById('commands-tree-body');
        this.cmdTreeSearch = document.getElementById('cmd-tree-search');
        this.newCmdModal = document.getElementById('new-cmd-modal');
        this.modalCmdTrigger = document.getElementById('modal-cmd-trigger');
        this.modalCmdFolder = document.getElementById('modal-cmd-folder');
        this.modalCmdScope = document.getElementById('modal-cmd-scope');
        this.modalCmdResponse = document.getElementById('modal-cmd-response');
        this.modalStepsContainer = document.getElementById('modal-steps-container');
        this.modalConfirmChk = document.getElementById('modal-cmd-confirm-chk');
        this.modalConfirmTimeout = document.getElementById('modal-cmd-timeout');
        this.expandedFolderIds = new Set();
        this.editingCmdId = null;

        // Confirmation Popup DOM
        this.confirmModal = document.getElementById('cmd-confirm-modal');
        this.confirmModalTitle = document.getElementById('confirm-modal-title');
        this.confirmModalSteps = document.getElementById('confirm-modal-steps');
        this.confirmModalCountdown = document.getElementById('confirm-modal-countdown-text');
        this.confirmModalBar = document.getElementById('confirm-modal-bar');

        // Macro Recorder DOM
        this.macroRecIndicator = document.getElementById('macro-rec-indicator');
        this.macroRecStatusText = document.getElementById('macro-rec-status-text');
        this.macroRecTimer = document.getElementById('macro-rec-timer');
        this.macroRecBtn = document.getElementById('btn-toggle-macro-record');

        // Legacy Custom Commands DOM
        this.cmdTriggerInput = document.getElementById('cmd-trigger-input');
        this.cmdActionType = document.getElementById('cmd-action-type');
        this.cmdTargetInput = document.getElementById('cmd-target-input');
        this.cmdResponseInput = document.getElementById('cmd-response-input');
        this.customCommandsList = document.getElementById('custom-commands-list');

        // LLM Settings DOM
        this.selectLLMProvider = document.getElementById('select-llm-provider');
        this.selectLLMModel = document.getElementById('select-llm-model');
        this.llmBaseInput = document.getElementById('cfg-llm-base');
        this.llmKeyInput = document.getElementById('cfg-llm-key');
        this.llmTestStatus = document.getElementById('llm-test-status');

        // Avatar Studio DOM
        this.selectVrmModel = document.getElementById('select-vrm-model');
        this.modelGalleryGrid = document.getElementById('model-gallery-grid');
        this.vrmFileInput = document.getElementById('vrm-file-input');
        this.live2dFolderInput = document.getElementById('live2d-folder-input');
        this.live2dUploadStatus = document.getElementById('live2d-upload-status');

        // Voice & Equalizer DOM
        this.selectOutputDevice = document.getElementById('select-output-device');
        this.selectInputDevice = document.getElementById('select-input-device');
        this.selectVoice = document.getElementById('select-voice-profile');
        this.elevenKeyInput = document.getElementById('cfg-eleven-key');
        this.elevenPreset = document.getElementById('select-eleven-preset');
        this.elevenVoiceInput = document.getElementById('cfg-eleven-voice-id');

        this.headerEvaVolume = document.getElementById('header-eva-volume');
        this.headerEvaVolumeVal = document.getElementById('header-eva-volume-val');
        this.eqVolume = document.getElementById('eq-volume');
        this.eqVolumeVal = document.getElementById('eq-volume-val');
        this.eqPitch = document.getElementById('eq-pitch');
        this.eqSpeed = document.getElementById('eq-speed');
        this.eqBass = document.getElementById('eq-bass');
        this.eqTreble = document.getElementById('eq-treble');
        this.eqPitchVal = document.getElementById('eq-pitch-val');
        this.eqSpeedVal = document.getElementById('eq-speed-val');
        this.eqBassVal = document.getElementById('eq-bass-val');
        this.eqTrebleVal = document.getElementById('eq-treble-val');

        this.toastContainer = document.getElementById('toast-container');
    }

    showToast(message) {
        if (!this.toastContainer) return;
        const item = document.createElement('div');
        item.className = 'toast-item';
        item.textContent = message;
        this.toastContainer.appendChild(item);
        setTimeout(() => {
            item.style.opacity = '0';
            item.style.transition = 'opacity 0.25s ease';
            setTimeout(() => item.remove(), 260);
        }, 2800);
    }

    switchTab(targetId) {
        if (!targetId) return;
        document.querySelectorAll('.nav-btn[data-tab], .rail-nav-btn[data-tab]').forEach((b) => {
            b.classList.toggle('active', b.getAttribute('data-tab') === targetId);
        });
        document.querySelectorAll('.tab-page').forEach((page) => {
            page.classList.toggle('active', page.id === targetId);
        });
        if (targetId === 'tab-commands') {
            this.refreshCommandTree();
        }
    }

    _updateMicMuteUI(muted) {
        this.isMicMuted = Boolean(muted);
        if (this.micMuteBtn) {
            this.micMuteBtn.classList.toggle('muted-red', this.isMicMuted);
            this.micMuteBtn.setAttribute('data-tooltip', this.isMicMuted ? 'Микрофон ЗАМУЧЕН (нажмите, чтобы включить)' : 'Замутить микрофон (Ева не слушает)');
        }
        if (this.svgMicOn) this.svgMicOn.style.display = this.isMicMuted ? 'none' : 'block';
        if (this.svgMicOff) this.svgMicOff.style.display = this.isMicMuted ? 'block' : 'none';
    }

    _updateAvatarVisUI(visible) {
        this.avatarVisible = Boolean(visible);
        if (this.avatarVisLabel) {
            this.avatarVisLabel.textContent = this.avatarVisible ? 'Аватар: ВКЛЮЧЁН' : 'Аватар: ВЫКЛЮЧЕН';
        }
        if (this.toggleAvatarVisBtn) {
            this.toggleAvatarVisBtn.classList.toggle('emerald', this.avatarVisible);
            this.toggleAvatarVisBtn.classList.toggle('active-green', this.avatarVisible);
        }
    }

    async refreshCommandTree() {
        try {
            const res = await fetch('/api/commands/tree');
            const data = await res.json();
            if (data.success && Array.isArray(data.folders)) {
                this.commandFolders = data.folders;
                this._renderCommandTree();
            }
        } catch (err) {
            console.warn('Command tree fetch error:', err);
        }
    }

    async refreshMacros() {
        try {
            const res = await fetch('/api/macros');
            const data = await res.json();
            if (data.success && Array.isArray(data.macros)) {
                this.savedMacros = data.macros;
            }
        } catch (_) {}
    }

    _renderCommandTree() {
        if (!this.commandsTreeBody) return;
        this.commandsTreeBody.innerHTML = '';

        const query = (this.cmdTreeSearch?.value || '').trim().toLowerCase();
        const filteredFolders = this.commandFolders.filter((f) => {
            if (f.scope !== this.activeTreeScope) return false;
            if (!query) return true;
            if (f.title.toLowerCase().includes(query)) return true;
            return (f.commands || []).some((c) =>
                (c.trigger || '').toLowerCase().includes(query) ||
                (c.name || '').toLowerCase().includes(query)
            );
        });

        if (filteredFolders.length === 0) {
            const empty = document.createElement('div');
            empty.style.cssText = 'padding: 32px; text-align: center; color: var(--text-muted); font-size: 13px;';
            empty.textContent = 'В этом разделе пока нет подходящих команд. Нажмите «+ Новая команда», чтобы добавить свою!';
            this.commandsTreeBody.appendChild(empty);
            return;
        }

        filteredFolders.forEach((folder) => {
            const cmds = (folder.commands || []).filter((c) => {
                if (!query) return true;
                return (c.trigger || '').toLowerCase().includes(query) ||
                       (c.name || '').toLowerCase().includes(query) ||
                       folder.title.toLowerCase().includes(query);
            });

            const card = document.createElement('div');
            // Collapsed by default unless search query is active or user expanded it
            const isSearch = Boolean(query);
            const isExpanded = isSearch || this.expandedFolderIds.has(folder.id);
            card.className = `cmd-folder-card${isExpanded ? '' : ' collapsed'}`;

            const head = document.createElement('div');
            head.className = 'cmd-folder-head';
            head.innerHTML = `
                <div class="cmd-folder-title-wrap">
                    <span class="cmd-folder-chevron">▸</span>
                    <div class="cmd-folder-icon">
                        <svg viewBox="0 0 24 24">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                        </svg>
                    </div>
                    <span class="cmd-folder-title">${this._escape(folder.title)}<span class="cmd-folder-count">${cmds.length}</span></span>
                </div>
                <div class="field-row" style="gap: 8px; flex-shrink: 0;">
                    <button type="button" class="mini-pill" data-train-folder="${this._escape(folder.title)}" title="Добавить команду в эту папку">
                        + Добавить сюда
                    </button>
                </div>
            `;

            head.addEventListener('click', (e) => {
                if (e.target.closest('[data-train-folder]')) {
                    e.stopPropagation();
                    this.openNewCommandModal(folder.title, folder.scope);
                    return;
                }
                const nowCollapsed = card.classList.toggle('collapsed');
                if (nowCollapsed) {
                    this.expandedFolderIds.delete(folder.id);
                } else {
                    this.expandedFolderIds.add(folder.id);
                }
            });

            const itemsWrap = document.createElement('div');
            itemsWrap.className = 'cmd-folder-items';

            cmds.forEach((cmd) => {
                const steps = Array.isArray(cmd.steps) ? cmd.steps : [];
                const isChain = steps.length > 1;
                const needsConfirm = Boolean(cmd.require_confirmation);
                const isEnabled = cmd.enabled !== false;
                const firstTrigger = String(cmd.trigger || '').split(',')[0].trim();
                const cmdTitle = cmd.name || firstTrigger;

                const stepsHtml = steps.length > 0
                    ? steps.map((s, idx) => {
                        const rawLabel = String(s.label || `${s.action_type}: ${s.target}`).replace(/^\d+\.\s*/, '');
                        return `<div class="cmd-step-item"><span class="cmd-step-num">${idx + 1}.</span><span>${this._escape(rawLabel)}</span></div>`;
                    }).join('')
                    : `<div class="cmd-step-item"><span class="cmd-step-num">1.</span><span>${this._escape(cmd.response || 'Выполнение команды')}</span></div>`;

                const row = document.createElement('div');
                row.className = `cmd-leaf-row${isEnabled ? '' : ' cmd-leaf-disabled'}`;
                row.innerHTML = `
                    <div class="cmd-leaf-top">
                        <div class="cmd-leaf-info">
                            <div class="cmd-leaf-trigger">
                                <span>${this._escape(cmdTitle)}</span>
                                ${isChain ? `<span class="cmd-badge-chain">Цепочка (${steps.length} шага)</span>` : ''}
                                ${needsConfirm ? `<span class="cmd-badge-confirm">Таймер ${cmd.confirm_timeout_sec || 10}с</span>` : ''}
                            </div>
                        </div>
                        <div class="cmd-leaf-actions" style="gap: 6px;">
                            <button type="button" class="mini-pill ${isEnabled ? 'active-pill' : 'off-pill'}" data-toggle-cmd="${this._escape(cmd.id)}" title="${isEnabled ? 'Команда включена (нажмите, чтобы выключить)' : 'Команда выключена (нажмите, чтобы включить)'}">
                                ${isEnabled ? 'Вкл' : 'Выкл'}
                            </button>
                            <button type="button" class="action-btn" data-edit-cmd="${this._escape(cmd.id)}" title="Редактировать команду" style="width: auto; min-height: 30px; padding: 4px 9px; font-size: 11.5px;">
                                ✎
                            </button>
                            <button type="button" class="action-btn" data-exec-trigger="${this._escape(firstTrigger)}" data-exec-id="${this._escape(cmd.id)}" title="Запустить команду прямо сейчас" style="width: auto; min-height: 30px; padding: 4px 11px; font-size: 11.5px;">
                                Запустить
                            </button>
                            <button type="button" class="action-btn danger" data-del-cmd="${this._escape(cmd.id)}" title="Удалить команду" style="width: auto; min-height: 30px; padding: 4px 9px; font-size: 11.5px;">
                                ✕
                            </button>
                        </div>
                    </div>
                    <div class="cmd-leaf-details">
                        <div class="cmd-trigger-line">Триггерная фраза: <b>«${this._escape(cmd.trigger)}»</b></div>
                        <div class="cmd-steps-list">${stepsHtml}</div>
                    </div>
                `;

                // Toggle On/Off
                row.querySelector('[data-toggle-cmd]')?.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    try {
                        await fetch(`/api/custom_commands/${encodeURIComponent(cmd.id)}/toggle`, { method: 'POST' });
                        await this.refreshCommandTree();
                        this.showToast(`Команда «${cmdTitle}» ${isEnabled ? 'отключена' : 'включена'}`);
                    } catch (_) {}
                });

                // Edit Command
                row.querySelector('[data-edit-cmd]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.openNewCommandModal(folder.title, folder.scope, '', cmd);
                });

                // Run Command
                row.querySelector('[data-exec-trigger]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (cmd.id) {
                        fetch(`/api/commands/execute/${encodeURIComponent(cmd.id)}`, { method: 'POST' })
                            .then(r => {
                                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                                return r.json();
                            })
                            .then(d => {
                                if (d.reply) this.showToast(d.reply);
                            })
                            .catch(() => this.sendMessage(firstTrigger));
                    } else {
                        this.sendMessage(firstTrigger);
                    }
                });

                // Delete Command (Custom OR Built-in!)
                row.querySelector('[data-del-cmd]')?.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    try {
                        await fetch(`/api/custom_commands/${encodeURIComponent(cmd.id)}`, { method: 'DELETE' });
                        await this.refreshCommandTree();
                        this.showToast(`Команда «${cmdTitle}» удалена (можно вернуть кнопкой «↺ Сбросить»)`);
                    } catch (_) {}
                });

                itemsWrap.appendChild(row);
            });

            card.appendChild(head);
            card.appendChild(itemsWrap);
            this.commandsTreeBody.appendChild(card);
        });
    }

    openNewCommandModal(prefillFolder = '', prefillScope = '', prefillMacroId = '', editingCmd = null) {
        if (!this.newCmdModal) return;
        this.editingCmdId = editingCmd ? editingCmd.id : null;
        this.editingCmdName = editingCmd ? (editingCmd.name || '') : null;

        const modalTitle = document.getElementById('new-cmd-modal-title');
        if (modalTitle) {
            modalTitle.textContent = editingCmd
                ? `Редактирование: «${editingCmd.name || editingCmd.trigger}»`
                : 'Создать новую команду / сценарий';
        }

        if (editingCmd) {
            if (this.modalCmdTrigger) this.modalCmdTrigger.value = editingCmd.trigger || '';
            if (this.modalCmdFolder) this.modalCmdFolder.value = editingCmd.folder || prefillFolder || 'Мои сценарии';
            if (this.modalCmdScope) this.modalCmdScope.value = editingCmd.scope || prefillScope || this.activeTreeScope || 'pc';
            if (this.modalCmdResponse) this.modalCmdResponse.value = editingCmd.response || '';
            if (this.modalConfirmChk) this.modalConfirmChk.checked = Boolean(editingCmd.require_confirmation);
            if (this.modalConfirmTimeout) this.modalConfirmTimeout.value = String(editingCmd.confirm_timeout_sec || 10);

            if (this.modalStepsContainer) {
                this.modalStepsContainer.innerHTML = '';
                const steps = Array.isArray(editingCmd.steps) ? editingCmd.steps : [];
                if (steps.length > 0) {
                    steps.forEach((s) => {
                        this._appendStepRow(s.action_type || 'open_app', s.target || '');
                    });
                } else {
                    this._appendStepRow(editingCmd.action_type || 'open_app', editingCmd.target || '');
                }
            }
        } else {
            if (this.modalCmdTrigger) this.modalCmdTrigger.value = '';
            if (this.modalCmdFolder) this.modalCmdFolder.value = prefillFolder || 'Мои сценарии';
            if (this.modalCmdScope) this.modalCmdScope.value = prefillScope || this.activeTreeScope || 'pc';
            if (this.modalCmdResponse) this.modalCmdResponse.value = '';
            if (this.modalConfirmChk) this.modalConfirmChk.checked = false;
            if (this.modalConfirmTimeout) this.modalConfirmTimeout.value = '10';

            if (this.modalStepsContainer) {
                this.modalStepsContainer.innerHTML = '';
                if (prefillMacroId) {
                    this._appendStepRow('macro_play', prefillMacroId);
                } else {
                    this._appendStepRow('open_app', '');
                }
            }
        }
        this.newCmdModal.classList.add('open');
    }

    closeNewCommandModal() {
        this.newCmdModal?.classList.remove('open');
    }

    _appendStepRow(defaultType = 'open_app', defaultTarget = '') {
        if (!this.modalStepsContainer) return;
        const row = document.createElement('div');
        row.className = 'field-row step-builder-row';
        row.style.cssText = 'background: #0b0c10; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border-subtle);';

        row.innerHTML = `
            <select class="ctrl-select step-type-sel" style="max-width: 215px; height: 34px; font-size: 12.5px;">
                <option value="open_app">Запустить программу (.exe)</option>
                <option value="open_url">Открыть сайт / Steam URL</option>
                <option value="set_volume">Громкость Windows (0-100%)</option>
                <option value="set_eva_volume">Громкость Евы (0-150%)</option>
                <option value="hotkey">Нажать клавиши (Хоткей)</option>
                <option value="media_control">Медиа-клавиша (Play/Next/Prev)</option>
                <option value="type_text">Напечатать текст</option>
                <option value="macro_play">Воспроизвести запись (Макрос)</option>
                <option value="avatar_pose">Поза 3D/Live2D модели</option>
                <option value="wait">Пауза (секунд)</option>
                <option value="close_app">Закрыть процесс (.exe)</option>
                <option value="shell">Системная команда (CMD)</option>
                <option value="system">Системное действие (Экран)</option>
            </select>
            <input type="text" class="ctrl-input step-target-inp" style="height: 34px; font-size: 12.5px;" placeholder="Например: chrome, https://youtube.com, 50, ctrl+shift+m" value="${this._escape(defaultTarget)}" />
            <button type="button" class="action-btn step-pick-btn" style="width: auto; min-height: 34px; padding: 0 10px; font-size: 11.5px;" title="Выбрать .exe файл">Обзор</button>
            <button type="button" class="action-btn danger step-del-btn" style="width: auto; min-height: 34px; padding: 0 10px; font-size: 11.5px;">✕</button>
        `;

        const typeSel = row.querySelector('.step-type-sel');
        const targetInp = row.querySelector('.step-target-inp');
        if (typeSel) typeSel.value = defaultType;

        row.querySelector('.step-pick-btn')?.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/custom_commands/pick_app', { method: 'POST' });
                const data = await res.json();
                if (data.success && data.path && targetInp) {
                    targetInp.value = data.path;
                    if (typeSel) typeSel.value = 'open_app';
                }
            } catch (_) {}
        });

        row.querySelector('.step-del-btn')?.addEventListener('click', () => {
            if (this.modalStepsContainer.children.length > 1) {
                row.remove();
            }
        });

        this.modalStepsContainer.appendChild(row);
    }

    _showConfirmationPopup(payload) {
        if (!this.confirmModal || !payload) return;
        this._clearConfirmTimer();
        this._activeConfirmId = payload.confirm_id;

        if (this.confirmModalTitle) {
            this.confirmModalTitle.textContent = `Подтвердите: «${payload.command_name || payload.trigger}»`;
        }
        if (this.confirmModalSteps) {
            const labels = (payload.steps || []).map((s, i) => `${i + 1}. ${s.label || s.target}`).join(' · ');
            this.confirmModalSteps.textContent = labels || 'Выполнить цепочку действий?';
        }

        const totalSec = Number(payload.timeout_sec || 10);
        const startMs = performance.now();
        const durationMs = totalSec * 1000;

        this.confirmModal.classList.add('open');

        this._confirmTimerInterval = setInterval(async () => {
            const elapsed = performance.now() - startMs;
            const remainMs = Math.max(0, durationMs - elapsed);
            const pct = (remainMs / durationMs) * 100;
            if (this.confirmModalBar) this.confirmModalBar.style.width = `${pct}%`;
            if (this.confirmModalCountdown) {
                this.confirmModalCountdown.textContent = `${(remainMs / 1000).toFixed(1)} сек`;
            }
            if (remainMs <= 0) {
                const expiredId = this._activeConfirmId;
                this._hideConfirmationPopup();
                if (expiredId) {
                    try {
                        await fetch(`/api/custom_commands/confirm/${encodeURIComponent(expiredId)}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ approved: false })
                        });
                    } catch (_) {}
                }
                this.showToast('Время подтверждения истекло — команда отменена');
            }
        }, 80);
    }

    _clearConfirmTimer() {
        if (this._confirmTimerInterval) {
            clearInterval(this._confirmTimerInterval);
            this._confirmTimerInterval = null;
        }
    }

    _hideConfirmationPopup() {
        this._clearConfirmTimer();
        this._activeConfirmId = null;
        this.confirmModal?.classList.remove('open');
    }

    _updateTelemetryBadges() {
        const prov = this.selectLLMProvider?.value || 'ollama';
        const mod = this.selectLLMModel?.value || '';
        if (this.sidebarLLMLabel) this.sidebarLLMLabel.textContent = mod || prov;

        const foundModel = this.availableModels.find((m) => m.filename === this.activeModel);
        const cleanAvatarName = foundModel
            ? foundModel.name.replace(/^\[(3D VRM|Live2D)\]\s*/i, '')
            : this.activeModel.split('/').pop();

        if (this.sidebarAvatarLabel) this.sidebarAvatarLabel.textContent = cleanAvatarName;
    }

    _renderModelGallery(models, activeFilename) {
        if (Array.isArray(models) && models.length > 0) {
            this.availableModels = models;
        }
        if (activeFilename) {
            this.activeModel = activeFilename;
        }

        if (this.selectVrmModel && this.availableModels.length > 0) {
            this.selectVrmModel.innerHTML = '';
            this.availableModels.forEach((m) => {
                const opt = document.createElement('option');
                opt.value = m.filename;
                opt.textContent = `${m.name} (${m.size_mb} MB)`;
                this.selectVrmModel.appendChild(opt);
            });
            if (this.activeModel) {
                this.selectVrmModel.value = this.activeModel;
            }
        }

        if (this.modelGalleryGrid) {
            this.modelGalleryGrid.innerHTML = '';
            this.availableModels.forEach((m) => {
                const isActive = m.filename === this.activeModel;
                const isLive2D = m.type === 'live2d' || m.filename.endsWith('.json');
                const cleanTitle = m.name.replace(/^\[(3D VRM|Live2D)\]\s*/i, '');

                const card = document.createElement('button');
                card.type = 'button';
                card.className = `model-card${isActive ? ' active' : ''}`;
                card.innerHTML = `
                    <div class="model-card-top">
                        <span class="model-type-badge ${isLive2D ? 'live2d' : 'vrm'}">${isLive2D ? '2D Live2D' : '3D VRM'}</span>
                        <span class="model-size-tag">${m.size_mb} MB</span>
                    </div>
                    <div class="model-card-name">${this._escape(cleanTitle)}</div>
                    <div class="model-card-footer">
                        <span>${this._escape(m.filename.split('/').pop())}</span>
                        <span>${isActive ? 'Активна' : 'Выбрать'}</span>
                    </div>
                `;
                card.addEventListener('click', () => {
                    this.selectModel(m.filename, cleanTitle);
                });
                this.modelGalleryGrid.appendChild(card);
            });
        }

        this._updateTelemetryBadges();
    }

    async selectModel(modelFilename, displayTitle = '') {
        if (!modelFilename) return;
        const label = displayTitle || modelFilename.split('/').pop();
        this.activeModel = modelFilename;
        this._renderModelGallery(this.availableModels, modelFilename);
        try {
            const res = await fetch('/api/models/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model_name: modelFilename })
            });
            const data = await res.json();
            if (data.success && Array.isArray(data.models)) {
                this._renderModelGallery(data.models, data.model_name || modelFilename);
            }
            this.showToast(`Модель переключена: ${label}`);
        } catch (_) {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'set_model', model_name: modelFilename }));
                this.showToast(`Модель переключена: ${label}`);
            }
        }
    }

    _getProviderPresets(prov) {
        const map = {
            ollama: this.ollamaModels.length > 0 ? this.ollamaModels : ['qwen3.5:9b', 'qwen3:4b', 'qwen2.5:7b', 'llama3.2:latest'],
            eva_free: ['eva-turbo', 'gemini-2.5-flash-lite', 'deepseek-v3.2', 'gemma-4'],
            lm_studio: ['qwen2.5-7b-instruct', 'llama-3.2-3b-instruct', 'deepseek-r1-distill-qwen-7b'],
            gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'],
            openrouter: ['google/gemini-2.0-flash-001', 'deepseek/deepseek-chat', 'meta-llama/llama-3.3-70b-instruct'],
            groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'deepseek-r1-distill-llama-70b'],
            openai: ['gpt-4o-mini', 'gpt-4o', 'o3-mini']
        };
        return map[prov] || ['default'];
    }

    _populateProviderUI(prov, customModelsList = null) {
        const defaults = {
            ollama: { api_base: 'http://127.0.0.1:11434/v1', api_key: 'ollama' },
            eva_free: { api_base: 'https://api.deepai.org', api_key: 'not-needed' },
            lm_studio: { api_base: 'http://127.0.0.1:1234/v1', api_key: 'not-needed' },
            gemini: { api_base: 'https://generativelanguage.googleapis.com/v1beta/openai', api_key: '' },
            openrouter: { api_base: 'https://openrouter.ai/api/v1', api_key: '' },
            groq: { api_base: 'https://api.groq.com/openai/v1', api_key: '' },
            openai: { api_base: 'https://api.openai.com/v1', api_key: '' }
        };

        const cfg = (this.providersConfig && this.providersConfig[prov]) || {};
        const def = defaults[prov] || defaults.ollama;

        if (this.llmBaseInput) {
            this.llmBaseInput.value = cfg.api_base || def.api_base;
        }
        if (this.llmKeyInput) {
            let k = cfg.api_key || def.api_key || '';
            if (k.startsWith('AQ.')) k = '';
            this.llmKeyInput.value = k;
        }

        const models = customModelsList && customModelsList.length > 0
            ? customModelsList
            : this._getProviderPresets(prov);

        const savedModel = cfg.model || models[0] || '';
        this._fillModelDropdown(models, savedModel);
        this._updateTelemetryBadges();
    }

    _fillModelDropdown(modelsList, selectedModel) {
        if (!this.selectLLMModel) return;
        this.selectLLMModel.innerHTML = '';

        const finalModels = [...modelsList];
        if (selectedModel && !finalModels.includes(selectedModel) && selectedModel !== 'default') {
            finalModels.unshift(selectedModel);
        }

        finalModels.forEach((mName) => {
            const opt = document.createElement('option');
            opt.value = mName;
            opt.textContent = mName;
            this.selectLLMModel.appendChild(opt);
        });

        if (selectedModel && finalModels.includes(selectedModel)) {
            this.selectLLMModel.value = selectedModel;
        } else if (finalModels.length > 0) {
            this.selectLLMModel.value = finalModels[0];
        }
        this._updateTelemetryBadges();
    }

    async refreshOllamaModels() {
        try {
            const res = await fetch('/api/ollama/models');
            const data = await res.json();
            if (data.success && Array.isArray(data.models) && data.models.length > 0) {
                this.ollamaModels = data.models;
                if (this.selectLLMProvider.value === 'ollama') {
                    const current = this.providersConfig?.ollama?.model || this.ollamaModels[0];
                    this._fillModelDropdown(this.ollamaModels, current);
                }
            }
        } catch (err) {
            console.warn('Ollama discovery notice:', err);
        }
    }

    _initWebSocket() {
        if (this._wsReconnectTimer) {
            clearTimeout(this._wsReconnectTimer);
            this._wsReconnectTimer = null;
        }
        try {
            if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
                return;
            }
        } catch (_) {}

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${proto}//${location.host}/ws`);

        this.ws.onopen = () => {
            this._setAgentStatus('ONLINE');
        };

        this.ws.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this._handleServerEvent(data);
            } catch (err) {
                console.error(err);
            }
        };

        this.ws.onerror = () => {
            try { this.ws.close(); } catch (_) {}
        };

        this.ws.onclose = () => {
            this._setAgentStatus('RECONNECT');
            this._wsReconnectTimer = setTimeout(() => this._initWebSocket(), 1200);
        };
    }

    _startHeartbeatAndSync() {
        if (this._syncInterval) clearInterval(this._syncInterval);
        this._syncInterval = setInterval(() => {
            if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
                this._initWebSocket();
            } else if (this.ws.readyState === WebSocket.OPEN) {
                try {
                    this.ws.send(JSON.stringify({ type: 'ping' }));
                } catch (_) {}
            }
            this.syncChatHistoryFromServer();
        }, 2000);
    }

    async syncChatHistoryFromServer() {
        try {
            const res = await fetch('/api/chat/history');
            if (!res.ok) return;
            const data = await res.json();
            if (!data.success) return;

            if (data.ai_mode) {
                const normMode = (data.ai_mode === 'passive' || data.ai_mode === 'jarvis') ? 'jarvis' : 'conversational';
                this.aiMode = normMode;
                if (this.selectAiMode && document.activeElement !== this.selectAiMode) {
                    this.selectAiMode.value = normMode;
                }
            }
            if (data.mic_muted !== undefined) {
                this._updateMicMuteUI(data.mic_muted);
            }
            if (data.avatar_visible !== undefined) {
                this._updateAvatarVisUI(data.avatar_visible);
            }

            if (Array.isArray(data.history) && data.history.length > 0 && !this._activeStreamBubble) {
                const domBubbles = Array.from(this.chatStream?.querySelectorAll('.chat-item') || []);
                if (domBubbles.length === 0) {
                    this._hideEmptyState();
                    data.history.forEach((msg) => {
                        if (msg.role === 'user') this._renderUserBubble(msg.content);
                        else if (msg.role === 'assistant') this._renderAssistantBubble(msg.content);
                    });
                } else {
                    const lastDom = domBubbles[domBubbles.length - 1];
                    const lastDomRole = lastDom.dataset.role || (lastDom.classList.contains('user') ? 'user' : 'assistant');
                    const lastDomText = (lastDom.dataset.rawText || lastDom.querySelector('.bubble-text')?.textContent || '').trim();
                    const lastHist = data.history[data.history.length - 1];

                    if (lastHist && (lastHist.role !== lastDomRole || String(lastHist.content || '').trim() !== lastDomText)) {
                        // Find the rightmost match in data.history for lastDom
                        let matchIdx = -1;
                        for (let i = data.history.length - 1; i >= 0; i--) {
                            const h = data.history[i];
                            if (h.role === lastDomRole && String(h.content || '').trim() === lastDomText) {
                                matchIdx = i;
                                break;
                            }
                        }
                        if (matchIdx >= 0 && matchIdx < data.history.length - 1) {
                            for (let j = matchIdx + 1; j < data.history.length; j++) {
                                const msg = data.history[j];
                                if (msg.role === 'user') this._renderUserBubble(msg.content);
                                else if (msg.role === 'assistant') this._renderAssistantBubble(msg.content);
                            }
                        } else if (matchIdx === -1 && data.history.length > domBubbles.length) {
                            for (let j = domBubbles.length; j < data.history.length; j++) {
                                const msg = data.history[j];
                                if (msg.role === 'user') this._renderUserBubble(msg.content);
                                else if (msg.role === 'assistant') this._renderAssistantBubble(msg.content);
                            }
                        }
                    }
                }
            }
        } catch (_) {}
    }

    _setAgentStatus(rawState) {
        if (!this.statusText || !this.statusPillBox) return;
        this.statusPillBox.classList.remove('listening', 'thinking');

        if (rawState === 'LISTENING') {
            this.statusText.textContent = 'СЛУШАЮ';
            this.statusPillBox.classList.add('listening');
        } else if (rawState === 'THINKING' || rawState === 'WORKING') {
            this.statusText.textContent = 'ДУМАЮ';
            this.statusPillBox.classList.add('thinking');
        } else if (rawState === 'SPEAKING') {
            this.statusText.textContent = 'ГОВОРЮ';
            if (this.stopSpeechBtn) this.stopSpeechBtn.style.display = 'inline-flex';
        } else if (rawState === 'RECONNECT') {
            this.statusText.textContent = 'СВЯЗЬ...';
        } else {
            this.statusText.textContent = 'ONLINE';
            if (this.stopSpeechBtn) this.stopSpeechBtn.style.display = 'none';
        }
    }

    _clearChatDOMToEmptyState() {
        if (!this.chatStream) return;
        this._activeStreamBubble = null;
        Array.from(this.chatStream.children).forEach((child) => {
            if (child.id !== 'empty-state-hero') {
                child.remove();
            }
        });
        if (this.emptyHero) {
            this.emptyHero.classList.remove('hidden');
        }
    }

    _hideEmptyState() {
        if (this.emptyHero) {
            this.emptyHero.classList.add('hidden');
        }
    }

    _handleServerEvent(data) {
        const type = data.type;

        if (type === 'init') {
            if (Array.isArray(data.ollama_models) && data.ollama_models.length > 0) {
                this.ollamaModels = data.ollama_models;
            }
            if (data.providers) {
                this.providersConfig = data.providers;
            }
            if (data.llm_provider && this.selectLLMProvider) {
                this.selectLLMProvider.value = data.llm_provider;
                this._populateProviderUI(data.llm_provider);
            }
            if (data.ai_mode && this.selectAiMode) {
                const normMode = (data.ai_mode === 'passive' || data.ai_mode === 'jarvis') ? 'jarvis' : 'conversational';
                this.aiMode = normMode;
                this.selectAiMode.value = normMode;
            }
            if (data.avatar_visible !== undefined) {
                this._updateAvatarVisUI(data.avatar_visible);
            }
            if (data.mic_muted !== undefined) {
                this._updateMicMuteUI(data.mic_muted);
            }
            if (data.voice_eq) {
                this._updateVoiceEqUI(data.voice_eq);
            }
            if (Array.isArray(data.custom_commands)) {
                this._renderCustomCommands(data.custom_commands);
            }
            if (Array.isArray(data.command_folders)) {
                this.commandFolders = data.command_folders;
                this._renderCommandTree();
            }

            if (Array.isArray(data.models)) {
                this._renderModelGallery(data.models, data.active_model || 'sample_vrm1.vrm');
            }

            if (Array.isArray(data.output_devices) || Array.isArray(data.input_devices)) {
                this._populateAudioDevices(
                    data.output_devices || [],
                    data.input_devices || [],
                    data.output_device ?? 'auto',
                    data.input_device_index ?? -1
                );
            }

            if (data.voice_profile && this.selectVoice) {
                this.selectVoice.value = data.voice_profile;
            }
            if (data.elevenlabs_key !== undefined && this.elevenKeyInput) {
                this.elevenKeyInput.value = data.elevenlabs_key;
            }
            if (data.elevenlabs_voice_id !== undefined && this.elevenVoiceInput) {
                let vid = data.elevenlabs_voice_id || 'cgSgspJ2msm6clMCkdW9';
                if (vid === '21m00Tcm4TlvDq8ikWAM') vid = 'cgSgspJ2msm6clMCkdW9';
                this.elevenVoiceInput.value = vid;
                if (this.elevenPreset) {
                    const exists = Array.from(this.elevenPreset.options).some((o) => o.value === vid);
                    this.elevenPreset.value = exists ? vid : 'custom';
                }
            }

            if (Array.isArray(data.history) && data.history.length > 0) {
                this._clearChatDOMToEmptyState();
                this._hideEmptyState();
                data.history.forEach((msg) => {
                    if (msg.role === 'user') this._renderUserBubble(msg.content);
                    else if (msg.role === 'assistant') this._renderAssistantBubble(msg.content);
                });
            } else {
                this._clearChatDOMToEmptyState();
            }
        } else if (type === 'history_cleared') {
            this._clearChatDOMToEmptyState();
        } else if (type === 'avatar_visibility') {
            this._updateAvatarVisUI(data.visible);
        } else if (type === 'mic_muted') {
            this._updateMicMuteUI(data.muted);
        } else if (type === 'ai_mode_changed') {
            const normMode = (data.ai_mode === 'passive' || data.ai_mode === 'jarvis') ? 'jarvis' : 'conversational';
            this.aiMode = normMode;
            if (this.selectAiMode) this.selectAiMode.value = normMode;
        } else if (type === 'voice_eq_changed' && data.eq) {
            this._updateVoiceEqUI(data.eq);
        } else if (type === 'custom_commands_updated') {
            if (Array.isArray(data.commands)) this._renderCustomCommands(data.commands);
            if (Array.isArray(data.folders)) {
                this.commandFolders = data.folders;
                this._renderCommandTree();
            } else {
                this.refreshCommandTree();
            }
        } else if (type === 'command_confirmation_required') {
            this._showConfirmationPopup(data.payload || data);
        } else if (type === 'command_confirmation_resolved') {
            this._hideConfirmationPopup();
        } else if (type === 'state') {
            this._setAgentStatus(data.state);
            if (data.state === 'LISTENING') {
                this.isRecording = true;
                this.micBtn?.classList.add('recording');
            } else if (data.state === 'IDLE' || data.state === 'THINKING') {
                this.isRecording = false;
                this.micBtn?.classList.remove('recording');
                if (this.textInput) {
                    this.textInput.placeholder = 'Скажите «Ева ...» или напишите команду (например: уютный вечер, какая погода, включи музыку)...';
                }
            }
        } else if (type === 'mic_state') {
            this.isRecording = Boolean(data.active);
            this.micBtn?.classList.toggle('recording', this.isRecording);
            this._setAgentStatus(this.isRecording ? 'LISTENING' : 'ONLINE');
            if (this.textInput) {
                this.textInput.placeholder = this.isRecording
                    ? 'Микрофон активен — говорите команду...'
                    : 'Скажите «Ева ...» или напишите команду (например: уютный вечер, какая погода, включи музыку)...';
            }
        } else if (type === 'thought') {
            if (
                data.content &&
                !data.content.includes('готов к работе') &&
                !data.content.includes('Загрузка нейросети') &&
                !data.content.includes('Нейросеть успешно загружена') &&
                !data.content.includes('Слушаю микрофон (Device ID') &&
                (
                    data.content.includes('[Инструмент]') ||
                    data.content.includes('[Поиск]') ||
                    data.content.includes('Распознано:') ||
                    data.content.includes('Команда получена:') ||
                    data.content.includes('обнаружен! Жду вашу команду')
                )
            ) {
                this._hideEmptyState();
                const el = document.createElement('div');
                el.className = 'tool-log';
                el.textContent = data.content;
                this.chatStream.appendChild(el);
                this.chatStream.scrollTop = this.chatStream.scrollHeight;
            }
        } else if (type === 'user_message') {
            this._activeStreamBubble = null;
            this._renderUserBubble(data.text);
        } else if (type === 'search_state') {
            this._handleSearchState(data);
        } else if (type === 'response_chunk') {
            this._updateStreamingBubble(data.text);
        } else if (type === 'response') {
            this._handleSearchState({ active: false, status: 'done' });
            this._renderAssistantBubble(data.text);
        } else if (type === 'audio_playback') {
            if (this.stopSpeechBtn) this.stopSpeechBtn.style.display = 'inline-flex';
            if (data.audio_base64 && !data.played_by_backend && !this.avatarVisible) {
                try {
                    if (this._fallbackAudio) this._fallbackAudio.pause();
                    this._fallbackAudio = new Audio(`data:audio/mp3;base64,${data.audio_base64}`);
                    const vol = Math.max(0, Math.min(1.0, ((data.voice_eq?.volume ?? this.voiceEq?.volume ?? 100) / 100.0)));
                    this._fallbackAudio.volume = vol;
                    this._fallbackAudio.onended = () => {
                        if (this.stopSpeechBtn) this.stopSpeechBtn.style.display = 'none';
                    };
                    this._fallbackAudio.play().catch(() => {});
                } catch (_) {}
            }
        } else if (type === 'speech_stopped') {
            if (this.stopSpeechBtn) this.stopSpeechBtn.style.display = 'none';
            if (this._fallbackAudio) {
                try { this._fallbackAudio.pause(); } catch (_) {}
                this._fallbackAudio = null;
            }
        } else if (type === 'model_changed') {
            this._renderModelGallery(data.models || this.availableModels, data.model_name);
        }
    }

    _handleSearchState(data) {
        if (!this.chatStream) return;
        const isSearching = data.active !== undefined ? Boolean(data.active) : (data.status === 'searching');
        let card = document.getElementById('search-indicator-card');

        if (isSearching) {
            if (this._searchHideTimer) {
                clearTimeout(this._searchHideTimer);
                this._searchHideTimer = null;
            }
            this._searchStartedAt = Date.now();
            this._hideEmptyState();
            if (!card) {
                card = document.createElement('div');
                card.id = 'search-indicator-card';
                card.className = 'search-indicator-card';
                card.innerHTML = `
                    <div class="search-radar">
                        <div class="search-radar-circle"></div>
                        <div class="search-radar-circle"></div>
                        <svg class="search-radar-icon" viewBox="0 0 24 24">
                            <circle cx="11" cy="11" r="8"/>
                            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                        </svg>
                    </div>
                    <div class="search-status-text">
                        <span>Ищу актуальную информацию в интернете...</span>
                        <div class="search-status-query" id="search-status-query"></div>
                    </div>
                `;
                this.chatStream.appendChild(card);
            } else {
                card.style.opacity = '1';
                card.style.transform = 'none';
            }
            const qEl = card.querySelector('#search-status-query');
            if (qEl && data.query) {
                qEl.textContent = `«${data.query}» (${data.source || 'MET Norway / Steam / RSS / Web'})`;
            }
            this.chatStream.scrollTop = this.chatStream.scrollHeight;
        } else {
            if (card) {
                const elapsed = Date.now() - (this._searchStartedAt || 0);
                const minDisplayMs = 600;
                const waitMs = Math.max(0, minDisplayMs - elapsed);
                if (this._searchHideTimer) clearTimeout(this._searchHideTimer);
                this._searchHideTimer = setTimeout(() => {
                    const c = document.getElementById('search-indicator-card');
                    if (c) {
                        c.style.transition = 'opacity 0.35s ease, transform 0.35s ease';
                        c.style.opacity = '0';
                        c.style.transform = 'translateY(-6px)';
                        setTimeout(() => c.remove(), 350);
                    }
                }, waitMs);
            }
        }
    }

    async sendMessage(text) {
        if (!text || !text.trim()) return;
        const clean = text.trim();
        if (this.textInput) this.textInput.value = '';
        this._activeStreamBubble = null;
        this._renderUserBubble(clean);

        try {
            const res = await fetch('/api/chat/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: clean })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (_) {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'user_message', text: clean }));
            }
        }

        setTimeout(() => this.syncChatHistoryFromServer(), 700);
        setTimeout(() => this.syncChatHistoryFromServer(), 1800);
    }

    async sendAvatarAction(payload) {
        try {
            await fetch('/api/avatar/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {})
            });
        } catch (_) {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'avatar_action', ...payload }));
            }
        }
    }

    async clearHistory() {
        try {
            await fetch('/api/history/clear', { method: 'POST' });
            this._clearChatDOMToEmptyState();
            this.showToast('История запросов очищена');
        } catch (_) {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'clear_history' }));
            }
        }
    }

    _renderUserBubble(text) {
        if (!text || !this.chatStream) return;
        const clean = String(text).trim();
        if (!clean) return;

        // Deduplicate if the exact same user bubble was just rendered optimistically
        const domBubbles = Array.from(this.chatStream.querySelectorAll('.chat-item'));
        const lastBubble = domBubbles[domBubbles.length - 1];
        if (
            lastBubble &&
            lastBubble.dataset.role === 'user' &&
            lastBubble.dataset.rawText === clean &&
            Date.now() - Number(lastBubble.dataset.renderedAt || 0) < 4000
        ) {
            return;
        }

        this._hideEmptyState();
        if (this._activeStreamBubble) {
            try { this._activeStreamBubble.remove(); } catch (_) {}
            this._activeStreamBubble = null;
        }
        const el = document.createElement('div');
        el.className = 'chat-item user';
        el.dataset.role = 'user';
        el.dataset.rawText = clean;
        el.dataset.renderedAt = String(Date.now());
        el.innerHTML = `<div class="chat-meta">ВЫ</div><div class="bubble-text">${this._escape(clean)}</div>`;
        this.chatStream.appendChild(el);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    _getAssistantBadgeLabel(text = '') {
        if (this.aiMode === 'jarvis' || this.aiMode === 'passive' || /\bсэр\b/i.test(text) || /джарвис/i.test(text)) {
            return 'J.A.R.V.I.S.';
        }
        return 'EVA AI';
    }

    _updateStreamingBubble(text) {
        this._hideEmptyState();
        const badge = this._getAssistantBadgeLabel(text);
        if (!this._activeStreamBubble) {
            const el = document.createElement('div');
            el.className = 'chat-item assistant';
            el.dataset.role = 'assistant';
            el.innerHTML = `<div class="chat-meta">${badge}</div><div class="bubble-text"></div>`;
            this.chatStream.appendChild(el);
            this._activeStreamBubble = el;
        } else {
            const meta = this._activeStreamBubble.querySelector('.chat-meta');
            if (meta) meta.textContent = badge;
        }
        this._activeStreamBubble.dataset.rawText = String(text || '').trim();
        this._activeStreamBubble.dataset.renderedAt = String(Date.now());
        const t = this._activeStreamBubble.querySelector('.bubble-text');
        if (t) t.innerHTML = this._escape(text);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    _renderAssistantBubble(text) {
        if (!text || !this.chatStream) return;
        const clean = String(text).trim();
        if (!clean) return;

        this._hideEmptyState();
        const badge = this._getAssistantBadgeLabel(clean);
        if (this._activeStreamBubble) {
            const meta = this._activeStreamBubble.querySelector('.chat-meta');
            if (meta) meta.textContent = badge;
            const t = this._activeStreamBubble.querySelector('.bubble-text');
            if (t) t.innerHTML = this._escape(clean);
            this._activeStreamBubble.dataset.role = 'assistant';
            this._activeStreamBubble.dataset.rawText = clean;
            this._activeStreamBubble.dataset.renderedAt = String(Date.now());
            this._activeStreamBubble = null;
            this.chatStream.scrollTop = this.chatStream.scrollHeight;
            return;
        }

        // Deduplicate if the exact same assistant bubble was already rendered
        const domBubbles = Array.from(this.chatStream.querySelectorAll('.chat-item'));
        const lastBubble = domBubbles[domBubbles.length - 1];
        if (
            lastBubble &&
            lastBubble.dataset.role === 'assistant' &&
            lastBubble.dataset.rawText === clean &&
            Date.now() - Number(lastBubble.dataset.renderedAt || 0) < 4000
        ) {
            return;
        }

        const el = document.createElement('div');
        el.className = 'chat-item assistant';
        el.dataset.role = 'assistant';
        el.dataset.rawText = clean;
        el.dataset.renderedAt = String(Date.now());
        el.innerHTML = `<div class="chat-meta">${badge}</div><div class="bubble-text">${this._escape(clean)}</div>`;
        this.chatStream.appendChild(el);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    _escape(str) {
        return String(str).replace(/[&<>'"]/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[c] || c));
    }

    _initEvents() {
        this.sendBtn?.addEventListener('click', () => this.sendMessage(this.textInput.value));
        this.textInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.sendMessage(this.textInput.value);
        });

        this.micBtn?.addEventListener('click', async (e) => {
            e.preventDefault();
            if (this.isMicMuted) {
                this.showToast('Микрофон замучен — сначала включите его на левой панели');
                return;
            }
            try {
                const res = await fetch('/api/mic/toggle', { method: 'POST' });
                const data = await res.json();
                if (data.success !== undefined) {
                    this.isRecording = Boolean(data.active);
                    this.micBtn?.classList.toggle('recording', this.isRecording);
                    this._setAgentStatus(this.isRecording ? 'LISTENING' : 'ONLINE');
                    if (this.textInput) {
                        this.textInput.placeholder = this.isRecording
                            ? 'Микрофон активен — говорите команду...'
                            : 'Скажите «Ева ...» или напишите команду (например: уютный вечер, какая погода, включи музыку)...';
                    }
                }
            } catch (_) {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'mic_toggle' }));
                }
            }
        });

        // Microphone Mute Toggle Button
        this.micMuteBtn?.addEventListener('click', async () => {
            const nextMuted = !this.isMicMuted;
            this._updateMicMuteUI(nextMuted);
            try {
                const res = await fetch('/api/mic/mute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ muted: nextMuted })
                });
                const data = await res.json();
                this._updateMicMuteUI(data.muted);
                this.showToast(data.muted ? 'Микрофон ЗАМУЧЕН — Ева вас не слышит' : 'Микрофон ВКЛЮЧЁН — Ева снова слушает');
            } catch (_) {}
        });

        // Rail Logo Button -> Go to Chat
        document.getElementById('rail-logo-btn')?.addEventListener('click', () => {
            this.switchTab('tab-chat');
        });

        // Rail GitHub Repository Button
        document.getElementById('btn-github-repo')?.addEventListener('click', async () => {
            try {
                await fetch('/api/github/open', { method: 'POST' });
                this.showToast('Открываю GitHub репозиторий проекта...');
            } catch (_) {}
        });

        this.stopSpeechBtn?.addEventListener('click', async () => {
            this.stopSpeechBtn.style.display = 'none';
            if (this._fallbackAudio) {
                try { this._fallbackAudio.pause(); } catch (_) {}
                this._fallbackAudio = null;
            }
            try {
                await fetch('/api/speech/stop', { method: 'POST' });
            } catch (_) {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'stop_speaking' }));
                }
            }
        });

        this.clearHistoryBtn?.addEventListener('click', () => this.clearHistory());

        // AI Mode Switcher ('conversational' vs 'jarvis')
        this.selectAiMode?.addEventListener('change', async (e) => {
            const mode = e.target.value;
            this.aiMode = mode;
            try {
                await fetch('/api/ai_mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ai_mode: mode })
                });
                const label = (mode === 'jarvis' || mode === 'passive')
                    ? 'J.A.R.V.I.S. («Да, сэр» — голос и стиль Джарвиса)'
                    : 'Ева (Общительный компаньон)';
                this.showToast(`Режим ИИ: ${label}`);
            } catch (_) {}
        });

        // 1-Click Avatar Visibility Toggle
        this.toggleAvatarVisBtn?.addEventListener('click', async () => {
            const nextState = !this.avatarVisible;
            this._updateAvatarVisUI(nextState);
            try {
                await fetch('/api/avatar/visibility', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ visible: nextState })
                });
                this.showToast(nextState ? '3D/Live2D модель показана на экране' : 'Модель скрыта с экрана (голосовой режим активен)');
            } catch (_) {}
        });

        // Quick Prompt Cards
        document.querySelectorAll('[data-quick-prompt]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const prompt = btn.getAttribute('data-quick-prompt');
                if (prompt) {
                    this.switchTab('tab-chat');
                    this.sendMessage(prompt);
                }
            });
        });

        // Sidebar Rail Tab Navigation
        document.querySelectorAll('.nav-btn[data-tab], .rail-nav-btn[data-tab]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.switchTab(btn.getAttribute('data-tab'));
            });
        });

        // Commands Tree Scope Switcher (PC / 3D Avatar / App Packs)
        document.querySelectorAll('[data-tree-scope]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.activeTreeScope = btn.getAttribute('data-tree-scope') || 'pc';
                document.querySelectorAll('[data-tree-scope]').forEach((b) => {
                    b.classList.toggle('active', b === btn);
                });
                this._renderCommandTree();
            });
        });

        this.cmdTreeSearch?.addEventListener('input', () => {
            this._renderCommandTree();
        });

        // New Multi-Step Command Modal Events
        document.getElementById('btn-open-new-cmd-modal')?.addEventListener('click', () => {
            this.openNewCommandModal('', this.activeTreeScope);
        });
        document.querySelectorAll('[data-scenario-template]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const tpl = btn.getAttribute('data-scenario-template');
                this.openNewCommandModal('Утренние и вечерние сценарии', 'pc');
                if (this.modalStepsContainer) this.modalStepsContainer.innerHTML = '';
                if (tpl === 'morning') {
                    if (this.modalCmdTrigger) this.modalCmdTrigger.value = 'доброе утро';
                    if (this.modalCmdResponse) this.modalCmdResponse.value = 'Доброе утро! Браузер открыт, громкость выставлена на 50 процентов.';
                    this._appendStepRow('open_app', 'chrome');
                    this._appendStepRow('open_url', 'https://www.youtube.com');
                    this._appendStepRow('set_volume', '50');
                } else if (tpl === 'evening') {
                    if (this.modalCmdTrigger) this.modalCmdTrigger.value = 'уютный вечер';
                    if (this.modalCmdResponse) this.modalCmdResponse.value = 'Включаю режим уютного вечера: YouTube, Steam и спокойная музыка!';
                    this._appendStepRow('open_url', 'https://www.youtube.com');
                    this._appendStepRow('open_app', 'steam');
                    this._appendStepRow('open_app', 'spotify');
                } else if (tpl === 'stream') {
                    if (this.modalCmdTrigger) this.modalCmdTrigger.value = 'начать стрим';
                    if (this.modalCmdFolder) this.modalCmdFolder.value = 'Управление OBS и Стримом';
                    if (this.modalCmdResponse) this.modalCmdResponse.value = 'Запускаю OBS Studio и открываю панель трансляции!';
                    this._appendStepRow('open_app', 'obs');
                    this._appendStepRow('wait', '2');
                    this._appendStepRow('open_url', 'https://www.twitch.tv');
                }
            });
        });
        document.getElementById('btn-close-new-cmd-modal')?.addEventListener('click', () => {
            this.closeNewCommandModal();
        });
        document.getElementById('btn-cancel-new-cmd-modal')?.addEventListener('click', () => {
            this.closeNewCommandModal();
        });
        document.getElementById('btn-add-step-row')?.addEventListener('click', () => {
            this._appendStepRow('open_app', '');
        });

        document.getElementById('btn-save-new-cmd-modal')?.addEventListener('click', async () => {
            const trigger = this.modalCmdTrigger?.value.trim() || '';
            const folder = this.modalCmdFolder?.value.trim() || 'Мои сценарии';
            const scope = this.modalCmdScope?.value || 'pc';
            const response = this.modalCmdResponse?.value.trim() || 'Готово!';
            const requireConfirm = Boolean(this.modalConfirmChk?.checked);
            const timeoutSec = Number(this.modalConfirmTimeout?.value || 10);

            const steps = [];
            this.modalStepsContainer?.querySelectorAll('.step-builder-row').forEach((row) => {
                const stType = row.querySelector('.step-type-sel')?.value || 'open_app';
                const stTarget = row.querySelector('.step-target-inp')?.value.trim() || '';
                if (stTarget) {
                    steps.push({ action_type: stType, target: stTarget });
                }
            });

            if (!trigger || steps.length === 0) {
                this.showToast('Укажите ключевую фразу и хотя бы один шаг действия!');
                return;
            }

            try {
                const endpoint = this.editingCmdId
                    ? `/api/custom_commands/${encodeURIComponent(this.editingCmdId)}`
                    : '/api/custom_commands';
                const method = this.editingCmdId ? 'PUT' : 'POST';
                const cmdName = (this.editingCmdId && this.editingCmdName) ? this.editingCmdName : trigger;

                const res = await fetch(endpoint, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        trigger,
                        name: cmdName,
                        folder,
                        scope,
                        steps,
                        response,
                        require_confirmation: requireConfirm,
                        confirm_timeout_sec: timeoutSec
                    })
                });
                const data = await res.json();
                if (data.success) {
                    const isEdit = Boolean(this.editingCmdId);
                    this.closeNewCommandModal();
                    this.activeTreeScope = scope;
                    document.querySelectorAll('[data-tree-scope]').forEach((b) => {
                        b.classList.toggle('active', b.getAttribute('data-tree-scope') === scope);
                    });
                    await this.refreshCommandTree();
                    this.showToast(isEdit ? `Команда «${cmdName}» обновлена!` : `Команда «${cmdName}» добавлена в папку «${folder}»!`);
                }
            } catch (err) {
                this.showToast(`Ошибка: ${err.message}`);
            }
        });

        document.getElementById('btn-restore-defaults')?.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/custom_commands/restore_defaults', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    await this.refreshCommandTree();
                    this.showToast('Стандартные команды успешно восстановлены!');
                }
            } catch (err) {
                this.showToast(`Ошибка сброса: ${err.message}`);
            }
        });

        // Confirmation Popup Approve / Cancel Buttons
        document.getElementById('btn-confirm-approve')?.addEventListener('click', async () => {
            const cid = this._activeConfirmId;
            this._hideConfirmationPopup();
            if (cid) {
                try {
                    await fetch(`/api/custom_commands/confirm/${encodeURIComponent(cid)}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ approved: true })
                    });
                    this.showToast('Команда подтверждена и выполняется!');
                } catch (_) {}
            }
        });

        document.getElementById('btn-confirm-cancel')?.addEventListener('click', async () => {
            const cid = this._activeConfirmId;
            this._hideConfirmationPopup();
            if (cid) {
                try {
                    await fetch(`/api/custom_commands/confirm/${encodeURIComponent(cid)}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ approved: false })
                    });
                    this.showToast('Выполнение команды отменено');
                } catch (_) {}
            }
        });

        // Action Macro Recorder Toggle
        this.macroRecBtn?.addEventListener('click', async () => {
            if (!this.isMacroRecording) {
                try {
                    const res = await fetch('/api/macros/record/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: 'Запись действий' })
                    });
                    const data = await res.json();
                    if (data.success) {
                        this.isMacroRecording = true;
                        this._macroStartSec = 0;
                        this.macroRecIndicator?.classList.add('recording');
                        if (this.macroRecStatusText) this.macroRecStatusText.textContent = 'Идёт запись кликов и клавиш...';
                        this.macroRecBtn.textContent = 'Остановить и сохранить';
                        this.macroRecBtn.classList.replace('primary', 'danger');
                        this._macroTimerInterval = setInterval(() => {
                            this._macroStartSec += 1;
                            const mm = String(Math.floor(this._macroStartSec / 60)).padStart(2, '0');
                            const ss = String(this._macroStartSec % 60).padStart(2, '0');
                            if (this.macroRecTimer) this.macroRecTimer.textContent = `${mm}:${ss}`;
                        }, 1000);
                        this.showToast('Запись началась! Выполните нужные клики мышью или нажатия клавиш');
                    }
                } catch (_) {}
            } else {
                if (this._macroTimerInterval) {
                    clearInterval(this._macroTimerInterval);
                    this._macroTimerInterval = null;
                }
                this.isMacroRecording = false;
                this.macroRecIndicator?.classList.remove('recording');
                if (this.macroRecStatusText) this.macroRecStatusText.textContent = 'Готов к записи';
                this.macroRecBtn.textContent = 'Начать запись действий';
                this.macroRecBtn.classList.replace('danger', 'primary');
                try {
                    const res = await fetch('/api/macros/record/stop', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: `Макрос (${new Date().toLocaleTimeString()})` })
                    });
                    const data = await res.json();
                    if (data.success && data.macro) {
                        await this.refreshMacros();
                        const evCount = data.macro.count ?? data.macro.events?.length ?? 0;
                        this.showToast(`Записано событий: ${evCount}. Привяжите ключевую фразу!`);
                        this.openNewCommandModal('Мои макросы', 'pc', data.macro.id);
                    }
                } catch (_) {}
            }
        });

        // Hide Control Center to Background
        document.getElementById('btn-hide-control')?.addEventListener('click', async () => {
            try {
                await fetch('/api/window/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'hide_control' })
                });
            } catch (_) {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'window_action', action: 'hide_control' }));
                }
            }
        });

        this.newCmdModal?.addEventListener('click', (e) => {
            if (e.target === this.newCmdModal) {
                this.closeNewCommandModal();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (this.newCmdModal?.classList.contains('open')) {
                    this.closeNewCommandModal();
                }
                if (this.confirmModal?.classList.contains('open')) {
                    document.getElementById('btn-confirm-cancel')?.click();
                }
            }
        });

        // Custom Commands Builder Events
        document.getElementById('btn-pick-cmd-app')?.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/custom_commands/pick_app', { method: 'POST' });
                const data = await res.json();
                if (data.success && data.path && this.cmdTargetInput) {
                    this.cmdTargetInput.value = data.path;
                    if (this.cmdActionType) this.cmdActionType.value = 'open_app';
                }
            } catch (_) {}
        });

        document.querySelectorAll('[data-cmd-preset]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const p = btn.getAttribute('data-cmd-preset');
                if (p === 'cs2') {
                    this.cmdTriggerInput.value = 'го в кс';
                    this.cmdActionType.value = 'open_url';
                    this.cmdTargetInput.value = 'steam://rungameid/730';
                    this.cmdResponseInput.value = 'Запускаю Counter-Strike 2, тащи катку!';
                } else if (p === 'dota2') {
                    this.cmdTriggerInput.value = 'го в доту';
                    this.cmdActionType.value = 'open_url';
                    this.cmdTargetInput.value = 'steam://rungameid/570';
                    this.cmdResponseInput.value = 'Запускаю Dota 2, удачной игры!';
                } else if (p === 'spotify_like') {
                    this.cmdTriggerInput.value = 'музыка стоп';
                    this.cmdActionType.value = 'hotkey';
                    this.cmdTargetInput.value = 'playpause';
                    this.cmdResponseInput.value = 'Переключила воспроизведение музыки.';
                } else if (p === 'discord_mute') {
                    this.cmdTriggerInput.value = 'тишина в дискорде';
                    this.cmdActionType.value = 'hotkey';
                    this.cmdTargetInput.value = 'ctrl+shift+m';
                    this.cmdResponseInput.value = 'Переключила микрофон в Discord.';
                }
            });
        });

        document.getElementById('btn-add-custom-cmd')?.addEventListener('click', async () => {
            const trigger = this.cmdTriggerInput?.value.trim() || '';
            const actionType = this.cmdActionType?.value || 'open_app';
            const target = this.cmdTargetInput?.value.trim() || '';
            const response = this.cmdResponseInput?.value.trim() || '';

            if (!trigger || !target) {
                this.showToast('Заполните фразу-триггер и действие');
                return;
            }

            try {
                const res = await fetch('/api/custom_commands', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        trigger,
                        action_type: actionType,
                        target,
                        response
                    })
                });
                const data = await res.json();
                if (data.success) {
                    if (this.cmdTriggerInput) this.cmdTriggerInput.value = '';
                    if (this.cmdTargetInput) this.cmdTargetInput.value = '';
                    if (this.cmdResponseInput) this.cmdResponseInput.value = '';
                    this._renderCustomCommands(data.commands || []);
                    this.showToast(`Команда «${trigger}» добавлена!`);
                }
            } catch (err) {
                this.showToast(`Ошибка: ${err.message}`);
            }
        });

        // Voice Volume Sliders (Chat Header + Voice Studio)
        const syncVolumeSliders = (srcSlider, commit = false) => {
            if (!srcSlider) return;
            const v = srcSlider.value;
            if (this.eqVolume && this.eqVolume !== srcSlider) this.eqVolume.value = v;
            if (this.headerEvaVolume && this.headerEvaVolume !== srcSlider) this.headerEvaVolume.value = v;
            this._refreshEqBadges();
            if (commit) {
                this.saveVoiceEq();
            }
        };

        [this.headerEvaVolume, this.eqVolume].forEach((volSlider) => {
            volSlider?.addEventListener('input', () => syncVolumeSliders(volSlider, true));
            volSlider?.addEventListener('change', () => syncVolumeSliders(volSlider, true));
        });

        // Voice Equalizer Sliders & Presets
        [this.eqPitch, this.eqSpeed, this.eqBass, this.eqTreble].forEach((slider) => {
            slider?.addEventListener('input', () => this._refreshEqBadges());
            slider?.addEventListener('change', () => {
                this._refreshEqBadges();
                this.saveVoiceEq();
            });
        });

        document.querySelectorAll('[data-eq-preset]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const preset = btn.getAttribute('data-eq-preset');
                const map = {
                    natural: { pitch: 0, speed: 1.0, bass: 0, treble: 0 },
                    cute:    { pitch: 4, speed: 1.08, bass: -2, treble: 4 },
                    velvet:  { pitch: -3, speed: 0.96, bass: 5, treble: 1 },
                    crisp:   { pitch: 1, speed: 1.12, bass: 1, treble: 4 }
                };
                const cfg = { ...(map[preset] || map.natural), volume: this.voiceEq.volume ?? 100 };
                this._updateVoiceEqUI(cfg);
                await this.saveVoiceEq();
                this.showToast('Пресет эквалайзера применён');
            });
        });

        // Pose Presets (both in Chat quick-bar and Avatar Studio)
        document.querySelectorAll('[data-pose]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const pose = btn.getAttribute('data-pose');
                if (pose) {
                    document.querySelectorAll('[data-pose]').forEach((b) => {
                        b.classList.toggle('active', b.getAttribute('data-pose') === pose);
                    });
                    this.sendAvatarAction({ pose });
                }
            });
        });

        // Camera Presets
        document.querySelectorAll('[data-cam]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const camera = btn.getAttribute('data-cam');
                if (camera) {
                    document.querySelectorAll('[data-cam]').forEach((b) => {
                        b.classList.toggle('active', b.getAttribute('data-cam') === camera);
                    });
                    this.sendAvatarAction({ camera });
                }
            });
        });

        // LLM Provider Change
        this.selectLLMProvider?.addEventListener('change', async (e) => {
            const prov = e.target.value;
            if (prov === 'ollama') {
                await this.refreshOllamaModels();
            }
            this._populateProviderUI(prov);
            await this._autoSaveLLMSelection();
            this.showToast(`Провайдер ИИ: ${prov}`);
        });

        this.selectLLMModel?.addEventListener('change', async () => {
            await this._autoSaveLLMSelection();
            this._updateTelemetryBadges();
            this.showToast(`Активна модель: ${this.selectLLMModel.value}`);
        });

        document.getElementById('btn-refresh-models')?.addEventListener('click', async () => {
            await this.refreshOllamaModels();
            document.getElementById('btn-test-llm')?.click();
        });

        document.getElementById('btn-test-llm')?.addEventListener('click', async () => {
            const prov = this.selectLLMProvider.value;
            const apiBase = this.llmBaseInput.value.trim();
            const apiKey = this.llmKeyInput.value.trim();
            const model = this.selectLLMModel.value;

            if (this.llmTestStatus) {
                this.llmTestStatus.style.display = 'block';
                this.llmTestStatus.textContent = 'Проверка подключения и получение списка моделей...';
            }

            try {
                const res = await fetch('/api/llm/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: prov, api_base: apiBase, api_key: apiKey, model })
                });
                const json = await res.json();
                if (json.success) {
                    if (Array.isArray(json.models) && json.models.length > 0) {
                        if (prov === 'ollama') this.ollamaModels = json.models;
                        this._fillModelDropdown(json.models, model);
                    }
                    if (this.llmTestStatus) {
                        this.llmTestStatus.textContent = json.message;
                    }
                    this.showToast('Связь с нейросетью проверена');
                } else if (this.llmTestStatus) {
                    this.llmTestStatus.textContent = json.error || 'Ошибка подключения';
                }
            } catch (err) {
                if (this.llmTestStatus) {
                    this.llmTestStatus.textContent = `Ошибка: ${err.message}`;
                }
            }
        });

        // VRM / Live2D Select Dropdown
        this.selectVrmModel?.addEventListener('change', (e) => {
            const modelName = e.target.value;
            if (modelName) {
                this.selectModel(modelName);
            }
        });

        // Upload VRM or ZIP
        document.getElementById('btn-upload-vrm')?.addEventListener('click', () => {
            this.vrmFileInput?.click();
        });
        this.vrmFileInput?.addEventListener('change', async (e) => {
            if (e.target.files.length > 0) {
                if (this.live2dUploadStatus) {
                    this.live2dUploadStatus.style.display = 'block';
                    this.live2dUploadStatus.textContent = 'Загрузка модели...';
                }
                const formData = new FormData();
                formData.append('file', e.target.files[0]);
                try {
                    const res = await fetch('/api/models/upload', { method: 'POST', body: formData });
                    const json = await res.json();
                    if (json.success) {
                        if (this.live2dUploadStatus) {
                            this.live2dUploadStatus.textContent = `Модель успешно загружена и активирована: ${json.filename}`;
                        }
                        this.showToast(`Загружена модель: ${json.filename}`);
                    } else if (this.live2dUploadStatus) {
                        this.live2dUploadStatus.textContent = `Ошибка: ${json.detail || 'Не удалось загрузить модель'}`;
                    }
                } catch (err) {
                    if (this.live2dUploadStatus) {
                        this.live2dUploadStatus.textContent = `Ошибка загрузки: ${err.message}`;
                    }
                }
                e.target.value = '';
            }
        });

        // Upload Live2D Folder
        document.getElementById('btn-upload-live2d-folder')?.addEventListener('click', async () => {
            if (this.live2dUploadStatus) {
                this.live2dUploadStatus.style.display = 'block';
                this.live2dUploadStatus.textContent = 'Выберите папку с моделью Live2D в открывшемся окне Windows...';
            }
            try {
                const res = await fetch('/api/models/pick_folder', { method: 'POST' });
                const json = await res.json();
                if (json.cancelled) {
                    if (this.live2dUploadStatus) {
                        this.live2dUploadStatus.style.display = 'none';
                    }
                    return;
                }
                if (json.success) {
                    if (this.live2dUploadStatus) {
                        this.live2dUploadStatus.textContent = `Модель Live2D успешно установлена и включена: ${json.filename} (${json.size_mb} MB)`;
                    }
                    this.showToast('Папка Live2D установлена');
                } else if (this.live2dUploadStatus) {
                    this.live2dUploadStatus.textContent = `Ошибка: ${json.detail || 'В папке не найден файл .model3.json или .model.json'}`;
                }
            } catch (_) {
                this.live2dFolderInput?.click();
            }
        });

        this.live2dFolderInput?.addEventListener('change', async (e) => {
            const fileList = Array.from(e.target.files || []);
            if (fileList.length === 0) return;

            if (this.live2dUploadStatus) {
                this.live2dUploadStatus.style.display = 'block';
                this.live2dUploadStatus.textContent = `Копирование папки Live2D (${fileList.length} файлов)...`;
            }

            const formData = new FormData();
            fileList.forEach((file) => {
                const relPath = file.webkitRelativePath || file.name;
                formData.append('files', file);
                formData.append('paths', relPath);
            });

            try {
                const res = await fetch('/api/models/upload_folder', { method: 'POST', body: formData });
                const json = await res.json();
                if (json.success) {
                    if (this.live2dUploadStatus) {
                        this.live2dUploadStatus.textContent = `Модель Live2D успешно установлена и включена: ${json.filename}`;
                    }
                    this.showToast('Папка Live2D установлена');
                } else if (this.live2dUploadStatus) {
                    this.live2dUploadStatus.textContent = `Ошибка: ${json.detail || 'В папке не найден .model3.json или .model.json'}`;
                }
            } catch (err) {
                if (this.live2dUploadStatus) {
                    this.live2dUploadStatus.textContent = `Ошибка загрузки папки: ${err.message}`;
                }
            }
            e.target.value = '';
        });

        // Open data/models directory in Windows Explorer
        document.getElementById('btn-open-models-dir')?.addEventListener('click', async () => {
            try {
                await fetch('/api/models/open_dir', { method: 'POST' });
                setTimeout(async () => {
                    const r = await fetch('/api/models');
                    const d = await r.json();
                    if (d.success && Array.isArray(d.models)) {
                        this._renderModelGallery(d.models, this.activeModel);
                    }
                }, 2500);
            } catch (_) {}
        });

        // Audio Output Device Change (Headphones / Speakers)
        this.selectOutputDevice?.addEventListener('change', async (e) => {
            const val = e.target.value;
            try {
                await fetch('/api/audio/devices', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ output_device: val })
                });
                const label = e.target.options[e.target.selectedIndex]?.text || val;
                this.showToast(`Вывод звука: ${label}`);
            } catch (_) {}
        });

        // Audio Input Device Change (Microphone)
        this.selectInputDevice?.addEventListener('change', async (e) => {
            const val = parseInt(e.target.value, 10);
            try {
                await fetch('/api/audio/devices', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ input_device_index: isNaN(val) ? -1 : val })
                });
                const label = e.target.options[e.target.selectedIndex]?.text || val;
                this.showToast(`Микрофон: ${label}`);
            } catch (_) {}
        });

        // Voice Profile Auto-Save
        this.selectVoice?.addEventListener('change', async () => {
            await this._autoSaveLLMSelection(true);
            const label = this.selectVoice.options[this.selectVoice.selectedIndex]?.text || this.selectVoice.value;
            this.showToast(`Голос Евы: ${label}`);
        });

        // ElevenLabs Preset & Key Auto-Save
        this.elevenPreset?.addEventListener('change', async (e) => {
            if (e.target.value !== 'custom' && this.elevenVoiceInput) {
                this.elevenVoiceInput.value = e.target.value;
            }
            await this._autoSaveLLMSelection(true);
        });
        this.elevenVoiceInput?.addEventListener('change', async () => {
            await this._autoSaveLLMSelection(true);
        });
        this.elevenKeyInput?.addEventListener('change', async () => {
            await this._autoSaveLLMSelection(true);
            this.showToast('Ключ ElevenLabs сохранён');
        });

        // Test Voice + Equalizer
        document.getElementById('btn-test-voice-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('btn-test-voice-btn');
            if (btn) btn.textContent = 'Звучит...';
            try {
                await this.saveVoiceEq();
                await this._autoSaveLLMSelection(true);
                const fd = new FormData();
                fd.append('profile', this.selectVoice.value);
                fd.append('eleven_voice_id', this.elevenVoiceInput.value.trim() || 'cgSgspJ2msm6clMCkdW9');
                fd.append('eleven_key', this.elevenKeyInput.value.trim());
                await fetch('/api/voice/test', { method: 'POST', body: fd });
                this.showToast('Тестовая фраза озвучена в наушники / динамики');
            } catch (_) {}
            if (btn) btn.textContent = '▶ Проверить звук';
        });

        // Save All Settings
        document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
            await this.saveVoiceEq();
            await this._autoSaveLLMSelection(true);
            this.showToast('Все настройки успешно сохранены');
        });
    }

    _populateAudioDevices(outputDevs, inputDevs, activeOutput = 'auto', activeInput = -1) {
        if (this.selectOutputDevice) {
            this.selectOutputDevice.innerHTML = '';
            const autoOpt = document.createElement('option');
            autoOpt.value = 'auto';
            autoOpt.textContent = 'Авто: Все активные (Наушники + Динамики)';
            this.selectOutputDevice.appendChild(autoOpt);

            (outputDevs || []).forEach((dev) => {
                const opt = document.createElement('option');
                opt.value = String(dev.index);
                opt.textContent = dev.name;
                this.selectOutputDevice.appendChild(opt);
            });
            const targetOut = activeOutput === null || activeOutput === undefined || activeOutput === -1 ? 'auto' : String(activeOutput);
            const hasOut = Array.from(this.selectOutputDevice.options).some((o) => o.value === targetOut);
            this.selectOutputDevice.value = hasOut ? targetOut : 'auto';
        }

        if (this.selectInputDevice) {
            this.selectInputDevice.innerHTML = '';
            const defOpt = document.createElement('option');
            defOpt.value = '-1';
            defOpt.textContent = 'По умолчанию (Системный микрофон)';
            this.selectInputDevice.appendChild(defOpt);

            (inputDevs || []).forEach((dev) => {
                const opt = document.createElement('option');
                opt.value = String(dev.index);
                opt.textContent = dev.name;
                this.selectInputDevice.appendChild(opt);
            });
            const targetIn = activeInput === null || activeInput === undefined ? '-1' : String(activeInput);
            const hasIn = Array.from(this.selectInputDevice.options).some((o) => o.value === targetIn);
            this.selectInputDevice.value = hasIn ? targetIn : '-1';
        }
    }

    async _autoSaveLLMSelection(includeVoice = false) {
        const prov = this.selectLLMProvider?.value || 'ollama';
        const apiBase = this.llmBaseInput?.value.trim() || '';
        const apiKey = this.llmKeyInput?.value.trim() || '';
        const modelName = this.selectLLMModel?.value || 'qwen3:4b';

        if (!this.providersConfig[prov]) this.providersConfig[prov] = {};
        this.providersConfig[prov].api_base = apiBase;
        this.providersConfig[prov].api_key = apiKey;
        this.providersConfig[prov].model = modelName;

        const payload = {
            'llm_provider': prov,
            'ai_mode': this.selectAiMode?.value || 'conversational',
            [`providers.${prov}.api_base`]: apiBase,
            [`providers.${prov}.api_key`]: apiKey,
            [`providers.${prov}.model`]: modelName,
            [`providers.${prov}.vision_model`]: modelName
        };

        if (includeVoice) {
            const voiceProfile = this.selectVoice?.value || 'aoede';
            const elevenKey = this.elevenKeyInput?.value.trim() || '';
            const elevenVid = this.elevenVoiceInput?.value.trim() || 'cgSgspJ2msm6clMCkdW9';
            payload['audio.voice_profile'] = voiceProfile;
            payload['audio.elevenlabs.api_key'] = elevenKey;
            payload['audio.elevenlabs.voice_id'] = elevenVid;
            payload['audio.elevenlabs_api_key'] = elevenKey;
            payload['audio.elevenlabs_voice_id'] = elevenVid;
            if (this.selectVrmModel?.value) {
                payload['vrm.active_model'] = this.selectVrmModel.value;
            }
        }

        try {
            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            this._updateTelemetryBadges();
        } catch (err) {
            console.error('Save error:', err);
        }
    }

    _updateVoiceEqUI(eq) {
        if (!eq || typeof eq !== 'object') return;
        const vol = Math.max(0, Math.min(150, Math.round(Number(eq.volume ?? this.voiceEq.volume ?? 100))));
        const pitch = Math.max(-12, Math.min(12, Math.round(Number(eq.pitch ?? this.voiceEq.pitch ?? 0))));
        const speed = Math.max(0.7, Math.min(1.4, Number(eq.speed ?? this.voiceEq.speed ?? 1.0)));
        const bass = Math.max(-12, Math.min(12, Math.round(Number(eq.bass ?? this.voiceEq.bass ?? 0))));
        const treble = Math.max(-12, Math.min(12, Math.round(Number(eq.treble ?? this.voiceEq.treble ?? 0))));

        this.voiceEq = { pitch, speed, bass, treble, volume: vol };

        if (this.eqVolume) this.eqVolume.value = String(vol);
        if (this.headerEvaVolume) this.headerEvaVolume.value = String(vol);
        if (this.eqPitch) this.eqPitch.value = String(pitch);
        if (this.eqSpeed) this.eqSpeed.value = String(speed);
        if (this.eqBass) this.eqBass.value = String(bass);
        if (this.eqTreble) this.eqTreble.value = String(treble);

        this._refreshEqBadges();
    }

    _refreshEqBadges() {
        const vol = Math.max(0, Math.min(150, Math.round(Number(this.eqVolume?.value ?? this.headerEvaVolume?.value ?? this.voiceEq.volume ?? 100))));
        const pitch = Math.max(-12, Math.min(12, Math.round(Number(this.eqPitch?.value ?? this.voiceEq.pitch ?? 0))));
        const speed = Math.max(0.7, Math.min(1.4, Number(this.eqSpeed?.value ?? this.voiceEq.speed ?? 1.0)));
        const bass = Math.max(-12, Math.min(12, Math.round(Number(this.eqBass?.value ?? this.voiceEq.bass ?? 0))));
        const treble = Math.max(-12, Math.min(12, Math.round(Number(this.eqTreble?.value ?? this.voiceEq.treble ?? 0))));

        this.voiceEq = { pitch, speed, bass, treble, volume: vol };

        if (this.eqVolumeVal) this.eqVolumeVal.textContent = `${vol}%`;
        if (this.headerEvaVolumeVal) this.headerEvaVolumeVal.textContent = `${vol}%`;
        if (this.eqPitchVal) this.eqPitchVal.textContent = `${pitch > 0 ? '+' : ''}${pitch} пт`;
        if (this.eqSpeedVal) this.eqSpeedVal.textContent = `${speed.toFixed(2)}x`;
        if (this.eqBassVal) this.eqBassVal.textContent = `${bass > 0 ? '+' : ''}${bass} дБ`;
        if (this.eqTrebleVal) this.eqTrebleVal.textContent = `${treble > 0 ? '+' : ''}${treble} дБ`;
    }

    async saveVoiceEq() {
        this._refreshEqBadges();
        try {
            const res = await fetch('/api/voice/eq', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.voiceEq)
            });
            if (res.ok) {
                const data = await res.json();
                if (data.eq) {
                    this.voiceEq = data.eq;
                }
            }
        } catch (err) {
            console.warn('Voice EQ save error:', err);
        }
    }

    _renderCustomCommands(commands) {
        this.customCommands = Array.isArray(commands) ? commands : [];
        if (!this.customCommandsList) return;
        this.customCommandsList.innerHTML = '';
        this.customCommands.forEach((cmd) => {
            const item = document.createElement('div');
            item.className = 'custom-cmd-item';
            item.textContent = `${cmd.trigger || ''} -> ${cmd.target || ''}`;
            this.customCommandsList.appendChild(item);
        });
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.evaControl = new EVAControlCenter();
});
