from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.envelopes import normalize_envelope
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.mentions import MentionResolutionError, MentionResolver
from xmuse_core.chat.natural_handoff import (
    assess_natural_handoff,
    build_handoff_envelope,
)
from xmuse_core.chat.natural_routing import build_natural_route_event, natural_route_payload
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_proposals import classify_structured_proposal
from xmuse_core.chat.peer_types import PeerChatError
from xmuse_core.chat.review_trigger_verdicts import (
    REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE,
    ReviewTriggerVerdictError,
    review_trigger_verdict_decision,
)
from xmuse_core.chat.review_triggers import ReviewTriggerService
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
        review_verdict = self._review_trigger_verdict(
            conversation_id=conversation_id,
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            diagnostic=diagnostic,
            source_refs=source_refs,
        )
        if review_verdict is not None:
            return self._record_review_trigger_verdict(
                conversation_id=conversation_id,
                participant_id=participant_id,
                reply_to_inbox_item_id=reply_to_inbox_item_id,
                provider_result=provider_result,
                content=content,
                envelope=review_verdict["envelope"],
                proposal_id=review_verdict["proposal_id"],
                verdict=review_verdict["verdict"],
                source_refs=source_refs,
            )
        proposal_writeback = self._record_structured_proposal(
            conversation_id=conversation_id,
            participant_id=participant_id,
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            provider_result=provider_result,
            diagnostic=diagnostic,
            source_refs=source_refs,
        )
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
                **(
                    {"proposal_writeback": proposal_writeback}
                    if proposal_writeback is not None
                    else {}
                ),
            },
            envelope_type="a2a_provider_result",
        )
        extra_result: dict[str, Any] = {
            "a2a_writeback": {
                "provider_request_id": provider_result.request_id,
                "provider_profile_ref": provider_result.provider_profile_ref,
                "provider_status": provider_result.status.value,
                "source_refs": source_refs,
                "authority": "chat.db/inbox",
                "a2a_is_authority": False,
            }
        }
        if proposal_writeback is not None:
            extra_result["proposal_writeback"] = proposal_writeback
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
            extra_result=extra_result,
        )

    def _review_trigger_verdict(
        self,
        *,
        conversation_id: str,
        reply_to_inbox_item_id: str,
        diagnostic: dict[str, Any],
        source_refs: list[str],
    ) -> dict[str, Any] | None:
        try:
            inbox_item = ChatInboxStore(self._db_path).get(reply_to_inbox_item_id)
        except KeyError:
            return None
        if (
            inbox_item.conversation_id != conversation_id
            or inbox_item.item_type != "review_trigger"
        ):
            return None
        metadata = diagnostic.get("a2a_metadata")
        if not isinstance(metadata, dict):
            return None
        raw_envelope = metadata.get("xmuse_review_trigger_verdict")
        if not isinstance(raw_envelope, dict):
            return None
        proposal_id = _proposal_id_from_message(
            self._chat,
            conversation_id=conversation_id,
            source_message_id=inbox_item.source_message_id,
        )
        if proposal_id is None:
            return None
        envelope = normalize_envelope(
            raw_envelope,
            envelope_type=REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE,
        )
        envelope.setdefault("authority", "chat.db/inbox/review_trigger_verdict")
        envelope.setdefault("a2a_is_authority", False)
        envelope.setdefault("a2a_source_refs", list(source_refs))
        try:
            verdict = review_trigger_verdict_decision(
                envelope,
                expected_inbox_item_id=inbox_item.id,
                expected_source_message_id=inbox_item.source_message_id,
                expected_proposal_id=proposal_id,
            )
        except ReviewTriggerVerdictError:
            return None
        return {
            "envelope": envelope,
            "proposal_id": proposal_id,
            "verdict": verdict,
        }

    def _record_review_trigger_verdict(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        reply_to_inbox_item_id: str,
        provider_result: ProviderInvocationResult,
        content: str,
        envelope: dict[str, Any],
        proposal_id: str,
        verdict: str,
        source_refs: list[str],
    ) -> dict[str, Any]:
        result = self._chat.create_message_inbox_and_log(
            conversation_id=conversation_id,
            tool_name="a2a_provider_review_verdict",
            caller_identity=participant_id,
            client_request_id=(
                f"{provider_result.request_id}:{reply_to_inbox_item_id}:review-verdict"
            ),
            author=participant_id,
            role="assistant",
            content=content,
            envelope_type=REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE,
            envelope_json=envelope,
            mentions=[],
            inbox_items=[],
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            reply_owner_participant_id=participant_id,
            extra_result={
                "a2a_writeback": {
                    "provider_request_id": provider_result.request_id,
                    "provider_profile_ref": provider_result.provider_profile_ref,
                    "provider_status": provider_result.status.value,
                    "source_refs": source_refs,
                    "authority": "chat.db/inbox/review_trigger_verdict",
                    "a2a_is_authority": False,
                },
                "review_trigger_verdict": {
                    "proposal_id": proposal_id,
                    "decision": verdict,
                },
            },
        )
        message = result.get("message")
        message_id = message.get("id") if isinstance(message, dict) else None
        if isinstance(message_id, str) and message_id:
            verdict_ref = f"review_trigger_verdict:{message_id}"
            spine = AcceptanceSpineStore(self._db_path)
            if verdict == "blocked":
                spine.attach_review_blocker_for_proposal(
                    proposal_id=proposal_id,
                    blocker_ref=verdict_ref,
                )
            elif verdict == "dispatch_allowed":
                spine.attach_verdict_for_proposal(
                    proposal_id=proposal_id,
                    verdict_ref=verdict_ref,
                )
        return result

    def _record_structured_proposal(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        reply_to_inbox_item_id: str,
        provider_result: ProviderInvocationResult,
        diagnostic: dict[str, Any],
        source_refs: list[str],
    ) -> dict[str, Any] | None:
        proposal_payload = _proposal_payload_from_diagnostic(diagnostic)
        if proposal_payload is None:
            return None
        try:
            proposal_type, content, references, summary = _normalize_proposal_payload(
                proposal_payload,
                reply_to_inbox_item_id=reply_to_inbox_item_id,
                source_refs=source_refs,
            )
            _require_a2a_lane_graph_gate_profiles(
                proposal_type=proposal_type,
                content=content,
            )
            escalation = classify_structured_proposal(
                proposal_type=proposal_type,
                content=content,
                references=references,
            )
            result = self._chat.create_proposal_message_and_log(
                conversation_id=conversation_id,
                tool_name="a2a_provider_proposal_writeback",
                caller_identity=participant_id,
                client_request_id=(
                    f"{provider_result.request_id}:{reply_to_inbox_item_id}:proposal"
                ),
                author=participant_id,
                proposal_type=escalation.normalized_proposal_type,
                content=escalation.normalized_content,
                references=references,
                message_content=f"[a2a proposal] {summary}",
                envelope_json=normalize_envelope(
                    {
                        "type": "proposal",
                        "schema_version": 1,
                        "source_kind": "a2a_provider_result",
                        "provider_profile_ref": provider_result.provider_profile_ref,
                        "provider_request_id": provider_result.request_id,
                        "proposal_type": escalation.normalized_proposal_type,
                        "source_refs": references,
                        "authority": "chat.db/proposal",
                        "a2a_is_authority": False,
                    },
                    envelope_type="proposal",
                ),
            )
        except PeerChatError as exc:
            reason = (
                exc.code
                if exc.code == "missing_gate_profiles"
                else "invalid_xmuse_proposal"
            )
            return {
                "status": "blocked",
                "reason": reason,
                "detail": str(exc),
                "authority": "chat.db/inbox",
                "a2a_is_authority": False,
                "source_refs": source_refs,
            }
        except (TypeError, ValueError) as exc:
            return {
                "status": "blocked",
                "reason": "invalid_xmuse_proposal",
                "detail": str(exc),
                "authority": "chat.db/inbox",
                "a2a_is_authority": False,
                "source_refs": source_refs,
            }
        proposal = result.get("proposal")
        message = result.get("message")
        proposal_id = proposal.get("id") if isinstance(proposal, dict) else None
        message_id = message.get("id") if isinstance(message, dict) else None
        spine_proposal_link = self._attach_acceptance_spine_for_proposal(
            conversation_id=conversation_id,
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            proposal_id=proposal_id,
        )
        review_trigger = self._ensure_review_trigger_for_proposal(
            conversation_id=conversation_id,
            participant_id=participant_id,
            proposal_id=proposal_id,
            proposal_message_id=message_id,
            proposal_type=(
                proposal.get("proposal_type") if isinstance(proposal, dict) else None
            ),
        )
        return {
            "status": "accepted",
            "proposal_id": proposal_id,
            "proposal_message_id": message_id,
            "proposal_type": (
                proposal.get("proposal_type") if isinstance(proposal, dict) else None
            ),
            "acceptance_spine": spine_proposal_link,
            "review_trigger": review_trigger,
            "authority": "chat.db/proposal",
            "a2a_is_authority": False,
            "source_refs": source_refs,
        }

    def _attach_acceptance_spine_for_proposal(
        self,
        *,
        conversation_id: str,
        reply_to_inbox_item_id: str,
        proposal_id: str | None,
    ) -> dict[str, Any]:
        if not proposal_id:
            return {
                "status": "blocked",
                "reason": "missing_proposal_id",
                "authority": "chat.db/acceptance_spine",
                "a2a_is_authority": False,
            }
        spine = AcceptanceSpineStore(self._db_path).attach_proposal_for_inbox_reply(
            conversation_id=conversation_id,
            inbox_item_id=reply_to_inbox_item_id,
            proposal_id=proposal_id,
        )
        if spine is None:
            return {
                "status": "not_applicable",
                "reason": "no_acceptance_spine_for_source_inbox",
                "proposal_id": proposal_id,
                "authority": "chat.db/acceptance_spine",
                "a2a_is_authority": False,
            }
        return {
            "status": "attached",
            "proposal_id": proposal_id,
            "intake_message_id": spine.intake_message_id,
            "spine_status": spine.status.value,
            "authority": "chat.db/acceptance_spine",
            "a2a_is_authority": False,
        }

    def _ensure_review_trigger_for_proposal(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        proposal_id: str | None,
        proposal_message_id: str | None,
        proposal_type: str | None,
    ) -> dict[str, Any]:
        if not proposal_id or not proposal_message_id:
            return {
                "status": "blocked",
                "reason": "missing_proposal_message",
                "authority": "chat.db/inbox/review_trigger",
                "a2a_is_authority": False,
            }
        try:
            trigger = ReviewTriggerService(self._db_path).ensure_for_message(
                conversation_id=conversation_id,
                source_message_id=proposal_message_id,
                sender_participant_id=participant_id,
                reviewable_type=proposal_type or "proposal",
            )
        except PeerChatError as exc:
            return {
                "status": "blocked",
                "reason": str(exc.code),
                "detail": str(exc),
                "proposal_id": proposal_id,
                "proposal_message_id": proposal_message_id,
                "authority": "chat.db/inbox/review_trigger",
                "a2a_is_authority": False,
            }
        return {
            "status": "ensured",
            "inbox_item_id": trigger.id,
            "proposal_id": proposal_id,
            "proposal_message_id": proposal_message_id,
            "authority": "chat.db/inbox/review_trigger",
            "a2a_is_authority": False,
        }

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


def _proposal_payload_from_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any] | None:
    metadata = diagnostic.get("a2a_metadata")
    if not isinstance(metadata, dict):
        return None
    payload = metadata.get("xmuse_proposal")
    return payload if isinstance(payload, dict) else None


def _normalize_proposal_payload(
    payload: dict[str, Any],
    *,
    reply_to_inbox_item_id: str,
    source_refs: list[str],
) -> tuple[str, str, list[str], str]:
    proposal_type = _required_text(payload.get("proposal_type"), "proposal_type")
    raw_content = payload.get("content")
    if isinstance(raw_content, dict):
        content = json.dumps(raw_content, ensure_ascii=False, sort_keys=True)
        summary = _summary_from_payload(raw_content)
    else:
        content = _required_text(raw_content, "content")
        summary = _bounded_summary(content)
    raw_summary = payload.get("summary")
    if isinstance(raw_summary, str) and raw_summary.strip():
        summary = raw_summary.strip()
    references = _dedupe_refs(
        [
            f"inbox:{reply_to_inbox_item_id}",
            *source_refs,
            *_payload_references(payload),
        ]
    )
    return proposal_type, content, references, summary


def _require_a2a_lane_graph_gate_profiles(
    *,
    proposal_type: str,
    content: str,
) -> None:
    if proposal_type.strip() != "lane_graph":
        return
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        resolution = payload.get("resolution_content")
        if isinstance(resolution, dict):
            lanes = resolution.get("lanes")
    if not isinstance(lanes, list):
        return
    missing: list[str] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if _lane_has_gate_profile(lane):
            continue
        feature_id = str(lane.get("feature_id") or "<unknown>").strip()
        missing.append(feature_id or "<unknown>")
    if missing:
        raise PeerChatError(
            "missing_gate_profiles",
            "A2A lane_graph proposal lanes require explicit gate_profiles before "
            f"dispatch: {', '.join(missing)}",
        )


def _lane_has_gate_profile(lane: dict[str, Any]) -> bool:
    gate_profiles = lane.get("gate_profiles")
    if isinstance(gate_profiles, list) and any(
        str(item).strip() for item in gate_profiles
    ):
        return True
    gate_profile = lane.get("gate_profile")
    return isinstance(gate_profile, str) and bool(gate_profile.strip())


def _payload_references(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("references")
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _summary_from_payload(payload: dict[str, Any]) -> str:
    for key in ("summary", "title", "goal"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _bounded_summary(value)
    return "A2A structured proposal"


def _bounded_summary(value: str, *, max_chars: int = 120) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _dedupe_refs(refs: list[str]) -> list[str]:
    deduped: list[str] = []
    for ref in refs:
        cleaned = str(ref).strip()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _proposal_id_from_message(
    chat: ChatStore,
    *,
    conversation_id: str,
    source_message_id: str | None,
) -> str | None:
    if not source_message_id:
        return None
    source_message = next(
        (
            message
            for message in chat.list_messages(conversation_id)
            if message.id == source_message_id
        ),
        None,
    )
    if source_message is None or not isinstance(source_message.envelope_json, dict):
        return None
    proposal_id = source_message.envelope_json.get("proposal_id")
    return proposal_id if isinstance(proposal_id, str) and proposal_id.strip() else None
