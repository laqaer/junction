"""ACP runtime registry — spawn argv for each dockable coding agent.

Junction's harness plane treats ACP as a family of stdio JSON-RPC agents
(Cursor, Claude, Codex, DeepSeek Harness, Pi, Kimi, Goose, Grok, Droid, …).
``kiro-cli`` is one selectable backend, last in auto preference, and optional.

This module is stdlib-only besides ``junction.acp.types`` so tests can
exercise it without spawning a gateway.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from junction.acp.types import (
    ACP_BACKEND_AUTO,
    ACP_BACKEND_CLAUDE,
    ACP_BACKEND_CODEX,
    ACP_BACKEND_CURSOR,
    ACP_BACKEND_DROID,
    ACP_BACKEND_DSH,
    ACP_BACKEND_GOOSE,
    ACP_BACKEND_GROK,
    ACP_BACKEND_KIMI,
    ACP_BACKEND_KIRO,
    ACP_BACKEND_PI,
    ACP_BACKENDS_SPEC_FAMILY,
)

WhichFn = Callable[[str], str | None]

# Preference when ``agent.acp_backend`` is ``auto``. kiro-cli is last and
# optional: Junction docks whichever spec-family runtime is already installed.
AUTO_PREFERENCE: tuple[str, ...] = (
    ACP_BACKEND_CURSOR,
    ACP_BACKEND_CLAUDE,
    ACP_BACKEND_CODEX,
    ACP_BACKEND_KIMI,
    ACP_BACKEND_DSH,
    ACP_BACKEND_GOOSE,
    ACP_BACKEND_GROK,
    ACP_BACKEND_PI,
    ACP_BACKEND_DROID,
    ACP_BACKEND_KIRO,
)

_DSH_LAUNCHER_REL = Path(".buzz") / "tools" / "dsh-buzz" / "launch-acp.sh"


class RuntimeNotFoundError(LookupError):
    """No configured ACP runtime is installed / resolvable."""


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    """How to spawn one ACP agent over stdio."""

    id: str
    argv: tuple[str, ...]
    protocol: str  # "spec" (ACP v1 integer) or "kiro" (date-stamped)
    login_hint: str
    needs: tuple[str, ...] = ()

    @property
    def is_spec(self) -> bool:
        return self.protocol == "spec"


def dsh_launcher_path(*, home: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    """DeepSeek Harness ACP launcher used by Buzz (``dsh-acp``)."""
    environ = env if env is not None else os.environ
    override = environ.get("DSH_ACP_LAUNCHER")
    if override:
        return Path(override)
    root = home if home is not None else Path.home()
    return root / _DSH_LAUNCHER_REL


def builtin_specs(
    *,
    which: WhichFn | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, RuntimeSpec]:
    """Return spawn specs. *which* is ``shutil.which`` (injectable in tests)."""
    find = which or shutil.which
    environ = env if env is not None else os.environ
    home_path = home if home is not None else Path.home()
    dsh = dsh_launcher_path(home=home_path, env=environ)

    claude_argv: tuple[str, ...]
    claude_bin = find("claude-agent-acp")
    if claude_bin:
        claude_argv = (claude_bin,)
    else:
        claude_argv = (
            "npx",
            "-y",
            "@agentclientprotocol/claude-agent-acp@^0.60.0",
        )

    codex_argv = (
        "npx",
        "-y",
        "@agentclientprotocol/codex-acp@^1.1.5",
    )
    pi_argv = ("npx", "-y", "pi-acp@^0.0.31")

    return {
        ACP_BACKEND_CURSOR: RuntimeSpec(
            id=ACP_BACKEND_CURSOR,
            argv=("cursor-agent", "acp"),
            protocol="spec",
            login_hint="Install Cursor CLI and run `cursor-agent login`.",
            needs=("cursor-agent",),
        ),
        ACP_BACKEND_CLAUDE: RuntimeSpec(
            id=ACP_BACKEND_CLAUDE,
            argv=claude_argv,
            protocol="spec",
            login_hint="Install Claude Code (`claude`) and/or `claude-agent-acp`.",
            needs=(),  # npx fallback; availability checks claude OR adapter
        ),
        ACP_BACKEND_CODEX: RuntimeSpec(
            id=ACP_BACKEND_CODEX,
            argv=codex_argv,
            protocol="spec",
            login_hint="Install Codex CLI (`codex`) and log in.",
            needs=("codex",),
        ),
        ACP_BACKEND_KIMI: RuntimeSpec(
            id=ACP_BACKEND_KIMI,
            argv=("kimi", "acp"),
            protocol="spec",
            login_hint="Install Kimi Code and run `kimi acp --login`.",
            needs=("kimi",),
        ),
        ACP_BACKEND_DSH: RuntimeSpec(
            id=ACP_BACKEND_DSH,
            argv=(str(dsh),),
            protocol="spec",
            login_hint=("Clone deepseek-harness and keep ~/.buzz/tools/dsh-buzz/launch-acp.sh."),
            needs=(),
        ),
        ACP_BACKEND_GOOSE: RuntimeSpec(
            id=ACP_BACKEND_GOOSE,
            argv=("goose", "acp"),
            protocol="spec",
            login_hint="Install goose and run `goose acp`.",
            needs=("goose",),
        ),
        ACP_BACKEND_GROK: RuntimeSpec(
            id=ACP_BACKEND_GROK,
            argv=("grok", "agent", "stdio"),
            protocol="spec",
            login_hint="Install Grok CLI (`grok`).",
            needs=("grok",),
        ),
        ACP_BACKEND_PI: RuntimeSpec(
            id=ACP_BACKEND_PI,
            argv=pi_argv,
            protocol="spec",
            login_hint="Install pi (`npm i -g @mariozechner/pi-coding-agent`) or set PI_ACP.",
            needs=(),
        ),
        ACP_BACKEND_DROID: RuntimeSpec(
            id=ACP_BACKEND_DROID,
            argv=("droid", "exec", "--output-format", "acp"),
            protocol="spec",
            login_hint="Install Factory Droid CLI (`droid`).",
            needs=("droid",),
        ),
        ACP_BACKEND_KIRO: RuntimeSpec(
            id=ACP_BACKEND_KIRO,
            argv=("kiro-cli", "acp"),
            protocol="kiro",
            login_hint="Optional. Install kiro-cli and run `kiro-cli login`.",
            needs=("kiro-cli",),
        ),
    }


def runtime_available(
    spec: RuntimeSpec,
    *,
    which: WhichFn | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """True if this host can spawn *spec* without a missing-binary surprise."""
    find = which or shutil.which
    environ = env if env is not None else os.environ
    home_path = home if home is not None else Path.home()

    if spec.id == ACP_BACKEND_CLAUDE:
        return bool(find("claude-agent-acp") or find("claude"))
    if spec.id == ACP_BACKEND_DSH:
        launcher = dsh_launcher_path(home=home_path, env=environ)
        return launcher.is_file() and os.access(launcher, os.X_OK)
    if spec.id == ACP_BACKEND_PI:
        return bool(environ.get("PI_ACP") or find("pi") or find("pi-acp"))
    if spec.id == ACP_BACKEND_CODEX:
        return bool(find("codex") and (find("npx") or find("codex-acp")))
    return all(find(name) for name in spec.needs) if spec.needs else bool(find(spec.argv[0]))


def select_runtime(
    requested: str = ACP_BACKEND_AUTO,
    *,
    which: WhichFn | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    allow_kiro: bool = True,
) -> RuntimeSpec:
    """Pick a concrete runtime.

    ``auto`` walks :data:`AUTO_PREFERENCE` and returns the first available
    spec. An explicit id must be available or this raises
    :class:`RuntimeNotFoundError`. kiro-cli is skipped in auto unless no
    spec-family runtime is present *and* ``allow_kiro`` is true.
    """
    specs = builtin_specs(which=which, home=home, env=env)
    if requested and requested != ACP_BACKEND_AUTO:
        spec = specs.get(requested)
        if spec is None:
            raise RuntimeNotFoundError(
                f"Unknown ACP runtime {requested!r}. "
                f"Known: {', '.join(sorted(k for k in specs if k))}"
            )
        if not runtime_available(spec, which=which, home=home, env=env):
            raise RuntimeNotFoundError(
                f"ACP runtime {requested!r} is not installed. {spec.login_hint}"
            )
        return spec

    spec_hits: list[RuntimeSpec] = []
    kiro_hit: RuntimeSpec | None = None
    for runtime_id in AUTO_PREFERENCE:
        spec = specs[runtime_id]
        if not runtime_available(spec, which=which, home=home, env=env):
            continue
        if spec.id == ACP_BACKEND_KIRO:
            kiro_hit = spec
            continue
        spec_hits.append(spec)
    if spec_hits:
        return spec_hits[0]
    if allow_kiro and kiro_hit is not None:
        return kiro_hit
    raise RuntimeNotFoundError(
        "No ACP runtime found. Install cursor-agent, claude, codex, kimi, "
        "goose, grok, droid, pi, or the DeepSeek Harness launcher "
        "(~/.buzz/tools/dsh-buzz/launch-acp.sh)."
    )


def resolve_backend(
    configured: str,
    *,
    which: WhichFn | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """The concrete backend a session for *configured* ``agent.acp_backend`` runs on.

    ``auto`` resolves the way the provider does at start (first installed
    runtime). When nothing is installed the answer is ``ACP_BACKEND_KIRO``: that
    is what an unresolvable ``auto`` has always fallen back to, and callers that
    branch on the backend (the multiplexed-runtime paths, the Kiro readiness
    gate) keep their existing behavior on such a host.
    """
    if configured == ACP_BACKEND_AUTO:
        try:
            return select_runtime(ACP_BACKEND_AUTO, which=which, home=home, env=env).id
        except RuntimeNotFoundError:
            return ACP_BACKEND_KIRO
    return configured


def resolve_spawn_argv(
    runtime_id: str,
    *,
    which: WhichFn | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Return argv for a concrete (non-auto) runtime id."""
    spec = select_runtime(runtime_id, which=which, home=home, env=env, allow_kiro=True)
    return list(spec.argv)


def is_spec_backend(runtime_id: str) -> bool:
    """True for ACP v1 / stdio agents that are not kiro-cli or KAS."""
    return runtime_id in ACP_BACKENDS_SPEC_FAMILY


def session_load_meta(runtime_id: str, *, session_file: str = "") -> dict | None:
    """``_meta`` for ``session/load``. Spec-family agents get none (H5)."""
    if runtime_id == ACP_BACKEND_CLAUDE:
        return {"claudeCode": {"options": {}}}
    if runtime_id == ACP_BACKEND_KIRO:
        return {"_kiro.dev/session_file": session_file}
    return None
