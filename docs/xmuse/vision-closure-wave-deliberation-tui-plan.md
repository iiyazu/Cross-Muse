# Vision Closure Wave Deliberation TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Textual TUI into the visible front door for GOD deliberation, blueprint freeze, laneDAG execution, MemoryOS evidence, and GitHub truth.

**Architecture:** Keep durable authority in existing stores, graph sets, review evidence, MemoryOS REST bindings, and GitHub truth captures. Add provider-agnostic read models and focused TUI widgets that render fact levels without writing internal platform state.

**Tech Stack:** Python, Textual, Rich, FastAPI read surfaces, xmuse_core contracts, pytest, ruff, uv.

---

Updated: 2026-06-11

Source report:

```text
C:\tmp\deep-research-report_07.md
/mnt/c/tmp/deep-research-report_07.md
```

The short `/goal` prompt lives in:

```text
docs/xmuse/vision-closure-wave-deliberation-tui-goal-prompt.md
```

## Context

The report's central finding is that xmuse has a strong contract shell, CI gate,
fake/opt-in runtime evidence, baseline TUI, MemoryOS Lite adapter, and GitHub
merge model. The remaining product gap is visibility and live-operable flow:
users still cannot treat the TUI as the primary cockpit for natural GOD
deliberation, blueprint freeze, laneDAG execution, memory trace, and GitHub
truth.

This wave starts after the OpenCode-in evidence closure and PR #42 merge work.
Do not repeat already closed GitHub server-truth capture unless S0 finds the
current repository state differs from recorded evidence.

## Objective

Build one product-facing vision slice:

```text
natural GOD deliberation
-> freeze readiness
-> blueprint / feature / laneDAG drill-down
-> MemoryOS context and trace visibility
-> GitHub checks / review truth / merge fact visibility
```

The result must be usable from the Textual TUI and backed by focused tests. It
must not claim live or server-side truth from local fixtures.

## Non-Goals

- Do not restore or build a browser frontend.
- Do not convert OpenCode into first-class production GOD authority in this
  wave.
- Do not rewrite the chat API, lane planner, review plane, or MemoryOS adapter
  as a broad refactor.
- Do not make TUI cards, `feature_lanes.json`, dashboard projections, or Ray
  actors durable authority.
- Do not require secrets, live services, or GitHub admin mutation in default CI.
- Do not commit runtime state, sqlite/db files, jsonl logs, `feature_lanes.json`,
  `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.

## Proof And Truth Vocabulary

Use these labels consistently in UI, tests, docs, and evidence artifacts:

| Label | Meaning |
| --- | --- |
| `contract_proof` | Local contract or deterministic fixture proves behavior. |
| `fake_runtime_proof` | Fake/local runtime path ran without live services. |
| `live_service_proof` | A live service returned evidence. |
| `server_side_enforcement_proof` | GitHub server-side settings/statuses prove enforcement. |
| `server_side_merge_proof` | GitHub merge event, merge commit, and merged timestamp prove merge fact. |
| `real_provider_proof` | Real provider/Codex/OpenCode/Ray/MCP runtime produced evidence. |
| `manual_gap` | Operator/admin/live evidence is missing or unavailable. |

The TUI may display readiness as readiness. It must not render readiness as a
completed fact. In particular, `merge_ready` and `pr_merged` are different
states.

## File Map

Likely files to modify:

- `xmuse/tui/state.py` - store TUI-visible vision read-model slices in
  `AppState`.
- `xmuse/tui/adapter/xmuse_adapter.py` - poll and assemble TUI read-model
  deltas from existing contracts and stores.
- `xmuse/tui/screens/chat_screen.py` - compose cockpit widgets and route
  selected lane/message/card detail.
- `xmuse/tui/screens/provider_board.py` - evolve provider inventory into GOD
  runtime overview.
- `xmuse/tui/screens/feature_board.py` - expose feature/laneDAG readiness and
  blockers.
- `xmuse/tui/screens/lane_detail.py` - show lane gate/review/patch-forward
  lineage.
- `xmuse/tui/widgets/dag_tree.py` - render dependency and gate relationships
  without layout shifts.

Likely files to create:

- `src/xmuse_core/platform/tui_vision_read_model.py` - provider-agnostic read
  model builder for deliberation, freeze, execution, memory, and GitHub truth.
- `xmuse/tui/widgets/deliberation_cockpit.py` - speech-act and blocker panel.
- `xmuse/tui/widgets/blueprint_freeze_panel.py` - freeze readiness panel.
- `xmuse/tui/widgets/execution_cockpit.py` - laneDAG / review / patch-forward
  summary panel.
- `xmuse/tui/widgets/memory_trace_drawer.py` - MemoryOS session/context/trace
  panel.
- `xmuse/tui/widgets/github_truth_panel.py` - checks/review/manual_gap/merge fact
  panel.
- `docs/xmuse/vision-closure-wave-deliberation-tui-walkthrough.md` - replay or
  walkthrough artifact produced by this wave.

Likely tests:

- `tests/xmuse/test_tui_vision_read_model.py`
- `tests/xmuse/test_tui_vision_widgets.py`
- `tests/xmuse/test_tui_state.py`
- `tests/xmuse/test_tui_adapter.py`
- `tests/xmuse/test_tui_navigation.py`
- `tests/xmuse/test_deliberation_protocol_v2.py`
- `tests/xmuse/test_blueprint_lane_dag_service.py`
- `tests/xmuse/test_memoryos_lite_interop.py`
- `tests/xmuse/test_github_server_truth_capture.py`

## Work Packages

### S0 - Current-State Truth Map

Goal: confirm current code/docs evidence before implementation.

- [ ] Read `docs/xmuse/README.md`, `docs/xmuse/mainline-contracts.md`,
  `docs/xmuse/vision-runtime-evidence-closure.md`,
  `docs/xmuse/memoryos-lite-runtime-compatibility.md`,
  `docs/xmuse/github-server-side-gate.md`, and this plan.
- [ ] Inspect `xmuse/tui/state.py`, `xmuse/tui/adapter/xmuse_adapter.py`,
  `xmuse/tui/screens/chat_screen.py`, `xmuse/tui/screens/provider_board.py`,
  and existing `tests/xmuse/test_tui_*`.
- [ ] Record which GitHub truth, MemoryOS trace, and provider runtime facts are
  currently proven, contract-only, or `manual_gap`.
- [ ] If report assumptions are stale, update this plan or the follow-on
  walkthrough before changing product behavior.

Acceptance:

- Current-state map exists in the stage result or walkthrough artifact.
- No behavior changes are made in S0.
- Already closed GitHub truth work is not duplicated.

### S1 - TUI Vision Read Model

Goal: add a single provider-agnostic read model for the five vision planes.

- [ ] Write failing tests in `tests/xmuse/test_tui_vision_read_model.py` for:
  deliberation summary, freeze readiness, laneDAG summary, MemoryOS trace
  summary, and GitHub truth summary.
- [ ] Create `src/xmuse_core/platform/tui_vision_read_model.py`.
- [ ] Add dataclasses or Pydantic-compatible plain dictionaries that preserve:
  `proof_level`, `fact_state`, `source_refs`, `blockers`, `target_refs`, and
  `manual_gap_reason`.
- [ ] Update `xmuse/tui/adapter/xmuse_adapter.py` so `StateDelta` can carry the
  vision read model without making the TUI a write authority.
- [ ] Update `xmuse/tui/state.py` so `AppState.apply()` stores the latest vision
  read model.

Acceptance:

- Read-model tests pass.
- Existing `StateDelta` tests still pass.
- No `xmuse_core` import from runtime `xmuse/`.

### S2 - Deliberation Cockpit

Goal: render natural deliberation semantics instead of only a message stream.

- [ ] Write widget tests for speech-act rendering and unresolved blockers.
- [ ] Create `xmuse/tui/widgets/deliberation_cockpit.py`.
- [ ] Render `propose`, `ask`, `challenge`, `object`, `vote`, `decide`,
  `handoff`, `evidence`, and `retract` when present.
- [ ] Show target refs and source refs as compact text, not hidden payload.
- [ ] Show blocking objections and unresolved questions separately from normal
  chat messages.
- [ ] Integrate the widget into `xmuse/tui/screens/chat_screen.py` without
  growing business logic inside the screen.

Acceptance:

- The TUI can show who challenged whom and why.
- Blocking objections are visible without opening raw JSON.
- Deterministic contract fixtures are not labeled as natural live transcript
  proof.

### S3 - Blueprint Freeze Panel

Goal: make freeze readiness and blockers visible.

- [ ] Write tests proving the panel distinguishes `ready_to_freeze`, `frozen`,
  and `blocked`.
- [ ] Create `xmuse/tui/widgets/blueprint_freeze_panel.py`.
- [ ] Display blueprint revision, decision scope, source refs, votes,
  unresolved blockers, and freeze timestamp when available.
- [ ] Show `manual_gap` when live/natural transcript evidence is absent.
- [ ] Add navigation from deliberation detail to freeze panel when source refs
  connect them.

Acceptance:

- The user can see why the blueprint can or cannot freeze.
- The panel never treats readiness as an already frozen blueprint.

### S4 - Execution Cockpit And LaneDAG Drill-Down

Goal: connect frozen blueprint state to feature/lane/laneDAG execution views.

- [ ] Write tests for laneDAG summary, gate predecessor display, review state,
  and patch-forward lineage.
- [ ] Create `xmuse/tui/widgets/execution_cockpit.py`.
- [ ] Update `xmuse/tui/widgets/dag_tree.py` only for rendering support, not
  authority changes.
- [ ] Update `xmuse/tui/screens/feature_board.py` and
  `xmuse/tui/screens/lane_detail.py` to show laneDAG, gates, review, and
  patch-forward facts.
- [ ] Keep `feature_lanes.json` as projection/queue only.

Acceptance:

- The TUI can drill from feature to lane to gate/review lineage.
- Gate lanes and serialized touched areas remain visible.
- Review readiness and merge readiness stay separate.

### S5 - Memory Trace Drawer

Goal: expose MemoryOS Lite evidence without making live services mandatory.

- [ ] Write tests for fake/default MemoryOS trace display.
- [ ] Create `xmuse/tui/widgets/memory_trace_drawer.py`.
- [ ] Display session binding, namespace, trace availability, pinned core,
  retrieved pages, dropped pages, source refs, and proof level when available.
- [ ] Display `manual_gap` when live trace is missing.
- [ ] Preserve REST-first MemoryOS boundary and namespace/session binding
  semantics.

Acceptance:

- Default tests do not call live MemoryOS Lite.
- The TUI distinguishes fake/default evidence from live trace proof.
- Package boundary tests still prove `xmuse_core` does not import
  `memoryos_lite`.

### S6 - GitHub Truth Panel

Goal: expose check/review/merge fact levels precisely.

- [ ] Write tests for check status, internal review artifact, server-side
  branch protection truth, manual gaps, and merge fact display.
- [ ] Create `xmuse/tui/widgets/github_truth_panel.py`.
- [ ] Display required checks, internal review truth, server-side enforcement
  proof, merge commit SHA, merged timestamp, and gap reason when present.
- [ ] Render `merge_readiness` separately from `pr_merged`.
- [ ] Use existing GitHub truth capture contracts where available.

Acceptance:

- The TUI never renders local/fake readiness as a real merge.
- PR merge fact requires server-side merge evidence.
- Server-side gaps remain visible as gaps.

### S7 - GOD Runtime Overview

Goal: make provider/runtime/session state visible as GOD operating state.

- [ ] Write tests for provider/runtime rows with provider id, runtime kind,
  transport, session continuity, heartbeat, backlog, and waiting reason.
- [ ] Update `xmuse/tui/screens/provider_board.py`.
- [ ] Preserve current provider inventory behavior when runtime state is
  unavailable.
- [ ] Show OpenCode as bounded/secondary unless future evidence proves a
  stronger role.

Acceptance:

- Provider Board becomes a GOD runtime overview.
- Codex production boundary and OpenCode bounded-worker boundary stay explicit.
- Missing runtime evidence is rendered as `manual_gap`, not hidden.

### S8 - Walkthrough, Docs, And Final Validation

Goal: leave a complete audit trail for this wave.

- [ ] Create `docs/xmuse/vision-closure-wave-deliberation-tui-walkthrough.md`.
- [ ] Update `docs/xmuse/README.md` with the new plan, prompt, and walkthrough.
- [ ] Record what is proven, contract-only, live, server-side, real-provider, or
  `manual_gap`.
- [ ] Run focused tests for every changed surface.
- [ ] Run final lint.

Required validation:

```bash
uv run pytest tests/xmuse/test_tui_vision_read_model.py tests/xmuse/test_tui_vision_widgets.py -q
uv run pytest tests/xmuse/test_tui_state.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_navigation.py -q
uv run pytest tests/xmuse/test_deliberation_protocol_v2.py tests/xmuse/test_blueprint_lane_dag_service.py tests/xmuse/test_memoryos_lite_interop.py tests/xmuse/test_github_server_truth_capture.py -q
uv run ruff check .
```

Acceptance:

- Walkthrough links TUI visible state to source evidence.
- Docs do not claim live/server-side/real-provider proof unless captured.
- Final response includes changed files, validation output, proof-level changes,
  remaining manual gaps, and next recommended iteration.

## Behavior Rules

### Planning And Execution

- Start every implementation session by reading this plan and the current
  `AGENTS.md`.
- Use `uv run` for pytest, ruff, mypy, and project scripts.
- Prefer vertical slices: read model, widget/screen, tests, docs.
- Do not add broad abstractions unless a slice needs them.
- Do not inflate `chat_screen.py` with new business logic. Put reusable display
  logic in widgets or read-model helpers.
- Use focused tests before implementation for each behavior change.
- Use fresh review for completed behavior changes before merge.

### Authority Boundaries

- Durable authority remains in graph sets, stores, review artifacts, MemoryOS
  REST evidence, and GitHub server truth.
- TUI, dashboard cards, `feature_lanes.json`, and runtime health views are
  projections.
- LangGraph and Ray may orchestrate runtime flow but must not become lane status
  authority.
- `xmuse/` imports may use `xmuse_core.*`; `xmuse_core` must not import runtime
  `xmuse/`.
- `xmuse/__init__.py` must not exist.

### Proof Discipline

- Label every visible evidence claim with the strongest proven level and no
  stronger.
- Use `manual_gap` when operator/admin/live evidence is missing.
- Do not describe deterministic fixtures as natural multi-GOD proof.
- Do not describe fake/default MemoryOS tests as live MemoryOS proof.
- Do not describe GitHub readiness or local checks as merge fact.
- Reserve `pr_merged` display for server-side merge evidence.

### MemoryOS Rules

- Keep MemoryOS Lite REST-first.
- Do not import `memoryos_lite` from `xmuse_core`.
- Preserve namespace/session binding semantics.
- Default tests must not require live MemoryOS Lite.
- Live evidence, when available, must be opt-in and clearly labeled.

### Provider Rules

- Codex remains the current production groupchat GOD provider boundary.
- OpenCode remains secondary/bounded unless a future plan proves persistent
  session, MCP/writeback semantics, and peer deliberation evidence.
- Provider UI must be provider-agnostic so future peer-GOD promotion is possible
  without rewriting the TUI surface.

### Git Rules

- Do not use `git reset --hard` or destructive checkout commands.
- Preserve unrelated worktree changes.
- Do not commit runtime artifacts or ignored state.
- Keep changes scoped to this wave.

## Final Done Criteria

This wave is complete only when:

- The TUI shows deliberation, freeze readiness, laneDAG execution, memory trace,
  GitHub truth, and provider runtime state.
- Each panel distinguishes fact, readiness, contract proof, fake proof, live
  proof, server-side proof, real-provider proof, and manual gaps.
- Focused tests and lint pass.
- Docs and walkthrough are updated.
- Remaining gaps are named with owner and next action.
