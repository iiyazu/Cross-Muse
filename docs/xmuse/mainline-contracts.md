# xmuse Mainline Contracts

This document is the current product-mainline contract for xmuse. It makes the
intended path explicit:

```text
GOD groupchat deliberation
-> frozen blueprint
-> feature/lane/laneDAG
-> centralized execution/review
-> GitHub merge gate
-> REST-first MemoryOS
```

The boundary is deliberate: GOD participants deliberate in a logically
decentralized groupchat until a blueprint is frozen. After freeze, execution is
centralized through feature/lane/laneDAG planning, bounded workers, review
evidence, and GitHub merge gates.

## Authority Rules

| Surface | Authority | Projection / View | Notes |
|---|---|---|---|
| Groupchat deliberation | `chat.db` deliberation envelopes and source refs | compact cards, dashboard/TUI read models | Free-form text is not sufficient authority for execution decisions. |
| Blueprint | frozen `MissionBlueprintV1` revision | Markdown projection and blueprint cards | Freeze is the handoff from deliberation to execution. |
| Feature/lane plan | graph-set / lane graph durable stores | `feature_lanes.json`, dashboard graph state | `feature_lanes.json` is a live queue/projection, not authority. |
| Review | review plane verdict records and evidence bundles | final action cards, dashboard review panes | Patch-forward must retain lineage to the failed lane. |
| GitHub | PR checks, review state, merge decision | xmuse read models and PR body summaries | GitHub is a control plane, not only an archive target. |
| MemoryOS | REST memory refs with namespace and source refs | prompt context blocks and retrieved memory cards | MCP memory writes stay denied until auth/RBAC is proven. |

## Contract Map

| Contract | Current modules | Responsibility | Mainline status |
|---|---|---|---|
| GOD groupchat speech acts | `src/xmuse_core/chat/protocol_v2.py`, `src/xmuse_core/chat/deliberation_engine.py`, `src/xmuse_core/chat/collaboration_*`, `src/xmuse_core/chat/peer_scheduler.py`, `src/xmuse_core/chat/inbox_store.py` | Represent propose/ask/challenge/object/vote/decide/handoff/evidence/retract as structured behavior, create blockers, and preserve causal/source refs. | Active contract, to be expanded by #14. |
| Blueprint arbitration and freeze | `src/xmuse_core/structuring/mission_blueprint_v1.py`, `src/xmuse_core/chat/deliberation_engine.py`, `xmuse/chat_api.py` | Freeze only after quorum and no veto blocker; preserve objections, open questions, and immutable source-traceable revisions. | Active contract, to be hardened by #15. |
| Feature/lane/laneDAG execution | `src/xmuse_core/structuring/lane_planner_v2.py`, `src/xmuse_core/structuring/area_conflict_index.py`, `src/xmuse_core/structuring/graph_store.py`, `src/xmuse_core/platform/orchestrator_lane_flow.py`, `src/xmuse_core/platform/master_loop_lanes.py`, `src/xmuse_core/platform/lane_context.py` | Convert frozen blueprints to features, lanes, typed dependency edges, gate profiles, and dispatchable execution units. | Mainline shell exists, to be unified by #16. |
| Centralized review and patch-forward | `src/xmuse_core/platform/review_plane.py`, `src/xmuse_core/platform/review_evidence_bundle.py`, `src/xmuse_core/platform/review_rework.py`, `src/xmuse_core/platform/final_action_gate.py`, `src/xmuse_core/platform/execution/gate.py` | Ingest verdicts, enforce evidence requirements, create patch-forward lanes, and keep review lineage auditable. | Active execution gate. |
| GitHub review and merge | `src/xmuse_core/platform/execution/github_ops.py`, `src/xmuse_core/platform/execution/subagent_runtime.py`, `src/xmuse_core/platform/review_merge_guards.py` | Render feature/lane PR metadata, block merge-ready without checks/evidence, and align review responsibility with GitHub. | Fake ops contract exists, to be expanded by #17. |
| MemoryOS REST integration | `src/xmuse_core/integrations/memoryos_client.py`, `src/xmuse_core/integrations/memoryos_namespace.py`, `src/xmuse_core/integrations/memoryos_events.py`, `src/xmuse_core/platform/memory_refs.py`, `src/xmuse_core/platform/memory_update_events.py`, `src/xmuse_core/platform/mcp_permissions.py` | Keep memory REST-first, namespace refs by repo/workspace/conversation/GOD/feature/lane, and deny MCP memory writes unless auth/RBAC is enabled. | Adapter contract exists, to be hardened by #18. |

## Mainline Phases

### 1. GOD Groupchat Deliberation

GOD participants discuss requirements, constraints, assumptions, risks, and
evidence in groupchat. The mainline requires structured speech acts so that
active challenge is auditable:

```text
propose | ask | challenge | object | vote | decide | handoff | evidence | retract
```

A challenge or objection is not just text. It must be traceable to a target ref
and must either be resolved, carried into blueprint open questions, or become a
blocking condition.

### 2. Blueprint Freeze

Blueprint freeze is the boundary between decentralized deliberation and
centralized execution. A frozen blueprint is immutable, source-traceable, and
the only valid input to the mainline execution planner.

Freeze must be denied when:

- a veto blocker remains unresolved;
- quorum is not met;
- critical assumptions have no confirmation or objection round;
- acceptance contracts are missing.

### 3. Feature/Lane/LaneDAG Planning

The planner converts a frozen blueprint into a feature set and lanes. The lane
DAG must reject invalid blueprint refs, missing acceptance criteria, and cycles.
Typed dependency edges are:

- `hard_dep`
- `soft_dep`
- `review_dep`
- `artifact_dep`

Lanes become dispatchable only when dependencies and gates allow them.

### 4. Centralized Execution And Review

Subagents execute bounded work. They must receive a serializable runtime
contract with lane id, feature id, worktree path, allowed tools, write scope,
acceptance criteria, gate profiles, source refs, and memory context.

Review verdicts are authoritative only when backed by evidence. Patch-forward
creates a new auditable lane and links it to the failed lane.

Review tasks are durable work items, not stdout interpretations. Once a gated
lane opens a review task and starts a review attempt, the task must move from
`pending` to `in_progress` with `review_attempt_id`, `runner_id`,
`started_at`, provider runtime/model, and any spawn log refs that become
available. Every started review attempt must end in one of:

- `verdict_emitted` for a parseable Review GOD merge/rework verdict;
- `failed_classified` for provider/control failures such as
  `review_no_verdict`, `review_parse_failed`, `review_spawn_failed`,
  `review_timeout`, or `review_non_zero_exit`;
- `interrupted_retryable` for runner shutdown, cancellation, or recoverable
  interruption before a verdict is available.

`feature_lanes.json` may expose the lane status, but the review task terminal
state lives in the review plane store. A runner exit must not leave a started
review task permanently `pending` or `in_progress` without a classified
terminal reason.

### 5. GitHub Merge Gate

GitHub is part of the control plane. A lane/feature PR must carry blueprint,
feature, lane, dependency, memory, gate, review, rollback, and privacy metadata.
Merge-ready status is blocked unless required checks and review evidence are
present.

### 6. REST-First MemoryOS

MemoryOS supplies shared GOD memory through REST contracts. Required namespace
dimensions are:

```text
repo | workspace | god_id | conversation_id | thread_id | blueprint_id | feature_id | lane_id
```

Memory layers are:

```text
pinned_core | task_state | archival
```

LLM paging must support a redaction hook before transcript export. Deleted or
tombstoned source messages must not return as active memory.

## Demo And Legacy Boundaries

Fake groupchat demos, historical master-loop paths, and archived superpowers
plans remain useful for smoke tests and compatibility references. They are not
the product mainline unless they produce or consume the contracts above.

Legacy paths must not bypass:

- blueprint freeze;
- laneDAG validation;
- review evidence;
- GitHub merge gates;
- MemoryOS namespace/RBAC rules.

## Gate Requirements

Every mainline change should keep these gates meaningful:

- `uv run ruff check .`
- focused contract tests for the touched contract surface;
- package boundary tests when runtime/core imports are touched;
- explicit notes for any known broad-suite baseline failures.
