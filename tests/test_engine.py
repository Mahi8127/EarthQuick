"""Unit tests for EarthQuick Phase 3 structural dynamics engine."""

import math
import numpy as np
import pytest

from engine import (
    GRAVITY,
    analyze_matrices,
    assemble_mass_matrix,
    assemble_stiffness_matrix,
    generate_ground_motion,
    simulate_earthquake,
    solve_modal_analysis,
)


def test_matrix_assembly_2dof_and_3dof():
    M = assemble_mass_matrix([100.0, 80.0])
    K = assemble_stiffness_matrix([20000.0, 15000.0])
    np.testing.assert_allclose(M, [[100.0, 0.0], [0.0, 80.0]])
    np.testing.assert_allclose(K, [[35000.0, -15000.0], [-15000.0, 15000.0]])

    K3 = assemble_stiffness_matrix([10.0, 20.0, 30.0])
    np.testing.assert_allclose(
        K3,
        [
            [30.0, -20.0, 0.0],
            [-20.0, 50.0, -30.0],
            [0.0, -30.0, 30.0],
        ],
    )
    props = analyze_matrices(assemble_mass_matrix([1.0, 1.0, 1.0]), K3)
    assert props["is_spd"] is True
    assert props["m_sym_err"] == 0.0
    assert props["k_sym_err"] == 0.0
    assert props["nnz_k"] == 7


def test_modal_analysis_matches_closed_form_2dof():
    m, k = 120.0, 25000.0
    M = assemble_mass_matrix([m, m])
    K = assemble_stiffness_matrix([k, k])
    res = solve_modal_analysis(M, K)

    # Exact eigenvalues for uniform 2-DOF shear building: (k/m) * (3 -/+ sqrt(5)) / 2
    expected_lam1 = (k / m) * (3.0 - math.sqrt(5.0)) / 2.0
    expected_lam2 = (k / m) * (3.0 + math.sqrt(5.0)) / 2.0
    np.testing.assert_allclose(res["eigenvalues"], [expected_lam1, expected_lam2], rtol=1e-12)

    assert res["m_ortho_err"] < 1e-12
    assert res["k_ortho_err"] < 1e-8
    assert res["eigen_residual"] < 1e-8
    assert math.isclose(float(np.sum(res["mass_ratio_pct"])), 100.0, rel_tol=1e-12)
    assert res["phi_normalized"][-1, 0] == pytest.approx(1.0)


def test_invalid_inputs_raise_value_error():
    with pytest.raises(ValueError):
        assemble_mass_matrix([100.0])
    with pytest.raises(ValueError):
        assemble_mass_matrix([100.0, -5.0])
    with pytest.raises(ValueError):
        assemble_stiffness_matrix([25000.0, 0.0])
    with pytest.raises(ValueError):
        analyze_matrices(assemble_mass_matrix([1.0, 1.0]), assemble_stiffness_matrix([1.0, 1.0, 1.0]))


def test_earthquake_simulation_physics_and_damping():
    M = assemble_mass_matrix([100.0, 100.0, 100.0])
    K = assemble_stiffness_matrix([30000.0, 25000.0, 20000.0])

    # Static equilibrium check under constant sustained ground acceleration a_g = 0.2g
    t_const = np.arange(0.0, 12.0, 0.005)
    ag_const = np.full_like(t_const, 0.2)
    sim_const = simulate_earthquake(M, K, 0.25, t_const, ag_const)
    u_static = np.linalg.solve(K, -M @ np.ones(3) * (0.2 * GRAVITY))
    np.testing.assert_allclose(sim_const["u_m"][:, -1], u_static, rtol=1e-3)

    # Zero excitation gives zero motion; higher damping lowers peak response on broadband quake
    t, ag = generate_ground_motion("Broadband Seismic Pulse", duration_s=15.0, dt=0.01, pga_g=0.35)
    assert math.isclose(float(np.max(np.abs(ag))), 0.35, rel_tol=1e-9)

    sim_zero = simulate_earthquake(M, K, 0.05, t, np.zeros_like(t))
    assert sim_zero["peak_roof_disp_mm"] == 0.0
    assert sim_zero["peak_base_shear_kn"] == 0.0

    sim_low = simulate_earthquake(M, K, 0.01, t, ag)
    sim_high = simulate_earthquake(M, K, 0.12, t, ag)
    assert sim_high["peak_roof_disp_mm"] < sim_low["peak_roof_disp_mm"]
    # Base shear k1 * u1 matches total restoring force sum
    assert sim_low["peak_base_shear_kn"] == pytest.approx(float(np.max(np.abs(K[0, 0] * 0 + 30000.0 * sim_low["u_m"][0]))))
