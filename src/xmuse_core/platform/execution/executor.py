from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from xmuse_core.agents.god_identity import (
    feature_scope_id_from_lane,
)
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.persistent_peer import fingerprint_prompt
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime, SessionConfig
from xmuse_core.observability import log_event
from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.execution.review import (
    is_spawn_transient,
    spawn_result_transient,
)
from xmuse_core.platform.feature_context import build_feature_context_bundle
from xmuse_core.platform.messages import (
    EXECUTE_PEER_DEGRADED_REASON_FIELD,
    EXECUTE_PEER_DELIVERY_MODE_CONFIGURED,
    EXECUTE_PEER_DELIVERY_MODE_FIELD,
    EXECUTE_PEER_DELIVERY_MODE_ONE_SHOT_FALLBACK,
    EXECUTE_PEER_ID_FIELD,
    EXECUTE_PEER_REQUEST_ID_FIELD,
    EXECUTE_PEER_RESULT_ARTIFACT_FIELD,
    EXECUTE_PEER_ROUTING_MODE_FIELD,
    EXECUTE_PEER_ROUTING_MODE_PREFERRED,
    ExecuteRequest,
    Transport,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.adapters.base import ProviderFailureKind, ProviderInvocation
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderProfileId
from xmuse_core.providers.registry import DEFAULT_CODEX_GOD_MODEL_ID, normalize_codex_model_id
from xmuse_core.providers.session_binding import (
    ProviderSessionBindingWriter,
    build_provider_session_binding_from_result,
)
from xmuse_core.self_evolution.recovery import (
    CircuitOpenError,
    RecoveryEvent,
    RecoveryManager,
)
from xmuse_core.structuring.feature_review_contracts import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)

logger = logging.getLogger(__name__)

_COMPONENT = "orchestrator.execution_god"
_EXECUTE_ROLE = "execute"
_EXECUTE_DEGRADED_SOURCE_COORDINATOR_SESSION = "coordinator_session_delivery"
_EXECUTE_FAILURE_SOURCE_WORKER_TEST_GATE = "worker_test_gate"
PERSISTENT_EXECUTE_RECEIVE_TIMEOUT_S = 180.0
_PERSISTENT_EXECUTE_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class ExecutePeerContract:
    execute_peer_id: str
    request_id: str
    routing_mode: str = EXECUTE_PEER_ROUTING_MODE_PREFERRED


class PersistentExecuteSessionLayer(Protocol):
    async def ensure_conversation_session(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        role: str,
        agent: AgentDescriptor,
        worktree: Path,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        feature_scope_id: str | None = None,
    ) -> GodSessionRecord: ...

    async def send_message(
        self,
        god_session_id: str,
        message_type: str,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None: ...

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None: ...

    async def abort_session(self, god_session_id: str) -> None: ...


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
                    error=result.stderr or result.stdout or "execution spawn failed",
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
                error=result.stderr or result.stdout or "execution spawn failed",
                circuit_state=recovery.circuit(_COMPONENT).state.value,
            )
        )
    else:
        recovery.circuit(_COMPONENT).record_success()


async def run_execution_god(
    *,
    lane_id: str,
    god: GodConfig,
    prompt: str,
    worktree: Path,
    sm: LaneStateMachine,
    recovery: RecoveryManager,
    transport: Transport,
    observer: Callable[[RecoveryEvent], None],
    on_executed: Callable[[str], Awaitable[None]],
    persistent_execute_enabled: bool = False,
    persistent_session_layer: PersistentExecuteSessionLayer | None = None,
    xmuse_root: Path | None = None,
    receive_timeout_s: float = PERSISTENT_EXECUTE_RECEIVE_TIMEOUT_S,
    provider_invocation: ProviderInvocation | None = None,
    provider_session_binding: ProviderSessionBindingRecord | None = None,
    provider_session_binding_writer: ProviderSessionBindingWriter | None = None,
    provider_session_binding_god_session_id: str | None = None,
    provider_session_binding_role: str = "feature_worker",
    provider_session_binding_conversation_id: str | None = None,
    provider_session_binding_feature_graph_id: str | None = None,
    provider_session_binding_prompt_fingerprint: str | None = None,
    record_provider_session_binding_degradation: Callable[
        [str, str, str | None],
        None,
    ]
    | None = None,
) -> None:
    log_event(
        logger,
        logging.INFO,
        "execution_god_started",
        lane_id=lane_id,
        god=god.name,
        god_runtime=god.runtime,
    )
    lane = sm.get_lane(lane_id)
    execute_peer_contract = _execute_peer_contract(lane_id, lane)
    if execute_peer_contract is not None and (
        not persistent_execute_enabled or persistent_session_layer is None
    ):
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason="session_layer_unavailable",
            execute_peer_contract=execute_peer_contract,
        )
    if (
        execute_peer_contract is not None
        and persistent_execute_enabled
        and persistent_session_layer is not None
    ):
        delivered = await _try_persistent_execute(
            lane_id=lane_id,
            lane=lane,
            execute_peer_contract=execute_peer_contract,
            god=god,
            prompt=prompt,
            sm=sm,
            persistent_session_layer=persistent_session_layer,
            xmuse_root=xmuse_root or worktree,
            receive_timeout_s=receive_timeout_s,
            on_executed=on_executed,
        )
        if delivered:
            return

    try:
        result = await recovery.execute_async(
            _COMPONENT,
            "spawn",
            lambda: transport.send_execute(
                ExecuteRequest(
                    lane_id=lane_id,
                    prompt=prompt,
                    worktree=worktree,
                    capabilities=["code"],
                    god_config=god,
                    mcp_url=None,
                    env_overrides={},
                    parent_god_role="execute",
                    worker_kind="temporary_child_worker",
                    provider_invocation=provider_invocation,
                    provider_session_binding=provider_session_binding,
                )
            ),
            is_transient=is_spawn_transient,
            observer=observer,
        )
    except CircuitOpenError as exc:
        sm.transition(
            lane_id,
            "exec_failed",
            metadata={
                "failure_reason": "execution_circuit_open",
                "failure_layer": "coordinator",
                "retry_after_s": exc.retry_after_s,
                "degraded_component": "execution_god",
            },
        )
        return
    except Exception as exc:
        sm.transition(
            lane_id,
            "exec_failed",
            metadata={
                "failure_reason": "execution_infra_unavailable"
                if is_spawn_transient(exc)
                else "execution_spawn_failed",
                "failure_layer": "coordinator",
                "failure_error": str(exc),
            },
        )
        return

    _record_spawn_outcome(lane_id, result, recovery, observer)
    memoryos_metadata = _memoryos_metadata(result)
    if memoryos_metadata:
        sm.update_metadata(lane_id, memoryos_metadata)

    provider_result = result.provider_result

    if provider_result is not None:
        failure_metadata = _execution_provider_failure_metadata(
            god,
            provider_result.failure_kind,
        )
        if provider_result.status is WorkerResultStatus.COMPLETED:
            provider_binding_metadata = _upsert_successful_provider_session_binding(
                invocation=provider_invocation,
                result=provider_result,
                previous_binding=provider_session_binding,
                writer=provider_session_binding_writer,
                god_session_id=provider_session_binding_god_session_id,
                role=provider_session_binding_role,
                conversation_id=provider_session_binding_conversation_id,
                feature_graph_id=provider_session_binding_feature_graph_id,
                prompt_fingerprint=provider_session_binding_prompt_fingerprint,
                model=god.model,
                record_degradation=record_provider_session_binding_degradation,
            )
            log_event(logger, logging.INFO, "execution_god_completed", lane_id=lane_id)
            sm.transition(
                lane_id,
                "executed",
                metadata={
                    "parent_god": god.name,
                    "parent_god_role": "execute",
                    "worker_kind": "temporary_child_worker",
                }
                | provider_binding_metadata,
            )
            await on_executed(lane_id)
            return
        provider_binding_metadata = _mark_failed_provider_session_binding(
            binding=provider_session_binding,
            writer=provider_session_binding_writer,
            failure_kind=provider_result.failure_kind,
            record_degradation=record_provider_session_binding_degradation,
        )
        sm.transition(
            lane_id,
            "exec_failed",
            metadata=failure_metadata | provider_binding_metadata,
        )
        return

    if result.timed_out:
        sm.transition(
            lane_id,
            "exec_failed",
            metadata={
                "failure_reason": "timeout",
                "failure_layer": _execution_result_failure_layer(god),
                "execute_failure_source": _EXECUTE_FAILURE_SOURCE_WORKER_TEST_GATE,
            },
        )
        return

    current = sm.get_lane(lane_id)
    if current["status"] == "dispatched":
        if result.exit_code == 0:
            log_event(logger, logging.INFO, "execution_god_completed", lane_id=lane_id)
            sm.transition(
                lane_id,
                "executed",
                metadata={
                    "parent_god": god.name,
                    "parent_god_role": "execute",
                    "worker_kind": "temporary_child_worker",
                },
            )
            await on_executed(lane_id)
        else:
            sm.transition(
                lane_id,
                "exec_failed",
                metadata={
                    "failure_reason": "non_zero_exit",
                    "failure_layer": _execution_result_failure_layer(god),
                    "execute_failure_source": _EXECUTE_FAILURE_SOURCE_WORKER_TEST_GATE,
                },
            )
    elif current["status"] == "executed" and result.exit_code == 0:
        await on_executed(lane_id)


def _upsert_successful_provider_session_binding(
    *,
    invocation: ProviderInvocation | None,
    result,
    previous_binding: ProviderSessionBindingRecord | None,
    writer: ProviderSessionBindingWriter | None,
    god_session_id: str | None,
    role: str,
    conversation_id: str | None,
    feature_graph_id: str | None,
    prompt_fingerprint: str | None,
    model: str | None,
    record_degradation: Callable[[str, str, str | None], None] | None,
) -> dict[str, Any]:
    if invocation is None or writer is None or god_session_id is None:
        return {}
    if result.provider_session_id is None:
        return {}
    binding = build_provider_session_binding_from_result(
        invocation=invocation,
        result=result,
        god_session_id=god_session_id,
        role=role,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        conversation_id=conversation_id,
        feature_graph_id=feature_graph_id,
        prompt_fingerprint=prompt_fingerprint,
        model=model,
        binding_id=previous_binding.binding_id if previous_binding is not None else None,
    )
    try:
        binding = writer.upsert_active(binding)
    except Exception as exc:
        logger.warning(
            "provider session binding upsert failed after successful execution",
            exc_info=True,
        )
        if record_degradation is not None:
            _record_provider_session_binding_degradation(
                record_degradation,
                binding_id=binding.binding_id,
                reason="upsert_failed",
                failure=str(exc),
            )
        return {
            "provider_session_binding_degraded": True,
            "provider_session_binding_degraded_reason": "upsert_failed",
            "provider_session_binding_id": binding.binding_id,
            "provider_session_binding_failure": str(exc),
        }
    return {
        "provider_session_binding_degraded": False,
        "provider_session_binding_id": binding.binding_id,
    }


def _mark_failed_provider_session_binding(
    *,
    binding: ProviderSessionBindingRecord | None,
    writer: ProviderSessionBindingWriter | None,
    failure_kind: ProviderFailureKind | None,
    record_degradation: Callable[[str, str, str | None], None] | None,
) -> dict[str, Any]:
    if binding is None or writer is None:
        return {}
    mark_failed = getattr(writer, "mark_failed", None)
    if not callable(mark_failed):
        return {}
    reason = _provider_binding_failure_reason(failure_kind)
    status = (
        ProviderSessionBindingStatus.STALE
        if failure_kind is ProviderFailureKind.STALE_REQUEST
        else ProviderSessionBindingStatus.FAILED
    )
    try:
        mark_failed(
            binding.binding_id,
            status=status,
            reason=reason,
            failed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    except Exception as exc:
        logger.warning(
            "provider session binding mark_failed failed after provider failure",
            exc_info=True,
        )
        _record_provider_session_binding_degradation(
            record_degradation,
            binding_id=binding.binding_id,
            reason="mark_failed_failed",
            failure=str(exc),
        )
        return {
            "provider_session_binding_degraded": True,
            "provider_session_binding_degraded_reason": "mark_failed_failed",
            "provider_session_binding_id": binding.binding_id,
            "provider_session_binding_failure": str(exc),
        }
    return {
        "provider_session_binding_degraded": False,
        "provider_session_binding_id": binding.binding_id,
    }


def _record_provider_session_binding_degradation(
    callback: Callable[[str, str, str | None], None] | None,
    *,
    binding_id: str,
    reason: str,
    failure: str | None,
) -> None:
    if callback is None:
        return
    try:
        callback(binding_id, reason, failure)
    except Exception:
        logger.warning(
            "provider session binding degradation callback failed",
            exc_info=True,
        )


def _execution_provider_failure_metadata(
    god: GodConfig,
    failure_kind: ProviderFailureKind | None,
) -> dict[str, str]:
    failure_reason = _provider_binding_failure_reason(failure_kind)
    return {
        "failure_reason": failure_reason,
        "failure_layer": _execution_result_failure_layer(god),
        "execute_failure_source": _EXECUTE_FAILURE_SOURCE_WORKER_TEST_GATE,
    }


def _provider_binding_failure_reason(
    failure_kind: ProviderFailureKind | None,
) -> str:
    failure_reason = "provider_contract_failure"
    if failure_kind is ProviderFailureKind.TIMEOUT:
        failure_reason = "timeout"
    elif failure_kind is ProviderFailureKind.NON_ZERO_EXIT:
        failure_reason = "non_zero_exit"
    elif failure_kind is not None:
        failure_reason = failure_kind.value
    return failure_reason


async def _try_persistent_execute(
    *,
    lane_id: str,
    lane: dict[str, Any],
    execute_peer_contract: ExecutePeerContract,
    god: GodConfig,
    prompt: str,
    sm: LaneStateMachine,
    persistent_session_layer: PersistentExecuteSessionLayer,
    xmuse_root: Path,
    receive_timeout_s: float,
    on_executed: Callable[[str], Awaitable[None]],
) -> bool:
    conversation_id = lane.get("conversation_id")
    if not conversation_id:
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason="missing_conversation_id",
            execute_peer_contract=execute_peer_contract,
        )
        return False
    feature_scope_id = feature_scope_id_from_lane(lane)
    if feature_scope_id is None:
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason="missing_feature_identity",
            execute_peer_contract=execute_peer_contract,
        )
        return False

    identity_key = f"{conversation_id}:{execute_peer_contract.execute_peer_id}"
    execute_request_id = execute_peer_contract.request_id
    record: GodSessionRecord | None = None
    lock = _PERSISTENT_EXECUTE_LOCKS.setdefault(identity_key, asyncio.Lock())
    async with lock:
        agent = AgentDescriptor(
            runtime=AgentRuntime(god.runtime),
            name=god.name,
            capabilities=["code"],
            session_config=SessionConfig(persistent_role=_EXECUTE_ROLE),
        )
        try:
            record = await persistent_session_layer.ensure_conversation_session(
                conversation_id=str(conversation_id),
                participant_id=execute_peer_contract.execute_peer_id,
                role=_EXECUTE_ROLE,
                agent=agent,
                worktree=_persistent_execute_worktree(xmuse_root),
                model=_persistent_model_for_god(god, persistent_session_layer),
                prompt_fingerprint=_persistent_peer_prompt_fingerprint(
                    god,
                    role=_EXECUTE_ROLE,
                ),
                feature_scope_id=feature_scope_id,
            )
        except Exception as exc:
            _record_persistent_execute_degraded(
                sm,
                lane_id,
                reason=_ensure_failure_reason(exc),
                execute_request_id=execute_request_id,
                execute_peer_contract=execute_peer_contract,
            )
            return False

        sm.update_metadata(
            lane_id,
            {
                "execute_delivery_mode": "persistent",
                "persistent_execute_degraded": False,
                "persistent_execute_identity": identity_key,
                "execute_request_id": execute_request_id,
            }
            | _execute_peer_metadata(
                execute_peer_contract,
                delivery_mode=EXECUTE_PEER_DELIVERY_MODE_CONFIGURED,
            ),
        )
        try:
            await persistent_session_layer.send_message(
                god_session_id=record.god_session_id,
                message_type="execute",
                request_id=execute_request_id,
                prompt=_persistent_execute_prompt(
                    prompt,
                    god=god,
                    execute_request_id=execute_request_id,
                    identity_key=identity_key,
                    execute_peer_contract=execute_peer_contract,
                ),
                context=_persistent_execute_context(
                    lane,
                    xmuse_root=xmuse_root,
                    all_lanes=sm.get_lanes(),
                ),
            )
        except Exception:
            _record_persistent_execute_degraded(
                sm,
                lane_id,
                reason="send_failed",
                execute_request_id=execute_request_id,
                execute_peer_contract=execute_peer_contract,
            )
            await _abort_persistent_execute_session(
                persistent_session_layer,
                record.god_session_id,
            )
            return False

        try:
            message = await _receive_persistent_execute_result(
                persistent_session_layer,
                god_session_id=record.god_session_id,
                timeout_s=receive_timeout_s,
            )
        except PersistentExecuteReceiveError:
            _record_persistent_execute_degraded(
                sm,
                lane_id,
                reason="receive_error",
                execute_request_id=execute_request_id,
                execute_peer_contract=execute_peer_contract,
            )
            await _abort_persistent_execute_session(
                persistent_session_layer,
                record.god_session_id,
            )
            return False
        except TimeoutError:
            _record_persistent_execute_degraded(
                sm,
                lane_id,
                reason="receive_timeout",
                execute_request_id=execute_request_id,
                execute_peer_contract=execute_peer_contract,
            )
            await _abort_persistent_execute_session(
                persistent_session_layer,
                record.god_session_id,
            )
            return False
        except Exception:
            _record_persistent_execute_degraded(
                sm,
                lane_id,
                reason="receive_failed",
                execute_request_id=execute_request_id,
                execute_peer_contract=execute_peer_contract,
            )
            await _abort_persistent_execute_session(
                persistent_session_layer,
                record.god_session_id,
            )
            return False

    if message is None:
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason="no_result_message",
            execute_request_id=execute_request_id,
            execute_peer_contract=execute_peer_contract,
        )
        await _abort_persistent_execute_session(
            persistent_session_layer,
            record.god_session_id,
        )
        return False

    request_degraded_reason = _persistent_execute_request_degraded_reason(
        message,
        expected_request_id=execute_request_id,
    )
    if request_degraded_reason is not None:
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason=request_degraded_reason,
            execute_request_id=execute_request_id,
            execute_peer_contract=execute_peer_contract,
        )
        await _abort_persistent_execute_session(
            persistent_session_layer,
            record.god_session_id,
        )
        return False

    payload = _persistent_execute_payload(message)
    if payload is None:
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason="no_result_message",
            execute_request_id=execute_request_id,
            execute_peer_contract=execute_peer_contract,
        )
        await _abort_persistent_execute_session(
            persistent_session_layer,
            record.god_session_id,
        )
        return False
    returned_request_id = (
        payload.get("lane_request_id")
        or payload.get("execute_request_id")
        or payload.get(EXECUTE_PEER_REQUEST_ID_FIELD)
    )
    if returned_request_id is not None and str(returned_request_id) != execute_request_id:
        _record_persistent_execute_degraded(
            sm,
            lane_id,
            reason="request_id_mismatch",
            execute_request_id=execute_request_id,
            execute_peer_contract=execute_peer_contract,
        )
        await _abort_persistent_execute_session(
            persistent_session_layer,
            record.god_session_id,
        )
        return False

    return await _apply_persistent_execute_payload(
        lane_id=lane_id,
        sm=sm,
        payload=payload,
        god=god,
        execute_request_id=execute_request_id,
        persistent_execute_identity=identity_key,
        execute_peer_contract=execute_peer_contract,
        on_executed=on_executed,
    )


def _persistent_execute_worktree(xmuse_root: Path) -> Path:
    return xmuse_root.parent if xmuse_root.name == "xmuse" else xmuse_root


def _persistent_model_for_god(
    god: GodConfig,
    persistent_session_layer: PersistentExecuteSessionLayer,
) -> str | None:
    if god.model:
        return god.model
    model_getter = getattr(persistent_session_layer, "persistent_model_for_runtime", None)
    if callable(model_getter):
        value = model_getter(AgentRuntime(god.runtime))
        if isinstance(value, str) and value.strip():
            return normalize_codex_model_id(value, profile_id=ProviderProfileId.GOD)
    if god.runtime == "codex":
        return normalize_codex_model_id(
            os.environ.get("XMUSE_CODEX_MODEL", DEFAULT_CODEX_GOD_MODEL_ID),
            profile_id=ProviderProfileId.GOD,
        )
    return None


def _persistent_peer_prompt_fingerprint(god: GodConfig, *, role: str) -> str:
    lines = [
        f"role={role}",
        f"god={god.name}",
        f"runtime={god.runtime}",
        f"skill_prompt_path={god.skill_prompt_path}",
    ]
    if god.model:
        lines.append(f"model={god.model}")
    if god.worker_model:
        lines.append(f"worker_model={god.worker_model}")
    if god.delegation_mode:
        lines.append(f"delegation_mode={god.delegation_mode}")
    return fingerprint_prompt("\n".join(lines))


def _execute_request_id(identity_key: str, lane_id: str) -> str:
    return f"execute-{_safe_session_fragment(identity_key)}-{_safe_session_fragment(lane_id)}"


def _execute_peer_contract(
    lane_id: str,
    lane: dict[str, Any],
) -> ExecutePeerContract | None:
    execute_peer_id = _optional_text(lane.get(EXECUTE_PEER_ID_FIELD))
    if execute_peer_id is None:
        return None
    routing_mode = _optional_text(lane.get(EXECUTE_PEER_ROUTING_MODE_FIELD))
    if (
        routing_mode is not None
        and routing_mode.lower() != EXECUTE_PEER_ROUTING_MODE_PREFERRED
    ):
        return None
    return ExecutePeerContract(
        execute_peer_id=execute_peer_id,
        request_id=(
            f"execute-peer-{_safe_session_fragment(execute_peer_id)}-"
            f"{_safe_session_fragment(lane_id)}"
        ),
        routing_mode=EXECUTE_PEER_ROUTING_MODE_PREFERRED,
    )


def _execute_peer_metadata(
    execute_peer_contract: ExecutePeerContract,
    *,
    delivery_mode: str,
    degraded_reason: str | None = None,
) -> dict[str, Any]:
    metadata = {
        EXECUTE_PEER_ID_FIELD: execute_peer_contract.execute_peer_id,
        EXECUTE_PEER_REQUEST_ID_FIELD: execute_peer_contract.request_id,
        EXECUTE_PEER_ROUTING_MODE_FIELD: execute_peer_contract.routing_mode,
        EXECUTE_PEER_DELIVERY_MODE_FIELD: delivery_mode,
    }
    if degraded_reason is not None:
        metadata[EXECUTE_PEER_DEGRADED_REASON_FIELD] = degraded_reason
    return metadata


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _persistent_execute_prompt(
    prompt: str,
    *,
    god: GodConfig,
    execute_request_id: str,
    identity_key: str,
    execute_peer_contract: ExecutePeerContract,
) -> str:
    return (
        f"{prompt.rstrip()}\n\n"
        "## Persistent Execute Routing\n\n"
        f"- execute_peer_id: {execute_peer_contract.execute_peer_id}\n"
        f"- execute_peer_request_id: {execute_peer_contract.request_id}\n"
        f"- execute_peer_routing_mode: {execute_peer_contract.routing_mode}\n"
        f"- execute_request_id: {execute_request_id}\n"
        f"- persistent_execute_identity: {identity_key}\n"
        f"{_persistent_execute_model_policy_lines(god)}"
        "- This request is protected by single-flight routing for this identity.\n"
        f"{_persistent_execute_delegation_instruction(god)}"
    )


def _persistent_execute_model_policy_lines(god: GodConfig) -> str:
    lines = []
    if god.model:
        lines.append(f"- coordinator_model: {god.model}")
    if god.worker_model:
        lines.append(f"- worker_model: {god.worker_model}")
    if god.delegation_mode:
        lines.append(f"- delegation_mode: {god.delegation_mode}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _persistent_execute_delegation_instruction(god: GodConfig) -> str:
    if god.delegation_mode == "bounded_worker":
        worker_model = god.worker_model or "unset"
        return (
            "\n## Bounded Worker Delegation Contract\n\n"
            "- Coordinator layer: plan the lane, delegate bounded code-writing "
            "work, collect diffs, changed files, tests run, and summaries, "
            "then perform first-pass integration.\n"
            "- Worker layer: use a temporary_child_worker with configured "
            f"worker_model {worker_model}.\n"
            "- Runtime constraint: codex-only; do not choose other runtimes "
            "or autonomously optimize model/cost choices.\n"
        )
    if god.delegation_mode == "legacy_single_agent":
        return "- Complete this request in the persistent execute coordinator session.\n"
    return ""


def _persistent_execute_request_degraded_reason(
    message: StdoutMessage,
    *,
    expected_request_id: str,
) -> str | None:
    if message.request_id is None:
        return "request_id_missing"
    if message.request_id != expected_request_id:
        return "request_id_mismatch"
    return None


def _persistent_execute_context(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]],
) -> str:
    feature_context = build_feature_context_bundle(
        lane,
        all_lanes=all_lanes,
        xmuse_root=xmuse_root,
    )
    return "\n\n".join(
        section
        for section in [
            feature_context.as_prompt_context(),
            _lane_execute_context_for_prompt(lane),
        ]
        if section
    )


def _lane_execute_context_for_prompt(lane: dict[str, Any]) -> str:
    lane_id = str(lane.get("feature_id") or "unknown")
    prompt = str(lane.get("prompt") or "").strip()
    lines = ["## Lane Execution Context", "", f"- Lane ID: {lane_id}"]
    if lane.get("model_policy_enabled") is True:
        for key in (
            "model_policy_runtime",
            "coordinator_model",
            "worker_model",
            "delegation_mode",
        ):
            value = lane.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"- {key}: {value.strip()}")
    if prompt:
        lines.extend(["", "### Lane Prompt", "", prompt])
    else:
        lines.append("- Lane prompt unavailable.")
    return "\n".join(lines)


async def _receive_persistent_execute_result(
    persistent_session_layer: PersistentExecuteSessionLayer,
    *,
    god_session_id: str,
    timeout_s: float,
) -> StdoutMessage | None:
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        message = await asyncio.wait_for(
            persistent_session_layer.receive_message(god_session_id),
            timeout=remaining,
        )
        if message is None:
            return None
        if message.type == "result":
            return message
        if message.type == "error":
            if _is_persistent_execute_returncode_message(message):
                return message
            raise PersistentExecuteReceiveError()


class PersistentExecuteReceiveError(RuntimeError):
    pass


def _persistent_execute_payload(message: StdoutMessage) -> dict[str, Any] | None:
    if message.type not in {"result", "error"}:
        return None
    payload = message.artifacts.get(EXECUTE_PEER_RESULT_ARTIFACT_FIELD)
    if isinstance(payload, dict):
        return payload
    payload = message.artifacts.get("execution_result")
    if isinstance(payload, dict):
        return payload
    if "returncode" in message.artifacts:
        if not _is_persistent_execute_returncode_message(message):
            return None
        normalized = dict(message.artifacts)
        normalized["exit_code"] = message.artifacts["returncode"]
        return normalized
    return None


def _is_persistent_execute_returncode_message(message: StdoutMessage) -> bool:
    if "returncode" not in message.artifacts:
        return False
    message_type = message.artifacts.get("message_type")
    return message_type in {None, "execute"}


async def _apply_persistent_execute_payload(
    *,
    lane_id: str,
    sm: LaneStateMachine,
    payload: dict[str, Any],
    god: GodConfig,
    execute_request_id: str,
    persistent_execute_identity: str,
    execute_peer_contract: ExecutePeerContract,
    on_executed: Callable[[str], Awaitable[None]],
) -> bool:
    timed_out = bool(payload.get("timed_out", False))
    exit_code = _int_payload_value(payload.get("exit_code"), default=1)
    metadata = {
        "parent_god": god.name,
        "parent_god_role": "execute",
        "worker_kind": "temporary_child_worker",
        "execute_delivery_mode": "persistent",
        "persistent_execute_degraded": False,
        "persistent_execute_identity": persistent_execute_identity,
        "execute_request_id": execute_request_id,
    } | _execute_peer_metadata(
        execute_peer_contract,
        delivery_mode=EXECUTE_PEER_DELIVERY_MODE_CONFIGURED,
    )
    current = sm.get_lane(lane_id)
    if current["status"] != "dispatched":
        if current["status"] == "executed" and exit_code == 0 and not timed_out:
            await on_executed(lane_id)
        return True
    if timed_out:
        sm.transition(
            lane_id,
            "exec_failed",
            metadata=metadata
            | {
                "failure_reason": "timeout",
                "failure_layer": _execution_result_failure_layer(god),
                "execute_failure_source": _EXECUTE_FAILURE_SOURCE_WORKER_TEST_GATE,
            },
        )
        return True
    if exit_code == 0:
        log_event(logger, logging.INFO, "execution_god_completed", lane_id=lane_id)
        sm.transition(lane_id, "executed", metadata=metadata)
        await on_executed(lane_id)
        return True
    sm.transition(
        lane_id,
        "exec_failed",
        metadata=metadata
        | {
            "failure_reason": "non_zero_exit",
            "failure_layer": _execution_result_failure_layer(god),
            "execute_failure_source": _EXECUTE_FAILURE_SOURCE_WORKER_TEST_GATE,
        },
    )
    return True


def _execution_result_failure_layer(god: GodConfig) -> str:
    return "worker" if god.delegation_mode == "bounded_worker" else "coordinator"


def _int_payload_value(value: Any, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _ensure_failure_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "worktree" in message or "cannot reuse" in message:
        return "worktree_mismatch"
    return "ensure_failed"


async def _abort_persistent_execute_session(
    persistent_session_layer: PersistentExecuteSessionLayer,
    god_session_id: str,
) -> None:
    try:
        await persistent_session_layer.abort_session(god_session_id)
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "persistent_execute_god_abort_failed",
            god_session_id=god_session_id,
            exc_info=True,
        )


def _record_persistent_execute_degraded(
    sm: LaneStateMachine,
    lane_id: str,
    *,
    reason: str,
    execute_request_id: str | None = None,
    execute_peer_contract: ExecutePeerContract | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "execute_delivery_mode": "one_shot_fallback",
        "persistent_execute_degraded": True,
        "persistent_execute_degraded_reason": reason,
        "persistent_execute_degraded_source": _EXECUTE_DEGRADED_SOURCE_COORDINATOR_SESSION,
    }
    if execute_request_id is not None:
        metadata["execute_request_id"] = execute_request_id
    if execute_peer_contract is not None:
        metadata.update(
            _execute_peer_metadata(
                execute_peer_contract,
                delivery_mode=EXECUTE_PEER_DELIVERY_MODE_ONE_SHOT_FALLBACK,
                degraded_reason=reason,
            )
        )
        metadata["execute_request_id"] = execute_peer_contract.request_id
    sm.update_metadata(lane_id, metadata)


def _safe_session_fragment(value: str, *, max_chars: int = 80) -> str:
    fragment = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in value
    ).strip("-")
    return (fragment or "lane")[:max_chars]


def _memoryos_metadata(result: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    process_pid = getattr(result, "process_pid", None)
    if isinstance(process_pid, int) and not isinstance(process_pid, bool):
        metadata["worker_pid"] = process_pid
        metadata["worker_heartbeat_at"] = time.time()
    session_id = getattr(result, "memoryos_session_id", None)
    if session_id:
        metadata["memoryos_session_id"] = session_id
    if getattr(result, "memoryos_context_attached", False):
        metadata["memoryos_context_attached"] = True
    if getattr(result, "memoryos_ingested", False):
        metadata["memoryos_ingested"] = True
    degraded_reason = getattr(result, "memoryos_degraded_reason", None)
    if degraded_reason:
        metadata["memoryos_degraded_reason"] = str(degraded_reason)
    return metadata
