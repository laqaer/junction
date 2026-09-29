# Warding

**The lamp stays on. The rules stay shut.**

Warding runs the coding agent you already pay for, all night, on your own
box, and asks you in chat before anything risky — under a policy it cannot
read or rewrite.

Built on Amazon's open-source Kiro agent workspace, published under
Apache-2.0 in 2026. Most of the code is theirs; the attribution
notice is in [NOTICE](NOTICE). Not affiliated with Amazon. Lineage:
[README § Lineage](README.md#lineage).

## Positioning

For developers who already pay for a coding agent, and for the platform or
security lead who has to say yes to it running unattended, Warding is the
self-hosted late desk that keeps that agent working on your own machine after
you close the laptop, reports into the chat you already use, and asks first
before anything risky — under a written policy the agent can neither read nor
rewrite. Unlike vendor routines and cloud sessions, it runs on your hardware
with no run cap added by us (your model plan's limits still apply) and no
account with us in the door; unlike the personal-agent projects, it denies the
agent the secret paths and policy files on its deny list, at its own gate; and
unlike the at-the-keyboard GUIs, it is built for the hours when nobody is
watching.

The category we claim is **the governed late desk for coding agents**. Our
words: the late desk, the lamp stays on, ask first, the morning report
(in development), the policy it can't open, refused, not asked. The phrases we
never headline with are listed in [`JUNCTION.md`](JUNCTION.md#the-no-say-list).

The one emotion we sell is composure at 07:00: the lid opens and the report is
there — what ran, what asked, what was refused, nothing leaked.

## Who it is for

- **Free tier:** the developer with a Claude Code, Codex, Cursor, Goose, Kimi
  or kiro-cli subscription, a Mac mini, home server or VPS, and a phone that is
  always on Telegram, Slack or Discord. They install, screenshot, and some
  become Founding Supporters.
- **Revenue:** the platform, DevEx or security lead at a 20–500 engineer
  company that already pays for agent seats, wants nightly triage, PR review
  and dependency bumps unattended, and whose security team would ban an
  ungoverned chat-reachable agent. They forward a packet and book a call. They
  buy Setup and pilots now, Team later.

## What it is

1. **One docked harness.** A registry of ACP runtimes
   (`src/junction/acp/runtimes.py`): Cursor, Claude Code (via the ACP
   project's `claude-agent-acp` adapter, fetched with `npx` on first run),
   Codex, Kimi, DeepSeek Harness, Goose, Grok, Pi, Droid, and kiro-cli last
   and optional. `agent.acp_backend` defaults to `auto`; pin an id to choose.
   One harness at a time, set globally; schedules, memory and channels stay
   when you switch. Verification status per harness is the matrix in
   [README](README.md#one-harness-at-a-time).
2. **The desk.** The gateway this tree inherited: web dashboard, CLI, ten chat
   apps (five with approve buttons, WhatsApp typed, four chat-only), cron with
   a template gallery, a walk-away task runner with checkpoints, subagents,
   memory, lessons and skills, Agent Worlds, 21 built-in apps, 18 themes, 12
   dashboard languages.
3. **The charter.** The four articles in
   [README](README.md#the-rules-it-cant-open): a keystone policy the agent
   cannot read or write, credential redaction, an HMAC-chained audit log, and
   `POLICY ∩ PROFILE` at Warding's own gate. Scope and fail-open rows are in
   [`SECURITY.md`](SECURITY.md).
4. **A model catalog that lists names.** `warding up` starts a loopback
   listener (`src/junction/model_router/`) that serves `/health` and
   `/catalog`. Completion routes answer `501`. It forwards nothing, holds no
   keys, and is never a headline. The docked harness answers with the models
   it already serves. If the listener is down, the gateway still runs.

## Offers

Nothing in the Apache tree is ever gated. Every paid item carries one of three
labels: Available now, Pre-order, or Waitlist. The live list is the
[pricing page](https://getjunction.dev/pricing/).

| Offer | Label | What it is |
|---|---|---|
| Free | Available now | Everything in this repository, forever. |
| Late Desk Setup | Available now | A paid session on your own machine: install as a service, dock your agent, connect one channel with approvals, write a first policy profile, run one scheduled job. Scope in writing; refund if the named outcome is not reached. |
| Founding Supporter | Available now once its deliverables ship | A numbered seal badge, a Supporter-only Agent World scene and theme pack, a Discord role, a roadmap vote. Future paid features are added to the key as "in development", never sold. |
| Design-partner pilot | Available now, by conversation | Co-building the fleet layer (central policy push, audit forwarding) with a written deliverable and date. |
| Team | Waitlist | The fleet companion: signed policy distribution, plugin allowlist and kill switch, audit forwarding, dashboard SSO. Unbuilt. |
| Hosted late desk | Waitlist | An always-on box we run, only if the waitlist proves it. |

## What it is not

- **Not a parallel-agent GUI.** One harness at a time. If you are at the
  keyboard watching several agents, use a tool built for that.
- **Not a model router.** The catalog lists names; it forwards no traffic and
  takes no provider keys.
- **Not a hosted service.** No account with us, no cloud sessions, no
  multi-user or team features today. Single owner per install.
- **Not audited.** Unaudited by a third party; say so wherever the charter is
  described.
- **Not a fork that hides its origin.** The upstream project is credited in
  line one of anything long. If you are a kiro-cli user, the upstream project
  is ahead and you should use it.

## CLI

`warding` is the CLI. `junction` is a silent alias of the same entry point.

| Command | Role |
|---|---|
| `warding setup` | Install agent config, pick the harness, mark first run complete. |
| `warding up` | Dock the agent and serve the dashboard on loopback. |
| `warding planes` | The docked harness and the catalog in one snapshot (`--json`). |
| `warding doctor --quick` | Verify the install without serving. |
| `warding service install` | Run the same gateway as a systemd unit or launchd agent. |
| `warding chat`, `run`, `cron`, `spawn` | Chat, walk-away tasks, schedules, subagents. |
| `warding security events`, `audit`, `verify` | Read and verify the audit log. |
| `warding policy show`, `validate`, `explain` | Inspect the policy and profiles. |
| `warding router catalog` | The names-only model catalog. |

In development, not yet in the tree: `warding charter` (render the effective
policy as articles), `warding audit verify` (one-command chain status and
export), `warding switch <runtime>` (change harness with a carried-over list).

```json
{
  "agent": {
    "provider": "acp",
    "acp_backend": "auto"
  }
}
```

## Implementation identifiers

Python package `junction`. Data-home env `JUNCTION_HOME`; a new install stores
data in `~/.junction`. GitHub slug `laqaer/junction`. Electron package name
`junction-desktop`. Site: https://getjunction.dev until the owner moves it.
These spellings are implementation, not the product name.

## Authority

Identity and envelope: [`WORKING_BRIEF.md`](WORKING_BRIEF.md). Agent overlay:
[`JUNCTION.md`](JUNCTION.md). Name decision:
[ADR 0008](docs/adr/0008-product-rename-warding.md). Harness facts:
[`TREE.md`](TREE.md). Provenance:
[`docs/provenance/README.md`](docs/provenance/README.md).
