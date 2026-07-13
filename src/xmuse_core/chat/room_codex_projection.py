"""Bounded Room view over native Codex cache and durable bridge authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

ROOM_CODEX_PROJECTION_SCHEMA = "room_codex_projection/v1"
ROOM_CODEX_PROOF_BOUNDARY = "projection_not_codex_app_server_or_room_authority"


class RoomCodexBridgeReadStore(Protocol):
    def list_room_holds(self, conversation_id: str) -> list[dict[str, object]]: ...

    def list_room_actions(
        self,
        conversation_id: str,
        *,
        participant_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]: ...

    def room_participant_work_counts(
        self, conversation_id: str
    ) -> dict[str, dict[str, int]]: ...


def build_room_codex_projection(
    conversation_id: str,
    *,
    participants: Sequence[Mapping[str, Any]],
    bridge_store: RoomCodexBridgeReadStore,
    cache_page: Mapping[str, Any],
) -> dict[str, Any]:
    holds = {
        identifier: item
        for item in bridge_store.list_room_holds(conversation_id)
        if (identifier := _identifier(item.get("participant_id"))) is not None
    }
    counts = bridge_store.room_participant_work_counts(conversation_id)
    actions_by_participant: dict[str, list[dict[str, Any]]] = {}
    for raw in bridge_store.list_room_actions(conversation_id, limit=100):
        participant_id = _identifier(raw.get("participant_id"))
        safe = _safe_bridge_action(raw)
        if participant_id is not None and safe is not None:
            actions_by_participant.setdefault(participant_id, []).append(safe)
    cached = {
        identifier: item
        for item in _records(cache_page.get("participants"))
        if (identifier := _identifier(item.get("participant_id"))) is not None
    }
    participant_views: list[dict[str, Any]] = []
    for raw_participant in participants:
        participant_id = _identifier(raw_participant.get("participant_id"))
        if participant_id is None or raw_participant.get("cli_kind") != "codex":
            continue
        hold = _safe_hold(holds.get(participant_id))
        current = cached.get(participant_id, {})
        snapshot = _mapping(current.get("native_snapshot"))
        capabilities = _mapping(current.get("capabilities"))
        work = counts.get(participant_id, {})
        participant_views.append(
            {
                "participant": _safe_participant(raw_participant),
                "native_snapshot": {
                    "source": "codex_app_server_projection_cache",
                    "observed_at": _timestamp(current.get("observed_at")),
                    "available": snapshot is not None,
                    "value": dict(snapshot) if snapshot is not None else None,
                },
                "capabilities": {
                    "source": "codex_app_server_projection_cache",
                    "observed_at": _timestamp(current.get("observed_at")),
                    "available": capabilities is not None,
                    "value": dict(capabilities) if capabilities is not None else None,
                    "actions": _action_descriptors(
                        participant_id,
                        snapshot=snapshot,
                        capabilities=capabilities,
                        hold=hold,
                        unresolved_count=_integer(work.get("unresolved_count")),
                        active_attempt_count=_integer(work.get("active_attempt_count")),
                    ),
                },
                "room_bridge": {
                    "source": "chat.db:room_codex_bridge",
                    "observed_at": _timestamp(hold.get("observed_at") if hold else None),
                    "hold": hold,
                    "queue": {
                        "unresolved_count": _integer(work.get("unresolved_count")),
                        "active_attempt_count": _integer(work.get("active_attempt_count")),
                        "root_blocking": bool(
                            hold is not None
                            and hold.get("state") != "accepting"
                            and _integer(work.get("unresolved_count")) > 0
                        ),
                    },
                    "actions": actions_by_participant.get(participant_id, []),
                },
                "history_partial": current.get("history_partial") is not False,
                "omitted_event_count": _integer(current.get("omitted_count")),
            }
        )
    return {
        "schema_version": ROOM_CODEX_PROJECTION_SCHEMA,
        "conversation_id": conversation_id,
        "generated_at": _now(),
        "projection_only": True,
        "proof_boundary": ROOM_CODEX_PROOF_BOUNDARY,
        "participants": participant_views,
        "native_events": {
            "source": "codex_app_server_projection_cache",
            "projection_available": cache_page.get("projection_available") is True,
            "reason_code": _identifier(cache_page.get("reason_code")),
            "event_seq_domain": "room_codex_projection_cache",
            "items": [_safe_native_event(item) for item in _records(cache_page.get("events"))],
            "latest_event_seq": _integer(cache_page.get("latest_event_seq")),
            "has_older": cache_page.get("has_older") is True,
            "has_newer": cache_page.get("has_newer") is True,
            "next_before_event_seq": _optional_integer(
                cache_page.get("next_before_event_seq")
            ),
            "next_after_event_seq": _optional_integer(cache_page.get("next_after_event_seq")),
        },
    }


def _action_descriptors(
    participant_id: str,
    *,
    snapshot: Mapping[str, Any] | None,
    capabilities: Mapping[str, Any] | None,
    hold: Mapping[str, Any] | None,
    unresolved_count: int,
    active_attempt_count: int,
) -> list[dict[str, Any]]:
    if snapshot is None or capabilities is None or hold is None:
        return []
    guards = _mapping(snapshot.get("guards"))
    if guards is None or hold.get("session_guard") != guards.get("session"):
        return []
    goal = _mapping(snapshot.get("goal"))
    goal_status = _identifier(goal.get("status")) if goal is not None else None
    hold_state = _identifier(hold.get("state"))
    active_turn = snapshot.get("active_turn") is True
    descriptors: list[dict[str, Any]] = []
    value = capabilities.get("capabilities")
    for raw in _records(value):
        capability_id = _identifier(raw.get("capability_id"))
        if capability_id is None:
            continue
        available = raw.get("availability") == "available"
        confirmation = False
        if capability_id in {"turn_steer", "turn_interrupt"}:
            available = (
                available
                and active_turn
                and guards.get("turn") is not None
                and active_attempt_count == 0
            )
        elif capability_id == "goal_pause":
            available = available and goal_status == "active"
        elif capability_id == "goal_resume":
            available = available and goal_status in {"paused", "blocked"}
        elif capability_id == "goal_clear":
            available = available and not active_turn and goal_status in {
                "paused",
                "blocked",
                "usageLimited",
                "budgetLimited",
                "complete",
            }
        elif capability_id == "goal_set":
            available = available and hold_state == "accepting" and active_attempt_count == 0
            confirmation = available and unresolved_count > 0
        elif capability_id not in {"goal_get", "models_list"}:
            available = available and hold_state == "accepting" and not active_turn
        descriptors.append(
            {
                "capability_id": capability_id,
                "available": available,
                "disabled_reason": (
                    None if available else _identifier(raw.get("disabled_reason"))
                    or "codex_native_state_conflict"
                ),
                "method": "POST",
                "href": (
                    f"/api/chat/operator/room-participants/{participant_id}/codex-actions"
                ),
                "expected_session_guard": guards.get("session"),
                "expected_goal_guard": guards.get("goal"),
                "expected_settings_guard": guards.get("settings"),
                "expected_turn_guard": guards.get("turn"),
                "confirmation_required": confirmation,
            }
        )
    return descriptors


def _safe_participant(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "participant_id": _identifier(value.get("participant_id")),
        "role": _identifier(value.get("role")),
        "display_name": _text(value.get("display_name"), 120),
        "status": "active" if value.get("status") == "active" else "stopped",
    }


def _safe_hold(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "state": _identifier(value.get("state")),
        "hold_revision": _integer(value.get("hold_revision")),
        "session_guard": _guard(value.get("session_guard")),
        "goal_guard": _guard(value.get("goal_guard")),
        "settings_guard": _guard(value.get("settings_guard")),
        "active_turn_guard": _guard(value.get("active_turn_guard")),
        "reason_code": _identifier(value.get("reason_code")),
        "observed_at": _timestamp(value.get("observed_at")),
        "updated_at": _timestamp(value.get("updated_at")),
    }


def _safe_bridge_action(value: Mapping[str, Any]) -> dict[str, Any] | None:
    action_id = _identifier(value.get("action_id"))
    capability_id = _identifier(value.get("capability_id"))
    if action_id is None or capability_id is None:
        return None
    return {
        "action_id": action_id,
        "control_seq": _integer(value.get("control_seq")),
        "client_action_id": _identifier(value.get("client_action_id")),
        "capability_id": capability_id,
        "status": _identifier(value.get("status")),
        "reason_code": _identifier(value.get("reason_code")),
        "requested_at": _timestamp(value.get("requested_at")),
        "completed_at": _timestamp(value.get("completed_at")),
        "updated_at": _timestamp(value.get("updated_at")),
    }


def _safe_native_event(value: Mapping[str, Any]) -> dict[str, Any]:
    # The cache already rebuilt these records from a closed allowlist. Copy only
    # its public record, excluding any unknown future field at the API boundary.
    safe: dict[str, Any] = {
        "event_seq": _integer(value.get("event_seq")),
        "participant_seq": _integer(value.get("participant_seq")),
        "participant_id": _identifier(value.get("participant_id")),
        "observed_at": _timestamp(value.get("observed_at")),
        "kind": _identifier(value.get("kind")),
    }
    for key in (
        "status",
        "model",
        "effort",
        "item_type",
        "usage",
        "status_counts",
        "step_count",
        "file_count",
        "addition_count",
        "deletion_count",
        "duration_ms",
        "exit_code",
        "truncated",
        "text",
        "steps",
        "explanation",
    ):
        if key in value:
            safe[key] = value[key]
    return safe


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _records(value: object) -> list[Mapping[str, Any]]:
    return (
        [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )


def _identifier(value: object) -> str | None:
    return _text(value, 200)


def _guard(value: object) -> str | None:
    text = _text(value, 71)
    return text if text is not None and text.startswith("sha256:") else None


def _text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean if clean and len(clean.encode("utf-8")) <= maximum else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _timestamp(value: object) -> str | None:
    return _text(value, 100)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "ROOM_CODEX_PROJECTION_SCHEMA",
    "ROOM_CODEX_PROOF_BOUNDARY",
    "RoomCodexBridgeReadStore",
    "build_room_codex_projection",
]
