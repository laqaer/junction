"""Terminal routing contracts with isolated files and simulated providers.

These tests exercise CLI behavior, not machine-local harness verification. Every
provider and connection probe is a stub; no installed harness is ever started.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from junction.harness_router import cli, connect, limits
from junction.harness_router.kinds import TASK_KINDS
from junction.harness_router.service import HarnessRouter
from junction.providers.base import (
    EVENT_COMPLETE,
    EVENT_PERMISSION_REQUEST,
    EVENT_TEXT_CHUNK,
    LLMEvent,
)


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Harness detection also inspects the OS home, separately from JUNCTION_HOME.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def _arguments(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    cli.add_arguments(parser)
    return parser.parse_args(argv)


def _router(tmp_path: Path, *, lanes: list[dict[str, Any]] | None = None, **settings: Any):
    if lanes is not None:
        (tmp_path / "routing.json").write_text(
            json.dumps({"lanes": lanes, **settings}), encoding="utf-8"
        )
    binaries = {"codex": "/stub/codex", "claude": "/stub/claude", "npx": "/stub/npx"}
    return HarnessRouter(home=tmp_path, which=binaries.get, env={})


class _Provider:
    """An in-process provider with observable lifetime and deterministic events."""

    def __init__(
        self,
        events: list[LLMEvent] | None = None,
        *,
        start_error: BaseException | None = None,
        shutdown_error: Exception | None = None,
    ) -> None:
        self.events = events or []
        self.start_error = start_error
        self.shutdown_error = shutdown_error
        self.started = 0
        self.stopped = 0
        self.prompts: list[str] = []

    async def start(self) -> None:
        self.started += 1
        if self.start_error is not None:
            raise self.start_error

    async def shutdown(self) -> None:
        self.stopped += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error

    async def stream(self, prompt: str):
        self.prompts.append(prompt)
        for event in self.events:
            yield event


class TestArguments:
    def test_run_accepts_explicit_routing_and_permission_options(self) -> None:
        args = _arguments(
            "run",
            "repair the parser",
            "-k",
            "review",
            "--harness",
            "pro",
            "--cwd",
            "work",
            "--no-prompt",
        )
        assert (args.prompt, args.kind, args.harness, args.cwd, args.no_prompt) == (
            "repair the parser",
            "review",
            "pro",
            "work",
            True,
        )
        defaults = _arguments("run", "reply ok")
        assert (defaults.kind, defaults.harness, defaults.cwd, defaults.no_prompt) == (
            "implement",
            "route",
            "",
            False,
        )

    def test_check_init_and_clear_parse_their_scoped_options(self) -> None:
        assert _arguments("check", "pro", "max").lanes == ["pro", "max"]
        assert _arguments("check").lanes == []
        args = _arguments("init", "--force", "--all")
        assert args.force and args.all_harnesses
        assert _arguments("clear").lane == ""
        assert _arguments("clear", "pro").lane == "pro"

    def test_pick_rejects_an_unknown_task_kind(self) -> None:
        assert _arguments("pick", "review", "--prefer", "pro", "--json").as_json
        with pytest.raises(SystemExit) as exc:
            _arguments("pick", "not-a-kind")
        assert exc.value.code == 2


class TestStatusAndPick:
    def test_status_json_round_trips_the_actual_router_payload(self, tmp_path, capsys) -> None:
        router = _router(tmp_path)
        cli._print_status(router, as_json=True)
        result = json.loads(capsys.readouterr().out)
        assert result["source"] == "auto"
        assert {row["harness"] for row in result["lanes"]} == {"codex", "claude"}
        assert set(result["preview"]) == set(TASK_KINDS)

    def test_status_distinguishes_disabled_missing_resting_and_ready_lanes(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(cli.time, "time", lambda: 1000.0)
        router = _router(
            tmp_path,
            lanes=[
                {"id": "off", "harness": "codex", "enabled": False},
                {"id": "missing", "harness": "grok"},
                {"id": "rest", "harness": "claude"},
                {"id": "ready", "harness": "codex", "model": "operator-model"},
            ],
        )
        router.ledger.record_outcome(
            "rest",
            ok=False,
            failure=limits.FAILURE_AUTH,
            text="login expired",
            harness="claude",
            now=1000.0,
        )
        cli._print_status(router, as_json=False)
        output = capsys.readouterr().out
        rows = {line.split()[0]: line for line in output.splitlines() if line.strip()}
        assert "disabled" in rows["off"]
        assert "not installed" in rows["missing"]
        assert "resting" in rows["rest"] and "(auth)" in rows["rest"]
        assert "last error: login expired" in output
        assert "ready model=operator-model" in rows["ready"]
        assert "lanes from routing.json" in output
        assert "config:" in output and "Current pick per kind:" in output

    def test_status_explains_empty_detection_and_invalid_configuration(self, tmp_path, capsys):
        router = HarnessRouter(home=tmp_path, which=lambda _name: None, env={})
        (tmp_path / "routing.json").write_text("invalid json", encoding="utf-8")
        cli._print_status(router, as_json=False)
        output = capsys.readouterr().out
        assert "auto-detected" in output and "  ! " in output
        assert "No lanes. Install at least one harness" in output

    def test_status_names_installed_harnesses_omitted_from_configuration(self, tmp_path, capsys):
        router = _router(tmp_path, lanes=[{"id": "pro", "harness": "codex"}], enabled=False)
        cli._print_status(router, as_json=False)
        output = capsys.readouterr().out
        assert "Harness router: OFF" in output
        assert "installed but not in routing.json: claude" in output

    def test_pick_json_and_text_explain_the_selected_lane_and_cooldown(self, tmp_path, capsys):
        router = _router(tmp_path)
        router.record_failure("claude", text="login expired", harness="claude")
        cli._print_pick(router, "review", prefer="codex", as_json=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["lane"] == "codex"
        assert any(c["excluded"] == "cooldown" for c in payload["candidates"])
        cli._print_pick(router, "review", prefer="", as_json=False)
        output = capsys.readouterr().out
        assert "pick: codex" in output and "→ codex" in output
        assert "resting" in output and "(auth)" in output

    def test_pick_explains_when_no_lane_is_available(self, tmp_path, capsys):
        router = HarnessRouter(home=tmp_path, which=lambda _name: None, env={})
        cli._print_pick(router, "implement", prefer="", as_json=False)
        assert "no lane:" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("until", "expected"), [(4660.0, "1h01m"), (1061.0, "1m01s"), (0, "0m00s")]
    )
    def test_cooldown_display_never_reports_negative_time(self, monkeypatch, until, expected):
        monkeypatch.setattr(cli.time, "time", lambda: 1000.0)
        assert cli._fmt_until(until) == expected


class TestCommandDispatch:
    def test_default_command_prints_status_without_probing_a_harness(
        self, tmp_path, monkeypatch, capsys
    ):
        router = _router(tmp_path)
        monkeypatch.setattr(cli, "HarnessRouter", lambda: router)
        warm = Mock()
        monkeypatch.setattr(cli, "_warm_sandbox_probe", warm)
        cli.run_route_command(_arguments())
        assert "Harness router: on" in capsys.readouterr().out
        warm.assert_not_called()
        cli.run_route_command(_arguments("pick", "quick", "--json"))
        assert json.loads(capsys.readouterr().out)["kind"] == "quick"

    @pytest.mark.parametrize(
        ("action", "code"), [("run", 0), ("run", 1), ("check", 0), ("check", 1)]
    )
    def test_process_exit_reflects_run_or_probe_failure(self, tmp_path, monkeypatch, action, code):
        router = _router(tmp_path)
        monkeypatch.setattr(cli, "HarnessRouter", lambda: router)
        warm = Mock()
        monkeypatch.setattr(cli, "_warm_sandbox_probe", warm)
        run = Mock(return_value=code)
        check = AsyncMock(return_value=code)
        monkeypatch.setattr(cli, "_run_sync", run)
        monkeypatch.setattr(cli, "_check", check)
        args = _arguments(action, *(["hello"] if action == "run" else ["codex"]))
        if code:
            with pytest.raises(SystemExit) as exc:
                cli.run_route_command(args)
            assert exc.value.code == code
        else:
            cli.run_route_command(args)
        warm.assert_called_once_with()
        if action == "run":
            run.assert_called_once_with(router, args)
            check.assert_not_called()
        else:
            check.assert_awaited_once_with(router, ["codex"])
            run.assert_not_called()

    def test_clear_only_lifts_the_named_lane_then_reports_nothing_resting(
        self, tmp_path, monkeypatch, capsys
    ):
        router = _router(tmp_path)
        monkeypatch.setattr(cli, "HarnessRouter", lambda: router)
        for harness in ("codex", "claude"):
            router.record_failure(harness, text="login expired", harness=harness)
        cli.run_route_command(_arguments("clear", "codex"))
        assert capsys.readouterr().out.strip() == "cleared: codex"
        assert router.ledger.snapshot()["claude"].cooldown_reason == limits.FAILURE_AUTH
        cli.run_route_command(_arguments("clear"))
        assert capsys.readouterr().out.strip() == "cleared: claude"
        cli.run_route_command(_arguments("clear"))
        assert "nothing was resting" in capsys.readouterr().out

    def test_init_writes_only_the_isolated_routing_file_and_respects_overwrite(
        self, tmp_path, monkeypatch, capsys
    ):
        router = _router(tmp_path)
        monkeypatch.setattr(cli, "HarnessRouter", lambda: router)
        path = tmp_path / "routing.json"
        monkeypatch.setattr(cli, "routing_path", lambda: path)
        cli.run_route_command(_arguments("init"))
        saved = path.read_text(encoding="utf-8")
        assert {lane["harness"] for lane in json.loads(saved)["lanes"]} == {"claude", "codex"}
        with pytest.raises(SystemExit) as exc:
            cli.run_route_command(_arguments("init"))
        assert exc.value.code == 1 and path.read_text(encoding="utf-8") == saved
        cli.run_route_command(_arguments("init", "--force", "--all"))
        lanes = json.loads(path.read_text(encoding="utf-8"))["lanes"]
        assert len(lanes) > 2
        assert all(lane["enabled"] == (lane["harness"] in {"claude", "codex"}) for lane in lanes)
        assert "edit weight / window_limit / billing" in capsys.readouterr().out

    def test_unknown_command_exits_as_usage_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(cli, "HarnessRouter", lambda: _router(tmp_path))
        with pytest.raises(SystemExit) as exc:
            cli.run_route_command(argparse.Namespace(route_action="typo"))
        assert exc.value.code == 2
        assert "unknown route action: typo" in capsys.readouterr().err

    @pytest.mark.parametrize("failure", [False, True])
    def test_sandbox_warmup_is_attempted_and_failure_remains_nonfatal(self, monkeypatch, failure):
        from junction import sandbox

        warm = Mock(side_effect=RuntimeError("probe unavailable") if failure else None)
        monkeypatch.setattr(sandbox, "warm_backend", warm)
        cli._warm_sandbox_probe()
        warm.assert_called_once_with()


class TestStreamingRun:
    def test_provider_factory_receives_the_lane_model_and_harness(self, tmp_path, monkeypatch):
        from junction.config import JunctionConfig, loader

        lane = _router(tmp_path).settings().lanes[0]
        cfg = JunctionConfig()
        monkeypatch.setattr(JunctionConfig, "load", lambda: cfg)
        provider = object()
        factory = Mock(return_value=provider)
        build = Mock(return_value=factory)
        monkeypatch.setattr(loader, "build_provider_factory", build)
        assert cli._make_provider(lane, "") is provider
        build.assert_called_once_with(cfg)
        session_key = factory.call_args.args[0]
        assert session_key.startswith(f"{cli.RUN_SESSION_PREFIX}:")
        assert factory.call_args.kwargs == {
            "agent": "junction",
            "cwd": None,
            "model_override": None,
            "acp_backend_override": lane.harness,
        }

    @pytest.mark.asyncio
    async def test_stream_joins_chunks_stops_at_completion_and_reuses_permission_gate(
        self, monkeypatch, capsys
    ):
        from junction import cli_chat

        gate = object()
        build = Mock(return_value=gate)
        answer = AsyncMock()
        monkeypatch.setattr(cli_chat, "_build_tool_gate", build)
        monkeypatch.setattr(cli_chat, "_answer_permission", answer)
        first = LLMEvent(kind=EVENT_PERMISSION_REQUEST, request_id="one")
        second = LLMEvent(kind=EVENT_PERMISSION_REQUEST, request_id="two")
        provider = _Provider(
            [
                LLMEvent(kind=EVENT_TEXT_CHUNK, text="hello "),
                first,
                second,
                LLMEvent(kind=EVENT_TEXT_CHUNK, text="world"),
                LLMEvent(kind=EVENT_COMPLETE),
                LLMEvent(kind=EVENT_TEXT_CHUNK, text="ignored"),
            ]
        )
        assert await cli._stream_once(provider, "question", interactive=False) == (
            True,
            "hello world",
        )
        assert capsys.readouterr().out == "hello world\n"
        assert provider.prompts == ["question"]
        build.assert_called_once_with("junction")
        assert answer.await_count == 2
        answer.assert_any_await(provider, first, interactive=False, gate=gate)
        answer.assert_any_await(provider, second, interactive=False, gate=gate)

    @pytest.mark.asyncio
    async def test_empty_text_is_not_claimed_as_output(self, capsys):
        provider = _Provider(
            [LLMEvent(kind=EVENT_TEXT_CHUNK, text=""), LLMEvent(kind=EVENT_COMPLETE)]
        )
        assert await cli._stream_once(provider, "question", interactive=True) == (False, "")
        assert capsys.readouterr().out == "\n"

    @pytest.mark.asyncio
    async def test_run_records_success_for_the_producing_harness_and_closes_provider(
        self, tmp_path, monkeypatch, capsys
    ):
        router = _router(tmp_path)
        provider = _Provider(
            [LLMEvent(kind=EVENT_TEXT_CHUNK, text="done"), LLMEvent(kind=EVENT_COMPLETE)]
        )
        factory = Mock(return_value=provider)
        monkeypatch.setattr(cli, "_make_provider", factory)
        monkeypatch.chdir(tmp_path)
        assert await cli._run(router, _arguments("run", "repair it")) == 0
        usage = router.ledger.snapshot()
        lane_id = factory.call_args.args[0].id
        assert usage[lane_id].ok == 1
        assert usage[lane_id].harness == factory.call_args.args[0].harness
        assert len(usage[lane_id].dispatches) == 1
        assert factory.call_args.args[1] == str(tmp_path)
        assert provider.started == provider.stopped == 1
        assert provider.prompts == ["repair it"]
        output = capsys.readouterr()
        assert output.out == "done\n" and "[route]" in output.err

    @pytest.mark.asyncio
    async def test_failed_routing_returns_usage_error_without_creating_a_provider(
        self, tmp_path, monkeypatch, capsys
    ):
        router = HarnessRouter(home=tmp_path, which=lambda _name: None, env={})
        factory = Mock()
        monkeypatch.setattr(cli, "_make_provider", factory)
        assert await cli._run(router, _arguments("run", "hello")) == 2
        factory.assert_not_called()
        assert "route:" in capsys.readouterr().err

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("target", "error", "hops"),
        [
            ("codex", RuntimeError("login expired"), 2),
            ("route", RuntimeError("ordinary task failed"), 2),
            ("route", RuntimeError("login expired"), 0),
        ],
    )
    async def test_pinned_task_and_exhausted_hop_failures_never_move_lanes(
        self, tmp_path, monkeypatch, capsys, target, error, hops
    ):
        router = _router(tmp_path, lanes=[{"id": "codex", "harness": "codex"}], max_failover=hops)
        provider = _Provider(start_error=error)
        factory = Mock(return_value=provider)
        monkeypatch.setattr(cli, "_make_provider", factory)
        assert await cli._run(router, _arguments("run", "repair it", "--harness", target)) == 1
        factory.assert_called_once()
        assert provider.stopped == 1 and provider.prompts == []
        assert router.ledger.snapshot()["codex"].failed == 1
        assert "failed (" in capsys.readouterr().err

    @pytest.mark.asyncio
    @pytest.mark.parametrize("notice", [False, True])
    async def test_routed_lane_failure_uses_fallback_and_attributes_both_outcomes(
        self, tmp_path, monkeypatch, capsys, notice
    ):
        router = _router(tmp_path)
        first = _Provider(
            (
                [
                    LLMEvent(kind=EVENT_TEXT_CHUNK, text="You've hit your usage limit."),
                    LLMEvent(kind=EVENT_COMPLETE),
                ]
                if notice
                else []
            ),
            start_error=None if notice else RuntimeError("login expired"),
        )
        second = _Provider(
            [LLMEvent(kind=EVENT_TEXT_CHUNK, text="fixed"), LLMEvent(kind=EVENT_COMPLETE)]
        )
        factory = Mock(side_effect=[first, second])
        monkeypatch.setattr(cli, "_make_provider", factory)
        assert await cli._run(router, _arguments("run", "repair it")) == 0
        lanes = [call.args[0] for call in factory.call_args_list]
        assert len(lanes) == 2 and lanes[0].id != lanes[1].id
        usage = router.ledger.snapshot()
        assert usage[lanes[0].id].failed == 1 and usage[lanes[0].id].harness == lanes[0].harness
        assert usage[lanes[1].id].ok == 1 and usage[lanes[1].id].harness == lanes[1].harness
        assert first.stopped == second.stopped == 1
        assert second.prompts == ["repair it"]
        assert "moving to" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_cancellation_closes_provider_without_recording_a_lane_failure(
        self, tmp_path, monkeypatch
    ):
        router = _router(tmp_path)
        provider = _Provider(start_error=asyncio.CancelledError())
        factory = Mock(return_value=provider)
        monkeypatch.setattr(cli, "_make_provider", factory)
        with pytest.raises(asyncio.CancelledError):
            await cli._run(router, _arguments("run", "hello"))
        assert provider.stopped == 1
        assert router.ledger.snapshot()[factory.call_args.args[0].id].failed == 0

    @pytest.mark.asyncio
    async def test_shutdown_error_does_not_turn_completed_work_into_failure(
        self, tmp_path, monkeypatch
    ):
        router = _router(tmp_path)
        provider = _Provider(shutdown_error=RuntimeError("already closed"))
        monkeypatch.setattr(cli, "_make_provider", lambda _lane, _cwd: provider)
        assert await cli._run(router, _arguments("run", "hello")) == 0
        assert provider.stopped == 1

    def test_sync_wrapper_reports_keyboard_interrupt_as_shell_exit_130(
        self, tmp_path, monkeypatch, capsys
    ):
        async def interrupted(_router, _args):
            raise KeyboardInterrupt

        monkeypatch.setattr(cli, "_run", interrupted)
        assert cli._run_sync(_router(tmp_path), _arguments("run", "hello")) == 130
        assert "interrupted" in capsys.readouterr().err


class TestConnectionOutput:
    @pytest.mark.asyncio
    async def test_disabled_and_unselected_lanes_are_not_probed(
        self, tmp_path, monkeypatch, capsys
    ):
        router = _router(tmp_path, lanes=[{"id": "pro", "harness": "codex", "enabled": False}])
        probe = AsyncMock()
        monkeypatch.setattr(connect, "probe_harness", probe)
        assert await cli._check(router, []) == 1
        assert "no lanes to check" in capsys.readouterr().out
        probe.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "expected", "code"),
        [
            (connect.STATUS_CONNECTED, "auth unverified", 0),
            (connect.STATUS_NEEDS_LOGIN, "log in: codex login", 1),
            (connect.STATUS_NOT_INSTALLED, "install: npm i -g @openai/codex", 1),
            (connect.STATUS_TIMEOUT, "timeout", 1),
        ],
    )
    async def test_probe_status_and_exit_code_remain_honest(
        self, tmp_path, monkeypatch, capsys, status, expected, code
    ):
        router = _router(
            tmp_path, lanes=[{"id": "pro", "harness": "codex", "model": "operator-model"}]
        )
        result = connect.ProbeResult("codex", status, models=3, checked_at=1000)
        probe = AsyncMock(return_value=result)
        monkeypatch.setattr(connect, "probe_harness", probe)
        assert await cli._check(router, ["pro"]) == code
        probe.assert_awaited_once_with("codex", installed=True, model="operator-model")
        assert expected in capsys.readouterr().out
        assert router.probes.load()["codex"].status == status

    @pytest.mark.asyncio
    async def test_nonfeatured_harness_uses_registry_login_hint(
        self, tmp_path, monkeypatch, capsys
    ):
        router = _router(tmp_path, lanes=[{"id": "kiro", "harness": "kiro"}])
        probe = AsyncMock(
            return_value=connect.ProbeResult(
                "kiro", connect.STATUS_NEEDS_LOGIN, detail="sign in first"
            )
        )
        monkeypatch.setattr(connect, "probe_harness", probe)
        monkeypatch.setattr(connect, "login_hint", lambda _harness: "fixture login hint")
        assert await cli._check(router, []) == 1
        assert "log in: fixture login hint" in capsys.readouterr().out
        probe.assert_awaited_once_with("kiro", installed=False, model="")
