"""Hermetic CLI and JSON-handler regressions for the per-file coverage gate.

All providers, probes and router instances are explicit test doubles. Only the
init tests write files, under tmp_path. No server or real harness is started.
"""

import argparse
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from yarl import URL

from junction.harness_router import api, cli, connect
from junction.harness_router.lanes import RoutingConfigError
from junction.harness_router.limits import FAILURE_AUTH, FAILURE_OTHER
from junction.harness_router.service import RoutingError


def lane(name="codex", **kwargs):
    return NS(id=name, harness=name, label=name, model="", billing="subscription", **kwargs)


def router_stub():
    return NS(
        ledger=NS(clear_cooldown=Mock(return_value=["codex"])),
        probes=NS(save=Mock()),
        installed=Mock(return_value=("codex",)),
        settings=Mock(return_value=NS(max_failover=1, lanes=(lane(enabled=True),))),
        record_dispatch=Mock(),
        record_failure=Mock(return_value=FAILURE_AUTH),
        record_success=Mock(),
        next_lane=Mock(return_value=None),
        resolve=Mock(return_value=NS(lane=lane(), routed=True, decision=None)),
    )


def run_args(**changes):
    return NS(
        **dict(
            dict(
                kind="implement",
                cwd="",
                no_prompt=True,
                harness="route",
                prompt="test-only request",
            ),
            **changes,
        )
    )


class TestRouterCliDispatch:
    @pytest.mark.parametrize(
        "argv,action",
        [
            ([], None),
            (["status", "--json"], "status"),
            (["pick", "review", "--prefer", "codex", "--json"], "pick"),
            (["run", "test", "--no-prompt"], "run"),
            (["check", "codex"], "check"),
            (["init", "--all", "--force"], "init"),
            (["clear", "codex"], "clear"),
        ],
    )
    def test_argument_contract(self, argv, action):
        parser = argparse.ArgumentParser()
        cli.add_arguments(parser)
        assert parser.parse_args(argv).route_action == action

    @pytest.mark.parametrize("action", [None, "status", "pick", "run", "check", "init", "clear"])
    def test_dispatch_and_probe_warmup(self, monkeypatch, capsys, action):
        router = router_stub()
        monkeypatch.setattr(cli, "HarnessRouter", lambda: router)
        warm = Mock()
        monkeypatch.setattr(cli, "_warm_sandbox_probe", warm)
        status, pick, run, init = Mock(), Mock(), Mock(return_value=0), Mock()
        check = AsyncMock(return_value=0)
        for name, value in [
            ("_print_status", status),
            ("_print_pick", pick),
            ("_run_sync", run),
            ("_check", check),
            ("_init", init),
        ]:
            monkeypatch.setattr(cli, name, value)
        cli.run_route_command(
            NS(
                route_action=action,
                kind="review",
                prefer="codex",
                as_json=True,
                lanes=["codex"],
                lane="codex",
                force=False,
                all_harnesses=False,
            )
        )
        assert warm.call_count == int(action in ("run", "check"))
        if action in (None, "status"):
            status.assert_called_once_with(router, as_json=True)
        elif action == "pick":
            pick.assert_called_once_with(router, "review", prefer="codex", as_json=True)
        elif action == "run":
            assert run.call_count == 1
        elif action == "check":
            check.assert_awaited_once_with(router, ["codex"])
        elif action == "init":
            init.assert_called_once_with(router, force=False, all_harnesses=False)
        else:
            router.ledger.clear_cooldown.assert_called_once_with("codex")
            assert "cleared: codex" in capsys.readouterr().out

    @pytest.mark.parametrize("action,code", [("run", 1), ("check", 1), ("unknown", 2)])
    def test_nonzero_exit_is_not_hidden(self, monkeypatch, action, code):
        monkeypatch.setattr(cli, "HarnessRouter", router_stub)
        monkeypatch.setattr(cli, "_warm_sandbox_probe", lambda: None)
        monkeypatch.setattr(cli, "_run_sync", lambda *_: 1)
        monkeypatch.setattr(cli, "_check", AsyncMock(return_value=1))
        with pytest.raises(SystemExit) as err:
            cli.run_route_command(NS(route_action=action, lanes=[]))
        assert err.value.code == code

    def test_empty_clear_and_interrupt(self, monkeypatch, capsys):
        router = router_stub()
        router.ledger.clear_cooldown.return_value = []
        monkeypatch.setattr(cli, "HarnessRouter", lambda: router)
        cli.run_route_command(NS(route_action="clear", lane=""))
        router.ledger.clear_cooldown.assert_called_once_with(None)
        assert "nothing was resting" in capsys.readouterr().out
        monkeypatch.setattr(cli, "_run", AsyncMock(side_effect=KeyboardInterrupt))
        assert cli._run_sync(router, run_args()) == 130
        assert "interrupted" in capsys.readouterr().err


class TestRouterCliOutput:
    def test_status_json_and_all_lane_states(self, monkeypatch, capsys):
        monkeypatch.setattr(cli.time, "time", lambda: 10000)
        row = dict(
            id="codex",
            harness="codex",
            billing="subscription",
            enabled=True,
            installed=True,
            cooldown_until=0,
            cooldown_reason="",
            window_limit=0,
            window_used=2,
            day_used=3,
            model="",
            last_error="",
        )
        status = dict(
            source="config",
            enabled=True,
            path="test/routing.json",
            warnings=["fixture warning"],
            lanes=[
                row,
                dict(row, enabled=False),
                dict(row, installed=False),
                dict(
                    row,
                    cooldown_until=13660,
                    cooldown_reason="auth",
                    last_error="test sign-in failure",
                    model="test-model",
                ),
            ],
            unrouted_installed=["claude"],
            kinds=["review", "debug"],
            preview={"review": "codex"},
        )
        router = NS(status=lambda: status)
        cli._print_status(router, as_json=True)
        assert json.loads(capsys.readouterr().out) == status
        cli._print_status(router, as_json=False)
        text = capsys.readouterr().out
        for expected in [
            "fixture warning",
            "disabled",
            "not installed",
            "ready",
            "resting 1h01m",
            "2/?",
            "model=test-model",
            "test sign-in failure",
            "(none)",
        ]:
            assert expected in text
        status.update(source="auto", enabled=False, path="", warnings=[], lanes=[])
        cli._print_status(router, as_json=False)
        assert "No lanes" in capsys.readouterr().out
        assert cli._fmt_until(10065) == "1m05s"
        assert cli._fmt_until(9999) == "0m00s"

    @pytest.mark.parametrize("picked", [True, False])
    def test_pick_preserves_exclusions_and_json(self, monkeypatch, capsys, picked):
        monkeypatch.setattr(cli.time, "time", lambda: 10000)
        chosen = lane()
        candidate = NS(
            lane=chosen,
            excluded="cooldown",
            cooldown_until=10065,
            note="auth",
            score=0.3,
            affinity=0.4,
            headroom=0.2,
        )
        decision = NS(
            lane=chosen if picked else None,
            reason="fixture reason",
            candidates=[candidate],
            to_dict=lambda: {"fixture": picked},
        )
        router = NS(decide=Mock(return_value=decision))
        cli._print_pick(router, "review", prefer="codex", as_json=True)
        assert json.loads(capsys.readouterr().out) == {"fixture": picked}
        router.decide.assert_called_with("review", prefer=["codex"])
        cli._print_pick(router, "review", prefer="", as_json=False)
        text = capsys.readouterr().out
        assert ("pick: codex" if picked else "no lane") in text
        assert "resting 1m05s" in text
        router.decide.assert_called_with("review", prefer=())

    def test_init_is_isolated_and_requires_force(self, tmp_path, monkeypatch):
        path = tmp_path / "routing.json"
        monkeypatch.setattr(cli, "routing_path", lambda: path)
        router = router_stub()
        cli._init(router, force=False, all_harnesses=False)
        first = path.read_text()
        assert [item["harness"] for item in json.loads(first)["lanes"]] == ["codex"]
        with pytest.raises(SystemExit) as err:
            cli._init(router, force=False, all_harnesses=True)
        assert err.value.code == 1
        assert path.read_text() == first
        cli._init(router, force=True, all_harnesses=True)
        lanes = json.loads(path.read_text())["lanes"]
        assert len(lanes) > 1
        assert all(item["enabled"] == (item["harness"] == "codex") for item in lanes)


class TestRouterCliExecution:
    @pytest.mark.asyncio
    async def test_unresolvable_target_does_not_dispatch(self, capsys):
        router = router_stub()
        router.resolve.side_effect = RoutingError("test unavailable", code="not_installed")
        assert await cli._run(router, run_args()) == 2
        router.record_dispatch.assert_not_called()
        assert "test unavailable" in capsys.readouterr().err

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "routed,failure,max_hops,expected",
        [
            (True, FAILURE_AUTH, 1, 0),
            (False, FAILURE_AUTH, 1, 1),
            (True, FAILURE_OTHER, 1, 1),
            (True, FAILURE_AUTH, 0, 1),
        ],
    )
    async def test_start_failure_moves_only_eligible_routed_work(
        self, monkeypatch, routed, failure, max_hops, expected
    ):
        router = router_stub()
        router.resolve.return_value.routed = routed
        router.settings.return_value.max_failover = max_hops
        router.record_failure.return_value = failure
        router.next_lane.return_value = lane("claude")
        first = NS(
            start=AsyncMock(side_effect=RuntimeError("fixture auth failure")),
            shutdown=AsyncMock(),
        )
        second = NS(start=AsyncMock(), shutdown=AsyncMock())
        factory = Mock(side_effect=[first, second])
        monkeypatch.setattr(cli, "_make_provider", factory)
        monkeypatch.setattr(
            cli, "_stream_once", AsyncMock(return_value=(True, "completed fixture"))
        )
        assert await cli._run(router, run_args()) == expected
        first.shutdown.assert_awaited_once()
        assert factory.call_count == (2 if expected == 0 else 1)
        if expected == 0:
            router.record_success.assert_called_once_with("claude")
            second.shutdown.assert_awaited_once()
        else:
            router.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_fallback_and_shutdown_failure_preserve_failure(self, monkeypatch):
        router = router_stub()
        provider = NS(
            start=AsyncMock(side_effect=RuntimeError("fixture auth")),
            shutdown=AsyncMock(side_effect=RuntimeError("fixture shutdown")),
        )
        monkeypatch.setattr(cli, "_make_provider", lambda *_: provider)
        assert await cli._run(router, run_args()) == 1
        provider.shutdown.assert_awaited_once()
        router.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancellation_is_not_a_retry(self, monkeypatch):
        router = router_stub()
        provider = NS(start=AsyncMock(side_effect=asyncio.CancelledError), shutdown=AsyncMock())
        monkeypatch.setattr(cli, "_make_provider", lambda *_: provider)
        with pytest.raises(asyncio.CancelledError):
            await cli._run(router, run_args())
        provider.shutdown.assert_awaited_once()
        router.next_lane.assert_not_called()
        router.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_filters_lanes_records_probes_and_nonzero(self, monkeypatch, capsys):
        router = router_stub()
        router.settings.return_value.lanes = (lane(enabled=True), lane("claude", enabled=False))
        probe = AsyncMock(return_value=NS(status=connect.STATUS_CONNECTED, detail="", models=4))
        monkeypatch.setattr(connect, "probe_harness", probe)
        assert await cli._check(router, ["not-selected"]) == 1
        probe.assert_not_awaited()
        assert await cli._check(router, ["codex"]) == 0
        probe.assert_awaited_once_with("codex", installed=True, model="")
        router.probes.save.assert_called_once()
        for status, word in [
            (connect.STATUS_NEEDS_LOGIN, "log in:"),
            (connect.STATUS_NOT_INSTALLED, "install:"),
        ]:
            probe.return_value = NS(status=status, detail="test detail", models=0)
            assert await cli._check(router, []) == 1
            assert word in capsys.readouterr().out


class TestRouterJsonHandlers:
    @pytest.mark.asyncio
    async def test_status_decision_and_catalog(self, monkeypatch):
        router = NS(
            status=Mock(return_value={"lanes": []}),
            harnesses_view=Mock(return_value={"harnesses": []}),
            decide=Mock(return_value=NS(to_dict=lambda: {"code": "no_lane"})),
        )
        monkeypatch.setattr(api, "get_router", lambda: router)
        assert json.loads((await api.api_status(None)).text) == {"lanes": []}
        assert json.loads((await api.api_harnesses(None)).text) == {"harnesses": []}
        request = NS(rel_url=URL("/?kind=review&role=builder&prefer=CODEX,+Claude&exclude=kiro,,"))
        result = await api.api_decide(request)
        assert result.status == 200
        assert json.loads(result.text) == {"code": "no_lane"}
        router.decide.assert_called_once_with(
            "review", role="builder", prefer=["codex", "claude"], exclude=["kiro"]
        )
        assert api._ids(None) == []

    @pytest.mark.asyncio
    async def test_cooldown_validation_and_empty_fallback(self, monkeypatch):
        clear = Mock(return_value=["codex"])
        monkeypatch.setattr(api, "get_router", lambda: NS(ledger=NS(clear_cooldown=clear)))
        result = await api.api_clear_cooldown(NS(json=AsyncMock(return_value={"lane": "../bad"})))
        assert result.status == 400
        clear.assert_not_called()
        result = await api.api_clear_cooldown(NS(json=AsyncMock(return_value={"lane": " CODEX "})))
        assert json.loads(result.text) == {"code": "ok", "cleared": ["codex"]}
        clear.assert_called_once_with("codex")
        clear.return_value = []
        result = await api.api_clear_cooldown(
            NS(json=AsyncMock(side_effect=ValueError("bad JSON")))
        )
        assert result.status == 200
        clear.assert_called_with(None)

    @pytest.mark.asyncio
    async def test_probe_known_and_unknown_harness(self, monkeypatch):
        router = object()
        monkeypatch.setattr(api, "get_router", lambda: router)
        check = AsyncMock(return_value=NS(to_dict=lambda: {"status": "unknown"}))
        monkeypatch.setattr(api, "check_harness", check)
        result = await api.api_check_harness(NS(match_info={"harness": "not-a-harness"}))
        assert result.status == 404
        check.assert_not_awaited()
        result = await api.api_check_harness(NS(match_info={"harness": " CODEX "}))
        assert json.loads(result.text) == {
            "code": "ok",
            "harness": "codex",
            "probe": {"status": "unknown"},
        }
        check.assert_awaited_once_with("codex", router=router)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [None, [], {}, "invalid"])
    async def test_lane_edit_rejects_nonobject_or_empty(self, monkeypatch, body):
        save = Mock()
        monkeypatch.setattr(api, "save_lane_edit", save)
        result = await api.api_edit_lane(
            NS(match_info={"harness": "codex"}, json=AsyncMock(return_value=body))
        )
        assert result.status == 400
        assert json.loads(result.text)["code"] == "invalid_lane_edit"
        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_lane_edit_errors_success_and_routes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api, "get_router", lambda: NS(home=tmp_path))
        save = Mock(side_effect=RoutingConfigError("fixture invalid edit"))
        monkeypatch.setattr(api, "save_lane_edit", save)
        request = NS(
            match_info={"harness": "codex"}, json=AsyncMock(return_value={"enabled": True})
        )
        result = await api.api_edit_lane(request)
        assert result.status == 400
        assert json.loads(result.text)["code"] == "invalid_lane_edit"
        save.side_effect = None
        save.return_value = {"id": "codex", "enabled": True}
        result = await api.api_edit_lane(request)
        assert result.status == 200
        save.assert_called_with("codex", {"enabled": True}, home=tmp_path)
        assert json.loads(result.text)["lane"] == save.return_value
        request.json.side_effect = ValueError("bad JSON")
        assert json.loads((await api.api_edit_lane(request)).text)["code"] == "invalid_json"
        request.match_info["harness"] = "not-a-harness"
        assert (await api.api_edit_lane(request)).status == 404
        app = web.Application()
        api.register(app)
        routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
        assert ("GET", "/api/routing/decide") in routes
        assert ("PUT", "/api/routing/harnesses/{harness}/lane") in routes
