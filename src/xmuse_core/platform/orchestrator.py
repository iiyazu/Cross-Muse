from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.provider_session_binding_store import ProviderSessionBindingStore
from xmuse_core.observability import (
    current_observability_context,
    log_event,
    observability_context,
    timed_core_operation,
)
from xmuse_core.platform.agent_spawner import AgentSpawner, GodConfig
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.platform.execution import executor as execution_executor  # noqa: F401
from xmuse_core.platform.execution import gate as execution_gate
from xmuse_core.platform.execution import merger as execution_merger
from xmuse_core.platform.execution import review_god as execution_review_god
from xmuse_core.platform.execution.transport import SpawnerTransport
from xmuse_core.platform.feature_graph_claim_coordinator import (
    FeatureGraphWorkerClaimOutcome,
)
from xmuse_core.platform.feature_graph_claim_coordinator import (
    claim_next_ready_feature_graph_worker as claim_next_ready_feature_graph_worker_flow,
)
from xmuse_core.platform.feature_graph_dependency_coordinator import (
    FeatureGraphDependentReleaseOutcome,
)
from xmuse_core.platform.feature_graph_dependency_coordinator import (
    release_ready_feature_graph_dependents as release_ready_feature_graph_dependents_flow,
)
from xmuse_core.platform.feature_graph_patch_forward_gate_coordinator import (
    FeatureGraphPatchForwardGateResultOutcome,
    FeatureGraphPatchForwardMergeGuardDecisionOutcome,
    FeatureGraphPatchForwardStatusTransitionOutcome,
)
from xmuse_core.platform.feature_graph_patch_forward_gate_coordinator import (
    apply_feature_graph_patch_forward_merge_guard_decision_status as apply_pf_status_flow,
)
from xmuse_core.platform.feature_graph_patch_forward_gate_coordinator import (
    submit_feature_graph_patch_forward_gate_result as submit_patch_forward_gate_result_flow,
)
from xmuse_core.platform.feature_graph_patch_forward_gate_coordinator import (
    submit_feature_graph_patch_forward_merge_guard_decision as submit_pf_merge_guard_decision_flow,
)
from xmuse_core.platform.feature_graph_provider_binding_degradation_coordinator import (
    FeatureGraphProviderBindingDegradationOutcome,
    reconcile_feature_graph_provider_binding_degradations,
    record_feature_graph_provider_binding_degradation,
    record_feature_graph_provider_binding_degradation_from_lane,
)
from xmuse_core.platform.feature_graph_review_coordinator import (
    FeatureGraphReviewVerdictOutcome,
)
from xmuse_core.platform.feature_graph_review_coordinator import (
    submit_feature_graph_review_verdict as submit_feature_graph_review_verdict_flow,
)
from xmuse_core.platform.feature_graph_rework_coordinator import (
    FeatureGraphReworkStatusApplicationOutcome,
)
from xmuse_core.platform.feature_graph_rework_coordinator import (
    apply_feature_graph_rework_packet_status_from_artifacts as apply_rework_packet_status_flow,
)
from xmuse_core.platform.feature_graph_takeover_coordinator import (
    FeatureGraphTakeoverDecisionOutcome,
    FeatureGraphTakeoverFollowupReviewApplicationOutcome,
    FeatureGraphTakeoverFollowupReviewVerdictOutcome,
    FeatureGraphTakeoverWorkerOutcome,
)
from xmuse_core.platform.feature_graph_takeover_coordinator import (
    apply_feature_graph_takeover_followup_review_verdict as apply_takeover_followup_verdict_flow,
)
from xmuse_core.platform.feature_graph_takeover_coordinator import (
    submit_feature_graph_takeover_decision as submit_takeover_decision_flow,
)
from xmuse_core.platform.feature_graph_takeover_coordinator import (
    submit_feature_graph_takeover_followup_review_verdict as submit_takeover_followup_verdict_flow,
)
from xmuse_core.platform.feature_graph_takeover_coordinator import (
    submit_feature_graph_takeover_outcome as submit_takeover_outcome_flow,
)
from xmuse_core.platform.feature_graph_worker_evidence_coordinator import (
    FeatureGraphWorkerEvidenceSubmissionOutcome,
)
from xmuse_core.platform.feature_graph_worker_evidence_coordinator import (
    submit_feature_graph_worker_evidence as submit_feature_graph_worker_evidence_flow,
)
from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.lane_context import write_lane_context_bundle
from xmuse_core.platform.mcp_tools import McpToolHandler
from xmuse_core.platform.memory_refs import MemoryOSStoreAdapter
from xmuse_core.platform.model_policy import CodexModelPolicy
from xmuse_core.platform.orchestrator_lane_flow import (
    _graph_native_dispatch_authority_allows_lane,
    _graph_native_execution_authority_allows_lane,
    _graph_native_reprojection_authority_allows_lane,
    _graph_native_review_authority_allows_lane,
    _graph_native_status_record,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    create_or_reuse_worktree as create_or_reuse_worktree_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    dispatch_lane as dispatch_lane_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    ensure_lane_worktree as ensure_lane_worktree_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    on_lane_executed as on_lane_executed_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    on_lane_reviewed_inner as on_lane_reviewed_inner_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    open_review_task as open_review_task_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    record_lane_memory_event as record_lane_memory_event_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    run_execution_god as run_execution_god_flow,
)
from xmuse_core.platform.orchestrator_lane_flow import (
    run_review_god as run_review_god_flow,
)
from xmuse_core.platform.projection.dependents import reproject_dependents_if_needed
from xmuse_core.platform.review_plane import ReviewPlaneController
from xmuse_core.platform.selection.god_picker import GodPicker
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.selection_record import ProviderSelectionRecordStore
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.self_evolution.recovery import (
    RecoveryConfig,
    RecoveryEvent,
    RecoveryManager,
)
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_review_contracts import FeatureGraphExecutionStatus
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphSet,
    FeatureReviewVerdict,
    LaneGraph,
    RunTerminalAggregation,
    StructuredEvidenceBundle,
)
from xmuse_core.structuring.verdict_store import EvidenceBundleStore

logger = logging.getLogger(__name__)
DEFAULT_MCP_PORT = 8100
REVIEW_INFRA_RETRY_DELAY_S = 15 * 60
SUPPORTED_GOD_RUNTIMES = ("codex",)
WORKTREE_BASE = Path.home() / ".config" / "superpowers" / "worktrees" / "memoryOS"
RECONCILE_GATE_REVIEW_CONCURRENCY_ENV = "XMUSE_RECONCILE_GATE_REVIEW_CONCURRENCY"
SAFE_RECONCILE_GATE_REVIEW_CONCURRENCY = 16


def _lane_graph_id(lane: dict[str, Any] | None) -> str | None:
    graph_id = lane.get("graph_id") if isinstance(lane, dict) else None
    return str(graph_id) if graph_id else None


def _reconcile_candidate_lanes(
    orchestrator,
    *,
    graph_native_status: FeatureGraphExecutionStatus,
    legacy_statuses: set[str],
    graph_backed_operational_statuses: set[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    operational_statuses = graph_backed_operational_statuses or legacy_statuses
    for lane in list(orchestrator._sm.get_lanes()):
        lane_status = str(lane.get("status") or "pending")
        graph_status = _graph_native_status_record(orchestrator, lane)
        if graph_status is None:
            if lane_status in legacy_statuses:
                candidates.append(lane)
            continue
        if graph_status.status is not graph_native_status:
            continue
        if lane_status in operational_statuses:
            candidates.append(lane)
    return candidates


def _orchestrator_recovery_config() -> RecoveryConfig:
    return RecoveryConfig.from_env("XMUSE_RECOVERY")


def _resolve_god_runtime(explicit: str | None) -> str:
    runtime = explicit or "codex"
    if runtime not in SUPPORTED_GOD_RUNTIMES:
        raise ValueError(
            f"unsupported god runtime: {runtime!r}; xmuse is codex-only"
        )
    return runtime


def _safe_lane_ref(lane_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", lane_id).strip("-") or "lane"


def _reconcile_gate_review_concurrency_limit(*, total: int) -> int | None:
    """Return None to run the full currently-ready reconcile batch at once."""
    raw_limit = os.environ.get(RECONCILE_GATE_REVIEW_CONCURRENCY_ENV)
    if raw_limit is None or raw_limit.strip() == "":
        return None
    try:
        limit = int(raw_limit)
    except ValueError:
        logger.warning(
            "invalid_reconcile_gate_review_concurrency",
            extra={
                "env": RECONCILE_GATE_REVIEW_CONCURRENCY_ENV,
                "value": raw_limit,
                "fallback": SAFE_RECONCILE_GATE_REVIEW_CONCURRENCY,
            },
        )
        return min(SAFE_RECONCILE_GATE_REVIEW_CONCURRENCY, total)
    if limit <= 0:
        return None
    return min(limit, total)


def _merge_failure_is_reworkable(lane: dict[str, Any]) -> bool:
    return (
        lane.get("merge_failure_reason") == "merge_conflict_or_failed"
        and lane.get("merge_failure_reworkable") is True
    )


def _merge_failure_is_deferred(lane: dict[str, Any]) -> bool:
    return lane.get("merge_failure_reason") == "target_worktree_dirty_conflict"


def _merge_retry_after_is_active(
    lane: dict[str, Any],
    *,
    now: float | None = None,
) -> bool:
    retry_after = lane.get("merge_retry_after_at")
    return (
        isinstance(retry_after, int | float)
        and not isinstance(retry_after, bool)
        and (time.time() if now is None else now) < float(retry_after)
    )


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


def _lane_needs_takeover_memory(lane: dict[str, Any]) -> bool:
    status = str(lane.get("status") or "")
    return (
        status in {"reworking", "exec_failed", "gate_failed", "failed"}
        or int(lane.get("retry_count") or 0) > 0
        or int(lane.get("review_retry_count") or 0) > 0
        or bool(lane.get("failure_reason"))
        or bool(lane.get("merge_failure_reason"))
    )


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def _execution_god(
    runtime: str,
    *,
    model: str | None = None,
    worker_model: str | None = None,
    delegation_mode: str | None = None,
) -> GodConfig:
    return GodConfig(
        name="execution-god",
        runtime=runtime,
        timeout_s=3600,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
        model=model,
        worker_model=worker_model,
        delegation_mode=delegation_mode,
    )


def _review_god(runtime: str, *, model: str | None = None) -> GodConfig:
    return GodConfig(
        name="review-god",
        runtime=runtime,
        timeout_s=900,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
        model=model,
    )


EXECUTION_GOD = _execution_god("codex")
REVIEW_GOD = _review_god("codex")


class PlatformOrchestrator:
    def __init__(
        self,
        *,
        lanes_path: Path,
        xmuse_root: Path,
        mcp_port: int = DEFAULT_MCP_PORT,
        require_final_action_approval: bool = False,
        god_runtime: str | None = None,
        memoryos_client: Any | None = None,
        review_god_session_layer: Any | None = None,
        persistent_review_receive_timeout_s: float | None = None,
        default_review_peer_routing_enabled: bool = False,
        persistent_execute_enabled: bool = False,
        persistent_execute_session_layer: Any | None = None,
        model_policy: CodexModelPolicy | None = None,
        execution_provider_profile_ref: str | None = None,
        review_provider_profile_ref: str | None = None,
        provider_service: RunnerProviderService | None = None,
        provider_session_binding_store: ProviderSessionBindingStore | None = None,
        repo_root: Path | None = None,
        feature_graph_status_store: FeatureGraphStatusStore | None = None,
        feature_graph_artifact_store: FeatureGraphArtifactStore | None = None,
        feature_graph_max_rework_attempts: int = 2,
        runner_id: str | None = None,
    ) -> None:
        if feature_graph_max_rework_attempts < 0:
            raise ValueError("feature_graph_max_rework_attempts must be >= 0")
        self._lanes_path = lanes_path
        self._sm = LaneStateMachine(
            lanes_path,
            history_path=xmuse_root / "state_history.json",
        )
        self._bus = EventBus(audit_log_path=xmuse_root / "audit_events.json")
        self._provider_service = provider_service or RunnerProviderService(
            mcp_port=mcp_port,
            selection_record_store=ProviderSelectionRecordStore.from_xmuse_root(
                xmuse_root
            ),
            execution_provider_profile_ref=(
                execution_provider_profile_ref
                or "codex.default"
            ),
            review_provider_profile_ref=(
                review_provider_profile_ref
                or "codex.review"
            ),
        )
        self._provider_session_binding_store = (
            provider_session_binding_store
            or ProviderSessionBindingStore(xmuse_root / "provider_session_bindings.json")
        )
        self._feature_graph_status_store = (
            feature_graph_status_store
            or FeatureGraphStatusStore(xmuse_root / "feature_graph_statuses.json")
        )
        self._feature_graph_artifact_store = (
            feature_graph_artifact_store
            or FeatureGraphArtifactStore(xmuse_root / "feature_graph_artifacts.json")
        )
        self._feature_graph_max_rework_attempts = feature_graph_max_rework_attempts
        self._spawner = AgentSpawner(
            repo_root=xmuse_root,
            mcp_port=mcp_port,
            memoryos_client=memoryos_client,
            provider_service=self._provider_service,
            on_process_start=self._record_worker_lease,
        )
        self._transport = SpawnerTransport(self._spawner)
        self._review_god_session_layer = review_god_session_layer
        self._runner_id = runner_id or f"runner-{os.getpid()}"
        self._repo_root = repo_root or xmuse_root.parent
        self._persistent_review_receive_timeout_s = persistent_review_receive_timeout_s
        self._default_review_peer_routing_enabled = default_review_peer_routing_enabled
        self._persistent_execute_enabled = persistent_execute_enabled
        self._persistent_execute_session_layer = persistent_execute_session_layer
        self._model_policy = model_policy
        self._execution_provider_profile_ref = execution_provider_profile_ref
        self._review_provider_profile_ref = review_provider_profile_ref
        self._root = xmuse_root
        self._graph_store = LaneGraphStore(self._root / "lane_graphs")
        self._require_final_action_approval = require_final_action_approval
        self._final_action_store = FinalActionGateStore(self._root / "final_actions.json")
        self._recovery = RecoveryManager(
            _orchestrator_recovery_config(),
            observer=self._observe_recovery_event,
            async_sleep=asyncio.sleep,
        )
        self._review_plane = ReviewPlaneController(
            lanes_path=lanes_path,
            store_path=self._root / "review_plane.json",
            final_actions_path=self._root / "final_actions.json",
            clarification_store_path=self._root / "clarifications.json",
            require_final_action_approval=require_final_action_approval,
        )
        runtime = _resolve_god_runtime(god_runtime)
        self._runtime_mode = runtime
        self._execution_god = _execution_god(
            runtime,
            model=model_policy.coordinator_model if model_policy is not None else None,
            worker_model=model_policy.worker_model if model_policy is not None else None,
            delegation_mode=(
                model_policy.delegation_mode if model_policy is not None else None
            ),
        )
        self._review_god = _review_god(
            runtime,
            model=model_policy.review_model if model_policy is not None else None,
        )
        self._memory_store = (
            MemoryOSStoreAdapter(memoryos_client) if memoryos_client is not None else None
        )
        self._execution_gods = [self._execution_god]
        self._review_gods = [self._review_god]
        self._god_picker = GodPicker(
            runtime_mode=runtime,
            execution_gods=self._execution_gods,
            review_gods=self._review_gods,
            lane_reader=self._sm.get_lane,
        )
        self._tools = McpToolHandler(
            state_machine=self._sm,
            xmuse_root=xmuse_root,
            on_status_change=self._on_mcp_status_change,
        )
        self._bus.subscribe("lane_reviewed", self._handle_lane_reviewed)
        self._bus.subscribe("lane_rejected", self._handle_lane_rejected)
        self._bus.subscribe("lane_reworking", self._handle_lane_reworking)
        self._bus.subscribe("lane_executed", self._handle_lane_executed)

    def _record_worker_lease(
        self,
        lane_id: str,
        process_pid: int,
        command: list[str],
        worktree: Path,
    ) -> None:
        self._sm.update_metadata(
            lane_id,
            {
                "worker_pid": process_pid,
                "worker_started_at": time.time(),
                "worker_heartbeat_at": time.time(),
                "worker_command": command,
                "worker_worktree": str(worktree),
            },
        )

    def _observe_recovery_event(self, event: RecoveryEvent) -> None:
        log_event(
            logger,
            logging.INFO,
            "orchestrator_recovery_event",
            recovery_event=event.to_payload(),
        )

    def _lane_recovery_observer(self, lane_id: str):
        def _observe(event: RecoveryEvent) -> None:
            try:
                lane = self._sm.get_lane(lane_id)
            except KeyError:
                log_event(
                    logger,
                    logging.INFO,
                    "lane_recovery_event_missing_lane",
                    lane_id=lane_id,
                    recovery_event=event.to_payload(),
                )
                return
            history = lane.get("recovery_events", [])
            if not isinstance(history, list):
                history = []
            history = [*history[-19:], event.to_payload()]
            self._sm.update_metadata(
                lane_id,
                {
                    "recovery_events": history,
                    "last_recovery_event": event.to_payload(),
                },
            )

        return _observe

    def _on_mcp_status_change(self, lane_id: str, new_status: str) -> None:
        event_map = {
            "executed": "lane_executed",
            "exec_failed": "lane_exec_failed",
            "reviewed": "lane_reviewed",
            "rejected": "lane_rejected",
            "reworking": "lane_reworking",
            "gate_failed": "lane_gate_failed",
        }
        event = event_map.get(new_status)
        if event:
            with observability_context(lane_id=lane_id):
                log_event(
                    logger,
                    logging.INFO,
                    "mcp_status_change",
                    lane_id=lane_id,
                    status=new_status,
                    event_name=event,
                )
                asyncio.get_event_loop().create_task(
                    self._bus.publish(
                        event,
                        {
                            "lane_id": lane_id,
                            "observability": current_observability_context(),
                        },
                    )
                )

    async def _handle_lane_reviewed(self, payload: dict[str, Any]) -> None:
        context = payload.get("observability")
        with observability_context(
            trace_id=context.get("trace_id") if isinstance(context, dict) else None,
            lane_id=str(payload["lane_id"]),
        ):
            await self.on_lane_reviewed(str(payload["lane_id"]))

    async def _handle_lane_rejected(self, payload: dict[str, Any]) -> None:
        context = payload.get("observability")
        with observability_context(
            trace_id=context.get("trace_id") if isinstance(context, dict) else None,
            lane_id=str(payload["lane_id"]),
        ):
            await self.on_lane_rejected(str(payload["lane_id"]))

    async def _handle_lane_reworking(self, payload: dict[str, Any]) -> None:
        context = payload.get("observability")
        with observability_context(
            trace_id=context.get("trace_id") if isinstance(context, dict) else None,
            lane_id=str(payload["lane_id"]),
        ):
            lane_id = str(payload["lane_id"])
            if self._sm.get_lane(lane_id).get("status") != "reworking":
                return
            await self.dispatch_lane(lane_id)

    async def _handle_lane_executed(self, payload: dict[str, Any]) -> None:
        context = payload.get("observability")
        with observability_context(
            trace_id=context.get("trace_id") if isinstance(context, dict) else None,
            lane_id=str(payload["lane_id"]),
        ):
            await self._on_lane_executed(str(payload["lane_id"]))

    def _should_retry_review(self, lane: dict[str, Any]) -> bool:
        if lane.get("gate_passed") is not True:
            return False

        failure_reason = lane.get("failure_reason")
        retry_count = int(lane.get("review_retry_count", 0))
        if failure_reason in {"review_timeout", "review_no_verdict"}:
            return retry_count < 2
        if failure_reason == "review_infra_unavailable":
            retry_after = lane.get("review_retry_after_at")
            if isinstance(retry_after, int | float) and time.time() < float(retry_after):
                return False
            return retry_count < 40
        return False

    async def _run_reconcile_lane_batch(
        self,
        lane_ids: list[str],
        handler: Any,
        *,
        operation: str,
    ) -> None:
        if not lane_ids:
            return
        concurrency = _reconcile_gate_review_concurrency_limit(total=len(lane_ids))

        if concurrency is None or concurrency >= len(lane_ids):
            results = await asyncio.gather(
                *(handler(lane_id) for lane_id in lane_ids),
                return_exceptions=True,
            )
            for lane_id, result in zip(lane_ids, results, strict=False):
                if isinstance(result, Exception):
                    log_event(
                        logger,
                        logging.WARNING,
                        "reconcile_lane_task_failed",
                        lane_id=lane_id,
                        operation=operation,
                        error_type=type(result).__name__,
                        error=str(result),
                    )
            return

        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(lane_id: str) -> None:
            async with semaphore:
                await handler(lane_id)

        results = await asyncio.gather(
            *(run_one(lane_id) for lane_id in lane_ids),
            return_exceptions=True,
        )
        for lane_id, result in zip(lane_ids, results, strict=False):
            if isinstance(result, Exception):
                log_event(
                    logger,
                    logging.WARNING,
                    "reconcile_lane_task_failed",
                    lane_id=lane_id,
                    operation=operation,
                    error_type=type(result).__name__,
                    error=str(result),
                )

    def _gated_review_needs_reconcile(
        self,
        lane: dict[str, Any],
        *,
        now: float,
    ) -> bool:
        if lane.get("gate_passed") is not True:
            return False
        if not lane.get("review_started_at"):
            return True
        review_runner_id = lane.get("review_runner_id")
        if review_runner_id != self._runner_id:
            return True
        started_at = lane.get("review_started_at")
        if not isinstance(started_at, int | float) or isinstance(started_at, bool):
            return True
        timeout_s = (
            self._persistent_review_receive_timeout_s
            if self._persistent_review_receive_timeout_s is not None
            else execution_review_god.PERSISTENT_REVIEW_RECEIVE_TIMEOUT_S
        )
        return now - float(started_at) > timeout_s

    async def reconcile_status_changes(self, *, dispatch_reworking: bool = True) -> None:
        with timed_core_operation(
            component="orchestrator",
            operation="reconcile_status_changes",
            logger=logger,
        ):
            current_time = time.time()
            stranded_gated_lanes = [
                lane
                for lane in _reconcile_candidate_lanes(
                    self,
                    graph_native_status=FeatureGraphExecutionStatus.REVIEWING,
                    legacy_statuses={"gated"},
                )
                if self._gated_review_needs_reconcile(lane, now=current_time)
            ]
            await self._run_reconcile_lane_batch(
                [
                    str(lane["feature_id"])
                    for lane in _reconcile_candidate_lanes(
                        self,
                        graph_native_status=FeatureGraphExecutionStatus.RUNNING,
                        legacy_statuses={"executed"},
                    )
                    if _graph_native_execution_authority_allows_lane(self, lane)
                ],
                self._on_lane_executed,
                operation="gate_executed_lane",
            )
            await self._run_reconcile_lane_batch(
                [
                    str(lane["feature_id"])
                    for lane in stranded_gated_lanes
                    if self._sm.get_lane(str(lane["feature_id"])).get("status")
                    == "gated"
                    and _graph_native_review_authority_allows_lane(self, lane)
                ],
                self._run_review_god,
                operation="review_gated_lane",
            )
            for lane in _reconcile_candidate_lanes(
                self,
                graph_native_status=FeatureGraphExecutionStatus.REVIEWING,
                legacy_statuses={"reviewed"},
            ):
                if _merge_retry_after_is_active(lane, now=current_time):
                    continue
                if not _graph_native_review_authority_allows_lane(self, lane):
                    continue
                await self.on_lane_reviewed(str(lane["feature_id"]))
            for lane in _reconcile_candidate_lanes(
                self,
                graph_native_status=FeatureGraphExecutionStatus.REVIEWING,
                legacy_statuses={"rejected"},
            ):
                if not _graph_native_review_authority_allows_lane(self, lane):
                    continue
                await self.on_lane_rejected(str(lane["feature_id"]))
            if dispatch_reworking:
                for lane in _reconcile_candidate_lanes(
                    self,
                    graph_native_status=FeatureGraphExecutionStatus.REWORKING,
                    legacy_statuses={"reworking"},
                    graph_backed_operational_statuses={"pending", "reworking"},
                ):
                    lane_id = str(lane["feature_id"])
                    if not _graph_native_dispatch_authority_allows_lane(self, lane):
                        continue
                    if self._sm.get_lane(lane_id).get("status") in {
                        "pending",
                        "reworking",
                    }:
                        await self.dispatch_lane(lane_id)
            for lane in _reconcile_candidate_lanes(
                self,
                graph_native_status=FeatureGraphExecutionStatus.REVIEWING,
                legacy_statuses={"gate_failed"},
            ):
                if self._should_retry_review(lane):
                    if not _graph_native_review_authority_allows_lane(self, lane):
                        continue
                    lane_id = str(lane["feature_id"])
                    failure_reason = str(lane.get("failure_reason", "review_failed"))
                    review_retries = int(lane.get("review_retry_count", 0)) + 1
                    self._sm.transition(
                        lane_id,
                        "gated",
                        metadata={
                            "review_retry_count": review_retries,
                            "review_recovered_from": failure_reason,
                        },
                    )
                    await self._run_review_god(lane_id)
            for lane in _reconcile_candidate_lanes(
                self,
                graph_native_status=FeatureGraphExecutionStatus.MERGED,
                legacy_statuses={"merged"},
            ):
                if not _graph_native_reprojection_authority_allows_lane(
                    self,
                    lane,
                    expected_status=FeatureGraphExecutionStatus.MERGED,
                ):
                    continue
                await reproject_dependents_if_needed(
                    str(lane["feature_id"]),
                    sm=self._sm,
                    graph_store=self._graph_store,
                )
            for lane in _reconcile_candidate_lanes(
                self,
                graph_native_status=FeatureGraphExecutionStatus.FAILED,
                legacy_statuses={"failed"},
            ):
                if not _graph_native_reprojection_authority_allows_lane(
                    self,
                    lane,
                    expected_status=FeatureGraphExecutionStatus.FAILED,
                ):
                    continue
                await reproject_dependents_if_needed(
                    str(lane["feature_id"]),
                    sm=self._sm,
                    graph_store=self._graph_store,
                )

    async def dispatch_lane(self, lane_id: str) -> None:
        return await dispatch_lane_flow(self, lane_id)

    def claim_next_ready_feature_graph_worker(
        self,
        *,
        worker_session_id: str,
        provider_session_binding_ref: str | None,
        updated_at: str,
        graph_set_id: str | None = None,
        conversation_id: str | None = None,
        feature_graph_id: str | None = None,
    ) -> FeatureGraphWorkerClaimOutcome | None:
        return claim_next_ready_feature_graph_worker_flow(
            store=self._feature_graph_status_store,
            worker_session_id=worker_session_id,
            provider_session_binding_ref=provider_session_binding_ref,
            updated_at=updated_at,
            graph_set_id=graph_set_id,
            conversation_id=conversation_id,
            feature_graph_id=feature_graph_id,
        )

    def submit_feature_graph_worker_evidence(
        self,
        *,
        evidence_bundle: FeatureEvidenceBundle,
        evidence_bundle_ref: str,
        updated_at: str,
    ) -> FeatureGraphWorkerEvidenceSubmissionOutcome:
        return submit_feature_graph_worker_evidence_flow(
            store=self._feature_graph_status_store,
            evidence_bundle=evidence_bundle,
            evidence_bundle_ref=evidence_bundle_ref,
            updated_at=updated_at,
            artifact_store=self._feature_graph_artifact_store,
        )

    def submit_feature_graph_review_verdict(
        self,
        *,
        evidence_bundle: FeatureEvidenceBundle,
        verdict: FeatureReviewVerdict,
        updated_at: str,
    ) -> FeatureGraphReviewVerdictOutcome:
        return submit_feature_graph_review_verdict_flow(
            store=self._feature_graph_status_store,
            evidence_bundle=evidence_bundle,
            verdict=verdict,
            updated_at=updated_at,
            artifact_store=self._feature_graph_artifact_store,
            max_rework_attempts=self._feature_graph_max_rework_attempts,
        )

    def submit_feature_graph_patch_forward_gate_result(
        self,
        *,
        plan_id: str,
        result: FeatureGraphPatchForwardGateResult,
    ) -> FeatureGraphPatchForwardGateResultOutcome:
        return submit_patch_forward_gate_result_flow(
            artifact_store=self._feature_graph_artifact_store,
            plan_id=plan_id,
            result=result,
        )

    def submit_feature_graph_patch_forward_merge_guard_decision(
        self,
        *,
        handoff_id: str,
        merge_guard_ref: str,
        merge_guard_evidence_refs: list[str],
        passed: bool,
        failure_reasons: list[str] | None,
        checked_at: str,
    ) -> FeatureGraphPatchForwardMergeGuardDecisionOutcome:
        return submit_pf_merge_guard_decision_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            handoff_id=handoff_id,
            merge_guard_ref=merge_guard_ref,
            merge_guard_evidence_refs=merge_guard_evidence_refs,
            passed=passed,
            failure_reasons=failure_reasons,
            checked_at=checked_at,
        )

    def apply_feature_graph_patch_forward_merge_guard_decision_status(
        self,
        *,
        decision_id: str,
        updated_at: str,
    ) -> FeatureGraphPatchForwardStatusTransitionOutcome:
        return apply_pf_status_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            decision_id=decision_id,
            updated_at=updated_at,
        )

    def release_ready_feature_graph_dependents(
        self,
        *,
        graph_set: FeatureGraphSet,
        updated_at: str,
    ) -> FeatureGraphDependentReleaseOutcome:
        return release_ready_feature_graph_dependents_flow(
            store=self._feature_graph_status_store,
            graph_set=graph_set,
            updated_at=updated_at,
        )

    def apply_feature_graph_rework_packet_status(
        self,
        *,
        rework_id: str,
        updated_at: str,
    ) -> FeatureGraphReworkStatusApplicationOutcome:
        return apply_rework_packet_status_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            rework_id=rework_id,
            updated_at=updated_at,
        )

    def submit_feature_graph_takeover_decision(
        self,
        *,
        plan_id: str,
        approved: bool,
        takeover_worker_session_id: str | None,
        takeover_provider_session_binding_ref: str | None,
        gate_refs: list[str] | None,
        failure_reasons: list[str] | None,
        checked_at: str,
    ) -> FeatureGraphTakeoverDecisionOutcome:
        return submit_takeover_decision_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            plan_id=plan_id,
            approved=approved,
            takeover_worker_session_id=takeover_worker_session_id,
            takeover_provider_session_binding_ref=takeover_provider_session_binding_ref,
            gate_refs=gate_refs,
            failure_reasons=failure_reasons,
            checked_at=checked_at,
        )

    def submit_feature_graph_takeover_outcome(
        self,
        *,
        handoff_id: str,
        changed_file_refs: list[str] | None,
        evidence_refs: list[str] | None,
        verification_refs: list[str] | None,
        output_summary: str,
        completed: bool,
        failure_reasons: list[str] | None,
        created_at: str,
    ) -> FeatureGraphTakeoverWorkerOutcome:
        return submit_takeover_outcome_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            handoff_id=handoff_id,
            changed_file_refs=changed_file_refs,
            evidence_refs=evidence_refs,
            verification_refs=verification_refs,
            output_summary=output_summary,
            completed=completed,
            failure_reasons=failure_reasons,
            created_at=created_at,
        )

    def submit_feature_graph_takeover_followup_review_verdict(
        self,
        *,
        review_handoff_id: str,
        verdict: FeatureReviewVerdict,
    ) -> FeatureGraphTakeoverFollowupReviewVerdictOutcome:
        return submit_takeover_followup_verdict_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            review_handoff_id=review_handoff_id,
            verdict=verdict,
        )

    def apply_feature_graph_takeover_followup_review_verdict(
        self,
        *,
        review_handoff_id: str,
        verdict_id: str,
        updated_at: str,
    ) -> FeatureGraphTakeoverFollowupReviewApplicationOutcome:
        return apply_takeover_followup_verdict_flow(
            artifact_store=self._feature_graph_artifact_store,
            status_store=self._feature_graph_status_store,
            review_handoff_id=review_handoff_id,
            verdict_id=verdict_id,
            updated_at=updated_at,
            max_rework_attempts=self._feature_graph_max_rework_attempts,
        )

    def _ensure_lane_worktree(self, lane: dict[str, Any]) -> dict[str, Any]:
        return ensure_lane_worktree_flow(self, lane)

    def _create_or_reuse_worktree(self, *, worktree: Path, branch: str) -> None:
        return create_or_reuse_worktree_flow(self, worktree=worktree, branch=branch)

    async def _run_execution_god(self, lane_id: str) -> None:
        await run_execution_god_flow(self, lane_id)

    def record_feature_graph_provider_binding_degradation_from_lane(
        self,
        *,
        lane_id: str,
        updated_at: str,
        compatibility_bridge_enabled: bool = False,
    ) -> FeatureGraphProviderBindingDegradationOutcome | None:
        lane = self._sm.get_lane(lane_id)
        try:
            return record_feature_graph_provider_binding_degradation_from_lane(
                store=self._feature_graph_status_store,
                lane=lane,
                updated_at=updated_at,
                compatibility_bridge_enabled=compatibility_bridge_enabled,
            )
        except (KeyError, ValueError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "feature_graph_provider_binding_degradation_record_failed",
                lane_id=lane_id,
                graph_id=_lane_graph_id(lane),
                error=str(exc),
            )
            return None

    def record_feature_graph_provider_binding_degradation(
        self,
        *,
        lane_id: str,
        binding_id: str,
        reason: str,
        updated_at: str,
        failure: str | None = None,
    ) -> FeatureGraphProviderBindingDegradationOutcome | None:
        lane = self._sm.get_lane(lane_id)
        graph_set_id = lane.get("graph_set_id")
        feature_graph_id = _lane_graph_id(lane)
        if not graph_set_id or not feature_graph_id:
            return None
        try:
            return record_feature_graph_provider_binding_degradation(
                store=self._feature_graph_status_store,
                graph_set_id=str(graph_set_id),
                feature_graph_id=feature_graph_id,
                binding_id=binding_id,
                reason=reason,
                failure=failure,
                evidence_refs=[
                    f"runtime:execution_god:lane={lane_id}",
                    binding_id,
                ],
                updated_at=updated_at,
            )
        except (KeyError, ValueError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "feature_graph_provider_binding_degradation_record_failed",
                lane_id=lane_id,
                graph_id=feature_graph_id,
                error=str(exc),
            )
            return None

    def reconcile_feature_graph_provider_binding_degradations(
        self,
        *,
        updated_at: str,
        compatibility_bridge_enabled: bool = False,
    ) -> list[FeatureGraphProviderBindingDegradationOutcome]:
        return reconcile_feature_graph_provider_binding_degradations(
            store=self._feature_graph_status_store,
            lanes=self._sm.get_lanes(),
            updated_at=updated_at,
            compatibility_bridge_enabled=compatibility_bridge_enabled,
        )

    async def _on_lane_executed(self, lane_id: str) -> None:
        return await on_lane_executed_flow(self, lane_id)

    async def _run_review_god(self, lane_id: str) -> None:
        return await run_review_god_flow(self, lane_id)

    def _open_review_task(self, lane_id: str) -> None:
        return open_review_task_flow(self, lane_id)

    async def on_lane_reviewed(self, lane_id: str) -> None:
        lane = self._sm.get_lane(lane_id)
        with observability_context(
            lane_id=lane_id,
            graph_id=_lane_graph_id(lane),
        ), timed_core_operation(
            component="orchestrator",
            operation="on_lane_reviewed",
            logger=logger,
            lane_id=lane_id,
        ):
            return await self._on_lane_reviewed_inner(lane_id, lane)

    async def _on_lane_reviewed_inner(self, lane_id: str, lane: dict[str, Any]) -> None:
        return await on_lane_reviewed_inner_flow(self, lane_id, lane)

    async def _record_lane_memory_event(
        self,
        lane_id: str,
        lane: dict[str, Any],
        *,
        event: str,
    ) -> None:
        return await record_lane_memory_event_flow(self, lane_id, lane, event=event)

    async def _auto_merge(self, lane_id: str, worktree: Path) -> bool:
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="orchestrator",
            operation="auto_merge",
            logger=logger,
            lane_id=lane_id,
        ):
            lane = self._sm.get_lane(lane_id)
            merged = await execution_merger.auto_merge(
                lane_id=lane_id, lane=lane, worktree=worktree
            )
            if not merged and lane.get("merge_failure_reason"):
                metadata = {"merge_failure_reason": str(lane["merge_failure_reason"])}
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
                self._sm.update_metadata(lane_id, metadata)
            return merged

    async def on_lane_rejected(self, lane_id: str) -> None:
        lane = self._sm.get_lane(lane_id)
        with observability_context(
            lane_id=lane_id,
            graph_id=_lane_graph_id(lane),
        ), timed_core_operation(
            component="orchestrator",
            operation="on_lane_rejected",
            logger=logger,
            lane_id=lane_id,
        ):
            retries = lane.get("retry_count", 0)
            if retries >= 2:
                self._sm.transition(lane_id, "failed")
                log_event(logger, logging.INFO, "lane_failed_after_max_retries", lane_id=lane_id)
                return
            self._sm.transition(lane_id, "reworking")
            await self.dispatch_lane(lane_id)

    async def _run_gate(self, lane_id: str) -> bool:
        lane = self._sm.get_lane(lane_id)
        with observability_context(
            lane_id=lane_id,
            graph_id=_lane_graph_id(lane),
        ), timed_core_operation(
            component="orchestrator",
            operation="run_gate",
            logger=logger,
            lane_id=lane_id,
        ):
            return await execution_gate.run_gate(
                lane_id=lane_id,
                lane=lane,
                root=self._root,
            )

    def _write_lane_context_bundle(
        self,
        lane: dict[str, Any],
        *,
        all_lanes: list[dict[str, Any]] | None = None,
    ) -> None:
        lane_id = str(lane.get("feature_id", "unknown"))
        try:
            write_lane_context_bundle(
                lane,
                xmuse_root=self._root,
                all_lanes=all_lanes,
            )
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "lane_context_bundle_write_failed",
                lane_id=lane_id,
                exc_info=True,
            )

    def verdict_lineage_for_lane(self, lane_id: str) -> list[dict[str, Any]]:
        """Return the full task→verdict lineage for *lane_id* from the review plane."""
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="orchestrator",
            operation="verdict_lineage_for_lane",
            logger=logger,
            lane_id=lane_id,
        ):
            return self._review_plane.verdict_lineage_for_lane(lane_id)

    def verdict_lineage_for_run(self, graph_id: str) -> list[dict[str, Any]]:
        """Return the full task→verdict lineage for every lane in *graph_id*.

        Delegates to :meth:`ReviewPlaneController.verdict_lineage_for_run` so
        callers can audit the complete review history for a run without
        accessing the review plane directly.
        """
        with observability_context(graph_id=graph_id), timed_core_operation(
            component="orchestrator",
            operation="verdict_lineage_for_run",
            logger=logger,
            graph_id=graph_id,
        ):
            return self._review_plane.verdict_lineage_for_run(graph_id)

    def _load_lane_graph_if_available(self, graph_id: str) -> LaneGraph | None:
        try:
            return self._graph_store.get(graph_id)
        except KeyError:
            return None

    def aggregate_run_terminal_status(self, graph_id: str) -> RunTerminalAggregation:
        """Compute the run-level terminal status for *graph_id*.

        Delegates to :meth:`ReviewPlaneController.aggregate_run_terminal_status`
        with the orchestrator's final-action store so that pending holds are
        included in the aggregation.

        Returns a :class:`RunTerminalAggregation` with the computed status
        (``merged | terminated | blocked_for_input | in_progress``) and the
        full set of inputs used to reach that decision.
        """
        with observability_context(graph_id=graph_id), timed_core_operation(
            component="orchestrator",
            operation="aggregate_run_terminal_status",
            logger=logger,
            graph_id=graph_id,
        ):
            lane_graph = self._load_lane_graph_if_available(graph_id)
            return self._review_plane.aggregate_run_terminal_status(
                graph_id,
                lane_graph=lane_graph,
                final_action_store=self._final_action_store,
            )

    def assemble_evidence_bundle(
        self,
        graph_id: str,
        *,
        evidence_store: EvidenceBundleStore | None = None,
        selection_policy_id: str = "default-v1",
        selection_policy_version: str = "1",
    ) -> StructuredEvidenceBundle:
        """Assemble a StructuredEvidenceBundle from a terminal run.

        Delegates to :meth:`ReviewPlaneController.assemble_evidence_bundle`
        with the orchestrator's final-action store so that pending holds are
        included in the aggregation.

        The bundle is persisted in *evidence_store* when provided.

        Returns a :class:`StructuredEvidenceBundle` containing the curated
        summary view and full primary references for every cited item.
        """
        with observability_context(graph_id=graph_id), timed_core_operation(
            component="orchestrator",
            operation="assemble_evidence_bundle",
            logger=logger,
            graph_id=graph_id,
        ):
            lane_graph = self._load_lane_graph_if_available(graph_id)
            return self._review_plane.assemble_evidence_bundle(
                graph_id,
                lane_graph=lane_graph,
                final_action_store=self._final_action_store,
                evidence_store=evidence_store,
                selection_policy_id=selection_policy_id,
                selection_policy_version=selection_policy_version,
            )

    def has_verdict_lineage(self, lane_id: str) -> bool:
        """Return True if *lane_id* has at least one finalized verdict in the review plane."""
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="orchestrator",
            operation="has_verdict_lineage",
            logger=logger,
            lane_id=lane_id,
        ):
            return self._review_plane.has_verdict_lineage(lane_id)
