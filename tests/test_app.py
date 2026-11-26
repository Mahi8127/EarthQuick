"""API and static web delivery tests for EarthQuick Starlette server."""

from __future__ import annotations

import asyncio
import json

from server import app


def _call_asgi(method: str, path: str, body: bytes = b"", headers: list[tuple[bytes, bytes]] | None = None):
    async def _run():
        sent = False
        messages = []

        done = asyncio.Event()

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(msg):
            messages.append(msg)
            if msg["type"] == "http.response.body" and not msg.get("more_body", False):
                done.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers or [],
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return start["status"], payload

    return asyncio.run(_run())


def test_web_pages_and_assets_served():
    status, body = _call_asgi("GET", "/")
    assert status == 200
    assert b"EarthQuick" in body
    assert b"scene3d-canvas" in body

    for asset in [
        "/static/styles.css",
        "/static/app.js",
        "/static/scene3d.js",
        "/static/vendor/three.module.min.js",
        "/static/vendor/OrbitControls.js",
    ]:
        st_code, asset_body = _call_asgi("GET", asset)
        assert st_code == 200 and len(asset_body) > 100


def test_structural_api_endpoints_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHQUICK_DB_PATH", str(tmp_path / "e2e_test.db"))
    st_code, payload = _call_asgi("GET", "/api/presets")
    assert st_code == 200
    assert len(json.loads(payload)["presets"]) == 3

    req = json.dumps({"masses": [120, 120, 120], "stiffnesses": [25000, 25000, 25000], "damping_ratio": 0.05}).encode()
    hdrs = [(b"content-type", b"application/json")]

    st_m, body_m = _call_asgi("POST", "/api/matrices", req, hdrs)
    assert st_m == 200
    assert json.loads(body_m)["is_spd"] is True

    st_mod, body_mod = _call_asgi("POST", "/api/modal", req, hdrs)
    assert st_mod == 200
    mod_data = json.loads(body_mod)["modal"]
    assert len(mod_data["frequencies_hz"]) == 3
    assert mod_data["eigen_residual"] < 1e-8

    st_eq, body_eq = _call_asgi("POST", "/api/earthquake", req, hdrs)
    assert st_eq == 200
    eq_data = json.loads(body_eq)["earthquake"]
    assert eq_data["peak_roof_disp_mm"] > 0.0

    # Enforce 3-5 storeys on API endpoints (2 floors and 6 floors return 400)
    for bad_floors in (1, 2, 6):
        bad = json.dumps({"masses": [120] * bad_floors, "stiffnesses": [25000] * bad_floors}).encode()
        st_bad, _ = _call_asgi("POST", "/api/matrices", bad, hdrs)
        assert st_bad == 400
        st_bad_b, _ = _call_asgi("POST", "/api/buildings", bad, hdrs)
        assert st_bad_b == 400


def test_database_api_persistence_and_retrieval(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("EARTHQUICK_DB_PATH", str(tmp_path / "api_test.db"))
    hdrs = [(b"content-type", b"application/json")]

    st_h, body_h = _call_asgi("GET", "/api/health")
    assert st_h == 200
    assert json.loads(body_h) == {"status": "ok", "database": "sqlite"}

    # Clear initial history cleanly
    st_clr, _ = _call_asgi("DELETE", "/api/history")
    assert st_clr == 200

    # Save building configuration + floor properties
    b_req = json.dumps(
        {
            "name": "Steel Lab Frame",
            "building_type": "Steel Frame",
            "damping_ratio": 0.04,
            "masses": [110, 100, 90],
            "stiffnesses": [26000, 24000, 22000],
        }
    ).encode()
    st_b, body_b = _call_asgi("POST", "/api/buildings", b_req, hdrs)
    assert st_b == 201
    building = json.loads(body_b)["building"]
    b_id = building["id"]
    assert building["floors"] == 3
    assert building["masses"] == [110.0, 100.0, 90.0]

    # Run modal analysis linked to building_id -> persists eigenvalues & mode shapes
    mod_req = json.dumps(
        {
            "building_id": b_id,
            "masses": building["masses"],
            "stiffnesses": building["stiffnesses"],
            "damping_ratio": building["damping_ratio"],
        }
    ).encode()
    st_mod, body_mod = _call_asgi("POST", "/api/modal", mod_req, hdrs)
    assert st_mod == 200
    mod_res = json.loads(body_mod)
    assert len(mod_res["modal"]["eigenvalues"]) == 3
    assert mod_res["modal_id"] >= 1

    # Run earthquake simulation linked to building_id -> persists drift & risk_level
    eq_req = json.dumps(
        {
            "building_id": b_id,
            "masses": building["masses"],
            "stiffnesses": building["stiffnesses"],
            "damping_ratio": building["damping_ratio"],
            "preset_name": "Broadband Seismic Pulse",
            "pga_g": 0.35,
            "duration_s": 10.0,
        }
    ).encode()
    st_eq, body_eq = _call_asgi("POST", "/api/earthquake", eq_req, hdrs)
    assert st_eq == 200
    eq_res = json.loads(body_eq)
    assert eq_res["earthquake"]["risk_level"] in {"Low", "Moderate", "High", "Severe"}
    run_id = eq_res["run_id"]

    # Resonance check endpoint saves and retrieves separately from drift risk
    res_req = json.dumps(
        {
            "building_id": b_id,
            "masses": building["masses"],
            "stiffnesses": building["stiffnesses"],
            "damping_ratio": building["damping_ratio"],
            "freq_min_hz": 0.5,
            "freq_max_hz": 4.0,
        }
    ).encode()
    st_res, body_res = _call_asgi("POST", "/api/resonance", res_req, hdrs)
    assert st_res == 200
    res_data = json.loads(body_res)
    assert res_data["resonance"]["has_resonance_risk"] is True
    assert res_data["resonance_id"] >= 1

    # Storey stiffness comparison endpoint calculates, persists, and retrieves
    cmp_req = json.dumps(
        {
            "building_id": b_id,
            "masses": building["masses"],
            "stiffnesses": building["stiffnesses"],
            "damping_ratio": building["damping_ratio"],
            "story_index": 1,
            "pct_change": 30.0,
        }
    ).encode()
    st_cmp, body_cmp = _call_asgi("POST", "/api/stiffness-compare", cmp_req, hdrs)
    assert st_cmp == 200
    cmp_data = json.loads(body_cmp)
    assert len(cmp_data["comparison"]["modes"]) == 3
    assert cmp_data["comparison"]["modes"][0]["change_pct"] > 0.0

    # Retrieve persisted run details and history
    st_det, body_det = _call_asgi("GET", f"/api/runs/quake/{run_id}")
    assert st_det == 200
    detail = json.loads(body_det)["run"]
    assert detail["building"]["name"] == "Steel Lab Frame"
    assert len(detail["modal"]["eigenvalues"]) == 3
    assert len(detail["modal"]["phi_normalized"]) == 3
    assert detail["earthquake"]["risk_level"] == eq_res["earthquake"]["risk_level"]

    st_res_det, _ = _call_asgi("GET", f"/api/runs/resonance/{res_data['resonance_id']}")
    assert st_res_det == 200
    st_cmp_det, _ = _call_asgi("GET", f"/api/runs/stiffness/{cmp_data['comparison_id']}")
    assert st_cmp_det == 200

    st_hist, body_hist = _call_asgi("GET", "/api/history")
    assert st_hist == 200
    hist_types = {item["run_type"] for item in json.loads(body_hist)["history"]}
    assert {"quake", "resonance", "stiffness"}.issubset(hist_types)

    # Nonexistent building returns 404
    st_404, _ = _call_asgi("GET", "/api/buildings/999999")
    assert st_404 == 404

    # Delete cascades cleanly
    st_del, _ = _call_asgi("DELETE", f"/api/buildings/{b_id}")
    assert st_del == 200
    st_after, _ = _call_asgi("GET", f"/api/runs/quake/{run_id}")
    assert st_after == 404


def test_app_startup_lifespan_initializes_postgres_schema(tmp_path, monkeypatch):
    import db
    from tests.test_db import _MockPgConnection

    backing_file = str(tmp_path / "lifespan_pg.db")
    queries: list[str] = []
    events: list[str] = []

    db._INITIALIZED_TARGETS.clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@dpg-example:5432/earthquick")
    monkeypatch.setattr(db.psycopg, "connect", lambda url, row_factory=None: _MockPgConnection(backing_file, queries, events))

    async def _run_lifespan():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(_run_lifespan())
    assert any("CREATE TABLE IF NOT EXISTS buildings" in q for q in queries)
    assert any("CREATE TABLE IF NOT EXISTS earthquake_runs" in q for q in queries)

    st_h, body_h = _call_asgi("GET", "/api/health")
    assert st_h == 200
    assert json.loads(body_h) == {"status": "ok", "database": "postgres"}
