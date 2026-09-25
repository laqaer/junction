# Harness router — send each task to the subscription that should do it

**This is the change-control contract for `src/junction/harness_router/`.**
Read it before changing that package, the `harness` / `kind` fields on
`spawn_run`, or the per-session `acp_backend_override` factory seam. Update it
in the same commit when behavior documented here changes.

Junction docks several coding-agent harnesses at once — Claude Code, Codex
(ChatGPT), Cursor, Grok Build, OpenCode (OpenRouter and every other provider it
logs into), and the rest of the registry in `acp/runtimes.py`. Each is reached
through a plan or account the operator already pays for. The harness router
decides which one takes each unit of work. It **chooses a harness**; it never
forwards provider traffic, stores a key, or reads a harness's credentials. The
chosen harness runs with its own login, exactly as `agent.acp_backend` would.

Related: [harness-parity](harness-parity.md) (what an added harness may and may
not change), [model-router](model-router.md) (the model plane, which this does
not touch), [subagent](subagent.md) (where routed work runs), [mcp](../../architecture/mcp.md).

## Vocabulary

| Term | Meaning |
|---|---|
| **Harness** | An ACP backend id from `acp/types.py`, spelled for operators (`kiro` for the empty backend). |
| **Lane** | One subscription or account reached through one harness: `id`, `harness`, `billing`, `weight`, `window_hours`, `window_limit`, `daily_limit`, optional `model`, per-kind `affinity`. Two lanes may share a harness (an OpenCode lane on a cheap OpenRouter model for bulk work, another on a strong one for review). |
| **Kind** | What the work is: `plan`, `implement`, `debug`, `review`, `test`, `research`, `docs`, `quick`, `bulk` (`kinds.TASK_KINDS`). The orchestrating LLM names it as an enum; the router never guesses it from free text. |
| **Billing** | `subscription` (flat plan with a usage window), `free`, or `metered` (pay per token). |
| **Ledger** | `<data home>/routing/ledger.json`: per-lane dispatch timestamps, outcome counters, cooldown deadline, and a truncated, credential-redacted last error. Never prompts or keys. |

## Objective

Maximum useful work from what the operator already pays for:

1. **Spend flat-rate quota first.** Unused subscription quota is lost at reset,
   so metered lanes compete at `METERED_FACTOR` (0.6) of their score.
2. **Spread load by headroom.** A lane's dispatches in its rolling window are
   compared with its capacity (`window_limit` when stated, else `weight ×
   NOMINAL_WINDOW_DISPATCHES`). A lane near its cap yields to one with room.
3. **Match the task.** Affinity for the kind decides between lanes with similar
   headroom.
4. **Route around trouble.** A lane resting after a lane-level failure is
   excluded until its cooldown ends; a lane past `daily_limit` is excluded; a
   lane at `window_limit` falls behind every lane with room (`EXHAUSTED_FACTOR`)
   but is not excluded, since a stated limit may be conservative.

`score = billing_factor × (0.6 × affinity + 0.4 × headroom)` (+ a small bonus
for a caller's `prefer`). Scoring (`router.decide`) is pure over settings,
ledger snapshot and the installed set, so it is deterministic and testable
without spawning anything. Ties break by lane order in `routing.json`.

Default affinities live in `profiles.HARNESS_PROFILES`: Claude Code leads plan,
review and docs; Codex leads implement, debug and test; Grok leads research;
Cursor leads quick edits; OpenCode is metered and favours bulk. They are a
starting point for a zero-config install, not a benchmark — `routing.json`
overrides any of them per lane.

## Lanes and `routing.json`

`<data home>/routing.json` holds `enabled`, `max_failover` (default 2) and a
`lanes` list. It carries no credentials. With no file, every installed harness
becomes one lane with its built-in profile (`source: "auto"`), and that set
tracks installs without a restart. A present-but-unparseable file degrades to
the detected lanes with a warning: routing is never the reason a gateway cannot
start. Invalid lanes are skipped with a warning, never guessed at. `junction
route init` writes a template from the installed harnesses.

```json
{
  "enabled": true,
  "max_failover": 2,
  "lanes": [
    {"id": "claude-max", "harness": "claude", "billing": "subscription", "weight": 3},
    {"id": "chatgpt-pro", "harness": "codex", "billing": "subscription", "weight": 3},
    {"id": "cursor-pro", "harness": "cursor", "billing": "subscription"},
    {"id": "supergrok", "harness": "grok", "billing": "subscription"},
    {"id": "openrouter", "harness": "opencode", "billing": "metered",
     "model": "openrouter/deepseek/deepseek-v4", "daily_limit": 200}
  ]
}
```

A lane's `model` is spelled for **its own harness** and is sent only to that
harness (H12). A routed subagent never inherits `agent.role_models.subagent`,
which is spelled for the configured default harness.

## Failure classes and cooldowns (`limits.py`)

| Class | Examples | Rest when no reset is stated |
|---|---|---|
| `usage_limit` | "usage limit reached", "5-hour limit", "Insufficient credits" | 60 min |
| `rate_limit` | 429, "rate limit", "overloaded" | 2 min |
| `auth` | `AcpAuthRequired`, "Authentication required", "run /login" | 30 min |
| `unavailable` | harness binary missing, "is not installed" | 10 min |
| `other` | an ordinary task failure | none — it would fail on any lane |

A stated reset ("try again in 2 hours 5 minutes", "resets 3pm", Claude's
`|<epoch>` suffix) wins over the default, clamped to `[30 s, 8 days]`. Clock
times are read in the host's local zone. A success clears a lane's cooldown.

Some harnesses end a turn normally with the limit notice as the whole reply.
`limit_notice_failure` treats a reply as a lane failure only when it is short
(`LIMIT_NOTICE_MAX_CHARS`), classifies as `usage_limit` or `auth` (never
`rate_limit`, which an ordinary answer about rate limiting mentions), and the
turn ran no tools.

## Dispatch

### Subagents (`spawn_run`)

`spawn_run` takes `harness` (batch-wide) or `harnesses[]` (one per task), and
`kind` / `kinds[]`. `harness` is `route` (the router picks), a lane id, or a
harness name. The gateway's `POST /api/spawn` resolves it **before** the
submission is counted, so a refusal is an ordinary 400 with a `code`. The
response carries `route` (lane, harness, model, kind, routed, reason).

`SubagentInfo` gains `harness`, `lane`, `route_kind`, `routed`. In `_run_inner`
a set `harness` becomes the factory kwarg `acp_backend_override` and forces the
dedicated-process path (the parent's shared runtime is a different harness).
`state.json` persists `harness` and `lane`, and `continue_conversation`
continues on them: a conversation lives in the harness that ran it.

`SubagentManager._run_accounted` wraps `_run_inner` for a run with a lane:

- records a dispatch, then the outcome, in the ledger;
- on a lane-level failure of a **routed** run with no tool activity, not a
  continuation, not user-stopped, and within `max_failover` hops, tears the
  session down and re-runs on `router.next_lane(kind, tried)`, firing
  `subagent_retrying` with `{lane, harness, failed_lane}` and a
  `subagent.harness_failover` SEL record;
- an explicit pin (`routed=False`) never moves; its failure still rests the lane.

A run with no lane passes straight through: the unrouted path is unchanged.

### The provider-factory seam

`JunctionConfig.create_provider_factory()`'s closure takes an optional
`acp_backend_override`. Absent, the configured `agent.acp_backend` is used
exactly as before. Present, `resolve_acp_backend_override` maps `kiro` to `""`
and **raises** on an unknown value — an override is an explicit per-call choice,
and running a different harness than the one named is what H3/H8 forbid. The
warm pool is bypassed with decision `bypass_harness`: pooled processes run the
configured backend and a claim only re-keys and re-models them.

### Terminal (`junction route run`)

Runs one prompt on the resolved lane with the same failover rules, streaming to
stdout. Tool permission requests are asked at the terminal when both ends are a
TTY, else denied (`--no-prompt` forces deny). It warms the sandbox probe before
the event loop starts, because the probe never runs on a live loop.

## Surfaces

| Surface | What |
|---|---|
| `junction route` / `route status [--json]` | Lanes, windows, 24h use, cooldowns and last error, current pick per kind |
| `junction route pick KIND` | Rank every lane for a kind (twin of `route_task`) |
| `junction route run [-k KIND] [--harness T] PROMPT` | One prompt on the routed lane, with failover |
| `junction route check [LANE…]` | Start each harness once (initialize + session/new): installed? logged in? |
| `junction route init [--force] [--all]` | Write `routing.json` from the installed harnesses |
| `junction route clear [LANE]` | Lift a cooldown early |
| MCP `route_task(kind, prefer?)` | Read-only ranking for the orchestrating agent |
| MCP `spawn_run(harness, harnesses[], kind, kinds[])` | Routed or pinned dispatch |
| `GET /api/routing/status` | Same payload as `route status --json` |
| `GET /api/routing/decide?kind=&role=&prefer=&exclude=` | One decision; "no lane" is a 200 with `code: no_lane` |
| `POST /api/routing/cooldown/clear {lane?}` | Lift a cooldown |

`/api/routing` is a mixed internal path (MCP secret or dashboard cookie).
Handlers do their file I/O off the event loop.

## Invariants

1. **Choose, never forward.** No provider traffic, keys, or credential reads.
   OpenRouter reaches Junction as the OpenCode harness logged into it.
2. **Unrouted is unchanged.** No lane ⇒ `_run_inner` directly; no override ⇒
   the configured backend; the Kiro path gains no conditional (H13).
3. **Explicit beats routed.** A named lane or harness never silently moves.
4. **Only lane failures move work, only before activity.** An ordinary task
   failure never rests a lane; a run that executed a tool never re-runs.
5. **Accounting never fails a run.** Ledger and settings errors are logged and
   swallowed; a corrupt ledger starts fresh.
6. **No secrets at rest.** The ledger stores redacted, truncated error text.

Pinned by `test/test_harness_router.py`.
