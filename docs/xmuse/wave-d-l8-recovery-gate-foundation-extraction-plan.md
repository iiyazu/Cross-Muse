# Wave D L8 Recovery Gate Foundation Extraction Plan

更新日期: 2026-06-15

> For agentic workers: follow `docs/xmuse/goal-behavior-contract.md` and
> `docs/xmuse/anti-tdd-abuse-policy.md`. This is dependency-first extraction,
> not test-driven architecture. Tests verify the extracted production path.

**Goal:** Extract Slice 1a into a small branch/worktree:
`wave-d-l8-recovery-gate-foundation`.

**Architecture:** Build on the existing durable recovery dispatch-block reader
already present at HEAD `654b418c52cc1487193561f65e0521a5a82f0452`. Add only
the writer-side recovery artifact foundation and the normal gate-failure
producer. Do not extract review retry, review verdict, merge failure,
platform-runner repair, supervisor, L9, or L10 changes.

**Proof Level:** `contract_proof` / local authority producer proof only.

**Forbidden Claims:** independent review truth, broad live runner enforcement,
server truth, overnight-safe recovery, ready_to_merge, pr_merged.

---

## Preconditions

- Work from a clean branch or worktree based on HEAD
  `654b418c52cc1487193561f65e0521a5a82f0452`, or explicitly mark the future PR
  as stacked if another base is chosen.
- Do not push into PR #43.
- Do not commit runtime state.
- Keep the current heavy dirty branch as source material only.

## Current Dirty-Tree Patch Map

The current heavy branch has multiple recovery producers inside the same large
diff hunk. Do not apply the whole hunk. Use the line map below only as source
material; line numbers may drift after further edits.

Include from `src/xmuse_core/platform/orchestrator_lane_flow.py`:

- line 4: `import json`
- lines 42-48: only
  `LaneFailureEvidence`, `LaneRuntimeBudget`, `evaluate_lane_recovery`
- line 51: `lane_recovery_artifact_path`
- lines 176-181: `build_lane_recovery_dispatch_block_metadata`
- lines 184-292: `_record_gate_failure_recovery_artifact`
- lines 895-918: `_lane_runtime_budget` and `_lane_gate_failure_attempt`
- lines 1007-1038: `_lane_recovery_forbidden_claims`, `_text_list`,
  `_dedupe_texts`, `_relative_artifact_ref`
- line 1146: dispatch reads through
  `build_lane_recovery_dispatch_block_metadata`
- lines 1421-1426: gate-failure transition result plus
  `_record_gate_failure_recovery_artifact(...)`

Include from `tests/xmuse/test_platform_orchestrator.py`:

- lines 28-31: add `load_lane_recovery_decision` import
- lines 377-410 and existing continuation: keep existing
  `test_dispatch_lane_blocks_non_retry_recovery_decision`
- lines 5883-5942:
  `test_gate_failure_writes_retry_recovery_artifact`
- lines 5945-5995 and existing continuation:
  `test_repeated_gate_failure_writes_refactor_required_recovery_artifact`

Exclude from Slice 1a even if adjacent in the same diff:

- `LaneRecoveryDecision` and `LaneRecoveryDecisionType` imports unless they are
  needed by the minimal gate-failure implementation
- `_record_patch_forward_recovery_artifact`
- `record_review_rejection_recovery_artifact`
- `record_review_retry_exhaustion_recovery_artifact`
- `record_review_retry_recovery_artifact`
- `record_merge_failure_recovery_artifact`
- `_lane_review_failure_attempt`
- `_lane_review_retry_exhausted_attempt`
- `_lane_review_retry_failure_attempt`
- `_lane_merge_failure_attempt`
- `_merge_failure_class`
- `_merge_failure_recovery_decision`
- `run_execution_god` provider profile projection cleanup
- `on_lane_reviewed_inner` patch-forward/merge hunks
- all review-retry tests around current lines 9360-9770
- all merge/review/patch-forward tests around current lines 931-1370

## Suggested Extraction Workflow

Do not run `git apply` on the full current diff. The full diff includes later
sub-slices and unrelated cleanup.

Use this workflow after explicit approval to create an isolated workspace:

```bash
git worktree add .worktrees/wave-d-l8-recovery-gate-foundation \
  -b wave-d-l8-recovery-gate-foundation \
  654b418c52cc1487193561f65e0521a5a82f0452
cd .worktrees/wave-d-l8-recovery-gate-foundation
```

Then apply only the Slice 1a source ranges from the heavy worktree. Prefer
manual patching or `git add -p`-style hunk selection over whole-file copying.

Useful read-only source commands from the heavy worktree:

```bash
nl -ba /home/iiyatu/projects/python/xmuse/src/xmuse_core/platform/orchestrator_lane_flow.py \
  | sed -n '1,70p;170,295p;895,918p;1007,1038p;1138,1152p;1418,1428p'

nl -ba /home/iiyatu/projects/python/xmuse/tests/xmuse/test_platform_orchestrator.py \
  | sed -n '20,35p;377,430p;5883,5998p'
```

After extraction, inspect the small branch diff:

```bash
git diff --stat
git diff -- src/xmuse_core/platform/orchestrator_lane_flow.py tests/xmuse/test_platform_orchestrator.py
```

The small branch diff should not mention:

```text
platform_orchestrator_review_retry
platform_orchestrator_review_retry_exhaustion
platform_orchestrator_review_rejection
platform_orchestrator_review_patch_forward
platform_orchestrator_merge_failure
provider_profile_ref
overnight_supervisor_recovery_gate
local_execution_candidate
runner_session
```

## Task 1: Add Recovery Artifact Writer Foundation

**Files:**

- Modify: `src/xmuse_core/platform/orchestrator_lane_flow.py`

Steps:

- [ ] Add imports required by the writer foundation:

```python
import json

from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    LaneFailureEvidence,
    LaneRuntimeBudget,
    evaluate_lane_recovery,
)
from xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts import (
    LaneRecoveryArtifactError,
    lane_recovery_artifact_path,
    load_lane_recovery_decision,
)
```

- [ ] Keep the existing `_lane_recovery_dispatch_block_metadata(...)` behavior.
  It must continue to treat missing recovery artifacts and retry-allowed
  artifacts as non-blocking.

- [ ] Add public wrapper:

```python
def build_lane_recovery_dispatch_block_metadata(
    orchestrator,
    lane: dict[str, Any],
) -> dict[str, Any] | None:
    """Return durable recovery dispatch-block metadata for a lane."""
    return _lane_recovery_dispatch_block_metadata(orchestrator, lane)
```

- [ ] Add shared helpers used by the gate-failure producer:

```python
def _lane_runtime_budget(lane: dict[str, Any]) -> LaneRuntimeBudget:
    budget = lane.get("budget")
    if isinstance(budget, dict):
        try:
            return LaneRuntimeBudget.model_validate(budget)
        except ValueError:
            pass
    return LaneRuntimeBudget(
        source_refs=_dedupe_texts(
            [
                f"lane:{_optional_text(lane.get('feature_id'))}"
                if _optional_text(lane.get("feature_id"))
                else None,
                f"lane_graph:{_lane_graph_id(lane)}" if _lane_graph_id(lane) else None,
            ]
        )
    )


def _lane_gate_failure_attempt(lane: dict[str, Any]) -> int:
    retry_count = lane.get("retry_count")
    if isinstance(retry_count, bool) or not isinstance(retry_count, int):
        return 1
    return max(1, retry_count + 1)


def _lane_recovery_forbidden_claims() -> list[str]:
    return [
        "overnight_safe_recovery",
        "end_to_end_execution_review_closure",
        "worker_output_is_review_truth",
        "ready_to_merge",
        "pr_merged",
    ]


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dedupe_texts(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _relative_artifact_ref(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
```

## Task 2: Add Gate-Failure Recovery Producer

**Files:**

- Modify: `src/xmuse_core/platform/orchestrator_lane_flow.py`

Steps:

- [ ] Add `_record_gate_failure_recovery_artifact(orchestrator, lane)`.
- [ ] On missing `graph_id` or `feature_id`, update lane metadata with:
  `recovery_artifact_status=manual_gap`,
  `recovery_artifact_source_authority=platform_orchestrator_gate_runner`,
  `gate_failure_recovery_artifact_missing_graph_or_lane_id`, and forbidden
  claims from `_lane_recovery_forbidden_claims()`.
- [ ] On graph-bound lanes, write
  `xmuse.god_room_lane_recovery.v1` to `lane_recovery_artifact_path(...)`.
- [ ] Build `source_refs` from `lane:<lane_id>`, `lane_graph:<graph_id>`,
  gate report ref, lane source refs, and budget source refs.
- [ ] Use `evaluate_lane_recovery(...)` with one or more
  `LaneFailureEvidence(failure_class="gate_failed")` records.
- [ ] Persist `proof_level=contract_proof`, manual gaps:
  `live_runner_recovery_enforcement_not_proven`, `review_truth_not_proven`,
  `server_truth_not_proven`, `overnight_safe_recovery_not_proven`.
- [ ] Update lane metadata with `recovery_artifact_status=written`,
  `recovery_artifact_ref`, `recovery_decision`, and `recovery_source_refs`.

Do not add review retry, review rejection, patch-forward, merge-failure,
platform-runner, supervisor, L9, or L10 behavior in this task.

## Task 3: Hook Gate Failure After Durable Transition

**Files:**

- Modify: `src/xmuse_core/platform/orchestrator_lane_flow.py`

Steps:

- [ ] In `on_lane_executed(...)`, keep successful gate behavior unchanged.
- [ ] In the failed gate branch, capture the transition result:

```python
failed_lane = orchestrator._sm.transition(
    lane_id,
    "gate_failed",
    metadata={"gate_passed": False, "failure_reason": "gate_failed"},
)
_record_gate_failure_recovery_artifact(orchestrator, failed_lane or lane)
```

- [ ] Ensure the artifact is written only after the state-machine transition
  succeeds.

## Task 4: Keep Dispatch Reader API Stable

**Files:**

- Modify: `src/xmuse_core/platform/orchestrator_lane_flow.py`

Steps:

- [ ] In `dispatch_lane(...)`, call:

```python
recovery_block = build_lane_recovery_dispatch_block_metadata(orchestrator, lane)
```

- [ ] Preserve existing behavior: retry-allowed recovery decisions do not block
  dispatch; non-retry decisions and invalid artifacts block dispatch with
  manual gaps.

## Task 5: Extract Focused Tests

**Files:**

- Modify: `tests/xmuse/test_platform_orchestrator.py`

Steps:

- [ ] Import `load_lane_recovery_decision` from
  `xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts`.
- [ ] Keep or extract existing test:
  `test_dispatch_lane_blocks_non_retry_recovery_decision`.
- [ ] Add or extract:
  `test_gate_failure_writes_retry_recovery_artifact`.
- [ ] Add or extract:
  `test_repeated_gate_failure_writes_refactor_required_recovery_artifact`.
- [ ] Assertions must cover:
  `source_authority=platform_orchestrator_gate_runner`,
  `proof_level=contract_proof`,
  retry vs `refactor_required` decision,
  `review_truth_not_proven`,
  `worker_output_is_review_truth`, and written lane metadata.

Do not add broad snapshot tests or tests for future review/merge/supervisor
behavior in this PR.

## Validation

Run:

```bash
uv run pytest tests/xmuse/test_platform_orchestrator.py -q -k "gate_failure_writes_retry_recovery_artifact or repeated_gate_failure_writes_refactor_required_recovery_artifact or dispatch_lane_blocks_non_retry_recovery_decision"
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
uv run pytest tests/xmuse/test_package_boundaries.py -q
```

Expected:

- Slice 1a focused tests pass.
- Ruff passes.
- Diff whitespace check passes.
- `xmuse/__init__.py` does not exist.
- Package boundary tests pass.

## Review Checklist

- [ ] No PR #43 push or PR #43 readiness claim.
- [ ] No review truth, server truth, or overnight-safe claim.
- [ ] No feature_lanes.json authority claim.
- [ ] No worker output treated as review truth.
- [ ] No review retry/rejection/merge/supervisor hunks in this slice.
- [ ] No runtime/cache state added.
