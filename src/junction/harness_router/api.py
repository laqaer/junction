"""Dashboard / MCP JSON for the harness router.

Every handler does its file I/O (``routing.json``, the ledger, a ``PATH``
walk) off the event loop. Non-2xx bodies carry a machine-readable ``code``.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from junction.harness_router.lanes import LANE_ID_PATTERN
from junction.harness_router.service import get_router

logger = logging.getLogger(__name__)


def _ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


async def api_status(request: web.Request) -> web.Response:
    """GET /api/routing/status — lanes, usage windows, cooldowns, per-kind picks."""
    payload = await asyncio.to_thread(get_router().status)
    return web.json_response(payload)


async def api_decide(request: web.Request) -> web.Response:
    """GET /api/routing/decide?kind=&role=&prefer=&exclude= — rank lanes for a kind."""
    query = request.rel_url.query
    router = get_router()
    decision = await asyncio.to_thread(
        router.decide,
        query.get("kind") or None,
        role=query.get("role") or None,
        prefer=_ids(query.get("prefer")),
        exclude=_ids(query.get("exclude")),
    )
    # "no lane" is an answer, not a request error: 200 with its own code.
    return web.json_response(decision.to_dict())


async def api_clear_cooldown(request: web.Request) -> web.Response:
    """POST /api/routing/cooldown/clear {lane?} — lift a lane's rest early."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    lane = str((body or {}).get("lane") or "").strip().lower() or None
    if lane is not None and not LANE_ID_PATTERN.match(lane):
        return web.json_response({"error": "invalid lane id", "code": "invalid_lane"}, status=400)
    cleared = await asyncio.to_thread(get_router().ledger.clear_cooldown, lane)
    logger.info("routing cooldown cleared: %s", ",".join(cleared) or "-")
    return web.json_response({"code": "ok", "cleared": cleared})


def register(app: web.Application) -> None:
    app.router.add_get("/api/routing/status", api_status)
    app.router.add_get("/api/routing/decide", api_decide)
    app.router.add_post("/api/routing/cooldown/clear", api_clear_cooldown)
