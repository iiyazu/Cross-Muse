# xmuse/tui/adapter/xmuse_adapter.py
from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from xmuse_core.platform.dashboard_details import _conversation_runtime_timeline_detail
from xmuse_core.platform.operator_actions import (
    OperatorActionRequest,
    OperatorActionService,
)
from xmuse_core.platform.operator_evidence_actions import (
    build_blocker_navigation_action,
    build_github_truth_action,
    build_memory_trace_action,
    export_deliberation_transcript,
)
from xmuse_core.platform.release_evidence_attempts import (
    run_release_evidence_attempt_action,
)
from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)
from xmuse_core.platform.release_evidence_export_actions import (
    run_release_evidence_export_action,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.platform.tui_vision_read_model import build_tui_vision_read_model
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


@dataclass
class StateDelta:
    messages: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    participants: dict[str, list[dict]] = field(default_factory=dict)
    vision: dict | None = None
    replace_peer_status_cards: bool = False
    features: dict[str, Any] = field(default_factory=dict)
    lanes: list[dict] = field(default_factory=list)
    run_health: dict | None = None
    lanes_changed: bool = False
    errors: dict[str, str] = field(default_factory=dict)


class XmuseAdapter:
    def __init__(
        self,
        xmuse_root: Path,
        *,
        chat_api_base_url: str | None = None,
        chat_api_client_factory: Callable[[float], Any] | None = None,
    ) -> None:
        self._root = xmuse_root
        self._chat_api_base_url = (
            chat_api_base_url
            or os.environ.get("XMUSE_CHAT_API_URL")
            or "http://127.0.0.1:8201"
        ).rstrip("/")
        self._chat_api_client_factory = chat_api_client_factory
        self._last_message_ts: dict[str, str] = {}
        self._last_worklist_fingerprint: dict[str, str | None] = {}
        self._seen_envelope_card_fingerprints: dict[str, set[str]] = {}
        self._seen_poll_card_fingerprints: dict[str, set[str]] = {}
        self._participant_cache: dict[str, dict] = {}
        self._participant_cache_ttl_s = 30

    def poll_messages(self, conv_id: str) -> tuple[list[dict], str | None]:
        try:
            from xmuse_core.chat.store import ChatStore
            store = ChatStore(self._root / "chat.db")
            raw = store.list_messages(conv_id)
            dicts = [
                _display_message_author(self._root, conv_id, m.model_dump(mode="json"))
                for m in raw
                if hasattr(m, "model_dump")
            ]
            active_streams = _active_stream_messages(self._root, conv_id)
            since = self._last_message_ts.get(conv_id, "")
            new = [m for m in dicts if str(m.get("created_at", "")) > since]
            new.extend(active_streams)
            if new:
                non_stream = [
                    str(m.get("created_at", ""))
                    for m in new
                    if not str(m.get("id", "")).startswith("stream_")
                ]
                if non_stream:
                    self._last_message_ts[conv_id] = max(non_stream)
            return new, None
        except Exception as exc:
            return [], str(exc)

    def _message_snapshot(self, conv_id: str) -> list[dict]:
        try:
            from xmuse_core.chat.store import ChatStore

            store = ChatStore(self._root / "chat.db")
            raw = store.list_messages(conv_id)
            dicts = [
                _display_message_author(self._root, conv_id, m.model_dump(mode="json"))
                for m in raw
                if hasattr(m, "model_dump")
            ]
            dicts.extend(_active_stream_messages(self._root, conv_id))
            return dicts
        except Exception:
            return []

    async def poll_worklist_envelope(
        self,
        conv_id: str | None = None,
    ) -> tuple[dict | None, str | None]:
        try:
            from xmuse_core.platform.read_envelopes import build_tui_worklist_envelope

            envelope = await asyncio.to_thread(
                build_tui_worklist_envelope,
                self._root,
                conversation_id=conv_id,
            )
            data = envelope.model_dump(mode="json")
            fingerprint = _worklist_fingerprint(data)
            scope_key = conv_id or "*"
            if fingerprint == self._last_worklist_fingerprint.get(scope_key):
                return None, None
            self._last_worklist_fingerprint[scope_key] = fingerprint
            return data, None
        except Exception as exc:
            return None, str(exc)

    def poll_cards(self, conv_id: str) -> tuple[list[dict], str | None]:
        try:
            from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
            emitter = ChatExecutionCardEmitter(self._root)
            raw = emitter.list_intents(conversation_id=conv_id)
            dicts = [c.model_dump(mode="json") for c in raw if hasattr(c, "model_dump")]
            dicts.extend(_inbox_status_cards(self._root, conv_id))
            dicts.extend(_peer_latency_cards(self._root, conv_id))
            dicts.extend(
                _runtime_closure_cards(
                    self.get_conversation_inspector(conv_id),
                    bootstrap=self.get_bootstrap_status(conv_id),
                )
            )
            return self._new_polled_cards(conv_id, dicts), None
        except Exception as exc:
            return [], str(exc)

    async def poll_delta(self, conv_id: str | None = None) -> StateDelta:
        try:
            msgs, msg_err = self.poll_messages(conv_id) if conv_id else ([], None)
            envelope, envelope_err = await self.poll_worklist_envelope(conv_id)
            cards, card_err = self.poll_cards(conv_id) if conv_id else ([], None)
            participants = {conv_id: self.get_participants(conv_id)} if conv_id else {}
            errors = {
                k: v
                for k, v in {
                    "messages": msg_err,
                    "worklist": envelope_err,
                    "cards": card_err,
                }.items()
                if v
            }
            features = {}
            lanes_list = []
            health = None
            inspector = None
            if envelope is not None:
                items = _worklist_items(envelope)
                if items:
                    lanes_list = items
                    features = _build_features(lanes_list)
                if isinstance(envelope.get("run_health"), dict):
                    health = envelope["run_health"]
                scope_key = conv_id or str(envelope.get("conversation_id") or "*")
                cards = _merge_cards(
                    cards,
                    self._new_envelope_cards(
                        scope_key,
                        _cards_from_envelope(envelope, fallback_conv_id=conv_id),
                    ),
                )
            if conv_id:
                inspector = self.get_conversation_inspector(conv_id)
                health = _merge_runtime_health(
                    health,
                    _runtime_health_from_inspector(inspector),
                )
            vision_messages = self._message_snapshot(conv_id) if conv_id else []
            if not vision_messages and msgs:
                vision_messages = msgs
            vision_envelope = envelope
            if vision_envelope is None:
                vision_envelope = self._worklist_envelope_snapshot(conv_id)
            vision = build_tui_vision_read_model(
                conversation_id=conv_id,
                messages=vision_messages,
                worklist_envelope=vision_envelope,
                inspector=inspector,
            )
            return StateDelta(
                messages=msgs, cards=cards, participants=participants,
                vision=vision,
                features=features, lanes=lanes_list,
                replace_peer_status_cards=bool(conv_id and not card_err),
                run_health=health, lanes_changed=envelope is not None, errors=errors,
            )
        except Exception as exc:
            return StateDelta(errors={"poll_delta": str(exc)})

    async def sync(self, conv_id: str | None = None) -> StateDelta:
        try:
            self._last_message_ts.clear()
            self._last_worklist_fingerprint.clear()
            self._seen_envelope_card_fingerprints.clear()
            self._seen_poll_card_fingerprints.clear()
            return await self.poll_delta(conv_id)
        except Exception as exc:
            return StateDelta(errors={"sync": str(exc)})

    def send_message(self, conv_id: str, author: str, role: str, content: str) -> str | None:
        api_message_id = self._send_message_via_chat_api(conv_id, author, role, content)
        if api_message_id is not None:
            return api_message_id
        try:
            from xmuse_core.chat.store import ChatStore
            store = ChatStore(self._root / "chat.db")
            return store.add_message(conv_id, author, role, content)
        except Exception:
            return None

    def _send_message_via_chat_api(
        self,
        conv_id: str,
        author: str,
        role: str,
        content: str,
    ) -> str | None:
        if not conv_id:
            return None
        payload = {
            "author": author,
            "role": "human" if role in {"user", "human"} else role,
            "content": _default_routed_content(content),
        }
        try:
            with self._chat_api_client(5.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/messages",
                    json=payload,
                    headers=_chat_api_write_headers(),
                )
                response.raise_for_status()
                data = response.json()
            message_id = data.get("id")
            return str(message_id) if message_id else None
        except Exception:
            return None

    def list_conversations(self) -> list[dict]:
        try:
            from xmuse_core.chat.store import ChatStore
            store = ChatStore(self._root / "chat.db")
            raw = store.list_conversations()
            return [c.model_dump(mode="json") for c in raw if hasattr(c, "model_dump")]
        except Exception:
            return []

    def create_group_conversation(
        self,
        title: str,
        *,
        preset_id: str = "architect-review-execute",
        init_mode: str = "proposal_then_approve",
    ) -> dict | None:
        clean_title = title.strip()
        if not clean_title:
            return None
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations",
                    json={
                        "title": clean_title,
                        "preset_id": preset_id,
                        "init_mode": init_mode,
                    },
                    headers=_chat_api_write_headers(),
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def get_bootstrap_status(self, conv_id: str) -> dict | None:
        if not conv_id:
            return None
        try:
            with self._chat_api_client(10.0) as client:
                response = client.get(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/bootstrap/status",
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def get_conversation_inspector(self, conv_id: str) -> dict | None:
        if not conv_id:
            return None
        try:
            with self._chat_api_client(10.0) as client:
                response = client.get(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/inspector",
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def get_conversation_timeline(self, conv_id: str) -> dict | None:
        if not conv_id:
            return None
        try:
            with self._chat_api_client(10.0) as client:
                response = client.get(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/messages",
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            try:
                from xmuse_core.chat.peer_service import PeerChatService

                return PeerChatService(self._root / "chat.db").list_conversation_timeline(conv_id)
            except Exception:
                return None

    def get_lane_detail(
        self,
        lane_id: str,
        *,
        conversation_id: str | None = None,
    ) -> dict | None:
        clean_lane_id = lane_id.strip()
        if not clean_lane_id:
            return None
        envelope = self._worklist_envelope_snapshot(conversation_id)
        items = _worklist_items(envelope or {})
        lane = _find_worklist_item(items, clean_lane_id)
        if lane is None and conversation_id is not None:
            envelope = self._worklist_envelope_snapshot(None)
            items = _worklist_items(envelope or {})
            lane = _find_worklist_item(items, clean_lane_id)
        if lane is None:
            return None

        conv_id = conversation_id or str(lane.get("conversation_id") or "")
        inspector = self.get_conversation_inspector(conv_id) if conv_id else None
        timeline = self.get_conversation_timeline(conv_id) if conv_id else None
        return _build_lane_detail_payload(
            lane,
            envelope=envelope or {},
            inspector=inspector,
            timeline=timeline,
            tui_command_events=self.list_tui_command_events(conv_id or None),
        )

    def run_operator_evidence_action(
        self,
        action: str,
        conv_id: str,
    ) -> dict[str, Any]:
        clean_action = action.strip().lower().replace("-", "_")
        if clean_action in {"transcript", "transcript_export", "export_transcript"}:
            result = export_deliberation_transcript(
                conversation_id=conv_id,
                messages=self._message_snapshot(conv_id),
                artifact_path=self._operator_evidence_artifact_path(
                    conv_id,
                    "transcript.json",
                ),
            )
            return result.model_dump()

        vision = self._operator_vision_snapshot(conv_id)
        if clean_action in {"github", "github_truth", "github_truth_load"}:
            return build_github_truth_action(
                conversation_id=conv_id,
                github=vision.get("github") if isinstance(vision, dict) else None,
            ).model_dump()
        if clean_action in {"memory", "memory_trace", "memory_trace_load"}:
            return build_memory_trace_action(
                conversation_id=conv_id,
                memory=vision.get("memory") if isinstance(vision, dict) else None,
            ).model_dump()
        if clean_action in {"blockers", "blocker", "navigation", "blocker_navigation"}:
            return build_blocker_navigation_action(
                conversation_id=conv_id,
                vision=vision,
            ).model_dump()
        return {
            "action": clean_action or "unknown",
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "fact_state": "manual_gap",
            "conversation_id": conv_id,
            "source_refs": [],
            "target_refs": [],
            "artifact_path": None,
            "manual_gap_reason": f"unknown evidence action: {action}",
            "summary": f"Unknown evidence action: {action}",
            "payload": {},
        }

    def run_operator_control_action(
        self,
        action: str,
        conv_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_action = action.strip().lower().replace("-", "_")
        action_payload = dict(payload or {})
        if conv_id and "conversation_id" not in action_payload:
            action_payload["conversation_id"] = conv_id
        idempotency_key = f"tui:{clean_action}:{uuid.uuid4().hex}"
        headers = _chat_api_write_headers()
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/operator/actions",
                    json={
                        "action": clean_action,
                        "idempotency_key": idempotency_key,
                        "payload": action_payload,
                    },
                    headers=headers,
                )
                status_code = getattr(response, "status_code", 200)
                if isinstance(status_code, int) and status_code >= 400:
                    data = response.json()
                    detail = data.get("detail") if isinstance(data, dict) else None
                    if isinstance(detail, dict) and "status" in detail:
                        return detail
                    return _operator_api_error_result(
                        action=clean_action,
                        actor_id=headers["X-XMuse-Operator-Id"],
                        status_code=status_code,
                        detail=detail,
                    )
                response.raise_for_status()
                data = response.json()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        service = OperatorActionService(
            god_cli_registry=build_default_god_cli_registry(),
            audit_dir=self._root / "work" / "operator_actions",
            registration_store=GodCliRegistrationStore(
                self._root / "god_cli_registrations.json"
            ),
            selection_store=GodCliSelectionStore(self._root / "god_cli_selections.json"),
            lane_state_machine=LaneStateMachine(
                self._root / "feature_lanes.json",
                history_path=self._root / "state_history.json",
            ),
            release_evidence_export_handler=lambda request: run_release_evidence_export_action(
                request,
                xmuse_root=self._root,
                release_readiness_dir=self._root / "work" / "release_readiness",
            ),
            release_evidence_candidate_handler=lambda request: (
                _release_evidence_candidate_report(self._root, request)
            ),
            release_evidence_attempt_handler=lambda request: run_release_evidence_attempt_action(
                request,
                xmuse_root=self._root,
                release_readiness_dir=self._root / "work" / "release_readiness",
            ),
        )
        request = OperatorActionRequest(
            action=clean_action,
            actor_id=_operator_actor_id(),
            capabilities=_operator_capabilities(),
            idempotency_key=idempotency_key,
            payload=action_payload,
            source="tui",
        )
        return service.handle(request).model_dump()

    def ensure_god_room(self, conv_id: str) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="ensure_god_room",
            conv_id=conv_id,
            suffix="",
            payload=None,
        )

    def get_god_room(self, conv_id: str) -> dict[str, Any] | None:
        return self._get_god_room_contract(
            conv_id=conv_id,
            suffix="",
        )

    def get_god_room_snapshot(self, conv_id: str) -> dict[str, Any] | None:
        return self._get_god_room_contract(
            conv_id=conv_id,
            suffix="/snapshot",
        )

    def append_god_room_event(
        self,
        conv_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="append_god_room_event",
            conv_id=conv_id,
            suffix="/events",
            payload=dict(event),
        )

    def freeze_god_room_blueprint(
        self,
        conv_id: str,
        *,
        blueprint_id: str,
        revision: int = 1,
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="freeze_god_room_blueprint",
            conv_id=conv_id,
            suffix="/freeze-blueprint",
            payload={
                "blueprint_id": blueprint_id,
                "revision": revision,
            },
        )

    def build_god_room_lane_dag(
        self,
        conv_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="build_god_room_lane_dag",
            conv_id=conv_id,
            suffix="/lane-dag",
            payload=dict(payload),
        )

    def evaluate_god_room_lane_recovery(
        self,
        conv_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="evaluate_god_room_lane_recovery",
            conv_id=conv_id,
            suffix="/lane-dag/recovery",
            payload=dict(payload),
        )

    def build_god_room_memoryos_plan(
        self,
        conv_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="build_god_room_memoryos_plan",
            conv_id=conv_id,
            suffix="/memoryos-plan",
            payload=dict(payload),
        )

    def build_god_room_speaker_attempt(
        self,
        conv_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="build_god_room_speaker_attempt",
            conv_id=conv_id,
            suffix="/speaker-attempt",
            payload=dict(payload),
        )

    def capture_god_room_speaker_response(
        self,
        conv_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._post_god_room_contract(
            action="capture_god_room_speaker_response",
            conv_id=conv_id,
            suffix="/speaker-response",
            payload=dict(payload),
        )

    def _post_god_room_contract(
        self,
        *,
        action: str,
        conv_id: str,
        suffix: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        clean_conv_id = conv_id.strip()
        headers = _chat_api_write_headers()
        if not clean_conv_id:
            return _operator_api_error_result(
                action=action,
                actor_id=headers["X-XMuse-Operator-Id"],
                status_code=0,
                detail={
                    "code": "missing_conversation_id",
                    "message": "GOD room contract action requires conversation_id",
                },
            )
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    (
                        f"{self._chat_api_base_url}/api/chat/conversations/"
                        f"{clean_conv_id}/god-room{suffix}"
                    ),
                    json=payload,
                    headers=headers,
                )
                status_code = int(getattr(response, "status_code", 200) or 200)
                if status_code >= 400:
                    detail = _response_detail(response)
                    return _operator_api_error_result(
                        action=action,
                        actor_id=headers["X-XMuse-Operator-Id"],
                        status_code=status_code,
                        detail=detail,
                    )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:
            return _operator_api_error_result(
                action=action,
                actor_id=headers["X-XMuse-Operator-Id"],
                status_code=0,
                detail={"code": "request_failed", "message": str(exc)},
            )

    def _get_god_room_contract(
        self,
        *,
        conv_id: str,
        suffix: str,
    ) -> dict[str, Any] | None:
        clean_conv_id = conv_id.strip()
        if not clean_conv_id:
            return None
        try:
            with self._chat_api_client(10.0) as client:
                response = client.get(
                    (
                        f"{self._chat_api_base_url}/api/chat/conversations/"
                        f"{clean_conv_id}/god-room{suffix}"
                    ),
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _operator_vision_snapshot(self, conv_id: str) -> dict[str, Any]:
        inspector = self.get_conversation_inspector(conv_id)
        return build_tui_vision_read_model(
            conversation_id=conv_id,
            messages=self._message_snapshot(conv_id),
            worklist_envelope=self._worklist_envelope_snapshot(conv_id),
            inspector=inspector,
        )

    def _operator_evidence_artifact_path(self, conv_id: str, filename: str) -> Path:
        safe_conv_id = _safe_path_segment(conv_id)
        return self._root / "work" / "operator_evidence" / safe_conv_id / filename

    def _worklist_envelope_snapshot(self, conv_id: str | None = None) -> dict | None:
        try:
            from xmuse_core.platform.read_envelopes import build_tui_worklist_envelope

            envelope = build_tui_worklist_envelope(
                self._root,
                conversation_id=conv_id,
            )
            return envelope.model_dump(mode="json")
        except Exception:
            return None

    def create_bootstrap_proposal(self, conv_id: str) -> dict | None:
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/bootstrap/proposals",
                    json={"source": "deterministic"},
                    headers=_chat_api_write_headers(),
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def apply_bootstrap_proposal(self, conv_id: str, proposal_id: str) -> dict | None:
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/bootstrap/apply",
                    json={"proposal_id": proposal_id},
                    headers=_chat_api_write_headers(),
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def approve_proposal(
        self,
        proposal_id: str,
        *,
        approved_by: str = "human",
        approval_mode: str = "manual",
        goal_summary: str | None = None,
    ) -> dict | None:
        clean_proposal_id = proposal_id.strip()
        if not clean_proposal_id:
            return None
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/proposals/{clean_proposal_id}/approve",
                    json={
                        "approved_by": [approved_by],
                        "approval_mode": approval_mode,
                        "goal_summary": (
                            goal_summary
                            or f"Approve xmuse chat proposal {clean_proposal_id}"
                        ),
                    },
                    headers=_chat_api_write_headers(),
                )
                if response.status_code >= 400:
                    try:
                        detail = response.json().get("detail")
                    except Exception:
                        detail = response.text
                    return {
                        "error": detail,
                        "status_code": response.status_code,
                        "proposal_id": clean_proposal_id,
                    }
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:
            return {
                "error": {"code": "request_failed", "message": str(exc)},
                "proposal_id": clean_proposal_id,
            }

    def record_tui_command_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        normalized = _normalize_tui_command_event(event)
        if normalized is None:
            return None
        path = self._tui_command_events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _read_json_file(path, default={"command_events": []})
        events = payload.get("command_events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            events = []
        events.append(normalized)
        if len(events) > 500:
            events = events[-500:]
        path.write_text(
            json.dumps({"command_events": events}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalized

    def list_tui_command_events(self, conv_id: str | None = None) -> list[dict[str, Any]]:
        payload = _read_json_file(self._tui_command_events_path(), default={"command_events": []})
        events = payload.get("command_events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            return []
        rows = [event for event in events if isinstance(event, dict)]
        if conv_id is None:
            return rows
        return [
            event
            for event in rows
            if str(event.get("conversation_id") or "") == conv_id
        ]

    def _tui_command_events_path(self) -> Path:
        return self._root / "tui_command_events.json"

    def list_group_conversations(self) -> list[dict]:
        return [
            conversation
            for conversation in self.list_conversations()
            if self._is_user_group_conversation(str(conversation.get("id", "")))
        ]

    def list_archived_conversations(self) -> list[dict]:
        return [
            conversation
            for conversation in self.list_conversations()
            if not self._is_user_group_conversation(str(conversation.get("id", "")))
        ]

    def _is_user_group_conversation(self, conv_id: str) -> bool:
        if not conv_id:
            return False
        roles = {
            participant.get("role")
            for participant in self.get_participants(conv_id)
            if isinstance(participant, dict)
        }
        return {"architect", "review", "execute"}.issubset(roles)

    def get_participants(self, conv_id: str) -> list[dict]:
        cached = self._participant_cache.get(conv_id)
        if cached is not None and _now_s() < cached["expires_at"]:
            return cached["participants"]
        api_participants = self._get_participants_via_chat_api(conv_id)
        if api_participants is not None:
            self._set_participant_cache(conv_id, api_participants)
            return api_participants
        try:
            from xmuse_core.chat.participant_store import ParticipantStore
            store = ParticipantStore(self._root / "chat.db")
            parts = [p.model_dump(mode="json") for p in store.list_by_conversation(conv_id)]
            self._set_participant_cache(conv_id, parts)
            return parts
        except Exception:
            return []

    def _get_participants_via_chat_api(self, conv_id: str) -> list[dict] | None:
        if not conv_id:
            return None
        try:
            with self._chat_api_client(5.0) as client:
                response = client.get(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/participants",
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            return None
        participants = data.get("participants") if isinstance(data, dict) else None
        if not isinstance(participants, list):
            return []
        return [item for item in participants if isinstance(item, dict)]

    def _set_participant_cache(self, conv_id: str, participants: list[dict]) -> None:
        self._participant_cache[conv_id] = {
            "participants": participants,
            "expires_at": _now_s() + self._participant_cache_ttl_s,
        }

    def refresh_participants(self, conv_id: str) -> list[dict]:
        self._participant_cache.pop(conv_id, None)
        return self.get_participants(conv_id)

    def add_participant(
        self,
        conv_id: str,
        role: str,
        *,
        display_name: str | None = None,
        model: str | None = None,
        role_template_id: str | None = None,
    ) -> dict | None:
        clean_role = role.strip()
        if not conv_id or not clean_role:
            return None
        payload = {"role": clean_role}
        if display_name:
            payload["display_name"] = display_name.strip()
        if model:
            payload["model"] = model.strip()
        if role_template_id:
            payload["role_template_id"] = role_template_id.strip()
        try:
            with self._chat_api_client(10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/participants",
                    json=payload,
                    headers=_chat_api_write_headers(),
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def remove_participant(self, conv_id: str, role_or_participant_id: str) -> bool:
        target = role_or_participant_id.strip()
        if not conv_id or not target:
            return False
        participant_id = self._resolve_participant_id(conv_id, target)
        if not participant_id:
            return False
        try:
            with self._chat_api_client(10.0) as client:
                response = client.delete(
                    f"{self._chat_api_base_url}/api/chat/conversations/"
                    f"{conv_id}/participants/{participant_id}",
                    headers=_chat_api_write_headers(),
                )
                response.raise_for_status()
            return True
        except Exception:
            return False

    def _resolve_participant_id(self, conv_id: str, target: str) -> str | None:
        participants = self.get_participants(conv_id)
        for participant in participants:
            participant_id = participant.get("participant_id") or participant.get("id")
            if isinstance(participant_id, str) and participant_id == target:
                return participant_id
        matches = [
            participant
            for participant in participants
            if str(participant.get("role") or "") == target
        ]
        if len(matches) != 1:
            return None
        participant_id = matches[0].get("participant_id") or matches[0].get("id")
        return str(participant_id) if participant_id else None

    def list_role_templates(self) -> list[dict]:
        try:
            with self._chat_api_client(5.0) as client:
                response = client.get(f"{self._chat_api_base_url}/api/chat/role-templates")
                response.raise_for_status()
                data = response.json()
        except Exception:
            return []
        templates = data.get("role_templates") if isinstance(data, dict) else None
        if not isinstance(templates, list):
            return []
        return [item for item in templates if isinstance(item, dict)]

    def _chat_api_client(self, timeout: float):
        if self._chat_api_client_factory is not None:
            return self._chat_api_client_factory(timeout)
        return httpx.Client(timeout=timeout)

    def get_lane(self, lane_id: str) -> dict | None:
        """Get a lane by its feature_id (canonical lane identifier in projection)."""
        try:
            from xmuse_core.platform.projection.syncer import LaneProjectionSyncer
            syncer = LaneProjectionSyncer(self._root / "feature_lanes.json")
            data = syncer.read()
            for lane in data.get("lanes", []):
                if lane.get("feature_id") == lane_id:
                    return lane
            return None
        except Exception:
            return None

    def get_workbench_lane_detail(
        self,
        conv_id: str | None,
        lane_id: str,
    ) -> dict[str, Any] | None:
        clean_lane_id = lane_id.strip()
        if not clean_lane_id:
            return None
        task = self._workbench_task(conv_id, clean_lane_id)
        if task is None:
            return None
        execution_events = self._workbench_execution_events(conv_id)
        return {
            "conversation_id": conv_id,
            "lane_id": clean_lane_id,
            "source_authority": "tui_worklist_envelope",
            "task": task,
            "execution_log": {
                "source_authority": "dashboard_runtime_timeline+tui_command_events",
                "events": execution_events,
            },
        }

    def get_feature_graph(self, graph_id: str) -> dict | None:
        try:
            from xmuse_core.structuring.graph_store import LaneGraphStore
            store = LaneGraphStore(self._root / "lane_graphs")
            graph = store.get(graph_id)
            return graph.model_dump(mode="json")
        except Exception:
            return None

    def get_planning_run(self, run_id: str) -> dict | None:
        return None

    def get_provider_inventory(self) -> list[dict]:
        try:
            from xmuse_core.platform.provider_read_contracts import build_provider_inventory

            inventory = build_provider_inventory()
        except Exception:
            return []
        providers = inventory.get("providers") if isinstance(inventory, dict) else None
        if not isinstance(providers, list):
            return []
        rows: list[dict] = []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            profiles = provider.get("profiles")
            if not isinstance(profiles, list):
                continue
            rows.extend(
                _provider_inventory_row(profile)
                for profile in profiles
                if isinstance(profile, dict)
            )
        rows.extend(
            _god_cli_registration_inventory_row(registration)
            for registration in GodCliRegistrationStore(
                self._root / "god_cli_registrations.json"
            ).list_registrations()
        )
        return rows

    def _new_envelope_cards(self, scope_key: str, cards: list[dict]) -> list[dict]:
        seen = self._seen_envelope_card_fingerprints.setdefault(scope_key, set())
        new_cards: list[dict] = []
        for card in cards:
            fingerprint = json.dumps(card, sort_keys=True, separators=(",", ":"))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            new_cards.append(card)
        return new_cards

    def _new_polled_cards(self, conv_id: str, cards: list[dict]) -> list[dict]:
        seen = self._seen_poll_card_fingerprints.setdefault(conv_id, set())
        new_cards: list[dict] = []
        for card in cards:
            fingerprint = json.dumps(card, sort_keys=True, separators=(",", ":"))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            new_cards.append(card)
        return new_cards

    def _workbench_task(
        self,
        conv_id: str | None,
        lane_id: str,
    ) -> dict[str, Any] | None:
        try:
            from xmuse_core.platform import read_envelopes

            envelope = read_envelopes.build_tui_worklist_envelope(
                self._root,
                conversation_id=conv_id,
            )
            data = (
                envelope.model_dump(mode="json")
                if hasattr(envelope, "model_dump")
                else envelope
            )
            if not isinstance(data, dict):
                return None
        except Exception:
            return None
        for item in _worklist_items(data):
            item_lane_id = str(
                item.get("lane_id")
                or item.get("feature_id")
                or item.get("lane_local_id")
                or ""
            )
            if item_lane_id == lane_id:
                return item
        return None

    def _workbench_execution_events(self, conv_id: str | None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if conv_id:
            try:
                timeline = _conversation_runtime_timeline_detail(self._root, conv_id)
                raw_events = timeline.get("events") if isinstance(timeline, dict) else None
                if isinstance(raw_events, list):
                    events.extend(
                        event for event in raw_events if isinstance(event, dict)
                    )
            except Exception:
                pass
            for event in self.list_tui_command_events(conv_id):
                command = str(event.get("command") or "").strip()
                events.append(
                    {
                        "event_id": str(event.get("event_id") or f"cmd-{command}"),
                        "event_type": "tui_command",
                        "title": command or "TUI command",
                        "summary": (
                            f"{event.get('read_surface_authority', 'chat_inspector')}"
                            f" -> {event.get('surface_ref', '')}"
                        ),
                        "status": "observed",
                        "created_at": str(event.get("created_at") or ""),
                    }
                )
        events.sort(key=lambda event: str(event.get("created_at") or ""))
        return events


def _build_features(lanes: list[dict]) -> dict[str, Any]:
    features: dict[str, dict] = {}
    for lane in lanes:
        fid = (
            lane.get("feature_plan_feature_id")
            or lane.get("plan_feature_id")
            or lane.get("feature_group")
            or "?"
        )
        if fid not in features:
            features[fid] = {"feature_id": fid, "total": 0, "merged": 0, "lanes": []}
        features[fid]["total"] += 1
        if lane.get("effective_status") == "merged" or lane.get("status") == "merged":
            features[fid]["merged"] += 1
        features[fid]["lanes"].append(lane)
    return features


def _provider_inventory_row(profile: dict[str, Any]) -> dict[str, Any]:
    provider_id = _clean_text(profile.get("provider_id")) or "unknown"
    profile_id = _clean_text(profile.get("profile_id")) or "unknown"
    adapter_kind = _clean_text(profile.get("adapter_kind")) or "unknown"
    persistent_capability = _clean_text(profile.get("persistent_capability"))
    return {
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_profile_ref": _clean_text(profile.get("ref")),
        "capabilities": _string_values(profile.get("task_capabilities")),
        "runtime_kind": adapter_kind,
        "transport": "cli" if adapter_kind.endswith("_cli") else adapter_kind,
        "session_continuity": (
            "persistent_supported"
            if persistent_capability == "supported"
            else "bounded"
        ),
        "heartbeat": "manual_gap",
        "waiting_reason": _provider_waiting_reason(provider_id),
        "proof_level": "contract_proof",
        "boundary_role": _provider_boundary_role(provider_id, profile_id),
        "support_level": _clean_text(profile.get("support_level")),
        "model_id": _clean_text(profile.get("model_id")),
    }


def _god_cli_registration_inventory_row(registration: Any) -> dict[str, Any]:
    capabilities = [
        str(getattr(capability, "value", capability))
        for capability in getattr(registration, "capabilities", ())
    ]
    provider_profile_ref = _clean_text(getattr(registration, "provider_profile_ref", None))
    profile_id = _profile_id_from_ref(provider_profile_ref) or registration.cli_id
    return {
        "provider_id": registration.command_family,
        "profile_id": profile_id,
        "provider_profile_ref": provider_profile_ref,
        "capabilities": capabilities,
        "runtime_kind": registration.command_family,
        "transport": "cli",
        "session_continuity": (
            "persistent_supported"
            if registration.supports_persistent_sessions
            else "bounded"
        ),
        "heartbeat": "manual_gap",
        "waiting_reason": "manual GOD CLI registration; runtime heartbeat unavailable",
        "proof_level": registration.proof_level,
        "boundary_role": (
            "manual_registered_peer_god"
            if "peer_god" in capabilities
            else "manual_registered_support"
        ),
        "support_level": "manual",
        "model_id": None,
        "registration_kind": registration.registration_kind,
        "source_authority": registration.source_authority,
    }


def _provider_boundary_role(provider_id: str, profile_id: str) -> str:
    if provider_id == "codex" and profile_id in {"default", "god"}:
        return "production_groupchat_god"
    if provider_id == "codex":
        return "production_support"
    if provider_id == "opencode":
        return "bounded_secondary"
    return "manual_gap"


def _provider_waiting_reason(provider_id: str) -> str:
    if provider_id == "opencode":
        return "secondary bounded worker"
    return "static provider inventory; runtime heartbeat unavailable"


def _profile_id_from_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    _provider, sep, profile = ref.partition(".")
    return profile if sep and profile else None


def _string_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _release_evidence_candidate_report(
    root: Path,
    request: OperatorActionRequest,
) -> dict[str, Any]:
    return build_release_evidence_candidate_report(
        root,
        conversation_id=_clean_text(request.payload.get("conversation_id")),
        memoryos_payload=request.payload,
        trace_limit=_int_payload(request.payload.get("trace_limit"), default=20),
    )


def _int_payload(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _safe_path_segment(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in value.strip()
    )
    return cleaned or "unknown"


def _worklist_items(envelope: dict[str, Any]) -> list[dict]:
    items = envelope.get("items")
    if isinstance(items, list):
        compact_items = [item for item in items if isinstance(item, dict)]
        if compact_items:
            return compact_items
    worklist = envelope.get("worklist")
    if isinstance(worklist, list):
        return [item for item in worklist if isinstance(item, dict)]
    return []


def _find_worklist_item(items: list[dict], lane_id: str) -> dict | None:
    for item in items:
        ids = {
            str(item.get("lane_id") or ""),
            str(item.get("lane_local_id") or ""),
            str(item.get("feature_id") or ""),
        }
        if lane_id in ids:
            return item
    return None


def _build_lane_detail_payload(
    lane: dict,
    *,
    envelope: dict,
    inspector: dict | None,
    timeline: dict | None,
    tui_command_events: list[dict],
) -> dict:
    lane_id = str(lane.get("lane_id") or lane.get("feature_id") or "?")
    detail = {
        "lane_id": lane_id,
        "lane_local_id": lane.get("lane_local_id") or lane_id,
        "plan_feature_id": lane.get("plan_feature_id") or "?",
        "feature_label": lane.get("feature_label") or lane.get("title") or lane_id,
        "effective_status": lane.get("effective_status") or lane.get("status") or "?",
        "ready": bool(lane.get("ready")),
        "blocked": bool(lane.get("blocked")),
        "rework": bool(lane.get("rework")),
        "priority": lane.get("priority", 0),
        "prompt_summary": lane.get("prompt_summary") or "",
        "debug_refs": lane.get("debug_refs") if isinstance(lane.get("debug_refs"), dict) else {},
        "source_authority": envelope.get("source_authority") or "tui_worklist_envelope",
        "run_health": (
            envelope.get("run_health")
            if isinstance(envelope.get("run_health"), dict)
            else {}
        ),
        "graph_lineage": (
            envelope.get("graph_lineage")
            if isinstance(envelope.get("graph_lineage"), dict)
            else {}
        ),
        "inspector_summary": _lane_inspector_summary(inspector),
        "timeline_cards": _timeline_cards_for_lane(timeline, lane_id),
        "execution_log": _lane_execution_log_lines(
            lane,
            envelope=envelope,
            inspector=inspector,
            timeline=timeline,
            tui_command_events=tui_command_events,
        ),
    }
    return detail


def _lane_inspector_summary(inspector: dict | None) -> dict:
    if not isinstance(inspector, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "session_health",
        "graph_worklist",
        "degradation",
        "dispatch_queue",
        "blockers",
        "peer_latency",
    ):
        value = inspector.get(key)
        if isinstance(value, dict):
            summary[key] = value
    return summary


def _timeline_cards_for_lane(timeline: dict | None, lane_id: str) -> list[dict]:
    if not isinstance(timeline, dict):
        return []
    cards = timeline.get("cards")
    if not isinstance(cards, list):
        return []
    matched: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        blob = json.dumps(card, sort_keys=True, ensure_ascii=False, default=str)
        if lane_id in blob:
            matched.append(card)
    return matched


def _lane_execution_log_lines(
    lane: dict,
    *,
    envelope: dict,
    inspector: dict | None,
    timeline: dict | None,
    tui_command_events: list[dict],
) -> list[str]:
    lane_id = str(lane.get("lane_id") or lane.get("feature_id") or "?")
    lines = [
        f"lane {lane_id}",
        f"status {lane.get('effective_status') or lane.get('status') or '?'}",
    ]
    if lane.get("prompt_summary"):
        lines.append(f"prompt {lane['prompt_summary']}")
    counts = envelope.get("run_health", {}).get("counts") if isinstance(envelope, dict) else None
    if isinstance(counts, dict):
        compact = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        if compact:
            lines.append(f"run_health {compact}")
    graph_lineage = envelope.get("graph_lineage") if isinstance(envelope, dict) else None
    if isinstance(graph_lineage, dict) and graph_lineage.get("authoritative_graph_id"):
        lines.append(f"graph {graph_lineage['authoritative_graph_id']}")
    if isinstance(inspector, dict):
        degradation = inspector.get("degradation")
        if isinstance(degradation, dict):
            lines.append(f"degradation errors={degradation.get('error_count', 0)}")
        dispatch_queue = inspector.get("dispatch_queue")
        if isinstance(dispatch_queue, dict):
            lines.append(
                "dispatch_queue "
                f"queued={dispatch_queue.get('queued', 0)} "
                f"processing={dispatch_queue.get('processing', 0)} "
                f"failed={dispatch_queue.get('failed', 0)}"
            )
        peer_latency = inspector.get("peer_latency")
        turns = peer_latency.get("recent_turns") if isinstance(peer_latency, dict) else None
        if isinstance(turns, list) and turns:
            latest = turns[0] if isinstance(turns[0], dict) else {}
            if latest:
                lines.append(
                    "peer_latency "
                    f"role={latest.get('target_role') or latest.get('role') or '?'} "
                    f"delivery={latest.get('delivery_mode') or '?'}"
                )
    if isinstance(timeline, dict):
        items = timeline.get("items")
        if isinstance(items, list):
            lines.append(f"timeline_items {len(items)}")
    for event in tui_command_events[-3:]:
        command = str(event.get("command") or "").strip()
        authority = str(event.get("read_surface_authority") or "").strip()
        if command and authority:
            lines.append(f"tui_command {command} via {authority}")
    return lines


def _inbox_status_cards(root: Path, conv_id: str) -> list[dict]:
    try:
        from xmuse_core.chat.inbox_store import ChatInboxStore
        from xmuse_core.chat.participant_store import ParticipantStore

        inbox = ChatInboxStore(root / "chat.db")
        participants = ParticipantStore(root / "chat.db")
        cards: list[dict] = []
        for item in inbox.list_by_conversation(conv_id):
            participant = (
                participants.get(item.target_participant_id)
                if item.target_participant_id
                else None
            )
            display_name = (
                participant.display_name
                if participant is not None and participant.display_name
                else item.target_role
                or item.target_address
            )
            title_name = _title_name(display_name)
            card_type = "peer_pending" if item.status == "claimed" else "peer_route_status"
            status = "pending" if item.status == "claimed" else "routed"
            id_status = "pending" if item.status == "claimed" else "route"
            title = (
                f"{title_name} is thinking"
                if item.status == "claimed"
                else f"Routed to {title_name}"
            )
            summary = (
                f"{title_name} 正在处理这条消息。"
                if item.status == "claimed"
                else f"已路由给 {title_name}，等待处理。"
            )
            cards.append(
                {
                    "id": f"card_inbox_{id_status}_{item.id}",
                    "conversation_id": item.conversation_id,
                    "card_type": card_type,
                    "source_id": item.id,
                    "title": title,
                    "summary": summary,
                    "status": status,
                    "href": (
                        f"/dashboard/peer-chat/conversations/{item.conversation_id}"
                        f"#inbox-{item.id}"
                    ),
                    "api_href": f"/api/chat/conversations/{item.conversation_id}/messages",
                    "created_at": item.updated_at,
                    "counts": {"nudge_count": int(item.nudge_count or 0)},
                    "metadata": {
                        "target_role": item.target_role or "",
                        "target_participant_id": item.target_participant_id or "",
                        "source_message_id": item.source_message_id,
                    },
                }
            )
        return cards
    except Exception:
        return []


def _peer_latency_cards(root: Path, conv_id: str) -> list[dict]:
    try:
        from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore

        traces = PeerTurnLatencyTraceStore(root / "chat.db").list_recent(conv_id, limit=10)
    except Exception:
        return []
    cards: list[dict] = []
    for trace in traces:
        degraded_reason = trace.get("degraded_reason")
        if not degraded_reason:
            continue
        target_role = str(trace.get("target_role") or "")
        participant_id = str(trace.get("participant_id") or "")
        display_name = _display_author_from_participants(root, conv_id, participant_id)
        title_name = _title_name(display_name or target_role or "GOD")
        total_latency_ms = int(trace.get("total_latency_ms") or 0)
        inbox_item_id = str(trace.get("inbox_item_id") or trace.get("id") or "?")
        delivery_mode = str(trace.get("delivery_mode") or "unknown")
        cards.append(
            {
                "id": f"card_peer_latency_{inbox_item_id}",
                "conversation_id": conv_id,
                "card_type": "peer_latency",
                "source_id": inbox_item_id,
                "title": f"{title_name} degraded",
                "summary": f"{degraded_reason} in {total_latency_ms}ms",
                "status": "degraded",
                "href": f"/dashboard/peer-chat/conversations/{conv_id}#latency-{inbox_item_id}",
                "api_href": f"/api/dashboard/peer-chat/conversations/{conv_id}/inspector",
                "created_at": trace.get("writeback_at"),
                "counts": {"total_latency_ms": total_latency_ms},
                "metadata": {
                    "delivery_mode": delivery_mode,
                    "degraded_reason": degraded_reason,
                    "target_role": target_role,
                    "participant_id": participant_id,
                },
            }
        )
    return cards


def _runtime_closure_cards(inspector: dict | None, *, bootstrap: dict | None = None) -> list[dict]:
    conv_id = _runtime_conversation_id(inspector, bootstrap)
    if not conv_id:
        return []
    api_href = f"/api/chat/conversations/{conv_id}/inspector"
    href = f"/dashboard/peer-chat/conversations/{conv_id}#runtime"
    cards: list[dict] = []

    if isinstance(bootstrap, dict):
        status = str(bootstrap.get("status") or "").strip()
        if status:
            preset = str(bootstrap.get("preset_id") or "unknown").strip() or "unknown"
            plan = _string_list(bootstrap.get("participant_plan"))
            team = "/".join(plan) if plan else "pending"
            created_at = _timestamp(bootstrap, "updated_at", "created_at") or "0"
            cards.append(
                _runtime_card(
                    conv_id=conv_id,
                    card_type="runtime_bootstrap",
                    source_id=str(
                        bootstrap.get("draft_id")
                        or bootstrap.get("proposal_id")
                        or conv_id
                    ),
                    title="Bootstrap",
                    summary=f"{status} preset={preset} team={team}",
                    status=status,
                    created_at=created_at,
                    href=href,
                    api_href=api_href,
                    metadata={"preset_id": preset, "participant_plan": plan},
                )
            )

    collaboration = inspector.get("collaboration") if isinstance(inspector, dict) else None
    if isinstance(collaboration, dict):
        run = _latest_row(collaboration.get("runs"))
        if run is not None:
            run_id = str(run.get("run_id") or "?")
            status = str(run.get("status") or "?")
            mode = str(run.get("orchestration_mode") or "?")
            targets = _string_list(run.get("targets"))
            target_text = ", ".join(targets) if targets else "none"
            responses = int(run.get("response_count") or 0)
            blockers = int(run.get("blocker_count") or 0)
            cards.append(
                _runtime_card(
                    conv_id=conv_id,
                    card_type="runtime_discussion",
                    source_id=run_id,
                    title="Discussion run",
                    summary=(
                        f"{run_id} {status} {mode} targets={target_text} "
                        f"responses={responses} blockers={blockers}"
                    ),
                    status=status,
                    created_at=_timestamp(run, "updated_at", "created_at") or "0",
                    href=href,
                    api_href=api_href,
                    metadata={"run_id": run_id, "targets": targets, "orchestration_mode": mode},
                )
            )
        gate = _latest_row(collaboration.get("dispatch_gates"))
        if gate is not None:
            event_id = str(gate.get("event_id") or "?")
            run_id = str(gate.get("run_id") or "?")
            decision = str(gate.get("decision") or "?")
            proposal_ref = str(gate.get("proposal_ref") or "").strip()
            artifact_ref = str(gate.get("artifact_ref") or "").strip()
            suffix = " ".join(ref for ref in (proposal_ref, artifact_ref) if ref)
            summary = f"{event_id} {run_id} {decision}"
            if suffix:
                summary = f"{summary} {suffix}"
            cards.append(
                _runtime_card(
                    conv_id=conv_id,
                    card_type="runtime_dispatch_gate",
                    source_id=event_id,
                    title="Dispatch gate",
                    summary=summary,
                    status=decision,
                    created_at=_timestamp(gate, "created_at", "updated_at") or "0",
                    href=href,
                    api_href=api_href,
                    metadata={
                        "event_id": event_id,
                        "run_id": run_id,
                        "proposal_ref": proposal_ref,
                        "artifact_ref": artifact_ref,
                    },
                )
            )

    blockers = inspector.get("blockers") if isinstance(inspector, dict) else None
    if isinstance(blockers, dict):
        active = [
            item for item in _dict_rows(blockers.get("items"))
            if bool(item.get("active"))
        ]
        blocker = _latest_row(active)
        if blocker is not None:
            blocker_id = str(blocker.get("blocker_id") or "?")
            severity = str(blocker.get("severity") or "?")
            issuer = str(blocker.get("issuer") or "?")
            reason = str(blocker.get("reason") or "").strip()
            blocks_dispatch = bool(blocker.get("blocks_dispatch"))
            status = "blocked" if blocks_dispatch else severity
            summary = f"{blocker_id} {severity} {issuer}"
            if blocks_dispatch:
                summary = f"{summary} dispatch-blocking"
            if reason:
                summary = f"{summary}: {reason}"
            cards.append(
                _runtime_card(
                    conv_id=conv_id,
                    card_type="runtime_blocker",
                    source_id=blocker_id,
                    title="Active blocker",
                    summary=summary,
                    status=status,
                    created_at=_timestamp(blocker, "updated_at", "created_at") or "0",
                    href=href,
                    api_href=api_href,
                    metadata={
                        "blocker_id": blocker_id,
                        "run_id": blocker.get("run_id"),
                        "issuer": issuer,
                        "severity": severity,
                        "blocks_dispatch": blocks_dispatch,
                    },
                )
            )

    queue = inspector.get("dispatch_queue") if isinstance(inspector, dict) else None
    latest_dispatch = _latest_row(queue.get("entries")) if isinstance(queue, dict) else None
    if latest_dispatch is not None:
        entry_id = str(latest_dispatch.get("entry_id") or "?")
        status = str(latest_dispatch.get("status") or "?")
        source = str(latest_dispatch.get("source") or "?")
        target = str(latest_dispatch.get("target") or "?")
        auto = " auto" if bool(latest_dispatch.get("auto_execute")) else ""
        provider_ref = str(
            latest_dispatch.get("provider_run_ref")
            or latest_dispatch.get("failure_reason")
            or ""
        ).strip()
        summary = f"{entry_id} {status} {source} target={target}{auto}"
        if provider_ref:
            summary = f"{summary} {provider_ref}"
        cards.append(
            _runtime_card(
                conv_id=conv_id,
                card_type="runtime_dispatch_queue",
                source_id=entry_id,
                title="Dispatch queue",
                summary=summary,
                status=status,
                created_at=(
                    _timestamp(latest_dispatch, "updated_at", "completed_at", "created_at")
                    or "0"
                ),
                href=href,
                api_href=api_href,
                metadata={
                    "entry_id": entry_id,
                    "source": source,
                    "target": target,
                    "auto_execute": bool(latest_dispatch.get("auto_execute")),
                    "dispatch_evidence": latest_dispatch.get("dispatch_evidence"),
                },
            )
        )
        writeback = _correlated_writeback(inspector, latest_dispatch)
        if writeback is not None:
            inbox_id = str(writeback.get("inbox_item_id") or "")
            mode = str(writeback.get("delivery_mode") or "unknown")
            role = str(writeback.get("target_role") or "?")
            reason = str(writeback.get("degraded_reason") or "").strip()
            summary = f"{mode} {role} evidence={inbox_id}"
            if reason:
                summary = f"{summary} degraded={reason}"
            cards.append(
                _runtime_card(
                    conv_id=conv_id,
                    card_type="runtime_provider_writeback",
                    source_id=inbox_id or entry_id,
                    title="Provider writeback",
                    summary=summary,
                    status=mode if not reason else "degraded",
                    created_at=_timestamp(writeback, "writeback_at", "created_at") or "0",
                    href=href,
                    api_href=api_href,
                    metadata={
                        "inbox_item_id": inbox_id,
                        "delivery_mode": mode,
                        "target_role": role,
                        "dispatch_queue_entry_id": entry_id,
                    },
                )
            )
    order = {
        "runtime_bootstrap": 0,
        "runtime_discussion": 1,
        "runtime_blocker": 2,
        "runtime_dispatch_gate": 3,
        "runtime_dispatch_queue": 4,
        "runtime_provider_writeback": 5,
    }
    return sorted(cards, key=lambda card: order.get(str(card.get("card_type")), 99))


def _runtime_card(
    *,
    conv_id: str,
    card_type: str,
    source_id: str,
    title: str,
    summary: str,
    status: str,
    created_at: Any,
    href: str,
    api_href: str,
    metadata: dict,
) -> dict:
    return {
        "id": f"card_{card_type}_{source_id}",
        "conversation_id": conv_id,
        "card_type": card_type,
        "source_id": source_id,
        "title": title,
        "summary": summary,
        "status": status,
        "href": href,
        "api_href": api_href,
        "created_at": created_at,
        "metadata": metadata,
    }


def _runtime_conversation_id(inspector: dict | None, bootstrap: dict | None) -> str:
    if isinstance(inspector, dict):
        conversation = inspector.get("conversation")
        if isinstance(conversation, dict):
            conv_id = conversation.get("id")
            if isinstance(conv_id, str) and conv_id.strip():
                return conv_id.strip()
    if isinstance(bootstrap, dict):
        conv_id = bootstrap.get("conversation_id")
        if isinstance(conv_id, str) and conv_id.strip():
            return conv_id.strip()
    return ""


def _dict_rows(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _latest_row(value: Any) -> dict | None:
    rows = _dict_rows(value)
    if not rows:
        return None
    return max(
        enumerate(rows),
        key=lambda item: (
            _timestamp(item[1], "updated_at", "completed_at", "created_at") or "",
            -item[0],
        ),
    )[1]


def _timestamp(row: dict, *fields: str) -> Any:
    for name in fields:
        value = row.get(name)
        if value is not None and str(value):
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _correlated_writeback(inspector: dict | None, entry: dict) -> dict | None:
    inbox_id = _mcp_writeback_inbox_id(entry)
    if not inbox_id or not isinstance(inspector, dict):
        return None
    latency = inspector.get("peer_latency")
    turns = latency.get("recent_turns") if isinstance(latency, dict) else None
    for turn in _dict_rows(turns):
        if str(turn.get("inbox_item_id") or "") == inbox_id:
            return turn
    return None


def _mcp_writeback_inbox_id(entry: dict) -> str | None:
    evidence = str(entry.get("dispatch_evidence") or "")
    prefix = "mcp_writeback:"
    if not evidence.startswith(prefix):
        return None
    inbox_id = evidence.removeprefix(prefix).strip()
    return inbox_id or None


def _title_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "GOD"
    parts = []
    for part in cleaned.replace("_", " ").replace("-", " ").split():
        if part.lower() == "god":
            parts.append("GOD")
            continue
        parts.append(part if part.isupper() else part.capitalize())
    return " ".join(parts)


def _cards_from_envelope(
    envelope: dict[str, Any],
    *,
    fallback_conv_id: str | None,
) -> list[dict]:
    raw_cards = envelope.get("cards")
    if not isinstance(raw_cards, list):
        return []
    conversation_id = (
        envelope.get("conversation_id")
        if isinstance(envelope.get("conversation_id"), str)
        else fallback_conv_id
    )
    cards: list[dict] = []
    for raw_card in raw_cards:
        if not isinstance(raw_card, dict):
            continue
        card = dict(raw_card)
        if conversation_id and not isinstance(card.get("conversation_id"), str):
            card["conversation_id"] = conversation_id
        cards.append(card)
    return cards


def _runtime_health_from_inspector(inspector: dict | None) -> dict | None:
    if not isinstance(inspector, dict):
        return None
    session_health = inspector.get("session_health")
    if not isinstance(session_health, dict):
        return None
    items = session_health.get("items")
    if not isinstance(items, list):
        items = []
    live = 0
    stale = 0
    failed = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        binding_status = str(item.get("provider_binding_status") or "").strip().lower()
        has_provider_session = bool(str(item.get("provider_session_id") or "").strip())
        if status in {"failed", "error"} or binding_status in {"failed", "stale"}:
            failed += 1
        elif has_provider_session or binding_status == "active" or status in {
            "active",
            "running",
        }:
            live += 1
        elif status in {"stale", "stopped"}:
            stale += 1
    if live == 0 and stale == 0 and failed == 0:
        return None
    return {
        "counts": {
            "live": live,
            "stale": stale,
            "failed": failed,
            "degraded_fallback": 0,
        },
        "source": "chat_inspector.session_health",
    }


def _merge_runtime_health(primary: dict | None, fallback: dict | None) -> dict | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    primary_counts = primary.get("counts") if isinstance(primary, dict) else None
    fallback_counts = fallback.get("counts") if isinstance(fallback, dict) else None
    if not isinstance(primary_counts, dict) or not isinstance(fallback_counts, dict):
        return primary
    if int(primary_counts.get("live") or 0) > 0:
        return primary
    merged = dict(primary)
    counts = dict(primary_counts)
    counts["live"] = int(fallback_counts.get("live") or 0)
    counts["failed"] = max(
        int(counts.get("failed") or 0),
        int(fallback_counts.get("failed") or 0),
    )
    counts["stale"] = max(
        int(counts.get("stale") or 0),
        int(fallback_counts.get("stale") or 0),
    )
    merged["counts"] = counts
    merged.setdefault("source", fallback.get("source"))
    return merged


def _active_stream_messages(root: Path, conv_id: str) -> list[dict]:
    try:
        from xmuse_core.chat.stream_store import ChatStreamStore

        streams = ChatStreamStore(root / "chat.db").list_active(conv_id)
    except Exception:
        return []
    completed_source_ids = _completed_reply_source_ids(root, conv_id)
    messages: list[dict] = []
    for stream in streams:
        data = stream.model_dump(mode="json")
        source_inbox_item_id = data.get("source_inbox_item_id")
        if source_inbox_item_id and str(source_inbox_item_id) in completed_source_ids:
            continue
        content = str(data.get("content") or "")
        if not content:
            content = "..."
        messages.append(
            {
                "id": data["id"],
                "conversation_id": data["conversation_id"],
                "author": data["author"],
                "display_author": _display_author_from_participants(
                    root,
                    conv_id,
                    str(data["author"]),
                ),
                "role": "assistant",
                "content": content,
                "created_at": data["updated_at"],
                "envelope_type": "stream",
                "envelope_json": {
                    "type": "stream",
                    "status": data["status"],
                    "source_inbox_item_id": source_inbox_item_id,
                },
                "mentions": [],
                "reply_to_message_id": None,
            }
        )
    return messages


def _completed_reply_source_ids(root: Path, conv_id: str) -> set[str]:
    try:
        from xmuse_core.chat.store import ChatStore

        messages = ChatStore(root / "chat.db").list_messages(conv_id)
    except Exception:
        return set()
    source_ids: set[str] = set()
    for message in messages:
        if message.role != "assistant":
            continue
        source_inbox_item_id = message.envelope_json.get("source_inbox_item_id")
        if source_inbox_item_id:
            source_ids.add(str(source_inbox_item_id))
    return source_ids


def _display_author_from_participants(root: Path, conv_id: str, author: str) -> str:
    if not author or author.startswith("human") or author.startswith("user"):
        return author
    try:
        from xmuse_core.chat.participant_store import ParticipantStore

        store = ParticipantStore(root / "chat.db")
        for participant in store.list_by_conversation(conv_id):
            if participant.participant_id == author:
                return participant.display_name or participant.role or author
            if participant.role == author:
                return participant.display_name or participant.role or author
    except Exception:
        pass
    return author


def _display_message_author(root: Path, conv_id: str, message: dict) -> dict:
    author = str(message.get("author") or "")
    message["display_author"] = _display_author_from_participants(
        root,
        conv_id,
        author,
    )
    return message


def _merge_cards(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for card in [*primary, *secondary]:
        key = (
            str(card.get("card_type", "")),
            str(card.get("intent_id") or card.get("id") or card.get("source_id") or id(card)),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(card)
    return merged


def _now_s() -> float:
    import time
    return time.time()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _operator_actor_id() -> str:
    return os.environ.get("XMUSE_TUI_OPERATOR_ID", "local-operator").strip() or "local-operator"


def _operator_capabilities() -> tuple[str, ...]:
    raw = os.environ.get("XMUSE_TUI_OPERATOR_CAPABILITIES", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _operator_role() -> str:
    return os.environ.get("XMUSE_TUI_OPERATOR_ROLE", "operator").strip() or "operator"


def _chat_api_key() -> str | None:
    value = os.environ.get("XMUSE_CHAT_API_KEY", "").strip()
    return value or None


def _chat_api_write_headers() -> dict[str, str]:
    headers = {
        "X-XMuse-Operator-Id": _operator_actor_id(),
        "X-XMuse-Operator-Role": _operator_role(),
    }
    capabilities = ",".join(_operator_capabilities())
    if capabilities:
        headers["X-XMuse-Operator-Capabilities"] = capabilities
    api_key = _chat_api_key()
    if api_key:
        headers["X-XMUSE-API-Key"] = api_key
    return headers


def _operator_api_error_result(
    *,
    action: str,
    actor_id: str,
    status_code: int,
    detail: Any,
) -> dict[str, Any]:
    if isinstance(detail, dict):
        summary = str(detail.get("message") or detail.get("code") or detail)
    else:
        summary = str(detail or f"operator API rejected request with {status_code}")
    status = "denied" if status_code in {401, 403} else "blocked"
    return {
        "action": action,
        "status": status,
        "proof_level": "contract_proof",
        "fact_state": status,
        "actor_id": actor_id,
        "audit_id": None,
        "summary": summary,
        "payload": {
            "api_status_code": status_code,
            "api_detail": detail,
        },
    }


def _response_detail(response: Any) -> Any:
    try:
        data = response.json()
    except Exception:
        return getattr(response, "text", None)
    if isinstance(data, dict) and "detail" in data:
        return data["detail"]
    return data


def _read_json_file(path: Path, *, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _normalize_tui_command_event(event: dict[str, Any]) -> dict[str, Any] | None:
    command = str(event.get("command") or "").strip()
    conversation_id = str(event.get("conversation_id") or "").strip()
    authority = str(event.get("read_surface_authority") or "").strip()
    surface_ref = str(event.get("surface_ref") or "").strip()
    if not command or not conversation_id or not authority or not surface_ref:
        return None
    if authority not in {
        "chat_inspector",
        "dashboard_runtime_timeline",
        "operator_action_contract",
        "operator_evidence_action",
        "god_room_chat_api",
    }:
        return None
    normalized = {
        "event_id": str(event.get("event_id") or f"tui_cmd_{uuid.uuid4().hex}"),
        "command": command,
        "conversation_id": conversation_id,
        "read_surface_authority": authority,
        "surface_ref": surface_ref,
        "created_at": str(event.get("created_at") or _utc_now()),
    }
    terminal_run_id = str(event.get("terminal_run_id") or "").strip()
    if terminal_run_id:
        normalized["terminal_run_id"] = terminal_run_id
    return normalized


def _default_routed_content(content: str) -> str:
    text = content.strip()
    if not text:
        return text
    if "@" in text:
        return text
    return f"@architect {text}"


def _worklist_fingerprint(envelope: dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in envelope.items()
        if key != "generated_at"
    }
    return json.dumps(comparable, sort_keys=True, separators=(",", ":"))


def _build_health(lanes: list[dict]) -> dict:
    live = sum(
        1
        for lane in lanes
        if lane.get("status") in {"dispatched", "gated", "executed", "reworking"}
    )
    merged = sum(1 for lane in lanes if lane.get("status") == "merged")
    failed = sum(
        1
        for lane in lanes
        if lane.get("status") in {"failed", "exec_failed", "gate_failed"}
    )
    return {"live": live, "merged": merged, "failed": failed, "total": len(lanes)}
