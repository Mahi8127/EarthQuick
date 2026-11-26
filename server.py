"""Starlette web backend serving the EarthQuick 3D Web UI and structural API."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from engine import (
    GROUND_MOTIONS,
    analyze_matrices,
    assemble_mass_matrix,
    assemble_stiffness_matrix,
    generate_ground_motion,
    simulate_earthquake,
    solve_modal_analysis,
)

WEB_DIR = Path(__file__).resolve().parent / "web"


def _serialize_matrices(info: dict) -> dict:
    return {
        "n": int(info["n"]),
        "M": info["M"].tolist(),
        "K": info["K"].tolist(),
        "m_sym_err": float(info["m_sym_err"]),
        "k_sym_err": float(info["k_sym_err"]),
        "m_min_eig": float(info["m_min_eig"]),
        "k_min_eig": float(info["k_min_eig"]),
        "is_spd": bool(info["is_spd"]),
        "cond_k": float(info["cond_k"]),
        "nnz_k": int(info["nnz_k"]),
        "sparsity_pct": float(info["sparsity_pct"]),
    }


def _serialize_modal(res: dict) -> dict:
    return {
        "n": int(res["n"]),
        "omega": res["omega"].tolist(),
        "frequencies_hz": res["frequencies_hz"].tolist(),
        "periods_s": res["periods_s"].tolist(),
        "phi_normalized": res["phi_normalized"].tolist(),
        "participation_factors": res["participation_factors"].tolist(),
        "mass_ratio_pct": res["mass_ratio_pct"].tolist(),
        "m_ortho_err": float(res["m_ortho_err"]),
        "k_ortho_err": float(res["k_ortho_err"]),
        "eigen_residual": float(res["eigen_residual"]),
    }


def _serialize_earthquake(res: dict) -> dict:
    return {
        "n": int(res["n"]),
        "t": res["t"].tolist(),
        "accel_g": res["accel_g"].tolist(),
        "u_mm": (res["u_m"] * 1000.0).tolist(),
        "drifts_mm": (res["drifts_m"] * 1000.0).tolist(),
        "base_shear_kn": res["base_shear_kn"].tolist(),
        "peak_floor_disp_mm": res["peak_floor_disp_mm"].tolist(),
        "peak_story_drift_mm": res["peak_story_drift_mm"].tolist(),
        "peak_roof_disp_mm": float(res["peak_roof_disp_mm"]),
        "max_interstory_drift_mm": float(res["max_interstory_drift_mm"]),
        "critical_story": int(res["critical_story"]),
        "peak_base_shear_kn": float(res["peak_base_shear_kn"]),
        "pga_g": float(res["pga_g"]),
        "damping_ratio": float(res["damping_ratio"]),
        "modal": _serialize_modal(res["modal"]),
    }


async def index(_request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def favicon(_request: Request) -> Response:
    return Response(status_code=204)


async def presets(_request: Request) -> JSONResponse:
    return JSONResponse({"presets": [{"name": k, "description": v} for k, v in GROUND_MOTIONS.items()]})


async def api_matrices(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        M = assemble_mass_matrix(body["masses"])
        K = assemble_stiffness_matrix(body["stiffnesses"])
        return JSONResponse(_serialize_matrices(analyze_matrices(M, K)))
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_modal(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        M = assemble_mass_matrix(body["masses"])
        K = assemble_stiffness_matrix(body["stiffnesses"])
        return JSONResponse(
            {
                "matrices": _serialize_matrices(analyze_matrices(M, K)),
                "modal": _serialize_modal(solve_modal_analysis(M, K)),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_earthquake(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        M = assemble_mass_matrix(body["masses"])
        K = assemble_stiffness_matrix(body["stiffnesses"])
        damping = float(body.get("damping_ratio", 0.05))
        if "t" in body and "accel_g" in body:
            t = np.asarray(body["t"], dtype=float)
            ag = np.asarray(body["accel_g"], dtype=float)
        else:
            preset = body.get("preset_name", "Broadband Seismic Pulse")
            duration_s = float(body.get("duration_s", 20.0))
            pga_g = float(body.get("pga_g", 0.30))
            t, ag = generate_ground_motion(preset, duration_s=duration_s, dt=0.01, pga_g=pga_g)
        res = simulate_earthquake(M, K, damping, t, ag)
        return JSONResponse(
            {
                "matrices": _serialize_matrices(analyze_matrices(M, K)),
                "earthquake": _serialize_earthquake(res),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_earthquake_csv(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        masses = [float(x) for x in str(form["masses"]).split(",")]
        stiffnesses = [float(x) for x in str(form["stiffnesses"]).split(",")]
        damping = float(form.get("damping_ratio", 0.05))
        upload = form["file"]
        raw = (await upload.read()).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(raw)))
        t_vals, ag_vals = [], []
        for row in rows:
            if len(row) < 2:
                continue
            try:
                t_vals.append(float(row[0]))
                ag_vals.append(float(row[1]))
            except ValueError:
                continue  # skip header row
        M = assemble_mass_matrix(masses)
        K = assemble_stiffness_matrix(stiffnesses)
        res = simulate_earthquake(M, K, damping, np.array(t_vals), np.array(ag_vals))
        return JSONResponse(
            {
                "matrices": _serialize_matrices(analyze_matrices(M, K)),
                "earthquake": _serialize_earthquake(res),
            }
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


app = Starlette(
    routes=[
        Route("/", index),
        Route("/favicon.ico", favicon),
        Route("/api/health", health),
        Route("/api/presets", presets),
        Route("/api/matrices", api_matrices, methods=["POST"]),
        Route("/api/modal", api_modal, methods=["POST"]),
        Route("/api/earthquake", api_earthquake, methods=["POST"]),
        Route("/api/earthquake/csv", api_earthquake_csv, methods=["POST"]),
        Mount("/static", app=StaticFiles(directory=str(WEB_DIR)), name="static"),
    ]
)
