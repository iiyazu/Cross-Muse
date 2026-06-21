from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from xmuse_core.agents.persistent_peer import fingerprint_prompt
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.context_assembler import ContextAssembler
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.mentions import (
    MentionResolver,
    ResolvedMention,
)
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.prompt_builder import XmusePromptBuilder
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import ChatStreamStore, PeerTurnLatencyTraceStore

_DURABLE_WRITEBACK = object()


@dataclass(frozen=True)
class PeerChatSchedulerOutcome:
    nudged: int = 0
    happy_path: int = 0
    failed: int = 0
    fallback_replies: int = 0


class PeerChatScheduler:
    def __init__(
        self,
        *,
        db_path: Path,
        god_layer,
        worktree: Path,
        scheduler_id: str,
        claim_ttl_s: int = 240,
        response_wait_s: float = 180.0,
        post_writeback_grace_s: float = 8.0,
        degraded_fallback_enabled: bool = False,
        only_inbox_item_id: str | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._db_path = db_path
        self._inbox = ChatInboxStore(db_path)
        self._participants = ParticipantStore(db_path)
        self._chat = ChatStore(db_path)
        self._latency = PeerTurnLatencyTraceStore(db_path)
        self._context_assembler = ContextAssembler(
            participants=self._participants,
            chat=self._chat,
        )
        self._prompt_builder = XmusePromptBuilder()
        self._god_layer = god_layer
        self._worktree = worktree
        self._scheduler_id = scheduler_id
        self._claim_ttl_s = claim_ttl_s
        self._response_wait_s = response_wait_s
        self._post_writeback_grace_s = max(0.0, post_writeback_grace_s)
        self._degraded_fallback_enabled = degraded_fallback_enabled
        self._only_inbox_item_id = only_inbox_item_id
        self._clock = clock or time.monotonic
        self._participant_locks: dict[str, asyncio.Lock] = {}

    async def tick_once(self) -> PeerChatSchedulerOutcome:
        item = self._inbox.claim_next(
            owner=self._scheduler_id,
            claim_ttl_s=self._claim_ttl_s,
            item_id=self._only_inbox_item_id,
        )
        if item is None:
            return PeerChatSchedulerOutcome()

        trace_start_at = self._clock()
        delivery_started_at = self._clock()
        provider_turn_started_at = delivery_started_at
        scheduler_observed_result_at = None
        transport_latency_stages: dict[str, dict[str, float]] = {}
        try:
            if item.target_participant_id is None:
                raise RuntimeError("inbox item missing target_participant_id")
            participant = self._participants.get(item.target_participant_id)
            async with self._delivery_lock_for_participant(participant.participant_id):
                return await self._deliver_claimed_item(
                    item,
                    participant=participant,
                    trace_start_at=trace_start_at,
                    delivery_started_at=delivery_started_at,
                    provider_turn_started_at=provider_turn_started_at,
                    scheduler_observed_result_at=scheduler_observed_result_at,
                    transport_latency_stages=transport_latency_stages,
                )
        except Exception as exc:
            self._record_latency_trace(
                item,
                trace_start_at=trace_start_at,
                delivery_started_at=delivery_started_at,
                provider_turn_started_at=provider_turn_started_at,
                scheduler_observed_result_at=scheduler_observed_result_at,
                delivery_mode="failed",
                degraded_reason=str(exc),
            )
            self._finish_active_stream_for_item(item, status="error")
            self._record_failed_nudge(item.id, reason=str(exc))
            return PeerChatSchedulerOutcome(failed=1)

    def _delivery_lock_for_participant(self, participant_id: str) -> asyncio.Lock:
        lock = self._participant_locks.get(participant_id)
        if lock is None:
            lock = asyncio.Lock()
            self._participant_locks[participant_id] = lock
        return lock

    async def _deliver_claimed_item(
        self,
        item,
        *,
        participant: Participant,
        trace_start_at: float,
        delivery_started_at: float,
        provider_turn_started_at: float,
        scheduler_observed_result_at: float | None,
        transport_latency_stages: dict[str, dict[str, float]],
    ) -> PeerChatSchedulerOutcome:
        record = None
        try:
            agent = AgentDescriptor(
                name=participant.display_name,
                runtime=_runtime_for_participant(participant),
                capabilities=[participant.role],
            )
            group_context = self._context_assembler.group_chat_context(
                item.conversation_id
            )
            group_context = self._with_retry_feedback(group_context, item)
            assembled_prompt = self._prompt_builder.build_peer_chat_prompt(
                participant=participant,
                inbox_item=item,
                group_context=group_context,
            )
            record = await self._god_layer.ensure_conversation_session(
                conversation_id=item.conversation_id,
                participant_id=participant.participant_id,
                role=participant.role,
                agent=agent,
                worktree=self._worktree,
                model=participant.model,
                prompt_fingerprint=_peer_session_prompt_fingerprint(participant),
                feature_scope_id=None,
            )
            _record_prompt_contract_if_supported(
                self._god_layer,
                record.god_session_id,
                assembled_prompt.as_session_contract(),
            )
            provider_turn_started_at = self._clock()
            await self._god_layer.send_message(
                record.god_session_id,
                "peer_chat_nudge",
                prompt=assembled_prompt.text,
                context=json.dumps(
                    self._context_assembler.turn_context(
                        conversation_id=item.conversation_id,
                        participant_id=participant.participant_id,
                        god_session_id=record.god_session_id,
                        inbox_item=item,
                        group_chat=group_context,
                        prompt_artifact=assembled_prompt.as_context_artifact(),
                    )
                ),
                request_id=item.id,
            )
            try:
                message = await self._receive_message_or_durable_writeback(
                    record.god_session_id,
                    item=item,
                    participant=participant,
                )
                if message is _DURABLE_WRITEBACK:
                    await _abort_session_if_supported(
                        self._god_layer,
                        record.god_session_id,
                    )
                    self._finish_active_stream_for_item(item, status="done")
                    self._record_latency_trace(
                        item,
                        trace_start_at=trace_start_at,
                        delivery_started_at=delivery_started_at,
                        provider_turn_started_at=provider_turn_started_at,
                        scheduler_observed_result_at=None,
                        delivery_mode="mcp_writeback",
                        degraded_reason="peer_writeback_before_provider_result",
                    )
                    self._inbox.record_nudge_result(
                        item.id,
                        owner=self._scheduler_id,
                        success=True,
                    )
                    return PeerChatSchedulerOutcome(nudged=1, happy_path=1)
            except TimeoutError:
                refreshed = self._inbox.get(item.id)
                if refreshed.status == "read" and self._has_durable_writeback(
                    item.conversation_id,
                    refreshed.responded_message_id,
                    participant_id=participant.participant_id,
                    inbox_item_id=item.id,
                    item_type=getattr(item, "item_type", None),
                ):
                    await _abort_session_if_supported(self._god_layer, record.god_session_id)
                    self._finish_active_stream_for_item(item, status="done")
                    self._record_latency_trace(
                        item,
                        trace_start_at=trace_start_at,
                        delivery_started_at=delivery_started_at,
                        provider_turn_started_at=provider_turn_started_at,
                        scheduler_observed_result_at=None,
                        delivery_mode="mcp_writeback",
                        degraded_reason="peer_response_timeout_after_writeback",
                    )
                    self._inbox.record_nudge_result(
                        item.id,
                        owner=self._scheduler_id,
                        success=True,
                    )
                    return PeerChatSchedulerOutcome(nudged=1, happy_path=1)
                await _abort_session_if_supported(self._god_layer, record.god_session_id)
                self._finish_active_stream_for_item(item, status="error")
                reason = "provider_no_mcp_writeback_before_deadline"
                trace = self._record_latency_trace(
                    item,
                    trace_start_at=trace_start_at,
                    delivery_started_at=delivery_started_at,
                    provider_turn_started_at=provider_turn_started_at,
                    scheduler_observed_result_at=None,
                    delivery_mode="failed",
                    degraded_reason=reason,
                )
                if self._post_degraded_fallback_if_enabled(
                    item,
                    participant=participant,
                    reason=reason,
                ):
                    return PeerChatSchedulerOutcome(fallback_replies=1)
                self._terminalize_claimed_item_failure(
                    item,
                    reason=reason,
                    trace=trace,
                )
                return PeerChatSchedulerOutcome(failed=1)
            scheduler_observed_result_at = self._clock()
            if message is None or getattr(message, "type", None) == "error":
                reason = _message_failure_reason(message)
                refreshed = self._inbox.get(item.id)
                if refreshed.status == "read" and self._has_durable_writeback(
                    item.conversation_id,
                    refreshed.responded_message_id,
                    participant_id=participant.participant_id,
                    inbox_item_id=item.id,
                    item_type=getattr(item, "item_type", None),
                ):
                    self._finish_active_stream_for_item(item, status="done")
                    self._record_latency_trace(
                        item,
                        trace_start_at=trace_start_at,
                        delivery_started_at=delivery_started_at,
                        provider_turn_started_at=provider_turn_started_at,
                        scheduler_observed_result_at=scheduler_observed_result_at,
                        delivery_mode="mcp_writeback",
                        degraded_reason=_after_writeback_reason(reason),
                    )
                    self._inbox.record_nudge_result(
                        item.id,
                        owner=self._scheduler_id,
                        success=True,
                    )
                    return PeerChatSchedulerOutcome(nudged=1, happy_path=1)
                self._finish_active_stream_for_item(item, status="error")
                self._record_latency_trace(
                    item,
                    trace_start_at=trace_start_at,
                    delivery_started_at=delivery_started_at,
                    provider_turn_started_at=provider_turn_started_at,
                    scheduler_observed_result_at=scheduler_observed_result_at,
                    delivery_mode="failed",
                    degraded_reason=reason,
                )
                if self._post_degraded_fallback_if_enabled(
                    item,
                    participant=participant,
                    reason=reason,
                ):
                    return PeerChatSchedulerOutcome(fallback_replies=1)
                self._record_failed_nudge(item.id, reason=reason)
                return PeerChatSchedulerOutcome(failed=1)
            transport_latency_stages = _latency_stages_from_message(message)
            refreshed = self._inbox.get(item.id)
            if refreshed.status != "read":
                if self._degraded_fallback_enabled and self._post_stdout_reply_if_available(
                    item,
                    participant=participant,
                    message=message,
                ):
                    self._finish_active_stream_for_item(item, status="error")
                    self._record_latency_trace(
                        item,
                        trace_start_at=trace_start_at,
                        delivery_started_at=delivery_started_at,
                        provider_turn_started_at=provider_turn_started_at,
                        scheduler_observed_result_at=scheduler_observed_result_at,
                        delivery_mode="stdout_fallback",
                        degraded_reason="stdout_fallback",
                        transport_latency_stages=transport_latency_stages,
                    )
                    return PeerChatSchedulerOutcome(fallback_replies=1)
                if self._post_degraded_fallback_if_enabled(
                    item,
                    participant=participant,
                    reason="peer_no_inbox_side_effect",
                ):
                    self._finish_active_stream_for_item(item, status="error")
                    self._record_latency_trace(
                        item,
                        trace_start_at=trace_start_at,
                        delivery_started_at=delivery_started_at,
                        provider_turn_started_at=provider_turn_started_at,
                        scheduler_observed_result_at=scheduler_observed_result_at,
                        delivery_mode="degraded_fallback",
                        degraded_reason="peer_no_inbox_side_effect",
                        transport_latency_stages=transport_latency_stages,
                    )
                    return PeerChatSchedulerOutcome(fallback_replies=1)
                self._record_latency_trace(
                    item,
                    trace_start_at=trace_start_at,
                    delivery_started_at=delivery_started_at,
                    provider_turn_started_at=provider_turn_started_at,
                    scheduler_observed_result_at=scheduler_observed_result_at,
                    delivery_mode="failed",
                    degraded_reason="peer_no_inbox_side_effect",
                    transport_latency_stages=transport_latency_stages,
                )
                self._finish_active_stream_for_item(item, status="error")
                self._record_failed_nudge(item.id, reason="peer_no_inbox_side_effect")
                return PeerChatSchedulerOutcome(failed=1)
            if not self._has_durable_writeback(
                item.conversation_id,
                refreshed.responded_message_id,
                participant_id=participant.participant_id,
                inbox_item_id=item.id,
                item_type=getattr(item, "item_type", None),
            ):
                self._finish_active_stream_for_item(item, status="error")
                self._record_latency_trace(
                    item,
                    trace_start_at=trace_start_at,
                    delivery_started_at=delivery_started_at,
                    provider_turn_started_at=provider_turn_started_at,
                    scheduler_observed_result_at=scheduler_observed_result_at,
                    delivery_mode="failed",
                    degraded_reason="peer_no_inbox_writeback_message",
                    transport_latency_stages=transport_latency_stages,
                )
                self._record_failed_nudge(
                    item.id,
                    reason="peer_no_inbox_writeback_message",
                )
                return PeerChatSchedulerOutcome(failed=1)
        except asyncio.CancelledError:
            reason = "provider_turn_cancelled_before_mcp_writeback"
            if record is not None:
                await _abort_session_if_supported(self._god_layer, record.god_session_id)
            self._finish_active_stream_for_item(item, status="error")
            trace = self._record_latency_trace(
                item,
                trace_start_at=trace_start_at,
                delivery_started_at=delivery_started_at,
                provider_turn_started_at=provider_turn_started_at,
                scheduler_observed_result_at=scheduler_observed_result_at,
                delivery_mode="failed",
                degraded_reason=reason,
                transport_latency_stages=transport_latency_stages,
            )
            self._terminalize_claimed_item_failure(
                item,
                reason=reason,
                trace=trace,
            )
            raise
        except Exception as exc:
            self._record_latency_trace(
                item,
                trace_start_at=trace_start_at,
                delivery_started_at=delivery_started_at,
                provider_turn_started_at=provider_turn_started_at,
                scheduler_observed_result_at=scheduler_observed_result_at,
                delivery_mode="failed",
                degraded_reason=str(exc),
            )
            self._finish_active_stream_for_item(item, status="error")
            self._record_failed_nudge(item.id, reason=str(exc))
            return PeerChatSchedulerOutcome(failed=1)

        self._inbox.record_nudge_result(item.id, owner=self._scheduler_id, success=True)
        self._finish_active_stream_for_item(item, status="done")
        self._record_latency_trace(
            item,
            trace_start_at=trace_start_at,
            delivery_started_at=delivery_started_at,
            provider_turn_started_at=provider_turn_started_at,
            scheduler_observed_result_at=scheduler_observed_result_at,
            delivery_mode="mcp_writeback",
            degraded_reason=None,
            transport_latency_stages=transport_latency_stages,
        )
        return PeerChatSchedulerOutcome(nudged=1, happy_path=1)

    async def _receive_message_or_durable_writeback(
        self,
        god_session_id: str,
        *,
        item,
        participant: Participant,
    ):
        receive_task = asyncio.create_task(self._god_layer.receive_message(god_session_id))
        deadline = time.monotonic() + self._response_wait_s
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    receive_task.cancel()
                    raise TimeoutError
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(receive_task),
                        timeout=min(1.0, remaining),
                    )
                except TimeoutError:
                    refreshed = self._inbox.get(item.id)
                    if refreshed.status == "read" and self._has_durable_writeback(
                        item.conversation_id,
                        refreshed.responded_message_id,
                        participant_id=participant.participant_id,
                        inbox_item_id=item.id,
                        item_type=getattr(item, "item_type", None),
                    ):
                        grace_result = await self._wait_for_provider_result_during_grace(
                            receive_task
                        )
                        if grace_result is not _DURABLE_WRITEBACK:
                            return grace_result
                        receive_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await receive_task
                        return _DURABLE_WRITEBACK
        except BaseException:
            if not receive_task.done():
                receive_task.cancel()
            raise

    async def _wait_for_provider_result_during_grace(self, receive_task: asyncio.Task):
        deadline = time.monotonic() + self._post_writeback_grace_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _DURABLE_WRITEBACK
            try:
                return await asyncio.wait_for(
                    asyncio.shield(receive_task),
                    timeout=min(1.0, remaining),
                )
            except TimeoutError:
                continue

    async def tick_many(self, *, max_concurrent: int = 1) -> PeerChatSchedulerOutcome:
        if max_concurrent <= 1 or self._only_inbox_item_id is not None:
            return await self.tick_once()
        outcomes = await asyncio.gather(
            *(self.tick_once() for _ in range(max_concurrent))
        )
        return PeerChatSchedulerOutcome(
            nudged=sum(outcome.nudged for outcome in outcomes),
            happy_path=sum(outcome.happy_path for outcome in outcomes),
            failed=sum(outcome.failed for outcome in outcomes),
            fallback_replies=sum(outcome.fallback_replies for outcome in outcomes),
        )

    def _has_durable_writeback(
        self,
        conversation_id: str,
        responded_message_id: str | None,
        *,
        participant_id: str,
        inbox_item_id: str,
        item_type: str | None,
    ) -> bool:
        if self._has_real_writeback_message(
            conversation_id,
            responded_message_id,
            participant_id=participant_id,
            inbox_item_id=inbox_item_id,
        ):
            return True
        stages = set(self._latency.list_mcp_tool_stages(conversation_id, inbox_item_id))
        return (
            item_type == "collaboration_request"
            and "chat_record_collaboration_response" in stages
        )

    def _has_real_writeback_message(
        self,
        conversation_id: str,
        responded_message_id: str | None,
        *,
        participant_id: str,
        inbox_item_id: str,
    ) -> bool:
        if not responded_message_id:
            return False
        message = next(
            (
                item
                for item in self._chat.list_messages(conversation_id)
                if item.id == responded_message_id
            ),
            None,
        )
        if message is None:
            return False
        if message.author != participant_id or message.role != "assistant":
            return False
        stages = self._latency.list_mcp_tool_stages(conversation_id, inbox_item_id)
        return bool(
            {
                "chat_create_collaboration_request",
                "chat_emit_proposal",
                "chat_mention",
                "chat_post_message",
            }
            & set(stages)
        )

    def _record_latency_trace(
        self,
        item,
        *,
        trace_start_at: float,
        delivery_started_at: float,
        provider_turn_started_at: float,
        scheduler_observed_result_at: float | None,
        delivery_mode: str,
        degraded_reason: str | None,
        transport_latency_stages: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, object]:
        writeback_at = self._clock()
        mcp_tool_stages = self._latency.list_mcp_tool_stages(item.conversation_id, item.id)
        first_delta_at = _stage_at(transport_latency_stages, "first_stream_delta")
        stage_timings = _build_stage_timings(
            trace_start_at=trace_start_at,
            delivery_started_at=delivery_started_at,
            provider_turn_started_at=provider_turn_started_at,
            scheduler_observed_result_at=scheduler_observed_result_at,
            writeback_at=writeback_at,
            transport_latency_stages=transport_latency_stages,
            mcp_tool_stages=mcp_tool_stages,
        )
        return self._latency.record(
            conversation_id=item.conversation_id,
            inbox_item_id=item.id,
            participant_id=item.target_participant_id,
            target_role=item.target_role,
            message_created_at=item.created_at,
            inbox_claimed_at=item.claimed_at,
            delivery_started_at=delivery_started_at,
            provider_turn_started_at=provider_turn_started_at,
            first_delta_at=first_delta_at,
            writeback_at=writeback_at,
            total_latency_ms=round((writeback_at - trace_start_at) * 1000),
            delivery_mode=delivery_mode,
            degraded_reason=degraded_reason,
            stage_timings=stage_timings,
        )

    def _terminalize_claimed_item_failure(
        self,
        item,
        *,
        reason: str,
        trace: dict[str, object] | None = None,
    ) -> None:
        self._inbox.mark_failed(item.id, reason=reason)
        trace_id = trace.get("id") if isinstance(trace, dict) else None
        evidence_ref = (
            f"peer_turn_latency_traces#trace={trace_id}"
            if isinstance(trace_id, str) and trace_id
            else None
        )
        AcceptanceSpineStore(self._db_path).mark_intake_failed(
            intake_message_id=item.source_message_id,
            blocked_reason=reason,
            evidence_ref=evidence_ref,
        )

    def _finish_active_stream_for_item(self, item, *, status: str) -> None:
        try:
            ChatStreamStore(self._db_path).finish_active_for_source(
                conversation_id=item.conversation_id,
                source_inbox_item_id=item.id,
                status="error" if status == "error" else "done",
            )
        except Exception:
            return

    def _record_failed_nudge(self, item_id: str, *, reason: str) -> None:
        self._inbox.record_nudge_result(
            item_id,
            owner=self._scheduler_id,
            success=False,
            reason=reason,
        )

    def _with_retry_feedback(self, group_context: dict, item) -> dict:
        feedback = self._retry_feedback_for_item(item)
        if feedback is None:
            return group_context
        enriched = dict(group_context)
        guidance = list(enriched.get("turn_guidance") or [])
        guidance.append(feedback)
        enriched["turn_guidance"] = guidance
        capsule = dict(enriched.get("context_capsule") or {})
        capsule["degraded_state"] = {
            "inbox_item_id": item.id,
            "nudge_count": item.nudge_count,
            "retry_feedback": feedback,
        }
        enriched["context_capsule"] = capsule
        enriched["retry_feedback"] = feedback
        return enriched

    def _retry_feedback_for_item(self, item) -> str | None:
        if int(getattr(item, "nudge_count", 0) or 0) <= 0:
            return None
        if getattr(item, "item_type", None) != "collaboration_request":
            return None
        reason = self._last_delivery_failure_reason(item) or "peer_no_inbox_side_effect"
        return (
            f"Retry feedback for this same collaboration_request: the previous "
            f"attempt failed with {reason}. Plain final text or stream output was "
            "not accepted as durable reply truth. For this retry, call "
            "chat_record_collaboration_response for the collaboration run named in "
            "xmuse_context.inbox_item.payload.content. Do not answer with plain text. "
            "If mcp_tools_ready appears, MCP tools are available; do not say durable "
            "writeback is unavailable."
        )

    def _last_delivery_failure_reason(self, item) -> str | None:
        for trace in self._latency.list_recent(item.conversation_id, limit=20):
            if trace.get("inbox_item_id") != item.id:
                continue
            reason = trace.get("degraded_reason")
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
        return None

    def _post_degraded_fallback_if_enabled(
        self,
        item,
        *,
        participant: Participant,
        reason: str,
    ) -> bool:
        if not self._degraded_fallback_enabled:
            return False
        try:
            self._inbox.get(item.id)
        except KeyError:
            return False
        content = _degraded_fallback_content(participant, reason=reason)
        message = self._chat.add_message(
            item.conversation_id,
            author=participant.participant_id,
            role="assistant",
            content=content,
            envelope_type="peer_reply",
            envelope_json={"source_inbox_item_id": item.id, "degraded_reason": reason},
        )
        self._inbox.mark_read(item.id, responded_message_id=message.id)
        return True

    def _post_stdout_reply_if_available(
        self,
        item,
        *,
        participant: Participant,
        message,
    ) -> bool:
        content = _stdout_reply_content(message)
        if not content:
            return False
        mentions = _resolve_routable_mentions(
            self._participants,
            conversation_id=item.conversation_id,
            content=content,
            sender_participant_id=participant.participant_id,
        )
        self._chat.create_message_inbox_and_log(
            conversation_id=item.conversation_id,
            tool_name="peer_stdout_reply",
            caller_identity=f"scheduler:{self._scheduler_id}:{participant.participant_id}",
            client_request_id=f"{item.id}:stdout",
            author=participant.participant_id,
            role="assistant",
            content=content,
            envelope_type="peer_reply",
            envelope_json={
                "source_inbox_item_id": item.id,
                "degraded_reason": "stdout_fallback",
            },
            mentions=[mention.normalized for mention in mentions],
            inbox_items=[],
            reply_to_inbox_item_id=item.id,
            reply_owner_participant_id=participant.participant_id,
        )
        return True


def _latency_stages_from_message(message) -> dict[str, dict[str, float]]:
    artifacts = getattr(message, "artifacts", None)
    if not isinstance(artifacts, dict):
        return {}
    raw_stages = artifacts.get("latency_stages")
    if not isinstance(raw_stages, dict):
        return {}
    stages: dict[str, dict[str, float]] = {}
    for name, raw_stage in raw_stages.items():
        if not isinstance(name, str) or not isinstance(raw_stage, dict):
            continue
        at = raw_stage.get("at")
        if isinstance(at, (int, float)):
            stages[name] = {"at": float(at)}
    return stages


def _build_stage_timings(
    *,
    trace_start_at: float,
    delivery_started_at: float,
    provider_turn_started_at: float,
    scheduler_observed_result_at: float | None,
    writeback_at: float,
    transport_latency_stages: dict[str, dict[str, float]] | None,
    mcp_tool_stages: dict[str, dict[str, float]] | None,
) -> dict[str, dict[str, float]]:
    stages = {
        "inbox_claim": {"at": trace_start_at},
        "ray_actor_delivery_start": {"at": delivery_started_at},
        "codex_app_server_turn_start": {"at": provider_turn_started_at},
    }
    if transport_latency_stages:
        stages.update(transport_latency_stages)
    if mcp_tool_stages:
        stages.update(mcp_tool_stages)
    first_visible_at = _first_visible_at(stages)
    if first_visible_at is not None:
        stages["first_visible"] = {"at": first_visible_at}
    if scheduler_observed_result_at is not None:
        stages["scheduler_observed_result"] = {"at": scheduler_observed_result_at}
    stages["trace_persisted"] = {"at": writeback_at}
    return stages


def _stage_at(
    stages: dict[str, dict[str, float]] | None,
    name: str,
) -> float | None:
    if not stages:
        return None
    stage = stages.get(name)
    if not isinstance(stage, dict):
        return None
    at = stage.get("at")
    return float(at) if isinstance(at, (int, float)) else None


def _first_visible_at(stages: dict[str, dict[str, float]]) -> float | None:
    candidates = [
        at
        for at in (
            _stage_at(stages, "stream_started"),
            _stage_at(stages, "first_stream_delta"),
        )
        if at is not None
    ]
    return min(candidates) if candidates else None


def _runtime_for_participant(participant: Participant) -> AgentRuntime:
    if participant.cli_kind == "codex":
        return AgentRuntime.CODEX
    if participant.cli_kind == "opencode":
        return AgentRuntime.OPENCODE
    raise RuntimeError(f"unsupported participant cli_kind: {participant.cli_kind}")


def _peer_session_prompt_fingerprint(participant: Participant) -> str:
    return fingerprint_prompt(
        "\n".join(
            [
                "xmuse-peer-chat-session-v1",
                f"role={participant.role}",
                f"display_name={participant.display_name}",
                f"cli_kind={participant.cli_kind}",
                f"model={participant.model}",
            ]
        )
    )


def _record_prompt_contract_if_supported(
    god_layer,
    god_session_id: str,
    prompt_contract: dict[str, object],
) -> None:
    recorder = getattr(god_layer, "record_prompt_contract", None)
    if not callable(recorder):
        return
    recorder(god_session_id, **prompt_contract)


def _group_chat_context(
    *,
    participants: ParticipantStore,
    chat: ChatStore,
    conversation_id: str,
    recent_limit: int = 8,
) -> dict:
    active_participants = [
        participant
        for participant in participants.list_by_conversation(conversation_id)
        if participant.status == "active"
    ]
    messages = chat.list_messages(conversation_id)[-recent_limit:]
    return {
        "mode": "group_chat",
        "participants": [
            {
                "participant_id": participant.participant_id,
                "role": participant.role,
                "display_name": participant.display_name,
                "status": participant.status,
            }
            for participant in active_participants
        ],
        "recent_messages": [
            {
                "id": message.id,
                "author": message.author,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
                "mentions": list(message.mentions),
            }
            for message in messages
        ],
        "turn_guidance": [
            "Treat the conversation as shared group context.",
            "Avoid repeated greetings and low-information acknowledgement loops.",
            "Mention another GOD by exact @role only when the next turn is useful.",
            "Do not invent aliases such as @him; use the roster roles.",
            "Use structured collaboration/proposal tools for execution closure; "
            "plain chat does not dispatch work.",
        ],
    }


def _inbox_request_preview(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return ""
    preview = content.strip()
    if len(preview) > 8000:
        preview = preview[:7997] + "..."
    return "\n\nCurrent inbox request:\n" + preview


def _participant_roster_text(group_context: dict) -> str:
    participants = group_context.get("participants")
    if not isinstance(participants, list) or not participants:
        return "none"
    return ", ".join(
        f"@{participant.get('role')}={participant.get('display_name')}"
        for participant in participants
        if isinstance(participant, dict)
    )


async def _abort_session_if_supported(god_layer, god_session_id: str) -> None:
    abort = getattr(god_layer, "abort_session", None)
    if not callable(abort):
        return
    await abort(god_session_id)


def _message_failure_reason(message) -> str:
    if message is None:
        return "peer_no_result_message"
    code = getattr(message, "code", None)
    if code:
        return str(code)
    return "peer_error_message"


def _after_writeback_reason(reason: str) -> str:
    if not reason:
        return "peer_error_after_writeback"
    return f"{reason}_after_writeback"


def _stdout_reply_content(message) -> str:
    candidates = [
        getattr(message, "message", None),
        (getattr(message, "artifacts", {}) or {}).get("stdout")
        if isinstance(getattr(message, "artifacts", {}), dict)
        else None,
    ]
    for candidate in candidates:
        text = _bounded_text(candidate)
        if text:
            return text
    return ""


def _resolve_routable_mentions(
    participant_store: ParticipantStore,
    *,
    conversation_id: str,
    content: str,
    sender_participant_id: str,
) -> list[ResolvedMention]:
    resolver = MentionResolver(participant_store)
    mentions: list[ResolvedMention] = []
    seen: set[str] = set()
    for mention in resolver.resolve_content(conversation_id, content, strict=False):
        if mention.participant.participant_id == sender_participant_id:
            continue
        if mention.normalized in seen:
            continue
        seen.add(mention.normalized)
        mentions.append(mention)
    return mentions


def _bounded_text(value, *, max_chars: int = 4000) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


def _degraded_fallback_content(participant: Participant, *, reason: str) -> str:
    role = participant.role.strip().lower()
    name = participant.display_name.strip() or f"{role} GOD"
    if role == "architect":
        return (
            f"{name}: 我已收到。当前 CLI GOD 响应超时，先用快速确认兜底；"
            "请继续给出需求或约束，我会按 architect 视角收敛为蓝图。"
            f" [degraded:{reason}]"
        )
    if role == "review":
        return (
            f"{name}: 我已收到。当前 CLI GOD 响应超时，先记录为待审查事项；"
            "后续会围绕蓝图、验收标准和风险给出 review。"
            f" [degraded:{reason}]"
        )
    if role == "execute":
        return (
            f"{name}: 我已收到。当前 CLI GOD 响应超时，先记录执行请求；"
            "后续执行应通过 lane/worklist 链路继续。"
            f" [degraded:{reason}]"
        )
    return f"{name}: 我已收到，但 CLI GOD 响应超时。 [degraded:{reason}]"
