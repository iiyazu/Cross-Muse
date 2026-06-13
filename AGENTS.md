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
uv run xmuse-goal-stage-evidence-capture  # Goal stage result replay evidence
uv run xmuse-god-runtime-continuity-capture  # Selected-GOD runtime continuity artifact
uv run xmuse-god-session-heartbeat  # Guarded GOD session heartbeat update
uv run xmuse-internal-review-gate-capture  # Internal review release gate
uv run xmuse-memoryos-live-gate-capture  # MemoryOS Lite live release gate
uv run xmuse-mcp-server        # MCP-over-HTTP server (FastAPI)
uv run xmuse-platform-runner   # Platform orchestrator
uv run xmuse-live-gate-status-capture  # Live-gate status artifacts
uv run xmuse-natural-deliberation-gate-capture  # Natural GOD transcript release gate
uv run xmuse-overnight-supervisor  # Overnight supervisor snapshot runner
uv run xmuse-release-readiness-capture  # Redacted release-readiness report
uv run xmuse-proof-contamination-audit  # Release proof contamination audit
uv run xmuse-real-provider-runtime-gate-capture  # Real provider runtime release gate
uv run xmuse-tui               # Textual TUI
```

Or directly:
```bash
uv run python xmuse/chat_api.py
uv run python -m xmuse.tui
uv run python xmuse/goal_stage_evidence_capture.py
uv run python xmuse/god_runtime_continuity_capture.py
uv run python xmuse/god_session_heartbeat.py
uv run python xmuse/platform_runner.py
uv run python xmuse/internal_review_gate_capture.py
uv run python xmuse/memoryos_live_gate_capture.py
uv run python xmuse/live_gate_status_capture.py
uv run python xmuse/natural_deliberation_gate_capture.py
uv run python xmuse/overnight_operator_supervisor.py
uv run python xmuse/release_readiness_capture.py
uv run python xmuse/proof_contamination_audit.py
uv run python xmuse/real_provider_runtime_gate_capture.py
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

## Development Workflow

### Completion Definition

A task is complete only when:

1. The requested behavior is implemented.
2. Relevant tests pass.
3. Existing nearby behavior remains protected.
4. The diff has been reviewed for regressions, risky patterns, architecture
   boundary violations, and unrelated changes.
5. Any remaining risk or unverified area is reported.

Passing tests alone is not sufficient completion evidence.

### RIGR-V Policy

Use Read → Invariant → Green-by-fix → Refactor → Verify as the default
development loop. Do not start by writing tests before understanding the
system.

Before changing code, state or record:

- Task understanding:
  - User-visible behavior to change
  - Existing code path
  - Existing tests that already cover nearby behavior
  - Risk surface
- Behavior invariants:
  - Existing valid behavior must remain unchanged
  - Error handling, auth, persistence, and compatibility semantics remain
    unchanged unless explicitly requested
- Architecture invariants:
  - Do not change public API unless explicitly required
  - Do not bypass existing abstractions or contract boundaries
  - Do not add special cases for test fixtures

Use TDD when the task changes observable behavior, fixes a bug, or defines a
public contract. Do not force red-first tests for pure docs, comments, config,
mechanical refactors, architecture migration planning, or performance work that
requires benchmarks/profiles instead.

A new failing test is acceptable only when it:

- Fails before the implementation.
- Tests external behavior, public contract, reproduced bug, or a low-level
  library contract.
- Would remain valuable under a different correct implementation.
- Includes boundary or negative coverage when relevant.

### Anti-TDD-Abuse Rules

- Do not modify tests merely to make them pass.
- Do not delete, skip, xfail, or loosen tests without explaining why the old
  test was invalid.
- Do not special-case test fixtures, exact sample values, filenames, or
  test-only inputs in production code.
- Do not mock the behavior under test unless the boundary is external, slow,
  nondeterministic, or unsafe.
- Do not assert private implementation details unless working on a low-level
  internal unit.
- Do not update snapshots without semantic justification.
- Do not add broad integration mocks that bypass authentication,
  authorization, persistence, validation, or contract paths.
- If a test and implementation are both authored in the task, explain why the
  test would catch an alternative wrong implementation.

### Subagent Policy

Use single writer, multiple verifiers:

| Role | Permissions | Task |
|------|-------------|------|
| Main Codex | May write | Final design, production-code changes, final diff, commit, push, PR update |
| explorer subagent | Read-only | Map code paths, existing tests, invariants, and risky files |
| test-designer subagent | Read-only or tests-only | Propose behavior-level tests and overfitting risks |
| reviewer subagent | Read-only | Review final diff for regressions, overfitting, public API breakage, architecture boundary violations, excessive mocks, swallowed errors, missing negative tests, and unrelated edits |
| docs/api subagent | Read-only + docs tools | Verify framework/API behavior from primary docs instead of memory |

Do not let the same worker context write tests, write production implementation,
and self-certify completion without independent review. The main Codex remains
the only final production-code writer unless the user explicitly delegates
bounded implementation work.

Before claiming completion, answer these checks in the final review:

1. What real requirement did the new failing test prove?
2. Could the implementation be fitting only the test example?
3. Were any tests modified, deleted, weakened, skipped, or xfailed?
4. Was the real path under test mocked away?
5. What evidence besides green tests shows the behavior is correct?

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

For Codex development `/goal` work, use
`docs/xmuse/development-goal-worker-delegation-policy.md` as the canonical
OpenCode worker delegation policy. Do not repeat that policy in every goal
prompt; reference it unless the policy itself is being changed.

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

1. Coder and Codex must follow the RIGR-V policy above. TDD is required for
   bug fixes, public contracts, and behavior changes, but must not be forced
   onto docs-only, config-only, pure refactor, performance, or architecture
   migration work where other evidence is more appropriate
2. Orchestrator validates independently (never trust subagent self-reports)
3. Adversarial reviewer is always a FRESH instance
4. Repeated failures require direct refactor: after two same-class failures on
   a feature/stage/test cluster/runtime path, stop patch stacking and make the
   next action a bounded root-cause/refactor or replacement of the failed
   boundary. A third same-boundary retry is allowed only after that refactor
   artifact exists with migration, focused tests, and rollback/compatibility
   notes
5. Quality gates are BLOCKING — no skipping
6. Demo-grade implementations on the production path must be isolated or
   replaced with contract-backed production implementations, not wrapped to make
   gates appear green

## Git Conventions

- This worktree may already be pushed and may have an open PR; verify current
  branch, remote, PR, and CI state with `git status`, `git branch -vv`, `gh pr
  view`, and `gh run list` instead of relying on this file for live facts
- GitHub Actions may be configured; if pushing, update the PR body and inspect
  the latest Actions run for the pushed head
- Avoid committing runtime state: `*.db`, `*.sqlite3`, `*.jsonl`, `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, `xmuse/logs/` (all in `.gitignore`)
- Don't `git reset --hard` — worktree may have user goal dirtiness
- 78MB old blobs in history; full cleanup needs `git filter-repo` (confirm with user first)
