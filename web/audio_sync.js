/**
 * AIRI-Class Real-Time Audio Lip-Sync, Voice Equalizer & Spectrum Visualizer Engine
 * Web Audio API Frequency Analysis mapped to VRM/Live2D BlendShape Visemes:
 * - Low-Shelf Bass Filter (200 Hz) + High-Shelf Treble Filter (3500 Hz)
 * - Low Frequencies (300-700 Hz) -> 'oh' / 'ou'
 * - Mid Frequencies (700-2200 Hz) -> 'aa'
 * - High Frequencies (>2200 Hz) -> 'ih' / 'ee'
 */

export class AudioSyncEngine {
    constructor(vrmViewer, visualizerCanvas = null) {
        this.vrmViewer = vrmViewer;
        this.visualizerCanvas = visualizerCanvas;
        this.ctx = null;
        this.analyser = null;
        this.bassFilter = null;
        this.trebleFilter = null;
        this.gainNode = null;
        this.source = null;
        this.currentAudio = null;
        this.isPlaying = false;

        // Equalizer & Volume state
        this.eq = { pitch: 0, speed: 1.0, bass: 0, treble: 0, volume: 100 };

        // Smoothing parameters
        this.smoothedMouthOpen = 0;
        this.visemes = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

        this._initAudioContext();
    }

    _initAudioContext() {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) {
            this.ctx = new AudioCtx({ latencyHint: 'interactive', sampleRate: 44100 });

            this.bassFilter = this.ctx.createBiquadFilter();
            this.bassFilter.type = 'lowshelf';
            this.bassFilter.frequency.value = 200;
            this.bassFilter.gain.value = this.eq.bass || 0;

            this.trebleFilter = this.ctx.createBiquadFilter();
            this.trebleFilter.type = 'highshelf';
            this.trebleFilter.frequency.value = 3500;
            this.trebleFilter.gain.value = this.eq.treble || 0;

            this.analyser = this.ctx.createAnalyser();
            this.analyser.fftSize = 512;
            this.analyser.smoothingTimeConstant = 0.65;

            this.gainNode = this.ctx.createGain();
            const volRatio = Math.max(0, Math.min(1.5, (this.eq.volume ?? 100) / 100.0));
            this.gainNode.gain.value = volRatio;

            this.bassFilter.connect(this.trebleFilter);
            this.trebleFilter.connect(this.analyser);
            this.analyser.connect(this.gainNode);
            this.gainNode.connect(this.ctx.destination);

            this.bufferLength = this.analyser.frequencyBinCount;
            this.dataArray = new Uint8Array(this.bufferLength);
        }
    }

    setEqualizer(eqSettings) {
        if (!eqSettings || typeof eqSettings !== 'object') return;
        const vol = Number(eqSettings.volume ?? this.eq.volume ?? 100);
        this.eq = {
            pitch: Number(eqSettings.pitch ?? this.eq.pitch ?? 0),
            speed: Number(eqSettings.speed ?? this.eq.speed ?? 1.0),
            bass: Number(eqSettings.bass ?? this.eq.bass ?? 0),
            treble: Number(eqSettings.treble ?? this.eq.treble ?? 0),
            volume: Math.max(0, Math.min(150, isNaN(vol) ? 100 : vol))
        };
        if (this.bassFilter) {
            this.bassFilter.gain.value = this.eq.bass;
        }
        if (this.trebleFilter) {
            this.trebleFilter.gain.value = this.eq.treble;
        }
        if (this.gainNode) {
            this.gainNode.gain.value = Math.max(0, Math.min(1.5, this.eq.volume / 100.0));
        }
    }

    /**
     * Plays base64 MP3/WAV audio with real-time lip sync and equalizer filters
     */
    async playAudioBase64(base64Data, onEndCallback = null, eqOverride = null, mutedPlayback = false) {
        if (!this.ctx) this._initAudioContext();
        if (this.ctx.state === 'suspended') {
            try { await this.ctx.resume(); } catch (_) {}
        }
        if (eqOverride) {
            this.setEqualizer(eqOverride);
        }
        if (this.gainNode) {
            this.gainNode.gain.value = mutedPlayback
                ? 0.0
                : Math.max(0, Math.min(1.5, (this.eq.volume ?? 100) / 100.0));
        }

        // Stop previous audio and disconnect previous source node
        this.stop();

        const binary = atob(base64Data);
        const arrayBuffer = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            arrayBuffer[i] = binary.charCodeAt(i);
        }

        const blob = new Blob([arrayBuffer.buffer], { type: 'audio/mpeg' });
        const url = URL.createObjectURL(blob);
        this._currentObjectUrl = url;

        this.currentAudio = new Audio(url);
        this.currentAudio.crossOrigin = 'anonymous';
        this.currentAudio.preload = 'auto';

        this.source = this.ctx.createMediaElementSource(this.currentAudio);
        this.source.connect(this.bassFilter || this.analyser);

        this.isPlaying = true;
        this._startAnalysisLoop();

        this.currentAudio.onended = () => {
            this.isPlaying = false;
            this._cleanupSource();
            this._resetVisemes();
            if (onEndCallback) onEndCallback();
        };

        this.currentAudio.onerror = (e) => {
            console.error('Audio playback error:', e);
            this.isPlaying = false;
            this._cleanupSource();
            this._resetVisemes();
        };

        try {
            await this.currentAudio.play();
        } catch (_) {}
    }

    _cleanupSource() {
        if (this.source) {
            try { this.source.disconnect(); } catch (_) {}
            this.source = null;
        }
        if (this._currentObjectUrl) {
            try { URL.revokeObjectURL(this._currentObjectUrl); } catch (_) {}
            this._currentObjectUrl = null;
        }
    }

    stop() {
        if (this.currentAudio) {
            try {
                this.currentAudio.pause();
                this.currentAudio.currentTime = 0;
            } catch (_) {}
            this.currentAudio = null;
        }
        this._cleanupSource();
        this.isPlaying = false;
        this._resetVisemes();
    }

    _resetVisemes() {
        this.visemes = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
        if (this.vrmViewer) {
            this.vrmViewer.setVisemes(this.visemes);
        }
    }

    _startAnalysisLoop() {
        if (!this.isPlaying) return;

        this.analyser.getByteFrequencyData(this.dataArray);

        // 1. Calculate Frequency Bands
        // Low: Bins 2 to 14 (~120Hz to 850Hz)
        let lowSum = 0;
        for (let i = 2; i <= 14; i++) lowSum += this.dataArray[i];
        const lowAvg = lowSum / 13;

        // Mid: Bins 15 to 45 (~900Hz to 2800Hz)
        let midSum = 0;
        for (let i = 15; i <= 45; i++) midSum += this.dataArray[i];
        const midAvg = midSum / 31;

        // High: Bins 46 to 100 (~2850Hz to 6200Hz)
        let highSum = 0;
        for (let i = 46; i <= 100; i++) highSum += this.dataArray[i];
        const highAvg = highSum / 55;

        // Total volume
        const totalVolume = (lowAvg * 0.4 + midAvg * 0.45 + highAvg * 0.15) / 255.0;

        // Apply noise gate threshold
        if (totalVolume > 0.04) {
            this.smoothedMouthOpen = Math.min(1.0, totalVolume * 1.85);

            const sumFormants = lowAvg + midAvg + highAvg + 0.001;
            const rLow = lowAvg / sumFormants;
            const rMid = midAvg / sumFormants;
            const rHigh = highAvg / sumFormants;

            this.visemes = {
                aa: this.smoothedMouthOpen * (rMid * 1.2),
                oh: this.smoothedMouthOpen * (rLow * 0.9),
                ou: this.smoothedMouthOpen * (rLow * 0.5),
                ih: this.smoothedMouthOpen * (rHigh * 0.8),
                ee: this.smoothedMouthOpen * (rHigh * 0.6)
            };
        } else {
            this.smoothedMouthOpen = Math.max(0, this.smoothedMouthOpen - 0.15);
            this.visemes = {
                aa: this.smoothedMouthOpen * 0.5,
                oh: 0,
                ou: 0,
                ih: 0,
                ee: 0
            };
        }

        if (this.vrmViewer) {
            this.vrmViewer.setVisemes(this.visemes);
        }

        if (this.visualizerCanvas) {
            this._drawVisualizer();
        }

        if (this.isPlaying) {
            requestAnimationFrame(() => this._startAnalysisLoop());
        }
    }

    _drawVisualizer() {
        const cvs = this.visualizerCanvas;
        const ctx = cvs.getContext('2d');
        const w = cvs.width;
        const h = cvs.height;

        ctx.clearRect(0, 0, w, h);

        const barCount = 32;
        const barWidth = (w / barCount) - 2;
        const step = Math.floor(this.bufferLength / barCount / 2);

        for (let i = 0; i < barCount; i++) {
            const val = this.dataArray[i * step] || 0;
            const barHeight = (val / 255.0) * (h - 6);

            const grad = ctx.createLinearGradient(0, h, 0, h - barHeight);
            grad.addColorStop(0, '#6366f1');
            grad.addColorStop(1, '#10b981');

            ctx.fillStyle = grad;
            ctx.fillRect(i * (barWidth + 2), h - barHeight, barWidth, barHeight);
        }
    }
}
