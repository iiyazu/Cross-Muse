"""Provider-neutral Room core admission for non-Codex Room agents."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.mentions import MentionResolver
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_codex_bridge import RoomCodexBridgeStore
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_projection import (
    build_room_chat_projection,
    build_room_list_projection,
)


def _room(tmp_path: Path):
    path = tmp_path / "chat.db"
    conversation = RoomTestStore(path).create_conversation("multi-provider room")
    participants = ParticipantStore(path)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=role,
            display_name=display_name,
            cli_kind=cli_kind,
            model=model,
        )
        for role, display_name, cli_kind, model in (
            ("architect", "Codex Architect", "codex", "gpt-5"),
            ("review", "Claude Reviewer", "claude", "claude-sonnet"),
            ("execute", "Antigravity Executor", "antigravity", "gemini-pro"),
        )
    ]
    return path, conversation.id, members


def _complete(
    kernel: RoomKernelStore,
    conversation_id: str,
    participant,
    claim,
    request: str,
    outcome: str,
    payload: dict | None = None,
    **extra,
):
    return kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        caller_identity=f"god:session:{participant.participant_id}",
        observation_id=claim["observation"]["observation_id"],
        observation_batch_id=claim["batch"]["batch_id"],
        lease_token=claim["observation"]["lease_token"],
        client_request_id=request,
        outcome_type=outcome,
        outcome_payload=payload or {},
        **extra,
    )


def test_human_post_fans_out_one_root_observation_per_provider_kind(tmp_path: Path) -> None:
    path, conversation_id, members = _room(tmp_path)
    kernel = RoomKernelStore(path)

    posted = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="plan the release together",
        client_request_id="human-mixed-root",
    )

    assert sorted(item["participant_id"] for item in posted["observations"]) == sorted(
        member.participant_id for member in members
    )
    assert all(item["status"] == "pending" for item in posted["observations"])
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "select participant_id from room_observations "
            "where conversation_id = ? and delivery_mode = 'active'",
            (conversation_id,),
        ).fetchall()
    assert sorted(row[0] for row in rows) == sorted(member.participant_id for member in members)


def test_peer_fan_out_delivers_non_codex_responses_to_peers(tmp_path: Path) -> None:
    path, conversation_id, members = _room(tmp_path)
    codex, claude, antigravity = members
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="plan the release together",
        client_request_id="human-peer-root",
    )
    claims = [
        kernel.claim_next_observation_batch(
            conversation_id=conversation_id,
            participant_id=member.participant_id,
            lease_owner=f"root-{index}",
        )
        for index, member in enumerate(members)
    ]
    assert all(claim is not None and claim["batch"]["phase"] == "root" for claim in claims)
    produced: dict[str, str] = {}
    for index, (member, claim) in enumerate(zip(members, claims, strict=True)):
        completed = _complete(
            kernel,
            conversation_id,
            member,
            claim,
            f"root-{index}",
            "respond",
            {"content": f"{member.cli_kind} root response"},
        )
        produced[member.cli_kind] = completed["produced_activity"]["activity_id"]

    claude_peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=claude.participant_id,
        lease_owner="claude-peer",
    )
    codex_peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=codex.participant_id,
        lease_owner="codex-peer",
    )
    assert claude_peer is not None and claude_peer["batch"]["phase"] == "peer"
    assert codex_peer is not None and codex_peer["batch"]["phase"] == "peer"
    assert {item["activity"]["activity_id"] for item in claude_peer["batch"]["members"]} == {
        produced["codex"],
        produced["antigravity"],
    }
    assert {item["activity"]["activity_id"] for item in codex_peer["batch"]["members"]} == {
        produced["claude"],
        produced["antigravity"],
    }

    reply_target = claude_peer["batch"]["members"][1]["activity"]["activity_id"]
    completed = _complete(
        kernel,
        conversation_id,
        claude,
        claude_peer,
        "claude-peer-response",
        "respond",
        {"content": "claude synthesized follow-up"},
        reply_to_activity_id=reply_target,
    )
    assert completed["produced_activity"]["causation_id"] == reply_target
    assert completed["downstream_observations"] == []


def test_claude_participant_submits_bound_outcome_with_valid_lease(tmp_path: Path) -> None:
    path, conversation_id, members = _room(tmp_path)
    claude = members[1]
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="only claude acts",
        client_request_id="human-claude-only",
    )
    claim = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=claude.participant_id,
        lease_owner="claude-root",
    )
    assert claim is not None and claim["batch"]["phase"] == "root"

    completed = _complete(
        kernel,
        conversation_id,
        claude,
        claim,
        "claude-root-response",
        "respond",
        {"content": "claude durable response"},
    )

    assert completed["produced_message"]["content"] == "claude durable response"
    observation = kernel.get_observation(claim["observation"]["observation_id"])
    assert observation["status"] == "completed"
    assert observation["lease_token"] is None
    with sqlite3.connect(path) as conn:
        message = conn.execute(
            "select author, role, content from messages where id = ?",
            (completed["produced_message"]["id"],),
        ).fetchone()
    assert message == (claude.participant_id, "assistant", "claude durable response")


def test_projection_and_mentions_treat_non_codex_participants_as_active_agents(
    tmp_path: Path,
) -> None:
    path, conversation_id, members = _room(tmp_path)
    codex, claude, antigravity = members
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="hello room",
        client_request_id="human-projection",
    )

    projection = build_room_chat_projection(conversation_id, tmp_path)
    by_id = {item["participant_id"]: item for item in projection["participants"]}
    assert by_id[claude.participant_id]["status"] == "active"
    assert by_id[claude.participant_id]["participant_status"] == "active"
    assert by_id[claude.participant_id]["mention_handle"] == "@review"
    assert by_id[antigravity.participant_id]["status"] == "active"
    assert by_id[antigravity.participant_id]["mention_handle"] == "@execute"
    assert by_id[claude.participant_id]["cli_kind"] == "claude"
    assert by_id[antigravity.participant_id]["cli_kind"] == "antigravity"
    assert projection["active_turn_count"] == 1
    room = build_room_list_projection(tmp_path)["rooms"][0]
    assert room["status"] == "active"
    assert room["participant_count"] == 3
    assert room["active_participant_count"] == 3

    resolver = MentionResolver(ParticipantStore(path))
    mention = resolver.resolve(conversation_id, "@claude-reviewer")
    assert mention.participant.participant_id == claude.participant_id
    resolved = resolver.resolve_content(
        conversation_id,
        "@codex-architect and @antigravity-executor please review",
    )
    assert [item.participant.participant_id for item in resolved] == [
        codex.participant_id,
        antigravity.participant_id,
    ]


def test_delivery_gate_admits_non_codex_agents_without_codex_holds(tmp_path: Path) -> None:
    path, conversation_id, members = _room(tmp_path)
    codex, claude, antigravity = members
    bridge = RoomCodexBridgeStore(path)

    assert bridge.participant_accepts_delivery(codex.participant_id) is False
    assert bridge.participant_accepts_delivery(claude.participant_id) is True
    assert bridge.participant_accepts_delivery(antigravity.participant_id) is True
    assert bridge.participant_accepts_delivery("part_unknown") is False
