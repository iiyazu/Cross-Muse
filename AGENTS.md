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
uv run xmuse-god-room-review-chain-proof-capture  # GOD-room review chain proof artifact
uv run xmuse-god-session-heartbeat  # Guarded GOD session heartbeat update
uv run xmuse-internal-review-gate-capture  # Internal review release gate
uv run xmuse-local-execution-candidate-capture  # Local execution candidate artifact
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
uv run python xmuse/god_room_review_chain_proof_capture.py
uv run python xmuse/god_session_heartbeat.py
uv run python xmuse/platform_runner.py
uv run python xmuse/internal_review_gate_capture.py
uv run python xmuse/local_execution_candidate_capture.py
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

### XMuse Closure Behavior Rules

xmuse development is not test-driven-first. It is dependency-first,
contract-first, authority-first, and evidence-first. Tests are verification,
not architecture authority.

Treat `/goal` as desired state and durable artifacts/status as observed state.
Long-running xmuse work should behave like an idempotent reconcile loop:
declare the target condition, inspect observed durable state, produce or update
the smallest authority-owned artifact, and fail closed to `manual_gap`,
`blocked`, or `refactor_required` when proof is missing.

Before changing code in any `/goal` task, identify:

1. Target closure layer(s), L1-L11, from
   `docs/xmuse/production-closure-gap-ledger.md`.
2. Required upstream layers and blockers.
3. The authority object, durable store, or server truth source that owns truth.
4. The proof level the task can produce:
   `contract_proof`, `local_runtime_proof`, `opt_in_live_proof`,
   `server_side_truth`, or `manual_gap`.
5. Claims that remain forbidden after the change.
6. Stable refs and owner lineage required by the production path, including
   `source_refs`, `target_refs`, authority owner, allowed writer, and inherited
   `forbidden_claims`.

Do not start by writing broad tests against imagined behavior. First inspect
current contracts, stores, APIs, docs, runtime paths, and evidence artifacts.
Then implement the smallest production slice: contract/schema, store or
authority resolver, runtime/API/operator hook, fail-closed handling, evidence
artifact, and ledger update. Add targeted regression or contract tests only
after the authority/proof path is clear.

Never claim:

- TUI/dashboard/read model state is durable authority.
- Provider inventory means a CLI is a peer-GOD.
- Capture proof equals live provider invocation proof.
- Fixture deliberation equals natural multi-GOD deliberation.
- `feature_lanes.json` is execution authority.
- Local tests or worker self-report are review truth.
- CI success is GitHub review or merge truth.
- MemoryOS plan artifact is live MemoryOS trace.
- `ready_for_replay` means `ready_to_merge` or `pr_merged`.

Proof levels may only upgrade when a stronger upstream producer, live trace, or
server API proof exists:

```text
manual_gap -> contract_proof -> local_runtime_proof -> opt_in_live_proof -> server_side_truth
```

`forbidden_claims` are append-only guardrails. Carry them forward unless a
matching upstream proof explicitly removes one. Do not remove `ready_to_merge`,
`pr_merged`, `github_review_truth`, `live_memoryos`, or
`worker_output_is_review_truth` to make an evidence surface look complete.

Closure artifacts and status records must be machine-readable and scoped.
Prefer refs like `lane:{lane_id}`, `internal_review:{review_id}`, and
`god-room-review-closure:{graph_id}:{failed_lane_id}:{terminal_lane_id}`.
Opaque strings, pane ids, provider sessions, TUI row ids, and human summaries
are not closure authority. Missing owner lineage means candidate evidence or
`manual_gap`, not truth.

Before declaring completion, self-review:

1. Did this change only modify downstream projection while upstream authority
   remains missing?
2. Did tests pass by mocking away the real production gap?
3. Did any missing live/server proof get downgraded into contract proof?
4. Is `manual_gap` preserved when live proof is unavailable?
5. Was the closure ledger updated with current branch/head/PR/CI facts where
   claims changed?

Test budget gate: a `/goal` is TDD-abusive if tests define closure before
production authority is identified, tests construct artifacts that production
runtime should produce, mocks bypass selected GOD binding/provider invocation/
recovery enforcement/review truth, fields are added to evidence packs without
upstream producers, or TUI/read models expand without fail-closed authority
checks. It is also TDD-abusive if tests assert desired closure directly instead
of observed durable artifacts/status, pass by omitting inherited
`forbidden_claims`, or verify candidate artifacts without an independent verdict
that cites them before review truth is claimed. If detected, stop adding tests,
identify the missing production producer, and implement or document the smallest
real path/manual gap. The canonical policy is
`docs/xmuse/anti-tdd-abuse-policy.md`.

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

1. What real requirement did any new targeted test prove?
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

For long `/goal` work, read `docs/xmuse/goal-behavior-contract.md`,
`docs/xmuse/anti-tdd-abuse-policy.md`, `docs/xmuse/code-review.md`,
`docs/xmuse/github-git-behavior-policy.md`,
`docs/xmuse/production-closure-gap-ledger.md`,
`docs/xmuse/development-goal-worker-delegation-policy.md`, and
`docs/xmuse/goal-stage-harness.md`.

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

1. Coder and Codex must follow the XMuse closure behavior rules above and
   `docs/xmuse/goal-behavior-contract.md`. Targeted tests are required for bug
   fixes, public contracts, and behavior changes, but tests must not define
   architecture or substitute for authority/proof producers
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
- Follow `docs/xmuse/github-git-behavior-policy.md`: prefer small scoped PRs,
  do not use PR #43 as the default sink for future `/goal` work, and do not push
  into PR #43 unless explicitly instructed
- GitHub Actions may be configured; if pushing, update the PR body and inspect
  the latest Actions run for the pushed head
- CI success is not GitHub review truth, merge truth, `ready_to_merge`, or
  `pr_merged`
- Avoid committing runtime state: `*.db`, `*.sqlite3`, `*.jsonl`, `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, `xmuse/logs/` (all in `.gitignore`)
- Don't `git reset --hard` — worktree may have user goal dirtiness
- 78MB old blobs in history; full cleanup needs `git filter-repo` (confirm with user first)
