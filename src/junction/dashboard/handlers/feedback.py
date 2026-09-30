"""The session-pulse survey's dashboard routes, kept inert.

The survey's only backend is a third-party feedback service whose form was
registered by the upstream project. This project does not operate it and has
no form of its own there, so a default install must not contact it: the
default build reaches no host the project does not run.

The routes stay registered so the dashboard's survey card
(``SessionPulseSurveyCard.tsx``) gets a definite answer instead of a 404 it
would have to interpret. Eligibility always answers ``{"eligible": false}``,
so the card never renders, and a submit is refused with a coded 404. Neither
route makes an outbound request, reads the install id, or needs the telemetry
consent ladder, because nothing leaves the host.

Both routes remain dashboard-user surfaces: an app token is refused with a
SEL-audited 403, as every survey route was, so an installed app cannot probe
them.
"""

from __future__ import annotations

import logging

from aiohttp import web

from junction import sel as _sel_mod

logger = logging.getLogger(__name__)


def _session_key(request: web.Request) -> str:
    """The caller's session key (``X-Session-Key`` header), for the SEL trail."""
    return request.headers.get("X-Session-Key") or ""


def _audit_feedback_denial(request: web.Request, tool: str) -> None:
    """SEL-audit a denied feedback permission decision.

    A security allow/deny must leave a decision record. Fail-safe: an audit
    failure must never turn a 403 into a 500.
    """
    try:
        _sel_mod.sel().log_tool_invocation(
            session_key=_session_key(request),
            source="api",
            tool_name=tool,
            outcome="denied",
        )
    except Exception:  # pragma: no cover - audit must never break a request
        logger.debug("SEL audit failed for %s", tool, exc_info=True)


def _require_dashboard_user(request: web.Request, tool: str = "feedback") -> web.Response | None:
    """403 unless this is a real dashboard user's request, else ``None``.

    Deny-by-default on the app claim, matching the ``request["app"] == ""``
    convention used by ``deny_non_dashboard_caller`` / ``kiro_prerequisite`` /
    ``chat_handlers``: the auth middleware sets ``request["app"]`` on every
    authenticated path (``""`` for a dashboard user, the app name for an app
    token), so an ABSENT key means the middleware did not run and must be
    refused rather than fall through.
    """
    if request.get("app") != "":
        _audit_feedback_denial(request, tool)
        return web.json_response({"code": "forbidden"}, status=403)
    return None


async def api_feedback_submit(request: web.Request) -> web.Response:
    """POST /api/feedback/submit — refused: no survey service is configured.

    The body is never read, so a submission cannot reach a log or a host.
    The frontend already treats a failed submission as non-fatal.
    """
    denied = _require_dashboard_user(request, "feedback_submit")
    if denied is not None:
        return denied
    return web.json_response({"code": "feedback_unavailable"}, status=404)


async def api_feedback_eligible(request: web.Request) -> web.Response:
    """GET /api/feedback/eligible — always ``{"eligible": false}``."""
    denied = _require_dashboard_user(request, "feedback_eligible")
    if denied is not None:
        return denied
    return web.json_response({"eligible": False})


def setup_feedback_routes(app: web.Application) -> None:
    """Register the session-pulse survey's inert routes."""
    app.router.add_post("/api/feedback/submit", api_feedback_submit)
    app.router.add_get("/api/feedback/eligible", api_feedback_eligible)
