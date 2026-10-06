"""Behaviour tests for rule-assigned cross-family board reviews."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_board import (
    BOARD_REVIEW_RULE_ID,
    TOOL_REVIEW,
    RoomBoardStore,
    assign_cross_family_reviewer,
    normalize_review_findings,
    normalize_review_verdict,
)
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_mcp_contract import (
    ROOM_BOARD_REVIEW_TOOL_NAME,
    ROOM_BOARD_TOOL_NAMES,
    room_tool_schema,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = T0 + timedelta(seconds=10)
DIGEST_A = "sha256:" + "a" * 64


def _mixed_room(tmp_path: Path):
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("review room")
    participants = ParticipantStore(db)
    lead = participants.add(
        conversation_id=conversation.id,
        role="lead",
        display_name="Lead",
        cli_kind="opencode",
        model="m",
    )
    author = participants.add(
        conversation_id=conversation.id,
        role="backend",
        display_name="Backend",
        cli_kind="opencode",
        model="m",
    )
    reviewer = participants.add(
        conversation_id=conversation.id,
        role="frontend",
        display_name="Frontend",
        cli_kind="claude",
        model="m",
    )
    same_family = participants.add(
        conversation_id=conversation.id,
        role="extra",
        display_name="Extra",
        cli_kind="opencode",
        model="m",
    )
    members = [lead, author, reviewer, same_family]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=lead.participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
            review_policy="cross_family",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    return db, conversation.id, members


def _claim(db: Path, conversation_id: str, participant, *, owner: str):
    claimed = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner=owner,
        lease_ttl_s=300.0,
        now=T0,
    )
    assert claimed is not None
    return claimed["observation"]


def _lease_kwargs(participant, observation, *, request_id: str) -> dict[str, Any]:
    return {
        "conversation_id": observation["conversation_id"],
        "participant_id": participant.participant_id,
        "caller_identity": f"god:testsess:{participant.participant_id}",
        "observation_id": observation["observation_id"],
        "lease_token": observation["lease_token"],
        "client_request_id": request_id,
        "now": NOW,
    }


def _split_payload(members):
    lead, author = members[0], members[1]
    modules = [
        {
            "module_id": "alpha",
            "title": "Alpha",
            "paths": ["src/alpha/**"],
            "provides": ["api.alpha"],
            "depends": [],
            "acceptance": ["alpha works"],
            "report_to": lead.participant_id,
        },
    ]
    assignments = {"alpha": author.participant_id}
    contracts = [
        {
            "contract_id": "api.alpha",
            "provider_module_id": "alpha",
            "kind": "api_schema",
            "content": '{"alpha": 1}',
            "rationale": "alpha",
        },
    ]
    return modules, assignments, contracts


def _approved_board(tmp_path: Path):
    db, conversation_id, members = _mixed_room(tmp_path)
    store = RoomBoardStore(db)
    leases = {
        member.participant_id: _claim(db, conversation_id, member, owner=f"host-{i}")
        for i, member in enumerate(members)
    }
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], leases[members[0].participant_id], request_id="p1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    decided = store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    assert decided["status"] == "approved"
    return {
        "db": db,
        "conversation_id": conversation_id,
        "members": members,
        "store": store,
        "leases": leases,
    }


def _pass_alpha(ctx, request_id: str, *, done_at: datetime = NOW):
    owner = ctx["members"][1]
    reported = ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id=request_id),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = ctx["store"].claim_next_board_verification(worker_id="w1", now=done_at)
    assert claimed is not None
    result = ctx["store"].complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=["src/alpha/a.py"],
        gates=[{"gate_id": "g", "status": "passed", "exit_code": 0}],
        evidence={},
        patch_text="diff --git a/src/alpha/a.py b/src/alpha/a.py\n",
        now=done_at + timedelta(seconds=30),
    )
    return reported, result


def _review_row(db: Path, review_id: str) -> dict[str, Any]:
    with RoomDatabase(db).connect(readonly=True) as conn:
        row = conn.execute(
            "select * from room_board_reviews where review_id = ?", (review_id,)
        ).fetchone()
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------------------
# rule function
# ---------------------------------------------------------------------------


def test_rule_excludes_author_and_same_family() -> None:
    picked = assign_cross_family_reviewer(
        author_participant_id="a",
        author_family="opencode",
        candidates=[
            {"participant_id": "a", "family": "opencode"},
            {"participant_id": "b", "family": "opencode"},
            {"participant_id": "c", "family": "claude"},
        ],
        pending_loads={},
        last_reviewer_id=None,
    )
    assert picked == "c"


def test_rule_operator_fallback_when_no_other_family() -> None:
    assert (
        assign_cross_family_reviewer(
            author_participant_id="a",
            author_family="opencode",
            candidates=[{"participant_id": "b", "family": "opencode"}],
            pending_loads={},
            last_reviewer_id=None,
        )
        is None
    )
    assert (
        assign_cross_family_reviewer(
            author_participant_id="a",
            author_family="opencode",
            candidates=[],
            pending_loads={},
            last_reviewer_id=None,
        )
        is None
    )


def test_rule_continuity_beats_load_then_id() -> None:
    candidates = [
        {"participant_id": "c1", "family": "claude"},
        {"participant_id": "c2", "family": "claude"},
    ]
    assert (
        assign_cross_family_reviewer(
            author_participant_id="a",
            author_family="opencode",
            candidates=candidates,
            pending_loads={"c1": 5, "c2": 0},
            last_reviewer_id="c1",
        )
        == "c1"
    )
    # Stale continuity (same family / unknown) is ignored; lowest load wins.
    assert (
        assign_cross_family_reviewer(
            author_participant_id="a",
            author_family="opencode",
            candidates=candidates,
            pending_loads={"c1": 5, "c2": 0},
            last_reviewer_id="b",
        )
        == "c2"
    )
    assert (
        assign_cross_family_reviewer(
            author_participant_id="a",
            author_family="opencode",
            candidates=candidates,
            pending_loads={"c1": 1, "c2": 1},
            last_reviewer_id=None,
        )
        == "c1"
    )


def test_normalize_verdict_object_needs_blocker_or_major() -> None:
    assert normalize_review_verdict("endorse", [{"severity": "minor", "text": "nit"}]) == "endorse"
    assert normalize_review_verdict("object", [{"severity": "major", "text": "wrong"}]) == "object"
    with pytest.raises(ValueError, match="blocker_or_major"):
        normalize_review_verdict("object", [{"severity": "minor", "text": "nit"}])
    with pytest.raises(ValueError, match="blocker_or_major"):
        normalize_review_verdict("object", [])
    with pytest.raises(ValueError, match="findings_invalid"):
        normalize_review_findings([{"severity": "blocker", "text": ""}])
    with pytest.raises(ValueError, match="findings_invalid"):
        normalize_review_findings([{"severity": "nope", "text": "x"}])


# ---------------------------------------------------------------------------
# review created on pass, superseded by newer done
# ---------------------------------------------------------------------------


def test_pass_creates_cross_family_review_with_inputs(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")

    assert result["reviewer_kind"] == "participant"
    assert result["reviewer_participant_id"] == ctx["members"][2].participant_id
    row = _review_row(ctx["db"], result["review_id"])
    assert row["status"] == "pending"
    assert row["rule_id"] == BOARD_REVIEW_RULE_ID
    assert row["author_family"] == "opencode"
    assert row["reviewer_family"] == "claude"
    inputs = json.loads(str(row["rule_inputs_json"]))
    assert inputs["author_family"] == "opencode"
    assert {item["participant_id"]: item["family"] for item in inputs["eligible"]} == {
        ctx["members"][2].participant_id: "claude"
    }
    # Re-derivable: the same inputs pick the same reviewer.
    assert (
        assign_cross_family_reviewer(
            author_participant_id=inputs["author_id"],
            author_family=inputs["author_family"],
            candidates=[
                {
                    "participant_id": item["participant_id"],
                    "family": item["family"],
                }
                for item in inputs["eligible"]
            ],
            pending_loads={item["participant_id"]: item["pending"] for item in inputs["eligible"]},
            last_reviewer_id=inputs["last_reviewer_id"],
        )
        == row["reviewer_participant_id"]
    )
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        activity = conn.execute(
            "select * from room_activities where activity_id = ?",
            (row["request_activity_id"],),
        ).fetchone()
        assert activity is not None
        assert activity["activity_type"] == "board.review_requested"
        assert activity["actor_identity"] == "infrastructure:board-review"
        audience = json.loads(str(activity["audience_json"]))
        assert audience["participant_ids"] == [ctx["members"][2].participant_id]
        woke = conn.execute(
            "select * from room_observations where activity_id = ? and participant_id = ?",
            (row["request_activity_id"], ctx["members"][2].participant_id),
        ).fetchone()
        assert woke is not None


def test_newer_done_supersedes_pending_review(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1", done_at=NOW)
    first_id = result["review_id"]
    owner = ctx["members"][1]
    ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-2"),
        module_id="alpha",
        status="done",
        summary="again",
        claims=[],
    )
    assert _review_row(ctx["db"], first_id)["status"] == "superseded"


def test_failed_verification_creates_no_review(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner = ctx["members"][1]
    reported = ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = ctx["store"].claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    ctx["store"].complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="failed",
        reason_code="owner_patch_empty",
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        now=NOW + timedelta(seconds=30),
    )
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_board_reviews").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# verdict tool
# ---------------------------------------------------------------------------


def _review_lease(ctx, reviewer, *, request_id: str):
    observation = ctx["leases"][reviewer.participant_id]
    return {
        "conversation_id": observation["conversation_id"],
        "participant_id": reviewer.participant_id,
        "caller_identity": f"god:testsess:{reviewer.participant_id}",
        "observation_id": observation["observation_id"],
        "lease_token": observation["lease_token"],
        "client_request_id": request_id,
        "now": NOW + timedelta(seconds=60),
    }


def test_endorse_records_activity_without_wake(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    review_id = result["review_id"]

    # Read material as the reviewer works.
    material = ctx["store"].read(
        **_lease_kwargs(reviewer, ctx["leases"][reviewer.participant_id], request_id="read-1"),
        review_id=review_id,
    )["review_material"]
    assert material["module_id"] == "alpha"
    assert material["patch_text"] is not None
    assert material["charter"]["title"] == "Alpha"

    outcome = ctx["store"].review(
        **_review_lease(ctx, reviewer, request_id="rev-1"),
        review_id=review_id,
        verdict="endorse",
        summary="looks good",
        findings=[{"severity": "minor", "text": "nit"}],
    )
    assert outcome["status"] == "endorsed"
    assert outcome["woken_participant_ids"] == []
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        activity = conn.execute(
            "select * from room_activities where activity_id = ?",
            (outcome["activity_id"],),
        ).fetchone()
        assert activity["activity_type"] == "board.review"
        audience = json.loads(str(activity["audience_json"]))
        assert audience["participant_ids"] == [ctx["members"][0].participant_id]
    assert _review_row(ctx["db"], review_id)["status"] == "endorsed"


def test_object_wakes_author_and_requires_severity(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    review_id = result["review_id"]
    with pytest.raises(ValueError, match="blocker_or_major"):
        ctx["store"].review(
            **_review_lease(ctx, reviewer, request_id="rev-bad"),
            review_id=review_id,
            verdict="object",
            summary="bad",
            findings=[{"severity": "minor", "text": "nit"}],
        )
    outcome = ctx["store"].review(
        **_review_lease(ctx, reviewer, request_id="rev-1"),
        review_id=review_id,
        verdict="object",
        summary="wrong contract",
        findings=[{"severity": "blocker", "text": "breaks api"}],
    )
    assert outcome["status"] == "objected"
    assert outcome["woken_participant_ids"] == [ctx["members"][1].participant_id]
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        activity = conn.execute(
            "select * from room_activities where activity_id = ?",
            (outcome["activity_id"],),
        ).fetchone()
        audience = json.loads(str(activity["audience_json"]))
        assert ctx["members"][1].participant_id in audience["participant_ids"]


def test_only_assigned_reviewer_can_rule_or_read(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    review_id = result["review_id"]
    stranger = ctx["members"][3]
    with pytest.raises(ValueError, match="room_board_review_forbidden"):
        ctx["store"].review(
            **_review_lease(ctx, stranger, request_id="rev-x"),
            review_id=review_id,
            verdict="endorse",
            summary="me too",
            findings=[],
        )
    with pytest.raises(ValueError, match="room_board_review_forbidden"):
        ctx["store"].read(
            **_lease_kwargs(stranger, ctx["leases"][stranger.participant_id], request_id="read-x"),
            review_id=review_id,
        )
    # The author may read but may not rule.
    author = ctx["members"][1]
    material = ctx["store"].read(
        **_lease_kwargs(author, ctx["leases"][author.participant_id], request_id="read-a"),
        review_id=review_id,
    )["review_material"]
    assert material["review_id"] == review_id
    with pytest.raises(ValueError, match="room_board_review_forbidden"):
        ctx["store"].review(
            **_review_lease(ctx, author, request_id="rev-a"),
            review_id=review_id,
            verdict="endorse",
            summary="self approve",
            findings=[],
        )


def test_review_replay_is_idempotent(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    kwargs = {
        **_review_lease(ctx, reviewer, request_id="rev-same"),
        "review_id": result["review_id"],
        "verdict": "endorse",
        "summary": "good",
        "findings": [],
    }
    first = ctx["store"].review(**kwargs)
    second = ctx["store"].review(**kwargs)
    assert first == second


def test_second_verdict_after_decision_is_rejected(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    ctx["store"].review(
        **_review_lease(ctx, reviewer, request_id="rev-1"),
        review_id=result["review_id"],
        verdict="endorse",
        summary="good",
        findings=[],
    )
    with pytest.raises(ValueError, match="room_board_review_decided"):
        ctx["store"].review(
            **_review_lease(ctx, reviewer, request_id="rev-2"),
            review_id=result["review_id"],
            verdict="endorse",
            summary="again",
            findings=[],
        )


def test_operator_fallback_and_projection_counters(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("solo family")
    participants = ParticipantStore(db)
    lead = participants.add(
        conversation_id=conversation.id,
        role="lead",
        display_name="Lead",
        cli_kind="opencode",
        model="m",
    )
    author = participants.add(
        conversation_id=conversation.id,
        role="backend",
        display_name="Backend",
        cli_kind="opencode",
        model="m",
    )
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=lead.participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
            review_policy="cross_family",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation.id, lead, owner="h0")
    author_obs = _claim(db, conversation.id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation.id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    result = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        now=NOW + timedelta(seconds=30),
    )
    assert result["reviewer_kind"] == "operator"
    row = _review_row(db, result["review_id"])
    assert row["reviewer_participant_id"] is None
    with RoomDatabase(db).connect(readonly=True) as conn:
        activity = conn.execute(
            "select * from room_activities where activity_id = ?",
            (row["request_activity_id"],),
        ).fetchone()
        audience = json.loads(str(activity["audience_json"]))
        assert audience["participant_ids"] == [lead.participant_id]
        woke = conn.execute(
            "select count(*) from room_observations where activity_id = ?",
            (row["request_activity_id"],),
        ).fetchone()[0]
        assert woke == 0

    material = store.review_material(conversation.id, result["review_id"])
    decided = store.decide_review(
        conversation_id=conversation.id,
        review_id=result["review_id"],
        verdict="endorse",
        summary="human ok",
        findings=[],
        expected_digest=material["digest"],
        operator_identity="operator:local",
    )
    assert decided["status"] == "endorsed"
    row = _review_row(db, result["review_id"])
    verdict = json.loads(str(row["verdict_json"]))
    assert verdict["decided_via"] == "web"
    assert verdict["operator_identity"] == "operator:local"

    view = store.owner_view(conversation.id, author.participant_id)
    assert view["my_modules"][0]["review"]["status"] == "endorsed"


def test_application_review_reports_lease_errors(tmp_path: Path) -> None:
    from xmuse_core.chat.room_errors import RoomApplicationError

    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    service = RoomApplicationService(ctx["db"], tmp_path / "god_sessions.json")
    with pytest.raises(RoomApplicationError) as exc_info:
        service.board_review(
            conversation_id=ctx["conversation_id"],
            participant_id=reviewer.participant_id,
            god_session_id="missing",
            observation_id="nope",
            lease_token="nope",
            client_request_id="r1",
            review_id=result["review_id"],
            verdict="endorse",
            summary="x",
            findings=[],
        )
    assert exc_info.value.code


# ---------------------------------------------------------------------------
# MCP surface and operator HTTP
# ---------------------------------------------------------------------------


def test_review_tool_registered_with_exact_schema() -> None:
    assert ROOM_BOARD_REVIEW_TOOL_NAME in ROOM_BOARD_TOOL_NAMES
    assert TOOL_REVIEW == ROOM_BOARD_REVIEW_TOOL_NAME
    schema = room_tool_schema(ROOM_BOARD_REVIEW_TOOL_NAME)
    assert schema is not None
    required = schema["inputSchema"]["required"]
    for field in (
        "conversation_id",
        "participant_id",
        "god_session_id",
        "observation_id",
        "lease_token",
        "client_request_id",
        "review_id",
        "verdict",
        "summary",
    ):
        assert field in required
    assert schema["inputSchema"]["properties"]["verdict"]["enum"] == [
        "endorse",
        "object",
    ]


def test_claude_read_only_profile_approves_review_exact_title() -> None:
    import asyncio

    from tests.xmuse.test_room_acp_transport import _is_allowed, _permission_transport
    from xmuse_core.chat.room_acp_transport import CLAUDE_ACP_PROFILE

    async def _scenario(tmp_path: Path) -> None:
        _transport, client = _permission_transport(tmp_path, CLAUDE_ACP_PROFILE)
        assert await _is_allowed(client, "sess-1", f"mcp__xmuse-room__{TOOL_REVIEW}") is True
        assert (
            await _is_allowed(
                client,
                "sess-1",
                "mcp__other__tool",
                raw_input=f"mcp__xmuse-room__{TOOL_REVIEW}",
            )
            is False
        )

    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(_scenario(Path(directory)))


def test_operator_review_endpoint_requires_token_and_records_web(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from xmuse.chat_api import create_app

    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("solo family")
    participants = ParticipantStore(db)
    lead = participants.add(
        conversation_id=conversation.id,
        role="lead",
        display_name="Lead",
        cli_kind="opencode",
        model="m",
    )
    author = participants.add(
        conversation_id=conversation.id,
        role="backend",
        display_name="Backend",
        cli_kind="opencode",
        model="m",
    )
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=lead.participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
            review_policy="cross_family",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation.id, lead, owner="h0")
    author_obs = _claim(db, conversation.id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation.id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    completed = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        now=NOW + timedelta(seconds=30),
    )
    review_id = completed["review_id"]
    client = TestClient(
        create_app(
            tmp_path,
            auth_token="operator-secret",
            workroom_runtime_inspector=lambda *_args: {
                "state": "ready",
                "code": "ready",
                "ready": True,
            },
        )
    )
    path = f"/api/chat/operator/board-reviews/{review_id}/decision"
    material = store.review_material(conversation.id, review_id)
    body = {
        "conversation_id": conversation.id,
        "expected_digest": material["digest"],
        "verdict": "object",
        "summary": "human found a blocker",
        "findings": [{"severity": "blocker", "text": "wrong"}],
    }
    assert client.post(path, json=body).status_code == 401
    denied = client.post(path, json=body, headers={"X-XMuse-Operator-Token": "wrong"})
    assert denied.status_code == 401
    decided = client.post(path, json=body, headers={"X-XMuse-Operator-Token": "operator-secret"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "objected"
    verdict = json.loads(str(_review_row(db, review_id)["verdict_json"]))
    assert verdict["decided_via"] == "web"


def _operator_review_room(tmp_path: Path):
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("operator review room")
    participants = ParticipantStore(db)
    lead = participants.add(
        conversation_id=conversation.id,
        role="lead",
        display_name="Lead",
        cli_kind="opencode",
        model="m",
    )
    author = participants.add(
        conversation_id=conversation.id,
        role="backend",
        display_name="Backend",
        cli_kind="opencode",
        model="m",
    )
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=lead.participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
            review_policy="cross_family",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    return db, conversation.id, [lead, author]


def test_tamper_stored_patch_bytes_fails_digest_and_changes_nothing(tmp_path: Path) -> None:
    db, conversation_id, members = _operator_review_room(tmp_path)
    store = RoomBoardStore(db)
    lead, author = members
    lead_obs = _claim(db, conversation_id, lead, owner="h0")
    author_obs = _claim(db, conversation_id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    completed = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        patch_text="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        now=NOW + timedelta(seconds=30),
    )
    review_id = completed["review_id"]
    material = store.review_material(conversation_id, review_id)
    expected_digest = material["digest"]

    # Tamper the stored patch bytes directly in SQLite
    with RoomDatabase(db).connect() as conn:
        conn.execute(
            "update room_board_verifications set patch_text = 'tampered' where verification_id = ?",
            (reported["verification_id"],),
        )
        conn.commit()

    # Decision with the previously valid expected_digest must fail
    with pytest.raises(ValueError, match="room_board_review_digest_mismatch"):
        store.decide_review(
            conversation_id=conversation_id,
            review_id=review_id,
            verdict="endorse",
            summary="ok",
            findings=[],
            expected_digest=expected_digest,
            operator_identity="operator:host",
            now=NOW + timedelta(seconds=60),
        )

    # Review status must remain pending and change nothing
    row = _review_row(db, review_id)
    assert row["status"] == "pending"
    assert row["verdict_json"] is None


def test_finding_path_rejects_unicode_format_characters() -> None:
    for bad in ("src/\u202etest.py", "src/\u200btest.py", "src/\ufefftest.py"):
        with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
            normalize_review_findings([{"severity": "minor", "path": bad, "text": "issue"}])


def test_stored_path_violating_rule_emitted_as_null_in_projection_detail_and_owner_view(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from xmuse.chat_api import create_app
    from xmuse_core.chat.room_board_projection import build_board_projection

    db, conversation_id, members = _mixed_room(tmp_path)
    store = RoomBoardStore(db)
    lead, author, _, _ = members
    lead_obs = _claim(db, conversation_id, lead, owner="h0")
    author_obs = _claim(db, conversation_id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    completed = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        patch_text="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        now=NOW + timedelta(seconds=30),
    )
    review_id = completed["review_id"]

    # Directly insert a verdict with an invalid path (U+202E) into SQLite,
    # bypassing input validation
    invalid_path = "src/\u202einvalid.py"
    verdict_payload = {
        "verdict": "object",
        "summary": "found issue",
        "findings": [{"severity": "blocker", "path": invalid_path, "text": "bad"}],
        "decided_via": "web",
    }
    with RoomDatabase(db).connect() as conn:
        conn.execute(
            """update room_board_reviews
               set status = 'objected', verdict_json = ?, updated_at = ?
               where review_id = ?""",
            (json.dumps(verdict_payload), "2026-01-01T00:01:00.000000Z", review_id),
        )
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, causation_id, correlation_id, visibility, audience_json,
                causal_depth, delivery_mode, payload_json, created_at)
               values (?, ?, 999, 'board.review', 'operator',
                       'operator:host', 'cause_1', 'corr_1', 'room', '[]',
                       1, 'active', ?, '2026-01-01T00:01:00.000000Z')""",
            (
                "act_review_invalid_path",
                conversation_id,
                json.dumps(
                    {
                        "schema_version": "room_board_activity/v1",
                        "review_id": review_id,
                        "module_id": "alpha",
                        "verification_id": reported["verification_id"],
                        "verdict": "object",
                        "summary": "found issue",
                        "findings": [{"severity": "blocker", "path": invalid_path, "text": "bad"}],
                        "decided_via": "web",
                    }
                ),
            ),
        )
        conn.commit()

    # 1. Output filter in owner view
    owner_view = store.owner_view(conversation_id, author.participant_id)
    assert owner_view["my_modules"][0]["review"]["verdict"]["findings"][0]["path"] is None

    # 2. Output filter in review detail route
    detail = store.review_detail(conversation_id, review_id)
    assert detail["findings"][0]["path"] is None

    client = TestClient(create_app(tmp_path, auth_token="operator-secret"))
    route_res = client.get(f"/api/chat/conversations/{conversation_id}/board/reviews/{review_id}")
    assert route_res.status_code == 200
    assert route_res.json()["findings"][0]["path"] is None

    # 3. Output filter in projection event
    with RoomDatabase(db).connect(readonly=True) as conn:
        proj = build_board_projection(conn, conversation_id, now=NOW)
    rev_events = [e for e in proj["events"] if e["kind"] == "review"]
    assert len(rev_events) == 1
    assert rev_events[0]["data"]["findings"][0]["path"] is None


def test_board_decide_review_without_expected_digest_fails(tmp_path: Path) -> None:
    from xmuse_core.chat.room_errors import RoomApplicationError

    db, conversation_id, members = _operator_review_room(tmp_path)
    store = RoomBoardStore(db)
    lead, author = members
    lead_obs = _claim(db, conversation_id, lead, owner="h0")
    author_obs = _claim(db, conversation_id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    completed = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        patch_text="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        now=NOW + timedelta(seconds=30),
    )
    review_id = completed["review_id"]

    service = RoomApplicationService(db, tmp_path / "god_sessions.json")
    with pytest.raises(RoomApplicationError) as exc_info:
        service.board_decide_review(
            conversation_id=conversation_id,
            review_id=review_id,
            verdict="endorse",
            summary="ok",
            findings=[],
            expected_digest=None,
            operator_identity="operator:host",
        )
    assert exc_info.value.code == "room_board_review_digest_mismatch"


def test_room_setup_replay_fingerprint_preserves_without_review_policy() -> None:
    from xmuse_core.chat.room_setup import (
        _CollaborationSpec,
        _ParticipantSpec,
        _request_fingerprint,
    )

    specs = [
        _ParticipantSpec(
            role="lead",
            display_name="Lead",
            cli_kind="opencode",
            model="m",
            role_template_id=None,
            workspace_access="read_only",
            persona_snapshot=None,
        )
    ]
    collab_off = _CollaborationSpec(mode="broadcast", lead_index=0, review_policy="off")
    fp_off = _request_fingerprint(
        title="test-topic", roster_template_id=None, specs=specs, collaboration=collab_off
    )

    collab_xfam = _CollaborationSpec(mode="broadcast", lead_index=0, review_policy="cross_family")
    fp_xfam = _request_fingerprint(
        title="test-topic", roster_template_id=None, specs=specs, collaboration=collab_xfam
    )

    assert fp_off != fp_xfam


def _claim_review_request(ctx, reviewer):
    """End the reviewer's kickoff turn, then claim the delivery that carries the request."""

    kernel = RoomKernelStore(ctx["db"])
    kernel.submit_participant_outcome(
        **_lease_kwargs(reviewer, ctx["leases"][reviewer.participant_id], request_id="kick"),
        outcome_type="noop",
    )
    claimed = kernel.claim_next_observation_batch(
        conversation_id=ctx["conversation_id"],
        participant_id=reviewer.participant_id,
        lease_owner="host-review",
        lease_ttl_s=300.0,
        now=NOW + timedelta(seconds=40),
    )
    assert claimed is not None
    return claimed["observation"]


def _review_outcome(reviewer, observation, *, request_id: str) -> dict[str, Any]:
    return {
        **_lease_kwargs(reviewer, observation, request_id=request_id),
        "now": NOW + timedelta(seconds=60),
    }


def test_review_delivery_outcome_requires_verdict_first(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    observation = _claim_review_request(ctx, reviewer)
    kernel = RoomKernelStore(ctx["db"])

    # Prose is never a verdict: ending the review turn without ruling is refused, and the
    # refusal names the tool and the review so the agent can correct itself in the same turn.
    with pytest.raises(ValueError, match="room_outcome_review_verdict_required") as refused:
        kernel.submit_participant_outcome(
            **_review_outcome(reviewer, observation, request_id="out-1"), outcome_type="noop"
        )
    assert "chat_room_board_review" in str(refused.value)
    assert result["review_id"] in str(refused.value)
    assert _review_row(ctx["db"], result["review_id"])["status"] == "pending"

    ctx["store"].review(
        **_review_outcome(reviewer, observation, request_id="rev-1"),
        review_id=result["review_id"],
        verdict="endorse",
        summary="looks good",
        findings=[],
    )
    completed = kernel.submit_participant_outcome(
        **_review_outcome(reviewer, observation, request_id="out-2"), outcome_type="noop"
    )
    assert completed["observation"]["status"] == "completed"


def test_review_delivery_defer_stays_available_without_verdict(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    _reported, result = _pass_alpha(ctx, "done-1")
    reviewer = ctx["members"][2]
    observation = _claim_review_request(ctx, reviewer)

    deferred = RoomKernelStore(ctx["db"]).submit_participant_outcome(
        **_review_outcome(reviewer, observation, request_id="out-defer"),
        outcome_type="defer",
        outcome_payload={"wake_condition": "need the owner to answer a question first"},
    )

    assert deferred["observation"]["status"] == "completed"
    assert _review_row(ctx["db"], result["review_id"])["status"] == "pending"


def test_cancelled_observation_escalates_as_reviewer_unavailable(tmp_path: Path) -> None:
    db, conversation_id, members = _mixed_room(tmp_path)
    store = RoomBoardStore(db)
    lead, author, reviewer, _ = members
    lead_obs = _claim(db, conversation_id, lead, owner="h0")
    author_obs = _claim(db, conversation_id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    completed = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        patch_text="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        now=NOW + timedelta(seconds=30),
    )
    review_id = completed["review_id"]
    rev_row = _review_row(db, review_id)
    assert rev_row["status"] == "pending"
    assert rev_row["reviewer_kind"] == "participant"
    req_act_id = rev_row["request_activity_id"]

    with RoomDatabase(db).connect() as conn:
        conn.execute(
            """update room_observations set control_state = 'cancelled'
               where activity_id = ? and participant_id = ?""",
            (req_act_id, reviewer.participant_id),
        )
        conn.commit()

    escalated = store.escalate_stale_reviews(now=NOW + timedelta(seconds=60), response_seconds=3600)
    assert len(escalated) == 1
    assert escalated[0]["review_id"] == review_id
    assert escalated[0]["reason_code"] == "board_review_reviewer_unavailable"

    updated_row = _review_row(db, review_id)
    assert updated_row["reviewer_kind"] == "operator"
    esc_data = json.loads(str(updated_row["escalation_json"]))
    assert esc_data["reason_code"] == "board_review_reviewer_unavailable"


def test_revision_changes_after_escalate_stale_reviews(tmp_path: Path) -> None:
    from xmuse_core.chat.room_board_projection import build_board_projection

    db, conversation_id, members = _mixed_room(tmp_path)
    store = RoomBoardStore(db)
    lead, author, reviewer, _ = members
    lead_obs = _claim(db, conversation_id, lead, owner="h0")
    author_obs = _claim(db, conversation_id, author, owner="h1")
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="p1"),
        modules=[
            {
                "module_id": "alpha",
                "title": "Alpha",
                "paths": ["src/alpha/**"],
                "provides": [],
                "depends": [],
                "acceptance": ["ok"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={"alpha": author.participant_id},
        contracts=[],
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    reported = store.report_progress(
        **_lease_kwargs(author, author_obs, request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    completed = store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        patch_text="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        now=NOW + timedelta(seconds=30),
    )
    review_id = completed["review_id"]
    rev_row = _review_row(db, review_id)
    req_act_id = rev_row["request_activity_id"]

    with RoomDatabase(db).connect(readonly=True) as conn:
        proj_before = build_board_projection(conn, conversation_id, now=NOW)
    revision_before = proj_before["revision"]

    with RoomDatabase(db).connect() as conn:
        conn.execute(
            """update room_observations set status = 'completed'
               where activity_id = ? and participant_id = ?""",
            (req_act_id, reviewer.participant_id),
        )
        conn.commit()

    store.escalate_stale_reviews(now=NOW + timedelta(seconds=60), response_seconds=3600)

    with RoomDatabase(db).connect(readonly=True) as conn:
        proj_after = build_board_projection(conn, conversation_id, now=NOW)
    revision_after = proj_after["revision"]

    assert revision_before != revision_after
