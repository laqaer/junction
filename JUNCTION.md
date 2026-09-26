# Junction — product overlay

Read this **before** contributor docs that still use older names. This checkout
is Junction: a local control plane that docks ACP agents and routes their
models.

Frozen identity, authority, and execution id:
[`WORKING_BRIEF.md`](WORKING_BRIEF.md). Identity ADR:
[`docs/adr/0001-product-identity.md`](docs/adr/0001-product-identity.md).
Product / architecture / roadmap: [`PRODUCT.md`](PRODUCT.md),
[`ARCHITECTURE.md`](ARCHITECTURE.md), [`ROADMAP.md`](ROADMAP.md).
Lane map: [`docs/TASK_MAP.md`](docs/TASK_MAP.md).

## Product (do not un-freeze)

- **Name:** Junction. One word. CLI `junction`.
- **Tagline:** Where coding agents meet the models you want.
- **Not the product:** Codex Router, Hearth, Relay, Rudder.
- Do not present Junction as a public fork of another agent product in
  README, site, CLI help, or prompts.

## Two planes

1. **Harness plane** — ACP runtime registry (`src/junction/acp/runtimes.py`).
   Default `agent.acp_backend` is `auto`. A vendor agent CLI is optional.
2. **Model plane** — a loopback catalog `junction up` starts
   (`src/junction/model_router/`). `GET /health` and `GET /catalog` only.
   Completion routes answer `501` `model_router_no_forward`. It does not
   vendor the Node tree, copy tray/tunnel/agent-bridges, or reimplement
   LiteLLM. Translation on `:4200` is not bundled, so status stays
   `degraded` while only the catalog is up.

If the catalog listener is down, the gateway still runs. Document that
degradation. Never log secrets. Never paste provider keys into chat.
`junction router` must not claim a sidecar injects keys.

ADRs: [0002](docs/adr/0002-two-planes.md),
[0003](docs/adr/0003-sidecar-not-vendor.md),
[0007](docs/adr/0007-builtin-model-catalog.md). Spec:
[`docs/system-specs/modules/model-router.md`](docs/system-specs/modules/model-router.md).

Site: https://getjunction.dev

## Implementation identifiers

`junction`, `JUNCTION_HOME`, `~/.junction`, Electron `productName` Junction.
GitHub slug is `laqaer/junction`. The data home is `~/.junction` (override:
`JUNCTION_HOME`); there is no fallback to another product's directory, no
legacy env prefix, and no CLI alias besides `junction`.

## Visual identity

- **Mark:** the Ward Seal: a round seal with a keyhole whose shaft is crossed
  by three ward bars (the wards in a lock, which stop every wrong key from
  turning) and one drop of wax at two o'clock. Ink on paper, bars in seal
  vermillion; the nightly build lights the drop in lamp amber.
- **Palette:** paper (`#F3EEE3` ground, `#FBF8F1` sheet, `#1A1814` ink,
  `#B3301A` seal, `#B86A00` lamp) and night (`#0B0E14` ground, `#141A26`
  surface, `#ECE8E1` foreground, `#FF7A5C` seal, `#FFB547` lamp). The
  dashboard's factory theme slug is `junction`.
- **Type:** Fraunces (wordmark and display) and IBM Plex Sans (body and UI),
  bundled under `website/public/fonts`; no font CDN. The wordmark is
  "warding" in Fraunces wght 600, opsz 144, tracked -0.015 em.
- **Motif:** the seal and the refusal, the lit window, the three ward bars.
  No mascot.
- **Source of truth:** [`assets/brand/build.py`](assets/brand/build.py)
  generates the mark, glyph, wordmark, lockups, README banner, app icons
  (`.png`/`.ico`/`.icns`, nightly variant), tray template, PWA icons, the
  gateway's `/logo.png`, and the DMG/NSIS installer art.

## Security and harness (do not weaken)

Keystone paths under the data home stay in `security._SENSITIVE_HOME_DIRS`.
Governance is `effective = POLICY ∩ PROFILE` at Junction's own PreToolUse
gate. Computer use stays ungoverned by scopes. Harness identity is positive
(`is_kiro_backend` / membership sets), never "not Claude". An added harness
adapts; it does not widen the Kiro path.

ADR: [0004](docs/adr/0004-security-unchanged.md).

## Agent OS (this repo)

Checkout-local skills live under [`.agents/skills/`](.agents/README.md)
(contributor overlay). They are **not** packaged `builtin_skills`. Index:

| Skill | When |
|---|---|
| `product-identity` | Name, CLI, identifiers that stay |
| `acp-runtimes` | Harness registry, `auto` default |
| `model-router` | Catalog listener, health/status, role DAG, no forwarding |
| `security-keystone` | Ceiling and harness-parity floor |
| `integration-owner` | Envelope; no merge / spend |
| `marketing-site` | `site/` overlay and preview |
| `dashboard-i18n` | `{{productName}}`; no hardcoded English |
| `agent-os` | Scout / implement / review loop; never merge |

A skill that any **shipped** feature, tool, or packaged doc references must
still live in `src/junction/builtin_skills/`. Top-level `skills/` is
checkout-only.

## Docs and changelog

New contributor docs under `docs/` need directory indexes and
`./scripts/docs-lint.sh`. Provenance:
[`docs/provenance/README.md`](docs/provenance/README.md). Do not edit
`CHANGELOG.md` on a feature PR.

## Authority

Branch, commit, PR, issues, and `site/` preview: yes. Merge, production
deploy, DNS, spend, external comms, data deletion, irreversible migrations:
no. Envelope: [`WORKING_BRIEF.md`](WORKING_BRIEF.md). ADR:
[0005](docs/adr/0005-preview-not-production.md).
