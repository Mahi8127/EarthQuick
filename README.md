# EarthQuick — Building Vibration and Earthquake Analyzer

Interactive 3D structural dynamics web application and linear-algebra solver built with Python (Starlette, NumPy, SciPy, PostgreSQL via `psycopg` v3) and Three.js.

## Features

- **Building Setup (3–5 Storeys):** Configure buildings strictly between **3 and 5 storeys** with per-floor masses (tonnes), storey stiffnesses (`kN/m`), and viscous damping ratio with live 3D shear-frame preview.
- **Matrix Assembly (`M` & `K`):** Computes diagonal mass and tridiagonal stiffness matrices with SPD validation, condition number, sparsity, and interactive matrix heatmaps.
- **Modal Analysis & 3D Mode Animation:** Solves $K \phi = \omega^2 M \phi$ for eigenvalues ($\omega^2$), natural frequencies ($f_n$), periods ($T_n$), mass-participation ratios, and normalized mode shapes animated smoothly in 3D (returning to rest when paused or switched).
- **Earthquake Frequency Resonance Check:** Compares every building natural frequency against a user-defined earthquake frequency band `[min_Hz, max_Hz]`, flagging exact modes at risk or confirming no overlap (kept completely separate from drift-based seismic risk classification).
- **Storey Stiffness Comparison:** Adjust one storey's stiffness by percentage or new `kN/m` value, recomputes $K$ and modal frequencies, charts original vs modified frequencies, shows percentage shifts, and explains the structural dynamics impact.
- **Earthquake Simulator:** Runs modal Newmark-Beta ($\gamma = 0.5$, $\beta = 0.25$) time-history integration on synthetic presets or uploaded CSV accelerograms, computing peak floor displacements, interstorey drifts, base shear, and drift-based seismic risk level (`Low`, `Moderate`, `High`, `Severe`).
- **PostgreSQL Persistence (with Local SQLite Fallback):** Automatically persists buildings, floors, modal results, earthquake runs, resonance checks, and stiffness comparisons via `psycopg` v3 (`DATABASE_URL`) or local SQLite fallback.

## Linear Algebra Foundations

- **Mass Matrix ($M$):** An $n \times n$ diagonal positive-definite matrix storing each storey's lumped floor mass $m_i$, mapping accelerations $\ddot{u}$ to inertial forces $M\ddot{u}$.
- **Stiffness Matrix ($K$):** An $n \times n$ symmetric positive-definite tridiagonal matrix assembled from interstorey shear stiffnesses $k_i$ where $K u = f$ relates lateral floor displacements $u$ to restoring forces.
- **Eigenvalues & Eigenvectors:** Solving the generalized eigenproblem $(K - \lambda M)\phi = 0$ yields eigenvalues $\lambda_i = \omega_i^2$ (squared angular frequencies) and eigenvectors $\phi_i$ (mode shapes).
- **Natural Frequencies ($f_i$):** Computed from eigenvalues as $f_i = \frac{\sqrt{\lambda_i}}{2\pi}$ Hz, with corresponding sway periods $T_i = 1 / f_i$ seconds.
- **Mode Shapes ($\phi_i$):** Eigenvectors representing the relative lateral deflection profile of the 3–5 storeys when oscillating purely in mode $i$ (normalized so max displacement magnitude is $1$).
- **Orthogonality:** Distinct mode shapes satisfy $M$-orthogonality ($\phi_i^T M \phi_j = 0$) and $K$-orthogonality ($\phi_i^T K \phi_j = 0$ for $i \neq j$).
- **Diagonalization:** Assembling mass-normalized modes into $\Phi$ diagonalizes the coupled equations via $\Phi^T M \Phi = I$ and $\Phi^T K \Phi = \Lambda = \mathrm{diag}(\omega_i^2)$, decoupling $n$ coupled floors into $n$ independent SDOF modal equations.

## How Resonance Detection Works

1. User enters a ground-motion excitation frequency range `[freq_min_hz, freq_max_hz]` (Hz).
2. `check_earthquake_resonance()` evaluates **every** modal natural frequency $f_1, \dots, f_n$ of the building.
3. Any mode satisfying $f_{\min} \le f_i \le f_{\max}$ is flagged as a potential resonance risk with its mode number and natural frequency; if none match, it reports no frequency overlap detected.
4. This frequency-band resonance risk is distinct from `classify_seismic_risk()`, which classifies time-history interstorey drift ratio ($\Delta_{\max} / h_{\text{storey}}$).

## How Storey Stiffness Comparison Works

1. Select a target storey ($1 \dots n$) and specify either a percentage change (`pct_change`) or an absolute target stiffness (`new_stiffness` in `kN/m`).
2. `compare_storey_stiffness()` rebuilds the modified tridiagonal stiffness matrix $K_{\text{mod}}$ and solves the updated generalized eigenproblem.
3. Original vs modified frequencies and percentage shifts $\frac{f_{i,\text{mod}} - f_{i,\text{orig}}}{f_{i,\text{orig}}} \times 100\%$ are displayed alongside a physical explanation grounded in Rayleigh's quotient $\omega_i^2 = \frac{\phi_i^T K \phi_i}{\phi_i^T M \phi_i}$.

## DSA Mode Sorting & Complexity

- `merge_sort_modes()` in [engine.py](engine.py) sorts vibration modes by ascending natural frequency (`frequency_hz`) using a recursive **Merge Sort** implementation (without relying on Python's built-in `sorted()`).
- **Time Complexity:** $O(n \log n)$ in best, average, and worst cases.
- **Space Complexity:** $O(n)$ auxiliary memory for stable divide-and-conquer merging.

## Database Architecture (`psycopg` v3 PostgreSQL)

EarthQuick reads `DATABASE_URL` from the environment (`db.py`) and connects to **PostgreSQL** via **`psycopg` (version 3)** with parameterized queries, atomic transactions (`commit` / `rollback`), automatic schema initialization on Starlette app startup (`lifespan`), and foreign-key cascades (`ON DELETE CASCADE` / `ON DELETE SET NULL`):

- **Production / Render PostgreSQL (`DATABASE_URL` set):** Connects to PostgreSQL (supports both `postgresql://` and Render's `postgres://` URLs).
- **Local Development Fallback (`DATABASE_URL` unset):** Falls back cleanly to local SQLite (`EARTHQUICK_DB_PATH`, defaulting to `./earthquick.db`) with no hardcoded credentials.

### Schema Tables (6)

1. `buildings` — `id`, `name`, `building_type`, `floors` (`CHECK (floors >= 3 AND floors <= 5)`), `damping_ratio`, `created_at`
2. `building_floors` — `id`, `building_id` (FK CASCADE), `floor_index`, `mass_t`, `stiffness_kn_m`
3. `modal_analyses` — `id`, `building_id` (FK CASCADE), eigenvalues, `omega`, `frequencies_hz`, `periods_s`, mode shapes, participation factors, mass ratios, `eigen_residual`, `created_at`
4. `earthquake_runs` — `id`, `building_id` (FK CASCADE), `modal_id` (FK SET NULL), source/record metadata, peak floor/roof/drift/shear metrics, `risk_level`, `created_at`
5. `resonance_checks` — `id`, `building_id` (FK CASCADE), `modal_id` (FK SET NULL), `freq_min_hz`, `freq_max_hz`, `has_resonance_risk`, `at_risk_modes_json`, `modes_json`, `summary`, `created_at`
6. `stiffness_comparisons` — `id`, `building_id` (FK CASCADE), `story_index`, `orig_stiffness_kn_m`, `mod_stiffness_kn_m`, `pct_change`, `modes_json`, `explanation`, `created_at`

### REST API Endpoints

- `GET /api/health` — Server status and active database backend (`postgres` or `sqlite`)
- `GET /api/buildings` / `POST /api/buildings` — List saved buildings or create a 3–5 storey building
- `GET /api/buildings/{id}` / `DELETE /api/buildings/{id}` — Retrieve or cascade-delete a building
- `GET /api/history` / `DELETE /api/history` — Retrieve or clear saved analysis history
- `GET /api/runs/{modal|quake|resonance|stiffness}/{id}` — Retrieve full saved run details
- `POST /api/matrices` — Assemble & inspect mass and stiffness matrices
- `POST /api/modal` — Solve vibration modes and persist eigenvalues & mode shapes
- `POST /api/resonance` — Run earthquake frequency resonance check and persist result
- `POST /api/stiffness-compare` — Run storey stiffness comparison and persist result
- `POST /api/earthquake` / `POST /api/earthquake/csv` — Run seismic time-history analysis and persist response & drift risk

## Render Deployment Environment Variables

- `DATABASE_URL`: Internal Database URL from your Render PostgreSQL instance (`postgresql://...` or `postgres://...`).
- Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`

## Local Setup & Testing

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt

# Option A: Local SQLite fallback (zero DB config needed)
uvicorn server:app --host 0.0.0.0 --port 8501

# Option B: Local PostgreSQL
set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/earthquick
uvicorn server:app --host 0.0.0.0 --port 8501

# Run full test suite
pytest -v
```
