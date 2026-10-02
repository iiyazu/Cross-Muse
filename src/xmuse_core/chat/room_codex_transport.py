"""Codex transport adapter for participant-owned room observations.

The adapter ensures the session named by participant metadata, then requires its
exact conversation/participant binding before use; it never selects another
participant's session. Provider output only describes transport progress. The
``RoomParticipantHost`` checks durable observation state after delivery and accepts
only ``chat_room_submit_outcome`` state as completion.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_session_identity import (
    participant_session_prompt_fingerprint,
)
from xmuse_core.chat.participant_store import Participant
from xmuse_core.chat.room_agent_stream import RoomAgentStreamProjector
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_ports import ExecutionReviewReceiptWriter
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomTransportResult,
)
from xmuse_core.chat.room_memory_runtime import RoomMemoryContextReceiptPort
from xmuse_core.chat.room_observation_transport_base import (
    ROOM_CONTEXT_BYTE_LIMIT,
    ProviderNeutralDeliveryKit,
    build_room_observation_prompt,
    diagnostic_text,
    failed_result,
    normalized_text,
)
from xmuse_core.chat.room_skill_decisions import (
    RoomAttemptSkillDecisionStore,
    RoomSkillDecisionError,
)

_PROVIDER_SESSION_KIND = "codex_app_server_thread"


@dataclass(frozen=True)
class _CodexSessionProof:
    """The exact provider attachment authorized for one Room delivery.

    ``god_session_id`` is durable participant identity, not a process identity.
    The optional native incarnation prevents a late callback from an aborted
    app-server attachment being treated as belonging to a replacement attached
    under the same durable God identity.
    """

    god_session_id: str
    provider_session_id: str | None
    native_incarnation: int | None


class CodexRoomObservationTransport:
    """Deliver observations through exact conversation participant sessions."""

    def __init__(
        self,
        god_session_layer: GodSessionLayer,
        *,
        worktree: Path | str,
        control_store: RoomObservationControlStore | None = None,
        skill_decision_store: RoomAttemptSkillDecisionStore | None = None,
        execution_store: ExecutionReviewReceiptWriter | None = None,
        memory_runtime: RoomMemoryContextReceiptPort | None = None,
        stream_projector: RoomAgentStreamProjector | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._god_session_layer = god_session_layer
        self._worktree = Path(worktree)
        self._controls = control_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._kit = ProviderNeutralDeliveryKit(
            skill_decision_store=skill_decision_store,
            execution_store=execution_store,
            memory_runtime=memory_runtime,
            stream_projector=stream_projector,
            clock=self._clock,
        )

    async def deliver(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> RoomTransportResult:
        invalid = self._kit.validate_delivery(
            delivery,
            reason_prefix="room_codex",
            supported_cli_kinds=(AgentRuntime.CODEX.value,),
        )
        if invalid is not None:
            return RoomTransportResult("failed", invalid)
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or timeout_s <= 0
        ):
            return RoomTransportResult("failed", "room_codex_timeout_invalid")

        participant = delivery.participant
        activation_failure = self._kit.skill_activation_failure(delivery)
        if activation_failure is not None:
            return activation_failure
        if self._controls is not None:
            if not delivery.attempt_id:
                return RoomTransportResult("failed", "room_codex_attempt_binding_missing")
            try:
                self._controls.mark_provider_ensure_started(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                return failed_result("room_codex_attempt_binding_failed", exc)
        try:
            prompt_fingerprint = _resume_prompt_fingerprint(
                self._god_session_layer,
                conversation_id=delivery.conversation_id,
                participant_id=participant.participant_id,
                feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
                proposed_fingerprint=participant_session_prompt_fingerprint(participant),
            )
            ensured = await self._god_session_layer.ensure_conversation_session(
                conversation_id=delivery.conversation_id,
                participant_id=participant.participant_id,
                role=participant.role,
                agent=AgentDescriptor(
                    name=participant.display_name,
                    runtime=AgentRuntime.CODEX,
                    capabilities=[participant.role],
                ),
                worktree=self._worktree,
                model=participant.model,
                prompt_fingerprint=prompt_fingerprint,
                feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
            )
        except Exception as exc:
            return failed_result("room_codex_session_ensure_failed", exc)
        try:
            record = self._god_session_layer.require_live_provider_session_binding(
                conversation_id=delivery.conversation_id,
                participant_id=participant.participant_id,
                runtime=AgentRuntime.CODEX,
                provider_session_kind=_PROVIDER_SESSION_KIND,
                feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
            )
        except Exception as exc:
            return failed_result("room_codex_binding_unavailable", exc)
        if (
            record.conversation_id != delivery.conversation_id
            or record.participant_id != participant.participant_id
            or record.role != participant.role
            or record.runtime != AgentRuntime.CODEX.value
            or record.feature_scope_id != ROOM_DELIVERY_SESSION_SCOPE
            or ensured.feature_scope_id != ROOM_DELIVERY_SESSION_SCOPE
            or ensured.god_session_id != record.god_session_id
        ):
            return RoomTransportResult("failed", "room_codex_binding_identity_mismatch")
        provider_session_id = normalized_text(record.provider_session_id)
        try:
            session_proof = _CodexSessionProof(
                god_session_id=record.god_session_id,
                provider_session_id=provider_session_id,
                native_incarnation=_native_session_incarnation(
                    self._god_session_layer, record.god_session_id
                ),
            )
        except Exception as exc:
            return failed_result("room_codex_session_fenced", exc)
        if self._controls is not None:
            if not delivery.attempt_id or provider_session_id is None:
                await self._abort_delivery_session(
                    record.god_session_id,
                    delivery,
                    reason_code="room_codex_attempt_binding_missing",
                    session_proof=session_proof,
                )
                return RoomTransportResult("failed", "room_codex_attempt_binding_missing")
            try:
                self._controls.bind_provider_session(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    god_session_id=record.god_session_id,
                    provider_session_id=provider_session_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                await self._abort_delivery_session(
                    record.god_session_id,
                    delivery,
                    reason_code="room_codex_attempt_binding_failed",
                    session_proof=session_proof,
                )
                return failed_result("room_codex_attempt_binding_failed", exc)

        submission = self._kit.build_context_submission(
            delivery,
            god_session_id=record.god_session_id,
        )
        context_payload = submission.payload
        context = submission.text
        payload_sha256 = submission.payload_sha256
        if len(context.encode("utf-8")) > ROOM_CONTEXT_BYTE_LIMIT:
            await self._abort_delivery_session(
                record.god_session_id,
                delivery,
                reason_code="room_skill_context_too_large",
                session_proof=session_proof,
            )
            return RoomTransportResult("failed", "room_skill_context_too_large")
        prompt = build_room_observation_prompt()
        preview = await self._kit.open_preview(
            delivery,
            subscribe_native_events=getattr(
                self._god_session_layer, "subscribe_native_events", None
            ),
            god_session_id=record.god_session_id,
            session_is_current=lambda: _session_proof_is_current(
                self._god_session_layer, session_proof
            ),
        )
        preview_finalized = False
        try:
            async with asyncio.timeout(float(timeout_s)):
                if not _session_proof_is_current(self._god_session_layer, session_proof):
                    return RoomTransportResult("failed", "room_codex_session_fenced")
                await self._god_session_layer.send_message(
                    record.god_session_id,
                    "room_observation",
                    prompt=prompt,
                    context=context,
                    request_id=delivery.transport_request_id,
                )
                self._kit.bind_memory_context_receipt(
                    delivery,
                    context_payload=context_payload,
                    context_payload_sha256=payload_sha256,
                )
                try:
                    self._kit.bind_execution_review_receipts(
                        delivery,
                        context_payload=context_payload,
                        context_payload_sha256=payload_sha256,
                    )
                except RoomExecutionStoreError as exc:
                    await self._abort_delivery_session(
                        record.god_session_id,
                        delivery,
                        reason_code=exc.code,
                        session_proof=session_proof,
                    )
                    return failed_result(exc.code, exc)
                except Exception as exc:
                    await self._abort_delivery_session(
                        record.god_session_id,
                        delivery,
                        reason_code="room_execution_review_receipt_failed",
                        session_proof=session_proof,
                    )
                    return failed_result("room_execution_review_receipt_failed", exc)
                try:
                    self._kit.mark_skill_context_submitted(
                        delivery,
                        payload_sha256=payload_sha256,
                    )
                except RoomSkillDecisionError as exc:
                    await self._abort_delivery_session(
                        record.god_session_id,
                        delivery,
                        reason_code=exc.code,
                        session_proof=session_proof,
                    )
                    return failed_result(exc.code, exc)
                terminal = await self._receive_terminal(
                    record.god_session_id,
                    request_id=delivery.transport_request_id,
                )
                if not _session_proof_is_current(self._god_session_layer, session_proof):
                    await self._abort_delivery_session(
                        record.god_session_id,
                        delivery,
                        reason_code="room_codex_session_fenced",
                        session_proof=session_proof,
                    )
                    return RoomTransportResult("failed", "room_codex_session_fenced")
                if terminal.status == "failed":
                    await self._abort_delivery_session(
                        record.god_session_id,
                        delivery,
                        reason_code=terminal.reason or "room_codex_terminal_failed",
                        session_proof=session_proof,
                    )
                await self._kit.finalize_preview(
                    preview,
                    provider_succeeded=terminal.status == "finished",
                )
                preview_finalized = True
                return terminal
        except TimeoutError as exc:
            await self._abort_delivery_session(
                record.god_session_id,
                delivery,
                reason_code="room_codex_turn_timeout",
                session_proof=session_proof,
            )
            return failed_result("room_codex_turn_timeout", exc)
        except asyncio.CancelledError:
            await self._abort_delivery_session(
                record.god_session_id,
                delivery,
                reason_code="room_codex_turn_cancelled",
                session_proof=session_proof,
            )
            raise
        except Exception as exc:
            await self._abort_delivery_session(
                record.god_session_id,
                delivery,
                reason_code="room_codex_transport_error",
                session_proof=session_proof,
            )
            return failed_result("room_codex_transport_error", exc)
        finally:
            if not preview_finalized:
                await self._kit.finalize_preview(preview, provider_succeeded=False)

    async def reconcile_cancel(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        attempt: dict[str, Any],
        timeout_s: float,
    ) -> RoomCancelReconcileResult:
        """Reattach and abort only the exact durable Room session generation."""

        attempt_id = normalized_text(attempt.get("attempt_id"))
        expected_god_session_id = normalized_text(attempt.get("god_session_id"))
        expected_provider_session_id = normalized_text(attempt.get("provider_session_id"))
        delivery_generation = normalized_text(attempt.get("provider_session_generation"))
        provider_phase = normalized_text(attempt.get("provider_phase")) or "not_started"
        if (
            participant.conversation_id != conversation_id
            or not attempt_id
            or delivery_generation != attempt_id
        ):
            return RoomCancelReconcileResult("pending", "room_codex_cancel_binding_invalid")
        if provider_phase == "not_started":
            return RoomCancelReconcileResult("settled", "room_codex_cancel_session_not_started")
        if provider_phase == "cleanup_succeeded":
            return RoomCancelReconcileResult(
                "settled",
                normalized_text(attempt.get("provider_cleanup_reason"))
                or "room_codex_cancel_cleanup_already_succeeded",
            )
        binding_state = getattr(
            self._god_session_layer,
            "provider_binding_process_state",
            None,
        )
        if callable(binding_state) and expected_god_session_id and expected_provider_session_id:
            state = binding_state(
                god_session_id=expected_god_session_id,
                provider_session_id=expected_provider_session_id,
            )
            if state == "confirmed_dead":
                return RoomCancelReconcileResult(
                    "settled", "runner_reconciled_provider_process_dead"
                )
            if state == "superseded":
                return RoomCancelReconcileResult(
                    "settled", "room_codex_cancel_binding_superseded_and_fenced"
                )
            if state == "live_owned":
                try:
                    async with asyncio.timeout(float(timeout_s)):
                        await self._god_session_layer.abort_session(expected_god_session_id)
                except Exception:
                    return RoomCancelReconcileResult("pending", "room_codex_cancel_abort_failed")
                return RoomCancelReconcileResult("settled", "runner_reconciled_provider_abort")
            return RoomCancelReconcileResult("pending", "room_codex_cancel_binding_process_unknown")
        try:
            async with asyncio.timeout(float(timeout_s)):
                ensured = await self._god_session_layer.ensure_conversation_session(
                    conversation_id=conversation_id,
                    participant_id=participant.participant_id,
                    role=participant.role,
                    agent=AgentDescriptor(
                        name=participant.display_name,
                        runtime=AgentRuntime.CODEX,
                        capabilities=[participant.role],
                    ),
                    worktree=self._worktree,
                    model=participant.model,
                    prompt_fingerprint=_resume_prompt_fingerprint(
                        self._god_session_layer,
                        conversation_id=conversation_id,
                        participant_id=participant.participant_id,
                        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
                        proposed_fingerprint=participant_session_prompt_fingerprint(participant),
                    ),
                    feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
                )
                if (
                    ensured.conversation_id != conversation_id
                    or ensured.participant_id != participant.participant_id
                    or ensured.role != participant.role
                    or ensured.runtime != AgentRuntime.CODEX.value
                    or ensured.feature_scope_id != ROOM_DELIVERY_SESSION_SCOPE
                ):
                    return RoomCancelReconcileResult(
                        "pending", "room_codex_cancel_binding_identity_mismatch"
                    )
                superseded = (
                    (
                        ensured.god_session_id != expected_god_session_id
                        or ensured.provider_session_id != expected_provider_session_id
                    )
                    if expected_god_session_id and expected_provider_session_id
                    else False
                )
                await self._god_session_layer.abort_session(ensured.god_session_id)
                return RoomCancelReconcileResult(
                    "settled",
                    "room_codex_cancel_binding_superseded_and_fenced"
                    if superseded
                    else "runner_reconciled_provider_abort",
                )
        except Exception:
            return RoomCancelReconcileResult("pending", "room_codex_cancel_abort_failed")

    async def reset_after_missing_outcome(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> bool:
        """Rotate a completed delivery thread before retrying a missing outcome.

        The attempt ledger is the identity source.  A provider turn which ended
        without Room truth may have retained a malformed tool call in its thread
        history; replaying that same thread can deterministically repeat the
        malformed authority.  Abort only the exact bound generation, while the
        participant and God identity remain durable for the next fresh thread.
        """

        if self._controls is None or not delivery.attempt_id:
            return False
        try:
            projection = self._controls.reconcile_state(str(delivery.observation["observation_id"]))
        except (KeyError, RoomControlError):
            return False
        attempt = projection.get("reconcile_binding") or {}
        if (
            attempt.get("attempt_id") != delivery.attempt_id
            or attempt.get("provider_session_generation") != delivery.attempt_id
            or attempt.get("provider_phase") not in {"bound", "cleanup_succeeded"}
        ):
            return False
        if attempt.get("provider_phase") == "cleanup_succeeded":
            return True
        god_session_id = normalized_text(attempt.get("god_session_id"))
        provider_session_id = normalized_text(attempt.get("provider_session_id"))
        if god_session_id is None or provider_session_id is None:
            return False
        binding_state = getattr(self._god_session_layer, "provider_binding_process_state", None)
        if callable(binding_state):
            try:
                state = binding_state(
                    god_session_id=god_session_id,
                    provider_session_id=provider_session_id,
                )
            except Exception:
                return False
            # A new thread/process may share the durable God identity.  A
            # missing outcome must never abort that replacement generation.
            if state == "superseded":
                return False
        try:
            async with asyncio.timeout(float(timeout_s)):
                return await self._abort_delivery_session(
                    god_session_id,
                    delivery,
                    reason_code="room_codex_durable_outcome_missing",
                )
        except (TimeoutError, ValueError):
            return False

    async def _abort_delivery_session(
        self,
        god_session_id: str,
        delivery: RoomObservationDelivery,
        *,
        reason_code: str,
        session_proof: _CodexSessionProof | None = None,
    ) -> bool:
        # Never use a durable God identity to terminate a replacement native
        # attachment.  The ledger cleanup remains pending for reconciliation.
        if session_proof is not None and not _session_proof_is_current(
            self._god_session_layer, session_proof
        ):
            if self._controls is not None and delivery.attempt_id:
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=delivery.observation["observation_id"],
                        attempt_id=delivery.attempt_id,
                        delivery_generation=delivery.attempt_id,
                        succeeded=False,
                        reason_code=f"{reason_code}:session_fenced",
                    )
            return False
        if self._controls is not None and delivery.attempt_id:
            try:
                self._controls.mark_provider_cleanup(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    succeeded=False,
                    reason_code=reason_code,
                )
            except RoomControlError:
                return False
        try:
            await asyncio.shield(self._god_session_layer.abort_session(god_session_id))
        except Exception:
            if self._controls is not None and delivery.attempt_id:
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=delivery.observation["observation_id"],
                        attempt_id=delivery.attempt_id,
                        delivery_generation=delivery.attempt_id,
                        succeeded=False,
                        reason_code=f"{reason_code}:abort_failed",
                    )
            return False
        if self._controls is not None and delivery.attempt_id:
            try:
                self._controls.mark_provider_cleanup(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    succeeded=True,
                    reason_code=f"{reason_code}:abort_succeeded",
                )
            except RoomControlError:
                return False
        return True

    async def _receive_terminal(
        self,
        god_session_id: str,
        *,
        request_id: str,
    ) -> RoomTransportResult:
        while True:
            message = await self._god_session_layer.receive_message(god_session_id)
            if message is None:
                return RoomTransportResult("failed", "room_codex_session_closed")
            if not isinstance(message, StdoutMessage):
                return RoomTransportResult(
                    "failed", "room_codex_protocol_invalid", diagnostic_text(repr(message))
                )
            if message.request_id != request_id:
                return RoomTransportResult(
                    "failed",
                    "room_codex_request_mismatch",
                    diagnostic_text(message.message),
                )
            if message.type == "result":
                if message.status != "success":
                    return RoomTransportResult(
                        "failed",
                        "room_codex_turn_failed",
                        _message_diagnostic(message),
                    )
                # "finished" means the provider turn ended.  It is intentionally
                # not room-completion evidence; RoomParticipantHost checks the
                # durable observation after this method returns.
                return RoomTransportResult("finished", diagnostic_text=_message_diagnostic(message))
            if message.type == "error":
                return RoomTransportResult(
                    "failed",
                    "room_codex_turn_failed",
                    _message_diagnostic(message),
                )


def _native_session_incarnation(layer: object, god_session_id: str) -> int | None:
    """Read the narrow native-process fence when the layer exposes one.

    Older test doubles and non-native implementations deliberately do not grow a
    provider facade just for this transport, so absence is compatible. A present
    but malformed fence is an authority failure, not a value to coerce.
    """

    getter = getattr(layer, "native_session_incarnation", None)
    if not callable(getter):
        return None
    value = getter(god_session_id)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError("native Codex session incarnation invalid")
    return value


def _session_proof_is_current(layer: object, proof: _CodexSessionProof) -> bool:
    if proof.native_incarnation is None:
        return True
    try:
        return _native_session_incarnation(layer, proof.god_session_id) == proof.native_incarnation
    except Exception:
        return False


def _message_diagnostic(message: StdoutMessage) -> str | None:
    value = normalized_text(message.message)
    if value is None and isinstance(message.artifacts, dict):
        value = normalized_text(message.artifacts.get("stdout"))
    if value is None and message.code:
        value = message.code
    return diagnostic_text(value)


def _resume_prompt_fingerprint(
    layer: GodSessionLayer,
    *,
    conversation_id: str,
    participant_id: str,
    feature_scope_id: str,
    proposed_fingerprint: str,
) -> str:
    resolver = getattr(layer, "prompt_fingerprint_for_resume", None)
    if not callable(resolver):
        # Narrow test/compat doubles have no durable registry. Production uses
        # GodSessionLayer and always proves the existing binding fingerprint.
        return proposed_fingerprint
    result = resolver(
        conversation_id=conversation_id,
        participant_id=participant_id,
        feature_scope_id=feature_scope_id,
        proposed_fingerprint=proposed_fingerprint,
    )
    if not isinstance(result, str) or not result:
        raise RuntimeError("room_codex_prompt_fingerprint_invalid")
    return result
