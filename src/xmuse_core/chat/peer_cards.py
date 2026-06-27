"""Chat card assembly for peer chat conversations."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.persistent_peer import PeerHandle, PeerRequestResult
from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.chat.health_cards import build_run_health_chat_card
from xmuse_core.chat.lane_scope import conversation_scoped_lanes
from xmuse_core.chat.models import ChatCard
from xmuse_core.chat.participant_store import (
    Participant,
    ParticipantStore,
    provider_profile_id_for_role,
)
from xmuse_core.chat.peer_request_cards import (
    build_peer_request_chat_card,
    build_peer_result_chat_card,
)
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.run_health import summarize_run_health
from xmuse_core.platform.state_normalizer import normalize_lane_state


@dataclass
class PeerChatCardAssembler:
    """Builds compact chat cards from chat, graph, lane, and runtime read models."""

    base_dir: Path
    chat: ChatStore
    inbox: Any
    participants: ParticipantStore

    def __post_init__(self) -> None:
        self._base_dir = Path(self.base_dir)
        self._chat = self.chat
        self._inbox = self.inbox
        self._participants = self.participants

    def _card_counts(self, cards: list[ChatCard]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for card in cards:
            counts[card.card_type] = counts.get(card.card_type, 0) + 1
        counts["total"] = len(cards)
        return counts

    def _cards_for_conversation(self, conversation_id: str) -> list[ChatCard]:
        cards: list[ChatCard] = []
        for proposal in self._chat.list_proposals(conversation_id):
            if proposal.proposal_type == "mission_blueprint":
                continue
            cards.append(self._proposal_card(proposal))

        for resolution in self._chat.list_resolutions(conversation_id):
            if resolution.content.get("type") == "mission_blueprint":
                cards.append(self._mission_blueprint_card(resolution))

        cards.extend(self._lane_graph_cards(conversation_id))
        cards.extend(self._feature_plan_cards(conversation_id))
        cards.extend(self._feature_graph_set_cards(conversation_id))
        cards.extend(self._execution_cards(conversation_id))
        cards.extend(self._peer_request_result_cards(conversation_id))
        health_eligible = bool(cards)
        worklist_card = self._worklist_summary_card(conversation_id)
        if worklist_card is not None:
            cards.append(worklist_card)
        if health_eligible and self._has_health_sources():
            cards.append(self._health_summary_card(conversation_id))
        cards.sort(key=lambda card: (card.created_at, card.card_type, card.source_id))
        return cards

    def _execution_cards(self, conversation_id: str) -> list[ChatCard]:
        return ChatExecutionCardEmitter(self._base_dir).list_cards(conversation_id)

    def _inbox_counts(self, conversation_id: str) -> dict[str, int]:
        counts = {"unread": 0, "claimed": 0}
        for item in self._inbox.list_by_conversation(conversation_id):
            if item.status in counts:
                counts[item.status] += 1
        return counts

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
        elif provider_id == "a2a":
            session.setdefault("profile_id", "remote")
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

    def _proposal_card(self, proposal: Any) -> ChatCard:
        content = self._json_object(proposal.content)
        lanes = content.get("lanes", [])
        references = proposal.references
        summary = self._compact_text(self._string_value(content.get("summary")) or proposal.content)
        return ChatCard(
            id=f"card_proposal_{proposal.id}",
            conversation_id=proposal.conversation_id,
            card_type="proposal",
            source_id=proposal.id,
            title=summary,
            summary=summary,
            status=proposal.status.value,
            href=f"/dashboard/peer-chat/conversations/{proposal.conversation_id}"
            f"#proposal-{proposal.id}",
            api_href=f"/api/chat/proposals/{proposal.id}",
            created_at=proposal.created_at,
            counts={
                "references": len(references),
                "lanes": len(lanes) if isinstance(lanes, list) else 0,
            },
            metadata={"proposal_type": proposal.proposal_type},
        )

    def _mission_blueprint_card(self, resolution: Any) -> ChatCard:
        content = resolution.content
        references = content.get("references", [])
        if not isinstance(references, list):
            references = []
        if not references:
            for proposal_id in resolution.derived_from_proposal_ids:
                try:
                    references.extend(self._chat.get_proposal(proposal_id).references)
                except KeyError:
                    continue
        criteria = content.get("acceptance_criteria", [])
        title = self._string_value(content.get("title")) or resolution.goal_summary
        return ChatCard(
            id=f"card_mission_blueprint_{resolution.id}",
            conversation_id=resolution.conversation_id,
            card_type="mission_blueprint",
            source_id=resolution.id,
            title=title,
            summary=resolution.goal_summary,
            status=resolution.status.value,
            href=f"/dashboard/peer-chat/conversations/{resolution.conversation_id}"
            f"#resolution-{resolution.id}",
            api_href=f"/api/chat/resolutions/{resolution.id}",
            created_at=resolution.created_at,
            counts={
                "acceptance_criteria": len(criteria) if isinstance(criteria, list) else 0,
                "references": len(references),
            },
            metadata={"version": resolution.version},
        )

    def _peer_request_result_cards(self, conversation_id: str) -> list[ChatCard]:
        cards: list[ChatCard] = []
        seen: set[tuple[str, str]] = set()
        sessions = self._sessions_by_conversation().get(conversation_id, [])
        for lane in self._conversation_scoped_lanes(conversation_id, self._feature_lanes()):
            cards.extend(
                self._peer_cards_for_lane(
                    conversation_id=conversation_id,
                    lane=lane,
                    sessions=sessions,
                    seen=seen,
                    message_type="review",
                    participant_field="review_peer_id",
                    request_field="peer_request_id",
                    delivery_mode_field="peer_delivery_mode",
                    degraded_reason_fields=("peer_degraded_reason", "failure_reason"),
                )
            )
            cards.extend(
                self._peer_cards_for_lane(
                    conversation_id=conversation_id,
                    lane=lane,
                    sessions=sessions,
                    seen=seen,
                    message_type="execute",
                    participant_field="execute_peer_id",
                    request_field="execute_peer_request_id",
                    delivery_mode_field="execute_peer_delivery_mode",
                    degraded_reason_fields=(
                        "execute_peer_degraded_reason",
                        "persistent_execute_degraded_reason",
                        "failure_reason",
                    ),
                )
            )
        return cards

    def _peer_cards_for_lane(
        self,
        *,
        conversation_id: str,
        lane: dict[str, Any],
        sessions: list[dict[str, Any]],
        seen: set[tuple[str, str]],
        message_type: str,
        participant_field: str,
        request_field: str,
        delivery_mode_field: str,
        degraded_reason_fields: tuple[str, ...],
    ) -> list[ChatCard]:
        request_id = self._string_value(lane.get(request_field))
        participant_id = self._string_value(lane.get(participant_field))
        if request_id is None or participant_id is None:
            return []

        handle = self._peer_handle_for_card(
            conversation_id=conversation_id,
            participant_id=participant_id,
            message_type=message_type,
            lane=lane,
            sessions=sessions,
        )
        created_at = self._lane_card_timestamp(lane)
        lane_id = self._string_value(lane.get("feature_id"))
        feature_id = self._lane_feature_ref(lane)
        graph_id = self._string_value(lane.get("graph_id"))

        cards: list[ChatCard] = []
        request_key = ("request", request_id)
        if request_key not in seen:
            cards.append(
                build_peer_request_chat_card(
                    handle,
                    request_id=request_id,
                    message_type=message_type,
                    created_at=created_at,
                    lane_id=lane_id,
                    feature_id=feature_id,
                    graph_id=graph_id,
                )
            )
            seen.add(request_key)

        result = self._peer_result_for_lane(
            lane=lane,
            message_type=message_type,
            request_id=request_id,
            delivery_mode=self._string_value(lane.get(delivery_mode_field)),
            degraded_reason=self._first_string_value(lane, degraded_reason_fields),
        )
        result_key = ("result", request_id)
        if result is not None and result_key not in seen:
            cards.append(
                build_peer_result_chat_card(
                    handle,
                    result,
                    message_type=message_type,
                    created_at=created_at,
                    lane_id=lane_id,
                    feature_id=feature_id,
                    graph_id=graph_id,
                )
            )
            seen.add(result_key)
        return cards

    def _peer_handle_for_card(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        message_type: str,
        lane: dict[str, Any],
        sessions: list[dict[str, Any]],
    ) -> PeerHandle:
        session = self._session_for_participant(sessions, participant_id)
        participant = self._participant_for_card(participant_id)
        role = (
            participant.role
            if participant is not None
            else self._string_value(session.get("role") if session else None) or message_type
        )
        runtime = self._string_value(session.get("runtime") if session else None) or "codex"
        model = (
            self._string_value(session.get("model") if session else None)
            or (participant.model if participant is not None else None)
            or self._string_value(lane.get(f"{message_type}_model"))
            or "unknown"
        )
        feature_scope_id = (
            self._string_value(session.get("feature_scope_id") if session else None)
            or self._lane_feature_ref(lane)
        )
        return PeerHandle(
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=(
                self._string_value(session.get("god_session_id") if session else None)
                or self._string_value(session.get("session_id") if session else None)
                or "unknown"
            ),
            role=role,
            cli_kind=participant.cli_kind if participant is not None else runtime,
            runtime=runtime,
            model=model,
            prompt_fingerprint="",
            worktree="",
            feature_scope_id=feature_scope_id,
        )

    def _session_for_participant(
        self,
        sessions: list[dict[str, Any]],
        participant_id: str,
    ) -> dict[str, Any] | None:
        for session in sessions:
            if self._string_value(session.get("participant_id")) == participant_id:
                return session
        return None

    def _participant_for_card(self, participant_id: str) -> Participant | None:
        try:
            return self._participants.get(participant_id)
        except KeyError:
            return None

    def _peer_result_for_lane(
        self,
        *,
        lane: dict[str, Any],
        message_type: str,
        request_id: str,
        delivery_mode: str | None,
        degraded_reason: str | None,
    ) -> PeerRequestResult | None:
        if delivery_mode is None and degraded_reason is None:
            return None
        if delivery_mode == "configured_peer" and degraded_reason is None:
            if self._peer_success_result_available(lane, message_type=message_type):
                return PeerRequestResult(status="ok", request_id=request_id)
            return None
        status = (
            "peer_unavailable"
            if delivery_mode == "required_peer_failed"
            else "delivery_failed"
        )
        return PeerRequestResult(
            status=status,
            request_id=request_id,
            reason=degraded_reason or delivery_mode or "delivery_failed",
        )

    def _peer_success_result_available(
        self,
        lane: dict[str, Any],
        *,
        message_type: str,
    ) -> bool:
        lane_status = self._string_value(lane.get("status"))
        if message_type == "execute":
            return lane_status in {
                "executed",
                "reviewed",
                "rejected",
                "reworking",
                "gate_failed",
                "merged",
                "done",
            }
        if message_type == "review":
            return lane_status in {
                "reviewed",
                "rejected",
                "reworking",
                "gate_failed",
                "merged",
                "done",
            }
        return False

    def _first_string_value(
        self,
        data: dict[str, Any],
        fields: tuple[str, ...],
    ) -> str | None:
        for field in fields:
            value = self._string_value(data.get(field))
            if value is not None:
                return value
        return None

    def _lane_feature_ref(self, lane: dict[str, Any]) -> str | None:
        return (
            self._string_value(lane.get("feature_plan_feature_id"))
            or self._string_value(lane.get("plan_feature_id"))
            or self._string_value(lane.get("feature_scope_id"))
            or self._string_value(lane.get("feature_id"))
        )

    def _lane_card_timestamp(self, lane: dict[str, Any]) -> str:
        for field in (
            "updated_at",
            "completed_at",
            "reviewed_at",
            "started_at",
            "created_at",
        ):
            value = self._string_value(lane.get(field))
            if value is not None:
                return value
        lanes_path = self._base_dir / "feature_lanes.json"
        if lanes_path.exists():
            return self._file_timestamp(lanes_path)
        return "1970-01-01T00:00:00Z"

    def _lane_graph_cards(self, conversation_id: str) -> list[ChatCard]:
        graphs_dir = self._base_dir / "lane_graphs"
        if not graphs_dir.exists():
            return []
        cards: list[ChatCard] = []
        for path in sorted(graphs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not self._is_lane_graph_snapshot(data):
                continue
            if data.get("conversation_id") != conversation_id:
                continue
            graph_id = self._string_value(data.get("id")) or path.stem
            lanes = data.get("lanes", [])
            cards.append(
                ChatCard(
                    id=f"card_lane_graph_{graph_id}",
                    conversation_id=conversation_id,
                    card_type="lane_graph",
                    source_id=graph_id,
                    title=graph_id,
                    summary=f"{len(lanes) if isinstance(lanes, list) else 0} lanes",
                    status=self._string_value(data.get("status")) or "planned",
                    href=(
                        f"/dashboard/peer-chat/conversations/{conversation_id}"
                        f"#lane-graph-{graph_id}"
                    ),
                    api_href=(
                        f"/api/dashboard/peer-chat/conversations/{conversation_id}"
                        f"/lane-graphs/{graph_id}"
                    ),
                    created_at=self._string_value(data.get("created_at"))
                    or self._string_value(data.get("updated_at"))
                    or self._file_timestamp(path),
                    counts={"lanes": len(lanes) if isinstance(lanes, list) else 0},
                    metadata={
                        "resolution_id": self._string_value(data.get("resolution_id")) or "",
                        "version": int(data.get("version") or 0),
                    },
                )
            )
        return cards

    def _feature_plan_cards(self, conversation_id: str) -> list[ChatCard]:
        graphs_dir = self._base_dir / "lane_graphs"
        if not graphs_dir.exists():
            return []
        cards: list[ChatCard] = []
        for path in sorted(graphs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not self._is_feature_graph_set_snapshot(data):
                continue

            feature_plan = data["feature_plan"]
            if feature_plan.get("conversation_id") != conversation_id:
                continue

            graph_set_id = self._string_value(data.get("id")) or path.stem
            plan_id = self._string_value(feature_plan.get("id")) or f"{graph_set_id}:feature-plan"
            features = feature_plan.get("features", [])
            graphs = data.get("graphs", [])
            progress_counts = self._feature_graph_set_progress_counts(feature_plan, graphs)
            feature_count = len(features) if isinstance(features, list) else 0
            terminal_features = progress_counts.get("terminal_features", 0)
            projected_features = progress_counts.get("projected_features", 0)
            status = "planned"
            if feature_count > 0 and terminal_features == feature_count:
                status = "terminal"
            elif projected_features > 0:
                status = "active"

            cards.append(
                ChatCard(
                    id=f"card_feature_plan_{plan_id}",
                    conversation_id=conversation_id,
                    card_type="feature_plan",
                    source_id=plan_id,
                    title=plan_id,
                    summary=f"{feature_count} features",
                    status=status,
                    href=f"/dashboard/feature-graph-sets/{graph_set_id}#feature-plan",
                    api_href=f"/api/feature-graph-sets/{graph_set_id}",
                    created_at=self._string_value(data.get("created_at"))
                    or self._string_value(data.get("updated_at"))
                    or self._file_timestamp(path),
                    counts={
                        "features": feature_count,
                        "projected_features": projected_features,
                        "terminal_features": terminal_features,
                    },
                    metadata={
                        "graph_set_id": graph_set_id,
                        "resolution_id": self._string_value(
                            feature_plan.get("resolution_id")
                        )
                        or "",
                        "version": int(feature_plan.get("version") or 0),
                    },
                )
            )
        return cards

    def _feature_graph_set_cards(self, conversation_id: str) -> list[ChatCard]:
        graphs_dir = self._base_dir / "lane_graphs"
        if not graphs_dir.exists():
            return []
        cards: list[ChatCard] = []
        for path in sorted(graphs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not self._is_feature_graph_set_snapshot(data):
                continue

            feature_plan = data["feature_plan"]
            if feature_plan.get("conversation_id") != conversation_id:
                continue

            graph_set_id = self._string_value(data.get("id")) or path.stem
            features = feature_plan["features"]
            graphs = data["graphs"]
            counts = {
                "features": len(features),
                "lane_graphs": len(graphs),
            }
            progress_counts = self._feature_graph_set_progress_counts(feature_plan, graphs)
            counts.update(progress_counts)
            terminal_features = progress_counts.get("terminal_features", 0)
            projected_features = progress_counts.get("projected_features", 0)
            status = "planned"
            if counts["features"] > 0 and terminal_features == counts["features"]:
                status = "terminal"
            elif projected_features > 0:
                status = "active"

            cards.append(
                ChatCard(
                    id=f"card_feature_graph_set_{graph_set_id}",
                    conversation_id=conversation_id,
                    card_type="feature_graph_set",
                    source_id=graph_set_id,
                    title=graph_set_id,
                    summary=(
                        f"{counts['features']} features, "
                        f"{counts['lane_graphs']} lane graphs"
                    ),
                    status=status,
                    href=(
                        f"/dashboard/peer-chat/conversations/{conversation_id}"
                        f"#feature-graph-set-{graph_set_id}"
                    ),
                    api_href=(
                        f"/api/dashboard/peer-chat/conversations/{conversation_id}"
                        f"/feature-graph-sets/{graph_set_id}"
                    ),
                    created_at=self._string_value(data.get("created_at"))
                    or self._string_value(data.get("updated_at"))
                    or self._file_timestamp(path),
                    counts=counts,
                    metadata={
                        "feature_plan_id": self._string_value(feature_plan.get("id")) or "",
                        "resolution_id": self._string_value(
                            feature_plan.get("resolution_id")
                        )
                        or "",
                        "version": int(feature_plan.get("version") or 0),
                    },
                )
            )
        return cards

    def _feature_graph_set_progress_counts(
        self,
        feature_plan: dict[str, Any],
        graphs: list[Any],
    ) -> dict[str, int]:
        plan_id = self._string_value(feature_plan.get("id"))
        features = feature_plan.get("features", [])
        if plan_id is None or not isinstance(features, list):
            return {}

        feature_ids = {
            feature["feature_id"]
            for feature in features
            if isinstance(feature, dict) and self._string_value(feature.get("feature_id"))
        }
        graph_feature_ids = {
            feature["graph_id"]: feature["feature_id"]
            for feature in features
            if isinstance(feature, dict)
            and self._string_value(feature.get("feature_id"))
            and self._string_value(feature.get("graph_id"))
        }
        lane_feature_ids = self._graph_lane_feature_ids(graphs, graph_feature_ids)
        lanes_by_feature: dict[str, list[dict[str, Any]]] = {}
        for lane in self._feature_lanes():
            lane_plan_id = self._string_value(lane.get("feature_plan_id"))
            if lane_plan_id is not None and lane_plan_id != plan_id:
                continue
            feature_id = self._string_value(lane.get("plan_feature_id"))
            if feature_id is None:
                feature_id = self._string_value(lane.get("feature_plan_feature_id"))
            if feature_id is None:
                graph_id = self._string_value(lane.get("graph_id"))
                feature_id = graph_feature_ids.get(graph_id) if graph_id is not None else None
            if feature_id is None:
                feature_id = lane_feature_ids.get(self._string_value(lane.get("feature_id")))
            if feature_id in feature_ids:
                lanes_by_feature.setdefault(feature_id, []).append(lane)

        terminal_features = 0
        for lanes in lanes_by_feature.values():
            if lanes and all(normalize_lane_state(lane).is_terminal for lane in lanes):
                terminal_features += 1
        return {
            "projected_features": len(lanes_by_feature),
            "terminal_features": terminal_features,
        }

    def _graph_lane_feature_ids(
        self,
        graphs: list[Any],
        graph_feature_ids: dict[str, str],
    ) -> dict[str, str]:
        lane_feature_ids: dict[str, str] = {}
        for graph in graphs:
            if not isinstance(graph, dict):
                continue
            graph_id = self._string_value(graph.get("id"))
            feature_id = graph_feature_ids.get(graph_id) if graph_id is not None else None
            if feature_id is None:
                continue
            lanes = graph.get("lanes", [])
            if not isinstance(lanes, list):
                continue
            for lane in lanes:
                if not isinstance(lane, dict):
                    continue
                lane_id = self._string_value(lane.get("feature_id"))
                if lane_id is not None:
                    lane_feature_ids[lane_id] = feature_id
        return lane_feature_ids

    def _is_lane_graph_snapshot(self, data: Any) -> bool:
        if not isinstance(data, dict) or self._is_feature_graph_set_snapshot(data):
            return False
        return isinstance(data.get("lanes"), list)

    def _is_feature_graph_set_snapshot(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        feature_plan = data.get("feature_plan")
        if not isinstance(feature_plan, dict):
            return False
        features = feature_plan.get("features")
        graphs = data.get("graphs")
        return isinstance(features, list) and isinstance(graphs, list)

    def _health_summary_card(self, conversation_id: str) -> ChatCard:
        run_health = summarize_run_health(
            self._conversation_scoped_lanes(conversation_id, self._feature_lanes()),
            xmuse_root=self._base_dir,
        )
        return build_run_health_chat_card(
            conversation_id,
            run_health,
            created_at=self._latest_health_timestamp(),
            href=f"/dashboard/peer-chat/conversations/{conversation_id}#run-health",
            api_href=(
                f"/api/dashboard/peer-chat/conversations/{conversation_id}/run-health"
            ),
        )

    def _worklist_summary_card(self, conversation_id: str) -> ChatCard | None:
        counts = self._worklist_counts(conversation_id)
        if not self._has_worklist_signal(counts):
            return None
        failed = counts["failed_lanes"]
        waiting = counts["unread_inbox"] + counts["claimed_inbox"]
        active_lanes = counts["ready_lanes"] + counts["under_review_lanes"]
        return ChatCard(
            id=f"card_worklist_summary_{conversation_id}",
            conversation_id=conversation_id,
            card_type="worklist_summary",
            source_id="worklist",
            title="Worklist summary",
            summary=(
                f"{waiting} inbox items, {active_lanes} active lanes, "
                f"{failed} failed lanes"
            ),
            status="degraded" if failed else "actionable",
            href=f"/dashboard/peer-chat/conversations/{conversation_id}#worklist",
            api_href=f"/api/chat/conversations/{conversation_id}/messages",
            created_at=self._worklist_timestamp(conversation_id),
            counts=counts,
            metadata={},
        )

    def _worklist_counts(self, conversation_id: str) -> dict[str, int]:
        inbox_counts = self._inbox_counts(conversation_id)
        counts = {
            "unread_inbox": inbox_counts["unread"],
            "claimed_inbox": inbox_counts["claimed"],
            "ready_lanes": 0,
            "under_review_lanes": 0,
            "failed_lanes": 0,
            "terminal_lanes": 0,
        }
        for lane in self._conversation_scoped_lanes(conversation_id, self._feature_lanes()):
            normalized = normalize_lane_state(lane)
            if normalized.normalized_status == "ready":
                counts["ready_lanes"] += 1
            elif normalized.normalized_status == "under_review":
                counts["under_review_lanes"] += 1
            if normalized.is_terminal:
                counts["terminal_lanes"] += 1
                if normalized.normalized_status != "merged":
                    counts["failed_lanes"] += 1
        return counts

    def _has_worklist_signal(self, counts: dict[str, int]) -> bool:
        return any(
            counts[key] > 0
            for key in (
                "unread_inbox",
                "claimed_inbox",
                "ready_lanes",
                "under_review_lanes",
                "failed_lanes",
            )
        )

    def _worklist_timestamp(self, conversation_id: str) -> str:
        candidates = [
            item.updated_at
            for item in self._inbox.list_by_conversation(conversation_id)
            if item.updated_at
        ]
        lanes_path = self._base_dir / "feature_lanes.json"
        if lanes_path.exists():
            candidates.append(self._file_timestamp(lanes_path))
        return max(candidates) if candidates else self._latest_health_timestamp()

    def _feature_lanes(self) -> list[dict[str, Any]]:
        lane_data = self._read_json_file(self._base_dir / "feature_lanes.json", {"lanes": []})
        if isinstance(lane_data, dict) and isinstance(lane_data.get("lanes"), list):
            return [lane for lane in lane_data["lanes"] if isinstance(lane, dict)]
        return []

    def _conversation_scoped_lanes(
        self,
        conversation_id: str,
        lanes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return conversation_scoped_lanes(self._base_dir, conversation_id, lanes)

    def _has_health_sources(self) -> bool:
        return any(
            (self._base_dir / name).exists()
            for name in ("feature_lanes.json", "active_sessions.json", "error_knowledge.json")
        )

    def _latest_health_timestamp(self) -> str:
        candidates = [
            self._base_dir / "feature_lanes.json",
            self._base_dir / "active_sessions.json",
            self._base_dir / "error_knowledge.json",
        ]
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return "1970-01-01T00:00:00Z"
        return self._file_timestamp(max(existing, key=lambda path: path.stat().st_mtime))

    def _file_timestamp(self, path: Path) -> str:
        from datetime import UTC, datetime

        return (
            datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _read_json_file(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _json_object(self, raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _string_value(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _compact_text(self, value: str, *, limit: int = 160) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "..."
