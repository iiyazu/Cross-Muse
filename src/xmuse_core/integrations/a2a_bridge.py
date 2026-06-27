from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.context_assembler import (
    build_participant_profile,
    build_participant_session_binding,
)
from xmuse_core.chat.envelopes import normalize_envelope
from xmuse_core.chat.mentions import MentionResolutionError, MentionResolver
from xmuse_core.chat.natural_handoff import (
    assess_natural_handoff,
    build_handoff_envelope,
)
from xmuse_core.chat.natural_routing import build_natural_route_event, natural_route_payload
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.a2a_sdk_boundary import build_sdk_agent_card_payload


class A2ABridgeError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class A2AInboundTask:
    task_id: str
    context_id: str
    sender_agent_id: str
    content: str
    target_address: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    input_parts: tuple[dict[str, Any], ...] = ()
    sdk_request: dict[str, Any] = field(default_factory=dict)


def build_participant_agent_card(
    participant: Participant,
    *,
    base_url: str,
    version: str = "0.1.0",
    active_participants: list[Participant] | None = None,
    session_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only A2A-compatible card for an xmuse participant."""

    url = base_url.rstrip("/")
    profile = build_participant_profile(
        participant,
        session_binding=session_binding,
        active_participants=active_participants,
    )
    skill = {
        "id": f"xmuse-{participant.role}",
        "name": participant.role,
        "description": f"Participates in xmuse natural groupchat as {participant.role}.",
        "tags": ["xmuse", "groupchat", participant.role],
    }
    compatibility_card = {
        "protocolVersion": "1.0",
        "name": participant.display_name,
        "description": f"xmuse {participant.role} participant",
        "url": f"{url}/a2a/agents/{participant.participant_id}",
        "version": version,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "skills": [
            skill
        ],
        "metadata": {
            "authority": "chat.db",
            "participant_id": participant.participant_id,
            "conversation_id": participant.conversation_id,
            "role": participant.role,
            "mention_handle": profile["mention_handle"],
            "aliases": profile["aliases"],
            "capabilities": profile["capabilities"],
            "default_skill_refs": profile["default_skill_refs"],
            "provider_id": profile["provider_id"],
            "profile_id": profile["profile_id"],
            "cli_kind": participant.cli_kind,
            "model": participant.model,
            "natural_profile": profile,
        },
    }
    compatibility_card["sdk_agent_card"] = build_sdk_agent_card_payload(
        name=participant.display_name,
        description=f"xmuse {participant.role} participant",
        url=f"{url}/a2a/agents/{participant.participant_id}",
        version=version,
        streaming=False,
        push_notifications=False,
        skills=(skill,),
    )
    compatibility_card["sdk_boundary"] = {
        "protocol": "a2a-sdk",
        "authority": "xmuse-chat-db",
        "write_authority": "chat.db/inbox",
    }
    return compatibility_card


def build_participant_agent_card_from_store(
    db_path: Path,
    *,
    participant_id: str,
    base_url: str,
    session_registry_path: Path | None = None,
) -> dict[str, Any]:
    participants = ParticipantStore(db_path)
    participant = participants.get(participant_id)
    active_participants = [
        item
        for item in participants.list_by_conversation(participant.conversation_id)
        if item.status == "active"
    ]
    session = None
    if session_registry_path is not None and session_registry_path.exists():
        try:
            session = GodSessionRegistry(
                session_registry_path
            ).find_by_conversation_participant(
                participant.conversation_id,
                participant.participant_id,
            )
        except KeyError:
            session = None
    return build_participant_agent_card(
        participant,
        base_url=base_url,
        active_participants=active_participants,
        session_binding=build_participant_session_binding(participant, session),
    )


class A2AInboundBridge:
    def __init__(self, db_path: Path | str, *, enabled: bool = False) -> None:
        self._db_path = Path(db_path)
        self._enabled = enabled
        self._chat = ChatStore(self._db_path)
        self._participants = ParticipantStore(self._db_path)

    def record_task_send(self, task: A2AInboundTask) -> dict[str, Any]:
        if not self._enabled:
            return {
                "status": "disabled",
                "reason": "a2a_bridge_disabled",
                "task_id": task.task_id,
            }
        conversation_id = _required(task.context_id, "context_id")
        task_id = _required(task.task_id, "task_id")
        sender_agent_id = _required(task.sender_agent_id, "sender_agent_id")
        content = _required(task.content, "content")
        target_address = _optional_text(task.target_address, "target_address")
        metadata = _metadata_dict(task.metadata)
        input_parts = tuple(task.input_parts)
        sdk_request = _metadata_dict(task.sdk_request)
        self._assert_conversation_exists(conversation_id)
        target = self._resolve_target(
            conversation_id=conversation_id,
            target_address=target_address,
            content=content,
        )
        source_refs = [f"a2a_task:{task_id}", f"a2a_context:{conversation_id}"]
        payload = self._chat.create_message_inbox_and_log(
            conversation_id=conversation_id,
            tool_name="a2a_task_send",
            caller_identity=f"a2a:{sender_agent_id}",
            client_request_id=task_id,
            author=f"a2a:{sender_agent_id}",
            role="assistant",
            content=content,
            envelope_type="a2a_task",
            envelope_json=normalize_envelope(
                {
                    "type": "a2a_task",
                    "task_id": task_id,
                    "context_id": conversation_id,
                    "sender_agent_id": sender_agent_id,
                    "target_address": target.normalized,
                    "input_parts": list(input_parts),
                    "source_refs": source_refs,
                    "metadata": metadata,
                    "sdk_request": sdk_request,
                },
                envelope_type="a2a_task",
            ),
            mentions=[target.normalized],
            inbox_items=[
                self._inbox_item(
                    conversation_id=conversation_id,
                    task_id=task_id,
                    sender_agent_id=sender_agent_id,
                    target=target,
                    content=content,
                    metadata=metadata,
                    input_parts=input_parts,
                    sdk_request=sdk_request,
                    source_refs=source_refs,
                )
            ],
        )
        return {
            "status": "accepted",
            "task_id": task_id,
            "message": payload["message"],
            "inbox_items": payload["inbox_items"],
        }

    def _assert_conversation_exists(self, conversation_id: str) -> None:
        if not any(item.id == conversation_id for item in self._chat.list_conversations()):
            raise A2ABridgeError("unknown_conversation", conversation_id)

    def _resolve_target(
        self,
        *,
        conversation_id: str,
        target_address: str | None,
        content: str,
    ):
        resolver = MentionResolver(self._participants)
        if target_address:
            try:
                target = resolver.resolve(conversation_id, target_address)
                self._assert_explicit_target_matches_leading_content(
                    resolver=resolver,
                    conversation_id=conversation_id,
                    explicit_participant_id=target.participant.participant_id,
                    content=content,
                )
                return target
            except MentionResolutionError as exc:
                raise A2ABridgeError(exc.code, exc.target) from exc
        try:
            targets = resolver.resolve_leading_content(
                conversation_id,
                content,
                strict=True,
            )
            if not targets:
                targets = resolver.resolve_content(
                    conversation_id,
                    content,
                    strict=True,
                )
        except MentionResolutionError as exc:
            raise A2ABridgeError(exc.code, exc.target) from exc
        if not targets:
            raise A2ABridgeError("missing_a2a_target", "target_address or @mention required")
        if len(targets) > 1:
            raise A2ABridgeError(
                "multiple_a2a_targets",
                ",".join(target.normalized for target in targets),
            )
        return targets[0]

    def _assert_explicit_target_matches_leading_content(
        self,
        *,
        resolver: MentionResolver,
        conversation_id: str,
        explicit_participant_id: str,
        content: str,
    ) -> None:
        targets = resolver.resolve_leading_content(
            conversation_id,
            content,
            strict=True,
        )
        if not targets:
            return
        if len(targets) > 1:
            raise A2ABridgeError(
                "multiple_a2a_targets",
                ",".join(target.normalized for target in targets),
            )
        if targets[0].participant.participant_id != explicit_participant_id:
            raise A2ABridgeError(
                "a2a_target_mismatch",
                f"{explicit_participant_id}!={targets[0].participant.participant_id}",
            )

    def _inbox_item(
        self,
        *,
        conversation_id: str,
        task_id: str,
        sender_agent_id: str,
        target,
        content: str,
        metadata: dict[str, Any],
        input_parts: tuple[dict[str, Any], ...],
        sdk_request: dict[str, Any],
        source_refs: list[str],
    ) -> dict[str, Any]:
        assessment = assess_natural_handoff(
            content,
            target_role=target.participant.role,
        )
        blocker_reason = (
            "missing_handoff_fields"
            if assessment.requires_envelope and assessment.missing_fields
            else None
        )
        event = build_natural_route_event(
            conversation_id=conversation_id,
            origin_message_id=task_id,
            source_kind="a2a_inbound",
            author_participant_id=f"a2a:{sender_agent_id}",
            target_participant_id=target.participant.participant_id,
            route_kind=assessment.route_kind
            if assessment.requires_envelope
            else "a2a_task",
            source_refs=source_refs,
            blocker_reason=blocker_reason,
        )
        assessment_payload = assessment.model_dump()
        extra: dict[str, object] = {
            "a2a_task_id": task_id,
            "a2a_context_id": conversation_id,
            "a2a_sender_agent_id": sender_agent_id,
            "a2a_metadata": metadata,
            "a2a_input_parts": list(input_parts),
            "a2a_sdk_request": sdk_request,
            "a2a_sdk_boundary": {
                "protocol": "a2a-sdk",
                "authority": "xmuse-chat-db",
            },
            "handoff_assessment": assessment_payload,
        }
        if assessment.requires_envelope:
            extra["handoff_envelope"] = build_handoff_envelope(
                assessment,
                conversation_id=conversation_id,
                origin_message_id=task_id,
                source_kind="a2a_inbound",
                author_participant_id=f"a2a:{sender_agent_id}",
                target_participant_id=target.participant.participant_id,
                target_role=target.participant.role,
                source_refs=source_refs,
            )
        if blocker_reason:
            extra.update(
                {
                    "blocks_dispatch": True,
                    "blocker_kind": blocker_reason,
                    "missing_fields": list(assessment.missing_fields),
                }
            )
        return {
            "target_participant_id": target.participant.participant_id,
            "target_role": target.participant.role,
            "target_address": target.normalized,
            "sender_participant_id": None,
            "sender_address": f"a2a:{sender_agent_id}",
            "item_type": "a2a_task",
            "payload": natural_route_payload(
                event,
                content=content,
                mention=target.raw,
                extra=extra,
            ),
        }


def _required(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise A2ABridgeError(f"invalid_{field_name}", field_name)
    text = value.strip()
    if not text:
        raise A2ABridgeError(f"missing_{field_name}", field_name)
    return text


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2ABridgeError(f"invalid_{field_name}", field_name)
    return value.strip() or None


def _metadata_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise A2ABridgeError("invalid_metadata", "metadata")
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as exc:
        raise A2ABridgeError("invalid_metadata_json", "metadata") from exc
