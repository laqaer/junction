"""HTTP contracts for routing refusals and operator-controlled lane changes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from junction.harness_router import api
from junction.harness_router.connect import STATUS_NEEDS_LOGIN, ProbeResult
from junction.harness_router.service import HarnessRouter


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HarnessRouter:
    """Resolve only named fake binaries, with all routing state under tmp_path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    document = {
        "version": 1,
        "enabled": True,
        "lanes": [
            {"id": "pro", "harness": "codex", "weight": 1},
            {"id": "max", "harness": "claude", "weight": 1},
        ],
    }
    (tmp_path / "routing.json").write_text(json.dumps(document), encoding="utf-8")
    binaries = {"codex": "/fake/codex", "claude": "/fake/claude", "npx": "/fake/npx"}
    instance = HarnessRouter(home=tmp_path, which=binaries.get)
    monkeypatch.setattr(api, "get_router", lambda: instance)
    return instance


@asynccontextmanager
async def _client() -> AsyncIterator[TestClient]:
    app = web.Application()
    api.register(app)
    async with TestClient(TestServer(app)) as client:
        yield client


def _configuration(router: HarnessRouter) -> Path:
    assert router.home is not None
    return router.home / "routing.json"


@pytest.mark.asyncio
async def test_status_and_harness_inventory_return_persisted_state(router: HarnessRouter) -> None:
    router.record_dispatch("pro", "implement")
    router.probes.save(ProbeResult("codex", STATUS_NEEDS_LOGIN, checked_at=1.0))

    async with _client() as client:
        response = await client.get("/api/routing/status")
        assert response.status == 200
        status = await response.json()
        assert status["code"] == "ok"
        lanes = {lane["id"]: lane for lane in status["lanes"]}
        assert lanes["pro"]["window_used"] == 1
        assert lanes["pro"]["harness"] == "codex"

        response = await client.get("/api/routing/harnesses")
        assert response.status == 200
        inventory = await response.json()
        assert inventory["code"] == "ok"
        harnesses = {row["harness"]: row for row in inventory["harnesses"]}
        assert harnesses["codex"]["installed"] is True
        assert harnesses["codex"]["lane"]["id"] == "pro"
        assert harnesses["codex"]["probe"]["status"] == STATUS_NEEDS_LOGIN


@pytest.mark.asyncio
async def test_decision_normalizes_lane_filters_and_reports_no_lane_as_an_answer(
    router: HarnessRouter,
) -> None:
    before = _configuration(router).read_bytes()
    async with _client() as client:
        response = await client.get(
            "/api/routing/decide",
            params={"kind": "implement", "prefer": " PRO, ,", "exclude": " MAX, "},
        )
        assert response.status == 200
        decision = await response.json()
        assert decision["code"] == "ok" and decision["lane"] == "pro"

        response = await client.get("/api/routing/decide", params={"exclude": " PRO, MAX "})
        assert response.status == 200
        decision = await response.json()
        assert decision["code"] == "no_lane" and decision["lane"] == ""
    assert _configuration(router).read_bytes() == before


@pytest.mark.asyncio
async def test_clear_normalizes_one_lane_and_leaves_the_other_resting(
    router: HarnessRouter,
) -> None:
    router.ledger.set_cooldown("pro", 600, "auth")
    router.ledger.set_cooldown("max", 600, "usage_limit")
    before = router.ledger.snapshot()["max"]
    async with _client() as client:
        response = await client.post("/api/routing/cooldown/clear", json={"lane": " PRO "})
        assert response.status == 200
        assert await response.json() == {"code": "ok", "cleared": ["pro"]}
    usage = router.ledger.snapshot()
    assert usage["pro"].cooldown_until == 0 and usage["pro"].cooldown_reason == ""
    assert usage["max"].cooldown_until == before.cooldown_until
    assert usage["max"].cooldown_reason == "usage_limit"


@pytest.mark.asyncio
async def test_clear_refuses_an_invalid_lane_without_changing_the_ledger(
    router: HarnessRouter,
) -> None:
    router.ledger.set_cooldown("pro", 600, "auth")
    before = router.ledger.path.read_bytes()
    async with _client() as client:
        response = await client.post("/api/routing/cooldown/clear", json={"lane": "../pro"})
        assert response.status == 400
        assert await response.json() == {"error": "invalid lane id", "code": "invalid_lane"}
    assert router.ledger.path.read_bytes() == before


@pytest.mark.asyncio
async def test_clear_without_a_lane_lifts_every_recorded_cooldown(router: HarnessRouter) -> None:
    for lane in ("pro", "max"):
        router.ledger.set_cooldown(lane, 600, "auth")
    async with _client() as client:
        response = await client.post("/api/routing/cooldown/clear", json={})
        assert response.status == 200
        body = await response.json()
        assert body["code"] == "ok" and set(body["cleared"]) == {"pro", "max"}
    assert all(
        usage.cooldown_until == 0 and usage.cooldown_reason == ""
        for usage in router.ledger.snapshot().values()
    )


@pytest.mark.parametrize("action,method", [("check", "post"), ("lane", "put")])
@pytest.mark.asyncio
async def test_unknown_harness_is_refused_before_any_probe_or_edit(
    router: HarnessRouter, monkeypatch: pytest.MonkeyPatch, action: str, method: str
) -> None:
    async def unexpected_probe(*args: Any, **kwargs: Any) -> None:
        pytest.fail("an unknown harness must not start a probe")

    monkeypatch.setattr(api, "check_harness", unexpected_probe)
    before = _configuration(router).read_bytes()
    async with _client() as client:
        response = await getattr(client, method)(
            f"/api/routing/harnesses/unknown-agent/{action}", json={"weight": 2}
        )
        assert response.status == 404
        assert await response.json() == {"error": "unknown harness", "code": "unknown_harness"}
    assert _configuration(router).read_bytes() == before
    assert not router.ledger.path.exists()
    assert router.probes.load() == {}


@pytest.mark.asyncio
async def test_lane_edit_refuses_invalid_json_without_changing_configuration(
    router: HarnessRouter,
) -> None:
    before = _configuration(router).read_bytes()
    async with _client() as client:
        response = await client.put(
            "/api/routing/harnesses/codex/lane",
            data="{",
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 400
        assert await response.json() == {"error": "invalid JSON", "code": "invalid_json"}
    assert _configuration(router).read_bytes() == before


@pytest.mark.parametrize("body", [None, [], {}, "codex"])
@pytest.mark.asyncio
async def test_lane_edit_requires_a_nonempty_object(router: HarnessRouter, body: Any) -> None:
    before = _configuration(router).read_bytes()
    async with _client() as client:
        response = await client.put(
            "/api/routing/harnesses/codex/lane",
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 400
        assert await response.json() == {
            "error": "expected an object of lane fields",
            "code": "invalid_lane_edit",
        }
    assert _configuration(router).read_bytes() == before


@pytest.mark.parametrize("body", [{"weight": -1}, {"harness": "claude"}])
@pytest.mark.asyncio
async def test_lane_edit_refuses_invalid_values_and_identity_changes(
    router: HarnessRouter, body: dict[str, Any]
) -> None:
    before = _configuration(router).read_bytes()
    async with _client() as client:
        response = await client.put("/api/routing/harnesses/codex/lane", json=body)
        assert response.status == 400
        result = await response.json()
        assert result["code"] == "invalid_lane_edit" and result["error"]
    assert _configuration(router).read_bytes() == before


@pytest.mark.asyncio
async def test_lane_edit_preserves_a_broken_operator_configuration(router: HarnessRouter) -> None:
    path = _configuration(router)
    path.write_text("{broken", encoding="utf-8")
    async with _client() as client:
        response = await client.put("/api/routing/harnesses/codex/lane", json={"weight": 2})
        assert response.status == 400
        body = await response.json()
        assert body["code"] == "invalid_lane_edit"
        assert "routing.json is not valid JSON" in body["error"]
    assert path.read_text(encoding="utf-8") == "{broken"


@pytest.mark.asyncio
async def test_lane_edit_normalizes_the_harness_and_changes_only_its_lane(
    router: HarnessRouter,
) -> None:
    path = _configuration(router)
    before = json.loads(path.read_text(encoding="utf-8"))
    async with _client() as client:
        response = await client.put(
            "/api/routing/harnesses/%20CoDeX%20/lane", json={"weight": 4, "enabled": False}
        )
        assert response.status == 200
        body = await response.json()
        assert body["code"] == "ok" and body["lane"]["id"] == "pro"
        assert body["lane"]["weight"] == 4 and body["lane"]["enabled"] is False
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["lanes"][1] == before["lanes"][1]
    assert after["lanes"][0] == {**before["lanes"][0], "weight": 4, "enabled": False}
