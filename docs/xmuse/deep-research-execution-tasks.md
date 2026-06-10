# Deep Research Execution Tasks

Date: 2026-06-10

This document expands `docs/xmuse/deep-research-conversion-roadmap.md` into
issue-sized execution tasks. It is the task reference for goal prompts that should
stay short while still executing the full deep-research conversion plan.

## Source Of Truth

- Source report: `C:\tmp\deep-research-report.md`
- Roadmap: `docs/xmuse/deep-research-conversion-roadmap.md`
- GitHub repo: `https://github.com/iiyazu/Cross-Muse`
- GitHub issues: #1 through #12

## Execution Rules

1. Work issue by issue. Do not skip ahead to GitHub automation or MemoryOS
   integration before protocol and artifact contracts are stable.
2. Keep "decentralized" as a logical deliberation protocol first. Do not introduce
   physical distributed transport in this batch.
3. Keep execution centralized. GOD participants deliberate, challenge, vote, freeze,
   route, and review; subagents only write within bounded worktrees.
4. Use Codex as the primary persistent GOD provider. Keep OpenCode as a bounded worker.
5. Integrate MemoryOS REST-first. Do not expose memory through MCP until auth/RBAC
   exists.
6. Preserve package boundaries: `xmuse/` has no `__init__.py`; runtime imports
   `xmuse_core.*`; `xmuse_core` must not depend on runtime modules.
7. Use `uv run` for pytest and ruff.
8. Do not commit runtime state: databases, jsonl logs, `feature_lanes.json`,
   `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
9. Each implementation slice needs focused tests, `uv run ruff check .`, and a
   commit that references the relevant issue.
10. Update GitHub issue checklists and notes after each completed slice.

## Phase 0: Baseline Audit

Read:

- `AGENTS.md`
- `docs/xmuse/README.md`
- `docs/xmuse/deep-research-conversion-roadmap.md`
- `pyproject.toml`
- `src/xmuse_core/chat/`
- `src/xmuse_core/structuring/`
- `src/xmuse_core/platform/`
- `xmuse/chat_api.py`

Run:

- `uv run ruff check .`
- `uv run pytest tests/xmuse/test_package_boundaries.py`

Output a short baseline note before making implementation edits.

## Phase 1: M1 Protocol And Artifact Contracts

Issues: #1, #7, #8

Implement `src/xmuse_core/chat/protocol_v2.py`:

- `DeliberationMessageV1`
- stable serialization
- deterministic idempotency key
- kinds: `note`, `challenge`, `proposal`, `vote`, `commit`, `evidence`
- objection levels: `none`, `non_blocking`, `blocking`
- fields: `msg_id`, `conversation_id`, `agent_id`, `lamport_ts`, `kind`,
  `parent_id`, `target_ref`, `mentions`, `payload`, `source_refs`,
  `objection_level`, `decision_scope`

Implement `src/xmuse_core/structuring/mission_blueprint_v1.py`:

- `MissionBlueprintV1`
- deterministic Markdown projection
- frozen revision immutability
- source refs preserved in JSON and Markdown
- fields: `blueprint_id`, `conversation_id`, `revision`, `goal`, `scope`,
  `constraints`, `non_goals`, `acceptance_contracts`, `repo_areas`,
  `open_questions`, `decision_log`, `source_refs`, `status`, `approved_by`

Tests:

- valid and invalid deliberation payloads
- ordering and idempotency
- stable serialization
- blueprint revision immutability
- deterministic Markdown rendering
- empty acceptance contracts rejected
- source refs preserved

## Phase 2: M2 Deliberation Freeze MVP

Issues: #2, #9

Implement `src/xmuse_core/chat/deliberation_engine.py` as a pure service first:

- proposal, challenge, vote, commit, freeze event handling
- bounded objection window
- unresolved blocking challenge prevents freeze
- non-blocking objections become blueprint open questions
- duplicate vote/commit events are idempotent
- structured freeze decision for later Chat API wiring

Then wire minimal APIs:

- `POST /api/chat/conversations/{id}/deliberations`
- `POST /api/chat/conversations/{id}/freeze-blueprint`

Tests:

- blocking challenge without response denies freeze
- resolved blocking challenge allows freeze if quorum is met
- non-blocking objection is carried forward
- duplicate vote/commit is idempotent
- frozen blueprint emits durable card/read evidence

## Phase 3: M3 Blueprint To LaneDAG Planner

Issues: #3, #10

Implement:

- `src/xmuse_core/structuring/lane_planner_v2.py`
- `src/xmuse_core/structuring/area_conflict_index.py`
- deterministic validation shell around future LLM decomposition
- normalized planner input/output contracts

Validators:

- reject lanes without acceptance criteria
- reject invalid blueprint refs
- preserve deterministic cycle rejection
- same touched repo area creates a serial edge
- gate profiles can insert review/check predecessors
- validation errors are renderable in chat/dashboard

## Phase 4: M4 Subagent GitHub Workflow

Issues: #4, #11

Implement:

- `src/xmuse_core/platform/execution/subagent_runtime.py`
- `src/xmuse_core/platform/execution/github_ops.py`
- `SubagentRuntimeContract`
- prompt envelope serialization
- write-scope allowlist validation
- feature-level Draft PR body template
- fake GitHub ops before real write automation

Contract fields:

- `lane_id`, `feature_id`, `worktree_path`, `allowed_tools`, `write_scope`,
  `acceptance_criteria`, `gate_profiles`, `base_branch`, `parent_pr`,
  `source_context_refs`, `memory_context`

Tests:

- valid contract
- invalid path rejected
- missing acceptance criteria rejected
- prompt rendering stable
- PR body includes blueprint refs, lane refs, acceptance criteria, evidence bundle,
  and memory refs

## Phase 5: M5 MemoryOS REST Integration

Issues: #5, #12

Implement:

- `src/xmuse_core/integrations/memoryos_client.py`
- `src/xmuse_core/integrations/memoryos_namespace.py`
- fake client plus REST client protocol for `ingest`, `build_context`, and `search`
- namespace mapping for repo, workspace, conversation, GOD participant, and shared
  memory
- event writeback for proposal accepted, blueprint frozen, feature reworked, review
  verdict finalized, and PR merged
- GOD prompt context injection

Tests:

- namespace isolation
- deterministic source refs
- missing MemoryOS service degrades gracefully
- per-GOD namespace does not leak into shared namespace unless promoted

## Phase 6: M6 Production Hardening

Issue: #6

Implement after Phases 1-5 are stable:

- Chat API auth layer
- MCP RBAC and permission checks
- SQLite schema migration strategy
- runtime retention and cleanup daemon
- metrics/SLO surfaces
- GitHub App migration plan

Tests:

- anonymous write rejected
- unauthorized role cannot mutate lanes or memory
- migration preserves existing rows
- cleanup never deletes durable authority records

## Required Closeout For Each Phase

1. Run targeted tests.
2. Run `uv run ruff check .`.
3. Run broader `uv run pytest` when shared contracts or execution paths changed.
4. Commit with the issue number in the message.
5. Update the relevant GitHub issue and parent checklist.
6. Leave a short summary of completed work, tests, and remaining risk.
