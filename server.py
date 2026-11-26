"""Starlette web backend serving the EarthQuick 3D Web UI and structural API."""

from __future__ import annotations

from contextlib import asynccontextmanager
import csv
import io
from pathlib import Path

import numpy as np
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import db
from engine import (
    GROUND_MOTIONS,
    analyze_matrices,
    assemble_mass_matrix,
    assemble_stiffness_matrix,
    check_earthquake_resonance,
    compare_storey_stiffness,
    generate_ground_motion,
    simulate_earthquake,
    solve_modal_analysis,
    validate_building_inputs,
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
        "eigenvalues": res["eigenvalues"].tolist(),
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
        "risk_level": str(res["risk_level"]),
        "modal": _serialize_modal(res["modal"]),
    }


def _resolve_building_id(
    building_id_raw: object,
    name: str | None,
    building_type: str | None,
    damping_ratio: float,
    masses: list[float] | object,
    stiffnesses: list[float] | object,
) -> int:
    if building_id_raw not in (None, ""):
        existing = db.get_building(int(building_id_raw))
        if not existing:
            raise LookupError(f"Building {building_id_raw} not found.")
        return int(existing["id"])
    n = len(masses)
    saved = db.save_building(
        name=str(name or f"{n}-Story Frame"),
        building_type=str(building_type or "Standard Shear Frame"),
        damping_ratio=damping_ratio,
        masses=masses,
        stiffnesses=stiffnesses,
    )
    return int(saved["id"])


async def index(_request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "database": "postgres" if db.get_database_url() else "sqlite"})


async def favicon(_request: Request) -> Response:
    return Response(status_code=204)


async def presets(_request: Request) -> JSONResponse:
    return JSONResponse({"presets": [{"name": k, "description": v} for k, v in GROUND_MOTIONS.items()]})


async def api_buildings(request: Request) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse({"buildings": db.list_buildings()})
    try:
        body = await request.json()
        building = db.save_building(
            name=body.get("name") or body.get("building_name") or "Building",
            building_type=body.get("building_type", "Standard Shear Frame"),
            damping_ratio=float(body.get("damping_ratio", 0.05)),
            masses=body["masses"],
            stiffnesses=body["stiffnesses"],
        )
        return JSONResponse({"building": building}, status_code=201)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_building_detail(request: Request) -> JSONResponse:
    building_id = int(request.path_params["building_id"])
    if request.method == "GET":
        building = db.get_building(building_id)
        if not building:
            return JSONResponse({"error": "Building not found."}, status_code=404)
        return JSONResponse({"building": building})
    deleted = db.delete_building(building_id)
    if not deleted:
        return JSONResponse({"error": "Building not found."}, status_code=404)
    return JSONResponse({"deleted": True, "id": building_id})


async def api_history(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        db.clear_history()
        return JSONResponse({"cleared": True})
    return JSONResponse({"history": db.list_history()})


async def api_run_detail(request: Request) -> JSONResponse:
    run_type = request.path_params["run_type"]
    run_id = int(request.path_params["run_id"])
    try:
        detail = db.get_run_detail(run_type, run_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if not detail:
        return JSONResponse({"error": "Run not found."}, status_code=404)
    return JSONResponse({"run": detail})


async def api_matrices(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        validate_building_inputs(body["masses"], body["stiffnesses"], float(body.get("damping_ratio", 0.05)))
        M = assemble_mass_matrix(body["masses"])
        K = assemble_stiffness_matrix(body["stiffnesses"])
        return JSONResponse(_serialize_matrices(analyze_matrices(M, K)))
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_modal(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        masses = body["masses"]
        stiffnesses = body["stiffnesses"]
        damping = float(body.get("damping_ratio", 0.05))
        validate_building_inputs(masses, stiffnesses, damping)
        M = assemble_mass_matrix(masses)
        K = assemble_stiffness_matrix(stiffnesses)
        matrices_payload = _serialize_matrices(analyze_matrices(M, K))
        modal_payload = _serialize_modal(solve_modal_analysis(M, K))
        building_id = _resolve_building_id(
            body.get("building_id"),
            body.get("building_name") or body.get("name"),
            body.get("building_type"),
            damping,
            masses,
            stiffnesses,
        )
        saved_modal = db.save_modal_analysis(building_id, matrices_payload, modal_payload)
        return JSONResponse(
            {
                "building_id": building_id,
                "modal_id": saved_modal["id"],
                "matrices": matrices_payload,
                "modal": modal_payload,
            }
        )
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_resonance(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        masses = body["masses"]
        stiffnesses = body["stiffnesses"]
        damping = float(body.get("damping_ratio", 0.05))
        validate_building_inputs(masses, stiffnesses, damping)
        freq_min = float(body["freq_min_hz"])
        freq_max = float(body["freq_max_hz"])

        M = assemble_mass_matrix(masses)
        K = assemble_stiffness_matrix(stiffnesses)
        matrices_payload = _serialize_matrices(analyze_matrices(M, K))
        modal_payload = _serialize_modal(solve_modal_analysis(M, K))
        resonance_payload = check_earthquake_resonance(modal_payload["frequencies_hz"], freq_min, freq_max)

        building_id = _resolve_building_id(
            body.get("building_id"),
            body.get("building_name") or body.get("name"),
            body.get("building_type"),
            damping,
            masses,
            stiffnesses,
        )
        saved_modal = db.save_modal_analysis(building_id, matrices_payload, modal_payload)
        saved_res = db.save_resonance_check(building_id, saved_modal["id"], resonance_payload)
        return JSONResponse(
            {
                "building_id": building_id,
                "modal_id": saved_modal["id"],
                "resonance_id": saved_res["id"],
                "matrices": matrices_payload,
                "modal": modal_payload,
                "resonance": resonance_payload,
            }
        )
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_stiffness_compare(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        masses = body["masses"]
        stiffnesses = body["stiffnesses"]
        damping = float(body.get("damping_ratio", 0.05))
        validate_building_inputs(masses, stiffnesses, damping)

        comparison = compare_storey_stiffness(
            masses=masses,
            stiffnesses=stiffnesses,
            story_index=int(body["story_index"]),
            pct_change=float(body["pct_change"]) if body.get("pct_change") not in (None, "") else None,
            new_stiffness=float(body["new_stiffness"]) if body.get("new_stiffness") not in (None, "") else None,
        )
        building_id = _resolve_building_id(
            body.get("building_id"),
            body.get("building_name") or body.get("name"),
            body.get("building_type"),
            damping,
            masses,
            stiffnesses,
        )
        saved_cmp = db.save_stiffness_comparison(building_id, comparison)
        return JSONResponse(
            {
                "building_id": building_id,
                "comparison_id": saved_cmp["id"],
                "comparison": comparison,
            }
        )
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_earthquake(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        masses = body["masses"]
        stiffnesses = body["stiffnesses"]
        damping = float(body.get("damping_ratio", 0.05))
        validate_building_inputs(masses, stiffnesses, damping)
        M = assemble_mass_matrix(masses)
        K = assemble_stiffness_matrix(stiffnesses)
        if "t" in body and "accel_g" in body:
            t = np.asarray(body["t"], dtype=float)
            ag = np.asarray(body["accel_g"], dtype=float)
            record_name = str(body.get("record_name", "Custom Series"))
            duration_s = float(t[-1] - t[0]) if t.size > 1 else 0.0
            source_type = "series"
        else:
            preset = body.get("preset_name", "Broadband Seismic Pulse")
            duration_s = float(body.get("duration_s", 20.0))
            pga_g = float(body.get("pga_g", 0.30))
            t, ag = generate_ground_motion(preset, duration_s=duration_s, dt=0.01, pga_g=pga_g)
            record_name = str(preset)
            source_type = "preset"
        res = simulate_earthquake(M, K, damping, t, ag)
        matrices_payload = _serialize_matrices(analyze_matrices(M, K))
        eq_payload = _serialize_earthquake(res)
        building_id = _resolve_building_id(
            body.get("building_id"),
            body.get("building_name") or body.get("name"),
            body.get("building_type"),
            damping,
            masses,
            stiffnesses,
        )
        saved_modal = db.save_modal_analysis(building_id, matrices_payload, eq_payload["modal"])
        saved_run = db.save_earthquake_run(
            building_id, saved_modal["id"], source_type, record_name, duration_s, eq_payload
        )
        return JSONResponse(
            {
                "building_id": building_id,
                "modal_id": saved_modal["id"],
                "run_id": saved_run["id"],
                "matrices": matrices_payload,
                "earthquake": eq_payload,
            }
        )
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_earthquake_csv(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        masses = [float(x) for x in str(form["masses"]).split(",")]
        stiffnesses = [float(x) for x in str(form["stiffnesses"]).split(",")]
        damping = float(form.get("damping_ratio", 0.05))
        validate_building_inputs(masses, stiffnesses, damping)
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
        t_arr = np.array(t_vals)
        res = simulate_earthquake(M, K, damping, t_arr, np.array(ag_vals))
        matrices_payload = _serialize_matrices(analyze_matrices(M, K))
        eq_payload = _serialize_earthquake(res)
        building_id = _resolve_building_id(
            form.get("building_id"),
            form.get("building_name"),
            form.get("building_type"),
            damping,
            masses,
            stiffnesses,
        )
        saved_modal = db.save_modal_analysis(building_id, matrices_payload, eq_payload["modal"])
        record_name = getattr(upload, "filename", None) or "Uploaded CSV"
        duration_s = float(t_arr[-1] - t_arr[0]) if t_arr.size > 1 else 0.0
        saved_run = db.save_earthquake_run(
            building_id, saved_modal["id"], "csv", record_name, duration_s, eq_payload
        )
        return JSONResponse(
            {
                "building_id": building_id,
                "modal_id": saved_modal["id"],
                "run_id": saved_run["id"],
                "matrices": matrices_payload,
                "earthquake": eq_payload,
            }
        )
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@asynccontextmanager
async def lifespan(_app: Starlette):
    db.init_db()
    yield


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/", index),
        Route("/favicon.ico", favicon),
        Route("/api/health", health),
        Route("/api/presets", presets),
        Route("/api/buildings", api_buildings, methods=["GET", "POST"]),
        Route("/api/buildings/{building_id:int}", api_building_detail, methods=["GET", "DELETE"]),
        Route("/api/history", api_history, methods=["GET", "DELETE"]),
        Route("/api/runs/{run_type:str}/{run_id:int}", api_run_detail, methods=["GET"]),
        Route("/api/matrices", api_matrices, methods=["POST"]),
        Route("/api/modal", api_modal, methods=["POST"]),
        Route("/api/resonance", api_resonance, methods=["POST"]),
        Route("/api/stiffness-compare", api_stiffness_compare, methods=["POST"]),
        Route("/api/earthquake", api_earthquake, methods=["POST"]),
        Route("/api/earthquake/csv", api_earthquake_csv, methods=["POST"]),
        Mount("/static", app=StaticFiles(directory=str(WEB_DIR)), name="static"),
    ]
)
