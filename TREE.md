# Warding

Runs one docked ACP coding agent at a time on the operator's own machine
and keeps a names-only model catalog beside it. GitHub slug:
`laqaer/junction`. Product identity: [`PRODUCT.md`](PRODUCT.md). Overlay:
[`JUNCTION.md`](JUNCTION.md).

This tree does not require `kiro-cli`. Multi-ACP is already on `main`.

## Why this exists

Warding is a gateway (dashboard, CLI, messaging channels, cron, memory)
that speaks [Agent Client Protocol](https://agentclientprotocol.com/) over
stdio to one docked agent. `warding up` starts a loopback model catalog
that lists names. The docked agent uses the models it already serves.
Warding does not forward provider traffic.

Default `agent.acp_backend` is `auto`: the first installed of Cursor,
Claude, Codex, Kimi, DeepSeek Harness, Goose, Grok, Pi, Droid. `kiro-cli`
is last in that list and optional. Set a concrete id to pin.

```json
{
  "agent": {
    "provider": "acp",
    "acp_backend": "cursor"
  }
}
```

CLI: `junction`. State lives in `~/.junction`, the one data home. Package
import path is `junction`. `JUNCTION_HOME` overrides the data home.

Registry: `src/junction/acp/runtimes.py`. Two-plane thesis:
[`ARCHITECTURE.md`](ARCHITECTURE.md). Model catalog and role DAG:
[`docs/system-specs/modules/model-router.md`](docs/system-specs/modules/model-router.md).
