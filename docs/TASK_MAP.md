# Junction — task map

**A dated local handoff.** GitHub issues own status: bugs, features, and stories
live there. The *why* lives in the ADRs ([`adr/`](adr/README.md)); the
*direction* lives in [`../ROADMAP.md`](../ROADMAP.md). This file says what is in
flight and where. Local work is real, just unmerged; merged is not released.
Envelope: [`../WORKING_BRIEF.md`](../WORKING_BRIEF.md). Agent loop:
[ADR 0006](adr/0006-agent-os-no-automerge.md).

## Where work is tracked

| Surface | Owns | Published? |
|---|---|---|
| GitHub issues (`bug`, `enhancement`, `documentation`) | Status of every bug, feature, and story | Yes — issues own status |
| [`docs/adr/`](adr/README.md) | Decisions and their rationale (*why*), frozen once accepted | Yes |
| [`../ROADMAP.md`](../ROADMAP.md) | Merged milestones and the maintain loop | Yes |
| This file | Local, in-flight lanes and where they live, as of a date | No — a dated local handoff |

The operator's portfolio memory lives in `~/dev/memory/INDEX.md` on the
operator's machine. It is a **reference, not authority**: it carries reviewed
conventions, lessons, and pointers, but each repository owns its own facts,
contracts, and work state. A memory record never overrides this repo's
`AGENTS.md`, ADRs, or code.

**Writing to memory.** When a session learns something reusable — a convention,
a lesson, a pointer — propose it as a record under that repository's own rules,
with the exact source. An agent never self-publishes memory. An operator merge
makes the record an accepted **reference**; the owning repository always stays
authoritative, so a record never overrides this repo's `AGENTS.md`, ADRs, or
code. This is a shared **file read/write protocol** only; automatic
cross-harness memory import (hooks that sync memory between harnesses) is not
installed.

## Start and finish

**Start of a session**

1. `git fetch`; compare your branch with `origin/main` so you know what is
   *merged* (on `main`) versus *local* (unpushed, on a branch).
2. Read the open GitHub issues (they own status) and this file for in-flight
   lanes.
3. Read `~/dev/memory/INDEX.md` for prior lessons and conventions (reference,
   not authority).
4. Open the owning doc for the subsystem from the routing table in
   [`../AGENTS.md`](../AGENTS.md) before editing code.

**Finish of a session**

1. File or update a GitHub issue for every bug, feature, or story: it is the
   published record. Apply an existing label (`bug`, `enhancement`,
   `documentation`, `readiness:*`); do not mint a new taxonomy.
2. If a decision was made, write it as an ADR (the *why*), not into this file.
3. If the session learned a reusable lesson or convention, propose a memory
   record (the "Writing to memory" rule above); it is an accepted reference
   once the operator merges it, never authority over this repo.
4. Update this file only for local, unpublished state.
5. Run [`./scripts/docs-lint.sh`](../scripts/docs-lint.sh) when docs changed.
6. **Record, do not publish.** Leave the branch, the changed paths (committed or
   not), the test command and its result, and the next action where the next
   session will find them. Commit and push only when explicitly authorized; a
   lane is not on `main` until a human merges it
   ([ADR 0005](adr/0005-preview-not-production.md),
   [ADR 0006](adr/0006-agent-os-no-automerge.md)).

## Merged on `main`

Verified 2026-09-27 against `origin/main`:

- **Identity freeze (M0)** — product is Junction, CLI `junction`. [ADR 0001](adr/0001-product-identity.md).
- **Harness plane** — ACP runtime registry, `agent.acp_backend` defaults to `auto`.
- **Model plane** — built-in loopback catalog (`src/junction/model_router/`);
  `/health` and `/catalog` only, no provider forwarding, completions answer
  `501` (`model_router_no_forward`). Landed via [#24](https://github.com/laqaer/junction/pull/24).
- **CLI chrome, ship program, identity retire** — merged as
  [#26](https://github.com/laqaer/junction/pull/26),
  [#33](https://github.com/laqaer/junction/pull/33),
  [#39](https://github.com/laqaer/junction/pull/39),
  [#41](https://github.com/laqaer/junction/pull/41).

The original bootstrap PR [#23](https://github.com/laqaer/junction/pull/23) was
**closed unmerged**; its bootstrap work landed through the PRs above.
Epic [#16](https://github.com/laqaer/junction/issues/16) and lanes
[#17](https://github.com/laqaer/junction/issues/17)–[#30](https://github.com/laqaer/junction/issues/30)
are all closed.

## Local (unmerged)

On a branch, not on `main`. Local work is real; it is just unmerged.

| Branch | Worktree | SHA | Lane | State | Issue |
|---|---|---|---|---|---|
| `rescue/harness-router` | `/tmp/jxrescue` | `50bc58329` | Dock OpenCode as an ACP harness; route work across harness subscriptions; reruns, model choice, tasks, and background work run on the active harness | Kiro-ID leakage fix in place: Kiro model ids were wrongly inherited and translated onto a foreign harness; the fix keeps the foreign harness on its own ids. Focused harness suite **402 passed** (router / parity / runtimes / session, 2026-09-27); an extended nine-file run is 777 passed / 6 pre-existing skips; ACP client suite 533 passed. `auto` now resolves to a concrete harness at provider creation, so an `auto`-persisted session may see one provider-switch replay after upgrade (live behavior unverified). Not yet merged | [#43](https://github.com/laqaer/junction/issues/43) |
| `rescue/config-role-keys` | `/tmp/jx-rescue-rolekeys` | `f33e4ca81` | Add the allowed-value enum to the **existing** per-role effort properties (config baseline, config loader, model-router spec, tests; +84/-7 across 4 files). Per-role **model** and **effort** keys are already on `main`. | Verified 2026-09-27: `test/test_config_schema.py` **21 passed** | [#42](https://github.com/laqaer/junction/issues/42) |
| `claude/pensive-faraday-g61q5y` | — | `9dc42c1d4` | Adversarial audit of identity, vocabulary, and host handling | Triaged 2026-09-27; no human choice needed — see below | [#44](https://github.com/laqaer/junction/issues/44) |

**Next action.** These lanes are unmerged and not committed to `main`. Commit and
push require an explicit user instruction. Full CI and a live-harness run have
not been done. The harness suite now reports 402 passed; that is a
focused-suite result only, not full verification, and the lane itself still
stays unmerged. The immediate AUTO behaviour change is covered by the suites
above; the operator-facing provider-switch replay is a caution, not a tested
guarantee (no live-harness run has been done). The rescue branches are preserved
as a full-history git bundle outside this repository, with an
uncommitted-changes patch export alongside it.

**Pensive audit, triaged.** Most of the branch overlaps work already merged in
[#41](https://github.com/laqaer/junction/pull/41) and is dropped rather than
re-landed:

- The npx adapter fallback is needed and is now implemented (uncommitted) on the
  same branch.
- The upstream-vocabulary drop is mostly superseded by #41; the two remaining
  descriptions are now corrected locally.
- The upstream-host safety change is superseded: the beacon ships empty and the
  host list already names Junction hosts, so the current defaults stand.

Verified 2026-09-27 on the rescue branch: 533 ACP tests and 396 focused UI
tests pass; catalog gates are green. Three broader i18n failures are
pre-existing and recorded as a verification limitation.

## Lane map (bootstrap cut)

| Epic / lane | What lands | Surfaces | Status | Issue |
|---|---|---|---|---|
| Freeze | Product name Junction, CLI `junction`, tagline, promise, authority envelope, execution id | [`WORKING_BRIEF.md`](../WORKING_BRIEF.md), [`JUNCTION.md`](../JUNCTION.md), [ADR 0001](adr/0001-product-identity.md) | Merged (M0) | [#16](https://github.com/laqaer/junction/issues/16) |
| Docs / agent OS | Product, architecture, ADRs 0002–0006, provenance, overlay skills, router rows | [`PRODUCT.md`](../PRODUCT.md), [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`docs/adr/`](adr/README.md), [`.agents/`](../.agents/README.md) | Merged on `main` | [#17](https://github.com/laqaer/junction/issues/17) |
| Site | Marketing overlay: Junction, two planes, track motif, no ghost emoji; catalog copy matches ADR 0007 | `site/` | Merged; preview at [junction-site.vercel.app](https://junction-site.vercel.app) | [#18](https://github.com/laqaer/junction/issues/18) |
| CLI chrome | `junction`, the only console script | CLI packaging / entry | Merged on `main` | [#19](https://github.com/laqaer/junction/issues/19) |
| Model-router | Built-in loopback catalog with `junction up`; health, catalog, role DAG; no provider forwarding; namespaced slugs are not sent on the harness wire | `src/junction/model_router/`, [model-router spec](system-specs/modules/model-router.md) | Merged on `main` | [#20](https://github.com/laqaer/junction/issues/20) |
| GitHub / CI / preview | Epic issues; site CI; Vercel preview of `site/` only | `.github/workflows/site.yml`, Vercel hobby preview | Merged on `main` | [#21](https://github.com/laqaer/junction/issues/21) |
| Integration-owner | End-to-end check that lanes compose; no merge, no production, no spend | [ADR 0005](adr/0005-preview-not-production.md), skill `integration-owner` | Ongoing | [#16](https://github.com/laqaer/junction/issues/16) |
| Ship program | Chrome rewrite, routing fixes, ship + maintain roadmaps, agent-OS loop | this file, [`../ROADMAP.md`](../ROADMAP.md), [ADR 0006](adr/0006-agent-os-no-automerge.md) | Merged ([#26](https://github.com/laqaer/junction/pull/26)) | [#26](https://github.com/laqaer/junction/pull/26) |
| M2 router install | A separate translation install is not this cut. The catalog listener is built in. Secrets stay out of the data home. | Docs | Superseded as an install step by [ADR 0007](adr/0007-builtin-model-catalog.md); forwarding is still not bundled | [#22](https://github.com/laqaer/junction/issues/22) |
| M3 domain | Human confirms a quoted domain, pays, attaches DNS to `junction-site` | Vercel registrar | Closed, human-gated | [#27](https://github.com/laqaer/junction/issues/27) |
| Catalog i18n | Remaining dashboard catalog literals to `{{productName}}` | `website/` locales | Closed (follow-up) | [#28](https://github.com/laqaer/junction/issues/28) |
| Automations | Cursor Automations for scout / implement / review | Cursor dashboard | Closed, human-gated | [#29](https://github.com/laqaer/junction/issues/29) |
| Adversarial remainder | Orchestration apply site; brand-gate teaching text names the retired upstream identity and Junction's replacement for each finding | routing + `check_brand_name.py` | Closed | [#30](https://github.com/laqaer/junction/issues/30) |
| Maintain | Scout → implement → review → human merge; adversarial passes; catalog refresh | [ADR 0006](adr/0006-agent-os-no-automerge.md) | Ongoing | [#29](https://github.com/laqaer/junction/issues/29) |

## Out of this cut

Merge; GitHub rename; package / data-home rename; PyPI / Docker / DNS /
paid Vercel; vendoring Codex Router; copying tray / widget / Electron /
public Cursor HTTPS tunnel / ACP agent bridges; reimplementing LiteLLM;
whole-tree i18n rewrite; `CHANGELOG.md`; auto-merge of agent PRs.
