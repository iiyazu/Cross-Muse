# xmuse Quickstart

This walkthrough starts from a clean checkout and ends with a fake groupchat demo. The
demo does not require Codex, Ray, OpenCode, DeepSeek, or memoryOS.

## Clean Environment Setup

Prerequisites:

- Python 3.11
- `uv`

Install all locked dependency groups:

```bash
uv sync --frozen --all-groups
```

Optional local config:

```bash
cp .env.example .env
```

Default fake demo and CI paths do not need provider secrets.

## Run Health Check

Run the local health summary:

```bash
uv run xmuse-platform-runner --health-once
```

To include HTTP readiness probes while the Chat API and MCP server are already running:

```bash
uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100
```

## Run Fake Groupchat Demo

Run:

```bash
uv run python scripts/demo_fake_groupchat.py
```

Use a custom runtime root and message:

```bash
uv run python scripts/demo_fake_groupchat.py \
  --xmuse-root /tmp/xmuse-fake-demo \
  --message "Create a small release candidate checklist."
```

Expected output includes:

```text
fake-groupchat-demo-ok
scheduler_happy_path=1
GOD reply: Architect GOD demo reply: ...
```

The script creates a conversation, posts a human message, runs the existing scheduler, and
verifies a GOD reply was persisted through the existing chat/store/scheduler path.

## Optional Real Runtime Notes

The real Ray/Codex/MCP path needs local runtime services and a working Codex CLI:

```bash
export XMUSE_PEER_GOD_BACKEND=ray
export XMUSE_EXECUTE_GOD_BACKEND=ray
export XMUSE_REVIEW_GOD_BACKEND=ray
export XMUSE_RAY_GOD_TRANSPORT=app-server
export XMUSE_RAY_GOD_EFFORT=low
export XMUSE_RAY_GOD_MCP=1
export XMUSE_CHAT_API_URL=http://127.0.0.1:8201
```

Start services from separate terminals:

```bash
uv run python -m xmuse.chat_api
uv run python -m xmuse.mcp_server --port 8100
uv run xmuse-platform-runner --peer-chat --mcp-port 8100
```

Run the manual real runtime gate only when those dependencies are available:

```bash
uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume
```
