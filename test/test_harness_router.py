"""Harness router: lanes, limit detection, ledger, scoring, and dispatch seams."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from junction.harness_router import limits
from junction.harness_router.kinds import TASK_KINDS, normalize_kind
from junction.harness_router.lanes import (
    Lane,
    RoutingSettings,
    auto_lanes,
    load_settings,
    parse_settings,
    template_document,
)
from junction.harness_router.ledger import RETENTION_SECS, UsageLedger
from junction.harness_router.router import (
    DECISION_DISABLED,
    DECISION_NO_LANE,
    DECISION_OK,
    EXCLUDED_COOLDOWN,
    EXCLUDED_DAILY_CAP,
    EXCLUDED_NOT_INSTALLED,
    decide,
)
from junction.harness_router.service import HarnessRouter, RoutingError

NOW = 1_800_000_000.0

_ALL_BINS = {
    "claude": "/b/claude",
    "codex": "/b/codex",
    "npx": "/b/npx",
    "cursor-agent": "/b/cursor-agent",
    "grok": "/b/grok",
    "opencode": "/b/opencode",
}


def _which(installed: dict[str, str]):
    return installed.get


def _lane(lane_id: str, harness: str, **kw: Any) -> Lane:
    raw = {"id": lane_id, "harness": harness, **kw}
    lane = parse_settings({"lanes": [raw]}).lanes[0]
    return lane


def _settings(*lanes: Lane, **kw: Any) -> RoutingSettings:
    return RoutingSettings(lanes=tuple(lanes), **kw)


# ── kinds ──


def test_normalize_kind_falls_back_to_role_then_implement() -> None:
    assert normalize_kind("REVIEW") == "review"
    assert normalize_kind("", role="planning") == "plan"
    assert normalize_kind("nonsense", role="background") == "quick"
    assert normalize_kind(None) == "implement"


# ── limits ──


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Claude AI usage limit reached|1800003600", limits.FAILURE_USAGE_LIMIT),
        ("5-hour limit reached ∙ resets 3pm", limits.FAILURE_USAGE_LIMIT),
        (
            "You've hit your usage limit. Upgrade to Pro or try again in 2 hours 5 minutes.",
            limits.FAILURE_USAGE_LIMIT,
        ),
        ("Insufficient credits. Add more at openrouter.ai", limits.FAILURE_USAGE_LIMIT),
        ("stream error: last status: 429 Too Many Requests", limits.FAILURE_RATE_LIMIT),
        ("Rate limit exceeded, please retry", limits.FAILURE_RATE_LIMIT),
        ("JSON-RPC error: {'code': -32000, 'message': 'Authentication required'}", "auth"),
        ("Invalid API key · Please run /login", limits.FAILURE_AUTH),
        ("ACP runtime 'grok' is not installed. Install Grok CLI", limits.FAILURE_UNAVAILABLE),
        # Task failures that merely mention limits must not rest a lane.
        ("context window limit reached while reading the repo", limits.FAILURE_OTHER),
        ("turn_limit:100", limits.FAILURE_OTHER),
        ("AssertionError at line 429 of test_api.py", limits.FAILURE_OTHER),
        ("", limits.FAILURE_OTHER),
    ],
)
def test_classify_failure(text: str, expected: str) -> None:
    assert limits.classify_failure(text) == expected


def test_classify_exception_by_type() -> None:
    class AcpAuthRequired(Exception):
        pass

    assert limits.classify_exception(AcpAuthRequired("x")) == limits.FAILURE_AUTH
    assert limits.classify_exception(FileNotFoundError("grok")) == limits.FAILURE_UNAVAILABLE
    failure = limits.HarnessLaneFailure(limits.FAILURE_USAGE_LIMIT, "limit")
    assert limits.classify_exception(failure) == limits.FAILURE_USAGE_LIMIT


def test_parse_reset_relative_clock_and_epoch() -> None:
    assert limits.parse_reset_seconds("try again in 2 hours 5 minutes", now=NOW) == 7500
    assert limits.parse_reset_seconds("retry after 30 seconds", now=NOW) == 30
    assert limits.parse_reset_seconds("usage limit reached|1800003600", now=NOW) == 3600
    clock = limits.parse_reset_seconds("limit reached, resets 3pm", now=NOW)
    assert clock is not None and 0 < clock <= 86400
    assert limits.parse_reset_seconds("resets 3", now=NOW) is None
    assert limits.parse_reset_seconds("no hint here", now=NOW) is None


def test_cooldown_bounds_and_ordinary_failures() -> None:
    assert limits.cooldown_seconds(limits.FAILURE_OTHER, "boom") == 0.0
    usage = limits.cooldown_seconds(limits.FAILURE_USAGE_LIMIT, "usage limit", now=NOW)
    assert usage == limits.DEFAULT_COOLDOWN_SECS[limits.FAILURE_USAGE_LIMIT]
    tiny = limits.cooldown_seconds(limits.FAILURE_RATE_LIMIT, "retry after 1 seconds", now=NOW)
    assert tiny == limits.MIN_COOLDOWN_SECS
    huge = limits.cooldown_seconds(limits.FAILURE_USAGE_LIMIT, "try again in 30 days", now=NOW)
    assert huge == limits.MAX_COOLDOWN_SECS


def test_limit_notice_only_for_short_usage_or_auth_replies() -> None:
    assert limits.limit_notice_failure("You've hit your usage limit.") == "usage_limit"
    assert limits.limit_notice_failure("Please run /login first") == "auth"
    # An answer ABOUT rate limiting is not a throttle.
    assert limits.limit_notice_failure("I added a rate limiter to the API.") == ""
    long_answer = "Here is the usage limit design. " + "x" * limits.LIMIT_NOTICE_MAX_CHARS
    assert limits.limit_notice_failure(long_answer) == ""


# ── lanes ──


def test_parse_settings_applies_profile_defaults_and_overrides() -> None:
    settings = parse_settings(
        {
            "max_failover": 1,
            "lanes": [
                {"id": "max", "harness": "claude", "weight": 3, "window_limit": 200},
                {
                    "id": "or-cheap",
                    "harness": "opencode",
                    "model": "openrouter/deepseek/deepseek-v4",
                    "affinity": {"bulk": 1.0},
                    "daily_limit": 50,
                },
            ],
        }
    )
    assert settings.source == "config" and settings.max_failover == 1
    claude, cheap = settings.lanes
    assert claude.billing == "subscription" and claude.weight == 3 and claude.window_limit == 200
    assert claude.affinity_for("plan") == 1.0
    assert cheap.billing == "metered" and cheap.affinity_for("bulk") == 1.0
    assert cheap.model == "openrouter/deepseek/deepseek-v4"


def test_parse_settings_skips_bad_lanes_with_warnings() -> None:
    settings = parse_settings(
        {
            "lanes": [
                {"harness": "nope"},
                {"id": "Bad Id", "harness": "codex"},
                {"id": "a", "harness": "codex", "billing": "weird", "affinity": {"zzz": 1}},
                {"id": "a", "harness": "grok"},
                {"id": "k", "harness": "auto"},
                "not-an-object",
            ]
        }
    )
    assert [lane.id for lane in settings.lanes] == ["a"]
    assert settings.lanes[0].billing == "subscription"
    assert len(settings.warnings) >= 5


def test_kiro_lane_maps_to_empty_backend() -> None:
    lane = _lane("kiro", "kiro")
    assert lane.backend == ""


def test_load_settings_without_file_detects_installed(tmp_path: Path) -> None:
    settings = load_settings(home=tmp_path, which=_which({"grok": "/b/grok"}), env={})
    assert settings.source == "auto"
    assert [lane.harness for lane in settings.lanes] == ["grok"]


def test_load_settings_with_broken_file_degrades_to_detection(tmp_path: Path) -> None:
    (tmp_path / "routing.json").write_text("{not json", encoding="utf-8")
    settings = load_settings(home=tmp_path, which=_which({"grok": "/b/grok"}), env={})
    assert settings.source == "auto"
    assert settings.warnings and "ignored" in settings.warnings[0]


def test_template_round_trips_through_the_parser() -> None:
    doc = template_document(["claude", "codex", "opencode"])
    settings = parse_settings(json.loads(json.dumps(doc)))
    assert [lane.id for lane in settings.lanes] == ["claude", "codex", "opencode"]
    assert not settings.warnings


# ── ledger ──


def test_ledger_records_dispatches_and_limits(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    ledger.record_dispatch("codex", "implement", now=NOW)
    ledger.record_dispatch("codex", "implement", now=NOW + 1)
    until = ledger.record_outcome(
        "codex",
        ok=False,
        failure=limits.FAILURE_USAGE_LIMIT,
        text="You've hit your usage limit, try again in 10 minutes. key=AKIAABCDEFGHIJKLMNOP",
        now=NOW + 2,
    )
    usage = ledger.snapshot()["codex"]
    assert usage.count_since(NOW) == 2
    assert usage.kinds == {"implement": 2}
    assert until == pytest.approx(NOW + 2 + 600)
    assert usage.cooling(NOW + 3) and usage.cooldown_reason == "usage_limit"
    assert "AKIAABCDEFGHIJKLMNOP" not in usage.last_error
    ledger.record_outcome("codex", ok=True, now=NOW + 4)
    assert not ledger.snapshot()["codex"].cooling(NOW + 5)


def test_ledger_task_failure_does_not_rest_the_lane(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    ledger.record_outcome("codex", ok=False, failure=limits.FAILURE_OTHER, text="boom", now=NOW)
    usage = ledger.snapshot()["codex"]
    assert usage.failed == 1 and usage.limited == 0 and not usage.cooling(NOW)


def test_ledger_prunes_old_dispatches_and_survives_corruption(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    ledger.record_dispatch("grok", now=NOW - RETENTION_SECS - 10)
    ledger.record_dispatch("grok", now=NOW)
    assert ledger.snapshot()["grok"].dispatches == [NOW]
    ledger.path.write_text("garbage", encoding="utf-8")
    assert ledger.snapshot() == {}
    ledger.record_dispatch("grok", now=NOW)
    assert ledger.snapshot()["grok"].count_since(0) == 1


def test_clear_cooldown(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    ledger.set_cooldown("a", 600, "usage_limit")
    ledger.set_cooldown("b", 600, "auth")
    assert ledger.clear_cooldown("a") == ["a"]
    assert sorted(ledger.clear_cooldown()) == ["b"]


# ── scoring ──


def _full_house() -> RoutingSettings:
    return _settings(*auto_lanes(["cursor", "claude", "codex", "grok", "opencode"]))


_INSTALLED = ("cursor", "claude", "codex", "grok", "opencode")


@pytest.mark.parametrize(
    ("kind", "lane"),
    [
        ("plan", "claude"),
        ("review", "claude"),
        ("implement", "codex"),
        ("debug", "codex"),
        ("research", "grok"),
        ("quick", "cursor"),
    ],
)
def test_fresh_install_routes_by_affinity(kind: str, lane: str) -> None:
    decision = decide(_full_house(), {}, _INSTALLED, kind=kind, now=NOW)
    assert decision.code == DECISION_OK and decision.lane is not None
    assert decision.lane.id == lane


def test_metered_lane_is_overflow_not_first_choice() -> None:
    decision = decide(_full_house(), {}, _INSTALLED, kind="bulk", now=NOW)
    assert decision.lane is not None and decision.lane.billing != "metered"
    only_metered = decide(_full_house(), {}, ("opencode",), kind="bulk", now=NOW)
    assert only_metered.lane is not None and only_metered.lane.id == "opencode"


def test_load_spreads_across_subscriptions(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    settings = _settings(*auto_lanes(["claude", "codex"]))
    picks = []
    for step in range(40):
        decision = decide(
            settings, ledger.snapshot(), ("claude", "codex"), kind="implement", now=NOW
        )
        assert decision.lane is not None
        picks.append(decision.lane.id)
        ledger.record_dispatch(decision.lane.id, now=NOW - 1 - step)
    assert picks[0] == "codex"
    # Both plans take a real share; neither is drained while the other idles.
    assert 12 <= picks.count("claude") <= 28


def test_cooldown_and_install_state_exclude_lanes(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    ledger.record_outcome("codex", ok=False, failure="usage_limit", text="usage limit", now=NOW)
    decision = decide(
        _full_house(), ledger.snapshot(), ("claude", "codex", "grok"), kind="implement", now=NOW + 5
    )
    assert decision.lane is not None and decision.lane.id == "claude"
    by_id = {c.lane.id: c for c in decision.candidates}
    assert by_id["codex"].excluded == EXCLUDED_COOLDOWN
    assert by_id["cursor"].excluded == EXCLUDED_NOT_INSTALLED
    assert "cursor" not in [lane.id for lane in decision.fallbacks]


def test_window_limit_and_daily_cap(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    for i in range(3):
        ledger.record_dispatch("codex", now=NOW - i)
        ledger.record_dispatch("or", now=NOW - i)
    settings = _settings(
        _lane("codex", "codex", window_limit=3),
        _lane("claude", "claude"),
        _lane("or", "opencode", daily_limit=3),
    )
    decision = decide(
        settings, ledger.snapshot(), ("codex", "claude", "opencode"), kind="implement", now=NOW
    )
    assert decision.lane is not None and decision.lane.id == "claude"
    by_id = {c.lane.id: c for c in decision.candidates}
    assert by_id["or"].excluded == EXCLUDED_DAILY_CAP
    assert by_id["codex"].eligible and by_id["codex"].note == "window limit reached"


def test_exclude_prefer_disabled_and_empty() -> None:
    settings = _full_house()
    excluded = decide(settings, {}, _INSTALLED, kind="implement", exclude=["codex"], now=NOW)
    assert excluded.lane is not None and excluded.lane.id != "codex"
    preferred = decide(settings, {}, _INSTALLED, kind="implement", prefer=["claude"], now=NOW)
    assert preferred.lane is not None and preferred.lane.id == "claude"
    off = decide(_settings(*settings.lanes, enabled=False), {}, _INSTALLED, kind="plan", now=NOW)
    assert off.code == DECISION_DISABLED and off.lane is None
    empty = decide(_settings(), {}, (), kind="plan", now=NOW)
    assert empty.code == DECISION_NO_LANE and "install" in empty.reason


def test_every_kind_has_a_pick_on_a_full_house() -> None:
    for kind in TASK_KINDS:
        assert decide(_full_house(), {}, _INSTALLED, kind=kind, now=NOW).code == DECISION_OK


# ── service ──


def _router(tmp_path: Path, installed: dict[str, str] | None = None) -> HarnessRouter:
    return HarnessRouter(home=tmp_path, which=_which(installed or _ALL_BINS), env={})


def test_resolve_route_lane_and_harness(tmp_path: Path) -> None:
    (tmp_path / "routing.json").write_text(
        json.dumps(
            {"lanes": [{"id": "pro", "harness": "codex"}, {"id": "max", "harness": "claude"}]}
        ),
        encoding="utf-8",
    )
    router = _router(tmp_path)
    routed = router.resolve("route", kind="plan")
    assert routed.routed and routed.lane.id == "max" and routed.backend == "claude"
    assert router.resolve("pro").lane.id == "pro"
    by_harness = router.resolve("codex")
    assert by_harness.lane.id == "pro" and not by_harness.routed
    # A harness with no lane still resolves to its profile when installed.
    assert router.resolve("grok").lane.harness == "grok"
    with pytest.raises(RoutingError) as unknown:
        router.resolve("nope")
    assert unknown.value.code == "unknown_target"


def test_resolve_refuses_uninstalled_harness(tmp_path: Path) -> None:
    router = _router(tmp_path, {"grok": "/b/grok"})
    with pytest.raises(RoutingError) as err:
        router.resolve("cursor")
    assert err.value.code == "not_installed"
    assert router.resolve("route", kind="research").lane.id == "grok"


def test_next_lane_skips_tried_and_resting(tmp_path: Path) -> None:
    router = _router(tmp_path)
    first = router.resolve("route", kind="research").lane
    assert first.id == "grok"
    failure = router.record_failure("grok", text="Authentication required")
    assert failure == limits.FAILURE_AUTH
    nxt = router.next_lane("research", [first.id])
    assert nxt is not None and nxt.id not in ("grok",)
    assert router.resolve("route", kind="research").lane.id != "grok"


def test_settings_reload_on_file_change(tmp_path: Path) -> None:
    router = _router(tmp_path)
    assert router.settings().source == "auto"
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({"lanes": [{"id": "only", "harness": "grok"}]}), encoding="utf-8")
    later = time.time() + 5
    import os

    os.utime(path, (later, later))
    assert [lane.id for lane in router.settings().lanes] == ["only"]


def test_status_shape(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.record_dispatch("claude", "plan")
    status = router.status()
    assert status["code"] == "ok" and status["source"] == "auto"
    assert set(status["preview"]) == set(TASK_KINDS)
    claude = next(row for row in status["lanes"] if row["id"] == "claude")
    assert claude["window_used"] == 1 and claude["installed"] is True


# ── provider factory seam ──


def test_backend_override_resolution() -> None:
    from junction.config.loader import resolve_acp_backend_override

    assert resolve_acp_backend_override("kiro") == ""
    assert resolve_acp_backend_override("opencode") == "opencode"
    with pytest.raises(ValueError):
        resolve_acp_backend_override("not-a-harness")


def test_factory_honours_per_session_backend(tmp_path: Path) -> None:
    from junction.config.loader import JunctionConfig

    cfg = JunctionConfig()
    cfg.agent.acp_backend = "cursor"
    factory = cfg.create_provider_factory()
    default = factory("k1", cwd=str(tmp_path))
    override = factory("k2", cwd=str(tmp_path), acp_backend_override="codex")
    assert default._client.backend == "cursor"
    assert override._client.backend == "codex"


def test_pool_decisions_name_the_harness_bypass() -> None:
    from junction.session import POOL_DECISIONS

    assert "bypass_harness" in POOL_DECISIONS


# ── tool surfaces ──


def test_spawn_run_schema_accepts_routing_fields() -> None:
    from junction.validation import SPAWN_RUN_SCHEMA, ValidationError, validate_tool_args

    cleaned = validate_tool_args(
        {"task": "t", "harness": "route", "kind": "review"}, SPAWN_RUN_SCHEMA
    )
    assert cleaned["harness"] == "route" and cleaned["kind"] == "review"
    with pytest.raises(ValidationError):
        validate_tool_args({"task": "t", "kind": "dance"}, SPAWN_RUN_SCHEMA)
    with pytest.raises(ValidationError):
        validate_tool_args({"task": "t", "harness": "../etc"}, SPAWN_RUN_SCHEMA)


def test_spawn_run_forwards_per_task_harness_and_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from junction import mcp_core
    from junction.mcp_tools import spawn

    bodies: list[dict[str, Any]] = []

    def fake_post(path: str, body: dict[str, Any] | None = None, **_kw: Any) -> dict[str, Any]:
        if path == "/api/spawn":
            assert body is not None
            bodies.append(body)
            return {
                "id": f"id{len(bodies)}",
                "route": {
                    "harness": body.get("harness"),
                    "lane": body.get("harness"),
                    "routed": False,
                },
            }
        return {}

    monkeypatch.setattr(mcp_core, "_post", fake_post)
    monkeypatch.setattr(mcp_core, "_resolve_session_key", lambda: "dashboard:x")
    out = spawn.spawn_run(
        "spawn_run",
        {"tasks": ["a", "b"], "harnesses": ["claude", "codex"], "kinds": ["plan", "implement"]},
    )
    assert [(b["harness"], b["kind"]) for b in bodies] == [
        ("claude", "plan"),
        ("codex", "implement"),
    ]
    assert "on claude/claude" in out and "on codex/codex" in out
    mismatch = spawn.spawn_run("spawn_run", {"tasks": ["a", "b"], "harnesses": ["claude"]})
    assert mismatch.startswith("Error: harnesses length")


def test_route_task_tool_renders_the_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    from junction import mcp_core
    from junction.mcp_tools import routing

    seen: list[str] = []
    decision = decide(_full_house(), {}, _INSTALLED, kind="review", now=NOW).to_dict()

    def fake_get(path: str, session_key: str | None = None) -> dict[str, Any]:
        seen.append(path)
        return decision

    monkeypatch.setattr(mcp_core, "_get", fake_get)
    out = routing.route_task("route_task", {"kind": "review"})
    assert seen == ["/api/routing/decide?kind=review"]
    assert "lane 'claude'" in out and "harness='route'" in out


@pytest.mark.asyncio
async def test_api_decide_and_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from aiohttp.test_utils import make_mocked_request

    from junction.harness_router import api

    router = _router(tmp_path)
    monkeypatch.setattr(api, "get_router", lambda: router)
    resp = await api.api_decide(make_mocked_request("GET", "/api/routing/decide?kind=research"))
    body = json.loads(resp.body)
    assert body["code"] == "ok" and body["lane"] == "grok"
    status = json.loads((await api.api_status(make_mocked_request("GET", "/"))).body)
    assert status["code"] == "ok"


# ── subagent failover ──


class _FakeManager:
    """Just enough of SubagentManager for ``_run_accounted``."""

    def __init__(self, outcomes: list[Exception | None]) -> None:
        self._outcomes = outcomes
        self.ran_on: list[str] = []
        self.teardowns = 0
        self.events: list[dict[str, Any]] = []

    async def _run_inner(self, info: Any, session_key: str) -> None:
        self.ran_on.append(info.harness)
        outcome = self._outcomes.pop(0)
        if outcome is not None:
            raise outcome

    async def _teardown_run_session(self, info: Any, session_key: str) -> None:
        self.teardowns += 1

    async def _fire_event(self, name: str, info: Any, payload: dict[str, Any]) -> None:
        self.events.append(payload)


def _bind(manager: _FakeManager) -> SimpleNamespace:
    from junction.subagent import SubagentManager

    ns = SimpleNamespace()
    ns._run_inner = manager._run_inner
    ns._teardown_run_session = manager._teardown_run_session
    ns._fire_event = manager._fire_event
    ns._failover_lane = SubagentManager._failover_lane.__get__(ns)
    return ns


@pytest.mark.asyncio
async def test_routed_subagent_fails_over_after_a_usage_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from junction import subagent as subagent_mod
    from junction.harness_router import service
    from junction.subagent import SubagentInfo, SubagentManager

    router = _router(tmp_path)
    monkeypatch.setattr(service, "get_router", lambda: router)
    manager = _FakeManager(
        [RuntimeError("You've hit your usage limit. try again in 1 hours"), None]
    )
    info = SubagentInfo(
        id="a1", task="t", harness="codex", lane="codex", route_kind="implement", routed=True
    )
    monkeypatch.setattr(
        subagent_mod, "sel", lambda: SimpleNamespace(log_api_access=lambda **_: None)
    )
    await SubagentManager._run_accounted(_bind(manager), info, "subagent:a1")
    assert manager.ran_on[0] == "codex" and manager.ran_on[1] != "codex"
    assert info.lane == info.harness == manager.ran_on[1]
    assert manager.teardowns == 1
    usage = router.ledger.snapshot()
    assert usage["codex"].cooldown_reason == "usage_limit"
    assert usage[info.lane].ok == 1


@pytest.mark.asyncio
async def test_pinned_subagent_does_not_move(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from junction.harness_router import service
    from junction.subagent import SubagentInfo, SubagentManager

    router = _router(tmp_path)
    monkeypatch.setattr(service, "get_router", lambda: router)
    manager = _FakeManager([RuntimeError("usage limit reached")])
    info = SubagentInfo(id="a2", task="t", harness="codex", lane="codex", routed=False)
    with pytest.raises(RuntimeError):
        await SubagentManager._run_accounted(_bind(manager), info, "subagent:a2")
    assert manager.ran_on == ["codex"]
    assert router.ledger.snapshot()["codex"].cooling(time.time())


@pytest.mark.asyncio
async def test_task_failure_is_not_a_lane_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from junction.harness_router import service
    from junction.subagent import SubagentInfo, SubagentManager

    router = _router(tmp_path)
    monkeypatch.setattr(service, "get_router", lambda: router)
    manager = _FakeManager([ValueError("the tests still fail")])
    info = SubagentInfo(id="a3", task="t", harness="codex", lane="codex", routed=True)
    with pytest.raises(ValueError):
        await SubagentManager._run_accounted(_bind(manager), info, "subagent:a3")
    assert manager.ran_on == ["codex"]
    assert not router.ledger.snapshot()["codex"].cooling(time.time())


@pytest.mark.asyncio
async def test_unaccounted_subagent_skips_the_router(monkeypatch: pytest.MonkeyPatch) -> None:
    from junction.harness_router import service
    from junction.subagent import SubagentInfo, SubagentManager

    def boom() -> None:
        raise AssertionError("router must not be consulted")

    monkeypatch.setattr(service, "get_router", boom)
    manager = _FakeManager([None])
    info = SubagentInfo(id="a4", task="t")
    await SubagentManager._run_accounted(_bind(manager), info, "subagent:a4")
    assert manager.ran_on == [""]
