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


def test_structural_api_endpoints_end_to_end():
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

    # Invalid input returns 400 JSON error cleanly
    bad = json.dumps({"masses": [120], "stiffnesses": [25000]}).encode()
    st_bad, _ = _call_asgi("POST", "/api/matrices", bad, hdrs)
    assert st_bad == 400
