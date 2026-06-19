from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_identity import (
    MissingGodFeatureIdentity,
    build_persistent_god_identity,
    feature_scope_id_from_lane,
)
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.persistent_peer import PersistentCliPeerService
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime, SessionConfig
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.observability import log_event
from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.execution import persistent_review_context, persistent_review_delivery
from xmuse_core.platform.execution.persistent_review_session import (
    ConfiguredReviewPeerAttempt,
    PersistentReviewSessionLayer,
)
from xmuse_core.platform.execution.review import (
    infer_review_fallback,
    is_spawn_transient,
    review_infra_failure_reason,
    review_infra_reason_from_exception,
    spawn_result_transient,
)
from xmuse_core.platform.messages import ReviewRequest, Transport
from xmuse_core.platform.review_summary_safety import sanitize_review_summary
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.adapters.base import ProviderFailureKind, ProviderInvocation
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderProfileId
from xmuse_core.providers.registry import DEFAULT_CODEX_REVIEW_MODEL_ID, normalize_codex_model_id
from xmuse_core.self_evolution.recovery import (
    CircuitOpenError,
    RecoveryEvent,
    RecoveryManager,
)
from xmuse_core.structuring.feature_review_contracts import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)
from xmuse_core.structuring.models import ReviewDecision

logger = logging.getLogger(__name__)

_COMPONENT = "orchestrator.review_god"
REVIEW_INFRA_RETRY_DELAY_S = 15 * 60
PERSISTENT_REVIEW_RECEIVE_TIMEOUT_S = 30 * 60.0
_REVIEW_ROLE = "review"
_PERSISTENT_REVIEW_LOCKS: dict[str, asyncio.Lock] = {}
_DEFAULT_REVIEW_PEER_LOCKS: dict[str, asyncio.Lock] = {}
_CONFIGURED_REVIEW_PEER_LOCKS: dict[str, asyncio.Lock] = {}

_persistent_peer_prompt_fingerprint = (
    persistent_review_context.persistent_peer_prompt_fingerprint
)
_persistent_peer_session_prompt = persistent_review_context.persistent_peer_session_prompt
_persistent_review_context = persistent_review_context.persistent_review_context
_persistent_review_prompt = persistent_review_context.persistent_review_prompt
_persistent_review_request_degraded_reason = (
    persistent_review_context.persistent_review_request_degraded_reason
)
_persistent_review_session_prompt_contract = (
    persistent_review_context.persistent_review_session_prompt_contract
)
_persistent_review_worktree = persistent_review_context.persistent_review_worktree
_review_request_id = persistent_review_context.review_request_id
_safe_session_fragment = persistent_review_context.safe_session_fragment
PersistentReviewReceiveError = persistent_review_delivery.PersistentReviewReceiveError
_apply_persistent_review_message = persistent_review_delivery.apply_persistent_review_message
_persistent_verdict_payload = persistent_review_delivery.persistent_verdict_payload
_receive_persistent_review_result = (
    persistent_review_delivery.receive_persistent_review_result
)
_record_persistent_review_degraded = (
    persistent_review_delivery.record_persistent_review_degraded
)
_review_metadata = persistent_review_delivery.review_metadata

def _record_spawn_outcome(
    lane_id: str,
    result: Any,
    recovery: RecoveryManager,
    observer: Callable[[RecoveryEvent], None],
) -> None:
    if result.timed_out or spawn_result_transient(result):
        recovery.circuit(_COMPONENT).record_failure()
        if recovery.circuit(_COMPONENT).state.value == "open":
            observer(
                RecoveryEvent(
                    component=_COMPONENT,
                    operation="spawn",
                    kind="circuit_opened",
                    attempt=1,
                    max_attempts=recovery.config.max_attempts,
                    error_type="SpawnResult",
                    error=result.stderr or result.stdout or "review spawn failed",
                    circuit_state="open",
                )
            )
        observer(
            RecoveryEvent(
                component=_COMPONENT,
                operation="spawn",
                kind="operation_failed",
                attempt=1,
                max_attempts=recovery.config.max_attempts,
                error_type="SpawnResult",
                error=result.stderr or result.stdout or "review spawn failed",
                circuit_state=recovery.circuit(_COMPONENT).state.value,
            )
        )
    else:
        recovery.circuit(_COMPONENT).record_success()


async def run_review_god(
    *,
    lane_id: str,
    lane: dict[str, Any],
    god: GodConfig,
    prompt: str,
    worktree: Path,
    xmuse_root: Path,
    sm: LaneStateMachine,
    recovery: RecoveryManager,
    transport: Transport,
    persistent_session_layer: PersistentReviewSessionLayer | None = None,
    persistent_review_receive_timeout_s: float = PERSISTENT_REVIEW_RECEIVE_TIMEOUT_S,
    default_review_peer_routing_enabled: bool = False,
    observer: Callable[[RecoveryEvent], None],
    open_review_task: Callable[[str], Any],
    stable_verdict_id: Callable[[str], str],
    ingest_merge_verdict: Callable[[str, str, list[str] | None], None],
    ingest_rework_verdict: Callable[[str, str, list[str] | None], None],
    ingest_review_failure_verdict: Callable[[str, str, list[str]], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
    provider_invocation: ProviderInvocation | None = None,
    provider_session_binding: ProviderSessionBindingRecord | None = None,
    provider_session_binding_writer: Any | None = None,
) -> None:
    log_event(
        logger,
        logging.INFO,
        "review_god_started",
        lane_id=lane_id,
        god=god.name,
        god_runtime=god.runtime,
    )

    metadata = {
        "god": god.name,
        "review_started_at": time.time(),
    }
    if lane.get("status") != "gated":
        sm.transition(lane_id, "gated", metadata=metadata)
    else:
        sm.update_metadata(lane_id, metadata)

    open_review_task(lane_id)

    configured_peer_attempt = await _try_configured_review_peer(
        lane_id=lane_id,
        lane=lane,
        god=god,
        prompt=prompt,
        xmuse_root=xmuse_root,
        sm=sm,
        persistent_session_layer=persistent_session_layer,
        receive_timeout_s=persistent_review_receive_timeout_s,
        default_review_peer_routing_enabled=default_review_peer_routing_enabled,
        stable_verdict_id=stable_verdict_id,
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
    )
    if configured_peer_attempt.delivered or configured_peer_attempt.required_failed:
        return

    result = None
    if provider_session_binding is not None:
        result = await _send_review_request(
            lane_id=lane_id,
            god=god,
            prompt=prompt,
            worktree=worktree,
            sm=sm,
            recovery=recovery,
            transport=transport,
            observer=observer,
            on_reviewed=on_reviewed,
            on_rejected=on_rejected,
            ingest_rework_verdict=ingest_rework_verdict,
            provider_invocation=provider_invocation,
            provider_session_binding=provider_session_binding,
        )
        if result is None:
            return
        provider_result = result.provider_result
        if (
            provider_result is not None
            and provider_result.status is not WorkerResultStatus.COMPLETED
        ):
            _mark_failed_provider_session_binding(
                binding=provider_session_binding,
                writer=provider_session_binding_writer,
                failure_kind=provider_result.failure_kind,
            )
            if persistent_session_layer is not None:
                delivered = await _try_persistent_review(
                    lane_id=lane_id,
                    lane=lane,
                    god=god,
                    prompt=prompt,
                    worktree=worktree,
                    xmuse_root=xmuse_root,
                    sm=sm,
                    persistent_session_layer=persistent_session_layer,
                    receive_timeout_s=persistent_review_receive_timeout_s,
                    stable_verdict_id=stable_verdict_id,
                    ingest_merge_verdict=ingest_merge_verdict,
                    ingest_rework_verdict=ingest_rework_verdict,
                    on_reviewed=on_reviewed,
                    on_rejected=on_rejected,
                )
                if delivered:
                    return
            if configured_peer_attempt.attempted:
                sm.update_metadata(lane_id, {"peer_delivery_mode": "one_shot_fallback"})
            result = await _send_review_request(
                lane_id=lane_id,
                god=god,
                prompt=prompt,
                worktree=worktree,
                sm=sm,
                recovery=recovery,
                transport=transport,
                observer=observer,
                on_reviewed=on_reviewed,
                on_rejected=on_rejected,
                ingest_rework_verdict=ingest_rework_verdict,
                provider_invocation=provider_invocation,
                provider_session_binding=None,
            )
            if result is None:
                return

    if result is None and persistent_session_layer is not None:
        if configured_peer_attempt.attempted:
            sm.update_metadata(lane_id, {"peer_delivery_mode": "auto_persistent_fallback"})
        delivered = await _try_persistent_review(
            lane_id=lane_id,
            lane=lane,
            god=god,
            prompt=prompt,
            worktree=worktree,
            xmuse_root=xmuse_root,
            sm=sm,
            persistent_session_layer=persistent_session_layer,
            receive_timeout_s=persistent_review_receive_timeout_s,
            stable_verdict_id=stable_verdict_id,
            ingest_merge_verdict=ingest_merge_verdict,
            ingest_rework_verdict=ingest_rework_verdict,
            on_reviewed=on_reviewed,
            on_rejected=on_rejected,
        )
        if delivered:
            return

    if result is None:
        if configured_peer_attempt.attempted:
            sm.update_metadata(lane_id, {"peer_delivery_mode": "one_shot_fallback"})
        result = await _send_review_request(
            lane_id=lane_id,
            god=god,
            prompt=prompt,
            worktree=worktree,
            sm=sm,
            recovery=recovery,
            transport=transport,
            observer=observer,
            on_reviewed=on_reviewed,
            on_rejected=on_rejected,
            ingest_rework_verdict=ingest_rework_verdict,
            provider_invocation=provider_invocation,
            provider_session_binding=None,
        )
        if result is None:
            return

    await _handle_review_result(
        lane_id=lane_id,
        result=result,
        sm=sm,
        recovery=recovery,
        observer=observer,
        xmuse_root=xmuse_root,
        stable_verdict_id=stable_verdict_id,
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        ingest_review_failure_verdict=ingest_review_failure_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
    )


async def _send_review_request(
    *,
    lane_id: str,
    god: GodConfig,
    prompt: str,
    worktree: Path,
    sm: LaneStateMachine,
    recovery: RecoveryManager,
    transport: Transport,
    observer: Callable[[RecoveryEvent], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
    ingest_rework_verdict: Callable[[str, str], None],
    provider_invocation: ProviderInvocation | None,
    provider_session_binding: ProviderSessionBindingRecord | None,
):
    try:
        return await recovery.execute_async(
            _COMPONENT,
            "spawn",
            lambda: transport.send_review(
                ReviewRequest(
                    lane_id=lane_id,
                    prompt=prompt,
                    worktree=worktree,
                    evidence_refs=[],
                    god_config=god,
                    mcp_url=None,
                    provider_invocation=provider_invocation,
                    provider_session_binding=provider_session_binding,
                )
            ),
            is_transient=lambda exc: (
                False if _committed_review_status(sm, lane_id) else is_spawn_transient(exc)
            ),
            observer=observer,
        )
    except CircuitOpenError as exc:
        if await _honor_committed_review_state(
            lane_id=lane_id,
            sm=sm,
            ingest_rework_verdict=ingest_rework_verdict,
            on_reviewed=on_reviewed,
            on_rejected=on_rejected,
        ):
            return None
        sm.transition(
            lane_id,
            "gate_failed",
            metadata={
                "failure_reason": "review_infra_unavailable",
                "failure_layer": "review",
                "review_infra_reason": "circuit_open",
                "review_retry_after_at": time.time() + exc.retry_after_s,
                "degraded_component": "review_god",
            },
        )
        return None
    except Exception as exc:
        if await _honor_committed_review_state(
            lane_id=lane_id,
            sm=sm,
            ingest_rework_verdict=ingest_rework_verdict,
            on_reviewed=on_reviewed,
            on_rejected=on_rejected,
        ):
            return None
        sm.transition(
            lane_id,
            "gate_failed",
            metadata={
                "failure_reason": "review_infra_unavailable"
                if is_spawn_transient(exc)
                else "review_spawn_failed",
                "failure_layer": "review",
                "review_infra_reason": review_infra_reason_from_exception(exc),
                "review_retry_after_at": time.time() + REVIEW_INFRA_RETRY_DELAY_S,
                "failure_error": str(exc),
            },
        )
        return None


async def _handle_review_result(
    *,
    lane_id: str,
    result,
    sm: LaneStateMachine,
    recovery: RecoveryManager,
    observer: Callable[[RecoveryEvent], None],
    xmuse_root: Path,
    stable_verdict_id: Callable[[str], str],
    ingest_merge_verdict: Callable[[str, str, list[str] | None], None],
    ingest_rework_verdict: Callable[[str, str, list[str] | None], None],
    ingest_review_failure_verdict: Callable[[str, str, list[str]], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
) -> None:
    if await _honor_committed_review_state(
        lane_id=lane_id,
        sm=sm,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
    ):
        return

    _record_spawn_outcome(lane_id, result, recovery, observer)

    provider_result = result.provider_result
    if provider_result is not None and provider_result.status is not WorkerResultStatus.COMPLETED:
        sm.transition(
            lane_id,
            "gate_failed",
            metadata=_review_provider_failure_metadata(provider_result.failure_kind),
        )
        return

    if result.timed_out:
        sm.transition(
            lane_id,
            "gate_failed",
            metadata={
                "failure_reason": "review_timeout",
                "failure_layer": "review",
            },
        )
        return

    if result.exit_code != 0:
        infra_reason = review_infra_failure_reason(result)
        if infra_reason is not None:
            sm.transition(
                lane_id,
                "gate_failed",
                metadata={
                    "failure_reason": "review_infra_unavailable",
                    "failure_layer": "review",
                    "review_infra_reason": infra_reason,
                    "review_retry_after_at": time.time() + REVIEW_INFRA_RETRY_DELAY_S,
                },
            )
            return
        sm.transition(
            lane_id,
            "gate_failed",
            metadata={
                "failure_reason": "review_non_zero_exit",
                "failure_layer": "review",
            },
        )
        return

    current = sm.get_lane(lane_id)
    if current.get("status") == "gated" and not result.stdout.strip():
        ingest_review_failure_verdict(
            lane_id,
            "review_no_verdict",
            _review_failure_evidence_refs(result),
        )
        sm.transition(
            lane_id,
            "gate_failed",
            metadata={
                "failure_reason": "review_no_verdict",
                "failure_layer": "review",
            },
        )
        return

    if current.get("status") == "gated" and result.stdout.strip():
        decision, summary, reason = infer_review_fallback(result.stdout)
        summary = sanitize_review_summary(summary)
        evidence_refs = _stdout_review_evidence_refs(
            lane_id,
            lane=current,
            xmuse_root=xmuse_root,
        )
        if decision == "reviewed":
            verdict_id = stable_verdict_id(lane_id)
            sm.transition(
                lane_id,
                "reviewed",
                metadata=_review_metadata(
                    lane=current,
                    decision=ReviewDecision.MERGE.value,
                    summary=summary,
                    fallback="stdout",
                    fallback_reason=reason,
                )
                | {
                    "review_verdict_id": verdict_id,
                    "review_evidence_refs": evidence_refs,
                },
            )
            ingest_merge_verdict(lane_id, summary, evidence_refs)
            await on_reviewed(lane_id)
            return

        sm.transition(
            lane_id,
            "rejected",
            metadata=_review_metadata(
                lane=current,
                decision=ReviewDecision.REWORK.value,
                summary=summary,
                fallback="stdout",
                fallback_reason=reason,
            )
            | {"review_evidence_refs": evidence_refs},
        )
        ingest_rework_verdict(lane_id, summary, evidence_refs)
        await on_rejected(lane_id)


def _review_provider_failure_metadata(
    failure_kind: ProviderFailureKind | None,
) -> dict[str, str]:
    failure_reason = "review_provider_failed"
    if failure_kind is ProviderFailureKind.TIMEOUT:
        failure_reason = "review_timeout"
    elif failure_kind is ProviderFailureKind.NON_ZERO_EXIT:
        failure_reason = "review_non_zero_exit"
    elif failure_kind is not None:
        failure_reason = f"review_{failure_kind.value}"
    return {
        "failure_reason": failure_reason,
        "failure_layer": "review",
    }


def _mark_failed_provider_session_binding(
    *,
    binding: ProviderSessionBindingRecord | None,
    writer: Any | None,
    failure_kind: ProviderFailureKind | None,
) -> None:
    if binding is None or writer is None:
        return
    mark_failed = getattr(writer, "mark_failed", None)
    if not callable(mark_failed):
        return
    status = (
        ProviderSessionBindingStatus.STALE
        if failure_kind is ProviderFailureKind.STALE_REQUEST
        else ProviderSessionBindingStatus.FAILED
    )
    try:
        mark_failed(
            binding.binding_id,
            status=status,
            reason=_provider_binding_failure_reason(failure_kind),
        )
    except Exception:
        logger.warning(
            "provider session binding mark_failed failed after review resume failure",
            exc_info=True,
        )


def _provider_binding_failure_reason(
    failure_kind: ProviderFailureKind | None,
) -> str:
    if failure_kind is None:
        return "review_provider_failed"
    return f"review_{failure_kind.value}"


async def _honor_committed_review_state(
    *,
    lane_id: str,
    sm: LaneStateMachine,
    ingest_rework_verdict: Callable[[str, str], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
) -> bool:
    """Honor Review GOD decisions already committed through MCP.

    The MCP server runs in a separate process, so its status update does not
    publish into this runner's in-memory event bus. Re-read the lane before
    interpreting the CLI process exit code; otherwise a late transport/API
    failure can overwrite an already committed semantic review verdict.
    """
    current = sm.get_lane(lane_id)
    status = current.get("status")
    if status == "reviewed":
        await on_reviewed(lane_id)
        return True
    if status == "rejected":
        ingest_rework_verdict(
            lane_id,
            str(
                current.get("review_summary")
                or current.get("rework_context")
                or "Review GOD requested rework through committed lane state."
            ),
        )
        await on_rejected(lane_id)
        return True
    return False


def _review_failure_evidence_refs(result: Any) -> list[str]:
    refs: list[str] = []
    for attr in ("result_log_path", "stdout_log_path", "stderr_log_path", "prompt_log_path"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value:
            refs.append(value)
    return refs


def _stdout_review_evidence_refs(
    lane_id: str,
    *,
    lane: dict[str, Any],
    xmuse_root: Path,
) -> list[str]:
    refs: list[str] = []
    if lane_id:
        refs.append(f"feature_lanes.json#lane={lane_id}")
    task_id = lane.get("review_task_id")
    if isinstance(task_id, str) and task_id.strip():
        refs.append(f"review_plane.json#task={task_id.strip()}")
    prompt_ref = lane.get("prompt_ref")
    if isinstance(prompt_ref, str) and prompt_ref.strip():
        refs.append(prompt_ref.strip())
    gate_report = xmuse_root / "logs" / "gates" / lane_id / "report.json"
    if gate_report.exists():
        refs.append(f"logs/gates/{lane_id}/report.json")
    return _dedupe_refs(refs)


def _dedupe_refs(value: list[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for item in value:
        ref = str(item).strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _committed_review_status(sm: LaneStateMachine, lane_id: str) -> bool:
    try:
        return sm.get_lane(lane_id).get("status") in {"reviewed", "rejected"}
    except KeyError:
        return False


async def _try_configured_review_peer(
    *,
    lane_id: str,
    lane: dict[str, Any],
    god: GodConfig,
    prompt: str,
    xmuse_root: Path,
    sm: LaneStateMachine,
    persistent_session_layer: PersistentReviewSessionLayer | None,
    receive_timeout_s: float,
    default_review_peer_routing_enabled: bool,
    stable_verdict_id: Callable[[str], str],
    ingest_merge_verdict: Callable[[str, str, list[str] | None], None],
    ingest_rework_verdict: Callable[[str, str, list[str] | None], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
) -> ConfiguredReviewPeerAttempt:
    review_peer_id = _optional_text(lane.get("review_peer_id"))
    review_peer_defaulted = False
    runtime_peer_required = False
    runtime_peer_failure: str | None = None
    if review_peer_id is None:
        review_peer_id, runtime_peer_failure = _review_peer_id_for_requested_runtime(
            xmuse_root=xmuse_root,
            conversation_id=_optional_text(lane.get("conversation_id")),
            runtime=_optional_text(lane.get("review_runtime")),
        )
        runtime_peer_required = (
            review_peer_id is not None or runtime_peer_failure is not None
        )
        if runtime_peer_failure is not None:
            review_peer_id = "runtime:opencode"
    if (
        review_peer_id is None
        and default_review_peer_routing_enabled
        and persistent_session_layer is not None
    ):
        review_peer_id = await _ensure_default_review_peer(
            xmuse_root=xmuse_root,
            conversation_id=_optional_text(lane.get("conversation_id")),
            model=_persistent_model_for_god(god, persistent_session_layer),
            feature_scope_id=feature_scope_id_from_lane(lane),
        )
        review_peer_defaulted = review_peer_id is not None
    if review_peer_id is None:
        return ConfiguredReviewPeerAttempt()
    mode = (
        "required"
        if runtime_peer_required
        else "preferred"
        if review_peer_defaulted
        else _peer_routing_mode(lane.get("peer_routing_mode"))
    )
    base_metadata = {"peer_routing_mode": mode}
    if not review_peer_defaulted:
        base_metadata["review_peer_id"] = review_peer_id
    if runtime_peer_required:
        base_metadata["review_runtime_requested"] = "opencode"
    if mode != lane.get("peer_routing_mode"):
        base_metadata["peer_routing_mode_normalized"] = mode
    sm.update_metadata(lane_id, base_metadata)

    peer_request_id = _peer_request_id(review_peer_id, lane_id)
    if runtime_peer_failure is not None:
        return _configured_peer_failed(
            sm,
            lane_id,
            mode=mode,
            review_peer_id=review_peer_id,
            peer_request_id=peer_request_id,
            reason=runtime_peer_failure,
            unavailable=True,
            review_peer_defaulted=review_peer_defaulted,
        )
    if persistent_session_layer is None:
        return _configured_peer_failed(
            sm,
            lane_id,
            mode=mode,
            review_peer_id=review_peer_id,
            peer_request_id=peer_request_id,
            reason="session_layer_unavailable",
            unavailable=True,
        )

    participant = _review_peer_participant(
        xmuse_root=xmuse_root,
        conversation_id=_optional_text(lane.get("conversation_id")),
        review_peer_id=review_peer_id,
    )
    if isinstance(participant, str):
        return _configured_peer_failed(
            sm,
            lane_id,
            mode=mode,
            review_peer_id=review_peer_id,
            peer_request_id=peer_request_id,
            reason=participant,
            unavailable=True,
            review_peer_defaulted=review_peer_defaulted,
        )
    participant_metadata = _review_peer_runtime_metadata(participant)
    if participant_metadata:
        sm.update_metadata(lane_id, participant_metadata)

    service = PersistentCliPeerService(
        db_path=xmuse_root / "chat.db",
        session_layer=persistent_session_layer,
    )
    peer_session_scope_id = _configured_review_peer_session_scope(lane_id, lane)
    peer_session_prompt = _persistent_peer_session_prompt(
        god,
        role=_REVIEW_ROLE,
        identity_key=f"configured:{review_peer_id}",
    )
    peer_prompt = _persistent_review_prompt(
        prompt,
        review_request_id=peer_request_id,
        identity_key=f"configured:{review_peer_id}",
    )
    peer_lock_key = _configured_peer_lock_key(
        lane_id,
        lane,
        review_peer_id,
    )
    lock = _CONFIGURED_REVIEW_PEER_LOCKS.setdefault(peer_lock_key, asyncio.Lock())
    async with lock:
        result = await service.request(
            conversation_id=str(lane.get("conversation_id")),
            participant_id=review_peer_id,
            model=participant.model,
            prompt=peer_prompt,
            session_prompt=peer_session_prompt,
            worktree=_persistent_review_worktree(xmuse_root),
            feature_scope_id=peer_session_scope_id,
            request_id=peer_request_id,
            message_type="review",
            context=_persistent_review_context(
                lane,
                conversation_id=str(lane.get("conversation_id")),
                xmuse_root=xmuse_root,
                all_lanes=sm.get_lanes(),
            ),
            timeout_s=receive_timeout_s,
            prompt_contract=_persistent_review_session_prompt_contract(peer_session_prompt),
        )
    if result.ok and result.message is not None:
        delivered = await _apply_persistent_review_message(
            lane_id=lane_id,
            sm=sm,
            message=result.message,
            stable_verdict_id=stable_verdict_id,
            ingest_merge_verdict=ingest_merge_verdict,
            ingest_rework_verdict=ingest_rework_verdict,
            on_reviewed=on_reviewed,
            on_rejected=on_rejected,
            review_request_id=peer_request_id,
            persistent_review_identity=f"configured:{review_peer_id}",
            evidence_refs=_stdout_review_evidence_refs(
                lane_id,
                lane=sm.get_lane(lane_id),
                xmuse_root=xmuse_root,
            ),
            extra_metadata={
                "review_peer_id": review_peer_id,
                "peer_request_id": peer_request_id,
                "peer_routing_mode": mode,
                "peer_delivery_mode": "configured_peer",
            }
            | participant_metadata
            | ({"review_peer_defaulted": True} if review_peer_defaulted else {}),
        )
        if not delivered:
            return _configured_peer_failed(
                sm,
                lane_id,
                mode=mode,
                review_peer_id=review_peer_id,
                peer_request_id=peer_request_id,
                reason="review_peer_no_verdict",
                unavailable=False,
                review_peer_defaulted=review_peer_defaulted,
                peer_result=result,
            )
        return ConfiguredReviewPeerAttempt(attempted=True, delivered=delivered)

    return _configured_peer_failed(
        sm,
        lane_id,
        mode=mode,
        review_peer_id=review_peer_id,
        peer_request_id=peer_request_id,
        reason=result.reason or result.status,
        unavailable=result.status == "peer_unavailable",
        review_peer_defaulted=review_peer_defaulted,
        peer_result=result,
    )


def _review_peer_id_for_requested_runtime(
    *,
    xmuse_root: Path,
    conversation_id: str | None,
    runtime: str | None,
) -> tuple[str | None, str | None]:
    if runtime is None:
        return None, None
    if runtime != "opencode":
        return None, None
    if conversation_id is None:
        return None, "missing_conversation_id"
    try:
        participants = ParticipantStore(xmuse_root / "chat.db").list_by_conversation(
            conversation_id
        )
    except Exception:
        return None, "review_peer_lookup_failed"
    matches = [
        participant
        for participant in participants
        if participant.role == _REVIEW_ROLE
        and participant.cli_kind == runtime
        and participant.status == "active"
    ]
    if not matches:
        return None, "review_peer_runtime_unavailable"
    if len(matches) > 1:
        return None, "review_peer_runtime_ambiguous"
    return matches[0].participant_id, None


def _configured_peer_failed(
    sm: LaneStateMachine,
    lane_id: str,
    *,
    mode: str,
    review_peer_id: str,
    peer_request_id: str,
    reason: str,
    unavailable: bool,
    review_peer_defaulted: bool = False,
    peer_result: Any | None = None,
) -> ConfiguredReviewPeerAttempt:
    peer_metadata = _peer_result_failure_metadata(peer_result)
    if mode == "required":
        sm.transition(
            lane_id,
            "gate_failed",
            metadata={
                "failure_reason": (
                    "required_review_peer_unavailable"
                    if unavailable
                    else "review_peer_delivery_failed"
                ),
                "failure_layer": "review",
                "review_peer_id": review_peer_id,
                "peer_request_id": peer_request_id,
                "peer_routing_mode": mode,
                "peer_delivery_mode": "required_peer_failed",
                "peer_degraded_reason": reason,
            }
            | peer_metadata,
        )
        return ConfiguredReviewPeerAttempt(attempted=True, required_failed=True)
    metadata = {
        "peer_routing_mode": mode,
        "peer_delivery_mode": "configured_peer_degraded",
        "peer_degraded_reason": reason,
    } | peer_metadata
    if not review_peer_defaulted:
        metadata.update(
            {
                "review_peer_id": review_peer_id,
                "peer_request_id": peer_request_id,
            }
        )
    sm.update_metadata(lane_id, metadata)
    return ConfiguredReviewPeerAttempt(attempted=True)


def _peer_result_failure_metadata(peer_result: Any | None) -> dict[str, Any]:
    if peer_result is None:
        return {}
    metadata: dict[str, Any] = {}
    for attr, key in (
        ("status", "peer_result_status"),
        ("reason", "peer_result_reason"),
        ("error_message", "peer_result_error"),
    ):
        value = getattr(peer_result, attr, None)
        text = _compact_peer_text(value)
        if text is not None:
            metadata[key] = text

    message = getattr(peer_result, "message", None)
    if message is None:
        return metadata

    for attr, key in (
        ("type", "peer_result_message_type"),
        ("request_id", "peer_result_message_request_id"),
        ("status", "peer_result_message_status"),
        ("runtime", "peer_result_message_runtime"),
        ("message", "peer_result_message_excerpt"),
    ):
        value = getattr(message, attr, None)
        text = _compact_peer_text(value)
        if text is not None:
            metadata[key] = text

    artifacts = getattr(message, "artifacts", None)
    if isinstance(artifacts, dict):
        keys = sorted(str(key) for key in artifacts if isinstance(key, str))
        if keys:
            metadata["peer_result_artifact_keys"] = keys[:20]
        stdout = _compact_peer_text(artifacts.get("stdout"))
        if stdout is not None:
            metadata["peer_result_stdout_excerpt"] = stdout
        reply_text = _compact_peer_text(artifacts.get("reply_text"))
        if reply_text is not None:
            metadata["peer_result_reply_excerpt"] = reply_text
    return metadata


def _compact_peer_text(value: Any, *, max_chars: int = 600) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


async def _ensure_default_review_peer(
    *,
    xmuse_root: Path,
    conversation_id: str | None,
    model: str | None,
    feature_scope_id: str | None,
) -> str | None:
    if conversation_id is None:
        return None
    lock_key = f"{conversation_id}:{feature_scope_id or 'conversation-default-review'}"
    lock = _DEFAULT_REVIEW_PEER_LOCKS.setdefault(lock_key, asyncio.Lock())
    async with lock:
        return _ensure_default_review_peer_sync(
            xmuse_root=xmuse_root,
            conversation_id=conversation_id,
            model=model,
            feature_scope_id=feature_scope_id,
        )


def _ensure_default_review_peer_sync(
    *,
    xmuse_root: Path,
    conversation_id: str,
    model: str | None,
    feature_scope_id: str | None,
) -> str | None:
    selected_model = model or DEFAULT_CODEX_REVIEW_MODEL_ID
    store = ParticipantStore(xmuse_root / "chat.db")
    try:
        participants = store.list_by_conversation(conversation_id)
        opencode_peer_id = _unique_active_review_peer_id(
            participants,
            cli_kind="opencode",
        )
        if opencode_peer_id is not None:
            return opencode_peer_id
        if feature_scope_id is None:
            return None
        display_name = _default_review_peer_display_name(feature_scope_id)
        for participant in participants:
            if (
                participant.role == _REVIEW_ROLE
                and participant.display_name == display_name
                and participant.status == "active"
                and participant.model == selected_model
            ):
                return participant.participant_id
        participant = store.add(
            conversation_id=conversation_id,
            role=_REVIEW_ROLE,
            display_name=display_name,
            cli_kind="codex",
            model=selected_model,
        )
    except Exception:
        return None
    return participant.participant_id


def _unique_active_review_peer_id(participants: list[Any], *, cli_kind: str) -> str | None:
    matches = [
        participant
        for participant in participants
        if participant.role == _REVIEW_ROLE
        and participant.cli_kind == cli_kind
        and participant.status == "active"
    ]
    if len(matches) != 1:
        return None
    return matches[0].participant_id


def _default_review_peer_display_name(feature_scope_id: str) -> str:
    suffix = _safe_session_fragment(feature_scope_id, max_chars=40)
    digest = sha256(feature_scope_id.encode("utf-8")).hexdigest()[:10]
    return f"Review GOD [{suffix}-{digest}]"


def _configured_peer_lock_key(
    lane_id: str,
    lane: dict[str, Any],
    review_peer_id: str,
) -> str:
    conversation_id = _optional_text(lane.get("conversation_id")) or "missing-conversation"
    peer_session_scope_id = _configured_review_peer_session_scope(lane_id, lane)
    return f"{conversation_id}:{review_peer_id}:{peer_session_scope_id}"


def _configured_review_peer_session_scope(
    lane_id: str,
    lane: dict[str, Any],
) -> str:
    return feature_scope_id_from_lane(lane) or f"configured-review:{lane_id}"


def _review_peer_participant(
    *,
    xmuse_root: Path,
    conversation_id: str | None,
    review_peer_id: str,
):
    if conversation_id is None:
        return "missing_conversation_id"
    try:
        participant = ParticipantStore(xmuse_root / "chat.db").get(review_peer_id)
    except KeyError:
        return "ensure_failed"
    if participant.conversation_id != conversation_id:
        return "conversation_mismatch"
    if participant.status != "active":
        return "participant_inactive"
    if participant.role != _REVIEW_ROLE:
        return "review_peer_role_mismatch"
    return participant


def _review_peer_runtime_metadata(participant: Any) -> dict[str, str]:
    metadata: dict[str, str] = {}
    cli_kind = _optional_text(getattr(participant, "cli_kind", None))
    model = _optional_text(getattr(participant, "model", None))
    if cli_kind is not None:
        metadata["review_peer_cli_kind"] = cli_kind
    if model is not None:
        metadata["review_peer_model"] = model
    return metadata


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _peer_routing_mode(value: Any) -> str:
    if value == "required":
        return "required"
    return "preferred"


def _peer_request_id(review_peer_id: str, lane_id: str) -> str:
    return (
        f"review-peer-{_safe_session_fragment(review_peer_id)}-"
        f"{_safe_session_fragment(lane_id)}"
    )


async def _try_persistent_review(
    *,
    lane_id: str,
    lane: dict[str, Any],
    god: GodConfig,
    prompt: str,
    worktree: Path,
    xmuse_root: Path,
    sm: LaneStateMachine,
    persistent_session_layer: PersistentReviewSessionLayer,
    receive_timeout_s: float,
    stable_verdict_id: Callable[[str], str],
    ingest_merge_verdict: Callable[[str, str, list[str] | None], None],
    ingest_rework_verdict: Callable[[str, str, list[str] | None], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
) -> bool:
    conversation_id = lane.get("conversation_id")
    if not conversation_id:
        _record_persistent_review_degraded(
            sm,
            lane_id,
            reason="missing_conversation_id",
        )
        return False
    try:
        identity = build_persistent_god_identity(
            conversation_id=str(conversation_id),
            role=_REVIEW_ROLE,
            feature_scope_id=feature_scope_id_from_lane(lane),
            lane_id=lane_id,
            require_feature=True,
        )
    except MissingGodFeatureIdentity:
        _record_persistent_review_degraded(
            sm,
            lane_id,
            reason="missing_feature_identity",
        )
        return False

    record: GodSessionRecord | None = None
    review_request_id = _review_request_id(identity.session_key, lane_id)
    lock = _PERSISTENT_REVIEW_LOCKS.setdefault(identity.session_key, asyncio.Lock())
    try:
        async with lock:
            agent = AgentDescriptor(
                runtime=AgentRuntime(god.runtime),
                name=god.name,
                capabilities=["review"],
                session_config=SessionConfig(persistent_role=_REVIEW_ROLE),
            )
            session_prompt = _persistent_peer_session_prompt(god, role=_REVIEW_ROLE)
            try:
                record = await persistent_session_layer.ensure_conversation_session(
                    conversation_id=identity.conversation_id,
                    participant_id=identity.participant_id,
                    role=_REVIEW_ROLE,
                    agent=agent,
                    worktree=_persistent_review_worktree(xmuse_root),
                    model=_persistent_model_for_god(god, persistent_session_layer),
                    prompt_fingerprint=_persistent_peer_prompt_fingerprint(
                        god,
                        role=_REVIEW_ROLE,
                    ),
                    feature_scope_id=identity.feature_scope_id,
                )
            except Exception:
                _record_persistent_review_degraded(
                    sm,
                    lane_id,
                    reason="ensure_failed",
                    review_request_id=review_request_id,
                )
                raise
            _record_prompt_contract_if_supported(
                persistent_session_layer,
                record.god_session_id,
                _persistent_review_session_prompt_contract(session_prompt),
            )
            sm.update_metadata(
                lane_id,
                {
                    "review_delivery_mode": "persistent",
                    "persistent_review_degraded": False,
                    "persistent_review_identity": identity.session_key,
                    "review_request_id": review_request_id,
                },
            )
            try:
                await persistent_session_layer.send_message(
                    god_session_id=record.god_session_id,
                    message_type="review",
                    request_id=review_request_id,
                    prompt=_persistent_review_prompt(
                        prompt,
                        review_request_id=review_request_id,
                        identity_key=identity.session_key,
                    ),
                    context=_persistent_review_context(
                        lane,
                        conversation_id=identity.conversation_id,
                        xmuse_root=xmuse_root,
                        all_lanes=sm.get_lanes(),
                    ),
                )
            except Exception:
                _record_persistent_review_degraded(
                    sm,
                    lane_id,
                    reason="send_failed",
                    review_request_id=review_request_id,
                )
                raise
            try:
                message = await _receive_persistent_review_result(
                    persistent_session_layer,
                    god_session_id=record.god_session_id,
                    timeout_s=receive_timeout_s,
                )
            except PersistentReviewReceiveError:
                _record_persistent_review_degraded(
                    sm,
                    lane_id,
                    reason="receive_error",
                    review_request_id=review_request_id,
                )
                try:
                    await persistent_session_layer.abort_session(record.god_session_id)
                except Exception:
                    log_event(
                        logger,
                        logging.WARNING,
                        "persistent_review_god_abort_failed",
                        lane_id=lane_id,
                        conversation_id=str(conversation_id),
                        exc_info=True,
                    )
                return False
            except TimeoutError:
                log_event(
                    logger,
                    logging.WARNING,
                    "persistent_review_god_receive_timed_out",
                    lane_id=lane_id,
                    conversation_id=str(conversation_id),
                )
                _record_persistent_review_degraded(
                    sm,
                    lane_id,
                    reason="receive_timeout",
                    review_request_id=review_request_id,
                )
                try:
                    await persistent_session_layer.abort_session(record.god_session_id)
                except Exception:
                    log_event(
                        logger,
                        logging.WARNING,
                        "persistent_review_god_abort_failed",
                        lane_id=lane_id,
                        conversation_id=str(conversation_id),
                        exc_info=True,
                    )
                return False
            except Exception:
                _record_persistent_review_degraded(
                    sm,
                    lane_id,
                    reason="receive_failed",
                    review_request_id=review_request_id,
                )
                try:
                    await persistent_session_layer.abort_session(record.god_session_id)
                except Exception:
                    log_event(
                        logger,
                        logging.WARNING,
                        "persistent_review_god_abort_failed",
                        lane_id=lane_id,
                        conversation_id=str(conversation_id),
                        exc_info=True,
                    )
                return False
    except Exception:
        if record is not None:
            try:
                await persistent_session_layer.abort_session(record.god_session_id)
            except Exception:
                log_event(
                    logger,
                    logging.WARNING,
                    "persistent_review_god_abort_failed",
                    lane_id=lane_id,
                    conversation_id=str(conversation_id),
                    exc_info=True,
                )
        log_event(
            logger,
            logging.WARNING,
            "persistent_review_god_delivery_failed",
            lane_id=lane_id,
            conversation_id=str(conversation_id),
            exc_info=True,
        )
        return False

    if message is None:
        _record_persistent_review_degraded(
            sm,
            lane_id,
            reason="no_result_message",
            review_request_id=review_request_id,
        )
        try:
            await persistent_session_layer.abort_session(record.god_session_id)
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "persistent_review_god_abort_failed",
                lane_id=lane_id,
                conversation_id=str(conversation_id),
                exc_info=True,
            )
        return False

    request_degraded_reason = _persistent_review_request_degraded_reason(
        message,
        expected_request_id=review_request_id,
    )
    if request_degraded_reason is not None:
        _record_persistent_review_degraded(
            sm,
            lane_id,
            reason=request_degraded_reason,
            review_request_id=review_request_id,
        )
        try:
            await persistent_session_layer.abort_session(record.god_session_id)
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "persistent_review_god_abort_failed",
                lane_id=lane_id,
                conversation_id=str(conversation_id),
                exc_info=True,
            )
        return False

    return await _apply_persistent_review_message(
        lane_id=lane_id,
        sm=sm,
        message=message,
        stable_verdict_id=stable_verdict_id,
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
        review_request_id=review_request_id,
        persistent_review_identity=identity.session_key,
        evidence_refs=_stdout_review_evidence_refs(
            lane_id,
            lane=sm.get_lane(lane_id),
            xmuse_root=xmuse_root,
        ),
    )


def _persistent_model_for_god(
    god: GodConfig,
    persistent_session_layer: PersistentReviewSessionLayer,
) -> str | None:
    if god.model:
        return god.model
    model_getter = getattr(persistent_session_layer, "persistent_model_for_runtime", None)
    if callable(model_getter):
        value = model_getter(AgentRuntime(god.runtime))
        if isinstance(value, str) and value.strip():
            return normalize_codex_model_id(
                value,
                profile_id=ProviderProfileId.REVIEW,
            )
    if god.runtime == "codex":
        return normalize_codex_model_id(
            os.environ.get("XMUSE_CODEX_MODEL", DEFAULT_CODEX_REVIEW_MODEL_ID),
            profile_id=ProviderProfileId.REVIEW,
        )
    return None


def _record_prompt_contract_if_supported(
    persistent_session_layer: PersistentReviewSessionLayer,
    god_session_id: str,
    prompt_contract: dict[str, object],
) -> None:
    recorder = getattr(persistent_session_layer, "record_prompt_contract", None)
    if not callable(recorder):
        return
    recorder(god_session_id, **prompt_contract)
