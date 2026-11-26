# EarthQuick — 3D Structural Vibration & Earthquake Lab

Interactive 3D structural dynamics web application and linear-algebra solver built with Python (Starlette, NumPy, SciPy, built-in `sqlite3`) and Three.js.

## Features

- **Building Setup (2–10 Stories):** Configure per-floor weights (tonnes), story stiffnesses (`kN/m`), and viscous damping ratio with live 3D frame preview.
- **Matrix Assembly (`M` & `K`):** Computes diagonal mass and tridiagonal stiffness matrices with SPD validation, conditioning, sparsity, and interactive heatmaps.
- **Modal Analysis:** Solves the generalized eigenvalue problem $K \phi = \omega^2 M \phi$ for eigenvalues ($\omega^2$), natural frequencies ($f_n$), periods ($T_n$), mass-participation ratios, and normalized 3D mode shapes.
- **Earthquake Simulator:** Runs modal Newmark-Beta ($\gamma = 0.5$, $\beta = 0.25$) time-history integration on built-in synthetic ground motions or uploaded CSV accelerograms, computing peak displacements, interstory drifts, base shear, and structural drift risk level.
- **SQLite Persistence:** Automatically saves and retrieves building configurations, floor parameters, modal analyses (eigenvalues, frequencies, mode shapes), and earthquake/risk runs across browser reloads.

## Database Architecture (`sqlite3`)

EarthQuick uses Python's built-in `sqlite3` library (`db.py`) with foreign-key cascading enabled (`PRAGMA foreign_keys = ON`) and WAL mode (`PRAGMA journal_mode = WAL`):

- **Database file:** Configured via `EARTHQUICK_DB_PATH` environment variable (defaults to `./earthquick.db`, ignored by Git via `*.db`).
- **Tables:**
  1. `buildings` — `id`, `name`, `building_type`, `floors`, `damping_ratio`, `created_at`
  2. `building_floors` — `id`, `building_id` (FK -> `buildings.id ON DELETE CASCADE`), `floor_index`, `mass_t`, `stiffness_kn_m`
  3. `modal_analyses` — `id`, `building_id` (FK CASCADE), `is_spd`, `cond_k`, `eigenvalues_json`, `omega_json`, `frequencies_hz_json`, `periods_s_json`, `mode_shapes_json`, `participation_json`, `mass_ratio_pct_json`, `eigen_residual`, `created_at`
  4. `earthquake_runs` — `id`, `building_id` (FK CASCADE), `modal_id` (FK `ON DELETE SET NULL`), `source_type`, `record_name`, `pga_g`, `duration_s`, `peak_roof_disp_mm`, `max_interstory_drift_mm`, `critical_story`, `peak_base_shear_kn`, `peak_floor_disp_json`, `peak_story_drift_json`, `risk_level`, `created_at`

### REST API Endpoints

- `GET /api/buildings` — List saved buildings and per-floor arrays
- `POST /api/buildings` — Create a persisted building + floor rows
- `GET /api/buildings/{id}` / `DELETE /api/buildings/{id}` — Retrieve or cascade-delete a building
- `GET /api/history` / `DELETE /api/history` — Retrieve or clear saved analysis history
- `GET /api/runs/{modal|quake}/{id}` — Retrieve full saved modal or earthquake run details
- `POST /api/matrices` — Compute mass & stiffness matrix metrics
- `POST /api/modal` — Compute modal analysis and persist eigenvalues, frequencies, and mode shapes
- `POST /api/earthquake` / `POST /api/earthquake/csv` — Run seismic time-history analysis and persist response & drift risk

## Local Setup & Testing

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt

# Run the server
uvicorn server:app --host 0.0.0.0 --port 8501

# Run full test suite
pytest -v
```
