"""Durable addressed collaboration mode: directed roots, batons, and handoff notes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_api_models import RoomCollaborationInit, RoomConversationCreate
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore, normalize_participant_outcome
from xmuse_core.chat.room_projection import (
    build_room_chat_projection,
    build_room_list_projection,
)
from xmuse_core.chat.room_setup import RoomSetupError, RoomSetupService
from xmuse_core.chat.roster_templates import (
    RosterCollaboration,
    RosterTemplate,
    builtin_workroom_catalog,
    persona_snapshot_for_role_profile,
    template_to_participant_inits,
    validate_roster_template,
)

OUTCOME_TOOL = "chat_room_submit_outcome"


def _room(tmp_path: Path, *, mode: str | None = None, lead: str | None = None):
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("collaboration room")
    participants = ParticipantStore(db)
    members = {
        "claude": participants.add(
            conversation_id=conversation.id,
            role="review",
            display_name="Claude Reviewer",
            cli_kind="claude",
            model="claude-sonnet",
        ),
        "antigravity": participants.add(
            conversation_id=conversation.id,
            role="research",
            display_name="Antigravity Researcher",
            cli_kind="antigravity",
            model="gemini-pro",
        ),
        "codex": participants.add(
            conversation_id=conversation.id,
            role="execute",
            display_name="Codex Executor",
            cli_kind="codex",
            model="gpt-5",
        ),
    }
    if mode is not None:
        _write_policy(
            db,
            conversation.id,
            mode=mode,
            lead_participant_id=members[lead].participant_id if lead else None,
        )
    return db, conversation.id, members


def _write_policy(
    db: Path,
    conversation_id: str,
    *,
    mode: str,
    lead_participant_id: str | None,
    updated_at: str = "2026-10-01T00:00:00.000000Z",
) -> None:
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation_id,
            mode=mode,
            lead_participant_id=lead_participant_id,
            updated_at=updated_at,
        )


def _post(kernel: RoomKernelStore, conversation_id: str, request: str, **extra: Any):
    return kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="collaborate on the release",
        client_request_id=request,
        **extra,
    )


def _claim(kernel: RoomKernelStore, conversation_id: str, member, owner: str):
    return kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=member.participant_id,
        lease_owner=owner,
    )


def _complete(
    kernel: RoomKernelStore,
    conversation_id: str,
    member,
    claim,
    outcome_type: str,
    payload: dict,
    request: str,
    **extra: Any,
):
    return kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=member.participant_id,
        caller_identity=f"god:session:{member.participant_id}",
        observation_id=claim["observation"]["observation_id"],
        observation_batch_id=claim["batch"]["batch_id"],
        lease_token=claim["observation"]["lease_token"],
        client_request_id=request,
        outcome_type=outcome_type,
        outcome_payload=payload,
        **extra,
    )


def _observation_count(
    db: Path, conversation_id: str, participant_id: str, *, peer_only: bool
) -> int:
    peer_predicate = (
        "and not (a.actor_kind = 'human' and a.activity_type = 'message.posted')"
        if peer_only
        else ""
    )
    with sqlite3.connect(db) as conn:
        return int(
            conn.execute(
                f"""select count(*) from room_observations o
                    join room_activities a on a.activity_id = o.activity_id
                    where o.conversation_id = ? and o.participant_id = ?
                      and o.delivery_mode = 'active' {peer_predicate}""",
                (conversation_id, participant_id),
            ).fetchone()[0]
        )


def _activities(db: Path, conversation_id: str) -> list[tuple[str, str]]:
    with sqlite3.connect(db) as conn:
        return [
            (row[0], row[1])
            for row in conn.execute(
                "select activity_id, payload_json from room_activities "
                "where conversation_id = ? order by seq",
                (conversation_id,),
            )
        ]


def test_broadcast_room_keeps_undirected_fan_out_and_payload_shape(tmp_path: Path) -> None:
    db, conversation_id, members = _room(tmp_path)
    claude, antigravity, codex = (
        members["claude"],
        members["antigravity"],
        members["codex"],
    )
    kernel = RoomKernelStore(db)

    posted = _post(
        kernel,
        conversation_id,
        "broadcast-root",
        mentions=[f"@participant:{codex.participant_id}"],
    )
    assert {item["participant_id"] for item in posted["observations"]} == {
        claude.participant_id,
        antigravity.participant_id,
        codex.participant_id,
    }
    assert posted["activity"]["payload"] == {
        "content": "collaborate on the release",
        "mentions": [f"@participant:{codex.participant_id}"],
    }
    priorities = {item["participant_id"]: item["priority"] for item in posted["observations"]}
    assert priorities[codex.participant_id] == 100
    assert priorities[claude.participant_id] == 0

    claim = _claim(kernel, conversation_id, codex, "broadcast-codex")
    assert claim is not None and claim["batch"]["phase"] == "root"
    completed = _complete(
        kernel,
        conversation_id,
        codex,
        claim,
        "respond",
        {"content": "broadcast answer", "mentioned_participant_ids": [claude.participant_id]},
        "broadcast-codex-response",
    )
    assert {item["participant_id"] for item in completed["downstream_observations"]} == {
        claude.participant_id,
        antigravity.participant_id,
    }
    payload = completed["produced_activity"]["payload"]
    assert "addressing" not in payload
    assert payload["context_only"] is False
    assert payload["downstream_mode"] == "active"

    projection = build_room_chat_projection(conversation_id, tmp_path)
    assert projection["collaboration"] == {"mode": "broadcast", "lead_participant_id": None}
    assert build_room_list_projection(tmp_path)["rooms"][0]["collaboration"] == {
        "mode": "broadcast",
        "lead_participant_id": None,
    }


def test_addressed_root_delivers_only_to_mentions_lead_or_fallback(tmp_path: Path) -> None:
    db, conversation_id, members = _room(tmp_path, mode="addressed", lead="claude")
    claude, antigravity = members["claude"], members["antigravity"]
    kernel = RoomKernelStore(db)

    mentioned = _post(
        kernel,
        conversation_id,
        "root-mentions",
        mentions=[f"@participant:{antigravity.participant_id}"],
    )
    assert [item["participant_id"] for item in mentioned["observations"]] == [
        antigravity.participant_id
    ]
    assert mentioned["observations"][0]["priority"] == 100
    assert mentioned["activity"]["payload"]["addressing"] == "mentions"

    lead = _post(kernel, conversation_id, "root-lead")
    assert [item["participant_id"] for item in lead["observations"]] == [claude.participant_id]
    assert lead["activity"]["payload"]["addressing"] == "lead"
    assert lead["observations"][0]["priority"] == 0

    with RoomDatabase(db).connect() as conn:
        conn.execute(
            "update room_collaboration_policies set lead_participant_id = null "
            "where conversation_id = ?",
            (conversation_id,),
        )
    missing_lead = _post(kernel, conversation_id, "root-missing-lead")
    assert missing_lead["activity"]["payload"]["addressing"] == "fallback_broadcast"
    assert {item["participant_id"] for item in missing_lead["observations"]} == {
        claude.participant_id,
        antigravity.participant_id,
        members["codex"].participant_id,
    }

    with RoomDatabase(db).connect() as conn:
        conn.execute(
            "update room_collaboration_policies set lead_participant_id = ? "
            "where conversation_id = ?",
            (claude.participant_id, conversation_id),
        )
    ParticipantStore(db).update_status(members["codex"].participant_id, "stopped")
    ParticipantStore(db).update_status(claude.participant_id, "stopped")
    stopped_lead = _post(kernel, conversation_id, "root-stopped-lead")
    assert stopped_lead["activity"]["payload"]["addressing"] == "fallback_broadcast"
    assert [item["participant_id"] for item in stopped_lead["observations"]] == [
        antigravity.participant_id
    ]


def test_addressed_directed_handoff_chain_across_phases_stops_at_depth(tmp_path: Path) -> None:
    db, conversation_id, members = _room(tmp_path, mode="addressed", lead="claude")
    claude, antigravity, codex = (
        members["claude"],
        members["antigravity"],
        members["codex"],
    )
    kernel = RoomKernelStore(db)
    _post(kernel, conversation_id, "chain-root")

    claude_claim = _claim(kernel, conversation_id, claude, "chain-claude-root")
    assert claude_claim is not None and claude_claim["batch"]["phase"] == "root"
    first = _complete(
        kernel,
        conversation_id,
        claude,
        claude_claim,
        "handoff",
        {"content": "research this", "target_participant_ids": [antigravity.participant_id]},
        "chain-hop-1",
        max_causal_depth=3,
    )
    assert [item["participant_id"] for item in first["downstream_observations"]] == [
        antigravity.participant_id
    ]
    assert first["produced_activity"]["payload"]["context_only"] is False

    antigravity_claim = _claim(kernel, conversation_id, antigravity, "chain-antigravity")
    assert antigravity_claim is not None and antigravity_claim["batch"]["phase"] == "peer"
    second = _complete(
        kernel,
        conversation_id,
        antigravity,
        antigravity_claim,
        "handoff",
        {"content": "back to you", "target_participant_ids": [claude.participant_id]},
        "chain-hop-2",
        max_causal_depth=3,
    )
    assert [item["participant_id"] for item in second["downstream_observations"]] == [
        claude.participant_id
    ]

    claude_peer_claim = _claim(kernel, conversation_id, claude, "chain-claude-peer")
    assert claude_peer_claim is not None and claude_peer_claim["batch"]["phase"] == "peer"
    third = _complete(
        kernel,
        conversation_id,
        claude,
        claude_peer_claim,
        "handoff",
        {"content": "one more hop", "target_participant_ids": [antigravity.participant_id]},
        "chain-hop-3",
        max_causal_depth=3,
    )
    assert third["downstream_observations"] == []
    assert third["produced_activity"]["payload"]["context_only"] is True
    assert third["produced_activity"]["payload"]["downstream_mode"] == "context_only"

    assert _observation_count(db, conversation_id, codex.participant_id, peer_only=False) == 0
    assert _observation_count(db, conversation_id, codex.participant_id, peer_only=True) == 0


def test_addressed_untargeted_outcome_fans_out_to_nobody(tmp_path: Path) -> None:
    db, conversation_id, members = _room(tmp_path, mode="addressed", lead="antigravity")
    antigravity, codex = members["antigravity"], members["codex"]
    kernel = RoomKernelStore(db)
    posted = _post(kernel, conversation_id, "untargeted-root")
    assert [item["participant_id"] for item in posted["observations"]] == [
        antigravity.participant_id
    ]

    claim = _claim(kernel, conversation_id, antigravity, "untargeted-antigravity")
    assert claim is not None
    completed = _complete(
        kernel,
        conversation_id,
        antigravity,
        claim,
        "respond",
        {"content": "plain answer without targets"},
        "untargeted-response",
    )
    assert completed["downstream_observations"] == []
    assert completed["produced_activity"]["payload"]["context_only"] is True
    assert _observation_count(db, conversation_id, codex.participant_id, peer_only=False) == 0


def test_addressed_outcome_targets_must_be_active_and_never_self(tmp_path: Path) -> None:
    db, conversation_id, members = _room(tmp_path, mode="addressed", lead="claude")
    claude, antigravity = members["claude"], members["antigravity"]
    kernel = RoomKernelStore(db)
    _post(kernel, conversation_id, "target-root")
    claim = _claim(kernel, conversation_id, claude, "target-claude")
    assert claim is not None

    with pytest.raises(ValueError, match="room_outcome_target_invalid"):
        _complete(
            kernel,
            conversation_id,
            claude,
            claim,
            "handoff",
            {"content": "self baton", "target_participant_ids": [claude.participant_id]},
            "target-self",
        )

    completed = _complete(
        kernel,
        conversation_id,
        claude,
        claim,
        "respond",
        {
            "content": "self mention is skipped",
            "mentioned_participant_ids": [claude.participant_id, antigravity.participant_id],
        },
        "target-self-mention",
    )
    assert [item["participant_id"] for item in completed["downstream_observations"]] == [
        antigravity.participant_id
    ]

    with pytest.raises(ValueError, match="room_outcome_target_invalid"):
        _complete(
            kernel,
            conversation_id,
            antigravity,
            _claim(kernel, conversation_id, antigravity, "target-antigravity"),
            "handoff",
            {"content": "ghost baton", "target_participant_ids": ["part_ghost"]},
            "target-ghost",
        )


def test_addressed_peer_fan_out_respects_the_sixteen_observation_cap(tmp_path: Path) -> None:
    db, conversation_id, members = _room(tmp_path, mode="addressed", lead="claude")
    claude, antigravity = members["claude"], members["antigravity"]
    kernel = RoomKernelStore(db)
    _post(kernel, conversation_id, "cap-root")

    results = []
    for step in range(40):
        claimed = None
        for member in (claude, antigravity):
            claim = _claim(kernel, conversation_id, member, f"cap-{step}-{member.role}")
            if claim is not None:
                claimed = (member, claim)
                break
        if claimed is None:
            break
        member, claim = claimed
        other = antigravity if member is claude else claude
        results.append(
            _complete(
                kernel,
                conversation_id,
                member,
                claim,
                "handoff",
                {
                    "content": f"baton {step}",
                    "target_participant_ids": [other.participant_id],
                },
                f"cap-hop-{step}",
                max_causal_depth=100,
            )
        )

    assert len(results) > 16
    assert _observation_count(db, conversation_id, antigravity.participant_id, peer_only=True) == 16
    assert results[-1]["downstream_observations"] == []
    assert results[-1]["produced_activity"]["payload"]["context_only"] is True


def test_handoff_note_normalization_is_bounded_and_additive() -> None:
    plain = normalize_participant_outcome(
        "handoff",
        {"content": "go", "target_participant_ids": ["part_1"]},
        4,
    )
    assert plain == {
        "content": "go",
        "target_participant_ids": ["part_1"],
        "mentioned_participant_ids": [],
        "priority_participant_ids": ["part_1"],
    }

    note = {
        "what": "Add the migration",
        "why": "Schema drift blocks the release",
        "open_questions": ["Does it lock writes?", "Rollback cost?"],
        "next_action": "Report a bounded plan",
    }
    with_note = normalize_participant_outcome(
        "handoff",
        {"content": "go", "target_participant_ids": ["part_1"], "handoff_note": note},
        4,
    )
    assert with_note["handoff_note"] == note
    proposed = normalize_participant_outcome(
        "propose",
        {
            "proposal_type": "plan",
            "content": "Plan",
            "references": [],
            "handoff_note": {"next_action": "Review the plan"},
        },
        4,
    )
    assert proposed["handoff_note"] == {"next_action": "Review the plan"}

    for bad_payload, bad_type in (
        ({"content": "x", "handoff_note": {}}, "handoff"),
        ({"content": "x", "handoff_note": {"unknown": "x"}}, "handoff"),
        ({"content": "x", "handoff_note": {"what": "   "}}, "handoff"),
        ({"content": "x", "handoff_note": {"what": "y" * 2001}}, "handoff"),
        ({"content": "x", "handoff_note": {"open_questions": "not a list"}}, "handoff"),
        ({"content": "x", "handoff_note": {"open_questions": []}}, "handoff"),
        ({"content": "x", "handoff_note": {"open_questions": ["y" * 2001]}}, "handoff"),
        ({"content": "x", "handoff_note": {"what": "y"}}, "respond"),
        ({"wake_condition": "later", "handoff_note": {"what": "y"}}, "defer"),
        ({"handoff_note": {"what": "y"}}, "noop"),
    ):
        payload = {"target_participant_ids": ["part_1"], **bad_payload}
        with pytest.raises(ValueError, match="room_handoff_note_invalid"):
            normalize_participant_outcome(bad_type, payload, 4)


def test_handoff_note_round_trips_through_mcp_tool_activity_and_projection(
    tmp_path: Path,
) -> None:
    db, conversation_id, members = _room(tmp_path, mode="addressed", lead="claude")
    claude, antigravity = members["claude"], members["antigravity"]
    kernel = RoomKernelStore(db)
    _post(kernel, conversation_id, "note-root")
    claim = _claim(kernel, conversation_id, claude, "note-claude")
    assert claim is not None

    registry_path = tmp_path / "god_sessions.json"
    session = GodSessionRegistry(registry_path).create(
        claude.role,
        claude.display_name,
        "claude",
        "address",
        "inbox",
        conversation_id,
        claude.participant_id,
    )
    from xmuse.room_mcp_server import create_app

    client = TestClient(create_app(tmp_path))
    note = {
        "what": "Research release risks",
        "why": "We lack independent evidence",
        "tradeoffs": "Slower but safer",
        "open_questions": ["Does the migration lock writes?"],
        "next_action": "Report findings with sources",
    }

    def call(payload_note: dict) -> dict:
        response = client.post(
            "/mcp/room",
            json={
                "jsonrpc": "2.0",
                "id": "handoff-note",
                "method": "tools/call",
                "params": {
                    "name": OUTCOME_TOOL,
                    "arguments": {
                        "conversation_id": conversation_id,
                        "participant_id": claude.participant_id,
                        "god_session_id": session.god_session_id,
                        "observation_id": claim["observation"]["observation_id"],
                        "observation_batch_id": claim["batch"]["batch_id"],
                        "lease_token": claim["observation"]["lease_token"],
                        "client_request_id": "mcp-handoff-note",
                        "outcome_type": "handoff",
                        "outcome_payload": {
                            "content": "Please research the release risks.",
                            "target_participant_ids": [antigravity.participant_id],
                            "handoff_note": payload_note,
                        },
                    },
                },
            },
        )
        assert response.status_code == 200
        return response.json()["result"]

    rejected = call({**note, "budget": 1})
    assert rejected["isError"] is True
    assert rejected["structuredContent"]["error"]["code"] == "room_handoff_note_invalid"
    observation = kernel.get_observation(claim["observation"]["observation_id"])
    assert observation["status"] == "claimed"
    assert observation["lease_token"] == claim["observation"]["lease_token"]

    result = call(note)
    assert result["isError"] is False
    durable = result["structuredContent"]
    assert durable["produced_activity"]["payload"]["handoff_note"] == note
    assert [item["participant_id"] for item in durable["downstream_observations"]] == [
        antigravity.participant_id
    ]

    projection = build_room_chat_projection(conversation_id, tmp_path)
    assert projection["collaboration"] == {
        "mode": "addressed",
        "lead_participant_id": claude.participant_id,
    }
    root_item = projection["timeline_items"][0]
    assert root_item["addressing"] == "lead"
    assert "handoff_note" not in root_item
    handoff_items = [item for item in projection["timeline_items"] if item["kind"] == "handoff"]
    assert len(handoff_items) == 1
    assert handoff_items[0]["handoff_note"] == note
    assert handoff_items[0]["target_participant_ids"] == [antigravity.participant_id]

    activities = dict(_activities(db, conversation_id))
    stored = json.loads(activities[handoff_items[0]["activity_id"]])
    assert stored["handoff_note"] == note


def _setup_participants() -> list[dict]:
    return [
        {"role": "architect", "provider_id": "codex", "profile_id": "god", "cli_kind": "codex"},
        {
            "role": "review",
            "provider_id": "claude",
            "cli_kind": "claude",
            "model": "claude-acp-default",
        },
        {"role": "execute", "provider_id": "codex", "profile_id": "worker", "cli_kind": "codex"},
    ]


def test_room_setup_writes_addressed_policy_and_replays_idempotently(tmp_path: Path) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    service = RoomSetupService(tmp_path)
    request = RoomConversationCreate.model_validate(
        {
            "title": "Addressed Room",
            "client_request_id": "setup-addressed",
            "initial_participants": _setup_participants(),
            "collaboration": {"mode": "addressed", "lead_role": "review"},
        }
    )

    first = service.create_conversation(request)
    replay = service.create_conversation(request)
    assert first == replay
    setup = first["setup"]
    assert setup["collaboration"]["mode"] == "addressed"
    by_role = {item["role"]: item for item in first["participants"]}
    assert setup["collaboration"]["lead_participant_id"] == by_role["review"]["participant_id"]

    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute(
            "select mode, lead_participant_id, revision from room_collaboration_policies "
            "where conversation_id = ?",
            (first["id"],),
        ).fetchone() == ("addressed", by_role["review"]["participant_id"], 1)

    projection = build_room_chat_projection(first["id"], tmp_path)
    assert projection["collaboration"] == {
        "mode": "addressed",
        "lead_participant_id": by_role["review"]["participant_id"],
    }

    with pytest.raises(RoomSetupError) as conflict:
        service.create_conversation(
            RoomConversationCreate.model_validate(
                {
                    "title": "Addressed Room",
                    "client_request_id": "setup-addressed",
                    "initial_participants": _setup_participants(),
                    "collaboration": {"mode": "broadcast"},
                }
            )
        )
    assert conflict.value.code == "room_setup_idempotency_conflict"


def test_room_setup_defaults_addressed_lead_to_first_participant(tmp_path: Path) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    service = RoomSetupService(tmp_path)
    created = service.create_conversation(
        RoomConversationCreate.model_validate(
            {
                "title": "Default Lead Room",
                "client_request_id": "setup-default-lead",
                "initial_participants": _setup_participants(),
                "collaboration": {"mode": "addressed"},
            }
        )
    )
    setup = created["setup"]
    by_role = {item["role"]: item for item in created["participants"]}
    assert setup["collaboration"] == {
        "mode": "addressed",
        "lead_participant_id": by_role["architect"]["participant_id"],
    }


def test_room_setup_rejects_unknown_collaboration_lead_without_writes(tmp_path: Path) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    service = RoomSetupService(tmp_path)
    service.create_conversation(
        RoomConversationCreate.model_validate(
            {
                "title": "First Room",
                "client_request_id": "setup-first",
                "initial_participants": _setup_participants(),
            }
        )
    )

    with pytest.raises(RoomSetupError) as excinfo:
        service.create_conversation(
            RoomConversationCreate.model_validate(
                {
                    "title": "Bad Lead Room",
                    "client_request_id": "setup-bad-lead",
                    "initial_participants": _setup_participants(),
                    "collaboration": {"mode": "addressed", "lead_role": "ghost"},
                }
            )
        )
    assert excinfo.value.code == "room_participant_invalid"

    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 1
        assert conn.execute("select count(*) from room_collaboration_policies").fetchone()[0] == 0


def test_heterogeneous_trio_template_expands_to_three_providers_with_addressed_policy(
    tmp_path: Path,
) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    catalog = builtin_workroom_catalog()
    template = catalog.roster_templates["builtin.heterogeneous-trio"]
    assert template.collaboration == RosterCollaboration(mode="addressed", lead_role="architect")
    validated = validate_roster_template(template, catalog=catalog)
    participants = template_to_participant_inits(validated, catalog=catalog)
    assert [item.cli_kind for item in participants] == ["claude", "antigravity", "codex"]
    assert [item.role for item in participants] == ["architect", "research", "review"]
    assert [item.model for item in participants] == ["claude-acp-default", "flash", "gpt-5.6-sol"]
    snapshots = [
        persona_snapshot_for_role_profile(catalog.role_profiles[binding.role_id])
        for binding in validated.roles
    ]
    assert [snapshot.role_description.split(",")[0] for snapshot in snapshots] == [
        "Owns product judgment",
        "Runs fast",
        "Implements and critically reviews backend work with rigorous verification discipline.",
    ]

    created = RoomSetupService(tmp_path).create_conversation(
        RoomConversationCreate.model_validate(
            {
                "title": "Heterogeneous Trio",
                "client_request_id": "setup-trio",
                "roster_template_id": "builtin.heterogeneous-trio",
            }
        )
    )
    by_role = {item["role"]: item for item in created["participants"]}
    assert by_role["architect"]["cli_kind"] == "claude"
    assert by_role["research"]["cli_kind"] == "antigravity"
    assert by_role["review"]["cli_kind"] == "codex"
    assert created["setup"]["collaboration"] == {
        "mode": "addressed",
        "lead_participant_id": by_role["architect"]["participant_id"],
    }

    kernel = RoomKernelStore(tmp_path / "chat.db")
    posted = kernel.post_human_activity(
        conversation_id=created["id"],
        human_id="human",
        content="introduce the trio",
        client_request_id="trio-root",
    )
    assert [item["participant_id"] for item in posted["observations"]] == [
        by_role["architect"]["participant_id"]
    ]
    assert posted["activity"]["payload"]["addressing"] == "lead"

    projection = build_room_chat_projection(created["id"], tmp_path)
    assert projection["collaboration"]["mode"] == "addressed"
    listing = build_room_list_projection(tmp_path)["rooms"][0]
    assert listing["collaboration"]["mode"] == "addressed"

    bad = RosterTemplate(
        template_id="user.bad-lead",
        display_name="Bad Lead",
        description="Invalid lead role.",
        roles=template.roles,
        collaboration=RosterCollaboration(mode="addressed", lead_role="ghost"),
    )
    with pytest.raises(ValueError, match="unknown collaboration lead role: ghost"):
        validate_roster_template(bad, catalog=catalog)


def test_heterogeneous_duo_template_expands_claude_and_antigravity_with_addressed_policy(
    tmp_path: Path,
) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    catalog = builtin_workroom_catalog()
    template = catalog.roster_templates["builtin.heterogeneous-duo"]
    assert template.collaboration == RosterCollaboration(mode="addressed", lead_role="architect")
    validated = validate_roster_template(template, catalog=catalog)
    participants = template_to_participant_inits(validated, catalog=catalog)
    assert [item.cli_kind for item in participants] == ["claude", "antigravity"]
    assert [item.role for item in participants] == ["architect", "research"]
    assert [item.model for item in participants] == ["claude-acp-default", "flash"]

    created = RoomSetupService(tmp_path).create_conversation(
        RoomConversationCreate.model_validate(
            {
                "title": "Heterogeneous Duo",
                "client_request_id": "setup-duo",
                "roster_template_id": "builtin.heterogeneous-duo",
            }
        )
    )
    by_role = {item["role"]: item for item in created["participants"]}
    assert by_role["architect"]["cli_kind"] == "claude"
    assert by_role["research"]["cli_kind"] == "antigravity"
    assert created["setup"]["collaboration"] == {
        "mode": "addressed",
        "lead_participant_id": by_role["architect"]["participant_id"],
    }

    kernel = RoomKernelStore(tmp_path / "chat.db")
    posted = kernel.post_human_activity(
        conversation_id=created["id"],
        human_id="human",
        content="introduce the pair",
        client_request_id="duo-root",
    )
    assert [item["participant_id"] for item in posted["observations"]] == [
        by_role["architect"]["participant_id"]
    ]
    assert posted["activity"]["payload"]["addressing"] == "lead"


def test_collaboration_mode_is_broadcast_for_rooms_without_a_policy_row(tmp_path: Path) -> None:
    db, conversation_id, _members = _room(tmp_path)
    assert isinstance(RoomCollaborationInit(mode="broadcast").mode, str)
    projection = build_room_chat_projection(conversation_id, tmp_path)
    assert projection["collaboration"] == {"mode": "broadcast", "lead_participant_id": None}
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "select count(*) from room_collaboration_policies where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )
