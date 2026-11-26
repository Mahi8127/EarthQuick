# EarthQuick — 3D Structural Vibration & Earthquake Lab

Interactive 3D structural dynamics web application and linear-algebra solver built with Python (Starlette, NumPy, SciPy, PostgreSQL via `psycopg` v3) and Three.js.

## Features

- **Building Setup (2–10 Stories):** Configure per-floor weights (tonnes), story stiffnesses (`kN/m`), and viscous damping ratio with live 3D frame preview.
- **Matrix Assembly (`M` & `K`):** Computes diagonal mass and tridiagonal stiffness matrices with SPD validation, conditioning, sparsity, and interactive heatmaps.
- **Modal Analysis:** Solves the generalized eigenvalue problem $K \phi = \omega^2 M \phi$ for eigenvalues ($\omega^2$), natural frequencies ($f_n$), periods ($T_n$), mass-participation ratios, and normalized 3D mode shapes.
- **Earthquake Simulator:** Runs modal Newmark-Beta ($\gamma = 0.5$, $\beta = 0.25$) time-history integration on built-in synthetic ground motions or uploaded CSV accelerograms, computing peak displacements, interstory drifts, base shear, and structural drift risk level.
- **PostgreSQL Persistence (with Local SQLite Fallback):** Saves and retrieves building configurations, floor parameters, modal analyses (eigenvalues, frequencies, mode shapes), and earthquake/risk runs cleanly across Render restarts.

## Database Architecture (`psycopg` v3 PostgreSQL)

EarthQuick reads `DATABASE_URL` from the environment (`db.py`) and connects to **PostgreSQL** via **`psycopg` (version 3)** with parameterized queries, atomic transactions (`commit` / `rollback`), automatic schema creation on Starlette app startup (`lifespan`), and foreign-key cascades (`ON DELETE CASCADE` / `ON DELETE SET NULL`):

- **Production / Render PostgreSQL (`DATABASE_URL` set):** Connects directly to PostgreSQL (supports both `postgresql://` and Render's legacy `postgres://` prefix).
- **Local Development Fallback (`DATABASE_URL` unset):** Automatically falls back to local SQLite (`EARTHQUICK_DB_PATH`, defaulting to `./earthquick.db`, ignored by Git via `*.db`) so developers can run locally without provisioning a database server or embedding credentials.

### Schema Tables

1. `buildings` — `id`, `name`, `building_type`, `floors`, `damping_ratio`, `created_at`
2. `building_floors` — `id`, `building_id` (FK -> `buildings.id ON DELETE CASCADE`), `floor_index`, `mass_t`, `stiffness_kn_m`
3. `modal_analyses` — `id`, `building_id` (FK CASCADE), `is_spd`, `cond_k`, `eigenvalues_json`, `omega_json`, `frequencies_hz_json`, `periods_s_json`, `mode_shapes_json`, `participation_json`, `mass_ratio_pct_json`, `eigen_residual`, `created_at`
4. `earthquake_runs` — `id`, `building_id` (FK CASCADE), `modal_id` (FK `ON DELETE SET NULL`), `source_type`, `record_name`, `pga_g`, `duration_s`, `peak_roof_disp_mm`, `max_interstory_drift_mm`, `critical_story`, `peak_base_shear_kn`, `peak_floor_disp_json`, `peak_story_drift_json`, `risk_level`, `created_at`

### REST API Endpoints

- `GET /api/health` — Server status and active database backend (`postgres` or `sqlite`)
- `GET /api/buildings` / `POST /api/buildings` — List saved buildings or create a building with floor rows
- `GET /api/buildings/{id}` / `DELETE /api/buildings/{id}` — Retrieve or cascade-delete a building
- `GET /api/history` / `DELETE /api/history` — Retrieve or clear saved analysis history
- `GET /api/runs/{modal|quake}/{id}` — Retrieve full saved modal or earthquake run details
- `POST /api/matrices` — Compute mass & stiffness matrix metrics
- `POST /api/modal` — Compute modal analysis and persist eigenvalues, frequencies, and mode shapes
- `POST /api/earthquake` / `POST /api/earthquake/csv` — Run seismic time-history analysis and persist response & drift risk

## Render PostgreSQL Setup

1. Create a **Render PostgreSQL** database instance in the Render dashboard.
2. In your EarthQuick **Web Service -> Environment**, add:
   - `DATABASE_URL` = the **Internal Database URL** from your Render PostgreSQL instance (starts with `postgresql://...` or `postgres://...`).
3. Ensure the Render **Start Command** is:
   ```bash
   uvicorn server:app --host 0.0.0.0 --port $PORT
   ```
4. Never commit `.env` files or real credentials into Git.

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
