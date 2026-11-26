/* EarthQuick — Local Three.js 3D Shear-Frame + Software 3D Canvas Fallback */

import * as THREE from '/static/vendor/three.module.min.js';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

export class BuildingScene3D {
  constructor(canvas, onTick) {
    this.canvas = canvas;
    this.onTick = onTick;
    this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.playing = !this.reducedMotion;
    this.speed = 1.0;
    this.mode = 'static'; // 'static' | 'mode' | 'quake'

    this.floors = 4;
    this.masses = [120, 120, 120, 120];
    this.stiffnesses = [25000, 25000, 25000, 25000];
    this.modeShape = null;
    this.modeFreq = 1.5;
    this.quakeData = null;
    this.quakeTime = 0;
    this.phase = 0;
    this.lastTs = performance.now();
    this.curDisp = [0, 0, 0, 0];
    this.curGround = 0;
    this.curDrifts = null;

    this.floorGroups = [];
    this.storyColumns = [];
    this.fallback2d = false;
    this.swYaw = 0.62;
    this.swPitch = 0.32;
    this.swZoom = 1.0;

    this._initThree();
    this.rebuildBuilding(this.floors, this.masses, this.stiffnesses);
    this._bindResize();
    this._animate(performance.now());
  }

  get rendererType() {
    return this.fallback2d ? 'Canvas 3D' : 'WebGL 3D';
  }

  _initThree() {
    try {
      this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(44, 1, 0.1, 100);
      this.camera.position.set(7.5, 5.2, 8.8);

      this.controls = new OrbitControls(this.camera, this.canvas);
      this.controls.enableDamping = true;
      this.controls.target.set(0, 2.2, 0);

      const amb = new THREE.AmbientLight(0xdbeafe, 0.95);
      const dir = new THREE.DirectionalLight(0x7dd3fc, 1.45);
      dir.position.set(6, 12, 8);
      const rim = new THREE.DirectionalLight(0x2563eb, 0.75);
      rim.position.set(-6, 4, -5);
      this.scene.add(amb, dir, rim);

      const grid = new THREE.GridHelper(16, 16, 0x1e3a5f, 0x0f223d);
      grid.position.y = -0.14;
      this.scene.add(grid);

      this.baseMesh = new THREE.Mesh(
        new THREE.BoxGeometry(3.2, 0.24, 3.2),
        new THREE.MeshStandardMaterial({ color: 0x0f223d, metalness: 0.35, roughness: 0.55 })
      );
      this.baseMesh.position.y = -0.02;
      this.scene.add(this.baseMesh);

      this.buildingRoot = new THREE.Group();
      this.scene.add(this.buildingRoot);
      this._resize();
    } catch {
      this._initSoftwareFallback();
    }
  }

  _initSoftwareFallback() {
    this.fallback2d = true;
    this.ctx = this.canvas.getContext('2d');
    let dragging = false;
    let lx = 0;
    let ly = 0;
    this.canvas.addEventListener('pointerdown', (e) => { dragging = true; lx = e.clientX; ly = e.clientY; });
    window.addEventListener('pointerup', () => { dragging = false; });
    window.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      this.swYaw += (e.clientX - lx) * 0.008;
      this.swPitch = Math.max(0.05, Math.min(1.15, this.swPitch + (e.clientY - ly) * 0.006));
      lx = e.clientX;
      ly = e.clientY;
    });
    this.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.swZoom = Math.max(0.55, Math.min(1.8, this.swZoom - e.deltaY * 0.0008));
    }, { passive: false });
    this._resize();
  }

  _bindResize() {
    this._ro = new ResizeObserver(() => this._resize());
    if (this.canvas.parentElement) this._ro.observe(this.canvas.parentElement);
  }

  _resize() {
    const host = this.canvas.parentElement;
    if (!host) return;
    const w = Math.max(200, host.clientWidth);
    const h = Math.max(240, host.clientHeight);
    if (this.fallback2d) {
      this.canvas.width = w;
      this.canvas.height = h;
      return;
    }
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  resetCamera() {
    if (this.fallback2d) {
      this.swYaw = 0.62;
      this.swPitch = 0.32;
      this.swZoom = 1.0;
      return;
    }
    const midY = Math.max(1.6, this.floors * 0.55);
    const dist = Math.max(7.2, this.floors * 1.15);
    this.camera.position.set(dist * 0.85, midY + dist * 0.45, dist);
    this.controls.target.set(0, midY, 0);
    this.controls.update();
  }

  rebuildBuilding(floors, masses, stiffnesses) {
    this.floors = floors;
    this.masses = masses.slice(0, floors);
    this.stiffnesses = stiffnesses.slice(0, floors);
    this.curDisp = new Array(floors).fill(0);
    this.curGround = 0;
    this.curDrifts = null;
    if (this.fallback2d) {
      this.resetCamera();
      return;
    }

    while (this.buildingRoot.children.length) {
      const child = this.buildingRoot.children.pop();
      child.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) obj.material.dispose();
      });
    }
    this.floorGroups = [];
    this.storyColumns = [];

    const storyH = 1.05;
    const halfSpan = 1.05;
    const colOffsets = [
      [-halfSpan, -halfSpan],
      [halfSpan, -halfSpan],
      [-halfSpan, halfSpan],
      [halfSpan, halfSpan],
    ];

    const maxK = Math.max(...this.stiffnesses, 1);
    const maxM = Math.max(...this.masses, 1);

    for (let i = 0; i < floors; i++) {
      const kNorm = Math.sqrt(this.stiffnesses[i] / maxK);
      const colRadius = 0.045 + 0.045 * kNorm;
      const colGeo = new THREE.CylinderGeometry(colRadius, colRadius, storyH, 12);
      const colMat = new THREE.MeshStandardMaterial({ color: 0x60a5fa, metalness: 0.45, roughness: 0.35 });
      const cols = [];
      for (const [cx, cz] of colOffsets) {
        const mesh = new THREE.Mesh(colGeo, colMat);
        mesh.position.set(cx, i * storyH + storyH / 2 + 0.1, cz);
        this.buildingRoot.add(mesh);
        cols.push({ mesh, cx, cz });
      }
      this.storyColumns.push({ cols, mat: colMat });

      const mNorm = this.masses[i] / maxM;
      const slabH = 0.11 + 0.09 * mNorm;
      const slabGeo = new THREE.BoxGeometry(2.5, slabH, 2.5);
      const slabMat = new THREE.MeshStandardMaterial({
        color: 0x1d4ed8,
        emissive: 0x0c4a6e,
        emissiveIntensity: 0.45,
        metalness: 0.3,
        roughness: 0.25,
        transparent: true,
        opacity: 0.88,
      });
      const slab = new THREE.Mesh(slabGeo, slabMat);
      slab.position.set(0, (i + 1) * storyH + 0.1, 0);

      slab.add(new THREE.LineSegments(new THREE.EdgesGeometry(slabGeo), new THREE.LineBasicMaterial({ color: 0x38bdf8 })));
      this.buildingRoot.add(slab);
      this.floorGroups.push({ slab, baseY: (i + 1) * storyH + 0.1, mat: slabMat });
    }
    this.resetCamera();
  }

  setStatic() {
    this.mode = 'static';
    this.phase = 0;
    this._applyDisplacements(new Array(this.floors).fill(0), 0);
    if (this.onTick) this.onTick({ time: 0, roofMm: 0, frac: 0 });
  }

  setModeShape(phiVec, freqHz) {
    this.mode = 'mode';
    this.modeShape = phiVec.slice(0, this.floors);
    this.modeFreq = Math.max(0.2, freqHz || 1.0);
    this.phase = 0;
    this.playing = !this.reducedMotion;
    this._applyDisplacements(new Array(this.floors).fill(0), 0);
    if (this.onTick) this.onTick({ time: 0, roofMm: 0, frac: 0 });
  }

  setQuake(t, uMm, accelG) {
    this.mode = 'quake';
    this.quakeData = { t, uMm, accelG };
    this.quakeTime = 0;
    this.playing = !this.reducedMotion;
  }

  setPlaying(flag) {
    this.playing = flag;
    if (!flag && this.mode === 'mode') {
      this.phase = 0;
      this._applyDisplacements(new Array(this.floors).fill(0), 0);
      if (this.onTick) this.onTick({ time: 0, roofMm: 0, frac: 0 });
    }
  }

  setSpeed(speed) {
    this.speed = speed;
  }

  seekFraction(frac) {
    if (!this.quakeData) return;
    const tMax = this.quakeData.t[this.quakeData.t.length - 1] || 1;
    this.quakeTime = Math.max(0, Math.min(tMax, frac * tMax));
    this._renderQuakeAt(this.quakeTime);
  }

  _applyDisplacements(dispUnits, groundShift = 0, driftRatios = null) {
    this.curDisp = dispUnits;
    this.curGround = groundShift;
    this.curDrifts = driftRatios;
    if (this.fallback2d) return;

    this.baseMesh.position.x = groundShift;
    const storyH = 1.05;

    for (let i = 0; i < this.floors; i++) {
      const xTop = dispUnits[i] || 0;
      const xBot = i === 0 ? groundShift : (dispUnits[i - 1] || 0);
      this.floorGroups[i].slab.position.x = xTop;

      const dx = xTop - xBot;
      const tilt = Math.atan2(dx, storyH);
      const stretch = Math.hypot(dx, storyH) / storyH;
      const { cols, mat } = this.storyColumns[i];

      if (driftRatios) {
        const ratio = Math.min(1, driftRatios[i] || 0);
        mat.color.copy(new THREE.Color().setHSL(0.56 - ratio * 0.56, 0.88, 0.58));
      } else {
        mat.color.setHex(0x60a5fa);
      }

      for (const c of cols) {
        c.mesh.position.x = c.cx + (xBot + xTop) * 0.5;
        c.mesh.rotation.z = -tilt;
        c.mesh.scale.y = stretch;
      }
    }
  }

  _renderQuakeAt(timeSec) {
    if (!this.quakeData) return;
    const { t, uMm, accelG } = this.quakeData;
    const dt = t.length > 1 ? t[1] - t[0] : 0.01;
    const idx = Math.min(t.length - 1, Math.max(0, Math.round(timeSec / dt)));

    const maxPeak = Math.max(1e-6, ...uMm.flat().map(Math.abs));
    const visScale = 0.85 / maxPeak;
    const disp = [];
    const drifts = [];
    let maxDrift = 1e-6;
    for (let f = 0; f < this.floors; f++) {
      const val = uMm[f][idx] || 0;
      const prev = f === 0 ? 0 : (uMm[f - 1][idx] || 0);
      maxDrift = Math.max(maxDrift, Math.abs(val - prev));
    }
    const normMax = Math.max(maxPeak * 0.4, maxDrift, 1);

    for (let f = 0; f < this.floors; f++) {
      const val = uMm[f][idx] || 0;
      const prev = f === 0 ? 0 : (uMm[f - 1][idx] || 0);
      disp.push(val * visScale);
      drifts.push(Math.abs(val - prev) / normMax);
    }

    this._applyDisplacements(disp, (accelG[idx] || 0) * 0.25, drifts);
    const roofMm = uMm[this.floors - 1][idx] || 0;
    const frac = t[t.length - 1] > 0 ? t[idx] / t[t.length - 1] : 0;
    if (this.onTick) this.onTick({ time: t[idx], roofMm, frac });
  }

  _drawSoftware3D() {
    if (!this.ctx) return;
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.clearRect(0, 0, w, h);

    const storyH = 1.0;
    const midY = this.floors * storyH * 0.5;
    const scale = Math.min(w, h) * (0.34 / Math.max(2.6, this.floors * 0.42)) * this.swZoom;
    const cy = Math.cos(this.swYaw);
    const sy = Math.sin(this.swYaw);
    const cp = Math.cos(this.swPitch);
    const sp = Math.sin(this.swPitch);

    const project = (x, y, z) => {
      const xr = x * cy - z * sy;
      const zr = x * sy + z * cy;
      const yr = (y - midY) * cp - zr * sp;
      const zp = (y - midY) * sp + zr * cp + 12;
      const f = 12 / Math.max(2, zp);
      return [w * 0.5 + xr * scale * f, h * 0.52 - yr * scale * f];
    };

    const corners = [[-1.05, -1.05], [1.05, -1.05], [1.05, 1.05], [-1.05, 1.05]];
    // Ground plate
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
    ctx.fillStyle = 'rgba(15, 34, 61, 0.75)';
    ctx.beginPath();
    corners.forEach(([cx, cz], i) => {
      const [px, py] = project(cx + this.curGround, 0, cz);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Stories
    for (let i = 0; i < this.floors; i++) {
      const xBot = i === 0 ? this.curGround : (this.curDisp[i - 1] || 0);
      const xTop = this.curDisp[i] || 0;
      const yBot = i * storyH;
      const yTop = (i + 1) * storyH;
      const ratio = this.curDrifts ? Math.min(1, this.curDrifts[i] || 0) : 0;
      ctx.strokeStyle = this.curDrifts ? `hsl(${200 - ratio * 200}, 90%, 60%)` : '#60a5fa';
      ctx.lineWidth = 2.4;
      corners.forEach(([cx, cz]) => {
        const [x0, y0] = project(cx + xBot, yBot, cz);
        const [x1, y1] = project(cx + xTop, yTop, cz);
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
      });

      ctx.fillStyle = 'rgba(29, 78, 216, 0.45)';
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      corners.forEach(([cx, cz], idx) => {
        const [px, py] = project(cx + xTop, yTop, cz);
        if (idx === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }

  _animate(now) {
    const dt = Math.min(0.05, (now - this.lastTs) / 1000);
    this.lastTs = now;

    if (this.mode === 'mode' && this.modeShape && this.playing) {
      this.phase += dt * Math.min(3.5, this.modeFreq) * 2.4 * this.speed;
      const amp = Math.sin(this.phase) * 0.65;
      const disp = this.modeShape.map((v) => v * amp);
      this._applyDisplacements(disp, 0);
      if (this.onTick) this.onTick({ time: 0, roofMm: disp[this.floors - 1] * 100, frac: 0 });
    } else if (this.mode === 'quake' && this.quakeData && this.playing) {
      const tMax = this.quakeData.t[this.quakeData.t.length - 1] || 1;
      this.quakeTime += dt * this.speed;
      if (this.quakeTime > tMax) this.quakeTime = 0;
      this._renderQuakeAt(this.quakeTime);
    }

    if (this.fallback2d) {
      this._drawSoftware3D();
    } else {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    }

    requestAnimationFrame((ts) => this._animate(ts));
  }
}
