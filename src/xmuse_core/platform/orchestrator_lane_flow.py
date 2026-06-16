"""Lane execution and review flow helpers for PlatformOrchestrator."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from xmuse_core.agents.persistent_peer import fingerprint_prompt
from xmuse_core.observability import log_event, observability_context, timed_core_operation
from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.execution import executor as execution_executor
from xmuse_core.platform.execution import review_god as execution_review_god
from xmuse_core.platform.execution.provider_session_binding import (
    plan_execution_runtime_session_route,
    plan_review_runtime_session_route,
)
from xmuse_core.platform.memory_update_events import (
    build_memory_lesson_for_event,
    find_matching_memory_ref,
    upsert_memory_ref,
)
from xmuse_core.platform.projection.dependents import reproject_dependents_if_needed
from xmuse_core.platform.prompts.builders import (
    build_execution_prompt,
    build_review_prompt,
    build_review_verdict,
)
from xmuse_core.platform.state_machine import InvalidTransitionError
from xmuse_core.platform.verdict_adapter import adapt_review_verdict
from xmuse_core.platform.verdicts.writer import (
    gate_report_ref_for_lane,
    ingest_merge_verdict,
    ingest_rework_verdict,
    stable_verdict_id_for_lane,
)
from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    LaneFailureEvidence,
    LaneRecoveryDecision,
    LaneRecoveryDecisionType,
    LaneRuntimeBudget,
    evaluate_lane_recovery,
)
from xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts import (
    LaneRecoveryArtifactError,
    lane_recovery_artifact_path,
    load_lane_recovery_decision,
)
from xmuse_core.structuring.feature_review_contracts import FeatureGraphExecutionStatus

logger = logging.getLogger(__name__)
WORKTREE_BASE = Path.home() / ".config" / "superpowers" / "worktrees" / "memoryOS"


def _orchestrator_module(orchestrator) -> Any | None:
    return sys.modules.get(type(orchestrator).__module__)


def _compat_symbol(orchestrator, name: str, fallback: Any) -> Any:
    module = _orchestrator_module(orchestrator)
    if module is None:
        return fallback
    return getattr(module, name, fallback)


def _lane_graph_id(lane: dict[str, Any] | None) -> str | None:
    graph_id = lane.get("graph_id") if isinstance(lane, dict) else None
    return str(graph_id) if graph_id else None


def _provider_binding_god_session_id(lane: dict[str, Any] | None) -> str | None:
    if not isinstance(lane, dict):
        return None
    return _optional_text(lane.get("provider_session_binding_god_session_id"))


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _safe_lane_ref(lane_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", lane_id).strip("-") or "lane"


def _graph_native_status_record(orchestrator, lane: dict[str, Any]) -> Any | None:
    graph_set_id = _optional_text(lane.get("graph_set_id"))
    feature_graph_id = _lane_graph_id(lane)
    if graph_set_id is None or feature_graph_id is None:
        return None
    try:
        return orchestrator._feature_graph_status_store.get(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
    except KeyError:
        return None


def _graph_native_authority_required(lane: dict[str, Any]) -> bool:
    return _optional_text(lane.get("graph_set_id")) is not None


def _graph_native_dispatch_authority_allows_lane(orchestrator, lane: dict[str, Any]) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return not _graph_native_authority_required(lane)
    lane_id = str(lane["feature_id"])
    if status.status is FeatureGraphExecutionStatus.REWORKING:
        return True
    if status.status is FeatureGraphExecutionStatus.READY:
        return lane_id in status.ready_lane_ids
    if status.status is FeatureGraphExecutionStatus.RUNNING:
        return lane_id in status.active_lane_ids
    return False


def _lane_recovery_dispatch_block_metadata(
    orchestrator,
    lane: dict[str, Any],
) -> dict[str, Any] | None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    if graph_id is None or lane_id is None:
        return None
    try:
        decision = load_lane_recovery_decision(
            orchestrator._root,
            graph_id=graph_id,
            lane_id=lane_id,
        )
    except (LaneRecoveryArtifactError, ValueError) as exc:
        return {
            "dispatch_blocked_by_recovery": True,
            "recovery_dispatch_block_reason": "invalid_recovery_artifact",
            "recovery_dispatch_block_error": str(exc),
            "recovery_source_authority": "lane_recovery_artifact",
            "manual_gaps": [
                "lane_recovery_artifact_invalid",
                "live_runner_recovery_enforcement_not_proven",
            ],
            "forbidden_claims": [
                "overnight_safe_recovery",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
            ],
        }
    if decision is None or decision.retry_allowed:
        return None
    return {
        "dispatch_blocked_by_recovery": True,
        "recovery_dispatch_block_reason": decision.decision.value,
        "recovery_decision": decision.model_dump(mode="json"),
        "recovery_source_authority": "lane_recovery_artifact",
        "manual_gaps": [
            "lane_status_not_updated_by_durable_authority",
            "live_runner_recovery_enforcement_not_proven",
        ],
        "forbidden_claims": [
            "overnight_safe_recovery",
            "end_to_end_execution_review_closure",
            "ready_to_merge",
            "pr_merged",
        ],
    }


def build_lane_recovery_dispatch_block_metadata(
    orchestrator,
    lane: dict[str, Any],
) -> dict[str, Any] | None:
    """Return durable recovery dispatch-block metadata for a lane."""
    return _lane_recovery_dispatch_block_metadata(orchestrator, lane)


def _record_recovery_artifact_manual_gap(
    orchestrator,
    lane_id: str,
    *,
    source_authority: str,
    manual_gap: str,
    error: str | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "recovery_artifact_status": "manual_gap",
        "recovery_artifact_source_authority": source_authority,
        "manual_gaps": [
            manual_gap,
            "live_runner_recovery_enforcement_not_proven",
        ],
        "forbidden_claims": _lane_recovery_forbidden_claims(),
    }
    if error is not None:
        metadata["recovery_artifact_error"] = error
    orchestrator._sm.update_metadata(lane_id, metadata)


def _write_lane_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
    *,
    source_authority: str,
    decision: LaneRecoveryDecision,
    failure_evidence: list[LaneFailureEvidence],
    source_refs: list[str],
    write_failed_gap: str,
    extra_payload: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Write the single durable recovery artifact format used by L8 producers."""
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    if graph_id is None or lane_id is None:
        raise ValueError("graph_id and feature_id are required to write recovery artifact")
    payload = {
        "schema_version": "xmuse.god_room_lane_recovery.v1",
        "source_authority": source_authority,
        "proof_level": "contract_proof",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "graph_id": graph_id,
        "lane_id": lane_id,
        "decision": decision.model_dump(mode="json"),
        "failure_evidence": [
            failure.model_dump(mode="json") for failure in failure_evidence
        ],
        "source_refs": source_refs,
        "manual_gaps": [
            "live_runner_recovery_enforcement_not_proven",
            "review_truth_not_proven",
            "server_truth_not_proven",
            "overnight_safe_recovery_not_proven",
        ],
        "forbidden_claims": _lane_recovery_forbidden_claims(),
    }
    if extra_payload:
        payload.update(extra_payload)
    try:
        recovery_path = lane_recovery_artifact_path(
            orchestrator._root,
            graph_id=graph_id,
            lane_id=lane_id,
        )
        recovery_path.parent.mkdir(parents=True, exist_ok=True)
        recovery_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            lane_id,
            source_authority=source_authority,
            manual_gap=write_failed_gap,
            error=str(exc),
        )
        return
    metadata = {
        "recovery_artifact_status": "written",
        "recovery_artifact_source_authority": source_authority,
        "recovery_artifact_ref": _relative_artifact_ref(
            orchestrator._root,
            recovery_path,
        ),
        "recovery_decision": decision.model_dump(mode="json"),
        "recovery_source_refs": source_refs,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    orchestrator._sm.update_metadata(lane_id, metadata)


def _record_gate_failure_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
) -> None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    source_authority = "platform_orchestrator_gate_runner"
    if graph_id is None or lane_id is None:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            str(lane.get("feature_id") or ""),
            source_authority=source_authority,
            manual_gap="gate_failure_recovery_artifact_missing_graph_or_lane_id",
        )
        return
    budget = _lane_runtime_budget(lane)
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"lane_graph:{graph_id}",
            gate_report_ref,
            *_text_list(lane.get("source_refs")),
            *budget.source_refs,
        ]
    )
    attempt = _lane_gate_failure_attempt(lane)
    failures = [
        LaneFailureEvidence(
            lane_id=lane_id,
            attempt=failure_attempt,
            failure_class="gate_failed",
            reason="execution gate returned failure",
            source_refs=source_refs,
            occurred_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        for failure_attempt in range(1, attempt + 1)
    ]
    decision = evaluate_lane_recovery(
        lane_id=lane_id,
        budget=budget,
        failures=failures,
    )
    _write_lane_recovery_artifact(
        orchestrator,
        lane,
        source_authority=source_authority,
        decision=decision,
        failure_evidence=failures,
        source_refs=source_refs,
        write_failed_gap="gate_failure_recovery_artifact_write_failed",
    )


def _record_patch_forward_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
    patch_lane: dict[str, Any],
    review_metadata: dict[str, Any],
) -> None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    patch_lane_id = _optional_text(patch_lane.get("feature_id"))
    source_authority = "platform_orchestrator_review_patch_forward"
    if graph_id is None or lane_id is None or patch_lane_id is None:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            str(lane.get("feature_id") or ""),
            source_authority=source_authority,
            manual_gap="patch_forward_recovery_artifact_missing_graph_or_lane_id",
        )
        return

    budget = _lane_runtime_budget(lane)
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    review_verdict_id = _optional_text(review_metadata.get("review_verdict_id"))
    evidence_refs = _text_list(review_metadata.get("review_evidence_refs"))
    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"lane_graph:{graph_id}",
            f"patch_lane:{patch_lane_id}",
            f"review_verdict:{review_verdict_id}" if review_verdict_id else None,
            gate_report_ref,
            *evidence_refs,
            *_text_list(lane.get("source_refs")),
            *_text_list(patch_lane.get("source_refs")),
            *budget.source_refs,
        ]
    )
    failure = LaneFailureEvidence(
        lane_id=lane_id,
        attempt=_lane_review_failure_attempt(review_metadata),
        failure_class="patch_forward_requested",
        reason="independent review requested patch-forward lane",
        source_refs=source_refs,
        occurred_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    decision = LaneRecoveryDecision(
        lane_id=lane_id,
        decision=LaneRecoveryDecisionType.SUSPENDED,
        retry_allowed=False,
        failure_class=failure.failure_class,
        attempt=failure.attempt,
        suspend_reason="patch_forward_requested",
        next_action=(
            f"execute and review patch-forward lane {patch_lane_id} before "
            "retrying the failed lane"
        ),
        source_refs=source_refs,
    )
    _write_lane_recovery_artifact(
        orchestrator,
        lane,
        source_authority=source_authority,
        decision=decision,
        failure_evidence=[failure],
        source_refs=source_refs,
        write_failed_gap="patch_forward_recovery_artifact_write_failed",
        extra_payload={"patch_lane_id": patch_lane_id},
        extra_metadata={"patch_forward_recovery_lane_id": patch_lane_id},
    )


def record_review_rejection_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
) -> None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    source_authority = "platform_orchestrator_review_rejection"
    if graph_id is None or lane_id is None:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            str(lane.get("feature_id") or ""),
            source_authority=source_authority,
            manual_gap="review_rejection_recovery_artifact_missing_graph_or_lane_id",
        )
        return

    attempt = _lane_review_retry_exhausted_attempt(lane)
    budget = _lane_runtime_budget(lane)
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"lane_graph:{graph_id}",
            gate_report_ref,
            *_text_list(lane.get("review_evidence_refs")),
            *_text_list(lane.get("source_refs")),
            *budget.source_refs,
        ]
    )
    failure = LaneFailureEvidence(
        lane_id=lane_id,
        attempt=attempt,
        failure_class="review_rejected",
        reason="review rejection retry budget exhausted",
        source_refs=source_refs,
        occurred_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    decision = LaneRecoveryDecision(
        lane_id=lane_id,
        decision=LaneRecoveryDecisionType.REFACTOR_REQUIRED,
        retry_allowed=False,
        failure_class=failure.failure_class,
        attempt=failure.attempt,
        refactor_required_reason=(
            f"review rejection retry budget exhausted after attempt {attempt}"
        ),
        next_action="refactor or replace the rejected lane boundary before retrying",
        source_refs=source_refs,
    )
    _write_lane_recovery_artifact(
        orchestrator,
        lane,
        source_authority=source_authority,
        decision=decision,
        failure_evidence=[failure],
        source_refs=source_refs,
        write_failed_gap="review_rejection_recovery_artifact_write_failed",
    )


def record_review_retry_exhaustion_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
    *,
    failure_reason: str,
) -> None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    source_authority = "platform_orchestrator_review_retry_exhaustion"
    if graph_id is None or lane_id is None:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            str(lane.get("feature_id") or ""),
            source_authority=source_authority,
            manual_gap=(
                "review_retry_exhaustion_recovery_artifact_missing_graph_or_lane_id"
            ),
        )
        return

    attempt = _lane_review_retry_failure_attempt(lane)
    budget = _lane_runtime_budget(lane)
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    review_task_id = _optional_text(lane.get("review_task_id"))
    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"lane_graph:{graph_id}",
            f"review_task:{review_task_id}" if review_task_id else None,
            f"review_failure:{failure_reason}",
            gate_report_ref,
            *_text_list(lane.get("review_evidence_refs")),
            *_text_list(lane.get("source_refs")),
            *budget.source_refs,
        ]
    )
    failure = LaneFailureEvidence(
        lane_id=lane_id,
        attempt=attempt,
        failure_class=failure_reason,
        reason=f"review retry budget exhausted for {failure_reason}",
        source_refs=source_refs,
        occurred_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    if failure_reason == "review_infra_unavailable":
        decision = LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.SUSPENDED,
            retry_allowed=False,
            failure_class=failure.failure_class,
            attempt=failure.attempt,
            suspend_reason=failure.failure_class,
            next_action="restore review infrastructure before retrying this lane",
            source_refs=source_refs,
        )
    else:
        decision = LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.REFACTOR_REQUIRED,
            retry_allowed=False,
            failure_class=failure.failure_class,
            attempt=failure.attempt,
            refactor_required_reason=(
                f"review retry budget exhausted for {failure_reason} "
                f"after attempt {attempt}"
            ),
            next_action="refactor or replace the review boundary before retrying",
            source_refs=source_refs,
        )
    _write_lane_recovery_artifact(
        orchestrator,
        lane,
        source_authority=source_authority,
        decision=decision,
        failure_evidence=[failure],
        source_refs=source_refs,
        write_failed_gap="review_retry_exhaustion_recovery_artifact_write_failed",
    )


def record_review_retry_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
    *,
    failure_reason: str,
) -> None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    source_authority = "platform_orchestrator_review_retry"
    if graph_id is None or lane_id is None:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            str(lane.get("feature_id") or ""),
            source_authority=source_authority,
            manual_gap="review_retry_recovery_artifact_missing_graph_or_lane_id",
        )
        return

    attempt = _lane_review_retry_failure_attempt(lane)
    budget = _lane_runtime_budget(lane)
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    review_task_id = _optional_text(lane.get("review_task_id"))
    review_attempt_id = _optional_text(lane.get("review_attempt_id"))
    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"lane_graph:{graph_id}",
            f"review_task:{review_task_id}" if review_task_id else None,
            f"review_attempt:{review_attempt_id}" if review_attempt_id else None,
            f"review_failure:{failure_reason}",
            gate_report_ref,
            *_text_list(lane.get("review_evidence_refs")),
            *_text_list(lane.get("source_refs")),
            *budget.source_refs,
        ]
    )
    failure = LaneFailureEvidence(
        lane_id=lane_id,
        attempt=attempt,
        failure_class=failure_reason,
        reason=f"review retry remains allowed for {failure_reason}",
        source_refs=source_refs,
        occurred_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    decision = LaneRecoveryDecision(
        lane_id=lane_id,
        decision=LaneRecoveryDecisionType.RETRY,
        retry_allowed=True,
        failure_class=failure.failure_class,
        attempt=failure.attempt,
        next_action="retry review within declared recovery budget",
        source_refs=source_refs,
    )
    _write_lane_recovery_artifact(
        orchestrator,
        lane,
        source_authority=source_authority,
        decision=decision,
        failure_evidence=[failure],
        source_refs=source_refs,
        write_failed_gap="review_retry_recovery_artifact_write_failed",
    )


def record_merge_failure_recovery_artifact(
    orchestrator,
    lane: dict[str, Any],
    merge_metadata: dict[str, Any],
    *,
    decision_type: LaneRecoveryDecisionType,
) -> None:
    graph_id = _lane_graph_id(lane)
    lane_id = _optional_text(lane.get("feature_id"))
    source_authority = "platform_orchestrator_merge_failure"
    if graph_id is None or lane_id is None:
        _record_recovery_artifact_manual_gap(
            orchestrator,
            str(lane.get("feature_id") or ""),
            source_authority=source_authority,
            manual_gap="merge_failure_recovery_artifact_missing_graph_or_lane_id",
        )
        return

    failure_class = _merge_failure_class(merge_metadata)
    attempt = _lane_merge_failure_attempt(lane)
    budget = _lane_runtime_budget(lane)
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"lane_graph:{graph_id}",
            gate_report_ref,
            *_text_list(lane.get("review_evidence_refs")),
            *_text_list(lane.get("source_refs")),
            *budget.source_refs,
        ]
    )
    failure = LaneFailureEvidence(
        lane_id=lane_id,
        attempt=attempt,
        failure_class=failure_class,
        reason=str(merge_metadata.get("merge_failure_detail") or failure_class),
        source_refs=source_refs,
        occurred_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    decision = _merge_failure_recovery_decision(
        lane_id=lane_id,
        decision_type=decision_type,
        failure=failure,
        source_refs=source_refs,
    )
    _write_lane_recovery_artifact(
        orchestrator,
        lane,
        source_authority=source_authority,
        decision=decision,
        failure_evidence=[failure],
        source_refs=source_refs,
        write_failed_gap="merge_failure_recovery_artifact_write_failed",
    )


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


def _lane_review_failure_attempt(review_metadata: dict[str, Any]) -> int:
    history = review_metadata.get("review_history")
    if not isinstance(history, list):
        return 1
    attempts = [
        entry
        for entry in history
        if isinstance(entry, dict) and entry.get("decision") == "patch-forward"
    ]
    return max(1, len(attempts))


def _lane_review_retry_exhausted_attempt(lane: dict[str, Any]) -> int:
    retry_count = lane.get("retry_count")
    if isinstance(retry_count, bool) or not isinstance(retry_count, int):
        return 1
    return max(1, retry_count + 1)


def _lane_review_retry_failure_attempt(lane: dict[str, Any]) -> int:
    retry_count = lane.get("review_retry_count")
    if isinstance(retry_count, bool) or not isinstance(retry_count, int):
        return 1
    return max(1, retry_count + 1)


def _lane_merge_failure_attempt(lane: dict[str, Any]) -> int:
    retry_count = lane.get("retry_count")
    if isinstance(retry_count, bool) or not isinstance(retry_count, int):
        return 1
    if lane.get("status") == "reworking":
        return max(1, retry_count)
    return max(1, retry_count + 1)


def _merge_failure_class(merge_metadata: dict[str, Any]) -> str:
    reason = str(merge_metadata.get("failure_reason") or "merge_failed")
    if reason == "merge_conflict_or_failed" and (
        merge_metadata.get("merge_failure_reworkable") is True
    ):
        return "merge_conflict"
    return reason


def _merge_failure_recovery_decision(
    *,
    lane_id: str,
    decision_type: LaneRecoveryDecisionType,
    failure: LaneFailureEvidence,
    source_refs: list[str],
) -> LaneRecoveryDecision:
    if decision_type is LaneRecoveryDecisionType.RETRY:
        return LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.RETRY,
            retry_allowed=True,
            failure_class=failure.failure_class,
            attempt=failure.attempt,
            next_action="retry merge failure lane within declared budget",
            source_refs=source_refs,
        )
    if decision_type is LaneRecoveryDecisionType.REFACTOR_REQUIRED:
        return LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.REFACTOR_REQUIRED,
            retry_allowed=False,
            failure_class=failure.failure_class,
            attempt=failure.attempt,
            refactor_required_reason=(
                f"merge failure {failure.failure_class} exhausted retry budget"
            ),
            next_action="refactor or replace the merge failure boundary before retrying",
            source_refs=source_refs,
        )
    return LaneRecoveryDecision(
        lane_id=lane_id,
        decision=LaneRecoveryDecisionType.SUSPENDED,
        retry_allowed=False,
        failure_class=failure.failure_class,
        attempt=failure.attempt,
        suspend_reason=failure.failure_class,
        next_action="inspect non-retryable merge failure before retrying",
        source_refs=source_refs,
    )


def _lane_recovery_forbidden_claims() -> list[str]:
    return [
        "independent_review_truth",
        "server_truth",
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


def _graph_native_review_authority_allows_lane(orchestrator, lane: dict[str, Any]) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return not _graph_native_authority_required(lane)
    return status.status is FeatureGraphExecutionStatus.REVIEWING


def _graph_native_execution_authority_allows_lane(orchestrator, lane: dict[str, Any]) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return not _graph_native_authority_required(lane)
    if status.status is not FeatureGraphExecutionStatus.RUNNING:
        return False
    return str(lane["feature_id"]) in status.active_lane_ids


def _graph_native_reprojection_authority_allows_lane(
    orchestrator,
    lane: dict[str, Any],
    *,
    expected_status: FeatureGraphExecutionStatus,
) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return not _graph_native_authority_required(lane)
    return status.status is expected_status


def _git_output(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git command failed: {command}")
    return result.stdout.strip()


def _lane_needs_takeover_memory(lane: dict[str, Any]) -> bool:
    status = str(lane.get("status") or "")
    return (
        status in {"reworking", "exec_failed", "gate_failed", "failed"}
        or int(lane.get("retry_count") or 0) > 0
        or int(lane.get("review_retry_count") or 0) > 0
        or bool(lane.get("failure_reason"))
        or bool(lane.get("merge_failure_reason"))
    )


def _merge_failure_is_reworkable(lane: dict[str, Any]) -> bool:
    return (
        lane.get("merge_failure_reason") == "merge_conflict_or_failed"
        and lane.get("merge_failure_reworkable") is True
    )


def _merge_failure_is_deferred(lane: dict[str, Any]) -> bool:
    return lane.get("merge_failure_reason") == "target_worktree_dirty_conflict"


def _merge_failure_clear_metadata() -> dict[str, None]:
    return {
        "merge_failure_reason": None,
        "merge_failure_detail": None,
        "merge_failure_reworkable": None,
        "merge_retry_after_at": None,
        "stale_against_current_target_head": None,
        "current_target_head": None,
        "stale_base_head_sha": None,
        "target_dirty_conflicting_paths": None,
    }

async def dispatch_lane(orchestrator, lane_id: str) -> None:
    try:
        lane = orchestrator._sm.get_lane(lane_id)
    except KeyError:
        lane = None
    memory_event = "planning"
    memory_lane: dict[str, Any] | None = None
    if lane is not None:
        if not _graph_native_dispatch_authority_allows_lane(orchestrator, lane):
            log_event(
                logger,
                logging.INFO,
                "lane_dispatch_skipped_graph_native_authority",
                lane_id=lane_id,
                graph_set_id=_optional_text(lane.get("graph_set_id")),
                graph_id=_lane_graph_id(lane),
            )
            return
        lane = orchestrator._ensure_lane_worktree(lane)
        lane = orchestrator._sm.get_lane(lane_id)
        current_status = str(lane.get("status") or "pending")
        if current_status not in {"pending", "reworking"}:
            log_event(
                logger,
                logging.INFO,
                "lane_dispatch_skipped_status_changed",
                lane_id=lane_id,
                status=current_status,
            )
            return
        recovery_block = build_lane_recovery_dispatch_block_metadata(orchestrator, lane)
        if recovery_block is not None:
            orchestrator._sm.update_metadata(lane_id, recovery_block)
            log_event(
                logger,
                logging.WARNING,
                "lane_dispatch_blocked_by_recovery_decision",
                lane_id=lane_id,
                graph_id=_lane_graph_id(lane),
                reason=recovery_block["recovery_dispatch_block_reason"],
            )
            return
        memory_event = "takeover" if _lane_needs_takeover_memory(lane) else "planning"
        memory_lane = dict(lane)
    with observability_context(
        lane_id=lane_id,
        graph_id=_lane_graph_id(lane),
    ), timed_core_operation(
        component="orchestrator",
        operation="dispatch_lane",
        logger=logger,
        lane_id=lane_id,
    ):
        current_status = (
            str(lane.get("status") or "pending")
            if isinstance(lane, dict)
            else "pending"
        )
        current_revision = orchestrator._sm.current_projection_revision()
        metadata: dict[str, Any] = {
            "runner_id": orchestrator._runner_id,
            "dispatch_attempt_id": (
                f"dispatch-{_safe_lane_ref(lane_id)}-{uuid.uuid4().hex[:12]}"
            ),
            "dispatch_status_guard": current_status,
            "dispatch_projection_revision": current_revision,
            "dispatched_at": time.time(),
            "god": orchestrator._execution_god.name,
            "god_runtime": orchestrator._god_picker.pick_execution(lane_id).runtime,
            "worker_pid": None,
            "worker_started_at": None,
            "worker_heartbeat_at": None,
            "worker_command": [],
            "worker_worktree": str(Path(lane.get("worktree", ".")))
            if isinstance(lane, dict)
            else ".",
        } | (
            orchestrator._model_policy.metadata_defaults(lane=lane)
            if orchestrator._model_policy is not None
            else {}
        )
        try:
            claimed = orchestrator._sm.transition_if_metadata(
                lane_id,
                "dispatched",
                expected_metadata={"status": current_status},
                metadata=metadata,
            )
        except InvalidTransitionError:
            log_event(
                logger,
                logging.INFO,
                "lane_dispatch_skipped_status_changed",
                lane_id=lane_id,
                status=current_status,
            )
            return
        if claimed is None:
            log_event(
                logger,
                logging.INFO,
                "lane_dispatch_skipped_status_changed",
                lane_id=lane_id,
                status=current_status,
            )
            return
        lane = claimed
        log_event(logger, logging.INFO, "lane_dispatched", lane_id=lane_id)
        await orchestrator._record_lane_memory_event(
            lane_id,
            memory_lane if memory_event == "takeover" and memory_lane is not None else lane,
            event=memory_event,
        )
        await orchestrator._run_execution_god(lane_id)

def ensure_lane_worktree(orchestrator, lane: dict[str, Any]) -> dict[str, Any]:
    lane_id = str(lane["feature_id"])
    existing_worktree = lane.get("worktree")
    existing_branch = lane.get("branch")
    if existing_worktree:
        return lane

    branch = str(existing_branch or _safe_lane_ref(lane_id))
    worktree_base = _compat_symbol(orchestrator, "WORKTREE_BASE", WORKTREE_BASE)
    worktree = worktree_base / _safe_lane_ref(lane_id)
    git_output = _compat_symbol(orchestrator, "_git_output", _git_output)
    base_head_sha = lane.get("base_head_sha") or git_output(
        ["git", "rev-parse", "HEAD"],
        cwd=orchestrator._root.parent,
    )
    orchestrator._create_or_reuse_worktree(worktree=worktree, branch=branch)
    metadata = {
        "branch": branch,
        "worktree": str(worktree),
        "base_head_sha": str(base_head_sha),
    }
    updated = orchestrator._sm.update_metadata(lane_id, metadata)
    log_event(
        logger,
        logging.INFO,
        "lane_worktree_initialized",
        lane_id=lane_id,
        branch=branch,
        worktree=str(worktree),
    )
    return updated

def create_or_reuse_worktree(orchestrator, *, worktree: Path, branch: str) -> None:
    if worktree.exists():
        return
    worktree.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"],
        cwd=orchestrator._root.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        return
    fallback = subprocess.run(
        ["git", "worktree", "add", str(worktree), branch],
        cwd=orchestrator._root.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if fallback.returncode != 0:
        raise RuntimeError(
            "failed to create lane worktree "
            f"{worktree}: {result.stderr.strip() or fallback.stderr.strip()}"
        )

async def run_execution_god(orchestrator, lane_id: str) -> None:
    lane = orchestrator._sm.get_lane(lane_id)
    with observability_context(
        lane_id=lane_id,
        graph_id=_lane_graph_id(lane),
    ), timed_core_operation(
        component="orchestrator",
        operation="run_execution_god",
        logger=logger,
        lane_id=lane_id,
    ):
        all_lanes = orchestrator._sm.get_lanes()
        orchestrator._write_lane_context_bundle(lane, all_lanes=all_lanes)
        prompt = build_execution_prompt(
            lane,
            xmuse_root=orchestrator._root,
            skill_prompt_path=orchestrator._execution_god.skill_prompt_path,
            all_lanes=all_lanes,
        )
        god = orchestrator._god_picker.pick_execution(lane_id)
        provider_invocation = orchestrator._provider_service.build_execution_invocation(
            lane_id=lane_id,
            prompt=prompt,
            workspace=Path(lane.get("worktree", ".")),
            timeout_seconds=god.timeout_s,
            provider_profile_ref=orchestrator._execution_provider_profile_ref,
            lane=lane,
        )
        orchestrator._provider_service.record_execution_selection(
            lane_id=lane_id,
            invocation=provider_invocation,
            used_override=orchestrator._execution_provider_profile_ref is not None,
        )
        provider_model = orchestrator._provider_service.model_for_invocation(
            provider_invocation,
            model_override=god.model,
        )
        session_route = plan_execution_runtime_session_route(
            store=orchestrator._provider_session_binding_store,
            provider_adapter=orchestrator._provider_service,
            lane=lane,
            invocation=provider_invocation,
            model=provider_model,
            prompt_fingerprint=fingerprint_prompt(prompt),
            feature_graph_status_store=orchestrator._feature_graph_status_store,
        )
        provider_session_binding = session_route.provider_session_binding
        persistent_execute_enabled = orchestrator._persistent_execute_enabled
        persistent_execute_session_layer = orchestrator._persistent_execute_session_layer
        if session_route.primary_path == "explicit_provider_resume":
            persistent_execute_enabled = False
            persistent_execute_session_layer = None
        if not session_route.allows_persistent_execute:
            persistent_execute_enabled = False
            persistent_execute_session_layer = None
        executor = _compat_symbol(orchestrator, "execution_executor", execution_executor)
        await executor.run_execution_god(
            lane_id=lane_id,
            god=GodConfig(
                name=god.name,
                runtime=orchestrator._provider_service.runtime_for_invocation(
                    provider_invocation
                ),
                timeout_s=god.timeout_s,
                skill_prompt_path=god.skill_prompt_path,
                model=provider_model,
                worker_model=god.worker_model,
                delegation_mode=god.delegation_mode,
            ),
            prompt=prompt,
            worktree=Path(lane.get("worktree", ".")),
            sm=orchestrator._sm,
            recovery=orchestrator._recovery,
            transport=orchestrator._transport,
            observer=orchestrator._lane_recovery_observer(lane_id),
            on_executed=orchestrator._on_lane_executed,
            persistent_execute_enabled=persistent_execute_enabled,
            persistent_session_layer=persistent_execute_session_layer,
            xmuse_root=orchestrator._root,
            provider_invocation=provider_invocation,
            provider_session_binding=provider_session_binding,
            provider_session_binding_writer=orchestrator._provider_session_binding_store,
            provider_session_binding_god_session_id=_provider_binding_god_session_id(lane),
            provider_session_binding_role="feature_worker",
            provider_session_binding_conversation_id=_optional_text(
                lane.get("conversation_id")
            ),
            provider_session_binding_feature_graph_id=_lane_graph_id(lane),
            provider_session_binding_prompt_fingerprint=fingerprint_prompt(prompt),
            record_provider_session_binding_degradation=(
                lambda binding_id, reason, failure: (
                    orchestrator.record_feature_graph_provider_binding_degradation(
                        lane_id=lane_id,
                        binding_id=binding_id,
                        reason=reason,
                        failure=failure,
                        updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    )
                )
            ),
        )

async def on_lane_executed(orchestrator, lane_id: str) -> None:
    lane = orchestrator._sm.get_lane(lane_id)
    with observability_context(
        lane_id=lane_id,
        graph_id=_lane_graph_id(lane),
    ), timed_core_operation(
        component="orchestrator",
        operation="on_lane_executed",
        logger=logger,
        lane_id=lane_id,
    ):
        if lane.get("status") != "executed":
            return
        try:
            passed = await orchestrator._recovery.execute_async(
                "orchestrator.gate_runner",
                "run",
                lambda: orchestrator._run_gate(lane_id),
                fallback=lambda _exc: False,
                critical=False,
                observer=orchestrator._lane_recovery_observer(lane_id),
            )
        except Exception:
            passed = False
        if orchestrator._sm.get_lane(lane_id).get("status") != "executed":
            return
        if passed:
            orchestrator._sm.transition(lane_id, "gated", metadata={"gate_passed": True})
            await orchestrator._run_review_god(lane_id)
        else:
            failed_lane = orchestrator._sm.transition(
                lane_id,
                "gate_failed",
                metadata={"gate_passed": False, "failure_reason": "gate_failed"},
            )
            _record_gate_failure_recovery_artifact(orchestrator, failed_lane or lane)

async def run_review_god(orchestrator, lane_id: str) -> None:
    lane = orchestrator._sm.get_lane(lane_id)
    with observability_context(
        lane_id=lane_id,
        graph_id=_lane_graph_id(lane),
    ), timed_core_operation(
        component="orchestrator",
        operation="run_review_god",
        logger=logger,
        lane_id=lane_id,
    ):
        all_lanes = orchestrator._sm.get_lanes()
        orchestrator._write_lane_context_bundle(lane, all_lanes=all_lanes)
        orchestrator._sm.update_metadata(
            lane_id,
            {
                "review_runner_id": orchestrator._runner_id,
                "review_attempt_id": (
                    f"review-{_safe_lane_ref(lane_id)}-{uuid.uuid4().hex[:12]}"
                ),
            },
        )
        prompt = build_review_prompt(
            lane,
            xmuse_root=orchestrator._root,
            skill_prompt_path=orchestrator._review_god.skill_prompt_path,
            all_lanes=all_lanes,
        )
        god = orchestrator._god_picker.pick_review(lane_id)
        provider_invocation = orchestrator._provider_service.build_review_invocation(
            lane_id=lane_id,
            prompt=prompt,
            workspace=Path(lane.get("worktree", ".")),
            timeout_seconds=god.timeout_s,
            provider_profile_ref=orchestrator._review_provider_profile_ref,
            lane=lane,
        )
        orchestrator._provider_service.record_review_selection(
            lane_id=lane_id,
            invocation=provider_invocation,
            used_override=orchestrator._review_provider_profile_ref is not None,
        )
        provider_model = orchestrator._provider_service.model_for_invocation(
            provider_invocation,
            model_override=god.model,
        )
        session_route = plan_review_runtime_session_route(
            store=orchestrator._provider_session_binding_store,
            provider_adapter=orchestrator._provider_service,
            lane=lane,
            invocation=provider_invocation,
            model=provider_model,
            prompt_fingerprint=fingerprint_prompt(prompt),
        )
        await execution_review_god.run_review_god(
            lane_id=lane_id,
            lane=lane,
            god=GodConfig(
                name=god.name,
                runtime=orchestrator._provider_service.runtime_for_invocation(
                    provider_invocation
                ),
                timeout_s=god.timeout_s,
                skill_prompt_path=god.skill_prompt_path,
                model=provider_model,
            ),
            prompt=prompt,
            worktree=Path(lane.get("worktree", ".")),
            xmuse_root=orchestrator._root,
            sm=orchestrator._sm,
            recovery=orchestrator._recovery,
            transport=orchestrator._transport,
            persistent_session_layer=orchestrator._review_god_session_layer,
            persistent_review_receive_timeout_s=(
                orchestrator._persistent_review_receive_timeout_s
                if orchestrator._persistent_review_receive_timeout_s is not None
                else execution_review_god.PERSISTENT_REVIEW_RECEIVE_TIMEOUT_S
            ),
            default_review_peer_routing_enabled=(
                orchestrator._default_review_peer_routing_enabled
            ),
            observer=orchestrator._lane_recovery_observer(lane_id),
            open_review_task=orchestrator._open_review_task,
            stable_verdict_id=lambda target_lane_id: stable_verdict_id_for_lane(
                target_lane_id,
                lane=orchestrator._sm.get_lane(target_lane_id),
            ),
            ingest_merge_verdict=lambda target_lane_id, summary: ingest_merge_verdict(
                target_lane_id,
                summary,
                lane=orchestrator._sm.get_lane(target_lane_id),
                review_plane=orchestrator._review_plane,
            ),
            ingest_rework_verdict=lambda target_lane_id, summary: ingest_rework_verdict(
                target_lane_id,
                summary,
                lane=orchestrator._sm.get_lane(target_lane_id),
                review_plane=orchestrator._review_plane,
            ),
            on_reviewed=orchestrator.on_lane_reviewed,
            on_rejected=orchestrator.on_lane_rejected,
            provider_invocation=provider_invocation,
            provider_session_binding=session_route.provider_session_binding,
            provider_session_binding_writer=orchestrator._provider_session_binding_store,
        )

def open_review_task(orchestrator, lane_id: str) -> None:
    # Open a ReviewTask so the review plane has a persistent audit record.
    gate_report_ref = gate_report_ref_for_lane(lane_id, xmuse_root=orchestrator._root)
    try:
        review_task = orchestrator._review_plane.open_review_task(
            lane_id, gate_report_ref=gate_report_ref
        )
        orchestrator._sm.update_metadata(lane_id, {"review_task_id": review_task.task_id})
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "review_plane_open_task_failed",
            lane_id=lane_id,
        )


async def on_lane_reviewed_inner(orchestrator, lane_id: str, lane: dict[str, Any]) -> None:
    await orchestrator._record_lane_memory_event(lane_id, lane, event="review")
    verdict = build_review_verdict(lane)

    # Persist the verdict through the review plane for auditable lineage.
    task_id = lane.get("review_task_id")
    if task_id:
        try:
            orchestrator._review_plane.ingest_verdict(task_id, verdict)
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "review_plane_verdict_ingest_failed",
                lane_id=lane_id,
                task_id=task_id,
            )

    adapted = adapt_review_verdict(
        verdict,
        lane=lane,
        require_final_action_approval=orchestrator._require_final_action_approval,
    )

    if adapted.patch_lane is not None:
        orchestrator._sm.append_lane(adapted.patch_lane)
        orchestrator._sm.transition(
            lane_id,
            "failed",
            metadata=adapted.metadata | {
                "failure_reason": "patch_forward_requested",
                "patch_lane_id": adapted.patch_lane["feature_id"],
            },
        )
        _record_patch_forward_recovery_artifact(
            orchestrator,
            lane,
            adapted.patch_lane,
            adapted.metadata,
        )
        log_event(
            logger,
            logging.INFO,
            "patch_forward_lane_created",
            lane_id=lane_id,
            patch_lane_id=adapted.patch_lane["feature_id"],
        )
        return

    if adapted.final_action is not None:
        hold = orchestrator._final_action_store.create_hold(
            lane_id=adapted.final_action.lane_id,
            verdict_id=adapted.final_action.verdict_id,
            action=adapted.final_action.action,
            target_status=adapted.final_action.target_status,
            summary=adapted.final_action.summary,
        )
        orchestrator._sm.transition(
            lane_id,
            "awaiting_final_action",
            metadata=adapted.metadata | {"final_action_hold_id": hold.id},
        )
        log_event(
            logger,
            logging.INFO,
            "lane_awaiting_final_action",
            lane_id=lane_id,
            action=hold.action,
        )
        return

    if adapted.transition_status == "rejected":
        orchestrator._sm.transition(lane_id, "rejected", metadata=adapted.metadata)
        await orchestrator.on_lane_rejected(lane_id)
        return

    if adapted.transition_status == "failed":
        orchestrator._sm.transition(lane_id, "failed", metadata=adapted.metadata)
        log_event(logger, logging.INFO, "lane_terminated_by_review", lane_id=lane_id)
        return

    merged = await orchestrator._auto_merge(lane_id, orchestrator._root.parent)
    if merged:
        orchestrator._sm.transition(
            lane_id,
            "merged",
            metadata=_merge_failure_clear_metadata(),
        )
        await reproject_dependents_if_needed(
            lane_id,
            sm=orchestrator._sm,
            graph_store=orchestrator._graph_store,
        )
        log_event(logger, logging.INFO, "lane_merged", lane_id=lane_id)
    else:
        lane = orchestrator._sm.get_lane(lane_id)
        metadata: dict[str, Any] = {
            "failure_reason": str(
                lane.get("merge_failure_reason") or "merge_failed"
            )
        }
        if lane.get("merge_failure_detail"):
            metadata["merge_failure_detail"] = str(lane["merge_failure_detail"])
        if lane.get("merge_failure_reworkable") is not None:
            metadata["merge_failure_reworkable"] = bool(
                lane["merge_failure_reworkable"]
            )
        if lane.get("merge_retry_after_at") is not None:
            metadata["merge_retry_after_at"] = lane["merge_retry_after_at"]
        if lane.get("target_dirty_conflicting_paths") is not None:
            metadata["target_dirty_conflicting_paths"] = lane[
                "target_dirty_conflicting_paths"
            ]
        if _merge_failure_is_deferred(lane):
            deferred_metadata = {
                key: value
                for key, value in metadata.items()
                if key != "failure_reason"
            }
            orchestrator._sm.update_metadata(lane_id, deferred_metadata)
            log_event(
                logger,
                logging.WARNING,
                "lane_merge_deferred",
                lane_id=lane_id,
                merge_failure_reason=lane.get("merge_failure_reason"),
                merge_retry_after_at=lane.get("merge_retry_after_at"),
            )
            return
        if _merge_failure_is_reworkable(lane):
            try:
                reworked_lane = orchestrator._sm.transition(
                    lane_id,
                    "reworking",
                    metadata=metadata,
                )
            except InvalidTransitionError:
                failed_lane = orchestrator._sm.transition(
                    lane_id,
                    "failed",
                    metadata=metadata,
                )
                record_merge_failure_recovery_artifact(
                    orchestrator,
                    failed_lane or lane,
                    metadata,
                    decision_type=LaneRecoveryDecisionType.REFACTOR_REQUIRED,
                )
                await reproject_dependents_if_needed(
                    lane_id,
                    sm=orchestrator._sm,
                    graph_store=orchestrator._graph_store,
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "lane_merge_failed",
                    lane_id=lane_id,
                )
                return
            record_merge_failure_recovery_artifact(
                orchestrator,
                reworked_lane or orchestrator._sm.get_lane(lane_id),
                metadata,
                decision_type=LaneRecoveryDecisionType.RETRY,
            )
            log_event(
                logger,
                logging.WARNING,
                "lane_merge_conflict_reworking",
                lane_id=lane_id,
            )
            await orchestrator.dispatch_lane(lane_id)
            return
        failed_lane = orchestrator._sm.transition(lane_id, "failed", metadata=metadata)
        record_merge_failure_recovery_artifact(
            orchestrator,
            failed_lane or lane,
            metadata,
            decision_type=LaneRecoveryDecisionType.SUSPENDED,
        )
        await reproject_dependents_if_needed(
            lane_id,
            sm=orchestrator._sm,
            graph_store=orchestrator._graph_store,
        )


async def record_lane_memory_event(
    orchestrator,
    lane_id: str,
    lane: dict[str, Any],
    *,
    event: Literal["planning", "review", "takeover"],
) -> None:
    if orchestrator._memory_store is None:
        return
    lesson = build_memory_lesson_for_event(
        event, lane, xmuse_root=orchestrator._root
    )
    if lesson is None:
        return
    try:
        existing_ref = find_matching_memory_ref(lane.get("memory_refs"), lesson)
        ref = await orchestrator._memory_store.remember(lesson, existing_ref=existing_ref)
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "lane_memory_update_failed",
            lane_id=lane_id,
            memory_event=event,
            error=str(exc),
        )
        return
    updated_refs = upsert_memory_ref(lane.get("memory_refs"), ref)
    if updated_refs == lane.get("memory_refs"):
        return
    orchestrator._sm.update_metadata(lane_id, {"memory_refs": updated_refs})
    log_event(
        logger,
        logging.INFO,
        "lane_memory_updated",
        lane_id=lane_id,
        memory_event=event,
        memory_ref=ref.uri,
    )
