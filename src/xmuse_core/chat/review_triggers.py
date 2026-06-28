from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.models import ChatInboxItem
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.peer_types import PeerChatError
from xmuse_core.chat.review_trigger_verdicts import REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE
from xmuse_core.chat.store import ChatStore


class ReviewTriggerService:
    """Create durable review-trigger inbox items for proposal messages."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._chat = ChatStore(self._db_path)
        self._inbox = ChatInboxStore(self._db_path)
        self._participants = ParticipantStore(self._db_path)

    def ensure_for_message(
        self,
        *,
        conversation_id: str,
        source_message_id: str,
        sender_participant_id: str,
        reviewable_type: str,
    ) -> ChatInboxItem:
        review_participant = self._review_participant(conversation_id)
        existing = self._find_review_trigger(
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            review_participant_id=review_participant.participant_id,
        )
        if existing is not None:
            return existing
        trigger = self._inbox.create_item(
            conversation_id=conversation_id,
            target_participant_id=review_participant.participant_id,
            target_role=review_participant.role,
            target_address="@review",
            sender_participant_id=sender_participant_id,
            sender_address=f"@participant:{sender_participant_id}",
            source_message_id=source_message_id,
            item_type="review_trigger",
            payload=self._review_trigger_payload(
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                reviewable_type=reviewable_type,
            ),
        )
        proposal_id = proposal_id_from_message(
            self._chat,
            conversation_id=conversation_id,
            message_id=source_message_id,
        )
        if proposal_id is not None:
            AcceptanceSpineStore(self._db_path).attach_review_trigger_for_proposal(
                proposal_id=proposal_id,
                review_trigger_inbox_id=trigger.id,
            )
        return trigger

    def _review_trigger_payload(
        self,
        *,
        conversation_id: str,
        source_message_id: str,
        reviewable_type: str,
    ) -> dict[str, Any]:
        source_message = next(
            (
                message
                for message in self._chat.list_messages(conversation_id)
                if message.id == source_message_id
            ),
            None,
        )
        projection_envelope = (
            self._review_projection_envelope(
                conversation_id=conversation_id,
                envelope=source_message.envelope_json,
            )
            if source_message is not None
            else {}
        )
        content = (
            _review_trigger_content(
                source_message_id=source_message_id,
                reviewable_type=reviewable_type,
                source_content=source_message.content,
                envelope=projection_envelope,
                collaboration_context=self._review_collaboration_context(
                    conversation_id=conversation_id,
                    envelope=projection_envelope,
                ),
            )
            if source_message is not None
            else f"Review {reviewable_type} message {source_message_id}."
        )
        return {
            "content": content,
            "reviewable_type": reviewable_type,
            "source_message_id": source_message_id,
            "trigger_mode": "automatic",
        }

    def _review_projection_envelope(
        self,
        *,
        conversation_id: str,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        proposal_id = envelope.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            return envelope
        proposal = next(
            (item for item in self._chat.list_proposals(conversation_id) if item.id == proposal_id),
            None,
        )
        if proposal is None:
            return envelope
        projection = dict(envelope)
        try:
            proposal_content = json.loads(proposal.content)
        except json.JSONDecodeError:
            proposal_content = {}
        if isinstance(proposal_content, dict):
            for key in ("summary", "lanes", "resolution_content"):
                if key not in projection and key in proposal_content:
                    projection[key] = proposal_content[key]
        if "references" not in projection:
            projection["references"] = list(proposal.references)
        return projection

    def _review_collaboration_context(
        self,
        *,
        conversation_id: str,
        envelope: dict[str, Any],
    ) -> list[str]:
        references = envelope.get("references")
        if not isinstance(references, list):
            return []
        run_ids = _collaboration_reference_run_ids(
            [ref for ref in references if isinstance(ref, str)]
        )
        if not run_ids:
            return []
        from xmuse_core.chat.collaboration_store import ChatCollaborationStore

        store = ChatCollaborationStore(self._db_path)
        lines: list[str] = ["Use this durable collaboration authority when checking references."]
        for run_id in run_ids:
            try:
                run = store.get_run(run_id)
            except KeyError:
                lines.append(f"- collaboration:{run_id}: unknown")
                continue
            if run.conversation_id != conversation_id:
                lines.append(f"- collaboration:{run_id}: foreign_conversation")
                continue
            lines.append(
                "- collaboration:"
                f"{run.run_id}: status={run.status.value}, "
                f"targets={','.join(run.targets)}, "
                f"responses={len(run.responses)}/{len(run.targets)}"
            )
            for response in run.responses:
                lines.append("  - " + _collaboration_response_review_summary(response))
            for blocker in run.blockers:
                if blocker.active and blocker.blocks_dispatch:
                    lines.append(
                        "  - active_blocker:"
                        f" severity={blocker.severity}, reason={blocker.reason}, "
                        f"suggested_fix={blocker.suggested_fix}"
                    )
        return lines

    def _find_review_trigger(
        self,
        *,
        conversation_id: str,
        source_message_id: str,
        review_participant_id: str,
    ) -> ChatInboxItem | None:
        for item in self._inbox.list_by_conversation(
            conversation_id,
            include_terminal=True,
        ):
            if (
                item.target_participant_id == review_participant_id
                and item.source_message_id == source_message_id
            ):
                return item
        return None

    def _review_participant(self, conversation_id: str) -> Participant:
        matches = [
            participant
            for participant in self._participants.list_by_conversation(conversation_id)
            if participant.role == "review" and participant.status == "active"
        ]
        if not matches:
            raise PeerChatError("review_trigger_target_missing", conversation_id)
        if len(matches) > 1:
            raise PeerChatError("review_trigger_target_ambiguous", conversation_id)
        return matches[0]


def proposal_id_from_message(
    chat: ChatStore,
    *,
    conversation_id: str,
    message_id: str,
) -> str | None:
    for message in chat.list_messages(conversation_id):
        if message.id != message_id:
            continue
        proposal_id = message.envelope_json.get("proposal_id")
        if isinstance(proposal_id, str) and proposal_id:
            return proposal_id
    return None


def _review_trigger_content(
    *,
    source_message_id: str,
    reviewable_type: str,
    source_content: str,
    envelope: dict[str, Any],
    collaboration_context: list[str] | None = None,
) -> str:
    sections = [
        f"Review this {reviewable_type} proposal.",
        f"Source message: {source_message_id}",
        (
            "You must finish this review turn with exactly one durable MCP "
            "writeback to this inbox item. If dispatch may proceed, call "
            "chat_post_message with reply_to_inbox_item_id set to "
            "xmuse_context.inbox_item.id and envelope.type="
            f"{REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE}."
        ),
        (
            "The envelope must contain: review_trigger_inbox_id="
            "xmuse_context.inbox_item.id, source_message_id, proposal_id, "
            "decision=dispatch_allowed or blocked, non-empty summary, and "
            "non-empty evidence_refs. A plain stdout reply or message text "
            "without this envelope does not clear dispatch."
        ),
        (
            "If a collaboration issue must block dispatch, call "
            "chat_raise_collaboration_blocker. A plain chat_post_message "
            "recommendation cannot block dispatch."
        ),
    ]
    proposal_id = envelope.get("proposal_id")
    if isinstance(proposal_id, str) and proposal_id.strip():
        sections.append(f"Proposal id: {proposal_id.strip()}")
        sections.append(
            "Envelope shape: "
            '{"type":"review_trigger_verdict",'
            '"review_trigger_inbox_id":"<xmuse_context.inbox_item.id>",'
            f'"source_message_id":"{source_message_id}",'
            f'"proposal_id":"{proposal_id.strip()}",'
            '"decision":"dispatch_allowed|blocked",'
            '"summary":"<review decision summary>",'
            '"evidence_refs":["<durable ref>"]}'
        )
    summary = envelope.get("summary")
    if isinstance(summary, str) and summary.strip():
        sections.append(f"Summary: {summary.strip()}")
    lanes = envelope.get("lanes")
    if isinstance(lanes, list) and lanes:
        sections.append("Lanes:")
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            feature_id = lane.get("feature_id")
            prompt = lane.get("prompt")
            if isinstance(feature_id, str) and feature_id.strip():
                line = f"- {feature_id.strip()}"
                if isinstance(prompt, str) and prompt.strip():
                    line += f": {prompt.strip()}"
                gate_profiles = _lane_gate_profiles(lane)
                if gate_profiles:
                    line += "; gate_profiles=" + json.dumps(gate_profiles, separators=(",", ":"))
                sections.append(line)
    references = envelope.get("references")
    if isinstance(references, list) and references:
        refs = [ref for ref in references if isinstance(ref, str) and ref.strip()]
        if refs:
            sections.append("References: " + ", ".join(refs))
    if collaboration_context:
        sections.append("Collaboration authority:")
        sections.extend(collaboration_context)
    if source_content.strip():
        sections.extend(["Source content:", source_content.strip()])
    return "\n".join(sections)


def _collaboration_reference_run_ids(references: list[str]) -> list[str]:
    run_ids: list[str] = []
    seen: set[str] = set()
    for reference in references:
        prefix, separator, raw_run_id = reference.strip().partition(":")
        if separator != ":" or prefix != "collaboration":
            continue
        run_id = raw_run_id.strip()
        if not run_id or run_id in seen:
            continue
        seen.add(run_id)
        run_ids.append(run_id)
    return run_ids


def _lane_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _lane_gate_profiles(lane: dict[str, Any]) -> list[str]:
    profiles = _lane_string_list(lane.get("gate_profiles"))
    if profiles:
        return profiles
    singular = lane.get("gate_profile")
    if isinstance(singular, str) and singular.strip():
        return [singular.strip()]
    return []


def _collaboration_response_review_summary(response: Any) -> str:
    base = f"response target={response.target} status={response.status}"
    try:
        payload = json.loads(response.content)
    except json.JSONDecodeError:
        content = response.content.strip()
        if content:
            return f"{base}: {content[:500]}"
        return base
    if not isinstance(payload, dict):
        return base
    parts = [base]
    for key in ("type", "status", "execution_performed", "summary"):
        value = payload.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    evidence_refs = payload.get("evidence_refs")
    if isinstance(evidence_refs, list):
        refs = [ref for ref in evidence_refs if isinstance(ref, str) and ref.strip()]
        if refs:
            parts.append("evidence_refs=" + ",".join(refs[:5]))
    return "; ".join(parts)
