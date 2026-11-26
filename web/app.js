/* EarthQuick — Client Application State, Validation, Charts & API Integration */

import { BuildingScene3D } from '/static/scene3d.js';

const STORAGE_KEY = 'earthquick_history_v1';
const THEME_KEY = 'earthquick_theme_v1';

const state = {
  view: 'overview',
  savedModel: null,
  savedBuildings: [],
  isDirty: false,
  matrices: null,
  modal: null,
  quake: null,
  quakeSource: 'preset',
  presets: [],
  history: [],
  compareRuns: [],
  stiffComparison: null,
};

// ---------------- Theme & Responsive Navbar ----------------
function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) document.documentElement.dataset.theme = saved;
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem(THEME_KEY, next);
  });
}

async function initNavbar() {
  if (!Object.hasOwn(HTMLElement.prototype, 'popover')) {
    try { await import('https://unpkg.com/@oddbird/popover-polyfill@latest/dist/popover.min.js'); } catch {}
  }
  const header = document.getElementById('site-header');
  const inner = header.querySelector('.header-inner');
  const menu = document.getElementById('site-menu');
  let wide = false;

  const measure = () => {
    header.classList.add('is-measuring');
    header.classList.add('is-wide');
    const fits = inner.scrollWidth <= inner.clientWidth + 2;
    wide = fits;
    header.classList.toggle('is-wide', fits);
    if (fits) menu.removeAttribute('popover');
    else menu.setAttribute('popover', 'auto');
    requestAnimationFrame(() => header.classList.remove('is-measuring'));
  };

  new ResizeObserver(() => {
    if (wide || header.clientWidth > 680) measure();
  }).observe(header);
  measure();
}

// ---------------- Polite Error Announcer & After-Interaction Validation ----------------
const announcer = document.createElement('div');
announcer.setAttribute('aria-live', 'polite');
announcer.className = 'visually-hidden';
document.body.append(announcer);

function syncFieldAria(el, announce = false) {
  if (!el.matches?.('input, select')) return;
  const invalid = el.matches(':user-invalid') || !el.validity.valid && el.dataset.touched === '1';
  el.classList.toggle('user-invalid-fallback', invalid);
  el.setAttribute('aria-invalid', invalid ? 'true' : 'false');
  const errId = el.dataset.error;
  if (errId) {
    const errEl = document.getElementById(errId);
    if (invalid) {
      el.setAttribute('aria-describedby', errId);
      if (announce && errEl) announcer.textContent = errEl.textContent;
    } else {
      el.removeAttribute('aria-describedby');
    }
  }
}

document.addEventListener('blur', (e) => {
  if (e.target.matches?.('input')) {
    e.target.dataset.touched = '1';
    syncFieldAria(e.target, true);
  }
}, true);

document.addEventListener('input', (e) => {
  if (e.target.matches?.('input[data-error]')) syncFieldAria(e.target, false);
});

// ---------------- Accessible Tabs (Learning Centre) ----------------
function initTabs() {
  const tablist = document.querySelector('[role="tablist"]');
  if (!tablist) return;
  const tabs = [...tablist.querySelectorAll('[role="tab"]')];
  const panels = tabs.map((t) => document.querySelector(`[aria-labelledby="${t.id}"]`));

  const selectTab = (idx, focusTab = false) => {
    tabs.forEach((t, i) => {
      const active = i === idx;
      t.setAttribute('aria-selected', String(active));
      t.tabIndex = active ? 0 : -1;
      if (active) panels[i].removeAttribute('hidden');
      else panels[i].setAttribute('hidden', 'until-found');
    });
    if (focusTab) tabs[idx].focus();
  };

  tabs.forEach((tab, idx) => {
    tab.addEventListener('click', () => selectTab(idx));
    tab.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight') selectTab((idx + 1) % tabs.length, true);
      if (e.key === 'ArrowLeft') selectTab((idx - 1 + tabs.length) % tabs.length, true);
    });
  });

  panels.forEach((p, idx) => p.addEventListener('beforematch', () => selectTab(idx)));
}

// ---------------- Building Model Form & Live 3D Sync ----------------
let scene3d;

function getDraftConfig() {
  const floors = Number(document.getElementById('b-floors').value);
  const masses = [];
  const stiffnesses = [];
  for (let i = 0; i < floors; i++) {
    const m = Number(document.getElementById(`f-mass-${i}`)?.value || 120);
    const k = Number(document.getElementById(`f-stiff-${i}`)?.value || 25000);
    masses.push(m);
    stiffnesses.push(k);
  }
  return {
    building_name: document.getElementById('b-name').value.trim() || 'Building',
    building_type: document.getElementById('b-type').value,
    floors,
    damping_ratio: Number(document.getElementById('b-damping').value),
    masses,
    stiffnesses,
  };
}

function syncStiffnessStoryOptions(floors) {
  const sel = document.getElementById('stiff-story');
  if (!sel) return;
  const prev = Number(sel.value || 1);
  sel.innerHTML = '';
  for (let i = 1; i <= floors; i++) {
    sel.add(new Option(`Storey ${i}`, String(i)));
  }
  sel.value = String(Math.min(Math.max(1, prev), floors));
}

function renderFloorRows(floors, existingMasses = null, existingStiff = null) {
  const safeFloors = Math.min(5, Math.max(3, Number(floors) || 4));
  const container = document.getElementById('floor-rows');
  const prevM = existingMasses || [...container.querySelectorAll('.m-in')].map((el) => Number(el.value));
  const prevK = existingStiff || [...container.querySelectorAll('.k-in')].map((el) => Number(el.value));
  container.innerHTML = '';

  for (let i = 0; i < safeFloors; i++) {
    const row = document.createElement('div');
    row.className = 'floor-row';
    const mVal = prevM[i] > 0 ? prevM[i] : 120;
    const kVal = prevK[i] > 0 ? prevK[i] : 25000;
    row.innerHTML = `
      <span class="floor-tag">Floor ${i + 1}</span>
      <input id="f-mass-${i}" class="m-in" type="number" min="1" max="10000" step="1" value="${mVal}" required aria-label="Floor ${i + 1} weight in tonnes">
      <input id="f-stiff-${i}" class="k-in" type="number" min="100" max="1000000" step="100" value="${kVal}" required aria-label="Story ${i + 1} stiffness in kN/m">
    `;
    container.append(row);
  }
  syncStiffnessStoryOptions(safeFloors);
}

function markDirtyAndSync3D() {
  if (state.savedModel) {
    state.isDirty = true;
    state.matrices = null;
    state.modal = null;
    state.quake = null;
  }
  const cfg = getDraftConfig();
  scene3d.rebuildBuilding(cfg.floors, cfg.masses, cfg.stiffnesses);
  refreshStatusUI();
}

// ---------------- Navigation & Workflow Stepper ----------------
function switchView(viewId) {
  state.view = viewId;
  document.querySelectorAll('.view-panel').forEach((p) => { p.hidden = p.id !== `view-${viewId}`; });
  document.querySelectorAll('#site-menu a').forEach((a) => {
    if (a.dataset.nav === viewId) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });

  const menu = document.getElementById('site-menu');
  if (menu.matches?.(':popover-open')) menu.hidePopover();

  const badge = document.getElementById('vp-mode-badge');
  const scrubber = document.getElementById('vp-scrubber');
  const playBtn = document.getElementById('vp-play-btn');
  if (viewId === 'modes' && state.modal) {
    badge.textContent = '3D Mode';
    scrubber.disabled = true;
    const idx = Number(document.getElementById('mode-select').value || 0);
    scene3d.setModeShape(state.modal.phi_normalized.map((row) => row[idx]), state.modal.frequencies_hz[idx]);
    if (playBtn) playBtn.textContent = scene3d.playing ? 'Pause' : 'Play';
    requestAnimationFrame(() => renderModalCharts(state.modal));
  } else if (viewId === 'quake' && state.quake) {
    badge.textContent = '3D Quake';
    scrubber.disabled = false;
    scene3d.setQuake(state.quake.t, state.quake.u_mm, state.quake.accel_g);
    if (playBtn) playBtn.textContent = scene3d.playing ? 'Pause' : 'Play';
  } else {
    badge.textContent = 'Static';
    scrubber.disabled = true;
    scene3d.setStatic();
  }
  if (viewId === 'compare' && state.stiffComparison) {
    requestAnimationFrame(() => renderStiffnessComparison(state.stiffComparison));
  }
  refreshStatusUI();
}

function refreshStatusUI() {
  const pill = document.getElementById('model-status-pill');
  const cfg = getDraftConfig();
  const modelReady = Boolean(state.savedModel && !state.isDirty);

  if (modelReady) {
    pill.textContent = 'Saved';
    pill.className = 'status-pill status-saved';
  } else if (state.savedModel && state.isDirty) {
    pill.textContent = 'Unsaved edits';
    pill.className = 'status-pill status-dirty';
  } else {
    pill.textContent = 'Draft';
    pill.className = 'status-pill status-draft';
  }

  document.getElementById('ov-status').textContent = pill.textContent;
  document.getElementById('ov-floors').textContent = String(cfg.floors);
  document.getElementById('ov-damping').textContent = `${(cfg.damping_ratio * 100).toFixed(1)}%`;
  document.getElementById('ov-runs').textContent = String(state.history.length);

  const stepDone = [modelReady, Boolean(state.matrices), Boolean(state.modal), Boolean(state.quake), state.compareRuns.length >= 2];
  let currentSet = false;
  document.querySelectorAll('.step-item').forEach((btn, idx) => {
    btn.classList.remove('is-done', 'is-current');
    if (stepDone[idx]) btn.classList.add('is-done');
    else if (!currentSet) {
      btn.classList.add('is-current');
      currentSet = true;
    }
  });

  // Empty-state toggles
  document.getElementById('matrices-empty').hidden = Boolean(state.matrices);
  document.getElementById('matrices-results').hidden = !state.matrices;
  document.getElementById('modes-empty').hidden = Boolean(state.modal);
  document.getElementById('modes-results').hidden = !state.modal;
  if (!state.modal) document.getElementById('resonance-results').hidden = true;
  document.getElementById('quake-empty').hidden = Boolean(state.quake);
  document.getElementById('quake-results').hidden = !state.quake;
  document.getElementById('compare-empty').hidden = state.compareRuns.length >= 2;
  document.getElementById('compare-results').hidden = state.compareRuns.length < 2;
  document.getElementById('history-empty').hidden = state.history.length > 0;
  document.getElementById('history-table-card').hidden = state.history.length === 0;
}

// ---------------- Lightweight Canvas Charts & Heatmaps ----------------
function renderHeatmap(elId, matrix) {
  const el = document.getElementById(elId);
  const n = matrix.length;
  const maxAbs = Math.max(1e-9, ...matrix.flat().map(Math.abs));
  const grid = document.createElement('div');
  grid.className = 'heatmap-grid';
  grid.style.gridTemplateColumns = `repeat(${n}, minmax(54px, 1fr))`;

  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const val = matrix[r][c];
      const norm = Math.abs(val) / maxAbs;
      const cell = document.createElement('div');
      cell.className = 'hm-cell';
      const bg = val < 0
        ? `rgba(248, 113, 113, ${0.18 + 0.55 * norm})`
        : `rgba(56, 189, 248, ${0.12 + 0.65 * norm})`;
      cell.style.background = bg;
      cell.textContent = val.toLocaleString(undefined, { maximumFractionDigits: 0 });
      cell.title = `Row ${r + 1}, Col ${c + 1}: ${val}`;
      grid.append(cell);
    }
  }
  el.replaceChildren(grid);
}

function drawLineChart(canvasId, xVals, seriesList, xLabel, yLabel) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  const w = canvas.clientWidth || 420;
  const h = canvas.height;
  canvas.width = w;
  ctx.clearRect(0, 0, w, h);

  const pad = { l: 48, r: 16, t: 24, b: 32 };
  const allY = seriesList.flatMap((s) => s.data);
  const minY = Math.min(0, ...allY);
  const maxY = Math.max(1e-6, ...allY);
  const spanY = Math.max(1e-6, maxY - minY);
  const minX = xVals[0];
  const spanX = Math.max(1e-6, xVals[xVals.length - 1] - minX);

  const sx = (v) => pad.l + ((v - minX) / spanX) * (w - pad.l - pad.r);
  const sy = (v) => h - pad.b - ((v - minY) / spanY) * (h - pad.t - pad.b);

  ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.l, sy(0));
  ctx.lineTo(w - pad.r, sy(0));
  ctx.stroke();

  seriesList.forEach((s) => {
    ctx.save();
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    if (s.dash) ctx.setLineDash(s.dash);
    ctx.beginPath();
    const step = Math.max(1, Math.floor(xVals.length / 400));
    for (let i = 0; i < xVals.length; i += step) {
      const px = sx(xVals[i]);
      const py = sy(s.data[i]);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.restore();
  });

  ctx.fillStyle = '#94a3b8';
  ctx.font = '11px Inter, sans-serif';
  ctx.fillText(yLabel, 8, 14);
  ctx.fillText(xLabel, w - 58, h - 8);
  let lx = pad.l;
  seriesList.forEach((s) => {
    ctx.fillStyle = s.color;
    ctx.fillText(`● ${s.name}`, lx, 14);
    lx += 110;
  });
}

function drawBarChart(canvasId, labels, seriesList) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  const w = canvas.clientWidth || 420;
  const h = canvas.height;
  canvas.width = w;
  ctx.clearRect(0, 0, w, h);

  const pad = { l: 42, r: 16, t: 24, b: 30 };
  const maxY = Math.max(1, ...seriesList.flatMap((s) => s.data)) * 1.15;
  const groupW = (w - pad.l - pad.r) / labels.length;
  const barW = Math.min(26, (groupW * 0.72) / seriesList.length);

  labels.forEach((lbl, i) => {
    const gx = pad.l + i * groupW + groupW * 0.14;
    seriesList.forEach((s, j) => {
      const val = s.data[i];
      const bh = (val / maxY) * (h - pad.t - pad.b);
      const bx = gx + j * (barW + 3);
      const by = h - pad.b - bh;
      ctx.fillStyle = s.color;
      ctx.fillRect(bx, by, barW, bh);
    });
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px JetBrains Mono, monospace';
    ctx.fillText(lbl, gx, h - 10);
  });

  let lx = pad.l;
  ctx.font = '11px Inter, sans-serif';
  seriesList.forEach((s) => {
    ctx.fillStyle = s.color;
    ctx.fillText(`■ ${s.name}`, lx, 14);
    lx += 115;
  });
}

function drawModeShapeChart(phiNorm) {
  const canvas = document.getElementById('chart-mode-shapes');
  const ctx = canvas.getContext('2d');
  const w = canvas.clientWidth || 360;
  const h = canvas.height;
  canvas.width = w;
  ctx.clearRect(0, 0, w, h);

  const n = phiNorm.length;
  const pad = { l: 46, r: 20, t: 20, b: 24 };
  const midX = pad.l + (w - pad.l - pad.r) / 2;
  const scaleX = (w - pad.l - pad.r) * 0.42;
  const sy = (lvl) => h - pad.b - (lvl / n) * (h - pad.t - pad.b);

  ctx.strokeStyle = 'rgba(148,163,184,0.35)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(midX, pad.t);
  ctx.lineTo(midX, h - pad.b);
  ctx.stroke();
  ctx.setLineDash([]);

  const colors = ['#38bdf8', '#60a5fa', '#34d399'];
  for (let m = 0; m < Math.min(3, n); m++) {
    ctx.strokeStyle = colors[m];
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(midX, sy(0));
    for (let f = 0; f < n; f++) {
      ctx.lineTo(midX + phiNorm[f][m] * scaleX, sy(f + 1));
    }
    ctx.stroke();
  }
  ctx.fillStyle = '#94a3b8';
  ctx.font = '11px Inter, sans-serif';
  ctx.fillText('Ground', 4, sy(0));
  ctx.fillText(`Floor ${n}`, 4, sy(n) + 4);
}

// ---------------- API Calls & Rendering ----------------
function requireSavedConfig() {
  if (!state.savedModel || state.isDirty) {
    switchView('model');
    return null;
  }
  return state.savedModel;
}

function renderMatricesResults(data) {
  state.matrices = data;
  document.getElementById('mat-dim').textContent = `${data.n} × ${data.n}`;
  document.getElementById('mat-spd').textContent = data.is_spd ? 'Passed' : 'Failed';
  document.getElementById('mat-cond').textContent = data.cond_k.toFixed(1);
  document.getElementById('mat-sparse').textContent = `${data.sparsity_pct.toFixed(0)}%`;
  renderHeatmap('heatmap-m', data.M);
  renderHeatmap('heatmap-k', data.K);
}

function renderModalCharts(mod) {
  drawModeShapeChart(mod.phi_normalized);
  drawBarChart('chart-mode-mass', mod.frequencies_hz.map((_, i) => `M${i + 1}`), [
    { name: 'Weight %', data: mod.mass_ratio_pct, color: '#38bdf8' },
  ]);
}

function renderModalResults(mod) {
  state.modal = mod;
  document.getElementById('mod-f1').textContent = `${mod.frequencies_hz[0].toFixed(2)} Hz`;
  document.getElementById('mod-t1').textContent = `${mod.periods_s[0].toFixed(2)} s`;
  document.getElementById('mod-m1').textContent = `${mod.mass_ratio_pct[0].toFixed(0)}%`;
  document.getElementById('mod-err').textContent = mod.eigen_residual.toExponential(1);

  const sel = document.getElementById('mode-select');
  sel.innerHTML = '';
  mod.frequencies_hz.forEach((f, idx) => {
    const opt = document.createElement('option');
    opt.value = String(idx);
    opt.textContent = `Mode ${idx + 1} (${f.toFixed(2)} Hz)`;
    sel.append(opt);
  });

  const tbody = document.querySelector('#modes-table tbody');
  tbody.innerHTML = mod.frequencies_hz.map((f, i) => `
    <tr>
      <th>Mode ${i + 1}</th>
      <td data-label="Speed (Hz)">${f.toFixed(3)}</td>
      <td data-label="Time T (s)">${mod.periods_s[i].toFixed(3)}</td>
      <td data-label="Weight share (%)">${mod.mass_ratio_pct[i].toFixed(1)}</td>
    </tr>
  `).join('');

  if (state.view === 'modes') {
    requestAnimationFrame(() => renderModalCharts(mod));
  }
}

async function runMatrices() {
  const cfg = requireSavedConfig();
  if (!cfg) return;
  const res = await fetch('/api/matrices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ masses: cfg.masses, stiffnesses: cfg.stiffnesses }),
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error);
  renderMatricesResults(data);
  refreshStatusUI();
}

async function runModal() {
  const cfg = requireSavedConfig();
  if (!cfg) return;
  const res = await fetch('/api/modal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building_id: cfg.id || null,
      building_name: cfg.building_name,
      building_type: cfg.building_type,
      damping_ratio: cfg.damping_ratio,
      masses: cfg.masses,
      stiffnesses: cfg.stiffnesses,
    }),
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error);
  if (data.building_id && state.savedModel && !state.savedModel.id) {
    state.savedModel.id = data.building_id;
    await refreshSavedBuildings();
  }
  renderMatricesResults(data.matrices);
  renderModalResults(data.modal);
  await refreshHistoryFromDb();

  document.getElementById('vp-mode-badge').textContent = '3D Mode';
  scene3d.setModeShape(data.modal.phi_normalized.map((r) => r[0]), data.modal.frequencies_hz[0]);
  const playBtn = document.getElementById('vp-play-btn');
  if (playBtn) playBtn.textContent = scene3d.playing ? 'Pause' : 'Play';
  refreshStatusUI();
  requestAnimationFrame(() => renderModalCharts(data.modal));
}

async function runEarthquake() {
  const cfg = requireSavedConfig();
  if (!cfg) return;
  const errEl = document.getElementById('quake-error');
  errEl.hidden = true;

  let res;
  if (state.quakeSource === 'csv') {
    const fileInput = document.getElementById('q-csv-file');
    if (!fileInput.files.length) {
      errEl.textContent = 'Select a CSV file first.';
      errEl.hidden = false;
      return;
    }
    const fd = new FormData();
    if (cfg.id) fd.append('building_id', String(cfg.id));
    fd.append('building_name', cfg.building_name);
    fd.append('building_type', cfg.building_type);
    fd.append('masses', cfg.masses.join(','));
    fd.append('stiffnesses', cfg.stiffnesses.join(','));
    fd.append('damping_ratio', String(cfg.damping_ratio));
    fd.append('file', fileInput.files[0]);
    res = await fetch('/api/earthquake/csv', { method: 'POST', body: fd });
  } else {
    res = await fetch('/api/earthquake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        building_id: cfg.id || null,
        building_name: cfg.building_name,
        building_type: cfg.building_type,
        masses: cfg.masses,
        stiffnesses: cfg.stiffnesses,
        damping_ratio: cfg.damping_ratio,
        preset_name: document.getElementById('q-preset').value,
        pga_g: Number(document.getElementById('q-pga').value),
        duration_s: Number(document.getElementById('q-dur').value),
      }),
    });
  }

  const data = await res.json();
  if (!res.ok) {
    errEl.textContent = data.error || 'Simulation failed.';
    errEl.hidden = false;
    return;
  }

  if (data.building_id && state.savedModel && !state.savedModel.id) {
    state.savedModel.id = data.building_id;
    await refreshSavedBuildings();
  }

  renderMatricesResults(data.matrices);
  renderModalResults(data.earthquake.modal);
  state.quake = data.earthquake;

  const eq = data.earthquake;
  document.getElementById('eq-roof').textContent = `${eq.peak_roof_disp_mm.toFixed(1)} mm`;
  document.getElementById('eq-drift').textContent = `${eq.max_interstory_drift_mm.toFixed(1)} mm (${eq.risk_level})`;
  document.getElementById('eq-shear').textContent = `${Math.round(eq.peak_base_shear_kn).toLocaleString()} kN`;
  document.getElementById('eq-pga').textContent = `${eq.pga_g.toFixed(2)} g`;

  drawLineChart('chart-time-history', eq.t, [
    { name: 'Roof', data: eq.u_mm[eq.n - 1], color: '#38bdf8' },
    { name: 'Floor 1', data: eq.u_mm[0], color: '#60a5fa', dash: [6, 3] },
  ], 'Time (s)', 'mm');

  drawBarChart('chart-drift-bars', eq.peak_floor_disp_mm.map((_, i) => `L${i + 1}`), [
    { name: 'Floor move', data: eq.peak_floor_disp_mm, color: '#38bdf8' },
    { name: 'Story shift', data: eq.peak_story_drift_mm, color: '#2563eb' },
  ]);

  document.querySelector('#eq-table tbody').innerHTML = eq.peak_floor_disp_mm.map((d, i) => `
    <tr>
      <th>Level ${i + 1}</th>
      <td data-label="Max move (mm)">${d.toFixed(2)}</td>
      <td data-label="Max shift (mm)">${eq.peak_story_drift_mm[i].toFixed(2)}</td>
    </tr>
  `).join('');

  await refreshHistoryFromDb();

  document.getElementById('vp-mode-badge').textContent = '3D Quake';
  document.getElementById('vp-scrubber').disabled = false;
  scene3d.setQuake(eq.t, eq.u_mm, eq.accel_g);
  refreshStatusUI();
  requestAnimationFrame(() => {
    drawLineChart('chart-time-history', eq.t, [
      { name: 'Roof', data: eq.u_mm[eq.n - 1], color: '#38bdf8' },
      { name: 'Floor 1', data: eq.u_mm[0], color: '#60a5fa', dash: [6, 3] },
    ], 'Time (s)', 'mm');
    drawBarChart('chart-drift-bars', eq.peak_floor_disp_mm.map((_, i) => `L${i + 1}`), [
      { name: 'Floor move', data: eq.peak_floor_disp_mm, color: '#38bdf8' },
      { name: 'Story shift', data: eq.peak_story_drift_mm, color: '#2563eb' },
    ]);
  });
}

function renderCompareSelectors() {
  const runs = state.compareRuns;
  if (runs.length < 2) return;
  const selA = document.getElementById('cmp-a');
  const selB = document.getElementById('cmp-b');
  selA.innerHTML = '';
  selB.innerHTML = '';
  runs.forEach((r, i) => {
    selA.add(new Option(r.label, String(i)));
    selB.add(new Option(r.label, String(i)));
  });
  selA.selectedIndex = 1;
  selB.selectedIndex = 0;
  updateCompareView();
}

function updateCompareView() {
  const runs = state.compareRuns;
  if (runs.length < 2) return;
  const a = runs[Number(document.getElementById('cmp-a').value || 1)];
  const b = runs[Number(document.getElementById('cmp-b').value || 0)];
  document.getElementById('cmp-t1').textContent = `${b.t1_s.toFixed(2)} s (${(b.t1_s - a.t1_s >= 0 ? '+' : '')}${(b.t1_s - a.t1_s).toFixed(2)})`;
  document.getElementById('cmp-roof').textContent = `${b.roof_mm.toFixed(1)} mm (${(b.roof_mm - a.roof_mm >= 0 ? '+' : '')}${(b.roof_mm - a.roof_mm).toFixed(1)})`;
  document.getElementById('cmp-drift').textContent = `${b.drift_mm.toFixed(1)} mm (${(b.drift_mm - a.drift_mm >= 0 ? '+' : '')}${(b.drift_mm - a.drift_mm).toFixed(1)})`;
  document.getElementById('cmp-shear').textContent = `${Math.round(b.shear_kn)} kN`;

  const maxStories = Math.max(a.stories, b.stories);
  const labels = Array.from({ length: maxStories }, (_, i) => `S${i + 1}`);
  drawBarChart('chart-compare', labels, [
    { name: `A: ${a.building}`, data: labels.map((_, i) => a.drift_profile[i] || 0), color: '#60a5fa' },
    { name: `B: ${b.building}`, data: labels.map((_, i) => b.drift_profile[i] || 0), color: '#38bdf8' },
  ]);
}

function renderResonanceResults(resData) {
  const errEl = document.getElementById('resonance-error');
  const box = document.getElementById('resonance-results');
  const banner = document.getElementById('resonance-banner');
  const tbody = document.querySelector('#resonance-table tbody');
  errEl.hidden = true;
  box.hidden = false;

  banner.textContent = resData.summary;
  banner.style.color = resData.has_resonance_risk ? 'var(--danger)' : 'var(--success)';

  tbody.innerHTML = resData.modes.map((m) => `
    <tr>
      <th>Mode ${m.mode}</th>
      <td data-label="Natural freq (Hz)">${m.frequency_hz.toFixed(3)}</td>
      <td data-label="Period (s)">${m.period_s.toFixed(3)}</td>
      <td data-label="Status">${m.at_risk ? '<strong style="color:var(--danger)">Resonance risk</strong>' : 'Outside band'}</td>
    </tr>
  `).join('');
}

async function runResonanceCheck() {
  const cfg = requireSavedConfig();
  if (!cfg) return;
  const errEl = document.getElementById('resonance-error');
  errEl.hidden = true;
  const freqMin = Number(document.getElementById('res-fmin').value);
  const freqMax = Number(document.getElementById('res-fmax').value);

  const res = await fetch('/api/resonance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building_id: cfg.id || null,
      building_name: cfg.building_name,
      building_type: cfg.building_type,
      damping_ratio: cfg.damping_ratio,
      masses: cfg.masses,
      stiffnesses: cfg.stiffnesses,
      freq_min_hz: freqMin,
      freq_max_hz: freqMax,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    errEl.textContent = data.error || 'Resonance check failed.';
    errEl.hidden = false;
    return;
  }
  renderMatricesResults(data.matrices);
  renderModalResults(data.modal);
  renderResonanceResults(data.resonance);
  await refreshHistoryFromDb();
  refreshStatusUI();
}

function renderStiffnessComparison(cmp) {
  state.stiffComparison = cmp;
  document.getElementById('stiff-compare-results').hidden = false;
  document.getElementById('stiff-explanation').textContent = cmp.explanation;

  const tbody = document.querySelector('#stiff-compare-table tbody');
  tbody.innerHTML = cmp.modes.map((m) => `
    <tr>
      <th>Mode ${m.mode}</th>
      <td data-label="Original (Hz)">${m.orig_freq_hz.toFixed(3)}</td>
      <td data-label="Modified (Hz)">${m.mod_freq_hz.toFixed(3)}</td>
      <td data-label="Change (%)">${m.change_pct >= 0 ? '+' : ''}${m.change_pct.toFixed(2)}%</td>
    </tr>
  `).join('');

  drawBarChart('chart-stiff-compare', cmp.modes.map((m) => `M${m.mode}`), [
    { name: 'Original (Hz)', data: cmp.modes.map((m) => m.orig_freq_hz), color: '#60a5fa' },
    { name: 'Modified (Hz)', data: cmp.modes.map((m) => m.mod_freq_hz), color: '#34d399' },
  ]);
}

async function runStiffnessComparison() {
  const cfg = state.savedModel && !state.isDirty ? state.savedModel : getDraftConfig();
  const errEl = document.getElementById('stiff-error');
  errEl.hidden = true;
  if (cfg.floors < 3 || cfg.floors > 5) {
    errEl.textContent = 'Building must have between 3 and 5 storeys.';
    errEl.hidden = false;
    return;
  }

  const storyIndex = Number(document.getElementById('stiff-story').value || 1);
  const newValRaw = document.getElementById('stiff-new-val').value.trim();
  const pctRaw = document.getElementById('stiff-pct').value.trim();

  const res = await fetch('/api/stiffness-compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building_id: state.savedModel && !state.isDirty ? state.savedModel.id || null : null,
      building_name: cfg.building_name,
      building_type: cfg.building_type,
      damping_ratio: cfg.damping_ratio,
      masses: cfg.masses,
      stiffnesses: cfg.stiffnesses,
      story_index: storyIndex,
      new_stiffness: newValRaw !== '' ? Number(newValRaw) : null,
      pct_change: newValRaw === '' && pctRaw !== '' ? Number(pctRaw) : null,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    errEl.textContent = data.error || 'Comparison failed.';
    errEl.hidden = false;
    return;
  }
  renderStiffnessComparison(data.comparison);
  await Promise.all([refreshSavedBuildings(), refreshHistoryFromDb()]);
  refreshStatusUI();
}

function renderHistoryTable() {
  const tbody = document.querySelector('#history-table tbody');
  tbody.innerHTML = state.history.map((r) => `
    <tr>
      <th>${r.time}</th>
      <td data-label="Type">${r.type}</td>
      <td data-label="Building">${r.building}</td>
      <td data-label="Floors">${r.floors}</td>
      <td data-label="T₁ (s)">${r.t1_s}</td>
      <td data-label="Roof (mm)">${r.roof_mm}</td>
      <td data-label="Max shift (mm)">${r.risk_level ? `${r.drift_mm} (${r.risk_level})` : r.drift_mm}</td>
    </tr>
  `).join('');
}

function applyBuildingToForm(b) {
  document.getElementById('b-name').value = b.name;
  const typeSel = document.getElementById('b-type');
  const hasType = [...typeSel.options].some((o) => o.value === b.building_type);
  typeSel.value = hasType ? b.building_type : typeSel.options[0].value;
  document.getElementById('b-floors').value = String(b.floors);
  document.getElementById('b-floors-out').textContent = String(b.floors);
  document.getElementById('b-damping').value = String(b.damping_ratio);
  renderFloorRows(b.floors, b.masses, b.stiffnesses);

  state.savedModel = {
    id: b.id,
    building_name: b.name,
    building_type: b.building_type,
    floors: b.floors,
    damping_ratio: b.damping_ratio,
    masses: b.masses,
    stiffnesses: b.stiffnesses,
  };
  state.isDirty = false;
  state.matrices = null;
  state.modal = null;
  state.quake = null;
  scene3d.rebuildBuilding(b.floors, b.masses, b.stiffnesses);
  refreshStatusUI();
}

async function refreshSavedBuildings(selectedId = null) {
  try {
    const res = await fetch('/api/buildings');
    if (!res.ok) return;
    const data = await res.json();
    state.savedBuildings = data.buildings || [];
    const bar = document.getElementById('saved-buildings-bar');
    const sel = document.getElementById('saved-building-select');
    bar.hidden = state.savedBuildings.length === 0;
    sel.innerHTML = '';
    state.savedBuildings.forEach((b) => sel.add(new Option(`${b.name} (${b.floors}F)`, String(b.id))));
    const activeId = selectedId ?? state.savedModel?.id;
    if (activeId && state.savedBuildings.some((b) => b.id === activeId)) {
      sel.value = String(activeId);
    }
  } catch {}
}

async function saveBuildingToDb(cfg) {
  const res = await fetch('/api/buildings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: cfg.building_name,
      building_type: cfg.building_type,
      damping_ratio: cfg.damping_ratio,
      masses: cfg.masses,
      stiffnesses: cfg.stiffnesses,
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to save building.');
  const b = data.building;
  state.savedModel = { ...cfg, id: b.id };
  state.isDirty = false;
  state.matrices = null;
  state.modal = null;
  state.quake = null;
  await refreshSavedBuildings(b.id);
  refreshStatusUI();
  return b;
}

async function refreshHistoryFromDb() {
  try {
    const res = await fetch('/api/history');
    if (!res.ok) return;
    const data = await res.json();
    state.history = data.history || [];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.history.slice(0, 30)));
    state.compareRuns = state.history
      .filter((r) => r.run_type === 'quake' && Array.isArray(r.drift_profile))
      .map((r) => ({
        label: `${r.time} · ${r.building} (${r.floors}F)`,
        building: r.building,
        stories: r.floors,
        t1_s: r.t1_num || 0,
        roof_mm: r.roof_num || 0,
        drift_mm: r.drift_num || 0,
        shear_kn: r.shear_kn || 0,
        drift_profile: r.drift_profile,
      }));
    renderHistoryTable();
    renderCompareSelectors();
  } catch {
    try { state.history = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch { state.history = []; }
    renderHistoryTable();
  }
}

function downloadCsv(filename, rows) {
  const csv = rows.map((r) => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------- Boot ----------------
async function boot() {
  initTheme();
  await initNavbar();
  initTabs();

  scene3d = new BuildingScene3D(document.getElementById('scene3d-canvas'), ({ time, roofMm, frac }) => {
    document.getElementById('vp-readout').textContent = `t = ${time.toFixed(2)} s · Roof = ${roofMm.toFixed(1)} mm`;
    if (state.view === 'quake' || document.getElementById('vp-mode-badge').textContent === '3D Quake') {
      document.getElementById('vp-scrubber').value = String(Math.round(frac * 100));
    }
  });
  document.getElementById('vp-subtitle').textContent = `${scene3d.rendererType} · Drag to rotate · Scroll to zoom`;

  renderFloorRows(4);

  const [presetsJson] = await Promise.all([
    fetch('/api/presets').then((r) => r.json()).catch(() => ({ presets: [] })),
    refreshSavedBuildings(),
    refreshHistoryFromDb(),
  ]);
  state.presets = presetsJson.presets || [];
  const presetSel = document.getElementById('q-preset');
  state.presets.forEach((p) => presetSel.add(new Option(p.name, p.name)));

  if (state.savedBuildings.length > 0) {
    applyBuildingToForm(state.savedBuildings[0]);
  }

  // Navigation events
  document.querySelectorAll('[data-nav]').forEach((el) => {
    el.addEventListener('click', (e) => { e.preventDefault(); switchView(el.dataset.nav); });
  });
  document.querySelectorAll('[data-jump]').forEach((el) => {
    el.addEventListener('click', () => switchView(el.dataset.jump));
  });

  // Building form events
  document.getElementById('b-floors').addEventListener('input', (e) => {
    const n = Number(e.target.value);
    document.getElementById('b-floors-out').textContent = String(n);
    renderFloorRows(n);
    markDirtyAndSync3D();
  });

  document.getElementById('building-form').addEventListener('input', (e) => {
    if (e.target.id !== 'b-floors') markDirtyAndSync3D();
  });

  document.getElementById('saved-building-select').addEventListener('change', (e) => {
    const picked = state.savedBuildings.find((b) => String(b.id) === e.target.value);
    if (picked) {
      applyBuildingToForm(picked);
      document.getElementById('save-feedback').textContent = `Loaded "${picked.name}"`;
    }
  });

  document.getElementById('delete-building-btn').addEventListener('click', async () => {
    const id = Number(document.getElementById('saved-building-select').value);
    if (!id) return;
    const res = await fetch(`/api/buildings/${id}`, { method: 'DELETE' });
    if (!res.ok) return;
    if (state.savedModel?.id === id) {
      state.savedModel = null;
      state.isDirty = false;
      state.matrices = null;
      state.modal = null;
      state.quake = null;
    }
    await Promise.all([refreshSavedBuildings(), refreshHistoryFromDb()]);
    if (state.savedBuildings.length > 0 && !state.savedModel) {
      applyBuildingToForm(state.savedBuildings[0]);
    }
    refreshStatusUI();
  });

  document.getElementById('apply-u-mass').addEventListener('click', () => {
    const val = Number(document.getElementById('u-mass').value);
    if (val > 0) document.querySelectorAll('.m-in').forEach((el) => { el.value = String(val); });
    markDirtyAndSync3D();
  });

  document.getElementById('apply-u-stiff').addEventListener('click', () => {
    const val = Number(document.getElementById('u-stiff').value);
    if (val >= 100) document.querySelectorAll('.k-in').forEach((el) => { el.value = String(val); });
    markDirtyAndSync3D();
  });

  document.getElementById('building-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const draft = getDraftConfig();
    if (draft.floors < 3 || draft.floors > 5) {
      document.getElementById('save-feedback').textContent = 'Building must have between 3 and 5 storeys.';
      return;
    }
    if (!form.checkValidity()) {
      [...form.elements].forEach((el) => { if (el.matches?.('input')) { el.dataset.touched = '1'; syncFieldAria(el, true); } });
      form.querySelector(':invalid')?.focus();
      return;
    }
    try {
      const saved = await saveBuildingToDb(draft);
      document.getElementById('save-feedback').textContent = `Saved (#${saved.id}) at ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      document.getElementById('save-feedback').textContent = err.message;
    }
  });

  document.getElementById('reset-model-btn').addEventListener('click', () => {
    document.getElementById('b-name').value = '4-Story Frame';
    document.getElementById('b-type').selectedIndex = 0;
    document.getElementById('b-floors').value = '4';
    document.getElementById('b-floors-out').textContent = '4';
    document.getElementById('b-damping').value = '0.05';
    renderFloorRows(4, [120, 120, 120, 120], [25000, 25000, 25000, 25000]);
    markDirtyAndSync3D();
  });

  // Action buttons
  document.getElementById('btn-gen-matrices').addEventListener('click', runMatrices);
  document.getElementById('btn-run-modes').addEventListener('click', runModal);
  document.getElementById('btn-check-resonance').addEventListener('click', runResonanceCheck);
  document.getElementById('btn-compare-stiffness').addEventListener('click', runStiffnessComparison);
  document.getElementById('mode-select').addEventListener('change', (e) => {
    if (!state.modal) return;
    const idx = Number(e.target.value);
    scene3d.setModeShape(state.modal.phi_normalized.map((r) => r[idx]), state.modal.frequencies_hz[idx]);
    playBtn.textContent = scene3d.playing ? 'Pause' : 'Play';
  });

  document.querySelectorAll('.seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('is-active', b === btn));
      state.quakeSource = btn.dataset.qsrc;
      document.getElementById('quake-preset-controls').hidden = state.quakeSource !== 'preset';
      document.getElementById('quake-csv-controls').hidden = state.quakeSource !== 'csv';
    });
  });

  document.getElementById('q-pga').addEventListener('input', (e) => { document.getElementById('q-pga-out').textContent = `${Number(e.target.value).toFixed(2)} g`; });
  document.getElementById('q-dur').addEventListener('input', (e) => { document.getElementById('q-dur-out').textContent = `${e.target.value} s`; });
  document.getElementById('btn-run-quake').addEventListener('click', runEarthquake);
  document.getElementById('cmp-a').addEventListener('change', updateCompareView);
  document.getElementById('cmp-b').addEventListener('change', updateCompareView);

  // 3D Controls
  const playBtn = document.getElementById('vp-play-btn');
  playBtn.addEventListener('click', () => {
    const next = !scene3d.playing;
    scene3d.setPlaying(next);
    playBtn.textContent = next ? 'Pause' : 'Play';
  });
  document.getElementById('vp-scrubber').addEventListener('input', (e) => {
    scene3d.setPlaying(false);
    playBtn.textContent = 'Play';
    scene3d.seekFraction(Number(e.target.value) / 100);
  });
  document.getElementById('vp-speed').addEventListener('change', (e) => scene3d.setSpeed(Number(e.target.value)));
  document.getElementById('vp-reset-cam').addEventListener('click', () => scene3d.resetCamera());
  document.getElementById('vp-demo-quake').addEventListener('click', async () => {
    if (!state.savedModel || state.isDirty) {
      try {
        await saveBuildingToDb(getDraftConfig());
      } catch {
        state.savedModel = getDraftConfig();
        state.isDirty = false;
      }
    }
    await runEarthquake();
    scene3d.setPlaying(true);
    playBtn.textContent = 'Pause';
  });

  // CSV downloads & History clear
  document.getElementById('dl-m-csv').addEventListener('click', () => state.matrices && downloadCsv('mass_matrix.csv', state.matrices.M));
  document.getElementById('dl-k-csv').addEventListener('click', () => state.matrices && downloadCsv('stiffness_matrix.csv', state.matrices.K));
  document.getElementById('dl-modes-csv').addEventListener('click', () => {
    if (!state.modal) return;
    const rows = [['Mode', 'Speed_Hz', 'Period_s', 'Weight_Share_pct']];
    state.modal.frequencies_hz.forEach((f, i) => rows.push([i + 1, f, state.modal.periods_s[i], state.modal.mass_ratio_pct[i]]));
    downloadCsv('modal_summary.csv', rows);
  });
  document.getElementById('dl-quake-csv').addEventListener('click', () => {
    if (!state.quake) return;
    const rows = [['Level', 'Peak_Move_mm', 'Peak_Shift_mm']];
    state.quake.peak_floor_disp_mm.forEach((d, i) => rows.push([i + 1, d, state.quake.peak_story_drift_mm[i]]));
    downloadCsv('seismic_envelope.csv', rows);
  });
  document.getElementById('dl-history-csv').addEventListener('click', () => {
    const rows = [['Time', 'Type', 'Building', 'Floors', 'T1_s', 'Roof_mm', 'Max_Shift_mm', 'Risk_Level']];
    state.history.forEach((h) => rows.push([h.time, h.type, h.building, h.floors, h.t1_s, h.roof_mm, h.drift_mm, h.risk_level || '']));
    downloadCsv('earthquick_history.csv', rows);
  });
  document.getElementById('clear-history-btn').addEventListener('click', async () => {
    await fetch('/api/history', { method: 'DELETE' }).catch(() => {});
    state.history = [];
    state.compareRuns = [];
    localStorage.removeItem(STORAGE_KEY);
    renderHistoryTable();
    refreshStatusUI();
  });

  refreshStatusUI();
}

boot();
