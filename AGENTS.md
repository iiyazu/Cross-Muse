# xmuse

Autonomous software development platform. Standalone sibling export of the `memoryOS` repo, developed in a git worktree.

## Package Structure

Two packages, one `pyproject.toml`:

| Path | Role | Notable |
|------|------|---------|
| `xmuse/` | Runtime/application layer | Intentionally **no `__init__.py`** — keeps runtime namespace boundary |
| `src/xmuse_core/` | Reusable core library | All platform logic lives here |
| `tests/xmuse/` | All xmuse tests | 167+ test files, `asyncio_mode = auto` |

`xmuse/` imports from `xmuse_core.*` (not from `xmuse.`). The split mirrors the old in-repo boundary with MemoryOS: `xmuse/` was the runtime dir, `src/xmuse_core/` was the shared library.

## Entrypoints

```bash
uv run xmuse-chat-api          # REST API (FastAPI)
uv run xmuse-mcp-server        # MCP-over-HTTP server (FastAPI)
uv run xmuse-platform-runner   # Platform orchestrator
uv run xmuse-release-readiness-capture  # Redacted release-readiness report
uv run xmuse-tui               # Textual TUI
```

Or directly:
```bash
uv run python xmuse/chat_api.py
uv run python -m xmuse.tui
uv run python xmuse/platform_runner.py
uv run python xmuse/release_readiness_capture.py
uv run python xmuse/mcp_server.py
```

## Developer Commands

```bash
uv run pytest                           # All tests
uv run pytest tests/xmuse/test_foo.py   # Single file
uv run ruff check .                     # Lint
uv run ruff check <file>                # Lint single file
```

Always use `uv run` — never bare `pytest` or `ruff`. The `.venv` is managed by `uv`.

## Architecture Facts

- **GOD 群聊**: `src/xmuse_core/chat/` + `xmuse/chat_api.py`. `chat.db` (sqlite) holds conversations/messages/participants.
- **Feature/lane workflow**: `src/xmuse_core/structuring/`. Blueprint → feature plan → lane graph/graph-set → projection → execution.
- **Platform orchestrator**: `src/xmuse_core/platform/orchestrator.py`. Coordinates lane execution & review.
- **Dashboard**: `xmuse/dashboard_api.py` (thin router) + `src/xmuse_core/platform/dashboard_*` (read models).
- **TUI**: `xmuse/tui/` — Textual app, reads local store/read envelopes.
- **Providers**: `src/xmuse_core/providers/`. Model adapters for Codex, OpenCode, fake. Policy & registry.
- **Self-evolution**: `src/xmuse_core/self_evolution/`. Controller, watcher, decomposer, recovery.
- **MCP**: `xmuse/mcp_server.py` + `src/xmuse_core/platform/mcp_*` modules.

## Key Constraints

- **`xmuse/__init__.py` must NOT exist** — it's the runtime namespace boundary. Wheel packaging uses explicit `packages = ["xmuse", "src/xmuse_core"]` in pyproject.toml.
- **`XMUSE_ROOT` env var** overrides the runtime root (`default_xmuse_root()`). All runtime state files respect this.
- **`feature_lanes.json`** is a live projection/queue, NOT the authority. Authority is in graph-sets and durable stores.
- **Ray actors** are not durable state authority. Crash recovery must use durable store.
- **LangGraph** orchestrates workflows but must NOT write lane status directly.
- **Dashboard/TUI** read read models and envelopes. They must NOT bypass contracts to write internal state.
- **Memory refs** use `memory://conversation/<id>/...` or `memory://global/...` format. Feature-scoped refs need `feature_scope_id`.
- **package boundary tests** (`tests/xmuse/test_package_boundaries.py`) enforce that `xmuse_core` doesn't directly import `memoryos_lite`.

## Docs

Current authoritative docs are in `docs/xmuse/`. Old `docs/superpowers/` specs/plans remain on disk for test/legacy references but are not the current entry point. Start with `docs/xmuse/README.md`.

## OpenCode Orchestration

Multi-agent orchestration system for long-running tasks. Configured in `opencode.json`.

### Subagents (@-mention)

| Agent | When to Use |
|-------|-------------|
| @orchestrator | Multi-step tasks (2+ files). Runs 4-phase loop |
| @planner | Complex tasks needing structured planning first |
| @coder | Implementation within defined scope (spawned by orchestrator) |
| @adversarial-reviewer | Code review against spec (spawned by orchestrator) |
| @swarm-coordinator | Multiple independent features in parallel |

### Skills (load with `skill` tool)

| Skill | Purpose |
|-------|---------|
| `start` | Entry point for orchestration system |
| `orchestrated-execution` | 4-phase loop: IMPLEMENT→VALIDATE→REVIEW→COMMIT |
| `plan-review-gate` | Adversarial review of implementation plans |

### Workflow Patterns

- **Simple (1-2 files)**: direct prompting, no orchestration
- **Multi-step (3+ files)**: `@orchestrator {task}`
- **Complex feature**: `@planner {task}` → review plan → `@orchestrator execute`
- **Multiple independent**: `@swarm-coordinator {list}`

### Orchestration Rules

1. Coder must follow TDD (test first, then implement)
2. Orchestrator validates independently (never trust subagent self-reports)
3. Adversarial reviewer is always a FRESH instance
4. Max 3 retries per work unit, then escalate to human
5. Quality gates are BLOCKING — no skipping

## Git Conventions

- Local git worktree development (not yet pushed to GitHub)
- No CI/GitHub Actions configured
- Avoid committing runtime state: `*.db`, `*.sqlite3`, `*.jsonl`, `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, `xmuse/logs/` (all in `.gitignore`)
- Don't `git reset --hard` — worktree may have user goal dirtiness
- 78MB old blobs in history; full cleanup needs `git filter-repo` (confirm with user first)
