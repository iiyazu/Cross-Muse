# Vision Closure Wave Deliberation TUI Walkthrough

Updated: 2026-06-11

This artifact records the first implementation wave for the Deliberation TUI
vision closure plan.

It does not claim full xmuse vision closure. It records the new TUI-visible
read-model and panel surfaces, and keeps live/server-side/real-provider proof
separate from local contract evidence.

## Implemented Path

This wave adds a TUI projection for:

```text
GOD deliberation
-> blueprint freeze readiness
-> feature/lane/laneDAG execution
-> MemoryOS trace visibility
-> GitHub truth visibility
-> provider/GOD runtime overview
```

The projection is built by:

```text
src/xmuse_core/platform/tui_vision_read_model.py
```

and carried through:

```text
xmuse/tui/adapter/xmuse_adapter.py
xmuse/tui/state.py
xmuse/tui/screens/chat_screen.py
```

## S0 Current-State Truth Map

Current proven facts:

- Mainline contract authority remains:
  `chat.db` deliberation envelopes, frozen blueprint revisions, graph/lane
  stores, review evidence, GitHub truth captures, and MemoryOS REST evidence.
- TUI, dashboard cards, `feature_lanes.json`, and runtime health are
  projections.
- Default CI and local focused tests remain no-secrets and no-live-service.
- MemoryOS Lite compatibility remains REST-first.
- GitHub `pr_merged` remains reserved for server-side merge evidence.

Current contract/fake proof:

- Structured speech-act projections can display `propose`, `ask`, `challenge`,
  `object`, `vote`, `decide`, `handoff`, `evidence`, and `retract`.
- Blueprint freeze readiness can be rendered without presenting readiness as an
  already frozen blueprint.
- LaneDAG projection can show lane count, ready lanes, blocked lanes,
  dependencies, and graph lineage refs.
- MemoryOS trace projection can show live trace fields when supplied, but
  default tests do not call live MemoryOS Lite.
- GitHub truth projection can show merge readiness and merged fact separately.

Current manual gaps:

- No new natural multi-GOD live transcript was captured in this wave.
- No new live MemoryOS Lite service run was captured in this wave.
- No new real provider/Ray/Codex/OpenCode runtime soak was captured in this
  wave.
- Provider Board shows runtime overview rows when evidence exists, but does not
  itself prove OpenCode peer-GOD equality.

## TUI Panels

The Chat screen now renders these right-side vision panels from `state.vision`:

- Deliberation Cockpit:
  `xmuse/tui/widgets/deliberation_cockpit.py`
- Blueprint Freeze:
  `xmuse/tui/widgets/blueprint_freeze_panel.py`
- Execution Cockpit:
  `xmuse/tui/widgets/execution_cockpit.py`
- Memory Trace:
  `xmuse/tui/widgets/memory_trace_drawer.py`
- GitHub Truth:
  `xmuse/tui/widgets/github_truth_panel.py`

Provider Board now renders a GOD runtime overview from provider inventory rows:

```text
xmuse/tui/screens/provider_board.py
```

It includes provider id, boundary role, profile, runtime kind, transport,
session continuity, heartbeat, waiting reason, and proof level.

## Proof-Level Discipline

The TUI read model preserves these levels:

| Surface | Default proof in this wave | Stronger proof still required |
| --- | --- | --- |
| Deliberation | `contract_proof` from structured messages | natural runtime transcript export |
| Blueprint freeze | `contract_proof` readiness/frozen projection | real natural freeze replay |
| Execution | `contract_proof` from worklist/laneDAG projection | real runtime execution evidence |
| MemoryOS | `manual_gap` unless trace evidence supplied | opt-in live MemoryOS Lite trace |
| GitHub | `manual_gap`, `server_side_enforcement_proof`, or `server_side_merge_proof` as supplied | authenticated server-side capture |
| Provider runtime | `manual_gap` unless runtime rows supplied | real provider/session continuity evidence |

The GitHub panel avoids rendering merge readiness as `pr_merged`. A real merged
fact still requires the GitHub truth model to carry server-side merge evidence.

## Validation Run

Focused validation run during implementation and branch finalization:

```bash
uv run pytest tests/xmuse/test_tui_vision_read_model.py tests/xmuse/test_tui_state.py tests/xmuse/test_tui_adapter.py -q
uv run pytest tests/xmuse/test_tui_widgets.py tests/xmuse/test_tui_navigation.py tests/xmuse/test_tui_vision_read_model.py tests/xmuse/test_tui_state.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_screen_integration.py -q
uv run pytest tests/xmuse/test_package_boundaries.py -q
uv run pytest tests/xmuse/test_deliberation_protocol_v2.py tests/xmuse/test_blueprint_lane_dag_service.py tests/xmuse/test_memoryos_lite_interop.py tests/xmuse/test_github_server_truth_capture.py tests/xmuse/test_package_boundaries.py tests/xmuse/test_mainline_contract_docs.py -q
uv run ruff check .
```

Observed results:

```text
47 passed
140 passed, 1 warning
16 passed
38 passed, 1 skipped
All checks passed!
```

The warning is the existing Starlette/httpx deprecation warning surfaced by
FastAPI `TestClient`.

`git diff --check` also passed.

## Next Iteration

The next implementation wave should connect these panels to richer live or
operator-supplied evidence:

- natural multi-GOD transcript export;
- opt-in live MemoryOS Lite trace artifact;
- real provider runtime/session continuity evidence;
- authenticated GitHub server-side truth capture refresh;
- OpenCode peer-GOD promotion only after persistent session and writeback
  semantics are proven.
