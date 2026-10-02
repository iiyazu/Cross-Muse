from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.chat.room_context_selection import (
    memory_excluded_activity_ids,
    select_room_context,
)


@dataclass(frozen=True)
class _Participant:
    display_name: str
    role: str


def _activity(
    activity_id: str,
    seq: int,
    *,
    actor_kind: str = "agent",
    actor_participant_id: str | None = "agent-1",
    causation_id: str | None = None,
    content: str = "content",
    correlation_id: str = "corr-1",
) -> dict[str, object]:
    return {
        "activity_id": activity_id,
        "conversation_id": "room-1",
        "seq": seq,
        "activity_type": "message.posted",
        "actor_kind": actor_kind,
        "actor_identity": "human:alice" if actor_kind == "human" else "god:agent-1",
        "actor_participant_id": actor_participant_id,
        "causation_id": causation_id,
        "correlation_id": correlation_id,
        "causal_depth": seq - 1,
        "created_at": f"2026-07-13T00:00:0{seq}Z",
        "payload": {"content": content},
    }


def test_selection_preserves_root_primary_ancestry_and_bounds_recent_burst() -> None:
    root = _activity("root", 1, actor_kind="human", actor_participant_id=None)
    ancestor = _activity("ancestor", 2, causation_id="root")
    source = _activity("source", 3, causation_id="ancestor")
    late = _activity("late", 4, causation_id="source")
    activities = {str(item["activity_id"]): item for item in (root, ancestor, source, late)}
    observation = {"observation_id": "obs-source"}
    selection = select_room_context(
        source_activity=source,
        member_activities=[source],
        activities=activities,
        batch={
            "batch_id": "batch-1",
            "phase": "peer",
            "correlation_id": "corr-1",
            "primary_observation_id": "obs-source",
            "cutoff_seq": 3,
            "digest": "sha256:digest",
        },
        batch_members=[{"ordinal": 0, "observation": observation, "activity": source}],
        participant_directory={"agent-1": _Participant("Reviewer", "reviewer")},
        fallback_observation=observation,
        recent_activity_limit=1,
        max_payload_chars=4000,
    )

    assert selection.human_root["activity_id"] == "root"
    assert selection.source_activity["activity_id"] == "source"
    assert [item["activity_id"] for item in selection.causal_ancestry] == ["ancestor"]
    assert [item["activity_id"] for item in selection.recent_activities] == ["source"]
    assert selection.batch["primary_observation_id"] == "obs-source"
    assert selection.batch["members"][0]["activity"]["actor"] == {
        "kind": "agent",
        "identity": "god:agent-1",
        "participant_id": "agent-1",
        "display_name": "Reviewer",
        "role": "reviewer",
    }
    assert selection.coverage == {
        "schema_version": "room_context_coverage/v1",
        "room_seq_cutoff": 3,
        "recent_burst_included_count": 1,
        "recent_burst_omitted_count": 2,
        "causal_ancestry_included_count": 1,
        "causal_ancestry_omitted_count": 0,
        "content_truncated_activity_ids": [],
    }
    assert "late" not in repr(selection)


def test_selection_truncates_content_without_losing_root_or_batch_member() -> None:
    root = _activity("root", 1, actor_kind="human", actor_participant_id=None, content="x" * 32)
    source = _activity("source", 2, causation_id="root", content="y" * 32)
    activities = {"root": root, "source": source}
    observation = {"observation_id": "obs-source"}
    selection = select_room_context(
        source_activity=source,
        member_activities=[source],
        activities=activities,
        batch=None,
        batch_members=[{"ordinal": 0, "observation": observation, "activity": source}],
        participant_directory={"agent-1": _Participant("Reviewer", "reviewer")},
        fallback_observation=observation,
        recent_activity_limit=8,
        max_payload_chars=8,
    )

    assert selection.human_root["content"] == "x" * 8
    assert selection.human_root["content_truncated"] is True
    assert selection.source_activity["content"] == "y" * 8
    assert selection.batch["batch_id"] == "singleton:obs-source"
    assert selection.batch["member_count"] == 1
    assert set(selection.coverage["content_truncated_activity_ids"]) == {
        "root",
        "source",
    }


def test_primary_inputs_use_the_wider_bound_and_only_recent_burst_stays_tight() -> None:
    # A long Human prompt and a long handed-off plan must reach the participant whole;
    # an unrelated earlier message in the recent burst keeps the tight bound.
    other = _activity("other", 1, correlation_id="corr-0", content="o" * 40)
    root = _activity("root", 2, actor_kind="human", actor_participant_id=None, content="r" * 40)
    ancestor = _activity("ancestor", 3, causation_id="root", content="a" * 40)
    source = _activity("source", 4, causation_id="ancestor", content="s" * 40)
    activities = {str(item["activity_id"]): item for item in (other, root, ancestor, source)}
    observation = {"observation_id": "obs-source"}
    selection = select_room_context(
        source_activity=source,
        member_activities=[source],
        activities=activities,
        batch=None,
        batch_members=[{"ordinal": 0, "observation": observation, "activity": source}],
        participant_directory={"agent-1": _Participant("Verifier", "review")},
        fallback_observation=observation,
        recent_activity_limit=8,
        max_payload_chars=8,
        max_primary_content_chars=64,
    )

    assert selection.human_root["content"] == "r" * 40
    assert selection.source_activity["content"] == "s" * 40
    assert selection.batch["members"][0]["activity"]["content"] == "s" * 40
    assert selection.causal_ancestry[0]["content"] == "a" * 40
    assert selection.human_root["content_truncated"] is False
    assert len(selection.source_activity["payload_preview"]) == 8
    recent = {item["activity_id"]: item for item in selection.recent_activities}
    assert recent["other"]["content"] == "o" * 8
    assert recent["other"]["content_truncated"] is True
    # The recent copy of the source is shortened, but its primary copy is whole.
    assert recent["source"]["content"] == "s" * 8
    assert selection.coverage["content_truncated_activity_ids"] == ["other"]

    over = select_room_context(
        source_activity=source,
        member_activities=[source],
        activities=activities,
        batch=None,
        batch_members=[{"ordinal": 0, "observation": observation, "activity": source}],
        participant_directory={"agent-1": _Participant("Verifier", "review")},
        fallback_observation=observation,
        recent_activity_limit=8,
        max_payload_chars=8,
        max_primary_content_chars=16,
    )
    assert over.source_activity["content"] == "s" * 16
    assert over.source_activity["content_truncated"] is True
    assert over.coverage["content_truncated_activity_ids"] == [
        "root",
        "source",
        "ancestor",
        "other",
    ]


def test_memory_exclusion_covers_every_context_source_once() -> None:
    assert memory_excluded_activity_ids(
        source_activity={"activity_id": "source"},
        human_root={"activity_id": "root"},
        causal_ancestry=({"activity_id": "ancestor"},),
        recent_activities=(
            {"activity_id": "source"},
            {"activity_id": "recent"},
        ),
        batch={
            "members": [
                {"activity": {"activity_id": "batch-member"}},
                {"activity": {"activity_id": "source"}},
            ]
        },
    ) == ("ancestor", "batch-member", "recent", "root", "source")
