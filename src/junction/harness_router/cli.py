"""``junction route`` — see and use the harness router from a terminal.

    junction route                     lanes, windows, cooldowns, per-kind picks
    junction route pick KIND           rank every lane for one kind of work
    junction route run "PROMPT"        run one prompt on the routed harness
    junction route check [LANE ...]    start each harness once: installed? logged in?
    junction route init                write routing.json from the installed harnesses
    junction route clear [LANE]        lift a cooldown early

``route pick`` is the CLI twin of the ``route_task`` MCP tool; ``route run`` is
the terminal twin of ``spawn_run(harness="route")``.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

from junction.harness_router.kinds import KIND_DESCRIPTIONS, TASK_KINDS
from junction.harness_router.lanes import routing_path, template_document
from junction.harness_router.limits import LANE_FAILURES
from junction.harness_router.service import HarnessRouter, RoutingError

logger = logging.getLogger(__name__)

# `route check` gives each harness this long to answer initialize + session/new.
# npx-launched adapters download on first use, so the first check is slow.
CHECK_TIMEOUT_SECS = 120.0
# Session-key prefix for `route run`; the provider gets a fresh workspace each run.
RUN_SESSION_PREFIX = "route-run"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="route_action")
    status = sub.add_parser("status", help="Lanes, usage windows, cooldowns, per-kind picks")
    status.add_argument("--json", dest="as_json", action="store_true", help="Print JSON")

    pick = sub.add_parser("pick", help="Rank every lane for one kind of work")
    pick.add_argument("kind", choices=TASK_KINDS, help="Kind of work")
    pick.add_argument("--prefer", default="", help="Lane or harness to favor slightly")
    pick.add_argument("--json", dest="as_json", action="store_true", help="Print JSON")

    run = sub.add_parser("run", help="Run one prompt on the routed (or named) harness")
    run.add_argument("prompt", help="What to do")
    run.add_argument(
        "-k", "--kind", choices=TASK_KINDS, default="implement", help="Kind of work (routing)"
    )
    run.add_argument(
        "--harness",
        default="route",
        help="'route' (default), a lane id, or a harness name (claude, codex, …)",
    )
    run.add_argument("--cwd", default="", help="Working directory (default: current)")
    run.add_argument(
        "--no-prompt",
        dest="no_prompt",
        action="store_true",
        help="Deny tool permission requests instead of asking at the terminal",
    )

    check = sub.add_parser("check", help="Start each harness once to verify install and login")
    check.add_argument("lanes", nargs="*", help="Lane ids (default: every enabled lane)")

    init = sub.add_parser("init", help="Write routing.json from the installed harnesses")
    init.add_argument("--force", action="store_true", help="Overwrite an existing routing.json")
    init.add_argument(
        "--all",
        dest="all_harnesses",
        action="store_true",
        help="Include every known harness, not only the installed ones",
    )

    clear = sub.add_parser("clear", help="Lift a lane's cooldown early")
    clear.add_argument("lane", nargs="?", default="", help="Lane id (default: every lane)")


def _warm_sandbox_probe() -> None:
    """Fill the sandbox probe cache before the event loop starts.

    The probe never runs on a running loop; a cold cache there reads as "no
    sandbox backend" and the harness spawn is refused. Blocking here, before
    ``asyncio.run``, is the CLI-path warm-up ``sandbox.warm_backend`` exists for.
    """
    try:
        from junction.sandbox import warm_backend

        warm_backend()
    except Exception:
        logger.debug("sandbox warm-up failed; spawn will re-probe", exc_info=True)


def run_route_command(args: argparse.Namespace) -> None:
    action = getattr(args, "route_action", None) or "status"
    router = HarnessRouter()
    if action in ("run", "check"):
        _warm_sandbox_probe()
    if action == "status":
        _print_status(router, as_json=getattr(args, "as_json", False))
    elif action == "pick":
        _print_pick(router, args.kind, prefer=args.prefer, as_json=args.as_json)
    elif action == "run":
        code = _run_sync(router, args)
        if code:
            raise SystemExit(code)
    elif action == "check":
        code = asyncio.run(_check(router, list(args.lanes)))
        if code:
            raise SystemExit(code)
    elif action == "init":
        _init(router, force=args.force, all_harnesses=args.all_harnesses)
    elif action == "clear":
        cleared = router.ledger.clear_cooldown(args.lane or None)
        print("cleared: " + (", ".join(cleared) if cleared else "nothing was resting"))
    else:
        print(f"unknown route action: {action}", file=sys.stderr)
        raise SystemExit(2)


# ── status / pick ──


def _fmt_until(until: float) -> str:
    left = max(0, int(until - time.time()))
    hours, rem = divmod(left, 3600)
    return f"{hours}h{rem // 60:02d}m" if hours else f"{rem // 60}m{rem % 60:02d}s"


def _print_status(router: HarnessRouter, *, as_json: bool) -> None:
    status = router.status()
    if as_json:
        print(json.dumps(status, indent=2))
        return
    source = "routing.json" if status["source"] == "config" else "auto-detected (no routing.json)"
    print(f"Harness router: {'on' if status['enabled'] else 'OFF'} — lanes from {source}")
    if status["path"]:
        print(f"  config: {status['path']}")
    for warning in status["warnings"]:
        print(f"  ! {warning}")
    if not status["lanes"]:
        print("\nNo lanes. Install at least one harness, e.g.:")
        print("  Claude Code: npm i -g @anthropic-ai/claude-code && claude   (log in)")
        print("  Codex:       npm i -g @openai/codex && codex login")
        print("  OpenCode:    npm i -g opencode-ai && opencode auth login   (OpenRouter)")
        return
    print()
    header = f"  {'lane':<14} {'harness':<9} {'billing':<12} {'window':>9} {'24h':>5}  state"
    print(header)
    for row in status["lanes"]:
        if not row["enabled"]:
            state = "disabled"
        elif not row["installed"]:
            state = "not installed"
        elif row["cooldown_until"]:
            state = f"resting {_fmt_until(row['cooldown_until'])} ({row['cooldown_reason']})"
        else:
            state = "ready"
        cap = row["window_limit"] or "?"
        window = f"{row['window_used']}/{cap}"
        model = f" model={row['model']}" if row["model"] else ""
        print(
            f"  {row['id']:<14} {row['harness']:<9} {row['billing']:<12} {window:>9} "
            f"{row['day_used']:>5}  {state}{model}"
        )
        if row["last_error"] and row["cooldown_until"]:
            print(f"  {'':<14} last error: {row['last_error'][:120]}")
    if status["unrouted_installed"]:
        print("\n  installed but not in routing.json: " + ", ".join(status["unrouted_installed"]))
    print("\nCurrent pick per kind:")
    for kind in status["kinds"]:
        print(f"  {kind:<9} → {status['preview'].get(kind) or '(none)'}")
    print('\nUse: junction route run -k <kind> "<prompt>"   ·   junction route pick <kind>')


def _print_pick(router: HarnessRouter, kind: str, *, prefer: str, as_json: bool) -> None:
    decision = router.decide(kind, prefer=[prefer] if prefer else ())
    if as_json:
        print(json.dumps(decision.to_dict(), indent=2))
        return
    print(f"{kind}: {KIND_DESCRIPTIONS.get(kind, '')}")
    if decision.lane:
        print(f"pick: {decision.lane.id} — {decision.reason}")
    else:
        print(f"no lane: {decision.reason}")
    for cand in decision.candidates:
        mark = "→" if decision.lane and cand.lane.id == decision.lane.id else " "
        state = cand.excluded or "ok"
        if cand.excluded == "cooldown":
            state = f"resting {_fmt_until(cand.cooldown_until)} ({cand.note})"
        print(
            f" {mark} {cand.lane.id:<14} score {cand.score:.3f}  affinity {cand.affinity:.2f}  "
            f"headroom {cand.headroom:.0%}  {cand.lane.billing:<12} {state}"
        )


# ── run ──


def _run_sync(router: HarnessRouter, args: argparse.Namespace) -> int:
    try:
        return asyncio.run(_run(router, args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


def _make_provider(lane: Any, cwd: str) -> Any:
    from junction.config import JunctionConfig
    from junction.config.loader import build_provider_factory

    factory = build_provider_factory(JunctionConfig.load())
    return factory(
        f"{RUN_SESSION_PREFIX}:{uuid.uuid4().hex[:8]}",
        agent="junction",
        cwd=cwd or None,
        model_override=lane.model or None,
        acp_backend_override=lane.harness,
    )


async def _stream_once(provider: Any, prompt: str, *, interactive: bool) -> tuple[bool, str]:
    """Stream one turn to stdout. Returns (produced_output, reply_text)."""
    from junction.cli_chat import _answer_permission, _build_tool_gate
    from junction.providers.base import (
        EVENT_COMPLETE,
        EVENT_PERMISSION_REQUEST,
        EVENT_TEXT_CHUNK,
    )

    gate = None
    produced = False
    reply: list[str] = []
    async for event in provider.stream(prompt):
        if event.kind == EVENT_TEXT_CHUNK:
            produced = produced or bool(event.text)
            reply.append(event.text)
            print(event.text, end="", flush=True)
        elif event.kind == EVENT_PERMISSION_REQUEST:
            produced = True
            if gate is None:
                gate = _build_tool_gate("junction")
            await _answer_permission(provider, event, interactive=interactive, gate=gate)
        elif event.kind == EVENT_COMPLETE:
            break
    print()
    return produced, "".join(reply)


async def _run(router: HarnessRouter, args: argparse.Namespace) -> int:
    from junction.harness_router.limits import HarnessLaneFailure, limit_notice_failure

    kind = args.kind
    cwd = args.cwd or os.getcwd()
    interactive = not args.no_prompt and sys.stdin.isatty() and sys.stdout.isatty()
    try:
        resolution = router.resolve(args.harness, kind=kind)
    except RoutingError as exc:
        print(f"route: {exc}", file=sys.stderr)
        return 2
    lane = resolution.lane
    tried: list[str] = []
    max_hops = router.settings().max_failover
    while True:
        tried.append(lane.id)
        why = resolution.decision.reason if resolution.decision and len(tried) == 1 else ""
        print(
            f"[route] {lane.id} ({lane.label}) · {kind}" + (f" · {why}" if why else ""),
            file=sys.stderr,
        )
        router.record_dispatch(lane.id, kind)
        provider = _make_provider(lane, cwd)
        produced = False
        try:
            await provider.start()
            produced, reply = await _stream_once(provider, args.prompt, interactive=interactive)
            notice = limit_notice_failure(reply) if reply else ""
            if notice:
                raise HarnessLaneFailure(notice, reply)
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception as exc:
            failure = router.record_failure(lane.id, exc=exc)
            can_move = (
                resolution.routed
                and failure in LANE_FAILURES
                and len(tried) <= max_hops
                and (not produced or isinstance(exc, HarnessLaneFailure))
            )
            nxt = router.next_lane(kind, tried) if can_move else None
            if nxt is None:
                print(f"\n[route] {lane.id} failed ({failure}): {exc}", file=sys.stderr)
                return 1
            print(
                f"\n[route] {lane.id} unavailable ({failure}); moving to {nxt.id}", file=sys.stderr
            )
            lane = nxt
            continue
        finally:
            try:
                await provider.shutdown()
            except Exception:
                logger.debug("route run: provider shutdown failed", exc_info=True)
            gc.collect()
        router.record_success(lane.id)
        return 0


# ── check ──


async def _check_lane(lane: Any) -> tuple[str, str]:
    provider = _make_provider(lane, os.getcwd())
    try:
        await asyncio.wait_for(provider.start(), timeout=CHECK_TIMEOUT_SECS)
        models = []
        try:
            getter = getattr(getattr(provider, "_client", None), "available_models", None)
            raw = getter() if callable(getter) else getter
            from junction.acp.client import advertised_model_ids

            models = advertised_model_ids(raw or [])
        except Exception:
            models = []
        detail = f"{len(models)} models" if models else "ready"
        return "ok", detail
    except asyncio.TimeoutError:
        return "timeout", f"no answer in {CHECK_TIMEOUT_SECS:.0f}s"
    except Exception as exc:
        from junction.harness_router.limits import classify_exception

        return classify_exception(exc), " ".join(str(exc).split())[:160]
    finally:
        try:
            await provider.shutdown()
        except Exception:
            logger.debug("route check: shutdown failed", exc_info=True)
        gc.collect()


async def _check(router: HarnessRouter, lane_ids: list[str]) -> int:
    from junction.acp.runtimes import builtin_specs
    from junction.harness_router.lanes import backend_for_harness

    settings = router.settings()
    installed = router.installed(refresh=True)
    lanes = [ln for ln in settings.lanes if ln.enabled and (not lane_ids or ln.id in lane_ids)]
    if not lanes:
        print("no lanes to check (see `junction route status`)")
        return 1
    specs = builtin_specs()
    worst = 0
    for lane in lanes:
        if lane.harness not in installed:
            hint = getattr(specs.get(backend_for_harness(lane.harness)), "login_hint", "")
            print(f"  {lane.id:<14} not installed  {hint}")
            worst = 1
            continue
        print(f"  {lane.id:<14} starting…", end="", flush=True)
        verdict, detail = await _check_lane(lane)
        print(f"\r  {lane.id:<14} {verdict:<12} {detail}")
        if verdict != "ok":
            worst = 1
            if verdict == "auth":
                hint = getattr(specs.get(backend_for_harness(lane.harness)), "login_hint", "")
                print(f"  {'':<14} log in: {hint}")
    return worst


# ── init ──


def _init(router: HarnessRouter, *, force: bool, all_harnesses: bool) -> None:
    from junction.atomic_write import atomic_write
    from junction.harness_router.profiles import HARNESS_PROFILES

    path = routing_path()
    if path.exists() and not force:
        print(f"{path} exists; pass --force to overwrite")
        raise SystemExit(1)
    installed = list(router.installed(refresh=True))
    names = installed
    if all_harnesses:
        names = installed + [h for h in HARNESS_PROFILES if h not in installed]
    doc = template_document(names)
    if all_harnesses:
        for lane in doc["lanes"]:
            lane["enabled"] = lane["harness"] in installed
    atomic_write(path, json.dumps(doc, indent=2) + "\n")
    print(f"wrote {path} with {len(doc['lanes'])} lane(s): " + ", ".join(names or ["(none)"]))
    print("edit weight / window_limit / billing per lane to match your plans.")
