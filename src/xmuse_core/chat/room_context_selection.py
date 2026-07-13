"""Pure selection and shaping for one bounded Room delivery context.

This leaf owns no Room authority, provider task, memory lookup, or transport byte
fitting.  It preserves the root/primary/causal inputs that the transport's 64 KiB
``room_context_envelope/v2`` fitter must never discard.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class ParticipantContextIdentity(Protocol):
    display_name: str
    role: str


@dataclass(frozen=True)
class RoomContextSelection:
    human_root: dict[str, Any]
    source_activity: dict[str, Any]
    causal_ancestry: tuple[dict[str, Any], ...]
    recent_activities: tuple[dict[str, Any], ...]
    batch: dict[str, Any]
    coverage: dict[str, Any]


def _preview(value: Any, limit: int) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return encoded[:limit]


def activity_content_truncated(activity: Mapping[str, Any], *, max_payload_chars: int) -> bool:
    payload = activity.get("payload")
    content = payload.get("content") if isinstance(payload, Mapping) else None
    return isinstance(content, str) and len(content) > max_payload_chars


def activity_context(
    activity: Mapping[str, Any],
    participant_directory: Mapping[str, ParticipantContextIdentity],
    *,
    max_payload_chars: int,
) -> dict[str, Any]:
    """Shape one activity while bounding untrusted payload text."""

    keys = (
        "activity_id",
        "conversation_id",
        "seq",
        "activity_type",
        "actor_kind",
        "actor_identity",
        "actor_participant_id",
        "causation_id",
        "correlation_id",
        "causal_depth",
        "created_at",
    )
    raw_payload = activity.get("payload")
    payload = raw_payload if isinstance(raw_payload, Mapping) else {}
    raw_content = payload.get("content")
    content = raw_content if isinstance(raw_content, str) else None
    if content is not None:
        content = content[:max_payload_chars]
    actor_participant_id = activity.get("actor_participant_id")
    actor = participant_directory.get(str(actor_participant_id))
    targets: list[str] = []
    for name in (
        "mentioned_participant_ids",
        "priority_participant_ids",
        "handoff_targets",
        "mentions",
    ):
        values = payload.get(name, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.removeprefix("@participant:")
            if normalized in participant_directory and normalized not in targets:
                targets.append(normalized)
    return {key: activity.get(key) for key in keys} | {
        "room_seq": activity.get("seq"),
        "actor": {
            "kind": activity.get("actor_kind"),
            "identity": activity.get("actor_identity"),
            "participant_id": actor_participant_id,
            "display_name": actor.display_name if actor is not None else None,
            "role": actor.role if actor is not None else None,
        },
        "target_participant_ids": targets,
        "content": content,
        "content_truncated": activity_content_truncated(
            activity, max_payload_chars=max_payload_chars
        ),
        "context_only": payload.get("context_only") is True,
        "payload_preview": _preview(payload, max_payload_chars),
    }


def causal_ancestry(
    member_activities: Sequence[Mapping[str, Any]],
    activities: Mapping[str, Mapping[str, Any]],
    *,
    human_root_activity_id: str,
) -> list[Mapping[str, Any]]:
    """Return complete, de-duplicated ancestry excluding delivered members/root."""

    member_ids = {str(activity.get("activity_id") or "") for activity in member_activities}
    ancestry: dict[str, Mapping[str, Any]] = {}
    for member in member_activities:
        parent_id = str(member.get("causation_id") or "")
        visited: set[str] = set()
        while parent_id and parent_id not in visited:
            visited.add(parent_id)
            parent = activities.get(parent_id)
            if parent is None:
                break
            activity_id = str(parent.get("activity_id") or "")
            if activity_id not in member_ids and activity_id != human_root_activity_id:
                ancestry[activity_id] = parent
            parent_id = str(parent.get("causation_id") or "")
    return sorted(ancestry.values(), key=lambda activity: int(activity["seq"]))


def batch_context(
    batch: Mapping[str, Any] | None,
    *,
    batch_members: Sequence[Mapping[str, Any]],
    participant_directory: Mapping[str, ParticipantContextIdentity],
    fallback_observation: Mapping[str, Any],
    fallback_activity: Mapping[str, Any],
    max_payload_chars: int,
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "schema_version": "room_observation_batch/v1",
        "batch_id": (
            batch.get("batch_id")
            if batch is not None
            else f"singleton:{fallback_observation['observation_id']}"
        ),
        "phase": batch.get("phase", "root") if batch is not None else "root",
        "correlation_id": (
            batch.get("correlation_id", fallback_activity.get("correlation_id"))
            if batch is not None
            else fallback_activity.get("correlation_id")
        ),
        "primary_observation_id": (
            batch.get(
                "primary_observation_id",
                fallback_observation["observation_id"],
            )
            if batch is not None
            else fallback_observation["observation_id"]
        ),
        "cutoff_seq": (
            int(batch.get("cutoff_seq", fallback_activity["seq"]))
            if batch is not None
            else int(fallback_activity["seq"])
        ),
        "digest": batch.get("digest") if batch is not None else None,
    }
    members: list[dict[str, Any]] = []
    for fallback_ordinal, member in enumerate(batch_members):
        observation = member.get("observation")
        activity = member.get("activity")
        if not isinstance(observation, Mapping) or not isinstance(activity, Mapping):
            continue
        members.append(
            {
                "ordinal": int(member.get("ordinal", fallback_ordinal)),
                "observation_id": observation.get("observation_id"),
                "activity": activity_context(
                    activity,
                    participant_directory,
                    max_payload_chars=max_payload_chars,
                ),
            }
        )
    identity["member_count"] = len(members)
    identity["members"] = members
    return identity


def select_room_context(
    *,
    source_activity: Mapping[str, Any],
    member_activities: Sequence[Mapping[str, Any]],
    activities: Mapping[str, Mapping[str, Any]],
    batch: Mapping[str, Any] | None,
    batch_members: Sequence[Mapping[str, Any]],
    participant_directory: Mapping[str, ParticipantContextIdentity],
    fallback_observation: Mapping[str, Any],
    recent_activity_limit: int,
    max_payload_chars: int,
) -> RoomContextSelection:
    """Select root, ancestry, immutable batch, and a bounded recent Room burst."""

    correlation_id = str(source_activity.get("correlation_id") or "")
    correlation_activities = [
        activity
        for activity in activities.values()
        if activity.get("correlation_id") == correlation_id
    ]
    human_root = min(
        (
            activity
            for activity in correlation_activities
            if activity.get("actor_kind") == "human"
            and activity.get("activity_type") == "message.posted"
        ),
        key=lambda activity: int(activity["seq"]),
        default=source_activity,
    )
    ancestry_source = list(member_activities) or [source_activity]
    ancestry = causal_ancestry(
        ancestry_source,
        activities,
        human_root_activity_id=str(human_root.get("activity_id") or ""),
    )
    cutoff_seq = int(
        batch.get("cutoff_seq", source_activity["seq"])
        if batch is not None
        else source_activity["seq"]
    )
    eligible = [activity for activity in activities.values() if int(activity["seq"]) <= cutoff_seq]
    eligible.sort(key=lambda activity: int(activity["seq"]))
    recent_source = eligible[-recent_activity_limit:]
    selected_batch = batch_context(
        batch,
        batch_members=batch_members,
        participant_directory=participant_directory,
        fallback_observation=fallback_observation,
        fallback_activity=source_activity,
        max_payload_chars=max_payload_chars,
    )
    truncation_candidates = [
        human_root,
        source_activity,
        *member_activities,
        *ancestry,
        *recent_source,
    ]
    coverage = {
        "schema_version": "room_context_coverage/v1",
        "room_seq_cutoff": cutoff_seq,
        "recent_burst_included_count": len(recent_source),
        "recent_burst_omitted_count": max(0, len(eligible) - len(recent_source)),
        "causal_ancestry_included_count": len(ancestry),
        "causal_ancestry_omitted_count": 0,
        "content_truncated_activity_ids": [
            str(item["activity_id"])
            for item in truncation_candidates
            if activity_content_truncated(item, max_payload_chars=max_payload_chars)
        ],
    }
    shape = lambda activity: activity_context(  # noqa: E731
        activity,
        participant_directory,
        max_payload_chars=max_payload_chars,
    )
    return RoomContextSelection(
        human_root=shape(human_root),
        source_activity=shape(source_activity),
        causal_ancestry=tuple(shape(activity) for activity in ancestry),
        recent_activities=tuple(shape(activity) for activity in recent_source),
        batch=selected_batch,
        coverage=coverage,
    )


def memory_excluded_activity_ids(
    *,
    source_activity: Mapping[str, Any],
    human_root: Mapping[str, Any] | None,
    causal_ancestry: Sequence[Mapping[str, Any]],
    recent_activities: Sequence[Mapping[str, Any]],
    batch: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Return sources already present in the causal envelope for recall exclusion."""

    values: set[str] = set()

    def add(activity: Mapping[str, Any] | None) -> None:
        if not isinstance(activity, Mapping):
            return
        activity_id = activity.get("activity_id")
        if isinstance(activity_id, str) and activity_id:
            values.add(activity_id)

    add(source_activity)
    add(human_root)
    for activity in (*causal_ancestry, *recent_activities):
        add(activity)
    members = batch.get("members") if isinstance(batch, Mapping) else None
    if isinstance(members, list):
        for member in members:
            if isinstance(member, Mapping):
                member_activity = member.get("activity")
                add(member_activity if isinstance(member_activity, Mapping) else None)
    return tuple(sorted(values))
