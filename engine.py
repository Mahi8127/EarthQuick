"""Structural dynamics linear algebra engine for EarthQuick (Phase 3)."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.linalg import eigh

GRAVITY = 9.80665

GROUND_MOTIONS = {
    "Broadband Seismic Pulse": "Realistic multi-frequency shaking envelope peaking early and decaying smoothly.",
    "Near-Fault Pulse (Low Frequency)": "Longer-period velocity pulse targeting mid-to-tall flexible frames.",
    "Harmonic Resonance Sweep": "Chirp sweep from 0.4 Hz to 6.0 Hz to excite fundamental and higher modes.",
}


def _validate_positive_vector(values: Sequence[float], name: str) -> np.ndarray:
    """Convert to 1D float array and verify at least 2 positive finite entries."""
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError(f"{name} must contain at least 2 floors/stories.")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        raise ValueError(f"All {name} entries must be finite and > 0.")
    return arr


def assemble_mass_matrix(masses: Sequence[float]) -> np.ndarray:
    """Assemble the n x n diagonal lumped-mass matrix M (tonnes)."""
    return np.diag(_validate_positive_vector(masses, "masses"))


def assemble_stiffness_matrix(stiffnesses: Sequence[float]) -> np.ndarray:
    """Assemble the n x n tridiagonal shear-frame stiffness matrix K (kN/m)."""
    k = _validate_positive_vector(stiffnesses, "stiffnesses")
    diag = k.copy()
    diag[:-1] += k[1:]
    K = np.diag(diag)
    if k.size > 1:
        off = np.diag(-k[1:], k=1)
        K = K + off + off.T
    return K


def analyze_matrices(M: np.ndarray, K: np.ndarray) -> dict:
    """Compute symmetry, positive-definiteness, conditioning, and sparsity metrics."""
    if M.shape != K.shape or M.ndim != 2 or M.shape[0] != M.shape[1] or M.shape[0] < 2:
        raise ValueError("M and K must be matching square matrices of size >= 2.")

    m_sym_err = float(np.max(np.abs(M - M.T)))
    k_sym_err = float(np.max(np.abs(K - K.T)))
    m_min_eig = float(np.linalg.eigvalsh(M).min())
    k_min_eig = float(np.linalg.eigvalsh(K).min())
    n = M.shape[0]
    nnz_k = int(np.count_nonzero(K))

    return {
        "n": n,
        "M": M,
        "K": K,
        "m_sym_err": m_sym_err,
        "k_sym_err": k_sym_err,
        "m_min_eig": m_min_eig,
        "k_min_eig": k_min_eig,
        "is_spd": m_min_eig > 0.0 and k_min_eig > 0.0 and m_sym_err < 1e-10 and k_sym_err < 1e-10,
        "cond_k": float(np.linalg.cond(K)),
        "det_k": float(np.linalg.det(K)),
        "nnz_k": nnz_k,
        "sparsity_pct": 100.0 * (1.0 - nnz_k / (n * n)),
    }


def solve_modal_analysis(M: np.ndarray, K: np.ndarray) -> dict:
    """Solve K * phi = omega^2 * M * phi using consistent units (kN/m, tonnes -> rad/s)."""
    info = analyze_matrices(M, K)
    if not info["is_spd"]:
        raise ValueError("M and K must be symmetric positive definite for modal analysis.")

    # kN/m divided by metric tonnes equals N/m divided by kg, so omega is directly in rad/s.
    eigenvalues, phi_m = eigh(K, M)
    eigenvalues = np.maximum(eigenvalues, 0.0)
    omega = np.sqrt(eigenvalues)
    frequencies_hz = omega / (2.0 * np.pi)
    periods_s = np.where(frequencies_hz > 0.0, 1.0 / frequencies_hz, np.inf)

    # Normalize each mode shape for display so max(|phi|) == 1 and roof deflection is non-negative.
    phi_disp = phi_m.copy()
    for col in range(phi_disp.shape[1]):
        mode = phi_disp[:, col]
        peak = np.max(np.abs(mode))
        if peak > 0.0:
            mode = mode / peak
        if abs(mode[-1]) > 1e-12:
            sign = 1.0 if mode[-1] >= 0.0 else -1.0
        else:
            nz = mode[np.abs(mode) > 1e-12]
            sign = 1.0 if (nz.size == 0 or nz[0] >= 0.0) else -1.0
        phi_disp[:, col] = mode * sign

    ones = np.ones(info["n"], dtype=float)
    participation = phi_m.T @ (M @ ones)
    effective_mass = participation ** 2
    total_mass = float(np.trace(M))
    mass_ratio_pct = 100.0 * effective_mass / total_mass

    n = info["n"]
    m_ortho_err = float(np.max(np.abs(phi_m.T @ M @ phi_m - np.eye(n))))
    k_ortho_err = float(np.max(np.abs(phi_m.T @ K @ phi_m - np.diag(eigenvalues))))
    eigen_residual = float(np.max(np.abs(K @ phi_m - M @ phi_m @ np.diag(eigenvalues))))

    return {
        "n": n,
        "eigenvalues": eigenvalues,
        "omega": omega,
        "frequencies_hz": frequencies_hz,
        "periods_s": periods_s,
        "phi_mass_norm": phi_m,
        "phi_normalized": phi_disp,
        "participation_factors": participation,
        "effective_mass": effective_mass,
        "mass_ratio_pct": mass_ratio_pct,
        "total_mass": total_mass,
        "m_ortho_err": m_ortho_err,
        "k_ortho_err": k_ortho_err,
        "eigen_residual": eigen_residual,
    }


def generate_ground_motion(
    preset_name: str,
    duration_s: float = 20.0,
    dt: float = 0.01,
    pga_g: float = 0.30,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate a deterministic synthetic ground acceleration record (time_s, accel_g)."""
    if preset_name not in GROUND_MOTIONS:
        raise ValueError(f"Unknown ground motion preset: {preset_name}")
    if duration_s <= 0.5 or dt <= 0.0 or dt >= duration_s / 4.0:
        raise ValueError("Invalid duration or time step dt.")
    if pga_g <= 0.0:
        raise ValueError("PGA must be > 0 g.")

    t = np.arange(0.0, duration_s + 1e-12, dt, dtype=float)
    if preset_name == "Broadband Seismic Pulse":
        env = np.exp(-0.22 * np.maximum(t - 2.5, 0.0)) * (1.0 - np.exp(-1.5 * t))
        raw = env * (
            0.55 * np.sin(2.0 * np.pi * 1.4 * t)
            + 0.35 * np.sin(2.0 * np.pi * 2.9 * t + 0.7)
            + 0.25 * np.sin(2.0 * np.pi * 5.1 * t + 1.9)
            + 0.15 * np.sin(2.0 * np.pi * 8.3 * t + 0.3)
        )
    elif preset_name == "Near-Fault Pulse (Low Frequency)":
        env = np.exp(-0.5 * ((t - 4.0) / 1.8) ** 2) + 0.25 * np.exp(-0.18 * np.maximum(t - 4.0, 0.0))
        raw = env * (0.85 * np.sin(2.0 * np.pi * 0.85 * t) + 0.30 * np.sin(2.0 * np.pi * 1.9 * t + 1.1))
    else:  # Harmonic Resonance Sweep
        phase = 2.0 * np.pi * (0.4 * t + 2.8 * (t ** 2) / duration_s)
        env = np.sin(np.pi * t / duration_s) ** 0.5
        raw = env * np.sin(phase)

    peak = float(np.max(np.abs(raw)))
    accel_g = (raw / peak) * float(pga_g) if peak > 0.0 else raw
    return t, accel_g


def simulate_earthquake(
    M: np.ndarray,
    K: np.ndarray,
    damping_ratio: float,
    t: np.ndarray,
    accel_g: np.ndarray,
) -> dict:
    """Integrate modal equations via Newmark-Beta (gamma=0.5, beta=0.25) and recover floor responses."""
    if damping_ratio < 0.0 or damping_ratio > 0.5:
        raise ValueError("Damping ratio must be between 0.0 and 0.5.")

    t_arr = np.asarray(t, dtype=float)
    ag_arr = np.asarray(accel_g, dtype=float)
    if t_arr.ndim != 1 or ag_arr.ndim != 1 or t_arr.size != ag_arr.size or t_arr.size < 4:
        raise ValueError("Time and acceleration vectors must match in length (>= 4 samples).")
    dts = np.diff(t_arr)
    if not np.all(np.isfinite(t_arr)) or not np.all(np.isfinite(ag_arr)) or np.any(dts <= 0):
        raise ValueError("Time vector must be strictly increasing with finite values.")
    dt = float(np.mean(dts))
    # shortcut: assumes uniform dt from preset or resampled record; re-step per interval if variable dt needed later.

    modal = solve_modal_analysis(M, K)
    n = modal["n"]
    omega = modal["omega"]
    phi_m = modal["phi_mass_norm"]
    gamma_modal = modal["participation_factors"]

    ug_mps2 = ag_arr * GRAVITY
    nt = t_arr.size
    q = np.zeros((n, nt), dtype=float)
    qd = np.zeros((n, nt), dtype=float)
    qdd = np.zeros((n, nt), dtype=float)

    c_m = 2.0 * float(damping_ratio) * omega
    k_m = omega ** 2
    p = -np.outer(gamma_modal, ug_mps2)
    qdd[:, 0] = p[:, 0]

    # Newmark constant-average-acceleration parameters (beta=0.25, gamma=0.5)
    a0 = 4.0 / (dt * dt)
    a1 = 2.0 / dt
    a2 = 4.0 / dt
    k_eff = k_m + a0 + a1 * c_m

    for j in range(nt - 1):
        p_eff = (
            p[:, j + 1]
            + (a0 * q[:, j] + a2 * qd[:, j] + qdd[:, j])
            + c_m * (a1 * q[:, j] + qd[:, j])
        )
        q[:, j + 1] = p_eff / k_eff
        qdd[:, j + 1] = a0 * (q[:, j + 1] - q[:, j]) - a2 * qd[:, j] - qdd[:, j]
        qd[:, j + 1] = qd[:, j] + 0.5 * dt * (qdd[:, j] + qdd[:, j + 1])

    u_m = phi_m @ q
    drifts_m = np.vstack([u_m[0:1, :], np.diff(u_m, axis=0)])
    base_shear_ts = np.sum(K @ u_m, axis=0)  # equals k1 * u1(t) for shear frame

    peak_floor_disp_mm = np.max(np.abs(u_m), axis=1) * 1000.0
    peak_story_drift_mm = np.max(np.abs(drifts_m), axis=1) * 1000.0
    critical_story = int(np.argmax(peak_story_drift_mm)) + 1
    max_drift_mm = float(np.max(peak_story_drift_mm))

    return {
        "n": n,
        "t": t_arr,
        "accel_g": ag_arr,
        "u_m": u_m,
        "drifts_m": drifts_m,
        "base_shear_kn": base_shear_ts,
        "peak_floor_disp_mm": peak_floor_disp_mm,
        "peak_story_drift_mm": peak_story_drift_mm,
        "peak_roof_disp_mm": float(peak_floor_disp_mm[-1]),
        "max_interstory_drift_mm": max_drift_mm,
        "critical_story": critical_story,
        "peak_base_shear_kn": float(np.max(np.abs(base_shear_ts))),
        "pga_g": float(np.max(np.abs(ag_arr))),
        "damping_ratio": float(damping_ratio),
        "risk_level": classify_seismic_risk(max_drift_mm),
        "modal": modal,
    }


def classify_seismic_risk(max_interstory_drift_mm: float, story_height_mm: float = 3500.0) -> str:
    """Classify structural drift demand using standard interstory drift ratio thresholds."""
    ratio = float(max_interstory_drift_mm) / float(story_height_mm)
    if ratio < 0.002:
        return "Low"
    if ratio < 0.005:
        return "Moderate"
    if ratio < 0.015:
        return "High"
    return "Severe"
