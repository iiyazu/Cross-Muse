"""Lane execution and review flow helpers for PlatformOrchestrator."""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

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
    ingest_review_failure_verdict,
    ingest_rework_verdict,
    stable_verdict_id_for_lane,
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


def _repo_root_for(orchestrator) -> Path:
    return Path(getattr(orchestrator, "_repo_root", orchestrator._root.parent))


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


def _graph_native_dispatch_authority_allows_lane(orchestrator, lane: dict[str, Any]) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return True
    lane_id = str(lane["feature_id"])
    if status.status is FeatureGraphExecutionStatus.REWORKING:
        return True
    if status.status is FeatureGraphExecutionStatus.READY:
        return lane_id in status.ready_lane_ids
    if status.status is FeatureGraphExecutionStatus.RUNNING:
        return lane_id in status.active_lane_ids
    return False


def _graph_native_review_authority_allows_lane(orchestrator, lane: dict[str, Any]) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return True
    return status.status is FeatureGraphExecutionStatus.REVIEWING


def _graph_native_execution_authority_allows_lane(orchestrator, lane: dict[str, Any]) -> bool:
    status = _graph_native_status_record(orchestrator, lane)
    if status is None:
        return True
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
        return True
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
        metadata = {
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
    existing_worktree_path = (
        Path(str(existing_worktree)) if existing_worktree else None
    )
    branch = str(existing_branch or _safe_lane_ref(lane_id))
    worktree = existing_worktree_path or (
        _compat_symbol(orchestrator, "WORKTREE_BASE", WORKTREE_BASE)
        / _safe_lane_ref(lane_id)
    )
    git_output = _compat_symbol(orchestrator, "_git_output", _git_output)
    if not worktree.exists():
        base_head_sha = lane.get("base_head_sha") or git_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_repo_root_for(orchestrator),
        )
        orchestrator._create_or_reuse_worktree(worktree=worktree, branch=branch)
    else:
        if _is_reclaimable_placeholder_worktree(worktree):
            base_head_sha = lane.get("base_head_sha") or git_output(
                ["git", "rev-parse", "HEAD"],
                cwd=_repo_root_for(orchestrator),
            )
            orchestrator._create_or_reuse_worktree(worktree=worktree, branch=branch)
        else:
            base_head_sha = lane.get("base_head_sha")
        branch, is_git_worktree = _ensure_existing_worktree_branch(worktree, branch)
        base_head_sha = (
            None if base_head_sha == "unknown" else base_head_sha
        ) or _worktree_head_sha(worktree)
        if base_head_sha is None:
            if existing_worktree and not is_git_worktree:
                base_head_sha = "unknown"
            else:
                base_head_sha = git_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=_repo_root_for(orchestrator),
                )
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


def _is_reclaimable_placeholder_worktree(worktree: Path) -> bool:
    if not worktree.exists() or not worktree.is_dir():
        return False
    if _worktree_head_sha(worktree) is not None:
        return False
    entries = list(worktree.iterdir())
    if not entries:
        return True
    return all(entry.name == ".pytest_cache" for entry in entries)


def _ensure_existing_worktree_branch(worktree: Path, branch: str) -> tuple[str, bool]:
    git_check = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if git_check.returncode != 0:
        return branch, False

    current = subprocess.run(
        ["git", "-C", str(worktree), "branch", "--show-current"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    current_branch = current.stdout.strip() if current.returncode == 0 else ""
    if current_branch:
        return current_branch, True

    checkout = subprocess.run(
        ["git", "-C", str(worktree), "checkout", "-B", branch],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if checkout.returncode != 0:
        raise RuntimeError(
            "failed to attach existing lane worktree to branch "
            f"{branch}: {checkout.stderr.strip()}"
        )
    return branch, True


def _worktree_head_sha(worktree: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def create_or_reuse_worktree(orchestrator, *, worktree: Path, branch: str) -> None:
    if worktree.exists():
        if not _is_reclaimable_placeholder_worktree(worktree):
            return
        shutil.rmtree(worktree)
    repo_root = _repo_root_for(orchestrator)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        return
    fallback = subprocess.run(
        ["git", "worktree", "add", str(worktree), branch],
        cwd=repo_root,
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
        orchestrator._sm.update_metadata(
            lane_id,
            {"provider_profile_ref": provider_invocation.provider_profile_ref},
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
            orchestrator._sm.transition(
                lane_id,
                "gate_failed",
                metadata={"gate_passed": False, "failure_reason": "gate_failed"},
            )

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
        review_god_config = GodConfig(
            name=god.name,
            runtime=orchestrator._provider_service.runtime_for_invocation(
                provider_invocation
            ),
            timeout_s=god.timeout_s,
            skill_prompt_path=god.skill_prompt_path,
            model=provider_model,
        )
        try:
            await execution_review_god.run_review_god(
                lane_id=lane_id,
                lane=lane,
                god=review_god_config,
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
                open_review_task=lambda target_lane_id: open_review_task_for_attempt(
                    orchestrator,
                    target_lane_id,
                    god=review_god_config,
                ),
                stable_verdict_id=lambda target_lane_id: stable_verdict_id_for_lane(
                    target_lane_id,
                    lane=orchestrator._sm.get_lane(target_lane_id),
                ),
                ingest_merge_verdict=lambda target_lane_id, summary, evidence_refs=None: (
                    ingest_merge_verdict(
                        target_lane_id,
                        summary,
                        lane=orchestrator._sm.get_lane(target_lane_id),
                        review_plane=orchestrator._review_plane,
                        evidence_refs=evidence_refs,
                    )
                ),
                ingest_rework_verdict=lambda target_lane_id, summary, evidence_refs=None: (
                    ingest_rework_verdict(
                        target_lane_id,
                        summary,
                        lane=orchestrator._sm.get_lane(target_lane_id),
                        review_plane=orchestrator._review_plane,
                        evidence_refs=evidence_refs,
                    )
                ),
                ingest_review_failure_verdict=(
                    lambda target_lane_id, reason, evidence_refs: ingest_review_failure_verdict(
                        target_lane_id,
                        reason,
                        lane=orchestrator._sm.get_lane(target_lane_id),
                        review_plane=orchestrator._review_plane,
                        evidence_refs=evidence_refs,
                    )
                ),
                on_reviewed=orchestrator.on_lane_reviewed,
                on_rejected=orchestrator.on_lane_rejected,
                provider_invocation=provider_invocation,
                provider_session_binding=session_route.provider_session_binding,
                provider_session_binding_writer=orchestrator._provider_session_binding_store,
            )
        except asyncio.CancelledError:
            mark_review_task_interrupted(
                orchestrator,
                lane_id,
                reason="review_interrupted",
                evidence_refs=[],
            )
            raise

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


def open_review_task_for_attempt(
    orchestrator,
    lane_id: str,
    *,
    god: GodConfig,
) -> None:
    open_review_task(orchestrator, lane_id)
    try:
        lane = orchestrator._sm.get_lane(lane_id)
        task_id = lane.get("review_task_id")
        if not isinstance(task_id, str) or not task_id:
            return
        orchestrator._review_plane.mark_review_task_in_progress(
            task_id,
            review_attempt_id=_optional_text(lane.get("review_attempt_id")),
            runner_id=_optional_text(lane.get("review_runner_id")),
            provider_runtime=god.runtime,
            provider_model=god.model,
        )
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "review_plane_mark_in_progress_failed",
            lane_id=lane_id,
        )


def mark_review_task_interrupted(
    orchestrator,
    lane_id: str,
    *,
    reason: str,
    evidence_refs: list[str] | None = None,
) -> None:
    try:
        lane = orchestrator._sm.get_lane(lane_id)
        task_id = lane.get("review_task_id")
        if not isinstance(task_id, str) or not task_id:
            return
        orchestrator._review_plane.mark_review_task_interrupted(
            task_id,
            reason=reason,
            evidence_refs=evidence_refs,
        )
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "review_plane_mark_interrupted_failed",
            lane_id=lane_id,
            reason=reason,
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
        metadata = {
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
                orchestrator._sm.transition(lane_id, "reworking", metadata=metadata)
            except InvalidTransitionError:
                orchestrator._sm.transition(lane_id, "failed", metadata=metadata)
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
            log_event(
                logger,
                logging.WARNING,
                "lane_merge_conflict_reworking",
                lane_id=lane_id,
            )
            await orchestrator.dispatch_lane(lane_id)
            return
        orchestrator._sm.transition(lane_id, "failed", metadata=metadata)
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
    event: str,
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
