from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.bootstrap_contracts import (
    AppliedBootstrap,
    BootstrapDraft,
    BootstrapInitMode,
    BootstrapStatus,
    LogicalForkSpec,
    LogicalPeerSpec,
    TeamPlanProposal,
    bootstrap_apply_id,
    bootstrap_fork_idempotency_key,
    deterministic_draft_id,
    deterministic_proposal_id,
    preset_to_logical_team,
    resolve_groupchat_preset,
)
from xmuse_core.chat.bootstrap_store import BootstrapStateStore
from xmuse_core.chat.collaboration_contracts import CollaborationStatus
from xmuse_core.chat.envelopes import normalize_envelope
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.lane_scope import conversation_scoped_lanes
from xmuse_core.chat.mentions import (
    DEFAULT_INTAKE_ROLE,
    MentionResolutionError,
    MentionResolver,
    default_intake_address,
    extract_mentions,
    has_inactive_mention_candidates,
    normalize_address,
)
from xmuse_core.chat.models import ChatCard, ChatMessage, ChatTimelineItem
from xmuse_core.chat.participant_store import (
    INIT_GOD_DISPLAY_NAME,
    INIT_GOD_ROLE,
    Participant,
    ParticipantStore,
    RoleTemplateStore,
    participant_summary,
    provider_profile_id_for_role,
    resolve_codex_cli_kind,
)
from xmuse_core.chat.peer_cards import PeerChatCardAssembler
from xmuse_core.chat.peer_forks import PeerForkStore
from xmuse_core.chat.peer_progress import (
    build_peer_progress_events,
    peer_progress_counts,
)
from xmuse_core.chat.peer_proposals import PeerProposalEmitter
from xmuse_core.chat.peer_types import PeerChatError, PeerMessageResult
from xmuse_core.chat.roster_events import build_roster_events, roster_event_counts
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.providers.registry import normalize_codex_model_id


def _has_leading_all_mention(content: str) -> bool:
    index = 0
    length = len(content)
    while index < length and content[index].isspace():
        index += 1
    end = index + len("@all")
    if content[index:end].lower() != "@all":
        return False
    return end >= length or not _is_mention_char(content[end])


def _is_mention_char(value: str) -> bool:
    return value.isalnum() or value in "_-:"


class PeerChatService:
    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._base_dir = self._db_path.parent
        self._chat = ChatStore(db_path)
        self._inbox = ChatInboxStore(db_path)
        self._participants = ParticipantStore(db_path)

    def create_conversation(
        self,
        *,
        title: str,
        participants: list[dict[str, Any]] | None = None,
        preset_id: str | None = None,
        init_mode: str = "deterministic",
        provider_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = self._required_string(title, "title")
        try:
            BootstrapInitMode(init_mode)
        except ValueError as exc:
            raise PeerChatError("invalid_bootstrap_init_mode", init_mode) from exc
        try:
            resolve_groupchat_preset(preset_id)
        except ValueError as exc:
            raise PeerChatError("invalid_bootstrap_preset", str(exc)) from exc
        if participants is not None:
            self._normalize_participant_specs(RoleTemplateStore(self._db_path), participants)
        conversation = self._chat.create_conversation(title)
        bootstrap = self.bootstrap_conversation(
            conversation_id=conversation.id,
            participants=participants,
            preset_id=preset_id,
            init_mode="deterministic" if participants is not None else init_mode,
            provider_overrides=provider_overrides,
        )
        return {
            "conversation": conversation.model_dump(mode="json"),
            "participants": bootstrap["participants"],
            "participant_sessions": bootstrap.get("participant_sessions", []),
            "bootstrap": bootstrap,
        }

    def bootstrap_conversation(
        self,
        *,
        conversation_id: str,
        participants: list[dict[str, Any]] | None = None,
        preset_id: str | None = None,
        init_mode: str = "proposal_then_approve",
        provider_overrides: dict[str, Any] | None = None,
        registry_path: Path | None = None,
    ) -> dict[str, Any]:
        conversation = self._conversation(conversation_id)
        if conversation is None:
            raise PeerChatError("unknown_conversation", conversation_id)
        try:
            mode = BootstrapInitMode(init_mode)
        except ValueError as exc:
            raise PeerChatError("invalid_bootstrap_init_mode", init_mode) from exc

        role_templates = RoleTemplateStore(self._db_path)
        participant_specs = (
            self._default_participant_specs(role_templates)
            if participants is None
            else self._normalize_participant_specs(role_templates, participants)
        )
        init_model = self._bootstrap_init_model(participant_specs, role_templates)
        init_participant = self._participants.ensure_init_god(
            conversation_id=conversation_id,
            model=init_model,
            display_name=INIT_GOD_DISPLAY_NAME,
        )
        init_session = self._ensure_init_god_session(
            conversation_id=conversation_id,
            participant=init_participant,
            registry_path=registry_path or self._base_dir / "god_sessions.json",
        )
        draft = self._bootstrap_draft(
            conversation_id=conversation_id,
            preset_id=preset_id,
            init_participant=init_participant,
            init_session=init_session,
            participant_specs=participant_specs,
            provider_overrides=provider_overrides,
        )
        self._bootstrap_state().upsert_draft(draft)
        if mode is BootstrapInitMode.PROPOSAL_THEN_APPROVE:
            proposal_result = self.create_bootstrap_proposal(
                conversation_id=conversation_id,
                source="deterministic",
            )
            proposal = proposal_result["proposal"]
            draft = self._bootstrap_state().get_draft(draft.draft_id)
            artifact = self._write_draft_bootstrap_artifact(
                conversation_id=conversation_id,
                title=conversation.title,
                draft=draft,
                init_participant=init_participant,
                init_session=init_session,
            )
            guidance_message = self._write_bootstrap_guidance_message_once(
                conversation_id=conversation_id,
                init_participant=init_participant,
                proposal_id=str(proposal["proposal_id"]),
                participant_plan=[peer.role for peer in draft.default_team],
            )
            return {
                "status": draft.status.value,
                "proposal_id": proposal["proposal_id"],
                "proposal_source": proposal["source"],
                "participant_plan": [peer.role for peer in draft.default_team],
                "fork_plan": [],
                "participants": [],
                "participant_sessions": [],
                "init_participant": init_participant.model_dump(mode="json"),
                "init_session": self._session_summary(init_session),
                "artifact": artifact,
                "draft": draft.model_dump(mode="json"),
                "guidance_message": guidance_message.model_dump(mode="json"),
            }

        proposal_result = self.create_bootstrap_proposal(
            conversation_id=conversation_id,
            source="deterministic",
        )
        applied = self.apply_bootstrap_proposal(
            conversation_id=conversation_id,
            proposal_id=proposal_result["proposal"]["proposal_id"],
            registry_path=registry_path,
        )
        return applied["bootstrap"]

    def create_bootstrap_proposal(
        self,
        *,
        conversation_id: str,
        source: str = "deterministic",
    ) -> dict[str, Any]:
        if source != "deterministic":
            raise PeerChatError("bootstrap_init_god_proposal_not_implemented", source)
        draft = self._bootstrap_state().get_latest_draft_for_conversation(conversation_id)
        if draft is None:
            raise PeerChatError("bootstrap_draft_not_found", conversation_id)
        proposal = self._deterministic_team_proposal(draft, source=source)
        state = self._bootstrap_state()
        state.upsert_proposal(proposal)
        if draft.status is not BootstrapStatus.BOOTSTRAPPED:
            state.update_draft_status(
                draft.draft_id,
                status=BootstrapStatus.PROPOSAL_READY,
                updated_at=self._utc_now(),
            )
        return {
            "conversation_id": conversation_id,
            "proposal": proposal.model_dump(mode="json"),
            "status": BootstrapStatus.PROPOSAL_READY.value,
        }

    def apply_bootstrap_proposal(
        self,
        *,
        conversation_id: str,
        proposal_id: str,
        registry_path: Path | None = None,
    ) -> dict[str, Any]:
        try:
            proposal = self._bootstrap_state().get_proposal(proposal_id)
        except KeyError as exc:
            raise PeerChatError("bootstrap_proposal_not_found", proposal_id) from exc
        if proposal.conversation_id != conversation_id:
            raise PeerChatError("bootstrap_proposal_conversation_mismatch", proposal_id)
        draft = self._bootstrap_state().get_draft(proposal.draft_id)
        init_participant = self._participants.get(draft.init_participant_id)
        registry = GodSessionRegistry(registry_path or self._base_dir / "god_sessions.json")
        participants: list[Participant] = []
        sessions = []
        forks = []
        role_templates = RoleTemplateStore(self._db_path)
        for peer in proposal.peers:
            template = role_templates.get_by_slug(peer.template_slug)
            if template is None:
                raise PeerChatError("unknown_role_template", peer.template_slug)
            participant = self._participants.ensure_bootstrap_participant(
                conversation_id=conversation_id,
                role=peer.role,
                display_name=peer.display_name,
                cli_kind=peer.cli_kind,
                model=peer.model,
                role_template_id=template.id,
            )
            participants.append(participant)
            session = self._ensure_peer_god_session(
                conversation_id=conversation_id,
                participant=participant,
                registry=registry,
            )
            sessions.append(session)
            forks.append(
                self._record_bootstrap_fork_once(
                    conversation_id=conversation_id,
                    proposal_id=proposal.proposal_id,
                    init_participant=init_participant,
                    participant=participant,
                    registry_path=registry.path,
                )
            )
        applied = self._applied_bootstrap(
            draft=draft,
            proposal=proposal,
            participants=participants,
            sessions=sessions,
            forks=forks,
        )
        state = self._bootstrap_state()
        applied = state.upsert_application(applied)
        draft = state.update_draft_status(
            draft.draft_id,
            status=BootstrapStatus.BOOTSTRAPPED,
            updated_at=self._utc_now(),
        )
        artifact = self._write_applied_bootstrap_artifact(
            conversation_id=conversation_id,
            draft=draft,
            proposal=proposal,
            applied=applied,
            participants=participants,
            init_participant=init_participant,
            init_session=registry.get(draft.init_session_id),
        )
        participant_sessions = [self._session_summary(session) for session in sessions]
        return {
            "conversation_id": conversation_id,
            "participants": [participant.model_dump(mode="json") for participant in participants],
            "participant_sessions": participant_sessions,
            "bootstrap": {
                **applied.model_dump(mode="json"),
                "status": applied.status,
                "participant_plan": [peer.role for peer in proposal.peers],
                "fork_plan": [fork.fork_id for fork in forks],
                "participants": [
                    participant.model_dump(mode="json") for participant in participants
                ],
                "participant_sessions": participant_sessions,
                "init_participant": init_participant.model_dump(mode="json"),
                "init_session": self._session_summary(registry.get(draft.init_session_id)),
                "artifact": artifact,
            },
        }

    def get_bootstrap_status(self, conversation_id: str) -> dict[str, Any]:
        conversation = self._conversation(conversation_id)
        if conversation is None:
            raise PeerChatError("unknown_conversation", conversation_id)
        state = self._bootstrap_state()
        draft = state.get_latest_draft_for_conversation(conversation_id)
        if draft is None:
            return {
                "conversation_id": conversation_id,
                "status": "unknown",
            }
        proposal = state.get_latest_proposal_for_conversation(conversation_id)
        application = state.get_latest_application_for_conversation(conversation_id)
        status = draft.status.value if hasattr(draft.status, "value") else str(draft.status)
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "status": status,
            "draft_id": draft.draft_id,
            "preset_id": draft.preset_id,
            "participant_plan": [peer.role for peer in draft.default_team],
            "updated_at": draft.updated_at,
        }
        if proposal is not None:
            payload["proposal_id"] = proposal.proposal_id
            payload["proposal_source"] = proposal.source
        if application is not None:
            payload["apply_id"] = application.apply_id
            payload["proposal_id"] = application.proposal_id
            payload["status"] = application.status
        return payload

    def _bootstrap_state(self) -> BootstrapStateStore:
        return BootstrapStateStore(self._db_path)

    def _bootstrap_draft(
        self,
        *,
        conversation_id: str,
        preset_id: str | None,
        init_participant: Participant,
        init_session: Any,
        participant_specs: list[dict[str, str]],
        provider_overrides: dict[str, Any] | None,
    ) -> BootstrapDraft:
        preset = resolve_groupchat_preset(preset_id)
        team = self._logical_team_from_specs_or_preset(
            participant_specs,
            preset_team=preset_to_logical_team(preset),
            provider_overrides=provider_overrides or {},
        )
        now = self._utc_now()
        return BootstrapDraft(
            draft_id=deterministic_draft_id(conversation_id),
            conversation_id=conversation_id,
            preset_id=preset.preset_id,
            init_participant_id=init_participant.participant_id,
            init_session_id=init_session.god_session_id,
            requested_overrides=provider_overrides or {},
            default_team=team,
            status=BootstrapStatus.DRAFTING,
            created_at=now,
            updated_at=now,
        )

    def _logical_team_from_specs_or_preset(
        self,
        participant_specs: list[dict[str, str]],
        *,
        preset_team: list[LogicalPeerSpec],
        provider_overrides: dict[str, Any],
    ) -> list[LogicalPeerSpec]:
        by_role = {peer.role: peer for peer in preset_team}
        team = []
        for spec in participant_specs:
            role = spec["role"]
            base = by_role.get(role)
            payload = {
                "role": role,
                "address_slug": base.address_slug if base is not None else role,
                "display_name": spec["display_name"],
                "template_slug": base.template_slug if base is not None else role,
                "provider_id": (
                    spec.get("provider_id")
                    or (base.provider_id if base is not None else spec["cli_kind"])
                ),
                "profile_id": (
                    spec.get("profile_id")
                    or (
                        base.profile_id
                        if base is not None
                        else provider_profile_id_for_role(role).value
                    )
                ),
                "cli_kind": spec["cli_kind"],
                "model": spec["model"],
            }
            override = provider_overrides.get(role)
            if override is not None:
                if not isinstance(override, dict):
                    raise PeerChatError("invalid_provider_override", role)
                payload.update(
                    {
                        key: value
                        for key, value in override.items()
                        if value is not None
                    }
                )
                payload["template_slug"] = override.get("template_slug") or payload["template_slug"]
                payload["display_name"] = override.get("display_name") or payload["display_name"]
            try:
                team.append(LogicalPeerSpec.model_validate(payload))
            except ValueError as exc:
                raise PeerChatError("invalid_provider_override", str(exc)) from exc
        return team

    def _deterministic_team_proposal(
        self,
        draft: BootstrapDraft,
        *,
        source: str,
    ) -> TeamPlanProposal:
        return TeamPlanProposal(
            proposal_id=deterministic_proposal_id(draft.conversation_id, draft.preset_id),
            draft_id=draft.draft_id,
            conversation_id=draft.conversation_id,
            source=source,
            peers=draft.default_team,
            fork_plan=[
                LogicalForkSpec(
                    target_address_slug=peer.address_slug,
                    prompt_delta=f"Bootstrap {peer.display_name} from init-god proposal.",
                    inherited_refs=["memory://conversation/bootstrap"],
                    fork_reason=f"bootstrap {peer.role}",
                )
                for peer in draft.default_team
            ],
            rationale=f"Apply preset {draft.preset_id} as durable groupchat peers.",
            validation_status="accepted",
        )

    def _write_bootstrap_guidance_message_once(
        self,
        *,
        conversation_id: str,
        init_participant: Participant,
        proposal_id: str,
        participant_plan: list[str],
    ):
        for message in self._chat.list_messages(conversation_id):
            if (
                message.envelope_type == "bootstrap_guidance"
                and message.envelope_json.get("proposal_id") == proposal_id
            ):
                return message
        roles = " / ".join(participant_plan)
        content = (
            f"初始化草案已准备好：推荐创建 {roles} 三个协作角色。"
            "请选择下方初始化操作继续。"
        )
        return self._chat.add_message(
            conversation_id,
            author=init_participant.participant_id,
            role="assistant",
            content=content,
            envelope_type="bootstrap_guidance",
            envelope_json={
                "type": "bootstrap_guidance",
                "proposal_id": proposal_id,
                "participant_plan": participant_plan,
                "actions": [
                    {
                        "id": "apply",
                        "label": "Apply recommended team",
                        "command": f"/init apply {proposal_id}",
                    },
                    {
                        "id": "retry",
                        "label": "Regenerate proposal",
                        "command": "/init retry",
                    },
                    {
                        "id": "status",
                        "label": "Show bootstrap status",
                        "command": "/init status",
                    },
                ],
                "next_actions": [
                    f"/init apply {proposal_id}",
                    "/init retry",
                    "/init status",
                ],
            },
        )

    def _ensure_peer_god_session(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        registry: GodSessionRegistry,
    ) -> Any:
        session_address, session_inbox_id = build_conversation_session_identity(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
        )
        try:
            record = registry.find_by_conversation_participant(
                conversation_id,
                participant.participant_id,
            )
        except KeyError:
            return registry.create(
                role=participant.role,
                agent_name=participant.display_name,
                runtime=participant.cli_kind,
                session_address=session_address,
                session_inbox_id=session_inbox_id,
                conversation_id=conversation_id,
                participant_id=participant.participant_id,
                model=participant.model,
            )
        if (
            record.session_address != session_address
            or record.session_inbox_id != session_inbox_id
            or record.runtime != participant.cli_kind
        ):
            raise PeerChatError("bootstrap_session_conflict", participant.participant_id)
        return record

    def _record_bootstrap_fork_once(
        self,
        *,
        conversation_id: str,
        proposal_id: str,
        init_participant: Participant,
        participant: Participant,
        registry_path: Path,
    ) -> Any:
        target_address_slug = participant.display_name.removesuffix("-god") or participant.role
        fork_id = bootstrap_fork_idempotency_key(
            conversation_id,
            proposal_id,
            init_participant.participant_id,
            target_address_slug,
        )
        return PeerForkStore(self._db_path, registry_path=registry_path).record_bootstrap_once(
            fork_id=fork_id,
            conversation_id=conversation_id,
            source_peer_id=init_participant.participant_id,
            new_peer_id=participant.participant_id,
            prompt_delta=f"Bootstrap {participant.display_name} as {participant.role}.",
            inherited_refs=["memory://conversation/bootstrap"],
            model_policy={"runtime": participant.cli_kind},
            feature_scope_id=None,
            fork_reason=f"bootstrap {participant.role}",
        )

    def _applied_bootstrap(
        self,
        *,
        draft: BootstrapDraft,
        proposal: TeamPlanProposal,
        participants: list[Participant],
        sessions: list[Any],
        forks: list[Any],
    ) -> AppliedBootstrap:
        return AppliedBootstrap(
            apply_id=bootstrap_apply_id(draft.conversation_id, proposal.proposal_id),
            draft_id=draft.draft_id,
            proposal_id=proposal.proposal_id,
            conversation_id=draft.conversation_id,
            participants=[participant.participant_id for participant in participants],
            durable_god_sessions=[session.god_session_id for session in sessions],
            fork_records=[fork.fork_id for fork in forks],
            status="bootstrapped",
            created_at=self._utc_now(),
        )

    def _write_draft_bootstrap_artifact(
        self,
        *,
        conversation_id: str,
        title: str,
        draft: BootstrapDraft,
        init_participant: Participant,
        init_session: Any,
    ) -> dict[str, str]:
        return self._write_bootstrap_json_artifact(
            conversation_id=conversation_id,
            payload={
                "artifact_id": f"bootstrap:{conversation_id}",
                "conversation_id": conversation_id,
                "title": title,
                "created_at": self._utc_now(),
                "status": draft.status.value,
                "bootstrap_context": {
                    "conversation_id": conversation_id,
                    "title": title,
                    "participant_count": len(draft.default_team),
                },
                "participant_plan": [peer.role for peer in draft.default_team],
                "fork_plan": [],
                "init_participant_id": init_participant.participant_id,
                "init_session_id": init_session.god_session_id,
                "instantiated_participants": [],
                "draft": draft.model_dump(mode="json"),
            },
        )

    def _write_applied_bootstrap_artifact(
        self,
        *,
        conversation_id: str,
        draft: BootstrapDraft,
        proposal: TeamPlanProposal,
        applied: AppliedBootstrap,
        participants: list[Participant],
        init_participant: Participant,
        init_session: Any,
    ) -> dict[str, str]:
        return self._write_bootstrap_json_artifact(
            conversation_id=conversation_id,
            payload={
                "artifact_id": f"bootstrap:{conversation_id}",
                "conversation_id": conversation_id,
                "created_at": self._utc_now(),
                "status": applied.status,
                "bootstrap_context": {
                    "conversation_id": conversation_id,
                    "participant_count": len(participants),
                },
                "participant_plan": [peer.role for peer in proposal.peers],
                "fork_plan": applied.fork_records,
                "init_participant_id": init_participant.participant_id,
                "init_session_id": init_session.god_session_id,
                "instantiated_participants": [
                    participant_summary(participant) for participant in participants
                ],
                "draft": draft.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
                "application": applied.model_dump(mode="json"),
            },
        )

    def _write_bootstrap_json_artifact(
        self,
        *,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        relative_path = Path("artifacts") / "chat_bootstrap" / f"{conversation_id}.json"
        artifact_path = self._base_dir / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=artifact_path.parent,
            prefix=f"{artifact_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(artifact_path)
        return {
            "artifact_id": str(payload["artifact_id"]),
            "path": str(relative_path),
        }

    def list_conversations(
        self,
        *,
        api_href_template: str = "/api/chat/conversations/{conversation_id}/messages",
    ) -> dict[str, Any]:
        conversations = []
        sessions_by_conversation = self._sessions_by_conversation()
        for conversation in self._chat.list_conversations():
            participants = self._participants.list_by_conversation(conversation.id)
            messages = self._natural_messages(conversation.id)
            cards = self._cards_for_conversation(conversation.id)
            sessions = sessions_by_conversation.get(conversation.id, [])
            conversations.append(
                self._conversation_summary(
                    conversation=conversation,
                    messages=messages,
                    cards=cards,
                    participants=participants,
                    sessions=sessions,
                    api_href_template=api_href_template,
                )
            )
        return {"conversations": conversations}

    def list_participants(
        self,
        *,
        conversation_id: str,
        registry_path: Path | None = None,
    ) -> dict[str, Any]:
        if not self._conversation_exists(conversation_id):
            raise PeerChatError("unknown_conversation", conversation_id)
        participants = self._participants.list_by_conversation(conversation_id)
        sessions_by_participant = self._sessions_by_participant(
            conversation_id,
            registry_path=registry_path,
        )
        return {
            "conversation_id": conversation_id,
            "participants": [
                {
                    **participant.model_dump(mode="json"),
                    "session": sessions_by_participant.get(participant.participant_id),
                }
                for participant in participants
            ],
            "lineage": (
                self.list_fork_lineage(
                    conversation_id=conversation_id,
                    registry_path=registry_path,
                )["lineage"]
                if registry_path is not None
                else []
            ),
        }

    def list_fork_lineage(
        self,
        *,
        conversation_id: str,
        registry_path: Path | None,
    ) -> dict[str, Any]:
        if not self._conversation_exists(conversation_id):
            raise PeerChatError("unknown_conversation", conversation_id)
        if registry_path is None:
            return {"conversation_id": conversation_id, "lineage": []}
        lineage = PeerForkStore(self._db_path, registry_path=registry_path)
        return {
            "conversation_id": conversation_id,
            "lineage": [
                summary.model_dump(mode="json")
                for summary in lineage.list_summaries_by_conversation(conversation_id)
            ],
        }

    def fork_participant(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        source_peer_id: str,
        role: str,
        display_name: str | None = None,
        model: str | None = None,
        role_template_id: str | None = None,
        prompt_delta: str,
        inherited_refs: list[str] | None = None,
        model_policy: dict[str, Any],
        fork_reason: str,
        feature_scope_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._conversation_exists(conversation_id):
            raise PeerChatError("unknown_conversation", conversation_id)
        source = self._participant_for_conversation(
            conversation_id=conversation_id,
            participant_id=source_peer_id,
            error_code="unknown_source_peer",
        )
        registry = GodSessionRegistry(registry_path)
        try:
            registry.find_by_conversation_participant(conversation_id, source.participant_id)
        except KeyError as exc:
            raise PeerChatError("source_peer_missing_session", source.participant_id) from exc
        lineage_store = PeerForkStore(self._db_path, registry_path=registry_path)
        validated_contract = lineage_store.validate_contract(
            conversation_id=conversation_id,
            source_peer_id=source.participant_id,
            new_peer_id="pending_fork_peer",
            prompt_delta=prompt_delta,
            inherited_refs=inherited_refs,
            model_policy=model_policy,
            feature_scope_id=feature_scope_id,
            fork_reason=fork_reason,
        )

        role_templates = RoleTemplateStore(self._db_path)
        spec = self._normalize_participant_spec(
            role_templates,
            {
                "role": role,
                "cli_kind": "codex",
                "display_name": display_name,
                "model": model,
                "role_template_id": role_template_id,
            },
        )
        participant = self._participants.add(
            conversation_id=conversation_id,
            role=spec["role"],
            display_name=spec["display_name"],
            cli_kind=spec["cli_kind"],
            model=spec["model"],
            role_template_id=spec["role_template_id"],
        )
        session_address, session_inbox_id = build_conversation_session_identity(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
        )
        runtime = str(validated_contract.model_policy["model_policy_runtime"])
        session = registry.create(
            role=participant.role,
            agent_name=participant.display_name,
            runtime=runtime,
            session_address=session_address,
            session_inbox_id=session_inbox_id,
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            model=participant.model,
            feature_scope_id=validated_contract.feature_scope_id,
        )
        lineage = lineage_store.record(
            conversation_id=conversation_id,
            source_peer_id=source.participant_id,
            new_peer_id=participant.participant_id,
            prompt_delta=validated_contract.prompt_delta,
            inherited_refs=validated_contract.inherited_refs,
            model_policy=validated_contract.model_policy,
            feature_scope_id=validated_contract.feature_scope_id,
            fork_reason=validated_contract.fork_reason,
        )
        lineage_summary = self.list_fork_lineage(
            conversation_id=conversation_id,
            registry_path=registry_path,
        )["lineage"][-1]
        return {
            "participant": participant.model_dump(mode="json"),
            "session": self._session_summary(session),
            "fork": lineage.model_dump(mode="json"),
            "lineage": lineage_summary,
        }

    def list_conversation_timeline(self, conversation_id: str) -> dict[str, Any]:
        conversation = self._conversation(conversation_id)
        messages = self._natural_messages(conversation_id)
        cards = self._cards_for_conversation(conversation_id)
        peer_progress_events = self._peer_progress_events(conversation_id)
        roster_events = self._roster_events(conversation_id)
        items = [
            ChatTimelineItem(
                kind="message",
                created_at=message.created_at,
                message=message,
            )
            for message in messages
        ]
        items.extend(
            ChatTimelineItem(
                kind="card",
                created_at=card.created_at,
                card=card,
            )
            for card in cards
        )
        items.sort(
            key=lambda item: (
                item.created_at,
                0 if item.kind == "message" else 1,
                item.message.id if item.message is not None else item.card.id if item.card else "",
            )
        )
        payload = {
            "messages": [message.model_dump(mode="json") for message in messages],
            "cards": [card.model_dump(mode="json") for card in cards],
            "items": [item.model_dump(mode="json") for item in items],
            "peer_progress_events": peer_progress_events,
            "peer_progress_counts": peer_progress_counts(peer_progress_events),
            "recent_peer_progress_events": peer_progress_events[-5:],
            "roster_events": roster_events,
            "roster_event_counts": roster_event_counts(roster_events),
            "recent_roster_events": roster_events[-5:],
        }
        if conversation is None:
            return payload

        sessions = self._sessions_by_conversation().get(conversation_id, [])
        participants = self._participants.list_by_conversation(conversation_id)
        payload.update(
            self._conversation_summary(
                conversation=conversation,
                messages=messages,
                cards=cards,
                participants=participants,
                sessions=sessions,
                peer_progress_events=peer_progress_events,
                roster_events=roster_events,
            )
        )
        payload["conversation_id"] = conversation.id
        return payload

    def _conversation(
        self,
        conversation_id: str,
    ) -> Any | None:
        for conversation in self._chat.list_conversations():
            if conversation.id == conversation_id:
                return conversation
        return None

    def _conversation_summary(
        self,
        *,
        conversation: Any,
        messages: list[ChatMessage],
        cards: list[ChatCard],
        participants: list[Participant],
        sessions: list[dict[str, Any]],
        api_href_template: str = "/api/chat/conversations/{conversation_id}/messages",
        peer_progress_events: list[dict[str, Any]] | None = None,
        roster_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        peer_progress = (
            peer_progress_events
            if peer_progress_events is not None
            else self._peer_progress_events(conversation.id)
        )
        roster = (
            roster_events
            if roster_events is not None
            else self._roster_events(conversation.id)
        )
        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "last_activity_at": self._last_activity_at(
                conversation.created_at,
                messages=messages,
                cards=cards,
                roster_events=roster,
            ),
            "href": f"/dashboard/peer-chat/conversations/{conversation.id}",
            "dashboard_href": f"/dashboard/peer-chat/conversations/{conversation.id}",
            "api_href": api_href_template.format(conversation_id=conversation.id),
            "participants": self._participant_group_summary(participants),
            "inbox_counts": self._inbox_counts(conversation.id),
            "card_counts": self._card_counts(cards),
            "peer_progress_counts": peer_progress_counts(peer_progress),
            "recent_peer_progress_events": peer_progress[-5:],
            "roster_event_counts": roster_event_counts(roster),
            "recent_roster_events": roster[-5:],
            "recent_messages": [
                self._message_summary(message) for message in messages[-5:]
            ],
            "recent_cards": [
                card.model_dump(mode="json") for card in cards[-5:]
            ],
            "linked_session_ids": self._linked_session_ids(sessions),
            "sessions": sessions,
        }

    def _default_participant_specs(
        self,
        role_templates: RoleTemplateStore,
    ) -> list[dict[str, str]]:
        specs = []
        for role in ("architect", "review", "execute"):
            template = role_templates.get_by_slug(role)
            if template is None:
                raise PeerChatError("missing_predefined_role_template", role)
            specs.append(
                {
                    "role": role,
                    "display_name": f"{role}-god",
                    "cli_kind": template.cli_kind,
                    "model": template.default_model,
                    "role_template_id": template.id,
                }
            )
        return specs

    def _normalize_participant_specs(
        self,
        role_templates: RoleTemplateStore,
        participants: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        if not isinstance(participants, list):
            raise PeerChatError("invalid_arguments", "participants must be a list")
        return [
            self._normalize_participant_spec(role_templates, participant)
            for participant in participants
        ]

    def _normalize_participant_spec(
        self,
        role_templates: RoleTemplateStore,
        participant: dict[str, Any],
    ) -> dict[str, str]:
        if not isinstance(participant, dict):
            raise PeerChatError("invalid_arguments", "participant must be an object")
        role = self._required_string(participant.get("role"), "role")
        explicit_cli_kind = self._optional_string(participant.get("cli_kind"))
        if explicit_cli_kind is not None and explicit_cli_kind not in {"codex", "opencode"}:
            raise PeerChatError("codex_only_participants", explicit_cli_kind)
        provider_id = self._optional_string(participant.get("provider_id"))
        profile_id = self._optional_string(participant.get("profile_id"))
        model = self._optional_string(participant.get("model"))
        role_template_id = self._optional_string(participant.get("role_template_id"))
        if role_template_id is not None:
            try:
                template = role_templates.get(role_template_id)
            except KeyError as exc:
                raise PeerChatError("unknown_role_template", role_template_id) from exc
        else:
            template = role_templates.get_by_slug(role)
            if template is None or not template.predefined:
                raise PeerChatError("role_template_id_required", role)

        expected_profile_id = provider_profile_id_for_role(role)
        if (
            profile_id is not None
            and profile_id != expected_profile_id.value
        ):
            raise PeerChatError(
                "participant_profile_role_mismatch",
                f"role {role!r} must use profile_id "
                f"{expected_profile_id.value!r}, got {profile_id!r}",
                details={
                    "role": role,
                    "expected_profile_id": expected_profile_id.value,
                    "provided_profile_id": profile_id,
                    "role_profile_map": {role: expected_profile_id.value},
                },
            )

        resolved_profile_id = profile_id or expected_profile_id.value

        try:
            cli_kind = resolve_codex_cli_kind(
                cli_kind=explicit_cli_kind,
                provider_id=provider_id,
                profile_id=resolved_profile_id,
                expected_profile_id=expected_profile_id,
                subject="xmuse chat participants",
            )
        except ValueError as exc:
            raise PeerChatError("invalid_arguments", str(exc)) from exc

        if cli_kind == "opencode":
            missing = [
                field_name
                for field_name, value in (
                    ("provider_id", provider_id),
                    ("cli_kind", explicit_cli_kind),
                    ("model", model),
                )
                if value is None
            ]
            if missing:
                raise PeerChatError(
                    "invalid_arguments",
                    "opencode initial_participants require explicit "
                    "provider_id, cli_kind, and model",
                )

        display_name = self._optional_string(participant.get("display_name")) or f"{role}-god"
        normalized_model = (
            normalize_codex_model_id(
                model or template.default_model,
                profile_id=expected_profile_id,
            )
            if cli_kind == "codex"
            else model
        )
        return {
            "role": role,
            "display_name": display_name,
            "provider_id": provider_id or cli_kind,
            "profile_id": resolved_profile_id,
            "cli_kind": cli_kind,
            "model": normalized_model,
            "role_template_id": template.id,
        }

    def _bootstrap_init_model(
        self,
        participant_specs: list[dict[str, str]],
        role_templates: RoleTemplateStore,
    ) -> str:
        for spec in participant_specs:
            if spec["role"] == "architect":
                return spec["model"]
        architect = role_templates.get_by_slug("architect")
        if architect is None:
            raise PeerChatError("missing_predefined_role_template", "architect")
        return architect.default_model

    def _ensure_init_god_session(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        registry_path: Path,
    ) -> Any:
        session_address, session_inbox_id = build_conversation_session_identity(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
        )
        registry = GodSessionRegistry(registry_path)
        try:
            record = registry.find_by_conversation_participant(
                conversation_id,
                participant.participant_id,
            )
        except KeyError:
            try:
                record = registry.find_by_conversation_role(conversation_id, INIT_GOD_ROLE)
            except KeyError:
                record = registry.create(
                    role=INIT_GOD_ROLE,
                    agent_name=participant.display_name,
                    runtime=participant.cli_kind,
                    session_address=session_address,
                    session_inbox_id=session_inbox_id,
                    conversation_id=conversation_id,
                    participant_id=participant.participant_id,
                    model=participant.model,
                )
            else:
                if record.participant_id != participant.participant_id:
                    raise PeerChatError(
                        "bootstrap_session_conflict",
                        f"init session points at {record.participant_id}, "
                        f"expected {participant.participant_id}",
                    )
        if (
            record.role != INIT_GOD_ROLE
            or record.session_address != session_address
            or record.session_inbox_id != session_inbox_id
            or record.runtime != participant.cli_kind
        ):
            raise PeerChatError(
                "bootstrap_session_conflict",
                f"invalid init session identity for conversation {conversation_id}",
            )
        if record.model != participant.model:
            record = registry.update_peer_metadata(
                record.god_session_id,
                model=participant.model,
                prompt_fingerprint=record.prompt_fingerprint,
                worktree=record.worktree,
                feature_scope_id=record.feature_scope_id,
            )
        return record

    def _write_bootstrap_artifact(
        self,
        *,
        conversation_id: str,
        title: str,
        participant_specs: list[dict[str, str]],
        participants: list[Participant],
        init_participant: Participant,
        init_session: Any,
    ) -> dict[str, str]:
        relative_path = Path("artifacts") / "chat_bootstrap" / f"{conversation_id}.json"
        artifact_path = self._base_dir / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact_id": f"bootstrap:{conversation_id}",
            "conversation_id": conversation_id,
            "title": title,
            "created_at": self._utc_now(),
            "bootstrap_context": {
                "conversation_id": conversation_id,
                "title": title,
                "participant_count": len(participant_specs),
            },
            "participant_plan": [spec["role"] for spec in participant_specs],
            "fork_plan": [],
            "init_participant_id": init_participant.participant_id,
            "init_session_id": init_session.god_session_id,
            "instantiated_participants": [
                participant_summary(participant) for participant in participants
            ],
        }
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=artifact_path.parent,
            prefix=f"{artifact_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(artifact_path)
        return {
            "artifact_id": payload["artifact_id"],
            "path": str(relative_path),
        }

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _required_string(self, value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PeerChatError("invalid_arguments", f"{field_name} is required")
        return value.strip()

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise PeerChatError("invalid_arguments", "optional string fields must be non-empty")
        return value.strip()

    def _required_string_list(self, value: Any, field_name: str) -> list[str]:
        if not isinstance(value, list):
            raise PeerChatError("invalid_arguments", f"{field_name} must be a list")
        cleaned = [self._required_string(item, field_name) for item in value]
        if not cleaned:
            raise PeerChatError("invalid_arguments", f"{field_name} must not be empty")
        return cleaned

    def _optional_string_list(self, value: Any, field_name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise PeerChatError("invalid_arguments", f"{field_name} must be a list")
        return [self._required_string(item, field_name) for item in value]

    def _collaboration_run_for_conversation(
        self,
        store: Any,
        run_id: str,
        conversation_id: str,
    ):
        try:
            run = store.get_run(run_id)
        except KeyError as exc:
            raise PeerChatError("unknown_collaboration_run", run_id) from exc
        if run.conversation_id != conversation_id:
            raise PeerChatError("unknown_collaboration_run", run_id)
        return run

    def _require_ready_collaboration_references(
        self,
        *,
        conversation_id: str,
        references: list[str],
    ) -> None:
        store = self._collaboration_store()
        for run_id in _collaboration_reference_run_ids(references):
            run = self._collaboration_run_for_conversation(store, run_id, conversation_id)
            if run.status is not CollaborationStatus.DONE:
                raise PeerChatError(
                    "collaboration_run_not_ready",
                    f"{run.run_id}:{run.status.value}",
                )

    def _conversation_exists(self, conversation_id: str) -> bool:
        return any(
            conversation.id == conversation_id
            for conversation in self._chat.list_conversations()
        )

    def _participant_group_summary(self, participants: list[Participant]) -> dict[str, Any]:
        roles: list[str] = []
        for participant in participants:
            if participant.role not in roles:
                roles.append(participant.role)
        return {
            "total": len(participants),
            "active": sum(1 for participant in participants if participant.status == "active"),
            "stopped": sum(1 for participant in participants if participant.status == "stopped"),
            "roles": roles,
            "items": [
                {
                    **participant_summary(participant),
                    "conversation_id": participant.conversation_id,
                }
                for participant in participants
            ],
        }

    def _inbox_counts(self, conversation_id: str) -> dict[str, int]:
        counts = {"unread": 0, "claimed": 0}
        for item in self._inbox.list_by_conversation(conversation_id):
            if item.status in counts:
                counts[item.status] += 1
        return counts

    def _peer_progress_events(self, conversation_id: str) -> list[dict[str, Any]]:
        return build_peer_progress_events(
            db_path=self._db_path,
            conversation_id=conversation_id,
            inbox_items=self._inbox.list_by_conversation(
                conversation_id,
                include_terminal=True,
            ),
        )

    def _roster_events(self, conversation_id: str) -> list[dict[str, Any]]:
        return build_roster_events(self._chat.list_messages(conversation_id))

    def _natural_messages(self, conversation_id: str) -> list[ChatMessage]:
        return [
            message
            for message in self._chat.list_messages(conversation_id)
            if message.envelope_type in {None, "message", "mention"}
        ]

    def _message_summary(self, message: ChatMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "author": message.author,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
            "envelope_type": message.envelope_type,
            "mentions": list(message.mentions),
            "reply_to_message_id": message.reply_to_message_id,
        }

    def _last_activity_at(
        self,
        created_at: str,
        *,
        messages: list[ChatMessage],
        cards: list[ChatCard],
        roster_events: list[dict[str, Any]] | None = None,
    ) -> str:
        timestamps = [created_at]
        timestamps.extend(message.created_at for message in messages)
        timestamps.extend(card.created_at for card in cards)
        timestamps.extend(
            str(event["created_at"])
            for event in (roster_events or [])
            if isinstance(event.get("created_at"), str)
        )
        return max(timestamps)

    def _linked_session_ids(self, sessions: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for session in sessions:
            god_session_id = session.get("god_session_id") or session.get("session_id")
            if isinstance(god_session_id, str) and god_session_id and god_session_id not in ids:
                ids.append(god_session_id)
        return ids

    def _sessions_by_participant(
        self,
        conversation_id: str,
        *,
        registry_path: Path | None,
    ) -> dict[str, dict[str, Any]]:
        if registry_path is None:
            return {}
        sessions: dict[str, dict[str, Any]] = {}
        for record in GodSessionRegistry(registry_path).list():
            if (
                record.conversation_id == conversation_id
                and isinstance(record.participant_id, str)
                and record.participant_id
            ):
                sessions[record.participant_id] = self._session_summary(record)
        return sessions

    def _session_summary(self, record: Any) -> dict[str, Any]:
        provider_id = "codex" if record.runtime == "codex" else str(record.runtime)
        profile_id = (
            provider_profile_id_for_role(record.role).value
            if provider_id == "codex"
            else "default"
        )
        if isinstance(record.participant_id, str) and record.participant_id:
            try:
                participant = self._participants.get(record.participant_id)
            except KeyError:
                participant = None
            if participant is not None and participant.conversation_id == record.conversation_id:
                provider_id = participant.provider_id.value
                profile_id = participant.profile_id.value
        return {
            "god_session_id": record.god_session_id,
            "conversation_id": record.conversation_id,
            "participant_id": record.participant_id,
            "role": record.role,
            "provider_id": provider_id,
            "profile_id": profile_id,
            "runtime": record.runtime,
            "model": record.model,
            "status": record.status,
            "feature_scope_id": record.feature_scope_id,
        }

    def _participant_for_conversation(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        error_code: str,
    ) -> Participant:
        try:
            participant = self._participants.get(participant_id)
        except KeyError as exc:
            raise PeerChatError(error_code, participant_id) from exc
        if participant.conversation_id != conversation_id:
            raise PeerChatError(error_code, participant_id)
        return participant

    def _sessions_by_conversation(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for raw in self._read_sessions():
            if not isinstance(raw, dict):
                continue
            conversation_id = raw.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                continue
            session = self._normalize_session(raw)
            god_session_id = session.get("god_session_id") or session.get("session_id")
            if isinstance(god_session_id, str) and god_session_id:
                session.setdefault("href", f"/dashboard/peer-chat/sessions/{god_session_id}")
                session.setdefault(
                    "api_href",
                    f"/api/dashboard/peer-chat/sessions/{god_session_id}",
                )
            grouped.setdefault(conversation_id, []).append(session)
        return grouped

    def _normalize_session(self, raw: dict[str, Any]) -> dict[str, Any]:
        session = dict(raw)
        role = self._string_value(session.get("role")) or ""
        runtime = self._string_value(session.get("runtime")) or "codex"
        provider_id = self._string_value(session.get("provider_id"))
        if provider_id is None:
            provider_id = "codex" if runtime == "codex" else runtime
        session.setdefault("provider_id", provider_id)
        if provider_id == "codex":
            session.setdefault("profile_id", provider_profile_id_for_role(role).value)
        else:
            session.setdefault("profile_id", "default")
        return session

    def _read_sessions(self) -> list[Any]:
        data = self._read_json_file(self._base_dir / "active_sessions.json", {"sessions": []})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            sessions = data.get("sessions", [])
            if isinstance(sessions, list):
                return sessions
            if isinstance(sessions, dict):
                normalized: list[Any] = []
                for feature_id, session in sessions.items():
                    if isinstance(session, dict):
                        normalized.append({"feature_id": feature_id, **session})
                return normalized
        return []

    def _card_assembler(self) -> PeerChatCardAssembler:
        return PeerChatCardAssembler(
            base_dir=self._base_dir,
            chat=self._chat,
            inbox=self._inbox,
            participants=self._participants,
        )

    def _card_counts(self, cards: list[ChatCard]) -> dict[str, int]:
        return self._card_assembler()._card_counts(cards)

    def _cards_for_conversation(self, conversation_id: str) -> list[ChatCard]:
        return self._card_assembler()._cards_for_conversation(conversation_id)

    def _conversation_scoped_lanes(
        self,
        conversation_id: str,
        lanes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return conversation_scoped_lanes(self._base_dir, conversation_id, lanes)

    def _read_json_file(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _string_value(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def post_human_message(
        self,
        *,
        conversation_id: str,
        author: str,
        content: str,
        client_request_id: str,
    ) -> PeerMessageResult:
        caller_identity = f"human:{author}"
        logged = self._chat.get_logged_request_result(
            conversation_id=conversation_id,
            tool_name="post_human_message",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
        )
        if logged is not None:
            return PeerMessageResult.from_json(logged)

        has_inactive_mentions = has_inactive_mention_candidates(content)
        routed_raw_mentions = self._human_routing_mentions(conversation_id, content)
        has_all_mention = any(
            normalize_address(raw) == "@all" for raw in routed_raw_mentions
        )
        if has_all_mention:
            mention_values = ["@all"]
            inbox_items = self._build_human_all_inbox_items(
                conversation_id=conversation_id,
                content=content,
            )
        else:
            mentions = self._resolve_human_mentions(
                conversation_id,
                content,
                raw_mentions=routed_raw_mentions,
            )
            mention_values = [mention.normalized for mention in mentions]
            inbox_items = self._build_human_inbox_items(
                conversation_id=conversation_id,
                content=content,
                mentions=mentions,
                allow_default_intake=not has_inactive_mentions,
            )
        payload = self._chat.create_message_inbox_and_log(
            conversation_id=conversation_id,
            tool_name="post_human_message",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
            author=author,
            role="human",
            content=content,
            envelope_type="message",
            envelope_json=normalize_envelope({"type": "message"}, envelope_type="message"),
            mentions=mention_values,
            inbox_items=inbox_items,
            turn_budget_action="reset",
            turn_budget_reset_amount=8,
        )
        return PeerMessageResult.from_json(payload)

    def _resolve_mentions(self, conversation_id: str, content: str):
        resolver = MentionResolver(self._participants)
        try:
            resolved = resolver.resolve_content(conversation_id, content)
        except MentionResolutionError as exc:
            raise PeerChatError(exc.code, exc.target) from exc
        return resolved

    def _human_routing_mentions(self, conversation_id: str, content: str) -> list[str]:
        if _has_leading_all_mention(content):
            return ["@all"]
        resolver = MentionResolver(self._participants)
        try:
            leading_mentions = resolver.resolve_leading_content(conversation_id, content)
            mentions = leading_mentions or resolver.resolve_content(conversation_id, content)
        except MentionResolutionError as exc:
            raise PeerChatError(exc.code, exc.target) from exc
        return [mention.raw for mention in mentions]

    def _resolve_human_mentions(
        self,
        conversation_id: str,
        content: str,
        *,
        raw_mentions: list[str] | None = None,
    ):
        raw_mentions = (
            self._human_routing_mentions(conversation_id, content)
            if raw_mentions is None
            else raw_mentions
        )
        return self._resolve_raw_mentions(conversation_id, raw_mentions)

    def _resolve_raw_mentions(self, conversation_id: str, raw_mentions: list[str]):
        resolver = MentionResolver(self._participants)
        resolved = []
        seen: set[str] = set()
        for raw in raw_mentions:
            try:
                mention = resolver.resolve(conversation_id, raw)
            except MentionResolutionError as exc:
                raise PeerChatError(exc.code, exc.target) from exc
            if mention.normalized in seen:
                continue
            seen.add(mention.normalized)
            resolved.append(mention)
        return resolved

    def _build_human_inbox_items(
        self,
        *,
        conversation_id: str,
        content: str,
        mentions: list[Any],
        allow_default_intake: bool = True,
    ) -> list[dict[str, Any]]:
        if mentions:
            return [
                {
                    "target_participant_id": mention.participant.participant_id,
                    "target_role": mention.participant.role,
                    "target_address": mention.normalized,
                    "sender_participant_id": None,
                    "sender_address": "@human",
                    "item_type": "mention",
                    "payload": {"content": content, "mention": mention.raw},
                }
                for mention in mentions
            ]

        if not allow_default_intake:
            return []

        default_target = self._resolve_default_intake(conversation_id)
        return [
            {
                "target_participant_id": default_target.participant.participant_id,
                "target_role": default_target.participant.role,
                "target_address": default_target.normalized,
                "sender_participant_id": None,
                "sender_address": "@human",
                "item_type": "default_intake",
                "payload": {
                    "content": content,
                    "intake_role": DEFAULT_INTAKE_ROLE,
                    "intake_address": default_intake_address(),
                },
            }
        ]

    def _build_human_all_inbox_items(
        self,
        *,
        conversation_id: str,
        content: str,
    ) -> list[dict[str, Any]]:
        inbox_items: list[dict[str, Any]] = []
        routed_participant_ids: set[str] = set()
        for participant in self._participants.list_by_conversation(conversation_id):
            if participant.status != "active":
                continue
            if participant.role == INIT_GOD_ROLE:
                continue
            if participant.participant_id in routed_participant_ids:
                continue
            routed_participant_ids.add(participant.participant_id)
            inbox_items.append(
                {
                    "target_participant_id": participant.participant_id,
                    "target_role": participant.role,
                    "target_address": f"@{participant.role}",
                    "sender_participant_id": None,
                    "sender_address": "@human",
                    "item_type": "mention",
                    "payload": {"content": content, "mention": "@all"},
                }
            )
        return inbox_items

    def _resolve_default_intake(self, conversation_id: str):
        resolver = MentionResolver(self._participants)
        try:
            return resolver.resolve(conversation_id, default_intake_address())
        except MentionResolutionError as exc:
            if exc.code == "unknown_target":
                raise PeerChatError(
                    "default_intake_target_missing",
                    DEFAULT_INTAKE_ROLE,
                ) from exc
            if exc.code == "ambiguous_target":
                raise PeerChatError(
                    "default_intake_target_ambiguous",
                    DEFAULT_INTAKE_ROLE,
                ) from exc
            raise PeerChatError(exc.code, exc.target) from exc

    def _verify_god_identity(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
    ) -> None:
        try:
            record = GodSessionRegistry(registry_path).get(god_session_id)
        except KeyError as exc:
            raise PeerChatError("unknown_god_session", god_session_id) from exc
        if record.conversation_id != conversation_id or record.participant_id != participant_id:
            raise PeerChatError("session_participant_mismatch", god_session_id)

    def inspect_conversation(self, conversation_id: str) -> dict[str, Any]:
        from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload

        try:
            return build_conversation_inspector_payload(conversation_id, self._base_dir)
        except KeyError as exc:
            raise PeerChatError("conversation_not_found", str(exc)) from exc

    def _collaboration_store(self):
        from xmuse_core.chat.collaboration_store import ChatCollaborationStore

        return ChatCollaborationStore(self._db_path)

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        registry_path: Path,
    ) -> dict[str, Any]:
        if tool_name == "chat_list_conversations":
            return self.list_conversations()
        if tool_name == "chat_create_conversation":
            return self.create_conversation(**arguments)
        if tool_name == "chat_list_participants":
            return self.list_participants(**arguments)
        if tool_name == "chat_post_message":
            return self.post_god_message(registry_path=registry_path, **arguments)
        if tool_name == "chat_mention":
            return self.mention_from_god(registry_path=registry_path, **arguments)
        if tool_name == "chat_read_inbox":
            return self.read_inbox(registry_path=registry_path, **arguments)
        if tool_name == "chat_mark_inbox":
            return self.mark_inbox(registry_path=registry_path, **arguments)
        if tool_name == "chat_emit_proposal":
            return self.emit_proposal(registry_path=registry_path, **arguments)
        if tool_name == "chat_emit_blueprint_proposal":
            return self.emit_blueprint_proposal(registry_path=registry_path, **arguments)
        if tool_name == "chat_inspect_conversation":
            return self.inspect_conversation(**arguments)
        if tool_name == "chat_create_collaboration_request":
            return self.create_collaboration_request(registry_path=registry_path, **arguments)
        if tool_name == "chat_record_collaboration_response":
            return self.record_collaboration_response(registry_path=registry_path, **arguments)
        if tool_name == "chat_raise_collaboration_blocker":
            return self.raise_collaboration_blocker(registry_path=registry_path, **arguments)
        if tool_name == "chat_resolve_collaboration_blocker":
            return self.resolve_collaboration_blocker(registry_path=registry_path, **arguments)
        if tool_name == "chat_evaluate_dispatch_gate":
            return self.evaluate_collaboration_dispatch_gate(
                registry_path=registry_path,
                **arguments,
            )
        raise PeerChatError("unknown_tool", tool_name)

    def create_collaboration_request(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        client_request_id: str,
        goal: str,
        targets: list[str],
        callback_target: str,
        question: str,
        context_refs: list[str] | None = None,
        idempotency_key: str | None = None,
        timeout_s: int = 480,
        orchestration_mode: str = "peer_consensus",
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        participant = self._participant_for_conversation(
            conversation_id=conversation_id,
            participant_id=participant_id,
            error_code="unknown_participant",
        )
        caller_identity = f"god:{god_session_id}:{participant_id}"
        logged = self._chat.get_logged_request_result(
            conversation_id=conversation_id,
            tool_name="chat_create_collaboration_request",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
        )
        if logged is not None:
            return logged

        target_mentions = self._resolve_collaboration_targets(
            conversation_id=conversation_id,
            targets=self._required_string_list(targets, "targets"),
        )
        callback = self._resolve_collaboration_callback_target(
            conversation_id=conversation_id,
            target=self._required_string(callback_target, "callback_target"),
        )
        normalized_idempotency_key = self._optional_string(idempotency_key)
        store = self._collaboration_store()
        if normalized_idempotency_key:
            existing = store.find_by_idempotency_key(
                conversation_id,
                normalized_idempotency_key,
            )
            if existing is not None:
                return {"run": existing.model_dump(mode="json")}

        try:
            run = store.create_request(
                conversation_id=conversation_id,
                goal=self._required_string(goal, "goal"),
                initiator=participant.role,
                targets=[target.normalized for target in target_mentions],
                callback_target=callback.normalized,
                question=self._required_string(question, "question"),
                context_refs=self._optional_string_list(context_refs, "context_refs"),
                idempotency_key=normalized_idempotency_key,
                timeout_s=int(timeout_s),
                orchestration_mode=orchestration_mode,
            )
        except ValueError as exc:
            raise PeerChatError("invalid_collaboration_request", str(exc)) from exc
        resolved_reply_to_inbox_item_id = self._single_claimed_inbox_item_id(
            conversation_id=conversation_id,
            participant_id=participant_id,
        )
        content = _collaboration_request_content(
            run_id=run.run_id,
            initiator=participant.role,
            target_addresses=[target.normalized for target in target_mentions],
            callback_target=callback.normalized,
            goal=run.goal,
            question=run.question,
        )
        result = self._chat.create_message_inbox_and_log(
            conversation_id=conversation_id,
            tool_name="chat_create_collaboration_request",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
            author=participant_id,
            role="assistant",
            content=content,
            envelope_type="collaboration_request",
            envelope_json=normalize_envelope(
                {
                    "type": "collaboration_request",
                    "schema_version": 1,
                    "collaboration_run_id": run.run_id,
                    "collaboration_status": run.status.value,
                    "targets": run.targets,
                    "callback_target": run.callback_target,
                },
                envelope_type="collaboration_request",
            ),
            mentions=[target.normalized for target in target_mentions],
            inbox_items=[
                {
                    "target_participant_id": target.participant.participant_id,
                    "target_role": target.participant.role,
                    "target_address": target.normalized,
                    "sender_participant_id": participant_id,
                    "sender_address": f"@participant:{participant_id}",
                    "item_type": "collaboration_request",
                    "payload": {
                        "content": _collaboration_request_target_content(
                            run_id=run.run_id,
                            target_address=target.normalized,
                            callback_target=callback.normalized,
                            goal=run.goal,
                            question=run.question,
                            context_refs=run.context_refs,
                        ),
                        "collaboration_run_id": run.run_id,
                        "collaboration_status": run.status.value,
                        "target": target.normalized,
                        "callback_target": callback.normalized,
                        "goal": run.goal,
                        "question": run.question,
                        "context_refs": run.context_refs,
                    },
                }
                for target in target_mentions
            ],
            reply_to_inbox_item_id=resolved_reply_to_inbox_item_id,
            reply_owner_participant_id=participant_id,
            extra_result={"run": run.model_dump(mode="json")},
        )
        if resolved_reply_to_inbox_item_id:
            PeerTurnLatencyTraceStore(self._db_path).record_mcp_tool_stage(
                conversation_id=conversation_id,
                inbox_item_id=resolved_reply_to_inbox_item_id,
                tool_name="chat_create_collaboration_request",
                called_at=time.monotonic(),
            )
            GodSessionRegistry(registry_path).promote_running(god_session_id)
        return result

    def _resolve_collaboration_targets(
        self,
        *,
        conversation_id: str,
        targets: list[str],
    ) -> list[Any]:
        resolver = MentionResolver(self._participants)
        resolved = []
        seen: set[str] = set()
        for target in targets:
            try:
                mention = resolver.resolve(conversation_id, target)
            except MentionResolutionError as exc:
                raise PeerChatError(exc.code, exc.target) from exc
            if mention.normalized in seen:
                continue
            seen.add(mention.normalized)
            resolved.append(mention)
        if not resolved:
            raise PeerChatError("invalid_collaboration_request", "targets")
        return resolved

    def record_collaboration_response(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        run_id: str,
        content: str,
        status: str = "received",
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        participant = self._participant_for_conversation(
            conversation_id=conversation_id,
            participant_id=participant_id,
            error_code="unknown_participant",
        )
        store = self._collaboration_store()
        run = self._collaboration_run_for_conversation(store, run_id, conversation_id)
        callback_target = self._resolve_collaboration_callback_target(
            conversation_id=conversation_id,
            target=run.callback_target,
        )
        response_target = _collaboration_response_target(participant.role, run.targets)
        if response_target is None:
            raise PeerChatError("collaboration_target_mismatch", participant.role)
        try:
            updated = store.record_response(
                run_id,
                target=response_target,
                content=str(content),
                response_status=status,
            )
        except ValueError as exc:
            raise PeerChatError("invalid_collaboration_response", str(exc)) from exc
        response_inbox_item_id = self._collaboration_inbox_item_id(
            conversation_id=conversation_id,
            participant_id=participant_id,
            run_id=run_id,
            item_type="collaboration_request",
        )
        if response_inbox_item_id:
            self._mark_inbox_consumed_by_tool(
                conversation_id=conversation_id,
                participant_id=participant_id,
                inbox_item_id=response_inbox_item_id,
                tool_name="chat_record_collaboration_response",
            )
        GodSessionRegistry(registry_path).promote_running(god_session_id)
        callback: dict[str, Any] | None = None
        if updated.status is CollaborationStatus.DONE:
            callback = self._create_collaboration_done_callback(
                run=updated,
                callback_target=callback_target,
            )
        result = {"run": updated.model_dump(mode="json")}
        if callback is not None:
            result["callback"] = callback
        return result

    def _resolve_collaboration_callback_target(
        self,
        *,
        conversation_id: str,
        target: str,
    ):
        try:
            return MentionResolver(self._participants).resolve(conversation_id, target)
        except MentionResolutionError as exc:
            raise PeerChatError(
                "collaboration_callback_target_unresolved",
                target,
            ) from exc

    def _create_collaboration_done_callback(
        self,
        *,
        run,
        callback_target,
    ) -> dict[str, Any]:
        responses = [
            response.model_dump(mode="json")
            for response in run.responses
        ]
        content = (
            f"Collaboration run `{run.run_id}` is done. Review the formal responses "
            "and continue the requested handoff. If the original request asked for "
            "a lane_graph proposal, call chat_emit_proposal now with exactly one "
            f"proposal and `collaboration:{run.run_id}` as a reference. Do not "
            "merely acknowledge that you will emit a proposal."
        )
        payload = self._chat.create_message_inbox_and_log(
            conversation_id=run.conversation_id,
            tool_name="chat_collaboration_done_callback",
            caller_identity=f"collaboration:{run.run_id}",
            client_request_id=f"collaboration-done:{run.run_id}",
            author="collaboration-runner",
            role="system",
            content=content,
            envelope_type="collaboration_callback",
            envelope_json=normalize_envelope(
                {
                    "type": "collaboration_callback",
                    "schema_version": 1,
                    "collaboration_run_id": run.run_id,
                    "collaboration_status": run.status.value,
                },
                envelope_type="collaboration_callback",
            ),
            mentions=[callback_target.normalized],
            inbox_items=[
                {
                    "target_participant_id": callback_target.participant.participant_id,
                    "target_role": callback_target.participant.role,
                    "target_address": callback_target.normalized,
                    "sender_participant_id": None,
                    "sender_address": f"@collaboration:{run.run_id}",
                    "item_type": "collaboration_callback",
                    "payload": {
                        "content": content,
                        "collaboration_run_id": run.run_id,
                        "collaboration_status": run.status.value,
                        "trigger_mode": "collaboration_done_callback",
                        "responses": responses,
                    },
                }
            ],
        )
        return {
            "message": payload.get("message"),
            "inbox_items": payload.get("inbox_items", []),
        }

    def raise_collaboration_blocker(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        run_id: str,
        severity: str,
        reason: str,
        affected_ref: str,
        suggested_fix: str,
        blocks_dispatch: bool,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        participant = self._participant_for_conversation(
            conversation_id=conversation_id,
            participant_id=participant_id,
            error_code="unknown_participant",
        )
        store = self._collaboration_store()
        self._collaboration_run_for_conversation(store, run_id, conversation_id)
        try:
            blocker = store.raise_blocker(
                run_id,
                issuer=participant.role,
                severity=severity,
                reason=reason,
                affected_ref=affected_ref,
                suggested_fix=suggested_fix,
                blocks_dispatch=bool(blocks_dispatch),
            )
        except ValueError as exc:
            raise PeerChatError("invalid_collaboration_blocker", str(exc)) from exc
        return {"blocker": blocker.model_dump(mode="json")}

    def resolve_collaboration_blocker(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        blocker_id: str,
        resolution_evidence: str,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        participant = self._participant_for_conversation(
            conversation_id=conversation_id,
            participant_id=participant_id,
            error_code="unknown_participant",
        )
        store = self._collaboration_store()
        try:
            blocker = store.get_blocker(blocker_id)
        except KeyError as exc:
            raise PeerChatError("unknown_collaboration_blocker", blocker_id) from exc
        if blocker.conversation_id != conversation_id:
            raise PeerChatError("unknown_collaboration_blocker", blocker_id)
        try:
            resolved = store.resolve_blocker(
                blocker_id,
                resolved_by=participant.role,
                resolution_evidence=resolution_evidence,
            )
        except ValueError as exc:
            raise PeerChatError("invalid_collaboration_blocker", str(exc)) from exc
        return {"blocker": resolved.model_dump(mode="json")}

    def evaluate_collaboration_dispatch_gate(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        run_id: str,
        proposal_ref: str | None = None,
        artifact_ref: str | None = None,
        execute_confirmed: bool = False,
        policy_allows_real_provider: bool = True,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        self._participant_for_conversation(
            conversation_id=conversation_id,
            participant_id=participant_id,
            error_code="unknown_participant",
        )
        decision = self._collaboration_store().evaluate_dispatch_gate(
            conversation_id=conversation_id,
            run_id=run_id,
            proposal_ref=proposal_ref,
            artifact_ref=artifact_ref,
            execute_confirmed=bool(execute_confirmed),
            policy_allows_real_provider=bool(policy_allows_real_provider),
        )
        return {"decision": decision.value}

    def post_god_message(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        client_request_id: str,
        content: str,
        envelope: dict[str, Any] | None = None,
        reply_to_inbox_item_id: str | None = None,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        caller_identity = f"god:{god_session_id}:{participant_id}"
        normalized = normalize_envelope(envelope, envelope_type="message")
        mentions, inbox_items = self._build_god_inbox_items(
            conversation_id=conversation_id,
            content=content,
        )
        result = self._chat.create_message_inbox_and_log(
            conversation_id=conversation_id,
            tool_name="chat_post_message",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
            author=participant_id,
            role="assistant",
            content=content,
            envelope_type=normalized["type"],
            envelope_json=normalized,
            mentions=mentions,
            inbox_items=inbox_items,
            reply_to_inbox_item_id=reply_to_inbox_item_id,
            reply_owner_participant_id=participant_id,
        )
        if reply_to_inbox_item_id:
            PeerTurnLatencyTraceStore(self._db_path).record_mcp_tool_stage(
                conversation_id=conversation_id,
                inbox_item_id=reply_to_inbox_item_id,
                tool_name="chat_post_message",
                called_at=time.monotonic(),
            )
            GodSessionRegistry(registry_path).promote_running(god_session_id)
        return result

    def _build_god_inbox_items(
        self,
        *,
        conversation_id: str,
        content: str,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        mentions: list[str] = []
        resolver = MentionResolver(self._participants)
        seen: set[str] = set()
        for raw in extract_mentions(content):
            if normalize_address(raw) == "@all":
                if "@all" not in seen:
                    seen.add("@all")
                    mentions.append("@all")
                continue
        for target in resolver.resolve_content(conversation_id, content, strict=False):
            if target.normalized in seen:
                continue
            seen.add(target.normalized)
            mentions.append(target.normalized)
        return mentions, []

    def mention_from_god(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        client_request_id: str,
        target_address: str,
        content: str,
        envelope: dict[str, Any] | None = None,
        reply_to_inbox_item_id: str | None = None,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        caller_identity = f"god:{god_session_id}:{participant_id}"
        logged = self._chat.get_logged_request_result(
            conversation_id=conversation_id,
            tool_name="chat_mention",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
        )
        if logged is not None:
            return logged

        resolver = MentionResolver(self._participants)
        try:
            target = resolver.resolve(conversation_id, target_address)
        except MentionResolutionError as exc:
            raise PeerChatError(exc.code, exc.target) from exc
        normalized = normalize_envelope(envelope, envelope_type="mention")
        resolved_reply_to_inbox_item_id = (
            reply_to_inbox_item_id
            or self._single_claimed_inbox_item_id(
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
        )
        try:
            result = self._chat.create_message_inbox_and_log(
                conversation_id=conversation_id,
                tool_name="chat_mention",
                caller_identity=caller_identity,
                client_request_id=client_request_id,
                author=participant_id,
                role="assistant",
                content=content,
                envelope_type=normalized["type"],
                envelope_json=normalized,
                mentions=[target.normalized],
                inbox_items=[
                    {
                        "target_participant_id": target.participant.participant_id,
                        "target_role": target.participant.role,
                        "target_address": target.normalized,
                        "sender_participant_id": participant_id,
                        "sender_address": f"@participant:{participant_id}",
                        "item_type": "mention",
                        "payload": {"content": content, "mention": target.raw},
                    }
                ],
                reply_to_inbox_item_id=resolved_reply_to_inbox_item_id,
                reply_owner_participant_id=participant_id,
                turn_budget_action="consume",
            )
            if resolved_reply_to_inbox_item_id:
                PeerTurnLatencyTraceStore(self._db_path).record_mcp_tool_stage(
                    conversation_id=conversation_id,
                    inbox_item_id=resolved_reply_to_inbox_item_id,
                    tool_name="chat_mention",
                    called_at=time.monotonic(),
                )
                GodSessionRegistry(registry_path).promote_running(god_session_id)
            return result
        except ValueError as exc:
            if str(exc) == "turn_budget_exhausted":
                raise PeerChatError("turn_budget_exhausted", conversation_id) from exc
            raise

    def read_inbox(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        limit: int = 20,
        include_claimed: bool = True,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        items = self._inbox.list_for_participant(
            conversation_id=conversation_id,
            participant_id=participant_id,
            include_claimed=include_claimed,
            limit=limit,
        )
        called_at = time.monotonic()
        latency = PeerTurnLatencyTraceStore(self._db_path)
        for item in items:
            latency.record_mcp_tool_stage(
                conversation_id=conversation_id,
                inbox_item_id=item.id,
                tool_name="chat_read_inbox",
                called_at=called_at,
            )
        return {"inbox_items": [item.model_dump(mode="json") for item in items]}

    def mark_inbox(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        inbox_item_id: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        try:
            item = self._inbox.get(inbox_item_id)
        except KeyError as exc:
            raise PeerChatError("unknown_inbox_item", inbox_item_id) from exc
        if item.conversation_id != conversation_id or item.target_participant_id != participant_id:
            raise PeerChatError("inbox_item_not_owned", inbox_item_id)
        if status == "read":
            updated = self._inbox.mark_read(inbox_item_id)
        elif status == "failed":
            updated = self._inbox.mark_failed(inbox_item_id, reason=reason or "marked_failed")
        else:
            raise PeerChatError("invalid_inbox_status", status)
        return {"inbox_item": updated.model_dump(mode="json")}

    def _proposal_emitter(self) -> PeerProposalEmitter:
        return PeerProposalEmitter(self._chat)

    def emit_proposal(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        client_request_id: str,
        summary: str,
        lanes: list[dict[str, Any]],
        references: list[str] | None = None,
        resolution_content: dict[str, Any] | None = None,
        reply_to_inbox_item_id: str | None = None,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        proposal_references = references or []
        self._require_ready_collaboration_references(
            conversation_id=conversation_id,
            references=proposal_references,
        )
        payload = self._proposal_emitter().emit_lane_graph_proposal(
            conversation_id=conversation_id,
            participant_id=participant_id,
            caller_identity=f"god:{god_session_id}:{participant_id}",
            client_request_id=client_request_id,
            summary=summary,
            lanes=lanes,
            references=proposal_references,
            resolution_content=resolution_content,
        )
        proposal_message_id = self._proposal_message_id(payload)
        resolved_reply_to_inbox_item_id = (
            reply_to_inbox_item_id
            or self._single_claimed_inbox_item_id(
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
        )
        if resolved_reply_to_inbox_item_id:
            self._mark_inbox_replied_by_tool(
                conversation_id=conversation_id,
                participant_id=participant_id,
                inbox_item_id=resolved_reply_to_inbox_item_id,
                responded_message_id=proposal_message_id,
                tool_name="chat_emit_proposal",
            )
            GodSessionRegistry(registry_path).promote_running(god_session_id)
        self._mark_collaboration_callback_inboxes_for_references(
            conversation_id=conversation_id,
            participant_id=participant_id,
            references=proposal_references,
            responded_message_id=proposal_message_id,
            exclude_inbox_item_id=resolved_reply_to_inbox_item_id,
        )
        self._ensure_review_trigger(
            conversation_id=conversation_id,
            source_message_id=proposal_message_id,
            sender_participant_id=participant_id,
            reviewable_type="lane_graph",
        )
        return payload

    def emit_proposal_without_session_for_test(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        client_request_id: str,
        summary: str,
        lanes: list[dict[str, Any]],
        references: list[str] | None = None,
        resolution_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        proposal_references = references or []
        self._require_ready_collaboration_references(
            conversation_id=conversation_id,
            references=proposal_references,
        )
        payload = self._proposal_emitter().emit_lane_graph_proposal(
            conversation_id=conversation_id,
            participant_id=participant_id,
            caller_identity=f"test:{participant_id}",
            client_request_id=client_request_id,
            summary=summary,
            lanes=lanes,
            references=proposal_references,
            resolution_content=resolution_content,
        )
        self._ensure_review_trigger(
            conversation_id=conversation_id,
            source_message_id=self._proposal_message_id(payload),
            sender_participant_id=participant_id,
            reviewable_type="lane_graph",
        )
        return payload

    def emit_blueprint_proposal(
        self,
        *,
        registry_path: Path,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        client_request_id: str,
        title: str,
        body: str,
        acceptance_criteria: list[str],
        revises_blueprint_ref: str | None = None,
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        self._verify_god_identity(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=god_session_id,
        )
        payload = self._proposal_emitter().emit_blueprint_proposal(
            conversation_id=conversation_id,
            participant_id=participant_id,
            caller_identity=f"god:{god_session_id}:{participant_id}",
            client_request_id=client_request_id,
            title=title,
            body=body,
            acceptance_criteria=acceptance_criteria,
            revises_blueprint_ref=revises_blueprint_ref,
            references=references or [],
        )
        self._ensure_review_trigger(
            conversation_id=conversation_id,
            source_message_id=self._proposal_message_id(payload),
            sender_participant_id=participant_id,
            reviewable_type="mission_blueprint",
        )
        return payload

    def emit_blueprint_proposal_without_session_for_test(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        client_request_id: str,
        title: str,
        body: str,
        acceptance_criteria: list[str],
        revises_blueprint_ref: str | None = None,
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self._proposal_emitter().emit_blueprint_proposal(
            conversation_id=conversation_id,
            participant_id=participant_id,
            caller_identity=f"test:{participant_id}",
            client_request_id=client_request_id,
            title=title,
            body=body,
            acceptance_criteria=acceptance_criteria,
            revises_blueprint_ref=revises_blueprint_ref,
            references=references or [],
        )
        self._ensure_review_trigger(
            conversation_id=conversation_id,
            source_message_id=self._proposal_message_id(payload),
            sender_participant_id=participant_id,
            reviewable_type="mission_blueprint",
        )
        return payload

    def _mark_inbox_replied_by_tool(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        inbox_item_id: str,
        responded_message_id: str,
        tool_name: str,
    ) -> None:
        self._mark_inbox_consumed_by_tool(
            conversation_id=conversation_id,
            participant_id=participant_id,
            inbox_item_id=inbox_item_id,
            tool_name=tool_name,
            responded_message_id=responded_message_id,
        )

    def _mark_inbox_consumed_by_tool(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        inbox_item_id: str,
        tool_name: str,
        responded_message_id: str | None = None,
    ) -> None:
        try:
            item = self._inbox.get(inbox_item_id)
        except KeyError as exc:
            raise PeerChatError("unknown_inbox_item", inbox_item_id) from exc
        if item.conversation_id != conversation_id or item.target_participant_id != participant_id:
            raise PeerChatError("inbox_item_not_owned", inbox_item_id)
        self._inbox.mark_read(inbox_item_id, responded_message_id=responded_message_id)
        PeerTurnLatencyTraceStore(self._db_path).record_mcp_tool_stage(
            conversation_id=conversation_id,
            inbox_item_id=inbox_item_id,
            tool_name=tool_name,
            called_at=time.monotonic(),
        )

    def _single_claimed_inbox_item_id(
        self,
        *,
        conversation_id: str,
        participant_id: str,
    ) -> str | None:
        claimed_items = [
            item
            for item in self._inbox.list_for_participant(
                conversation_id=conversation_id,
                participant_id=participant_id,
                include_claimed=True,
            )
            if item.status == "claimed"
        ]
        if len(claimed_items) != 1:
            return None
        return claimed_items[0].id

    def _collaboration_inbox_item_id(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        run_id: str,
        item_type: str,
    ) -> str | None:
        for item in self._inbox.list_for_participant(
            conversation_id=conversation_id,
            participant_id=participant_id,
            include_claimed=True,
            limit=100,
        ):
            if item.item_type != item_type:
                continue
            if item.payload.get("collaboration_run_id") == run_id:
                return item.id
        return None

    def _mark_collaboration_callback_inboxes_for_references(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        references: list[str],
        responded_message_id: str,
        exclude_inbox_item_id: str | None,
    ) -> None:
        for run_id in _collaboration_reference_run_ids(references):
            inbox_item_id = self._collaboration_inbox_item_id(
                conversation_id=conversation_id,
                participant_id=participant_id,
                run_id=run_id,
                item_type="collaboration_callback",
            )
            if not inbox_item_id or inbox_item_id == exclude_inbox_item_id:
                continue
            self._mark_inbox_consumed_by_tool(
                conversation_id=conversation_id,
                participant_id=participant_id,
                inbox_item_id=inbox_item_id,
                tool_name="chat_emit_proposal",
                responded_message_id=responded_message_id,
            )

    def _proposal_message_id(self, payload: dict[str, Any]) -> str:
        message = payload.get("message")
        if not isinstance(message, dict):
            raise PeerChatError("invalid_proposal_emit_result", "missing message payload")
        message_id = message.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise PeerChatError("invalid_proposal_emit_result", "missing message id")
        return message_id

    def _ensure_review_trigger(
        self,
        *,
        conversation_id: str,
        source_message_id: str,
        sender_participant_id: str,
        reviewable_type: str,
    ) -> None:
        review_participant = self._review_participant(conversation_id)
        if self._has_review_trigger(
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            review_participant_id=review_participant.participant_id,
        ):
            return
        self._inbox.create_item(
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
        content = (
            _review_trigger_content(
                source_message_id=source_message_id,
                reviewable_type=reviewable_type,
                source_content=source_message.content,
                envelope=source_message.envelope_json,
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

    def _has_review_trigger(
        self,
        *,
        conversation_id: str,
        source_message_id: str,
        review_participant_id: str,
    ) -> bool:
        for item in self._inbox.list_by_conversation(conversation_id, include_terminal=True):
            if (
                item.target_participant_id == review_participant_id
                and item.source_message_id == source_message_id
            ):
                return True
        return False

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


def _collaboration_response_target(role: str, targets: list[str]) -> str | None:
    """Return the stored collaboration target matching a participant role."""
    role = role.strip()
    if role in targets:
        return role
    address = f"@{role}"
    if address in targets:
        return address
    return None


def _collaboration_request_content(
    *,
    run_id: str,
    initiator: str,
    target_addresses: list[str],
    callback_target: str,
    goal: str,
    question: str,
) -> str:
    targets = ", ".join(target_addresses)
    return (
        f"Collaboration run `{run_id}` created by @{initiator} for {targets}.\n\n"
        f"Goal: {goal}\n\n"
        f"Question: {question}\n\n"
        f"Callback target after all responses: {callback_target}."
    )


def _collaboration_request_target_content(
    *,
    run_id: str,
    target_address: str,
    callback_target: str,
    goal: str,
    question: str,
    context_refs: list[str],
) -> str:
    refs = ", ".join(context_refs) if context_refs else "none"
    return (
        f"{target_address}\n"
        f"Record a formal collaboration response for collaboration run `{run_id}` "
        "using chat_record_collaboration_response.\n\n"
        f"Goal: {goal}\n\n"
        f"Question: {question}\n\n"
        f"Context refs: {refs}\n\n"
        f"After all targets respond, xmuse will notify {callback_target}. "
        "For executable dispatch, use the JSON shape "
        '{"type":"execute_feasibility_verdict","status":"executable",'
        '"summary":"<why dispatch is safe>","evidence_refs":["<ref>"]}.'
    )


def _collaboration_reference_run_ids(references: list[str]) -> list[str]:
    run_ids: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if not isinstance(reference, str):
            continue
        prefix, separator, raw_run_id = reference.strip().partition(":")
        if separator != ":" or prefix != "collaboration":
            continue
        run_id = raw_run_id.strip()
        if not run_id or run_id in seen:
            continue
        seen.add(run_id)
        run_ids.append(run_id)
    return run_ids


def _review_trigger_content(
    *,
    source_message_id: str,
    reviewable_type: str,
    source_content: str,
    envelope: dict[str, Any],
) -> str:
    sections = [
        f"Review this {reviewable_type} proposal.",
        f"Source message: {source_message_id}",
    ]
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
                sections.append(line)
    references = envelope.get("references")
    if isinstance(references, list) and references:
        refs = [ref for ref in references if isinstance(ref, str) and ref.strip()]
        if refs:
            sections.append("References: " + ", ".join(refs))
    if source_content.strip():
        sections.extend(["Source content:", source_content.strip()])
    return "\n".join(sections)
