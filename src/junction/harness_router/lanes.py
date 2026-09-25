"""Lanes: one subscription (or API account) reached through one harness.

A lane is what the router actually picks. It binds a harness (an ACP backend
id) to how that access is paid for, how big its usage window is, and which
kinds of work it should take. Two lanes may share a harness: an OpenCode lane
pinned to a cheap OpenRouter model for bulk work and another pinned to a strong
one for reviews.

Lanes come from ``<data home>/routing.json``. With no file, every installed
harness becomes one lane with its built-in profile, so routing works on a
fresh install. The file carries no credentials: every harness keeps its own
login.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from junction.acp.types import (
    ACP_BACKEND_AUTO,
    ACP_BACKEND_KIRO,
    ACP_BACKEND_KIRO_NAME,
    ACP_BACKENDS_SELECTABLE,
)
from junction.harness_router.kinds import TASK_KINDS
from junction.harness_router.profiles import BILLING_TYPES, HarnessProfile, profile_for

logger = logging.getLogger(__name__)

ROUTING_FILENAME = "routing.json"
ROUTING_SCHEMA_VERSION = 1

# Lane ids appear in CLI arguments, MCP tool arguments and ledger keys.
LANE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")

# Rolling usage window when a lane states none. Claude and Codex plans both
# meter in five-hour windows.
DEFAULT_WINDOW_HOURS = 5.0
MAX_WINDOW_HOURS = 24.0 * 7

WhichFn = Callable[[str], "str | None"]


class RoutingConfigError(ValueError):
    """``routing.json`` is present but unusable."""


def backend_for_harness(harness: str) -> str:
    """ACP backend id for an operator-facing harness name (``kiro`` → ``""``)."""
    if harness == ACP_BACKEND_KIRO_NAME:
        return ACP_BACKEND_KIRO
    return harness


def harness_name(backend: str) -> str:
    """Operator-facing name for an ACP backend id (``""`` → ``kiro``)."""
    if backend == ACP_BACKEND_KIRO:
        return ACP_BACKEND_KIRO_NAME
    return backend


def is_routable_harness(harness: str) -> bool:
    """True for a concrete, selectable harness. ``auto`` is not a lane."""
    if not harness or harness == ACP_BACKEND_AUTO:
        return False
    return backend_for_harness(harness) in ACP_BACKENDS_SELECTABLE


@dataclass(frozen=True)
class Lane:
    """One routable subscription or account."""

    id: str
    harness: str
    label: str
    billing: str
    affinity: Mapping[str, float]
    enabled: bool = True
    # Relative share of load when window_limit is unknown. 2.0 means "this
    # plan is about twice as big as a weight-1 plan".
    weight: float = 1.0
    # Harness-spelled model id to pin for this lane; "" inherits the harness
    # default.
    model: str = ""
    window_hours: float = DEFAULT_WINDOW_HOURS
    # Dispatches the plan allows per window; 0 means unknown.
    window_limit: int = 0
    # Hard cap on dispatches per rolling 24h (metered budget guard); 0 = none.
    daily_limit: int = 0
    note: str = ""
    source: str = "auto"  # "auto" (detected) or "config" (routing.json)

    @property
    def backend(self) -> str:
        return backend_for_harness(self.harness)

    def affinity_for(self, kind: str) -> float:
        return float(self.affinity.get(kind, profile_for(self.harness).affinity_for(kind)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "harness": self.harness,
            "label": self.label,
            "billing": self.billing,
            "enabled": self.enabled,
            "weight": self.weight,
            "model": self.model,
            "window_hours": self.window_hours,
            "window_limit": self.window_limit,
            "daily_limit": self.daily_limit,
            "affinity": {kind: round(self.affinity_for(kind), 3) for kind in TASK_KINDS},
            "note": self.note,
            "source": self.source,
        }


@dataclass(frozen=True)
class RoutingSettings:
    """Parsed ``routing.json`` (or the auto-detected equivalent)."""

    lanes: tuple[Lane, ...]
    enabled: bool = True
    # Failover hops a routed run may take after a lane-level failure.
    max_failover: int = 2
    source: str = "auto"
    path: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def lane(self, lane_id: str) -> Lane | None:
        for lane in self.lanes:
            if lane.id == lane_id:
                return lane
        return None

    def lanes_for_harness(self, harness: str) -> tuple[Lane, ...]:
        return tuple(lane for lane in self.lanes if lane.harness == harness)


def routing_path(home: Path | None = None) -> Path:
    if home is None:
        from junction.config.paths import data_home

        home = data_home()
    return home / ROUTING_FILENAME


def lane_from_profile(profile: HarnessProfile, *, source: str = "auto") -> Lane:
    return Lane(
        id=profile.harness,
        harness=profile.harness,
        label=profile.label,
        billing=profile.billing,
        affinity=dict(profile.affinity),
        note=profile.note,
        source=source,
    )


def installed_harnesses(
    *,
    which: WhichFn | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Operator-facing names of every harness this host can spawn, in auto order."""
    from junction.acp.runtimes import AUTO_PREFERENCE, builtin_specs, runtime_available

    specs = builtin_specs(which=which, home=home, env=env)
    found: list[str] = []
    for backend in AUTO_PREFERENCE:
        spec = specs.get(backend)
        if spec is not None and runtime_available(spec, which=which, home=home, env=env):
            found.append(harness_name(backend))
    return found


def auto_lanes(harnesses: Iterable[str]) -> tuple[Lane, ...]:
    return tuple(lane_from_profile(profile_for(name)) for name in harnesses)


def _as_float(raw: object, default: float, *, lo: float, hi: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    return max(lo, min(hi, float(raw)))


def _as_int(raw: object, default: int = 0) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return max(0, raw)


def _parse_affinity(raw: object, lane_id: str, warnings: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        warnings.append(f"lane {lane_id}: affinity must be an object; ignored")
        return out
    for kind, value in raw.items():
        if kind not in TASK_KINDS:
            warnings.append(f"lane {lane_id}: unknown kind {kind!r} in affinity; ignored")
            continue
        out[kind] = _as_float(value, 0.0, lo=0.0, hi=1.0)
    return out


def parse_lane(raw: object, warnings: list[str]) -> Lane | None:
    """One lane from its JSON object; ``None`` (with a warning) when unusable."""
    if not isinstance(raw, dict):
        warnings.append("lane entries must be objects; one skipped")
        return None
    harness = str(raw.get("harness") or "").strip().lower()
    lane_id = str(raw.get("id") or harness).strip().lower()
    if not LANE_ID_PATTERN.match(lane_id):
        warnings.append(f"lane id {lane_id!r} is not a valid id; skipped")
        return None
    if not is_routable_harness(harness):
        warnings.append(f"lane {lane_id}: unknown harness {harness!r}; skipped")
        return None
    profile = profile_for(harness)
    billing = str(raw.get("billing") or profile.billing).strip().lower()
    if billing not in BILLING_TYPES:
        warnings.append(f"lane {lane_id}: unknown billing {billing!r}; using {profile.billing}")
        billing = profile.billing
    affinity = dict(profile.affinity)
    affinity.update(_parse_affinity(raw.get("affinity"), lane_id, warnings))
    model = str(raw.get("model") or "").strip()
    return Lane(
        id=lane_id,
        harness=harness,
        label=str(raw.get("label") or profile.label),
        billing=billing,
        affinity=affinity,
        enabled=bool(raw.get("enabled", True)),
        weight=_as_float(raw.get("weight"), 1.0, lo=0.05, hi=100.0),
        model=model,
        window_hours=_as_float(
            raw.get("window_hours"), DEFAULT_WINDOW_HOURS, lo=0.25, hi=MAX_WINDOW_HOURS
        ),
        window_limit=_as_int(raw.get("window_limit")),
        daily_limit=_as_int(raw.get("daily_limit")),
        note=str(raw.get("note") or ""),
        source="config",
    )


def parse_settings(data: object, *, path: str = "") -> RoutingSettings:
    """Build settings from decoded ``routing.json``. Raises on a wrong shape."""
    if not isinstance(data, dict):
        raise RoutingConfigError("routing.json must hold a JSON object")
    raw_lanes = data.get("lanes")
    if not isinstance(raw_lanes, list):
        raise RoutingConfigError("routing.json needs a 'lanes' list")
    warnings: list[str] = []
    lanes: list[Lane] = []
    seen: set[str] = set()
    for raw in raw_lanes:
        lane = parse_lane(raw, warnings)
        if lane is None:
            continue
        if lane.id in seen:
            warnings.append(f"duplicate lane id {lane.id!r}; later entry skipped")
            continue
        seen.add(lane.id)
        lanes.append(lane)
    return RoutingSettings(
        lanes=tuple(lanes),
        enabled=bool(data.get("enabled", True)),
        max_failover=_as_int(data.get("max_failover"), 2),
        source="config",
        path=path,
        warnings=tuple(warnings),
    )


def load_settings(
    *,
    home: Path | None = None,
    which: WhichFn | None = None,
    env: Mapping[str, str] | None = None,
) -> RoutingSettings:
    """Settings from ``routing.json``, or detected lanes when the file is absent.

    A present-but-broken file degrades to detected lanes with a warning rather
    than raising: routing must never be the reason a gateway cannot start.
    """
    path = routing_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
    except OSError as exc:
        logger.warning("routing.json unreadable (%s); using detected harnesses", exc)
        text = None
    if text is not None:
        try:
            return parse_settings(json.loads(text), path=str(path))
        except (json.JSONDecodeError, RoutingConfigError) as exc:
            detected = auto_lanes(installed_harnesses(which=which, env=env))
            return RoutingSettings(
                lanes=detected,
                source="auto",
                path=str(path),
                warnings=(f"routing.json ignored: {exc}",),
            )
    return RoutingSettings(
        lanes=auto_lanes(installed_harnesses(which=which, env=env)),
        source="auto",
        path=str(path),
    )


def template_document(harnesses: Iterable[str]) -> dict[str, Any]:
    """A ``routing.json`` body with one lane per harness, ready to edit."""
    lanes = []
    for name in harnesses:
        profile = profile_for(name)
        lanes.append(
            {
                "id": profile.harness,
                "harness": profile.harness,
                "label": profile.label,
                "billing": profile.billing,
                "enabled": True,
                "weight": 1.0,
                "model": "",
                "window_hours": DEFAULT_WINDOW_HOURS,
                "window_limit": 0,
                "daily_limit": 0,
                "affinity": dict(profile.affinity),
                "note": profile.note,
            }
        )
    return {
        "version": ROUTING_SCHEMA_VERSION,
        "enabled": True,
        "max_failover": 2,
        "lanes": lanes,
    }
