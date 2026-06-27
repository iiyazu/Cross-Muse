from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.chat.envelopes import normalize_envelope
from xmuse_core.chat.mentions import MentionResolutionError, MentionResolver
from xmuse_core.chat.natural_handoff import (
    assess_natural_handoff,
    build_handoff_envelope,
)
from xmuse_core.chat.natural_routing import build_natural_route_event, natural_route_payload
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.providers.adapters.base import ProviderInvocationResult
from xmuse_core.providers.models import ProviderId


class A2AWritebackReconcilerError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class A2AProviderWritebackReconciler:
    """Persist A2A provider output through the durable chat/inbox authority."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._chat = ChatStore(self._db_path)
        self._participants = ParticipantStore(self._db_path)

    def record_provider_result(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        reply_to_inbox_item_id: str,
        provider_result: ProviderInvocationResult,
    ) -> dict[str, Any]:
        if provider_result.provider_id is not ProviderId.A2A:
            raise A2AWritebackReconcilerError(
                "unsupported_provider_result",
                provider_result.provider_profile_ref,
            )
        diagnostic = dict(provider_result.diagnostic_payload)
        if not diagnostic:
            raise A2AWritebackReconcilerError(
                "missing_a2a_diagnostic_payload",
                provider_result.request_id,
            )
        source_refs = _source_refs(provider_result, diagnostic)
        content = _content(provider_result, diagnostic)
        inbox_items = self._route_provider_result_mentions(
            conversation_id=conversation_id,
            participant_id=participant_id,
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            provider_result=provider_result,
            content=content,
            source_refs=source_refs,
        )
        envelope = normalize_envelope(
            {
                "type": "a2a_provider_result",
                "provider_profile_ref": provider_result.provider_profile_ref,
                "provider_request_id": provider_result.request_id,
                "provider_status": provider_result.status.value,
                "failure_kind": (
                    provider_result.failure_kind.value
                    if provider_result.failure_kind is not None
                    else None
                ),
                "source_refs": source_refs,
                "diagnostic_payload": diagnostic,
                "authority": "chat.db/inbox",
                "a2a_is_authority": False,
            },
            envelope_type="a2a_provider_result",
        )
        return self._chat.create_message_inbox_and_log(
            conversation_id=conversation_id,
            tool_name="a2a_provider_writeback",
            caller_identity=participant_id,
            client_request_id=(
                f"{provider_result.request_id}:{reply_to_inbox_item_id}"
            ),
            author=participant_id,
            role="assistant",
            content=content,
            envelope_type="a2a_provider_result",
            envelope_json=envelope,
            mentions=[
                str(item["target_address"])
                for item in inbox_items
                if isinstance(item.get("target_address"), str)
            ],
            inbox_items=inbox_items,
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            reply_owner_participant_id=participant_id,
            extra_result={
                "a2a_writeback": {
                    "provider_request_id": provider_result.request_id,
                    "provider_profile_ref": provider_result.provider_profile_ref,
                    "provider_status": provider_result.status.value,
                    "source_refs": source_refs,
                    "authority": "chat.db/inbox",
                    "a2a_is_authority": False,
                }
            },
        )

    def _route_provider_result_mentions(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        reply_to_inbox_item_id: str,
        provider_result: ProviderInvocationResult,
        content: str,
        source_refs: list[str],
    ) -> list[dict[str, Any]]:
        try:
            targets = MentionResolver(self._participants).resolve_leading_content(
                conversation_id,
                content,
                strict=True,
            )
        except MentionResolutionError:
            return []
        inbox_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for target in targets:
            target_participant_id = target.participant.participant_id
            if target_participant_id == participant_id or target_participant_id in seen:
                continue
            seen.add(target_participant_id)
            assessment = assess_natural_handoff(
                content,
                target_role=target.participant.role,
            )
            blocker_reason = (
                "missing_handoff_fields"
                if assessment.requires_envelope and assessment.missing_fields
                else None
            )
            route_event = build_natural_route_event(
                conversation_id=conversation_id,
                origin_message_id=provider_result.request_id,
                source_kind="a2a_provider_result",
                author_participant_id=participant_id,
                target_participant_id=target_participant_id,
                route_kind=(
                    assessment.route_kind
                    if assessment.requires_envelope
                    else "mention"
                ),
                source_refs=[
                    f"inbox:{reply_to_inbox_item_id}",
                    *source_refs,
                ],
                blocker_reason=blocker_reason,
            )
            assessment_payload = assessment.model_dump()
            extra: dict[str, object] = {
                "source_a2a_provider_request_id": provider_result.request_id,
                "source_a2a_provider_status": provider_result.status.value,
                "handoff_assessment": assessment_payload,
            }
            if assessment.requires_envelope:
                extra["handoff_envelope"] = build_handoff_envelope(
                    assessment,
                    conversation_id=conversation_id,
                    origin_message_id=provider_result.request_id,
                    source_kind="a2a_provider_result",
                    author_participant_id=participant_id,
                    target_participant_id=target_participant_id,
                    target_role=target.participant.role,
                    source_refs=source_refs,
                    task_id=provider_result.request_id,
                    source_inbox_item_id=reply_to_inbox_item_id,
                    artifact_refs=list(provider_result.evidence_refs),
                )
            if blocker_reason:
                extra.update(
                    {
                        "blocks_dispatch": True,
                        "blocker_kind": blocker_reason,
                        "blocker_reason": blocker_reason,
                    }
                )
            inbox_items.append(
                {
                    "target_participant_id": target_participant_id,
                    "target_role": target.participant.role,
                    "target_address": target.normalized,
                    "sender_participant_id": participant_id,
                    "sender_address": f"@participant:{participant_id}",
                    "item_type": "mention",
                    "payload": natural_route_payload(
                        route_event,
                        content=content,
                        mention=target.raw,
                        extra=extra,
                    ),
                }
            )
        return inbox_items


def _source_refs(
    provider_result: ProviderInvocationResult,
    diagnostic: dict[str, Any],
) -> list[str]:
    refs = list(provider_result.evidence_refs)
    diagnostic_refs = diagnostic.get("a2a_source_refs")
    if isinstance(diagnostic_refs, list):
        refs.extend(str(item) for item in diagnostic_refs if str(item).strip())
    deduped: list[str] = []
    for ref in refs:
        if ref not in deduped:
            deduped.append(ref)
    return deduped


def _content(
    provider_result: ProviderInvocationResult,
    diagnostic: dict[str, Any],
) -> str:
    content = diagnostic.get("a2a_content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return f"A2A provider result: {provider_result.status.value}"
