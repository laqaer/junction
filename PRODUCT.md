# Junction

**Where coding agents meet the models you want.**

Junction is a local control plane. It docks ACP coding agents on one
loopback dashboard, with memory and cron, on hardware you control. A vendor
agent CLI is optional.

Run Cursor, Claude, Codex, and Grok from one dashboard. `junction up`
starts a loopback catalog of model names and a role DAG. The docked agent
uses the models it already serves. Provider translation is not bundled.

Voice: local-first, precise, no hype.

## Who it is for

Operators who already run coding agents and want one place to choose **which
agent** and **which model**, without moving work into a hosted chatbot or
giving a remote service the keys.

Typical operator: a developer or small team with Cursor, Claude Code, Codex,
or Grok on the machine, plus a mix of provider accounts (Kimi, DeepSeek,
Copilot, …). Junction is the join.

## What it is

Two planes, one product. See [`ARCHITECTURE.md`](ARCHITECTURE.md).

1. **Harness plane** — an ACP runtime registry. Default `agent.acp_backend`
   is `auto`: the first installed of Cursor, Claude, Codex, Kimi, DeepSeek
   Harness, Goose, Grok, OpenCode, Pi, Droid. Pin a concrete id when you want one
   agent. A vendor agent CLI remains selectable and last in that preference list.
2. **Model plane** — a loopback catalog Junction starts with `junction up`.
   The shipped catalog lists namespaced model choices. Role routing
   (orchestration → planning → execution) spends cheaper models on
   coordination and capable models on planning. Provider translation is
   not bundled. If the catalog listener is down, the ACP gateway still runs.

Memory, cron, skills, and the dashboard come from the gateway that already
lives in this tree.

## Where it sits

| Product | What you get | What stays yours to do |
|---|---|---|
| Cursor, Claude Code, Codex | One harness and that vendor's models | A second tool for every other agent |
| OpenRouter, LiteLLM | One endpoint that translates provider traffic | Docking agents, local memory, cron, a dashboard |
| Hosted agent bots | A remote conversation | Your files, your keys, your machine |
| Junction | Several ACP harnesses, local memory, cron, skills, a sandbox, and a visible catalog and role DAG on loopback | Provider translation. The catalog lists names. Completions on that listener return 501. The harness answers with models it already serves. |

The join is the product: one local switch for agents you already run, plus
a map of model roles you can see. It is not a second proxy.

## What it is not

- **Not another chatbot.** There is no hosted conversation product and no
  account system of Junction's own.
- **Not a Codex clone.** Codex is one dockable ACP agent, not the product.
- **Not a hosted model proxy.** The catalog is local. Junction does not
  forward provider traffic and does not take provider keys in chat.

Rejected names (Hearth, Relay, Rudder, and the rest) live in
[`docs/adr/0001-product-identity.md`](docs/adr/0001-product-identity.md).

## CLI

| Command | Role |
|---|---|
| `junction` | Primary CLI. |
| `junction up` | Compose both planes, then start the loopback dashboard. |
| `junction planes` | Harness + model + role DAG in one snapshot (`--json` for machines). |
| `junction doctor --quick` | Compose-only probe. Full `junction doctor` still exists. |
| `junction gateway` | Same server as `up`; kept for scripts. |
| `junction router catalog` | Namespaced model choices (no credentials). |
| `junction router plan` | Orchestration / planning / execution DAG. |

```json
{
  "agent": {
    "provider": "acp",
    "acp_backend": "auto"
  }
}
```

## Implementation identifiers

Python package `junction`. Data-home env `JUNCTION_HOME`. A new install
stores data in `~/.junction`. GitHub slug: `laqaer/junction`. Site:
https://getjunction.dev

## Authority

Frozen identity and the execution envelope:
[`WORKING_BRIEF.md`](WORKING_BRIEF.md). Agent overlay:
[`JUNCTION.md`](JUNCTION.md). Multi-ACP facts:
[`TREE.md`](TREE.md). Provenance:
[`docs/provenance/README.md`](docs/provenance/README.md).
