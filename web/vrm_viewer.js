/**
 * EVA AI — 3D VRM & 2D Live2D Desktop Engine (v5.0)
 * Features:
 * - Unrestricted 360-degree OrbitControls (full vertical & horizontal rotation, zoom, pan)
 * - Natural Humanoid Procedural Idle System (contrapposto weight-shifting, relaxed bent elbows/wrists,
 *   autonomous micro-gestures, eye saccades, and expressive conversational hand movements)
 * - Full Live2D Cubism 2.1 & Cubism 4 Parameter Control (poses, arm raising, leaning, dancing, head tilts, lip-sync)
 * - 100% Transparent WebGL Viewport for Desktop Companion Mode
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

export class VRMViewer {
    constructor(containerEl) {
        this.container = containerEl;
        this.mode = 'vrm'; // 'vrm' | 'live2d'
        this.currentVrm = null;
        this.currentLive2D = null;
        this._pixiApp = null;
        this._live2dCanvas = null;
        this._live2dBaseScale = 1.0;
        this._live2dZoom = 1.0;
        this._live2dOffset = { x: 0, y: 0 };
        this._live2dAnimOffset = { x: 0, y: 0, rot: 0, scaleMul: 1.0 };
        this.clock = new THREE.Clock();

        // Lip-sync viseme state (0.0 -> 1.0)
        this.visemes = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
        this.targetVisemes = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

        // Blinking & Eye Saccade state
        this.blinkTimer = 0;
        this.nextBlinkInterval = 3.2;
        this.isBlinking = false;
        this.eyeSaccadeTimer = 0;
        this.eyeTarget = { x: 0, y: 0 };
        this.eyeCurrent = { x: 0, y: 0 };

        // Emotion & Pose state
        this.currentEmotion = 'neutral';
        this.currentPose = 'stand';
        this.poseTimer = 0;
        this.spinAngle = 0;
        this.isSpinning = false;
        this.jumpTimer = 0;
        this.isJumping = false;

        // Smooth camera interpolation state
        this._camAnim = null;

        // Legacy layer stubs for compatibility
        this.layers = { top: true, bottom: true, shoes: true, accessories: true, underwear: true, nsfw: false };

        this._initScene();
        this._initLive2DInteractions();
        this._animate();
    }

    _initScene() {
        const width = this.container.clientWidth || window.innerWidth;
        const height = this.container.clientHeight || window.innerHeight;

        this.scene = new THREE.Scene();

        this.camera = new THREE.PerspectiveCamera(28.0, width / height, 0.05, 50.0);
        this.camera.position.set(0, 1.25, 2.2);

        this.renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
            powerPreference: 'high-performance',
            premultipliedAlpha: false
        });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.0));
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.08;
        this.renderer.setClearColor(0x000000, 0);

        this.container.innerHTML = '';
        this.container.appendChild(this.renderer.domElement);

        // Dedicated overlay canvas for Live2D
        this._live2dCanvas = document.createElement('canvas');
        this._live2dCanvas.id = 'live2d-canvas';
        this._live2dCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:none;background:transparent;';
        this.container.appendChild(this._live2dCanvas);

        // Unrestricted 360-degree OrbitControls
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.screenSpacePanning = true;
        this.controls.target.set(0, 1.15, 0);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.07;
        this.controls.rotateSpeed = 0.85;
        this.controls.zoomSpeed = 1.1;
        this.controls.panSpeed = 0.85;
        this.controls.minDistance = 0.22;
        this.controls.maxDistance = 9.0;
        this.controls.minPolarAngle = 0.0;
        this.controls.maxPolarAngle = Math.PI;
        this.controls.minAzimuthAngle = -Infinity;
        this.controls.maxAzimuthAngle = Infinity;
        this.controls.update();

        // Balanced Studio Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.92);
        this.scene.add(ambientLight);

        const keyLight = new THREE.DirectionalLight(0xfffaf5, 1.35);
        keyLight.position.set(1.4, 2.4, 2.2);
        this.scene.add(keyLight);

        const fillLight = new THREE.DirectionalLight(0xeef2f6, 0.55);
        fillLight.position.set(-1.6, 1.4, 1.2);
        this.scene.add(fillLight);

        const rimLight = new THREE.DirectionalLight(0xffffff, 0.45);
        rimLight.position.set(0, 2.2, -2.0);
        this.scene.add(rimLight);

        window.addEventListener('resize', () => this._onResize());
    }

    _initLive2DInteractions() {
        let dragging = false;
        let lastX = 0;
        let lastY = 0;

        this._live2dCanvas.addEventListener('pointerdown', (e) => {
            dragging = true;
            lastX = e.clientX;
            lastY = e.clientY;
            this._live2dCanvas.setPointerCapture(e.pointerId);
            if (this.currentLive2D) {
                try { this.currentLive2D.tap(e.clientX, e.clientY); } catch (_) {}
            }
        });

        this._live2dCanvas.addEventListener('pointermove', (e) => {
            if (this.currentLive2D && this.currentPose === 'stand') {
                try { this.currentLive2D.focus(e.clientX, e.clientY); } catch (_) {}
            }
            if (!dragging || !this.currentLive2D) return;
            const dx = e.clientX - lastX;
            const dy = e.clientY - lastY;
            lastX = e.clientX;
            lastY = e.clientY;
            this._live2dOffset.x += dx;
            this._live2dOffset.y += dy;
            this._updateLive2DTransform();
        });

        const endDrag = (e) => {
            dragging = false;
            try { this._live2dCanvas.releasePointerCapture(e.pointerId); } catch (_) {}
        };
        this._live2dCanvas.addEventListener('pointerup', endDrag);
        this._live2dCanvas.addEventListener('pointercancel', endDrag);

        this._live2dCanvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            if (!this.currentLive2D) return;
            const factor = e.deltaY < 0 ? 1.09 : 0.91;
            this._live2dZoom = Math.max(0.25, Math.min(4.5, this._live2dZoom * factor));
            this._updateLive2DTransform();
        }, { passive: false });
    }

    _fitLive2DModel(model) {
        const width = this.container.clientWidth || window.innerWidth;
        const height = this.container.clientHeight || window.innerHeight;
        const mw = model.internalModel?.width || model.width || 1000;
        const mh = model.internalModel?.height || model.height || 1400;

        this._live2dBaseScale = Math.min((width * 0.88) / mw, (height * 0.92) / mh);
        this._live2dZoom = 1.0;
        this._live2dOffset = { x: 0, y: 0 };
        this._live2dAnimOffset = { x: 0, y: 0, rot: 0, scaleMul: 1.0 };
        model.anchor.set(0.5, 0.5);
        this._updateLive2DTransform();
    }

    _updateLive2DTransform() {
        if (!this.currentLive2D) return;
        const width = this.container.clientWidth || window.innerWidth;
        const height = this.container.clientHeight || window.innerHeight;
        const s = this._live2dBaseScale * this._live2dZoom * (this._live2dAnimOffset.scaleMul || 1.0);
        this.currentLive2D.scale.set(s, s);
        this.currentLive2D.rotation = this._live2dAnimOffset.rot || 0;
        this.currentLive2D.position.set(
            width * 0.5 + this._live2dOffset.x + (this._live2dAnimOffset.x || 0),
            height * 0.52 + this._live2dOffset.y + (this._live2dAnimOffset.y || 0)
        );
    }

    _onResize() {
        if (!this.container) return;
        const width = this.container.clientWidth || window.innerWidth;
        const height = this.container.clientHeight || window.innerHeight;
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
        if (this._pixiApp && this._pixiApp.renderer) {
            this._pixiApp.renderer.resize(width, height);
            if (this.currentLive2D) {
                const mw = this.currentLive2D.internalModel?.width || 1000;
                const mh = this.currentLive2D.internalModel?.height || 1400;
                this._live2dBaseScale = Math.min((width * 0.88) / mw, (height * 0.92) / mh);
                this._updateLive2DTransform();
            }
        }
    }

    async loadModel(url) {
        const cleanUrl = (url || '').split('?')[0];
        const lower = cleanUrl.toLowerCase();

        if (lower.endsWith('.model3.json') || lower.endsWith('.model.json')) {
            return this._loadLive2DModel(cleanUrl);
        }

        this.mode = 'vrm';
        if (this._live2dCanvas) this._live2dCanvas.style.display = 'none';
        if (this.renderer?.domElement) this.renderer.domElement.style.display = 'block';

        const vrmUrl = url.includes('?') ? `${url}&v=${Date.now()}` : `${url}?v=${Date.now()}`;

        return new Promise((resolve, reject) => {
            const loader = new GLTFLoader();
            loader.register((parser) => new VRMLoaderPlugin(parser));

            loader.load(
                vrmUrl,
                (gltf) => {
                    const vrm = gltf.userData.vrm;
                    if (!vrm) {
                        reject(new Error('No VRM instance in file'));
                        return;
                    }

                    if (this.currentVrm) {
                        this.scene.remove(this.currentVrm.scene);
                        VRMUtils.deepDispose(this.currentVrm.scene);
                    }

                    VRMUtils.removeUnnecessaryVertices(gltf.scene);
                    VRMUtils.removeUnnecessaryJoints(gltf.scene);
                    VRMUtils.rotateVRM0(vrm);

                    vrm.scene.traverse((obj) => {
                        if (obj.isMesh) {
                            obj.frustumCulled = false;
                            obj.visible = true;
                        }
                    });

                    this.currentVrm = vrm;
                    this._baseHipsY = undefined;
                    this.scene.add(vrm.scene);

                    this.setPose('stand');
                    this._autoFrameVRM();

                    resolve(vrm);
                },
                undefined,
                (err) => reject(err)
            );
        });
    }

    _autoFrameVRM() {
        if (!this.currentVrm?.humanoid) return;
        this.currentVrm.scene.updateMatrixWorld(true);
        const headNode = this.currentVrm.humanoid.getNormalizedBoneNode('head');
        const hipsNode = this.currentVrm.humanoid.getNormalizedBoneNode('hips');
        if (headNode && hipsNode) {
            const headPos = new THREE.Vector3();
            const hipsPos = new THREE.Vector3();
            headNode.getWorldPosition(headPos);
            hipsNode.getWorldPosition(hipsPos);
            const midY = (headPos.y + hipsPos.y) * 0.52;
            this.controls.target.set(0, midY, 0);
            this.camera.position.set(0, midY + 0.10, 2.05);
            this.controls.update();
        }
    }

    async _loadLive2DModel(cleanUrl) {
        if (!window.PIXI || !window.PIXI.live2d) {
            throw new Error('Live2D runtime is not loaded');
        }

        this.mode = 'live2d';
        if (this.renderer?.domElement) this.renderer.domElement.style.display = 'none';
        if (this._live2dCanvas) this._live2dCanvas.style.display = 'block';

        const width = this.container.clientWidth || window.innerWidth;
        const height = this.container.clientHeight || window.innerHeight;

        if (!this._pixiApp) {
            this._pixiApp = new window.PIXI.Application({
                view: this._live2dCanvas,
                width: width,
                height: height,
                backgroundAlpha: 0,
                transparent: true,
                antialias: true,
                autoDensity: true,
                resolution: Math.min(window.devicePixelRatio || 1, 2)
            });
        }

        if (this.currentLive2D) {
            this._pixiApp.stage.removeChild(this.currentLive2D);
            try { this.currentLive2D.destroy(); } catch (_) {}
            this.currentLive2D = null;
        }

        const model = await window.PIXI.live2d.Live2DModel.from(cleanUrl, {
            autoInteract: false
        });

        this.currentLive2D = model;
        this._pixiApp.stage.addChild(model);
        this._fitLive2DModel(model);

        if (model.internalModel) {
            model.internalModel.on('beforeModelUpdate', () => {
                this._applyLive2DLipSyncAndEmotion();
                this._applyLive2DPoseParameters();
            });
        }

        return model;
    }

    _setLive2DParam(core, id4, id2, val) {
        if (typeof core.setParameterValueById === 'function') {
            try { core.setParameterValueById(id4, val); } catch (_) {}
        }
        if (typeof core.setParamFloat === 'function') {
            try { core.setParamFloat(id2, val); } catch (_) {}
        }
    }

    _applyLive2DLipSyncAndEmotion() {
        const im = this.currentLive2D?.internalModel;
        const core = im?.coreModel;
        if (!core) return;

        const mouthOpen = Math.min(1.0, (this.visemes.aa * 1.15) + (this.visemes.oh * 0.65) + (this.visemes.ih * 0.35));
        const isEmotionHappy = (this.currentEmotion === 'happy' || this.currentEmotion === 'joy' || this.currentEmotion === 'fun');
        const isEmotionShy = (this.currentEmotion === 'shy' || this.currentEmotion === 'blush');

        if (mouthOpen > 0.02) {
            this._setLive2DParam(core, 'ParamMouthOpenY', 'PARAM_MOUTH_OPEN_Y', mouthOpen);
        }
        if (isEmotionHappy) {
            this._setLive2DParam(core, 'ParamMouthForm', 'PARAM_MOUTH_FORM', 1.0);
            this._setLive2DParam(core, 'ParamEyeLSmile', 'PARAM_EYE_L_SMILE', 1.0);
            this._setLive2DParam(core, 'ParamEyeRSmile', 'PARAM_EYE_R_SMILE', 1.0);
        }
        if (isEmotionShy) {
            this._setLive2DParam(core, 'ParamCheek', 'PARAM_CHEEK', 1.0);
        }
    }

    /**
     * Drives Live2D Cubism 2.1 & Cubism 4 skeleton/deformation parameters and container transforms
     * when the user commands poses like 'raise_hand', 'hands_up', 'dance', 'lean', 'sit', 'shy', 'spin', 'jump'.
     */
    _applyLive2DPoseParameters() {
        const im = this.currentLive2D?.internalModel;
        const core = im?.coreModel;
        if (!core) return;

        const t = this.clock.getElapsedTime();
        let pose = this.currentPose;

        if ((pose === 'raise_hand' || pose === 'hands_up' || pose === 'shy') && this.poseTimer > 6.5) {
            pose = 'stand';
            this.currentPose = 'stand';
        }

        // Default subtle idle breathing & sway
        let angleX = Math.sin(t * 1.1) * 5.0;
        let angleY = Math.sin(t * 0.8) * 3.5;
        let angleZ = Math.sin(t * 0.9) * 3.0;
        let bodyX = Math.sin(t * 0.9) * 2.5;
        let bodyZ = Math.sin(t * 0.7) * 2.0;
        let armL = null;
        let armR = null;
        let handWave = 0;

        let targetOffsetX = 0;
        let targetOffsetY = 0;
        let targetRot = 0;
        let targetScale = 1.0;

        if (pose === 'raise_hand') {
            handWave = Math.sin(t * 7.5) * 0.8;
            armR = 1.0;
            angleZ = -8.0 + Math.sin(t * 7.5) * 5.0;
            angleX = 6.0;
            bodyZ = -3.5;
            this._setLive2DParam(core, 'ParamEyeLSmile', 'PARAM_EYE_L_SMILE', 1.0);
            this._setLive2DParam(core, 'ParamEyeRSmile', 'PARAM_EYE_R_SMILE', 1.0);
        } else if (pose === 'hands_up') {
            const stretch = Math.sin(t * 3.0) * 0.2;
            armL = 1.0;
            armR = 1.0;
            angleY = 12.0 + stretch * 10.0;
            targetOffsetY = -14;
        } else if (pose === 'dance') {
            const beat = t * 5.4;
            angleX = Math.sin(beat) * 18.0;
            angleY = Math.abs(Math.cos(beat)) * 10.0 - 4.0;
            angleZ = Math.sin(beat) * 14.0;
            bodyX = Math.sin(beat) * 8.0;
            bodyZ = Math.cos(beat) * 7.0;
            armL = 0.5 + Math.sin(beat) * 0.5;
            armR = 0.5 - Math.sin(beat) * 0.5;
            targetOffsetX = Math.sin(beat) * 18;
            targetOffsetY = Math.abs(Math.sin(beat * 2)) * 14;
            targetRot = Math.sin(beat) * 0.045;
        } else if (pose === 'lean') {
            angleY = -14.0;
            angleZ = 7.0;
            bodyX = 4.0;
            targetScale = 1.18;
            targetOffsetY = 24;
        } else if (pose === 'sit') {
            angleY = -5.0;
            angleZ = 4.0;
            targetOffsetY = 55;
            targetScale = 0.96;
        } else if (pose === 'pose_model') {
            angleX = 12.0;
            angleY = 6.0;
            angleZ = -9.0;
            bodyX = -6.0;
            bodyZ = 5.0;
            armL = 0.65;
        } else if (pose === 'shy') {
            angleX = -10.0;
            angleY = -16.0;
            angleZ = 10.0;
            bodyX = -4.0;
            this._setLive2DParam(core, 'ParamCheek', 'PARAM_CHEEK', 1.0);
        }

        if (this.isJumping) {
            this.jumpTimer += 0.07;
            if (this.jumpTimer < Math.PI) {
                targetOffsetY -= Math.sin(this.jumpTimer) * 75;
            } else {
                this.isJumping = false;
                if (this.currentPose === 'jump') this.currentPose = 'stand';
            }
        }

        if (this.isSpinning) {
            this.spinAngle += 0.1;
            if (this.spinAngle >= Math.PI * 2) {
                this.spinAngle = 0;
                this.isSpinning = false;
                if (this.currentPose === 'spin') this.currentPose = 'stand';
            } else {
                targetOffsetX += Math.sin(this.spinAngle) * 30;
                angleX = Math.sin(this.spinAngle) * 30.0;
                bodyX = Math.sin(this.spinAngle) * 10.0;
            }
        }

        // Apply head and body angles to both Cubism 4 and Cubism 2.1 models
        this._setLive2DParam(core, 'ParamAngleX', 'PARAM_ANGLE_X', angleX);
        this._setLive2DParam(core, 'ParamAngleY', 'PARAM_ANGLE_Y', angleY);
        this._setLive2DParam(core, 'ParamAngleZ', 'PARAM_ANGLE_Z', angleZ);
        this._setLive2DParam(core, 'ParamBodyAngleX', 'PARAM_BODY_ANGLE_X', bodyX);
        this._setLive2DParam(core, 'ParamBodyAngleZ', 'PARAM_BODY_ANGLE_Z', bodyZ);
        this._setLive2DParam(core, 'ParamBreath', 'PARAM_BREATH', (Math.sin(t * 2.2) + 1) * 0.5);

        if (armL !== null) {
            this._setLive2DParam(core, 'ParamArmLA', 'PARAM_ARM_L_A', armL);
            this._setLive2DParam(core, 'ParamArmLB', 'PARAM_ARM_L_B', armL);
        }
        if (armR !== null) {
            this._setLive2DParam(core, 'ParamArmRA', 'PARAM_ARM_R_A', armR);
            this._setLive2DParam(core, 'ParamArmRB', 'PARAM_ARM_R_B', armR);
            this._setLive2DParam(core, 'ParamHandR', 'PARAM_HAND_R', handWave);
            this._setLive2DParam(core, 'ParamHandAngleR', 'PARAM_HAND_ANGLE_R', handWave);
        }

        // Smoothly interpolate Live2D container transform
        this._live2dAnimOffset.x = THREE.MathUtils.lerp(this._live2dAnimOffset.x, targetOffsetX, 0.14);
        this._live2dAnimOffset.y = THREE.MathUtils.lerp(this._live2dAnimOffset.y, targetOffsetY, 0.14);
        this._live2dAnimOffset.rot = THREE.MathUtils.lerp(this._live2dAnimOffset.rot, targetRot, 0.14);
        this._live2dAnimOffset.scaleMul = THREE.MathUtils.lerp(this._live2dAnimOffset.scaleMul, targetScale, 0.14);
        this._updateLive2DTransform();
    }

    // Safe no-op stubs for legacy calls
    setLayer(_layerName, _isVisible) {}
    toggleLayer(_layerName) { return true; }
    getLayers() { return { ...this.layers }; }
    applyLayers() {}
    setOutfit(_outfitName) {}

    setPose(poseName) {
        this.currentPose = poseName;
        this.poseTimer = 0;

        if (this.mode === 'live2d' && this.currentLive2D) {
            try {
                const groups = Object.keys(this.currentLive2D.internalModel?.motionManager?.definitions || {});
                if (groups.length > 0) {
                    const preferred = groups.find((g) => g.toLowerCase().includes('tap') || g.toLowerCase().includes('body')) || groups[0];
                    this.currentLive2D.motion(preferred);
                }
            } catch (_) {}
        }

        if (poseName === 'spin') {
            this.triggerSpin();
        } else if (poseName === 'jump') {
            this.isJumping = true;
            this.jumpTimer = 0;
        } else if (poseName === 'sit') {
            this.setCameraPreset('sit');
        } else if (poseName === 'dance' || poseName === 'pose_model') {
            this.setCameraPreset('waist');
        }
    }

    triggerSpin() {
        this.isSpinning = true;
        this.spinAngle = 0;
    }

    setCameraPreset(preset) {
        if (this.mode === 'live2d' && this.currentLive2D) {
            const zMap = { portrait: 1.55, bust: 1.25, waist: 1.0, sit: 1.05, full: 0.85 };
            const yMap = { portrait: 110, bust: 45, waist: 0, sit: 0, full: -20 };
            this._live2dZoom = zMap[preset] || 1.0;
            this._live2dOffset = { x: 0, y: yMap[preset] || 0 };
            this._updateLive2DTransform();
            return;
        }
        const presets = {
            portrait: { pos: new THREE.Vector3(0, 1.42, 0.85), target: new THREE.Vector3(0, 1.40, 0) },
            bust:     { pos: new THREE.Vector3(0, 1.28, 1.45), target: new THREE.Vector3(0, 1.22, 0) },
            waist:    { pos: new THREE.Vector3(0, 1.12, 2.05), target: new THREE.Vector3(0, 1.05, 0) },
            sit:      { pos: new THREE.Vector3(0, 0.95, 1.85), target: new THREE.Vector3(0, 0.82, 0) },
            full:     { pos: new THREE.Vector3(0, 0.95, 2.95), target: new THREE.Vector3(0, 0.88, 0) }
        };
        const p = presets[preset] || presets.waist;
        this._camAnim = {
            startPos: this.camera.position.clone(),
            endPos: p.pos,
            startTarget: this.controls.target.clone(),
            endTarget: p.target,
            progress: 0
        };
    }

    setVisemes(weights) {
        Object.assign(this.targetVisemes, weights);
    }

    setEmotion(emotionName) {
        this.currentEmotion = emotionName;
        if (this.mode === 'live2d' && this.currentLive2D) {
            try {
                if (emotionName && emotionName !== 'neutral') {
                    this.currentLive2D.expression(emotionName);
                }
            } catch (_) {}
        }
        if (!this.currentVrm?.expressionManager) return;
        const em = this.currentVrm.expressionManager;

        ['happy', 'angry', 'sad', 'relaxed', 'surprised', 'joy', 'fun', 'sorrow'].forEach((name) => {
            try { em.setValue(name, 0.0); } catch (_) {}
        });

        if (emotionName && emotionName !== 'neutral') {
            try { em.setValue(emotionName, 0.85); } catch (_) {}
            if (emotionName === 'joy' || emotionName === 'happy') {
                try { em.setValue('happy', 0.85); } catch (_) {}
                try { em.setValue('joy', 0.85); } catch (_) {}
            }
        }
    }

    _lerpBoneEuler(hum, boneName, tx, ty, tz, damp = 0.11) {
        const node = hum.getNormalizedBoneNode(boneName);
        if (!node) return;
        node.rotation.x = THREE.MathUtils.lerp(node.rotation.x, tx, damp);
        node.rotation.y = THREE.MathUtils.lerp(node.rotation.y, ty, damp);
        node.rotation.z = THREE.MathUtils.lerp(node.rotation.z, tz, damp);
    }

    _animate() {
        requestAnimationFrame(() => this._animate());

        const delta = Math.min(this.clock.getDelta(), 0.1);
        const elapsed = this.clock.getElapsedTime();
        this.poseTimer += delta;

        // Always interpolate lip-sync visemes for both 3D VRM and 2D Live2D
        this._updateLipSync(delta);

        if (this.mode === 'live2d') {
            return;
        }

        if (this._camAnim) {
            this._camAnim.progress = Math.min(1.0, this._camAnim.progress + delta * 3.2);
            const ease = 1 - Math.pow(1 - this._camAnim.progress, 3);
            this.camera.position.lerpVectors(this._camAnim.startPos, this._camAnim.endPos, ease);
            this.controls.target.lerpVectors(this._camAnim.startTarget, this._camAnim.endTarget, ease);
            if (this._camAnim.progress >= 1.0) this._camAnim = null;
        }

        if (this.currentVrm) {
            this._updateSkeletonPose(elapsed, delta);
            this._updateEyeGazeAndBlinking(delta);
            this.currentVrm.update(delta);
        }

        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    _updateSkeletonPose(t, delta) {
        const hum = this.currentVrm.humanoid;
        if (!hum) return;

        const hipsNode = hum.getNormalizedBoneNode('hips');
        const breath = Math.sin(t * 2.05) * 0.026;
        const weightShift = Math.sin(t * 0.52) * 0.042 + Math.sin(t * 0.23) * 0.024;
        const microSway = Math.cos(t * 0.78) * 0.022;
        const isTalking = this.visemes.aa > 0.05 || this.visemes.oh > 0.05;
        const talkGesture = isTalking ? Math.sin(t * 6.8) * 0.09 : 0;

        // Periodic natural idle micro-variation (every ~12s smoothly shifts subtle hand/head emphasis)
        const idleCycle = (Math.sin(t * 0.32) + 1) * 0.5; // 0.0 -> 1.0

        let targetHipsY = -Math.abs(weightShift) * 0.15;
        let pose = this.currentPose;

        if ((pose === 'raise_hand' || pose === 'hands_up' || pose === 'shy') && this.poseTimer > 6.0) {
            pose = 'stand';
            this.currentPose = 'stand';
        }

        // Lively, natural contrapposto idle stance (no stiff straight-down doll arms!)
        let b = {
            hips:          [0.02, weightShift * 0.85, weightShift * 0.75],
            spine:         [breath * 0.55, -weightShift * 0.45, -weightShift * 0.65],
            chest:         [breath * 1.1, microSway * 0.6, -weightShift * 0.25],
            neck:          [
                Math.sin(t * 0.65) * 0.035 + talkGesture * 0.3,
                Math.sin(t * 0.42) * 0.065,
                Math.sin(t * 0.55) * 0.035 + idleCycle * 0.03
            ],
            head:          [
                talkGesture * 0.55 + Math.cos(t * 0.5) * 0.025,
                Math.sin(t * 0.38) * 0.055,
                Math.sin(t * 0.46) * 0.035
            ],
            leftShoulder:  [0.02, 0.04, -0.07 - breath * 0.3],
            rightShoulder: [0.02, -0.04, 0.07 + breath * 0.3],
            // Relaxed arms slightly forward with natural elbow bend & gentle breathing
            leftUpperArm:  [
                0.18 + idleCycle * 0.08 + talkGesture * 0.9,
                0.14 + Math.sin(t * 0.7) * 0.04,
                -1.02 - breath * 0.45
            ],
            rightUpperArm: [
                0.20 + (1 - idleCycle) * 0.08 - talkGesture * 0.9,
                -0.16 - Math.cos(t * 0.65) * 0.04,
                1.00 + breath * 0.45
            ],
            leftLowerArm:  [
                -0.46 - idleCycle * 0.14 - Math.abs(talkGesture) * 1.6,
                -0.34 - Math.sin(t * 0.8) * 0.06,
                0.08
            ],
            rightLowerArm: [
                -0.52 - (1 - idleCycle) * 0.16 - Math.abs(talkGesture) * 1.6,
                0.38 + Math.cos(t * 0.75) * 0.06,
                -0.08
            ],
            leftHand:      [0.06, -0.08, -0.15 - Math.sin(t * 1.3) * 0.05],
            rightHand:     [0.08, 0.08, 0.15 + Math.cos(t * 1.2) * 0.05],
            // Natural leg stance with alternating knee relaxation during weight shift
            leftUpperLeg:  [Math.max(0, weightShift) * 0.65, -0.04, -0.04 - weightShift * 0.3],
            rightUpperLeg: [Math.max(0, -weightShift) * 0.65, 0.04, 0.04 - weightShift * 0.3],
            leftLowerLeg:  [-Math.max(0, weightShift) * 1.35 - 0.04, 0, 0],
            rightLowerLeg: [-Math.max(0, -weightShift) * 1.35 - 0.04, 0, 0],
            leftFoot:      [Math.max(0, weightShift) * 0.45, -0.05, 0],
            rightFoot:     [Math.max(0, -weightShift) * 0.45, 0.05, 0]
        };

        if (pose === 'sit') {
            targetHipsY = -0.36;
            b.hips = [-0.12, 0, 0];
            b.spine = [0.10, 0, 0];
            b.chest = [0.06 + breath, 0, 0];
            b.leftUpperLeg = [1.38, -0.08, -0.05];
            b.rightUpperLeg = [1.38, 0.08, 0.05];
            b.leftLowerLeg = [-1.42, 0, 0];
            b.rightLowerLeg = [-1.42, 0, 0];
            b.leftFoot = [0.15, 0, 0];
            b.rightFoot = [0.15, 0, 0];
            b.leftUpperArm = [0.32, 0.15, -1.04];
            b.rightUpperArm = [0.32, -0.15, 1.04];
            b.leftLowerArm = [-0.58, -0.35, 0];
            b.rightLowerArm = [-0.58, 0.35, 0];
        } else if (pose === 'raise_hand') {
            const wave = Math.sin(t * 7.5) * 0.26;
            b.rightShoulder = [0, 0, -0.25];
            b.rightUpperArm = [0.15, 0, -0.85];
            b.rightLowerArm = [-0.45, 0, -0.85 + wave];
            b.rightHand = [0, 0, wave * 0.7];
            b.head = [-0.05, -0.08, 0.08];
        } else if (pose === 'hands_up') {
            const stretch = Math.sin(t * 3.0) * 0.06;
            b.spine = [-0.10, 0, 0];
            b.chest = [-0.12 + stretch, 0, 0];
            b.leftShoulder = [0, 0, 0.25];
            b.rightShoulder = [0, 0, -0.25];
            b.leftUpperArm = [0.1, 0, 1.15 + stretch];
            b.rightUpperArm = [0.1, 0, -1.15 - stretch];
            b.leftLowerArm = [-0.25, 0, 0.2];
            b.rightLowerArm = [-0.25, 0, -0.2];
            b.head = [-0.1, 0, 0];
        } else if (pose === 'dance') {
            const beat = t * 5.2;
            const hipSwing = Math.sin(beat) * 0.18;
            const bounce = Math.abs(Math.sin(beat)) * -0.05;
            targetHipsY = bounce;
            b.hips = [0, hipSwing * 0.8, hipSwing];
            b.spine = [0.05, -hipSwing * 0.5, -hipSwing * 0.7];
            b.chest = [Math.sin(beat * 2) * 0.06, hipSwing * 0.4, 0];
            b.head = [Math.sin(beat * 2) * 0.06, -hipSwing * 0.4, Math.sin(beat) * 0.08];
            b.leftUpperArm = [0.35 + Math.sin(beat) * 0.35, 0, -0.65 + Math.cos(beat) * 0.25];
            b.rightUpperArm = [0.35 - Math.sin(beat) * 0.35, 0, 0.65 + Math.cos(beat) * 0.25];
            b.leftLowerArm = [-0.95 + Math.cos(beat) * 0.35, -0.3, 0];
            b.rightLowerArm = [-0.95 - Math.cos(beat) * 0.35, 0.3, 0];
            b.leftUpperLeg = [Math.max(0, Math.sin(beat)) * 0.25, 0, -0.05];
            b.rightUpperLeg = [Math.max(0, -Math.sin(beat)) * 0.25, 0, 0.05];
            b.leftLowerLeg = [-Math.max(0, Math.sin(beat)) * 0.45, 0, 0];
            b.rightLowerLeg = [-Math.max(0, -Math.sin(beat)) * 0.45, 0, 0];
        } else if (pose === 'lean') {
            b.hips = [-0.18, 0, 0];
            b.spine = [0.32, 0, 0];
            b.chest = [0.22 + breath, 0, 0];
            b.neck = [-0.28, 0, 0];
            b.head = [-0.18, 0.06, 0.08];
            b.leftUpperArm = [-0.25, 0, -0.95];
            b.rightUpperArm = [-0.25, 0, 0.95];
            b.leftLowerArm = [-0.55, -0.3, 0];
            b.rightLowerArm = [-0.55, 0.3, 0];
        } else if (pose === 'pose_model') {
            b.hips = [0, 0.18, 0.12];
            b.spine = [-0.06, -0.10, -0.08];
            b.chest = [-0.08 + breath, -0.08, -0.04];
            b.neck = [0, 0.14, 0.06];
            b.head = [0.04, 0.08, -0.06];
            b.leftUpperArm = [0.15, -0.25, -0.78];
            b.leftLowerArm = [-0.95, -0.65, 0];
            b.rightUpperArm = [0.18, -0.12, 1.02];
            b.rightLowerArm = [-0.48, 0.32, 0];
            b.leftUpperLeg = [0.08, 0, -0.06];
            b.rightUpperLeg = [-0.04, 0, 0.08];
            b.leftLowerLeg = [-0.15, 0, 0];
        } else if (pose === 'shy') {
            b.hips = [0, -0.08, 0];
            b.spine = [0.08, 0, 0];
            b.chest = [0.06, 0, 0];
            b.head = [0.18, -0.12, 0.10];
            b.leftUpperArm = [0.45, 0.38, -1.02];
            b.rightUpperArm = [0.45, -0.38, 1.02];
            b.leftLowerArm = [-1.15, -0.45, 0];
            b.rightLowerArm = [-1.15, 0.45, 0];
            b.leftUpperLeg = [0, 0.12, -0.02];
            b.rightUpperLeg = [0, -0.12, 0.02];
        }

        if (this.isJumping) {
            this.jumpTimer += delta * 4.2;
            if (this.jumpTimer < Math.PI) {
                targetHipsY += Math.sin(this.jumpTimer) * 0.28;
                b.leftUpperArm = [0, 0, -0.45];
                b.rightUpperArm = [0, 0, 0.45];
                b.leftLowerLeg = [-0.35, 0, 0];
                b.rightLowerLeg = [-0.35, 0, 0];
            } else {
                this.isJumping = false;
                if (this.currentPose === 'jump') this.currentPose = 'stand';
            }
        }

        const isVRM0 = (this.currentVrm.meta?.metaVersion === '0');
        const s = isVRM0 ? -1 : 1;

        Object.keys(b).forEach((boneName) => {
            const [rx, ry, rz] = b[boneName];
            this._lerpBoneEuler(hum, boneName, rx * s, ry, rz * s, 0.11);
        });

        if (hipsNode) {
            if (this._baseHipsY === undefined) {
                this._baseHipsY = hipsNode.position.y || 0.95;
            }
            hipsNode.position.y = THREE.MathUtils.lerp(
                hipsNode.position.y,
                this._baseHipsY + targetHipsY,
                0.12
            );
        }

        if (this.isSpinning && this.currentVrm.scene) {
            this.spinAngle += delta * 5.2;
            const baseRot = this.currentVrm.meta?.metaVersion === '0' ? Math.PI : 0;
            if (this.spinAngle >= Math.PI * 2) {
                this.spinAngle = 0;
                this.isSpinning = false;
                this.currentVrm.scene.rotation.y = baseRot;
                if (this.currentPose === 'spin') this.currentPose = 'stand';
            } else {
                this.currentVrm.scene.rotation.y = baseRot + this.spinAngle;
            }
        }
    }

    _updateLipSync(delta) {
        const lerpSpeed = Math.min(1.0, delta * 24.0);
        const em = this.currentVrm?.expressionManager;
        for (const key of ['aa', 'ih', 'ou', 'ee', 'oh']) {
            this.visemes[key] += (this.targetVisemes[key] - this.visemes[key]) * lerpSpeed;
            if (this.mode === 'vrm' && em) {
                try { em.setValue(key, this.visemes[key]); } catch (_) {}
            }
        }
    }

    _updateEyeGazeAndBlinking(delta) {
        // 1. Subtle natural eye saccades (lookAt / eye bones)
        this.eyeSaccadeTimer -= delta;
        if (this.eyeSaccadeTimer <= 0) {
            this.eyeSaccadeTimer = 1.4 + Math.random() * 2.8;
            this.eyeTarget.x = (Math.random() - 0.5) * 0.08;
            this.eyeTarget.y = (Math.random() - 0.5) * 0.05;
        }
        this.eyeCurrent.x = THREE.MathUtils.lerp(this.eyeCurrent.x, this.eyeTarget.x, delta * 8.0);
        this.eyeCurrent.y = THREE.MathUtils.lerp(this.eyeCurrent.y, this.eyeTarget.y, delta * 8.0);

        if (this.currentVrm?.lookAt) {
            try {
                this.currentVrm.lookAt.applier?.applyYawPitch(
                    this.eyeCurrent.x * 25.0,
                    this.eyeCurrent.y * 20.0
                );
            } catch (_) {}
        }

        // 2. Blinking
        const em = this.currentVrm.expressionManager;
        if (!em) return;

        this.blinkTimer += delta;
        if (!this.isBlinking && this.blinkTimer >= this.nextBlinkInterval) {
            this.isBlinking = true;
            this.blinkTimer = 0;
        }

        if (this.isBlinking) {
            const blinkDuration = 0.15;
            const progress = this.blinkTimer / blinkDuration;
            if (progress <= 0.5) {
                try { em.setValue('blink', progress * 2.0); } catch (_) {}
            } else if (progress <= 1.0) {
                try { em.setValue('blink', (1.0 - progress) * 2.0); } catch (_) {}
            } else {
                try { em.setValue('blink', 0.0); } catch (_) {}
                this.isBlinking = false;
                this.blinkTimer = 0;
                this.nextBlinkInterval = 2.0 + Math.random() * 4.0;
            }
        }
    }
}
