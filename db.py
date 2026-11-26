"""SQLite persistence layer for EarthQuick buildings, modal analyses, and seismic runs."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Sequence

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "earthquick.db"

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS buildings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    building_type   TEXT NOT NULL DEFAULT 'custom',
    floors          INTEGER NOT NULL CHECK (floors >= 2),
    damping_ratio   REAL NOT NULL CHECK (damping_ratio >= 0.0 AND damping_ratio <= 0.5),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS building_floors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id     INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    floor_index     INTEGER NOT NULL CHECK (floor_index >= 1),
    mass_t          REAL NOT NULL CHECK (mass_t > 0.0),
    stiffness_kn_m  REAL NOT NULL CHECK (stiffness_kn_m > 0.0),
    UNIQUE (building_id, floor_index)
);

CREATE TABLE IF NOT EXISTS modal_analyses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id         INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    is_spd              INTEGER NOT NULL,
    cond_k              REAL NOT NULL,
    eigenvalues_json    TEXT NOT NULL,
    omega_json          TEXT NOT NULL,
    frequencies_hz_json TEXT NOT NULL,
    periods_s_json      TEXT NOT NULL,
    mode_shapes_json    TEXT NOT NULL,
    participation_json  TEXT NOT NULL,
    mass_ratio_pct_json TEXT NOT NULL,
    eigen_residual      REAL NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS earthquake_runs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id              INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    modal_id                 INTEGER REFERENCES modal_analyses(id) ON DELETE SET NULL,
    source_type              TEXT NOT NULL,
    record_name              TEXT NOT NULL,
    pga_g                    REAL NOT NULL,
    duration_s               REAL NOT NULL,
    peak_roof_disp_mm        REAL NOT NULL,
    max_interstory_drift_mm  REAL NOT NULL,
    critical_story           INTEGER NOT NULL,
    peak_base_shear_kn       REAL NOT NULL,
    peak_floor_disp_json     TEXT NOT NULL,
    peak_story_drift_json    TEXT NOT NULL,
    risk_level               TEXT NOT NULL,
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db_path(db_path: Path | str | None = None) -> Path:
    """Resolve active SQLite database file path from explicit arg or EARTHQUICK_DB_PATH."""
    if db_path is not None:
        return Path(db_path)
    env_path = os.environ.get("EARTHQUICK_DB_PATH")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enabled and dict-like row access."""
    resolved = get_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Create EarthQuick SQLite tables if they do not exist."""
    with get_connection(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)


def _open_ready_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Ensure tables exist on the target DB before running a query."""
    init_db(db_path)
    return get_connection(db_path)


def _validate_building_inputs(
    name: str,
    damping_ratio: float,
    masses: Sequence[float],
    stiffnesses: Sequence[float],
) -> tuple[str, float, list[float], list[float]]:
    clean_name = str(name).strip() or "Building"
    zeta = float(damping_ratio)
    if not (0.0 <= zeta <= 0.5):
        raise ValueError("Damping ratio must be between 0.0 and 0.5.")
    m_list = [float(v) for v in masses]
    k_list = [float(v) for v in stiffnesses]
    if len(m_list) < 2 or len(m_list) != len(k_list):
        raise ValueError("masses and stiffnesses must match in length (>= 2 floors).")
    if any(v <= 0.0 for v in m_list) or any(v <= 0.0 for v in k_list):
        raise ValueError("All floor masses and story stiffnesses must be > 0.")
    return clean_name, zeta, m_list, k_list


def _hydrate_building(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    floor_rows = conn.execute(
        "SELECT floor_index, mass_t, stiffness_kn_m FROM building_floors "
        "WHERE building_id = ? ORDER BY floor_index ASC",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "name": row["name"],
        "building_type": row["building_type"],
        "floors": row["floors"],
        "damping_ratio": row["damping_ratio"],
        "masses": [float(f["mass_t"]) for f in floor_rows],
        "stiffnesses": [float(f["stiffness_kn_m"]) for f in floor_rows],
        "created_at": row["created_at"],
    }


def save_building(
    name: str,
    building_type: str,
    damping_ratio: float,
    masses: Sequence[float],
    stiffnesses: Sequence[float],
    db_path: Path | str | None = None,
) -> dict:
    """Persist a building configuration and its per-floor parameters."""
    clean_name, zeta, m_list, k_list = _validate_building_inputs(
        name, damping_ratio, masses, stiffnesses
    )
    b_type = str(building_type or "custom").strip() or "custom"
    with _open_ready_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO buildings (name, building_type, floors, damping_ratio) VALUES (?, ?, ?, ?)",
            (clean_name, b_type, len(m_list), zeta),
        )
        building_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO building_floors (building_id, floor_index, mass_t, stiffness_kn_m) "
            "VALUES (?, ?, ?, ?)",
            [(building_id, idx + 1, m_list[idx], k_list[idx]) for idx in range(len(m_list))],
        )
        row = conn.execute("SELECT * FROM buildings WHERE id = ?", (building_id,)).fetchone()
        return _hydrate_building(conn, row)


def list_buildings(db_path: Path | str | None = None) -> list[dict]:
    """Return all saved buildings ordered from newest to oldest."""
    with _open_ready_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM buildings ORDER BY id DESC").fetchall()
        return [_hydrate_building(conn, row) for row in rows]


def get_building(building_id: int, db_path: Path | str | None = None) -> dict | None:
    """Return a saved building with its floor parameters, or None if missing."""
    with _open_ready_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM buildings WHERE id = ?", (building_id,)).fetchone()
        return _hydrate_building(conn, row) if row else None


def delete_building(building_id: int, db_path: Path | str | None = None) -> bool:
    """Delete a building and cascade-remove its floors, modal analyses, and quake runs."""
    with _open_ready_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM buildings WHERE id = ?", (building_id,))
        return cur.rowcount > 0


def save_modal_analysis(
    building_id: int,
    matrices_data: dict,
    modal_data: dict,
    db_path: Path | str | None = None,
) -> dict:
    """Persist eigenvalues, natural frequencies, periods, mode shapes, and residuals."""
    with _open_ready_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO modal_analyses (
                building_id, is_spd, cond_k, eigenvalues_json, omega_json,
                frequencies_hz_json, periods_s_json, mode_shapes_json,
                participation_json, mass_ratio_pct_json, eigen_residual
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(building_id),
                int(bool(matrices_data["is_spd"])),
                float(matrices_data["cond_k"]),
                json.dumps(modal_data["eigenvalues"]),
                json.dumps(modal_data["omega"]),
                json.dumps(modal_data["frequencies_hz"]),
                json.dumps(modal_data["periods_s"]),
                json.dumps(modal_data["phi_normalized"]),
                json.dumps(modal_data["participation_factors"]),
                json.dumps(modal_data["mass_ratio_pct"]),
                float(modal_data["eigen_residual"]),
            ),
        )
        row = conn.execute("SELECT * FROM modal_analyses WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_modal_dict(row)


def save_earthquake_run(
    building_id: int,
    modal_id: int | None,
    source_type: str,
    record_name: str,
    duration_s: float,
    eq_data: dict,
    db_path: Path | str | None = None,
) -> dict:
    """Persist peak seismic responses, floor drift profile, and structural risk level."""
    with _open_ready_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO earthquake_runs (
                building_id, modal_id, source_type, record_name, pga_g, duration_s,
                peak_roof_disp_mm, max_interstory_drift_mm, critical_story,
                peak_base_shear_kn, peak_floor_disp_json, peak_story_drift_json, risk_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(building_id),
                int(modal_id) if modal_id is not None else None,
                str(source_type),
                str(record_name),
                float(eq_data["pga_g"]),
                float(duration_s),
                float(eq_data["peak_roof_disp_mm"]),
                float(eq_data["max_interstory_drift_mm"]),
                int(eq_data["critical_story"]),
                float(eq_data["peak_base_shear_kn"]),
                json.dumps(eq_data["peak_floor_disp_mm"]),
                json.dumps(eq_data["peak_story_drift_mm"]),
                str(eq_data["risk_level"]),
            ),
        )
        row = conn.execute("SELECT * FROM earthquake_runs WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_quake_dict(row)


def _row_to_modal_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "building_id": row["building_id"],
        "is_spd": bool(row["is_spd"]),
        "cond_k": float(row["cond_k"]),
        "eigenvalues": json.loads(row["eigenvalues_json"]),
        "omega": json.loads(row["omega_json"]),
        "frequencies_hz": json.loads(row["frequencies_hz_json"]),
        "periods_s": json.loads(row["periods_s_json"]),
        "phi_normalized": json.loads(row["mode_shapes_json"]),
        "participation_factors": json.loads(row["participation_json"]),
        "mass_ratio_pct": json.loads(row["mass_ratio_pct_json"]),
        "eigen_residual": float(row["eigen_residual"]),
        "created_at": row["created_at"],
    }


def _row_to_quake_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "building_id": row["building_id"],
        "modal_id": row["modal_id"],
        "source_type": row["source_type"],
        "record_name": row["record_name"],
        "pga_g": float(row["pga_g"]),
        "duration_s": float(row["duration_s"]),
        "peak_roof_disp_mm": float(row["peak_roof_disp_mm"]),
        "max_interstory_drift_mm": float(row["max_interstory_drift_mm"]),
        "critical_story": int(row["critical_story"]),
        "peak_base_shear_kn": float(row["peak_base_shear_kn"]),
        "peak_floor_disp_mm": json.loads(row["peak_floor_disp_json"]),
        "peak_story_drift_mm": json.loads(row["peak_story_drift_json"]),
        "risk_level": row["risk_level"],
        "created_at": row["created_at"],
    }


def list_history(limit: int = 50, db_path: Path | str | None = None) -> list[dict]:
    """Return unified analysis history across modal runs and earthquake runs."""
    with _open_ready_conn(db_path) as conn:
        quake_rows = conn.execute(
            """
            SELECT e.*, b.name AS building_name, b.floors AS floors, m.periods_s_json
            FROM earthquake_runs e
            JOIN buildings b ON b.id = e.building_id
            LEFT JOIN modal_analyses m ON m.id = e.modal_id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        modal_rows = conn.execute(
            """
            SELECT m.*, b.name AS building_name, b.floors AS floors
            FROM modal_analyses m
            JOIN buildings b ON b.id = m.building_id
            WHERE NOT EXISTS (SELECT 1 FROM earthquake_runs e WHERE e.modal_id = m.id)
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    items: list[dict] = []
    for r in quake_rows:
        periods = json.loads(r["periods_s_json"]) if r["periods_s_json"] else []
        t1 = float(periods[0]) if periods else None
        items.append(
            {
                "id": r["id"],
                "run_type": "quake",
                "type": "Quake",
                "building_id": r["building_id"],
                "building": r["building_name"],
                "floors": r["floors"],
                "t1_s": f"{t1:.2f}" if t1 is not None else "-",
                "t1_num": t1,
                "roof_mm": f"{r['peak_roof_disp_mm']:.1f}",
                "roof_num": float(r["peak_roof_disp_mm"]),
                "drift_mm": f"{r['max_interstory_drift_mm']:.1f}",
                "drift_num": float(r["max_interstory_drift_mm"]),
                "shear_kn": float(r["peak_base_shear_kn"]),
                "drift_profile": json.loads(r["peak_story_drift_json"]),
                "risk_level": r["risk_level"],
                "record_name": r["record_name"],
                "time": r["created_at"],
                "created_at": r["created_at"],
            }
        )

    for r in modal_rows:
        periods = json.loads(r["periods_s_json"])
        t1 = float(periods[0]) if periods else None
        items.append(
            {
                "id": r["id"],
                "run_type": "modal",
                "type": "Modes",
                "building_id": r["building_id"],
                "building": r["building_name"],
                "floors": r["floors"],
                "t1_s": f"{t1:.2f}" if t1 is not None else "-",
                "t1_num": t1,
                "roof_mm": "-",
                "roof_num": None,
                "drift_mm": "-",
                "drift_num": None,
                "shear_kn": None,
                "drift_profile": None,
                "risk_level": None,
                "record_name": None,
                "time": r["created_at"],
                "created_at": r["created_at"],
            }
        )

    items.sort(key=lambda x: (x["created_at"], x["id"]), reverse=True)
    return items[:limit]


def get_run_detail(run_type: str, run_id: int, db_path: Path | str | None = None) -> dict | None:
    """Retrieve complete saved modal or earthquake run details with building info."""
    with _open_ready_conn(db_path) as conn:
        if run_type == "modal":
            row = conn.execute("SELECT * FROM modal_analyses WHERE id = ?", (run_id,)).fetchone()
            if not row:
                return None
            b_row = conn.execute("SELECT * FROM buildings WHERE id = ?", (row["building_id"],)).fetchone()
            return {
                "run_type": "modal",
                "building": _hydrate_building(conn, b_row) if b_row else None,
                "modal": _row_to_modal_dict(row),
            }
        if run_type == "quake":
            row = conn.execute("SELECT * FROM earthquake_runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                return None
            b_row = conn.execute("SELECT * FROM buildings WHERE id = ?", (row["building_id"],)).fetchone()
            m_row = (
                conn.execute("SELECT * FROM modal_analyses WHERE id = ?", (row["modal_id"],)).fetchone()
                if row["modal_id"] is not None
                else None
            )
            return {
                "run_type": "quake",
                "building": _hydrate_building(conn, b_row) if b_row else None,
                "modal": _row_to_modal_dict(m_row) if m_row else None,
                "earthquake": _row_to_quake_dict(row),
            }
        raise ValueError("run_type must be 'modal' or 'quake'.")


def clear_history(db_path: Path | str | None = None) -> None:
    """Remove all saved modal analyses and earthquake runs while keeping buildings intact."""
    with _open_ready_conn(db_path) as conn:
        conn.execute("DELETE FROM earthquake_runs")
        conn.execute("DELETE FROM modal_analyses")
