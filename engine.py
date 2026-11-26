"""Structural dynamics linear algebra engine for EarthQuick (Phase 3)."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.linalg import eigh

GRAVITY = 9.80665
MIN_STOREYS = 3
MAX_STOREYS = 5

GROUND_MOTIONS = {
    "Broadband Seismic Pulse": "Realistic multi-frequency shaking envelope peaking early and decaying smoothly.",
    "Near-Fault Pulse (Low Frequency)": "Longer-period velocity pulse targeting mid-to-tall flexible frames.",
    "Harmonic Resonance Sweep": "Chirp sweep from 0.4 Hz to 6.0 Hz to excite fundamental and higher modes.",
}


def validate_building_inputs(
    masses: Sequence[float],
    stiffnesses: Sequence[float],
    damping_ratio: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Validate project building requirements: 3 to 5 storeys, positive m/k, damping in [0, 0.5]."""
    m = _validate_positive_vector(masses, "masses")
    k = _validate_positive_vector(stiffnesses, "stiffnesses")
    if m.size != k.size or not (MIN_STOREYS <= m.size <= MAX_STOREYS):
        raise ValueError(f"Building must have between {MIN_STOREYS} and {MAX_STOREYS} storeys.")
    zeta = float(damping_ratio)
    if not np.isfinite(zeta) or zeta < 0.0 or zeta > 0.5:
        raise ValueError("Damping ratio must be between 0.0 and 0.5.")
    return m, k, zeta


def merge_sort_modes(modes: Sequence[dict]) -> list[dict]:
    """Sort vibration mode dicts by natural frequency ascending using Merge Sort.

    Time complexity: O(n log n) in best, average, and worst cases.
    Space complexity: O(n) auxiliary storage for divide-and-conquer merging.
    """
    items = list(modes)
    if len(items) <= 1:
        return items

    mid = len(items) // 2
    left = merge_sort_modes(items[:mid])
    right = merge_sort_modes(items[mid:])

    merged: list[dict] = []
    i = j = 0
    while i < len(left) and j < len(right):
        if float(left[i]["frequency_hz"]) <= float(right[j]["frequency_hz"]):
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged


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

    # Sort eigenpairs explicitly by ascending natural frequency via DSA Merge Sort.
    eigenvalues_raw, phi_raw = eigh(K, M)
    eigenvalues_raw = np.maximum(eigenvalues_raw, 0.0)
    freqs_raw = np.sqrt(eigenvalues_raw) / (2.0 * np.pi)
    sorted_records = merge_sort_modes(
        [{"index": i, "frequency_hz": float(freqs_raw[i])} for i in range(len(freqs_raw))]
    )
    order = [rec["index"] for rec in sorted_records]
    eigenvalues = eigenvalues_raw[order]
    phi_m = phi_raw[:, order]
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


def check_earthquake_resonance(
    frequencies_hz: Sequence[float],
    freq_min_hz: float,
    freq_max_hz: float,
) -> dict:
    """Check every building natural frequency against an earthquake excitation band [min, max] Hz."""
    f_arr = np.asarray(frequencies_hz, dtype=float)
    if f_arr.ndim != 1 or f_arr.size == 0 or not np.all(np.isfinite(f_arr)):
        raise ValueError("frequencies_hz must be a non-empty finite 1D sequence.")
    f_min = float(freq_min_hz)
    f_max = float(freq_max_hz)
    if not (np.isfinite(f_min) and np.isfinite(f_max)) or f_min < 0.0 or f_max <= 0.0 or f_min > f_max:
        raise ValueError("Frequency range must satisfy 0 <= freq_min_hz <= freq_max_hz and freq_max_hz > 0.")

    modes = []
    at_risk_modes = []
    for idx, freq in enumerate(f_arr):
        f_val = float(freq)
        in_range = f_min <= f_val <= f_max
        entry = {
            "mode": idx + 1,
            "frequency_hz": f_val,
            "period_s": (1.0 / f_val) if f_val > 0.0 else float("inf"),
            "at_risk": bool(in_range),
        }
        modes.append(entry)
        if in_range:
            at_risk_modes.append(entry)

    has_risk = len(at_risk_modes) > 0
    if has_risk:
        flagged = ", ".join(f"Mode {m['mode']} ({m['frequency_hz']:.3f} Hz)" for m in at_risk_modes)
        summary = f"Potential resonance risk detected within {f_min:.2f}–{f_max:.2f} Hz: {flagged}."
    else:
        summary = f"No frequency overlap detected within {f_min:.2f}–{f_max:.2f} Hz."

    return {
        "freq_min_hz": f_min,
        "freq_max_hz": f_max,
        "has_resonance_risk": has_risk,
        "at_risk_modes": at_risk_modes,
        "modes": modes,
        "summary": summary,
    }


def compare_storey_stiffness(
    masses: Sequence[float],
    stiffnesses: Sequence[float],
    story_index: int,
    pct_change: float | None = None,
    new_stiffness: float | None = None,
) -> dict:
    """Compare natural frequencies before and after modifying one storey's stiffness."""
    m_arr, k_orig_arr, _ = validate_building_inputs(masses, stiffnesses)
    n = int(m_arr.size)
    s_idx = int(story_index)
    if s_idx < 1 or s_idx > n:
        raise ValueError(f"story_index must be between 1 and {n}.")

    orig_k = float(k_orig_arr[s_idx - 1])
    if new_stiffness is not None:
        mod_k = float(new_stiffness)
        if not np.isfinite(mod_k) or mod_k <= 0.0:
            raise ValueError("new_stiffness must be finite and > 0.")
        actual_pct = 100.0 * (mod_k - orig_k) / orig_k
    elif pct_change is not None:
        actual_pct = float(pct_change)
        if not np.isfinite(actual_pct) or actual_pct <= -100.0:
            raise ValueError("pct_change must be finite and > -100%.")
        mod_k = orig_k * (1.0 + actual_pct / 100.0)
    else:
        raise ValueError("Specify either pct_change or new_stiffness.")

    k_mod_arr = k_orig_arr.copy()
    k_mod_arr[s_idx - 1] = mod_k

    M = assemble_mass_matrix(m_arr)
    modal_orig = solve_modal_analysis(M, assemble_stiffness_matrix(k_orig_arr))
    modal_mod = solve_modal_analysis(M, assemble_stiffness_matrix(k_mod_arr))

    mode_comparisons = []
    for idx in range(n):
        f0 = float(modal_orig["frequencies_hz"][idx])
        f1 = float(modal_mod["frequencies_hz"][idx])
        delta_pct = 100.0 * (f1 - f0) / f0 if f0 > 0.0 else 0.0
        mode_comparisons.append(
            {
                "mode": idx + 1,
                "orig_freq_hz": f0,
                "mod_freq_hz": f1,
                "change_pct": delta_pct,
                "orig_period_s": float(modal_orig["periods_s"][idx]),
                "mod_period_s": float(modal_mod["periods_s"][idx]),
            }
        )

    f1_delta = mode_comparisons[0]["change_pct"]
    direction = "Increasing" if mod_k >= orig_k else "Decreasing"
    effect = "raises" if f1_delta >= 0 else "lowers"
    explanation = (
        f"{direction} Storey {s_idx} stiffness from {orig_k:,.0f} to {mod_k:,.0f} kN/m ({actual_pct:+.1f}%) "
        f"{effect} the fundamental sway frequency f₁ by {f1_delta:+.2f}%. Modes with large interstorey drift "
        f"across Storey {s_idx} experience the strongest frequency shift via Rayleigh's quotient ω² = (φᵀKφ)/(φᵀMφ)."
    )

    return {
        "n": n,
        "story_index": s_idx,
        "orig_stiffness_kn_m": orig_k,
        "mod_stiffness_kn_m": mod_k,
        "pct_change": actual_pct,
        "orig_stiffnesses": k_orig_arr.tolist(),
        "mod_stiffnesses": k_mod_arr.tolist(),
        "modes": mode_comparisons,
        "explanation": explanation,
    }
