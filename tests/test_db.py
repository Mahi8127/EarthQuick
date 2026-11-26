"""SQLite database persistence tests for EarthQuick."""

from __future__ import annotations

import pytest

import db
from engine import (
    analyze_matrices,
    assemble_mass_matrix,
    assemble_stiffness_matrix,
    generate_ground_motion,
    simulate_earthquake,
    solve_modal_analysis,
)


def test_building_floor_crud_and_cascade_delete(tmp_path):
    db_file = tmp_path / "test_eq.db"
    db.init_db(db_file)

    saved = db.save_building(
        name="3-Story Office",
        building_type="Concrete Frame",
        damping_ratio=0.05,
        masses=[150.0, 130.0, 110.0],
        stiffnesses=[32000.0, 28000.0, 24000.0],
        db_path=db_file,
    )
    assert saved["id"] == 1
    assert saved["floors"] == 3
    assert saved["masses"] == [150.0, 130.0, 110.0]
    assert saved["stiffnesses"] == [32000.0, 28000.0, 24000.0]

    fetched = db.get_building(saved["id"], db_path=db_file)
    assert fetched is not None
    assert fetched["name"] == "3-Story Office"
    assert len(db.list_buildings(db_path=db_file)) == 1

    # Add modal + quake run and verify foreign key CASCADE cleanup on building deletion.
    M = assemble_mass_matrix(saved["masses"])
    K = assemble_stiffness_matrix(saved["stiffnesses"])
    mat = analyze_matrices(M, K)
    mod_raw = solve_modal_analysis(M, K)
    mod_payload = {
        "eigenvalues": mod_raw["eigenvalues"].tolist(),
        "omega": mod_raw["omega"].tolist(),
        "frequencies_hz": mod_raw["frequencies_hz"].tolist(),
        "periods_s": mod_raw["periods_s"].tolist(),
        "phi_normalized": mod_raw["phi_normalized"].tolist(),
        "participation_factors": mod_raw["participation_factors"].tolist(),
        "mass_ratio_pct": mod_raw["mass_ratio_pct"].tolist(),
        "eigen_residual": float(mod_raw["eigen_residual"]),
    }
    saved_modal = db.save_modal_analysis(saved["id"], mat, mod_payload, db_path=db_file)

    t, ag = generate_ground_motion("Broadband Seismic Pulse", duration_s=5.0, dt=0.01, pga_g=0.25)
    eq_raw = simulate_earthquake(M, K, 0.05, t, ag)
    eq_payload = {
        "pga_g": eq_raw["pga_g"],
        "peak_roof_disp_mm": eq_raw["peak_roof_disp_mm"],
        "max_interstory_drift_mm": eq_raw["max_interstory_drift_mm"],
        "critical_story": eq_raw["critical_story"],
        "peak_base_shear_kn": eq_raw["peak_base_shear_kn"],
        "peak_floor_disp_mm": eq_raw["peak_floor_disp_mm"].tolist(),
        "peak_story_drift_mm": eq_raw["peak_story_drift_mm"].tolist(),
        "risk_level": eq_raw["risk_level"],
    }
    saved_quake = db.save_earthquake_run(
        saved["id"], saved_modal["id"], "preset", "Broadband Seismic Pulse", 5.0, eq_payload, db_path=db_file
    )

    detail = db.get_run_detail("quake", saved_quake["id"], db_path=db_file)
    assert detail is not None
    assert len(detail["modal"]["eigenvalues"]) == 3
    assert len(detail["modal"]["phi_normalized"]) == 3
    assert detail["earthquake"]["risk_level"] in {"Low", "Moderate", "High", "Severe"}
    assert len(db.list_history(db_path=db_file)) == 1

    assert db.delete_building(saved["id"], db_path=db_file) is True
    assert db.get_building(saved["id"], db_path=db_file) is None
    assert db.get_run_detail("modal", saved_modal["id"], db_path=db_file) is None
    assert db.get_run_detail("quake", saved_quake["id"], db_path=db_file) is None
    assert db.list_history(db_path=db_file) == []


def test_invalid_building_inputs_rejected(tmp_path):
    db_file = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        db.save_building("One Floor", "custom", 0.05, [100.0], [20000.0], db_path=db_file)
    with pytest.raises(ValueError):
        db.save_building("Bad Stiffness", "custom", 0.05, [100.0, 100.0], [20000.0, -5.0], db_path=db_file)
