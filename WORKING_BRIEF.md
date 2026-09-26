# Working brief — Junction bootstrap

This is the frozen execution contract for the Junction bootstrap cut.
Product identity, the two-plane thesis, the authority envelope, and the
execution id live here. Architecture detail lives in later ADRs and in
root `ARCHITECTURE.md` once the agent OS lane lands them.

## Identity (frozen)

| Field | Value |
|---|---|
| Product | **Junction** |
| CLI | `junction` |
| Tagline | Where coding agents meet the models you want. |
| Promise | Run Cursor, Claude, Codex, and Grok from one local dashboard, with memory and cron. `junction up` starts a loopback catalog and a role DAG. The docked agent uses models it already serves. Provider translation is not bundled. A vendor agent CLI is optional. |
| Voice | Local-first, precise, no hype. Not another chatbot. Not a Codex clone. |
| Visual | Paper and night: ink and a vermillion seal on paper, warm white and lamp amber on night; factory theme slug `junction`. Mark: the Ward Seal, a keyhole crossed by three ward bars with one drop of wax. Type: Fraunces (wordmark, display) + IBM Plex Sans (body, UI), bundled. Motifs: the seal and the refusal, the lit window, the three ward bars; no mascot. Brand kit: `assets/brand/build.py`. Live production: **https://getjunction.dev**. `www.getjunction.dev` redirects there. |
| GitHub slug | `laqaer/junction`. |
| Package / data home | `junction`, `JUNCTION_HOME`, Electron `productName` stay as implementation identifiers. |
| Lineage | Apache-2.0 gateway + MIT-observed [Codex Router](https://github.com/duolahypercho/codex-router) model plane. Junction is the product; do not present it as a public fork. |

Decision record: [`docs/adr/0001-product-identity.md`](docs/adr/0001-product-identity.md).
Agent overlay: [`JUNCTION.md`](JUNCTION.md).

## Two-plane thesis

Junction is a **local control plane** that docks ACP agents and shows their
model roles. The catalog snapshot came from Codex Router. Junction is not a
Node dump of that product, and it does not forward provider traffic.

```
Operator
  → junction CLI / dashboard
    → Python gateway
      → Harness plane (ACP runtime registry: Cursor, Claude, Codex, Grok, Pi, …)
      → Model plane (built-in loopback catalog, typically :4202; /health and /catalog only)
      → Memory, cron, skills
```

- **Harness plane** already exists on `main`: `agent.acp_backend` defaults to
  `auto` via `src/junction/acp/runtimes.py`. Multi-ACP must not be re-landed.
- **Model plane** is the listener `junction up` starts in
  `src/junction/model_router/`. Completions return `501`. A translation
  gateway on `:4200` is not bundled. If the catalog listener is down,
  Junction still works as an ACP gateway (degraded, documented).
- An operator may later point an agent's `openai_base_url` at a translation
  listener they run themselves. Junction does not mint that URL and never
  pastes provider keys into chat.

Current contract: [ADR 0007](docs/adr/0007-builtin-model-catalog.md). The
execution manifest below records the bootstrap cut. It is not the
model-plane contract.

## Authority envelope

Safe agent-prompts defaults for this execution:

| Allowed | Blocked |
|---|---|
| Feature branch, commit, push | Merge to `main` |
| Pull request | GitHub Pages on `main` |
| GitHub issues for the epic and lanes | Paid Vercel, PyPI, Docker publish |
| Vercel hobby deploy of `site/` (preview and production alias) | External comms (issues on other repos, emails, tweets) |
| Attach operator-purchased domains to `junction-site` | Data deletion, irreversible migrations |
| | GitHub repository rename (token cannot PATCH; human Settings → Rename) |

## Execution

| Field | Value |
|---|---|
| Execution id | `bc-39bfeb15-ff12-4636-840a-217a97c555da` |
| Branch | `cursor/junction-launch-55da` |
| Base | `main` at `78424fb73` |
| Intake | No intake issue existed at start. Open Dependabot PRs #10–#14 are unrelated. |
| Shape | One bootstrap PR to `main`. Do not merge it in this execution. |

## This-cut non-goals

Merge; GitHub rename (token-blocked); package / data-home rename; PyPI / Docker / paid
Vercel; vendoring Codex Router; copying tray / widget / Electron / public
Cursor HTTPS tunnel / ACP agent bridges; reimplementing LiteLLM; storing
provider keys in `JUNCTION_HOME` without the router's secret-entry rules;
weakening keystone or harness-parity; restoring Channels / Board; whole-tree
i18n rewrite; Dependabot unless it blocks the branch; `CHANGELOG.md` (written
only at version bump).

## Surfaces

| Surface | URL |
|---|---|
| Bootstrap PR | https://github.com/laqaer/junction/pull/23 |
| Epic | https://github.com/laqaer/junction/issues/16 |
| Hobby **preview** (this SHA, `target` unset) | https://junction-site-drdzpa9u5-laqaers-projects.vercel.app |
| Production site | https://getjunction.dev (live) |
| Canonical host | https://getjunction.dev (`www` redirects here). `junction.computer` is not the host: no public DNS, and it was not purchased. |
| Hobby default alias | https://junction-site.vercel.app |

## Execution manifest

Distinguish **proven** (this agent ran it) from **not_run**. Live provider
routing and the full gateway suite were never in this cut's must-run list.

| Check | Result |
|---|---|
| Site `npm ci` / `npm test` / `npm run build` | proven (8 vitest tests) |
| Branding + CLI tests (`TestBannerBranding`, dashboard `bot_name`, product name, brand-name gate) | proven (114 pytest) |
| Model-router unit tests (mocked listener up/down; secrets dropped) | proven |
| Brand-name diff gate vs `origin/main` | proven |
| docs-lint | proven |
| Bootstrap PR + epic/lane issues | proven (#23, #16–#22) |
| Site CI workflow file | proven (`.github/workflows/site.yml`; Actions in flight) |
| Vercel hobby URL for `site/` | proven. Preview: https://junction-site-drdzpa9u5-laqaers-projects.vercel.app (`target` unset). First deploy also created https://junction-site.vercel.app — Vercel labeled that one `production` internally. No custom domain, no GitHub Pages, no spend. Not a production ship of this product. |
| Marketing walkthrough (nav → two-plane → CLI → FAQ) | proven against local `vite preview` dump-dom and the live preview URL: Junction nav/hero, Harness + Model planes, `junction gateway`, vendor agent CLI optional, never-paste-keys on the model plane, no ghost emoji. Interactive FAQ accordion click and computerUse recording: not_run (GUI agent spend-limited). |
| Live Codex Router against Kimi/DeepSeek | not_run (no local sidecar) |
| Full gateway pytest / desktop | not_run |


