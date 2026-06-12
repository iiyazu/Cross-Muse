# Vision Operator-Closed Overnight Loop Walkthrough

Updated: 2026-06-12

This artifact records the first implementation slice for the operator-closed
overnight loop plan. It does not claim full xmuse vision closure, a real 8 hour
runtime soak, or live/provider/server-side proof.

## Implemented Path

This run adds a contract-level operator loop spine:

```text
TUI slash command
-> adapter evidence action
-> core evidence action result
-> ignored runtime artifact when exporting transcript
-> laneDAG drill-down display
-> supervisor checkpoint/manual_gap contract
```

The new core modules are:

```text
src/xmuse_core/platform/operator_evidence_actions.py
src/xmuse_core/platform/overnight_operator_supervisor.py
```

The TUI entry point is:

```text
/evidence <transcript|github|memory|blockers>
```

## S0 Current-State Truth Map

Confirmed starting facts during this run:

- Current branch: `vision-closure-deliberation-tui`.
- The checkout is a normal repo checkout, not a linked git worktree.
- Existing uncommitted docs from the handoff were preserved.
- `xmuse/__init__.py` remains absent.
- TUI, dashboard cards, `feature_lanes.json`, and runtime health remain
  projections, not authority.
- Default validation remains no-secrets and no-live-service.

## Evidence Actions

`operator_evidence_actions.py` defines a shared result shape with:

- action name;
- status: `ok`, `partial`, or `manual_gap`;
- proof level;
- fact state;
- source refs;
- target refs;
- artifact path;
- manual gap reason;
- timestamp;
- structured payload.

The transcript exporter preserves structured message evidence:

- `god_id`;
- `provider_id`;
- speech act;
- decision scope;
- source refs;
- target refs;
- blocker state;
- created timestamp.

When no structured deliberation messages exist, it returns `manual_gap` and does
not create a transcript artifact.

Adapter-level exports write runtime artifacts under:

```text
xmuse/work/operator_evidence/<conversation_id>/transcript.json
```

That path is ignored runtime state and is not a committed evidence source by
itself.

## TUI Actuation

`xmuse/tui/slash_commands.py` now exposes:

```text
/evidence transcript
/evidence github
/evidence memory
/evidence blockers
```

The command displays the action result as proof/status/fact text. It does not
upgrade evidence. For example, GitHub readiness remains `merge_ready` when the
underlying model says readiness, and MemoryOS remains `manual_gap` when no trace
exists.

## LaneDAG Drill-Down

The right-panel workbench formatter and full lane detail screen now render more
operator-relevant lane facts when supplied by the existing projection/detail
contracts:

- dependencies;
- gate predecessors;
- touched areas;
- source refs;
- merge blockers;
- review decision/verdict;
- patch-forward lineage.

`feature_lanes.json` is still treated as projection/queue only.

## Overnight Supervisor Contract

`overnight_operator_supervisor.py` adds a file-backed supervisor harness for
tests and future runtime integration. It records:

- heartbeat;
- stage journal;
- checkpoint metadata;
- validation commands;
- issue discovery queue;
- failure classification;
- resume metadata loaded from persisted snapshot;
- stage completion;
- `manual_gap` artifacts;
- move-to-next-stage behavior.

The tests simulate stage transitions, checkpoint/resume, issue discovery,
failure classification, and blocked fallback. They do not run for 8 real hours.

`uv run xmuse-overnight-supervisor` now provides a scriptable operator entry
point for the same supervisor snapshot. It records start-stage, heartbeat,
checkpoint, manual-gap, complete-stage, next-stage, and snapshot actions through
the existing contract object, so long `/goal` runs can persist progress without
editing projections or lane status directly.

## Opt-In Live Soak Boundary

The supervisor exposes a live soak plan helper that requires explicit opt-in
environment flags before a target is considered enabled. Missing flags produce
`manual_gap` entries instead of blocking the whole wave.

No live run was captured in this slice.

Current manual gaps:

- no new natural multi-GOD live transcript;
- no live MemoryOS Lite service trace;
- no real provider/Ray/Codex/OpenCode runtime soak;
- no authenticated GitHub server-side truth refresh;
- no proof that OpenCode is peer-GOD production authority.

## Proof-Level Summary

| Surface | Current proof from this slice | Boundary |
| --- | --- | --- |
| Evidence action contract | `contract_proof` | Pure local tests prove result shape and proof preservation. |
| Transcript export | `contract_proof` | Exports structured stored messages; no natural live transcript captured. |
| GitHub evidence action | `contract_proof` | Loads existing read-model truth without upgrading readiness to merge fact. |
| Memory evidence action | `contract_proof` | Loads existing read-model trace or returns `manual_gap`. |
| Blocker navigation | `contract_proof` | Returns target refs from projections; does not write authority state. |
| LaneDAG drill-down | `contract_proof` | Displays supplied projection/detail fields. |
| Overnight supervisor | `contract_proof` | Simulated heartbeat/checkpoint/manual_gap behavior. |
| Live soak | `manual_gap` unless opt-in flags and evidence exist | No live service/provider proof captured. |

## Focused Validation

Focused tests run during the implementation slice:

```bash
uv run pytest tests/xmuse/test_operator_evidence_actions.py tests/xmuse/test_overnight_operator_supervisor.py -q
uv run pytest tests/xmuse/test_tui_adapter.py::test_adapter_operator_evidence_action_exports_transcript_artifact tests/xmuse/test_tui_adapter.py::test_adapter_operator_evidence_action_loads_github_memory_and_blockers tests/xmuse/test_tui_navigation.py::test_chat_screen_help_command_lists_slash_commands tests/xmuse/test_tui_navigation.py::test_chat_screen_evidence_command_runs_operator_action -q
uv run pytest tests/xmuse/test_tui_navigation.py::test_chat_screen_right_panel_shows_workbench_lists_and_detail_surfaces tests/xmuse/test_tui_navigation.py::test_lane_detail_screen_uses_workbench_detail_contract -q
```

Observed focused results:

```text
9 passed
4 passed, 1 warning
2 passed, 1 warning
```

The warning is the existing Starlette/httpx deprecation warning surfaced by
FastAPI `TestClient`.

## Review Boundary

Two attempts to dispatch a fresh read-only reviewer timed out before returning
findings. A local requirement audit then found one real gap: the first
supervisor slice lacked explicit issue queue, failure classification, and
resume loading. That gap was fixed before final validation.

## Next Work

Recommended next implementation slices:

1. Connect supervisor snapshots to a real long-running command entry point.
2. Add a committed redacted evidence pack format for selected runtime artifacts.
3. Add opt-in collectors for live MemoryOS Lite and GitHub server truth.
4. Route blocker navigation targets directly to feature/lane/detail screens.
5. Capture a real provider/session heartbeat before changing provider boundary
   claims.
