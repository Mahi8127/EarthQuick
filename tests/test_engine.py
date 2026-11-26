"""Unit tests for EarthQuick structural dynamics engine, DSA sorting, resonance, and stiffness comparison."""

import math
import numpy as np
import pytest
from scipy.linalg import eigh

from engine import (
    GRAVITY,
    analyze_matrices,
    assemble_mass_matrix,
    assemble_stiffness_matrix,
    check_earthquake_resonance,
    classify_seismic_risk,
    compare_storey_stiffness,
    generate_ground_motion,
    merge_sort_modes,
    simulate_earthquake,
    solve_modal_analysis,
    validate_building_inputs,
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


def test_matrix_assembly_edge_and_scipy_spd_reference():
    # Edge case: highly non-uniform 5-DOF mass and stiffness ratio
    masses = [200.0, 180.0, 150.0, 120.0, 90.0]
    stiff = [50000.0, 42000.0, 35000.0, 28000.0, 18000.0]
    M = assemble_mass_matrix(masses)
    K = assemble_stiffness_matrix(stiff)
    assert np.trace(M) == pytest.approx(sum(masses))
    # Row sums except bottom floor equal zero for shear-frame K (rigid-body coupling above story 1)
    np.testing.assert_allclose(np.sum(K[1:], axis=1), np.zeros(4), atol=1e-12)
    # Comparison against numpy Cholesky SPD verification
    np.linalg.cholesky(M)
    np.linalg.cholesky(K)


def test_modal_analysis_matches_closed_form_2dof_and_scipy_4dof():
    m, k = 120.0, 25000.0
    M2 = assemble_mass_matrix([m, m])
    K2 = assemble_stiffness_matrix([k, k])
    res2 = solve_modal_analysis(M2, K2)

    # Exact eigenvalues for uniform 2-DOF shear building: (k/m) * (3 -/+ sqrt(5)) / 2
    expected_lam1 = (k / m) * (3.0 - math.sqrt(5.0)) / 2.0
    expected_lam2 = (k / m) * (3.0 + math.sqrt(5.0)) / 2.0
    np.testing.assert_allclose(res2["eigenvalues"], [expected_lam1, expected_lam2], rtol=1e-12)

    assert res2["m_ortho_err"] < 1e-12
    assert res2["k_ortho_err"] < 1e-8
    assert res2["eigen_residual"] < 1e-8
    assert math.isclose(float(np.sum(res2["mass_ratio_pct"])), 100.0, rel_tol=1e-12)
    assert res2["phi_normalized"][-1, 0] == pytest.approx(1.0)

    # 4-DOF normal case compared directly against SciPy eigh generalized solver
    M4 = assemble_mass_matrix([150.0, 140.0, 130.0, 110.0])
    K4 = assemble_stiffness_matrix([32000.0, 29000.0, 26000.0, 21000.0])
    res4 = solve_modal_analysis(M4, K4)
    ref_lam, ref_phi = eigh(K4, M4)
    ref_omega = np.sqrt(ref_lam)
    ref_freq = ref_omega / (2.0 * np.pi)
    np.testing.assert_allclose(res4["eigenvalues"], ref_lam, rtol=1e-12)
    np.testing.assert_allclose(res4["frequencies_hz"], ref_freq, rtol=1e-12)
    # Check diagonalization Phi^T M Phi = I and Phi^T K Phi = diag(lambda)
    np.testing.assert_allclose(res4["phi_mass_norm"].T @ M4 @ res4["phi_mass_norm"], np.eye(4), atol=1e-11)
    np.testing.assert_allclose(ref_phi.T @ K4 @ ref_phi, np.diag(ref_lam), atol=1e-8)


def test_invalid_inputs_and_storey_bounds():
    with pytest.raises(ValueError):
        assemble_mass_matrix([100.0])
    with pytest.raises(ValueError):
        assemble_mass_matrix([100.0, -5.0])
    with pytest.raises(ValueError):
        assemble_stiffness_matrix([25000.0, 0.0])
    with pytest.raises(ValueError):
        analyze_matrices(assemble_mass_matrix([1.0, 1.0]), assemble_stiffness_matrix([1.0, 1.0, 1.0]))

    # Enforce 3-5 building storey bounds strictly
    for valid_n in (3, 4, 5):
        m_arr, k_arr, zeta = validate_building_inputs([120.0] * valid_n, [25000.0] * valid_n, 0.05)
        assert m_arr.size == valid_n and k_arr.size == valid_n and zeta == 0.05

    for invalid_n in (1, 2, 6, 10):
        with pytest.raises(ValueError):
            validate_building_inputs([120.0] * invalid_n, [25000.0] * invalid_n, 0.05)
    with pytest.raises(ValueError):
        validate_building_inputs([120.0, 120.0, 120.0], [25000.0, 25000.0, 25000.0], -0.01)


def test_dsa_merge_sort_modes():
    # Normal scrambled mode list compared against Python reference
    scrambled = [
        {"mode": 3, "frequency_hz": 5.42},
        {"mode": 1, "frequency_hz": 0.95},
        {"mode": 4, "frequency_hz": 8.10},
        {"mode": 2, "frequency_hz": 2.75},
    ]
    sorted_modes = merge_sort_modes(scrambled)
    assert [m["frequency_hz"] for m in sorted_modes] == sorted(m["frequency_hz"] for m in scrambled)
    assert [m["mode"] for m in sorted_modes] == [1, 2, 3, 4]

    # Edge cases: empty list, single item, reverse-ordered with duplicate frequencies (stability)
    assert merge_sort_modes([]) == []
    assert merge_sort_modes([{"id": "only", "frequency_hz": 1.2}]) == [{"id": "only", "frequency_hz": 1.2}]
    dupes = [
        {"id": "a", "frequency_hz": 3.0},
        {"id": "b", "frequency_hz": 1.5},
        {"id": "c", "frequency_hz": 3.0},
    ]
    res_dupes = merge_sort_modes(dupes)
    assert [x["id"] for x in res_dupes] == ["b", "a", "c"]


def test_resonance_detection_normal_edge_and_validation():
    freqs = [0.85, 2.45, 4.10, 5.75]

    # Normal resonance match (2 modes fall in band)
    hit = check_earthquake_resonance(freqs, 0.80, 3.00)
    assert hit["has_resonance_risk"] is True
    assert [m["mode"] for m in hit["at_risk_modes"]] == [1, 2]
    assert "Mode 1 (0.850 Hz)" in hit["summary"]

    # Boundary-inclusive edge case (exact lower and upper boundary match)
    boundary = check_earthquake_resonance(freqs, 2.45, 4.10)
    assert [m["mode"] for m in boundary["at_risk_modes"]] == [2, 3]

    # No overlap case
    clear = check_earthquake_resonance(freqs, 10.0, 15.0)
    assert clear["has_resonance_risk"] is False
    assert clear["at_risk_modes"] == []
    assert "No frequency overlap detected" in clear["summary"]

    # Invalid frequency bounds
    with pytest.raises(ValueError):
        check_earthquake_resonance(freqs, 4.0, 2.0)
    with pytest.raises(ValueError):
        check_earthquake_resonance(freqs, -1.0, 2.0)


def test_storey_stiffness_comparison_normal_edge_and_reference():
    masses = [120.0, 120.0, 120.0, 120.0]
    stiff = [25000.0, 25000.0, 25000.0, 25000.0]

    # Normal case: +40% stiffness on Storey 1 raises natural frequencies
    cmp_pct = compare_storey_stiffness(masses, stiff, story_index=1, pct_change=40.0)
    assert cmp_pct["orig_stiffness_kn_m"] == pytest.approx(25000.0)
    assert cmp_pct["mod_stiffness_kn_m"] == pytest.approx(35000.0)
    assert all(m["mod_freq_hz"] >= m["orig_freq_hz"] for m in cmp_pct["modes"])
    assert cmp_pct["modes"][0]["change_pct"] > 0.0

    # Direct new_stiffness comparison verified against independent SciPy modal solve
    cmp_abs = compare_storey_stiffness(masses, stiff, story_index=2, new_stiffness=50000.0)
    assert cmp_abs["pct_change"] == pytest.approx(100.0)
    M = assemble_mass_matrix(masses)
    K_mod = assemble_stiffness_matrix([25000.0, 50000.0, 25000.0, 25000.0])
    lam_ref = np.linalg.eigvalsh(np.linalg.inv(M) @ K_mod)
    freq_ref = np.sort(np.sqrt(lam_ref)) / (2.0 * np.pi)
    np.testing.assert_allclose([m["mod_freq_hz"] for m in cmp_abs["modes"]], freq_ref, rtol=1e-10)

    # Edge cases: 0% change gives ~0% frequency shift; invalid story index rejected
    cmp_zero = compare_storey_stiffness(masses, stiff, story_index=4, pct_change=0.0)
    assert all(abs(m["change_pct"]) < 1e-12 for m in cmp_zero["modes"])
    with pytest.raises(ValueError):
        compare_storey_stiffness(masses, stiff, story_index=5, pct_change=10.0)
    with pytest.raises(ValueError):
        compare_storey_stiffness(masses, stiff, story_index=1, pct_change=-100.0)


def test_earthquake_simulation_physics_and_risk_levels():
    M = assemble_mass_matrix([100.0, 100.0, 100.0])
    K = assemble_stiffness_matrix([30000.0, 25000.0, 20000.0])

    # Static equilibrium check under constant sustained ground acceleration a_g = 0.2g
    t_const = np.arange(0.0, 12.0, 0.005)
    ag_const = np.full_like(t_const, 0.2)
    sim_const = simulate_earthquake(M, K, 0.25, t_const, ag_const)
    u_static = np.linalg.solve(K, -M @ np.ones(3) * (0.2 * GRAVITY))
    np.testing.assert_allclose(sim_const["u_m"][:, -1], u_static, rtol=1e-3)

    t, ag = generate_ground_motion("Broadband Seismic Pulse", duration_s=15.0, dt=0.01, pga_g=0.35)
    assert math.isclose(float(np.max(np.abs(ag))), 0.35, rel_tol=1e-9)

    sim_zero = simulate_earthquake(M, K, 0.05, t, np.zeros_like(t))
    assert sim_zero["peak_roof_disp_mm"] == 0.0
    assert sim_zero["peak_base_shear_kn"] == 0.0
    assert sim_zero["risk_level"] == "Low"

    sim_low = simulate_earthquake(M, K, 0.01, t, ag)
    sim_high = simulate_earthquake(M, K, 0.12, t, ag)
    assert sim_high["peak_roof_disp_mm"] < sim_low["peak_roof_disp_mm"]
    assert sim_low["peak_base_shear_kn"] == pytest.approx(float(np.max(np.abs(30000.0 * sim_low["u_m"][0]))))

    # Separate drift risk threshold coverage
    assert classify_seismic_risk(3.0) == "Low"
    assert classify_seismic_risk(10.0) == "Moderate"
    assert classify_seismic_risk(25.0) == "High"
    assert classify_seismic_risk(60.0) == "Severe"
