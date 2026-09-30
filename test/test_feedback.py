"""Tests for the session-pulse survey's inert dashboard routes (feedback.py).

The survey has no backend this project operates, so both routes answer
without leaving the host: eligibility is always false and a submit is refused.
Covers the dashboard-user guard (app tokens refused and SEL-audited), both
answers, and that neither route can make an outbound request.
"""

from __future__ import annotations

import inspect
import json
import urllib.request

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from junction.dashboard.handlers import feedback


def _dashboard_req(method: str, path: str) -> web.Request:
    """A mocked request from a real dashboard user (``app == ""``)."""
    req = make_mocked_request(method, path)
    req["app"] = ""
    return req


def _forbid_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any outbound HTTP attempt fail the test loudly."""

    def _boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("the survey routes must not make an outbound request")

    monkeypatch.setattr(aiohttp, "ClientSession", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)


class TestRequireDashboardUser:
    """The shared guard refuses app tokens and absent-middleware requests."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path", "handler"),
        [
            ("GET", "/api/feedback/eligible", feedback.api_feedback_eligible),
            ("POST", "/api/feedback/submit", feedback.api_feedback_submit),
        ],
    )
    async def test_app_token_is_refused(self, method, path, handler) -> None:
        req = make_mocked_request(method, path)
        req["app"] = "some-app"  # app token: app claim is the app's own name
        resp = await handler(req)
        assert resp.status == 403
        assert json.loads(resp.body) == {"code": "forbidden"}

    @pytest.mark.asyncio
    async def test_absent_app_key_is_refused(self) -> None:
        req = make_mocked_request("GET", "/api/feedback/eligible")  # no app claim
        resp = await feedback.api_feedback_eligible(req)
        assert resp.status == 403
        assert json.loads(resp.body) == {"code": "forbidden"}

    @pytest.mark.asyncio
    async def test_denial_is_sel_audited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict] = []

        class _Recorder:
            def log_tool_invocation(self, **kwargs: object) -> None:
                calls.append(kwargs)

        monkeypatch.setattr(feedback._sel_mod, "sel", lambda: _Recorder())
        req = make_mocked_request("GET", "/api/feedback/eligible")
        req["app"] = "some-app"
        resp = await feedback.api_feedback_eligible(req)
        assert resp.status == 403
        assert calls and calls[0]["outcome"] == "denied"
        assert calls[0]["tool_name"] == "feedback_eligible"


class TestInertRoutes:
    """A dashboard user gets a definite answer and nothing leaves the host."""

    @pytest.mark.asyncio
    async def test_eligible_is_always_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _forbid_egress(monkeypatch)
        resp = await feedback.api_feedback_eligible(_dashboard_req("GET", "/api/feedback/eligible"))
        assert resp.status == 200
        assert json.loads(resp.body) == {"eligible": False}

    @pytest.mark.asyncio
    async def test_submit_is_refused_without_reading_the_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _forbid_egress(monkeypatch)
        req = _dashboard_req("POST", "/api/feedback/submit")

        async def _no_read(*_a: object, **_kw: object) -> None:
            raise AssertionError("a refused submission must not read the body")

        monkeypatch.setattr(req, "read", _no_read)
        monkeypatch.setattr(req, "json", _no_read)
        resp = await feedback.api_feedback_submit(req)
        assert resp.status == 404
        assert json.loads(resp.body) == {"code": "feedback_unavailable"}

    def test_module_names_no_remote_host(self) -> None:
        """No endpoint literal can creep back in behind the inert routes."""
        source = inspect.getsource(feedback)
        assert "https://" not in source
        assert "http://" not in source


class TestRoutes:
    def test_both_routes_are_registered(self) -> None:
        app = web.Application()
        feedback.setup_feedback_routes(app)
        registered = {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
            if route.resource is not None
        }
        assert ("POST", "/api/feedback/submit") in registered
        assert ("GET", "/api/feedback/eligible") in registered
