"""Task-runner steps routed through the harness router (routing.json route_tasks).

Pins the rules in ``junction.task_routing`` and their wiring in
``task_executor``: a step asks the router for a lane, runs on that lane's
harness and model, keeps it across ordinary retries, and leaves it on a
lane-level failure — for free before any tool ran, at the cost of an attempt
after. Every dispatch and outcome lands in the routing ledger. With routing off
(the default) nothing changes: no override reaches the session layer.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from junction import task_executor
from junction.harness_router import service
from junction.harness_router.service import HarnessRouter
from junction.providers.base import EVENT_COMPLETE, EVENT_TEXT_CHUNK, EVENT_TOOL_CALL, LLMEvent
from junction.task_models import SESSION_PREFIX, Project, Task
from junction.task_routing import StepRoute, route_tasks_enabled

_BINS = {"claude": "/b/claude", "codex": "/b/codex", "npx": "/b/npx", "grok": "/b/grok"}
_USAGE_LIMIT = "You've hit your usage limit. Try again in 3 hours."


def _router(tmp_path: Path, *, route_tasks: bool = True, harnesses=("codex", "claude")) -> Any:
    lanes = [{"id": h, "harness": h} for h in harnesses]
    doc = {"enabled": True, "max_failover": 2, "route_tasks": route_tasks, "lanes": lanes}
    (tmp_path / "routing.json").write_text(json.dumps(doc), encoding="utf-8")
    return HarnessRouter(home=tmp_path, which=_BINS.get, env={})


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    r = _router(tmp_path)
    monkeypatch.setattr(service, "get_router", lambda: r)
    return r


# ── StepRoute ──


@pytest.mark.asyncio
async def test_a_step_takes_the_best_lane_for_its_kind_and_keeps_it(router: Any) -> None:
    route = StepRoute("", router=router)  # unnamed kind routes as implement
    first = await route.pick()
    assert first.harness == "codex"
    assert (await route.pick()).id == first.id  # sticky across attempts
    assert router.ledger.snapshot()["codex"].count_since(0) == 2  # one dispatch per attempt
    review = await StepRoute("review", router=router).pick()
    assert review.harness == "claude"


@pytest.mark.asyncio
async def test_a_limit_before_any_tool_is_a_free_move(router: Any) -> None:
    route = StepRoute("implement", router=router)
    await route.pick()
    assert await route.failed(RuntimeError(_USAGE_LIMIT), tool_ran=False) is True
    assert route.lane is None
    moved = await route.pick()
    assert moved.harness == "claude"
    assert router.ledger.snapshot()["codex"].cooldown_reason == "usage_limit"


@pytest.mark.asyncio
async def test_a_limit_after_tool_use_releases_the_lane_but_costs_an_attempt(
    router: Any,
) -> None:
    route = StepRoute("implement", router=router)
    await route.pick()
    assert await route.failed(RuntimeError(_USAGE_LIMIT), tool_ran=True) is False
    assert route.lane is None  # the next attempt still moves
    assert (await route.pick()).harness == "claude"


@pytest.mark.asyncio
async def test_an_ordinary_failure_stays_on_the_lane(router: Any) -> None:
    route = StepRoute("implement", router=router)
    lane = await route.pick()
    assert await route.failed(ValueError("tests still red"), tool_ran=False) is False
    assert route.lane is lane
    assert not router.ledger.snapshot()["codex"].cooling(time.time())


@pytest.mark.asyncio
async def test_free_moves_are_bounded_by_max_failover(tmp_path: Path) -> None:
    router = _router(tmp_path, harnesses=("codex", "claude", "grok"))
    doc = json.loads((tmp_path / "routing.json").read_text(encoding="utf-8"))
    doc["max_failover"] = 1
    (tmp_path / "routing.json").write_text(json.dumps(doc), encoding="utf-8")
    route = StepRoute("implement", router=router)
    await route.pick()
    assert await route.failed(RuntimeError(_USAGE_LIMIT), tool_ran=False) is True
    await route.pick()
    assert await route.failed(RuntimeError(_USAGE_LIMIT), tool_ran=False) is False


@pytest.mark.asyncio
async def test_no_eligible_lane_runs_unrouted(tmp_path: Path) -> None:
    router = _router(tmp_path, harnesses=("codex",))
    route = StepRoute("implement", router=router)
    await route.pick()
    await route.failed(RuntimeError(_USAGE_LIMIT), tool_ran=False)
    assert await route.pick() is None  # the configured agent takes it


@pytest.mark.asyncio
async def test_a_review_prefers_another_agent_but_accepts_the_same_one(tmp_path: Path) -> None:
    router = _router(tmp_path)
    assert (await StepRoute("review", router=router, avoid=["claude"]).pick()).harness == "codex"
    solo_home = tmp_path / "solo"
    solo_home.mkdir()
    alone = _router(solo_home, harnesses=("claude",))
    assert (await StepRoute("review", router=alone, avoid=["claude"]).pick()).harness == "claude"


def test_route_tasks_is_off_unless_switched_on(tmp_path: Path, monkeypatch) -> None:
    off = _router(tmp_path, route_tasks=False)
    monkeypatch.setattr(service, "get_router", lambda: off)
    assert route_tasks_enabled() is False
    on_home = tmp_path / "on"
    on_home.mkdir()
    on = _router(on_home, route_tasks=True)
    monkeypatch.setattr(service, "get_router", lambda: on)
    assert route_tasks_enabled() is True


# ── execute_task wiring ──


class _Client:
    """One scripted turn per instance: raise, or run a tool, reply and complete."""

    def __init__(
        self, error: Exception | None = None, *, tool: bool = False, reply: str = ""
    ) -> None:
        self._error = error
        self._tool = tool
        self._reply = reply

    async def stream(self, _prompt: str):
        if self._tool:
            yield LLMEvent(kind=EVENT_TOOL_CALL, title="edit")
        if self._error is not None:
            raise self._error
        if self._reply:
            yield LLMEvent(kind=EVENT_TEXT_CHUNK, text=self._reply)
        yield LLMEvent(kind=EVENT_COMPLETE)


def _sessions(clients: list[_Client]) -> MagicMock:
    sessions = MagicMock()
    opened: list[dict[str, Any]] = []

    async def _open(_parent: str, _key: str, **kwargs: Any):
        opened.append(kwargs)
        return clients.pop(0), True, False

    sessions.open_task_session = _open
    sessions.opened = opened
    sessions.record_success = MagicMock()
    sessions.record_failure = AsyncMock()
    sessions.check_context_usage = MagicMock()
    sessions.release = MagicMock()
    sessions.reset = AsyncMock()
    return sessions


def _quiet_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_executor, "check_context", AsyncMock())
    monkeypatch.setattr(task_executor, "build_task_prompt", AsyncMock(return_value="PROMPT"))
    monkeypatch.setattr(task_executor, "sel", lambda: MagicMock())
    monkeypatch.setattr(task_executor, "fire_tool_hooks", AsyncMock())
    monkeypatch.setattr(task_executor, "get_global_hook_store", MagicMock())
    fake_config = MagicMock()
    fake_config.load.return_value = MagicMock()
    monkeypatch.setattr(task_executor, "JunctionConfig", fake_config)


async def _execute(run: Project, task: Task, sessions: MagicMock) -> bool:
    return await task_executor.execute_task(
        run,
        task,
        sessions,
        None,
        "",
        None,
        False,
        None,
        "",
        AsyncMock(),
        f"{SESSION_PREFIX}:{run.task_id}:task{task.index}",
    )


def _run(task: Task, *, route_steps: bool | None) -> Project:
    run = Project(spec_path="spec.md", spec_content="body")
    run.task_id = "routed"
    run.tasks = [task]
    run.route_steps = route_steps
    return run


@pytest.mark.asyncio
async def test_a_limited_step_moves_agents_without_spending_an_attempt(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _quiet_executor(monkeypatch)
    task = Task(index=1, title="build it", description="d", kind="implement")
    sessions = _sessions([_Client(RuntimeError(_USAGE_LIMIT)), _Client()])
    assert await _execute(_run(task, route_steps=True), task, sessions) is True
    assert [o["acp_backend_override"] for o in sessions.opened] == ["codex", "claude"]
    assert task.harness == "claude"
    assert task.attempts == 1
    usage = router.ledger.snapshot()
    assert usage["codex"].cooldown_reason == "usage_limit"
    assert usage["claude"].ok == 1


@pytest.mark.asyncio
async def test_a_limit_after_tool_use_moves_on_the_next_attempt(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _quiet_executor(monkeypatch)
    task = Task(index=1, title="build it", description="d", kind="implement")
    sessions = _sessions([_Client(RuntimeError(_USAGE_LIMIT), tool=True), _Client()])
    assert await _execute(_run(task, route_steps=True), task, sessions) is True
    assert [o["acp_backend_override"] for o in sessions.opened] == ["codex", "claude"]
    assert task.attempts == 2


@pytest.mark.asyncio
async def test_a_limit_notice_reply_is_a_lane_failure_not_a_result(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _quiet_executor(monkeypatch)
    task = Task(index=1, title="build it", description="d", kind="implement")
    sessions = _sessions([_Client(reply=_USAGE_LIMIT), _Client(reply="done")])
    assert await _execute(_run(task, route_steps=True), task, sessions) is True
    assert [o["acp_backend_override"] for o in sessions.opened] == ["codex", "claude"]
    assert task.attempts == 1
    assert task.result == "done"
    usage = router.ledger.snapshot()
    assert usage["codex"].cooldown_reason == "usage_limit"
    assert usage["codex"].ok == 0


@pytest.mark.asyncio
async def test_a_notice_after_tool_use_is_the_steps_result(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The notice check applies only to a turn that did no work.
    _quiet_executor(monkeypatch)
    task = Task(index=1, title="build it", description="d", kind="implement")
    sessions = _sessions([_Client(tool=True, reply=_USAGE_LIMIT)])
    assert await _execute(_run(task, route_steps=True), task, sessions) is True
    assert [o["acp_backend_override"] for o in sessions.opened] == ["codex"]
    assert router.ledger.snapshot()["codex"].ok == 1


@pytest.mark.asyncio
async def test_unrouted_runs_pass_no_override(router: Any, monkeypatch) -> None:
    _quiet_executor(monkeypatch)
    monkeypatch.setattr(
        "junction.model_router.routing.apply_role_model", AsyncMock(return_value="auto")
    )
    for route_steps in (False, None):
        task = Task(index=1, title="build it", description="d", kind="implement")
        sessions = _sessions([_Client()])
        assert await _execute(_run(task, route_steps=route_steps), task, sessions) is True
        assert sessions.opened == [{"agent": None, "cwd": None}]
        assert task.harness == ""
    assert router.ledger.snapshot() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
async def test_failed_self_review_keeps_the_execution_lane_and_accounting(
    router: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fallback: bool
) -> None:
    _quiet_executor(monkeypatch)
    task = Task(index=1, title="build it", description="d", kind="implement")
    run = _run(task, route_steps=True)
    run.branch_name = ""
    if fallback:
        for lane in ("codex", "claude"):
            router.record_failure(lane, exc=RuntimeError(_USAGE_LIMIT))
    # SessionManager reuses the existing execution provider for the retry.
    client = _Client()
    sessions = _sessions([client, client])

    async def reject_review(*args):
        # Another turn can change lane headroom during the review. A new route
        # would now pick Claude, while this step's live provider remains Codex.
        if fallback:
            router.ledger.clear_cooldown()
        else:
            router.record_failure("codex", exc=RuntimeError(_USAGE_LIMIT))
        return False

    monkeypatch.setattr(task_executor, "self_review", reject_review)
    assert (
        await task_executor.execute_single_task(
            run,
            task,
            "history",
            sessions,
            None,
            "",
            AsyncMock(),
            None,
            None,
            False,
            None,
            tmp_path,
            MagicMock(),
            AsyncMock(),
        )
        is True
    )
    expected = None if fallback else "codex"
    assert [opened.get("acp_backend_override") for opened in sessions.opened] == [
        expected,
        expected,
    ]
    assert task.harness == ("" if fallback else "codex")
    usage = router.ledger.snapshot()
    assert usage["codex"].ok == (0 if fallback else 2)
    if fallback:
        assert usage["claude"].ok == 0
    else:
        assert "claude" not in usage


def _review_sessions() -> tuple[MagicMock, list[tuple[str, dict[str, Any]]]]:
    opened: list[tuple[str, dict[str, Any]]] = []

    async def _open(_parent: str, key: str, **kwargs: Any):
        opened.append((key, kwargs))
        return MagicMock(), True, False

    sessions = MagicMock()
    sessions.open_task_session = _open
    sessions.release = MagicMock()
    sessions.reset = AsyncMock()
    return sessions, opened


def _review_run(task: Task) -> Project:
    run = _run(task, route_steps=True)
    run.branch_name = ""
    return run


@pytest.mark.asyncio
async def test_a_routed_review_uses_its_own_lane_and_session(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        task_executor, "stream_and_collect", AsyncMock(return_value='{"ok": true}')
    )
    task = Task(index=3, title="build it", description="d", harness="claude")
    sessions, opened = _review_sessions()
    assert await task_executor.self_review(_review_run(task), task, sessions, "") is True
    key, kwargs = opened[0]
    assert key == f"{SESSION_PREFIX}:routed:review3"
    # Claude did the work, so the review goes to the other agent.
    assert kwargs["acp_backend_override"] == "codex"
    sessions.reset.assert_awaited_with(key)


@pytest.mark.asyncio
async def test_a_routed_review_moves_lanes_after_a_lane_failure(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = AsyncMock(side_effect=[RuntimeError(_USAGE_LIMIT), '{"ok": false, "issue": "typo"}'])
    monkeypatch.setattr(task_executor, "stream_and_collect", replies)
    task = Task(index=2, title="build it", description="d", harness="claude")
    sessions, opened = _review_sessions()
    # The second agent's verdict counts: the review is not waved through.
    assert await task_executor.self_review(_review_run(task), task, sessions, "") is False
    assert [kw["acp_backend_override"] for _key, kw in opened] == ["codex", "claude"]
    assert task.error == "Self-review: typo"
    usage = router.ledger.snapshot()
    assert usage["codex"].cooldown_reason == "usage_limit"
    assert usage["claude"].ok == 1
    # Every session the review opened is released.
    assert sessions.release.call_count == len(opened)


@pytest.mark.asyncio
async def test_a_routed_review_treats_a_notice_reply_as_a_lane_failure(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = AsyncMock(side_effect=[_USAGE_LIMIT, '{"ok": true}'])
    monkeypatch.setattr(task_executor, "stream_and_collect", replies)
    task = Task(index=2, title="build it", description="d", harness="claude")
    sessions, opened = _review_sessions()
    assert await task_executor.self_review(_review_run(task), task, sessions, "") is True
    assert [kw["acp_backend_override"] for _key, kw in opened] == ["codex", "claude"]
    assert router.ledger.snapshot()["codex"].ok == 0


@pytest.mark.asyncio
async def test_an_ordinary_review_failure_stays_non_blocking(
    router: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = AsyncMock(side_effect=ValueError("bad json"))
    monkeypatch.setattr(task_executor, "stream_and_collect", replies)
    task = Task(index=2, title="build it", description="d", harness="claude")
    sessions, opened = _review_sessions()
    assert await task_executor.self_review(_review_run(task), task, sessions, "") is True
    assert len(opened) == 1
