# xmuse

xmuse is a multi-agent software delivery platform for chat-driven GOD orchestration. It
turns a human request into a persistent groupchat where specialist GOD participants can
discuss, propose work, hand off execution, and leave durable evidence.

The current release candidate is intended to be understandable, installable, and
demo-runnable from a fresh checkout without reading the handoff history.

## Current Capabilities

- Chat-first groupchat intake with default Architect, Review, and Execute GOD participants.
- Durable chat state in `chat.db` plus GOD session metadata in `god_sessions.json`.
- Peer scheduling through `PeerChatScheduler`, with MCP writeback as the real happy path.
- Provider matrix for Codex, OpenCode, and test/demo fake paths.
- Runtime health and cleanup visibility through `xmuse-platform-runner --health-once`.
- Scoped CI gates for package boundaries, provider/config contracts, health smoke, and type baseline.

## Architecture Overview

```text
Human operator
  -> Chat API :8201
  -> chat.db inbox/message stores
  -> PeerChatScheduler
  -> GOD session layer
  -> Codex app-server thread
  -> MCP /mcp/chat :8100
  -> chat.db reply/writeback evidence
```

The fake demo uses the same chat store and scheduler semantics, but replaces the external
Codex/Ray/MCP transport with an in-process fake GOD layer. It is for onboarding only and is
not evidence that the real production runtime works.

## Install

Prerequisites:

- Python 3.11
- `uv`

From the repository root:

```bash
uv sync --frozen --all-groups
```

Optional local env file:

```bash
cp .env.example .env
```

Default install and CI paths do not require Codex, Ray services, OpenCode, DeepSeek keys, or
any sibling repository.

## Quickstart

Run the local health smoke:

```bash
uv run xmuse-platform-runner --health-once
```

Run the maintained fake groupchat demo:

```bash
uv run python scripts/demo_fake_groupchat.py
```

Expected output includes:

```text
fake-groupchat-demo-ok
scheduler_happy_path=1
GOD reply: ...
```

See [QUICKSTART.md](QUICKSTART.md) for a clean environment walkthrough.

## Fake Groupchat Demo

The fake demo:

- creates a real xmuse conversation through `PeerChatService`;
- posts a human message that creates an Architect GOD inbox item;
- runs `PeerChatScheduler.tick_once()`;
- writes a GOD reply via existing `chat_read_inbox` and `chat_post_message` service semantics;
- verifies the scheduler observed an MCP-style writeback happy path.

Command:

```bash
uv run python scripts/demo_fake_groupchat.py --message "Draft a release checklist."
```

## Real Ray/Codex/MCP Manual Gate

The real runtime gate is operator-run and is not part of default CI:

```bash
export XMUSE_PEER_GOD_BACKEND=ray
export XMUSE_EXECUTE_GOD_BACKEND=ray
export XMUSE_REVIEW_GOD_BACKEND=ray
export XMUSE_RAY_GOD_TRANSPORT=app-server
export XMUSE_RAY_GOD_EFFORT=low
export XMUSE_RAY_GOD_MCP=1
export XMUSE_DEPLOYMENT_PROFILE=production
export XMUSE_CHAT_API_URL=http://127.0.0.1:8201
export XMUSE_CHAT_API_AUTH_TOKEN=<server-token>
export XMUSE_CHAT_API_KEY=<same-token-for-tui-client>
export XMUSE_MCP_AUTH_TOKEN=<server-token>

uv run python -m xmuse.chat_api
uv run python -m xmuse.mcp_server --port 8100
uv run xmuse-platform-runner --peer-chat --mcp-port 8100
uv run xmuse-live-gate-status-capture \
  --output-dir xmuse/work/release_readiness/artifacts/live_gate_status
uv run xmuse-internal-review-gate-capture \
  --artifact xmuse/work/release_readiness/internal-review.json \
  --expected-head-sha <current-head-sha> \
  --output xmuse/work/release_readiness/artifacts/internal-review.json
uv run xmuse-memoryos-live-gate-capture \
  --artifact xmuse/work/release_readiness/memoryos-trace.json \
  --output xmuse/work/release_readiness/artifacts/live-memoryos.json
uv run xmuse-natural-deliberation-gate-capture \
  --artifact xmuse/work/release_readiness/natural-transcript.json \
  --output xmuse/work/release_readiness/artifacts/natural-deliberation.json
uv run xmuse-real-provider-runtime-gate-capture \
  --artifact xmuse/work/release_readiness/real-provider-runtime.json \
  --output xmuse/work/release_readiness/artifacts/real-provider-runtime.json
uv run xmuse-release-readiness-capture \
  --artifacts-dir xmuse/work/release_readiness/artifacts \
  --output xmuse/work/release_readiness/report.json
```

Manual verification:

```bash
uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume
```

## Production / Experimental / Legacy Boundaries

| Area | Status | Boundary |
| --- | --- | --- |
| Chat API, MCP server, `PeerChatScheduler`, Ray/Codex app-server writeback | Production path | Manual real runtime gate required before claiming production readiness. |
| Codex = primary | Supported provider | Only production groupchat GOD provider. |
| OpenCode = secondary | Bounded worker only | Requires `DEEPSEEK_API_KEY`; no MCP writeback or persistent GOD session. |
| Fake = test/demo only | Onboarding and CI smoke | Must not be used as proof of real Ray/Codex/MCP operation. |
| TUI/dashboard | Experimental UI surfaces | Useful for inspection, not release-blocking production proof. |
| Legacy master loop, Hermes, old shell scripts | Legacy | Kept for historical compatibility; not the current groupchat mainline. |

Known limits are tracked in [docs/xmuse/release-checklist.md](docs/xmuse/release-checklist.md).
