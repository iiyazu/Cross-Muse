# Deep Research Conversion Roadmap

Date: 2026-06-10

Source report: `C:\tmp\deep-research-report.md`

This document converts the deep research report into an executable xmuse roadmap. The
report's central conclusion is that xmuse should evolve from a center-driven peer
scheduler plus concept artifacts into:

```text
logical decentralized deliberation plane
-> frozen artifact pipeline
-> centralized execution/review plane
-> GitHub review workflow
-> REST-first MemoryOS integration
-> auth/RBAC/schema hardening
```

## Operating Decisions

1. Treat "decentralized" as a logical deliberation protocol first, not a physical
   distributed transport.
2. Keep execution centralized: GOD participants deliberate, challenge, vote, route,
   freeze, and review; bounded subagents write code in isolated worktrees.
3. Keep Codex as the primary persistent GOD provider. Keep OpenCode as a bounded worker
   until it gains persistent/MCP parity.
4. Integrate MemoryOS REST-first. Do not expose memory through MCP until auth, tenant
   boundaries, and RBAC are in place.
5. Prefer feature-level Draft PRs with required checks and evidence bundles over one PR
   per lane.

## Milestones

| ID | Name | Goal | Estimate |
|---|---|---|---:|
| M1 | Protocol and artifact contracts | Freeze message, blueprint, lane, verdict, and artifact versioning contracts | 2-3 person-weeks |
| M2 | Deliberation freeze MVP | Multiple GOD participants can challenge, vote, commit, and freeze a blueprint | 3-4 person-weeks |
| M3 | Blueprint to laneDAG planner | Convert an approved blueprint into feature plan and lane graph with deterministic validation | 3-5 person-weeks |
| M4 | Subagent GitHub workflow | Run bounded subagents through worktrees, Draft PRs, checks, and review evidence | 4-6 person-weeks |
| M5 | MemoryOS REST integration | Inject GOD memory context and write back key events with namespace isolation | 3-4 person-weeks |
| M6 | Production hardening | Add auth, RBAC, schema migrations, retention, SLOs, and GitHub App readiness | 4-6 person-weeks |

## M1: Protocol And Artifact Contracts

Target modules:

- `src/xmuse_core/chat/protocol_v2.py`
- `src/xmuse_core/structuring/mission_blueprint_v1.py`
- existing `src/xmuse_core/structuring/models.py`
- existing `src/xmuse_core/chat/models.py`

Deliverables:

- `DeliberationMessageV1` schema with `msg_id`, `conversation_id`, `agent_id`,
  `lamport_ts`, `kind`, `parent_id`, `target_ref`, `mentions`, `payload`,
  `source_refs`, `objection_level`, and `decision_scope`.
- `MissionBlueprintV1` schema with `blueprint_id`, `conversation_id`, `revision`,
  `goal`, `scope`, `constraints`, `non_goals`, `acceptance_contracts`, `repo_areas`,
  `open_questions`, `decision_log`, `source_refs`, `status`, and `approved_by`.
- Markdown projection for blueprint review.
- Artifact versioning rules and references that connect chat cards to blueprint JSON,
  feature plan, lane graph, PR, and evidence.

Tests:

- Deliberation messages preserve ordering and are idempotent.
- Blueprint revision is immutable and traceable to source chat messages.
- Feature plan `blueprint_refs` cannot reference unavailable blueprint refs.
- Markdown projection is deterministic.

## M2: Deliberation Freeze MVP

Target modules:

- `src/xmuse_core/chat/deliberation_engine.py`
- `src/xmuse_core/chat/peer_service.py`
- `xmuse/chat_api.py`

Deliverables:

- Objection/challenge/vote/commit/freeze protocol.
- Bounded objection window.
- Freeze guard: unresolved blocking challenge prevents freeze.
- Audit trail for proposal, challenge, vote, commit, and freeze events.
- Minimal APIs:
  - `POST /api/chat/conversations/{id}/deliberations`
  - `POST /api/chat/conversations/{id}/freeze-blueprint`

Tests:

- Challenge without response blocks freeze.
- Non-blocking objections can be carried into blueprint open questions.
- Duplicate vote/commit events are idempotent.
- Frozen blueprint emits a durable card/read envelope.

## M3: Blueprint To LaneDAG Planner

Target modules:

- `src/xmuse_core/structuring/lane_planner_v2.py`
- `src/xmuse_core/structuring/area_conflict_index.py`
- existing `src/xmuse_core/structuring/graph_validation.py`
- existing `src/xmuse_core/structuring/feature_graph_builder.py`

Deliverables:

- LLM-first decomposition with deterministic validator/normalizer.
- Feature granularity checks.
- Lane granularity checks.
- Dependency resolution from explicit `depends_on`, touched-area conflicts, and gate
  profiles.
- API surface:
  - `POST /api/blueprints/{id}/plan-features`
  - `POST /api/feature-plans/{id}/build-lanes`

Tests:

- Cycle rejection remains deterministic.
- Same touched area creates a serial edge.
- Gate profile can insert review/check predecessors.
- Planner rejects lanes without acceptance criteria or valid blueprint refs.

## M4: Subagent GitHub Workflow

Target modules:

- `src/xmuse_core/platform/execution/subagent_runtime.py`
- `src/xmuse_core/platform/execution/github_ops.py`
- existing `src/xmuse_core/platform/execution/*`
- existing `src/xmuse_core/platform/orchestrator.py`

Deliverables:

- Subagent runtime contract with `lane_id`, `feature_id`, `worktree_path`,
  `allowed_tools`, `write_scope`, `acceptance_criteria`, `gate_profiles`,
  `base_branch`, `parent_pr`, `source_context_refs`, and `memory_context`.
- Per-lane worktree isolation.
- Write-scope allowlist enforcement.
- Feature-level Draft PR creation and update.
- Required checks and review evidence mirrored back into xmuse.
- PR body template containing blueprint refs, lane refs, acceptance criteria, evidence
  bundle, and memory refs.

Tests:

- Out-of-scope write is rejected.
- Failed worker transitions lane to blocked.
- Review-required fix transitions lane to patch-forward.
- Required checks not passing prevents merge-ready status.

## M5: MemoryOS REST Integration

Target modules:

- `src/xmuse_core/integrations/memoryos_client.py`
- `src/xmuse_core/integrations/memoryos_namespace.py`
- existing `src/xmuse_core/agents/memoryos_client.py` should either delegate to or be
  reconciled with the new integration module.

Deliverables:

- REST client for MemoryOS `ingest`, `build-context`, and `search`.
- Namespace mapping for repo, workspace, conversation, GOD participant, and shared team
  memory.
- Event writeback for proposal accepted, blueprint frozen, feature reworked, review
  verdict finalized, and PR merged.
- Context injection into GOD prompts.

Tests:

- Memory context includes source refs.
- Commit-aligned ingest writes deterministic references.
- Missing MemoryOS service degrades without blocking local fake/demo flows.
- Per-GOD namespace does not leak into shared namespace unless explicitly promoted.

## M6: Production Hardening

Target modules:

- `xmuse/chat_api.py`
- `xmuse/mcp_server.py`
- `src/xmuse_core/platform/mcp_permissions.py`
- stores under `src/xmuse_core/chat/`, `src/xmuse_core/structuring/`, and
  `src/xmuse_core/platform/`

Deliverables:

- Auth layer for Chat API and MCP.
- MCP RBAC and tool permission checks.
- Schema migration strategy for SQLite stores.
- Retention and cleanup daemon for runtime state.
- SLO/metrics targets:
  - blueprint freeze p95 < 90s in PoC environment
  - ready lane dispatch p95 < 5s
  - memory search p95 < 300ms for SQLite PoC scale
  - feature PR cycle p95 < 30m excluding human wait time
- GitHub App migration plan for checks, annotations, and merge operations.

Tests:

- Anonymous write is rejected.
- Role without permission cannot mutate lanes or memory.
- Store migration preserves existing chat and artifact rows.
- Cleanup never deletes durable authority records.

## Cross-Cutting Risks

| Risk | Mitigation |
|---|---|
| Deliberation and execution collapse into one layer | Enforce dual-plane architecture in contracts and tests |
| OpenCode promoted to GOD too early | Keep OpenCode support level secondary until persistent/MCP parity exists |
| Memory drift | Use commit-aligned ingest and source refs for every durable memory page |
| Artifact state remains file-only too long | Allow file-backed PoC, but define metadata DB path before pilot |
| MCP exposed before auth | Keep REST-first internal integration, gate MCP behind RBAC milestone |

## First Execution Batch

The first implementation batch should be limited to M1 and the smallest slice of M2:

1. Add `DeliberationMessageV1` and tests.
2. Add `MissionBlueprintV1` and deterministic Markdown projection.
3. Add freeze guard rules in a pure service with fake stores.
4. Wire minimal Chat API endpoints only after the service tests pass.

This batch intentionally avoids GitHub write automation and MemoryOS integration until
the artifact contracts are stable.
