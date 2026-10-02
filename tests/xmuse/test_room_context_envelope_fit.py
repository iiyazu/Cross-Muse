from __future__ import annotations

from typing import Any

from xmuse_core.chat.room_observation_transport_base import (
    ROOM_CONTEXT_BYTE_LIMIT,
    _fit_context_envelope,
)


def _activity(activity_id: str, content: str) -> dict[str, Any]:
    return {"activity_id": activity_id, "content": content, "content_truncated": False}


def _context(*, member_chars: int, members: int) -> dict[str, Any]:
    return {
        "participant_id": "part-verifier",
        "durable_outcome": {},
        "room_context": {
            "coverage": {"content_truncated_activity_ids": []},
            "human_root": _activity("root", "r" * 1000),
            "primary_source": _activity("plan", "p" * 16000),
            "observation_batch": {
                "members": [
                    {"activity": _activity(f"member-{index}", "m" * member_chars)}
                    for index in range(members)
                ]
            },
            "causal_ancestry": [],
            "recent_room_burst": [_activity("recent", "x" * 4000)],
        },
    }


def test_fitter_keeps_a_long_primary_whole_when_the_envelope_has_room() -> None:
    context = _fit_context_envelope(_context(member_chars=16000, members=1))
    room = context["room_context"]
    assert room["primary_source"]["content"] == "p" * 16000
    assert room["observation_batch"]["members"][0]["activity"]["content"] == "m" * 16000
    assert room["recent_room_burst"]
    assert room["coverage"]["content_truncated_activity_ids"] == []
    assert room["coverage"]["bounded"] is True


def test_fitter_shrinks_batch_members_to_the_activity_bound_before_going_lower() -> None:
    context = _fit_context_envelope(_context(member_chars=16000, members=4))
    room = context["room_context"]
    assert room["recent_room_burst"] == []
    contents = [member["activity"]["content"] for member in room["observation_batch"]["members"]]
    assert contents == ["m" * 4000] * 4
    assert room["primary_source"]["content"] == "p" * 16000
    assert room["coverage"]["content_truncated_activity_ids"] == [
        "member-0",
        "member-1",
        "member-2",
        "member-3",
    ]
    assert room["coverage"]["bounded"] is True
    assert ROOM_CONTEXT_BYTE_LIMIT >= 64 * 1024
