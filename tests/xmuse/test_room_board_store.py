"""Behaviour tests for the Room coordination board store."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_board import (
    RoomBoardStore,
    contract_digest,
    normalize_charter,
)
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.runtime.sqlite_connection import ClosingConnection

T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = T0 + timedelta(seconds=10)


def _board_room(tmp_path: Path, count: int = 3):
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("board room")
    participants = ParticipantStore(db)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(count)
    ]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=members[0].participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
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


def _lease_kwargs(
    participant, observation, *, request_id: str, now: datetime = NOW
) -> dict[str, Any]:
    return {
        "conversation_id": observation["conversation_id"],
        "participant_id": participant.participant_id,
        "caller_identity": f"god:testsess:{participant.participant_id}",
        "observation_id": observation["observation_id"],
        "lease_token": observation["lease_token"],
        "client_request_id": request_id,
        "now": now,
    }


def _split_payload(members):
    lead, owner_a, owner_b = members[0], members[1], members[2]
    modules = [
        {
            "module_id": "alpha",
            "title": "Alpha module",
            "paths": ["src/alpha/**"],
            "provides": ["api.alpha"],
            "depends": [],
            "acceptance": ["alpha works"],
            "report_to": lead.participant_id,
        },
        {
            "module_id": "beta",
            "title": "Beta module",
            "paths": ["src/beta/**"],
            "provides": ["api.beta"],
            "depends": ["api.alpha"],
            "acceptance": ["beta works"],
            "report_to": lead.participant_id,
        },
    ]
    assignments = {
        "alpha": owner_a.participant_id,
        "beta": owner_b.participant_id,
    }
    contracts = [
        {
            "contract_id": "api.alpha",
            "provider_module_id": "alpha",
            "kind": "api_schema",
            "content": '{"alpha": 1}',
            "rationale": "alpha surface",
        },
        {
            "contract_id": "api.beta",
            "provider_module_id": "beta",
            "kind": "types",
            "content": "type Beta = string;",
            "rationale": "beta surface",
        },
    ]
    return modules, assignments, contracts


def _approved_board(tmp_path: Path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    obs_a = _claim(db, conversation_id, members[1], owner="host-a")
    obs_b = _claim(db, conversation_id, members[2], owner="host-b")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-1"),
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
        "leases": {
            members[0].participant_id: lead_obs,
            members[1].participant_id: obs_a,
            members[2].participant_id: obs_b,
        },
        "split_id": proposed["split_id"],
    }


def test_newer_split_proposal_supersedes_the_pending_one(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    first = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-first"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    second = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-second"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    with RoomDatabase(db).connect() as conn:
        statuses = dict(
            conn.execute(
                "select split_id, status from room_board_splits where conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        )
    assert statuses == {first["split_id"]: "superseded", second["split_id"]: "proposed"}
    with pytest.raises(ValueError, match="room_board_split_decided"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=first["split_id"],
            decision="approve",
            operator_identity="operator:host",
        )
    assert (
        store.decide_split(
            conversation_id=conversation_id,
            split_id=second["split_id"],
            decision="approve",
            operator_identity="operator:host",
        )["status"]
        == "approved"
    )


def test_board_wake_up_is_deliverable_with_visible_content(tmp_path):
    """A charter wake-up must pass the host's Skill binding like any other delivery."""
    from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
    from xmuse_core.skills.catalog import SkillCatalog

    ctx = _approved_board(tmp_path)
    db, conversation_id, members = ctx["db"], ctx["conversation_id"], ctx["members"]
    owner_a = members[1]
    kickoff = ctx["leases"][owner_a.participant_id]
    RoomKernelStore(db).submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=owner_a.participant_id,
        caller_identity=f"god:testsess:{owner_a.participant_id}",
        observation_id=kickoff["observation_id"],
        lease_token=kickoff["lease_token"],
        client_request_id="kickoff-noop",
        outcome_type="noop",
        now=NOW,
    )
    later = NOW + timedelta(seconds=5)
    claimed = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=owner_a.participant_id,
        lease_owner="host-a2",
        lease_ttl_s=300.0,
        now=later,
    )
    assert claimed is not None
    activity = claimed["activity"]
    assert activity["activity_type"] == "board.charter_assigned"
    assert "you now own module alpha" in activity["payload"]["content"]
    RoomAttemptSkillDecisionStore(db).bind_for_attempt(
        attempt_id=claimed["observation"]["current_attempt_id"],
        catalog=SkillCatalog.load_bundled(),
        now=later,
    )
    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select payload_json from room_activities where activity_type like 'board.%'"
        ).fetchall()
    assert all(json.loads(row["payload_json"])["content"] for row in rows)


def _board_activity_count(db: Path, conversation_id: str) -> int:
    with RoomDatabase(db).connect() as conn:
        row = conn.execute(
            "select count(*) from room_activities where conversation_id = ? "
            "and activity_type like 'board.%'",
            (conversation_id,),
        ).fetchone()
    return int(row[0])


def _pending_observations(
    db: Path, conversation_id: str, participant_id: str
) -> list[dict[str, Any]]:
    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select * from room_observations where conversation_id = ? "
            "and participant_id = ? and status = 'pending' order by rowid",
            (conversation_id, participant_id),
        ).fetchall()
    return [dict(row) for row in rows]


def _pending_for_activity(
    db: Path, conversation_id: str, participant_id: str, activity_id: str
) -> list[dict[str, Any]]:
    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select * from room_observations where conversation_id = ? "
            "and participant_id = ? and activity_id = ? and status = 'pending' "
            "order by rowid",
            (conversation_id, participant_id, activity_id),
        ).fetchall()
    return [dict(row) for row in rows]


def test_charter_normalizer_rejects_bad_charters():
    good = {
        "module_id": "alpha",
        "title": "Alpha",
        "paths": ["src/alpha/**"],
        "provides": ["api.alpha"],
        "depends": [],
        "acceptance": ["done"],
        "report_to": None,
    }
    assert normalize_charter(dict(good))["module_id"] == "alpha"
    with pytest.raises(ValueError, match="room_board_charter_invalid"):
        normalize_charter({**good, "bogus": 1})
    with pytest.raises(ValueError, match="room_board_charter_invalid"):
        normalize_charter({**good, "module_id": "Alpha"})
    with pytest.raises(ValueError, match="room_board_charter_invalid"):
        normalize_charter({**good, "paths": ["/absolute"]})
    with pytest.raises(ValueError, match="room_board_charter_invalid"):
        normalize_charter({**good, "paths": ["../escape"]})
    with pytest.raises(ValueError, match="room_board_charter_invalid"):
        normalize_charter({**good, "paths": []})
    with pytest.raises(ValueError, match="room_board_charter_invalid"):
        normalize_charter({**good, "provides": ["Bad Id"]})


def test_every_write_rejects_stale_foreign_and_expired_leases(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    lead, owner_a, owner_b = members
    leases = ctx["leases"]
    modules, assignments, contracts = _split_payload(members)

    calls = [
        lambda kw: store.propose_split(
            **kw, modules=modules, assignments=assignments, contracts=contracts
        ),
        lambda kw: store.claim(**kw, module_id="alpha"),
        lambda kw: store.publish_contract(
            **kw,
            contract_id="api.alpha",
            kind="api_schema",
            content='{"alpha": 2}',
            base_version=1,
            rationale="revise",
        ),
        lambda kw: store.report_progress(
            **kw, module_id="alpha", status="working", summary="on it", claims=[]
        ),
        lambda kw: store.ask(
            **kw,
            target_participant_id=owner_b.participant_id,
            question="how?",
            references=[],
        ),
    ]
    # Each call below runs as owner_a against owner_a's lease, except propose
    # which runs as the lead against the lead lease.
    lease_pairs = [(lead, leases[lead.participant_id])] + [
        (owner_a, leases[owner_a.participant_id])
    ] * 4

    for index, (call, (who, obs)) in enumerate(zip(calls, lease_pairs, strict=True)):
        base = _lease_kwargs(who, obs, request_id=f"lease-bad-{index}")
        stale = dict(base, lease_token="wrong-token", client_request_id=f"lease-stale-{index}")
        with pytest.raises(ValueError, match="room_observation_lease_lost"):
            call(stale)
        other_id = owner_b.participant_id if who != owner_b else owner_a.participant_id
        foreign_obs = leases[other_id]
        foreign = dict(
            base,
            observation_id=foreign_obs["observation_id"],
            client_request_id=f"lease-foreign-{index}",
        )
        with pytest.raises(ValueError, match="room_observation_lease_lost"):
            call(foreign)
        expired = dict(base, now=T0 + timedelta(seconds=900))
        with pytest.raises(ValueError, match="room_observation_lease_lost"):
            call(expired)

    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        store.read(
            **_lease_kwargs(
                owner_a,
                leases[owner_a.participant_id],
                request_id="read-expired",
                now=T0 + timedelta(seconds=900),
            )
        )
    assert _board_activity_count(db, conversation_id) == 3  # propose + 2 assignments


def test_every_write_is_idempotent_with_conflict_detection(tmp_path):
    ctx = _approved_board(tmp_path)
    members, store = ctx["members"], ctx["store"]
    lead, owner_a, owner_b = members
    leases = ctx["leases"]

    before = _board_activity_count(ctx["db"], ctx["conversation_id"])
    propose_kwargs = _lease_kwargs(lead, leases[lead.participant_id], request_id="idem-propose")
    # The board already holds alpha/beta, so the re-proposal uses fresh ids.
    modules, assignments, contracts = _renamed_split(*_split_payload(members), suffix="2")
    first = store.propose_split(
        **propose_kwargs, modules=modules, assignments=assignments, contracts=contracts
    )
    assert (
        store.propose_split(
            **propose_kwargs, modules=modules, assignments=assignments, contracts=contracts
        )
        == first
    )
    assert _board_activity_count(ctx["db"], ctx["conversation_id"]) == before + 1
    with pytest.raises(ValueError, match="room_board_idempotency_conflict"):
        store.propose_split(
            **_lease_kwargs(lead, leases[lead.participant_id], request_id="idem-propose"),
            modules=[{**modules[0], "title": "Changed"}] + modules[1:],
            assignments=assignments,
            contracts=contracts,
        )

    claim_kwargs = _lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-claim")
    claimed = store.claim(**claim_kwargs, module_id="alpha")
    assert store.claim(**claim_kwargs, module_id="alpha") == claimed
    assert _board_activity_count(ctx["db"], ctx["conversation_id"]) == before + 2
    with pytest.raises(ValueError, match="room_board_idempotency_conflict"):
        store.claim(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-claim"),
            module_id="beta",
        )

    publish_kwargs = _lease_kwargs(
        owner_a, leases[owner_a.participant_id], request_id="idem-publish"
    )
    published = store.publish_contract(
        **publish_kwargs,
        contract_id="api.alpha",
        kind="api_schema",
        content='{"alpha": 2}',
        base_version=1,
        rationale="revise",
    )
    assert published["version"] == 2
    assert (
        store.publish_contract(
            **publish_kwargs,
            contract_id="api.alpha",
            kind="api_schema",
            content='{"alpha": 2}',
            base_version=1,
            rationale="revise",
        )
        == published
    )
    assert _board_activity_count(ctx["db"], ctx["conversation_id"]) == before + 3
    with pytest.raises(ValueError, match="room_board_idempotency_conflict"):
        store.publish_contract(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-publish"),
            contract_id="api.alpha",
            kind="api_schema",
            content='{"alpha": 3}',
            base_version=1,
            rationale="revise",
        )

    report_kwargs = _lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-report")
    reported = store.report_progress(
        **report_kwargs, module_id="alpha", status="working", summary="on it", claims=[]
    )
    assert (
        store.report_progress(
            **report_kwargs, module_id="alpha", status="working", summary="on it", claims=[]
        )
        == reported
    )
    assert _board_activity_count(ctx["db"], ctx["conversation_id"]) == before + 4
    with pytest.raises(ValueError, match="room_board_idempotency_conflict"):
        store.report_progress(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-report"),
            module_id="alpha",
            status="working",
            summary="changed",
            claims=[],
        )

    ask_kwargs = _lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-ask")
    asked = store.ask(
        **ask_kwargs,
        target_participant_id=owner_b.participant_id,
        question="how?",
        references=[],
    )
    assert (
        store.ask(
            **ask_kwargs,
            target_participant_id=owner_b.participant_id,
            question="how?",
            references=[],
        )
        == asked
    )
    assert _board_activity_count(ctx["db"], ctx["conversation_id"]) == before + 5
    with pytest.raises(ValueError, match="room_board_idempotency_conflict"):
        store.ask(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="idem-ask"),
            target_participant_id=owner_b.participant_id,
            question="changed?",
            references=[],
        )


def test_propose_split_requires_lead_and_consistent_shape(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    other_obs = _claim(db, conversation_id, members[1], owner="host-a")
    modules, assignments, contracts = _split_payload(members)

    with pytest.raises(ValueError, match="room_board_lead_required"):
        store.propose_split(
            **_lease_kwargs(members[1], other_obs, request_id="non-lead"),
            modules=modules,
            assignments=assignments,
            contracts=contracts,
        )
    bad_assignments = dict(assignments, alpha="participant_missing")
    with pytest.raises(ValueError, match="room_board_assignee_unknown"):
        store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id="bad-assignee"),
            modules=modules,
            assignments=bad_assignments,
            contracts=contracts,
        )
    incomplete = [spec for spec in contracts if spec["contract_id"] != "api.alpha"]
    with pytest.raises(ValueError, match="room_board_contract_missing"):
        store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id="missing-contract"),
            modules=modules,
            assignments=assignments,
            contracts=incomplete,
        )
    with pytest.raises(ValueError, match="room_board_module_duplicate"):
        store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id="dup-module"),
            modules=[modules[0], modules[0]],
            assignments={"alpha": assignments["alpha"], "beta": assignments["beta"]},
            contracts=contracts,
        )
    assert _board_activity_count(db, conversation_id) == 0


def test_decide_split_approve_reject_and_double_decide(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="decide-propose"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    with pytest.raises(ValueError, match="room_board_decision_invalid"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=proposed["split_id"],
            decision="maybe",
            operator_identity="operator:host",
        )
    with pytest.raises(ValueError, match="room_board_split_unknown"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id="split_missing",
            decision="approve",
            operator_identity="operator:host",
        )
    decided = store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    assert decided["status"] == "approved"
    with RoomDatabase(db).connect() as conn:
        charters = conn.execute(
            "select * from room_board_charters where conversation_id = ? order by module_id",
            (conversation_id,),
        ).fetchall()
        assert [(row["module_id"], row["version"], row["status"]) for row in charters] == [
            ("alpha", 1, "active"),
            ("beta", 1, "active"),
        ]
        assert charters[0]["owner_participant_id"] == members[1].participant_id
        assert charters[1]["owner_participant_id"] == members[2].participant_id
        rows = conn.execute(
            "select * from room_board_contracts where conversation_id = ? order by contract_id",
            (conversation_id,),
        ).fetchall()
        assert [(row["contract_id"], row["version"]) for row in rows] == [
            ("api.alpha", 1),
            ("api.beta", 1),
        ]
        assert rows[0]["digest"] == contract_digest('{"alpha": 1}')
        assigned = conn.execute(
            "select * from room_activities where conversation_id = ? "
            "and activity_type = 'board.charter_assigned' order by seq",
            (conversation_id,),
        ).fetchall()
        assert len(assigned) == 2
        assert all(row["actor_kind"] == "operator" for row in assigned)
    for owner, activity_id in zip((members[1], members[2]), decided["activity_ids"], strict=True):
        woken = _pending_for_activity(db, conversation_id, owner.participant_id, activity_id)
        assert len(woken) == 1
        assert woken[0]["priority"] == 100

    with pytest.raises(ValueError, match="room_board_split_decided"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=proposed["split_id"],
            decision="approve",
            operator_identity="operator:host",
        )

    fresh_modules, fresh_assignments, fresh_contracts = _renamed_split(
        modules, assignments, contracts, suffix="2"
    )
    second = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="decide-propose-2"),
        modules=fresh_modules,
        assignments=fresh_assignments,
        contracts=fresh_contracts,
    )
    rejected = store.decide_split(
        conversation_id=conversation_id,
        split_id=second["split_id"],
        decision="reject",
        operator_identity="operator:host",
    )
    assert rejected["status"] == "rejected"
    with RoomDatabase(db).connect() as conn:
        assert (
            conn.execute(
                "select count(*) from room_board_charters where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "select count(*) from room_board_contracts where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "select count(*) from room_activities where conversation_id = ? "
                "and activity_type = 'board.split_rejected'",
                (conversation_id,),
            ).fetchone()[0]
            == 1
        )

    # An active module id is refused when the lead proposes, not at approval.
    with pytest.raises(ValueError, match="room_board_charter_active: module alpha"):
        store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id="decide-propose-3"),
            modules=modules,
            assignments=assignments,
            contracts=contracts,
        )


def _renamed_split(modules, assignments, contracts, *, suffix: str, keep_contract_ids=()):
    """The split with new module ids and, except ``keep_contract_ids``, new contract ids."""

    def module_name(name: str) -> str:
        return f"{name}{suffix}"

    def contract_name(name: str) -> str:
        return name if name in keep_contract_ids else f"{name}{suffix}"

    renamed_modules = [
        {
            **item,
            "module_id": module_name(item["module_id"]),
            "provides": [contract_name(c) for c in item["provides"]],
            "depends": [contract_name(c) for c in item["depends"]],
        }
        for item in modules
    ]
    renamed_assignments = {module_name(k): v for k, v in assignments.items()}
    renamed_contracts = [
        {
            **spec,
            "contract_id": contract_name(spec["contract_id"]),
            "provider_module_id": module_name(spec["provider_module_id"]),
        }
        for spec in contracts
    ]
    return renamed_modules, renamed_assignments, renamed_contracts


def test_propose_split_refuses_a_published_contract_id(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    first = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="contract-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=first["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    # New module ids, but api.alpha is reused: the follow-up the real run hit.
    reused = _renamed_split(
        modules, assignments, contracts, suffix="2", keep_contract_ids=("api.alpha",)
    )
    with pytest.raises(
        ValueError,
        match="room_board_contract_exists: contract api.alpha is already published by module alpha",
    ):
        store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id="contract-2"),
            modules=reused[0],
            assignments=reused[1],
            contracts=reused[2],
        )


def test_decide_split_refuses_a_contract_id_published_after_the_proposal(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="race-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    with RoomDatabase(db).connect() as conn:
        conn.execute(
            """insert into room_board_contracts
               (conversation_id, contract_id, version, provider_module_id, kind, content,
                digest, author_participant_id, rationale, activity_id, created_at)
               values (?, 'api.beta', 1, 'elsewhere', 'text', 'x', ?, ?, 'r', null, ?)""",
            (
                conversation_id,
                contract_digest("x"),
                members[1].participant_id,
                "2026-01-01T00:00:00.000000Z",
            ),
        )
        conn.commit()
    with pytest.raises(ValueError, match="room_board_contract_exists: contract api.beta"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=proposed["split_id"],
            decision="approve",
            operator_identity="operator:host",
        )
    with RoomDatabase(db).connect() as conn:
        assert (
            conn.execute(
                "select count(*) from room_board_charters where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "select status from room_board_splits where split_id = ?",
                (proposed["split_id"],),
            ).fetchone()[0]
            == "proposed"
        )


def test_decide_split_grant_id_rule(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="grant-propose"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    split_id = proposed["split_id"]
    # A plugin decision without a grant id is a programming error.
    with pytest.raises(ValueError, match="room_board_grant_id_invalid"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=split_id,
            decision="approve",
            operator_identity="operator:host",
            decided_via="plugin:claude-code",
        )
    with pytest.raises(ValueError, match="room_board_grant_id_invalid"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=split_id,
            decision="approve",
            operator_identity="operator:host",
            decided_via="plugin:claude-code",
            grant_id="",
        )
    # A grant id on a non-plugin decision is a programming error.
    with pytest.raises(ValueError, match="room_board_grant_id_invalid"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=split_id,
            decision="approve",
            operator_identity="operator:host",
            decided_via="web",
            grant_id="grant_some",
        )
    with pytest.raises(ValueError, match="room_board_grant_id_invalid"):
        store.decide_split(
            conversation_id=conversation_id,
            split_id=split_id,
            decision="approve",
            operator_identity="operator:host",
            decided_via="cli",
            grant_id="grant_some",
        )
    assert (
        store.decide_split(
            conversation_id=conversation_id,
            split_id=split_id,
            decision="approve",
            operator_identity="plugin-grant:grant_abc",
            decided_via="plugin:claude-code",
            grant_id="grant_abc",
        )["status"]
        == "approved"
    )
    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select payload_json from room_activities where conversation_id = ? "
            "and activity_type = 'board.charter_assigned' order by seq",
            (conversation_id,),
        ).fetchall()
    assert len(rows) == 2
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        assert payload["decided_via"] == "plugin:claude-code"
        assert payload["grant_id"] == "grant_abc"


def test_decide_split_reject_grant_id_recorded_and_web_cli_null(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    first = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="reject-propose-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    assert (
        store.decide_split(
            conversation_id=conversation_id,
            split_id=first["split_id"],
            decision="reject",
            operator_identity="plugin-grant:grant_xyz",
            decided_via="plugin:opencode",
            grant_id="grant_xyz",
        )["status"]
        == "rejected"
    )
    with RoomDatabase(db).connect() as conn:
        row = conn.execute(
            "select payload_json from room_activities where conversation_id = ? "
            "and activity_type = 'board.split_rejected'",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert payload["decided_via"] == "plugin:opencode"
    assert payload["grant_id"] == "grant_xyz"

    for decided_via in ("web", "cli"):
        nxt = store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id=f"reject-propose-{decided_via}"),
            modules=modules,
            assignments=assignments,
            contracts=contracts,
        )
        assert (
            store.decide_split(
                conversation_id=conversation_id,
                split_id=nxt["split_id"],
                decision="reject",
                operator_identity="operator:host",
                decided_via=decided_via,
            )["status"]
            == "rejected"
        )
    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select payload_json from room_activities where conversation_id = ? "
            "and activity_type = 'board.split_rejected' order by seq",
            (conversation_id,),
        ).fetchall()
    assert len(rows) == 3
    assert [json.loads(str(row["payload_json"]))["decided_via"] for row in rows] == [
        "plugin:opencode",
        "web",
        "cli",
    ]
    assert [json.loads(str(row["payload_json"]))["grant_id"] for row in rows] == [
        "grant_xyz",
        None,
        None,
    ]


def test_claim_owner_rules_and_repeat_claim(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    obs_a = _claim(db, conversation_id, members[1], owner="host-a")
    _claim(db, conversation_id, members[2], owner="host-b")

    with pytest.raises(ValueError, match="room_board_module_unknown"):
        store.claim(
            **_lease_kwargs(members[1], obs_a, request_id="claim-early"),
            module_id="alpha",
        )

    ctx = _approved_board(tmp_path)
    store2, members2, leases2 = ctx["store"], ctx["members"], ctx["leases"]
    with pytest.raises(ValueError, match="room_board_not_owner"):
        store2.claim(
            **_lease_kwargs(
                members2[2], leases2[members2[2].participant_id], request_id="claim-other"
            ),
            module_id="alpha",
        )
    first = store2.claim(
        **_lease_kwargs(members2[1], leases2[members2[1].participant_id], request_id="claim-first"),
        module_id="alpha",
    )
    assert first["claimed_at"]
    again = store2.claim(
        **_lease_kwargs(
            members2[1], leases2[members2[1].participant_id], request_id="claim-second"
        ),
        module_id="alpha",
    )
    assert again["claimed_at"] == first["claimed_at"]
    assert again["activity_id"] == first["activity_id"]
    with RoomDatabase(ctx["db"]).connect() as conn:
        assert (
            conn.execute(
                "select count(*) from room_activities where conversation_id = ? "
                "and activity_type = 'board.claimed'",
                (ctx["conversation_id"],),
            ).fetchone()[0]
            == 1
        )


def test_publish_contract_conflict_digest_limits_and_wake_scope(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    lead, owner_a, owner_b = members
    leases = ctx["leases"]

    with pytest.raises(ValueError, match="room_board_not_owner"):
        store.publish_contract(
            **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="pub-stranger"),
            contract_id="api.extra",
            kind="text",
            content="extra",
            base_version=None,
            rationale="sneaky",
            provider_module_id="alpha",
        )
    created = store.publish_contract(
        **_lease_kwargs(lead, leases[lead.participant_id], request_id="pub-new"),
        contract_id="api.extra",
        kind="text",
        content="extra",
        base_version=None,
        rationale="lead adds",
        provider_module_id="alpha",
    )
    assert created["version"] == 1
    assert created["digest"] == contract_digest("extra")

    with pytest.raises(ValueError, match="room_board_content_too_large"):
        store.publish_contract(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="pub-big"),
            contract_id="api.alpha",
            kind="api_schema",
            content="x" * 65537,
            base_version=1,
            rationale="big",
        )

    revised = store.publish_contract(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="pub-rev"),
        contract_id="api.alpha",
        kind="api_schema",
        content='{"alpha": 2}',
        base_version=1,
        rationale="revise",
    )
    assert revised["version"] == 2
    assert revised["digest"] == contract_digest('{"alpha": 2}')

    with pytest.raises(ValueError, match="room_board_contract_conflict") as excinfo:
        store.publish_contract(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="pub-stale"),
            contract_id="api.alpha",
            kind="api_schema",
            content='{"alpha": 3}',
            base_version=1,
            rationale="stale",
        )
    assert "2" in str(excinfo.value)

    beta_wake = _pending_for_activity(
        db, conversation_id, owner_b.participant_id, revised["activity_id"]
    )
    assert len(beta_wake) == 1
    assert beta_wake[0]["priority"] == 100
    # The provider itself and unrelated parties get no wake-up for the revision.
    assert (
        _pending_for_activity(db, conversation_id, owner_a.participant_id, revised["activity_id"])
        == []
    )
    assert (
        _pending_for_activity(db, conversation_id, lead.participant_id, revised["activity_id"])
        == []
    )


def test_report_progress_owner_and_lead_wake(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    lead, owner_a, owner_b = members
    leases = ctx["leases"]

    with pytest.raises(ValueError, match="room_board_module_unknown"):
        store.report_progress(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="rep-unknown"),
            module_id="missing",
            status="working",
            summary="x",
            claims=[],
        )
    with pytest.raises(ValueError, match="room_board_not_owner"):
        store.report_progress(
            **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="rep-other"),
            module_id="alpha",
            status="working",
            summary="x",
            claims=[],
        )
    working = store.report_progress(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="rep-working"),
        module_id="alpha",
        status="working",
        summary="steady",
        claims=["claim one"],
    )
    assert working["status"] == "working"
    assert _pending_observations(db, conversation_id, lead.participant_id) == []
    ready = store.report_progress(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="rep-ready"),
        module_id="alpha",
        status="ready_for_review",
        summary="review me",
        claims=[],
    )
    lead_pending = _pending_observations(db, conversation_id, lead.participant_id)
    assert [obs["activity_id"] for obs in lead_pending] == [ready["activity_id"]]
    with pytest.raises(ValueError, match="room_board_status_invalid"):
        store.report_progress(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="rep-bad"),
            module_id="alpha",
            status="napping",
            summary="x",
            claims=[],
        )


def test_ask_wakes_only_target_and_rejects_self(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    lead, owner_a, owner_b = members
    leases = ctx["leases"]

    with pytest.raises(ValueError, match="room_board_ask_self"):
        store.ask(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ask-self"),
            target_participant_id=owner_a.participant_id,
            question="me?",
            references=[],
        )
    with pytest.raises(ValueError, match="room_board_target_unknown"):
        store.ask(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ask-ghost"),
            target_participant_id="participant_missing",
            question="you?",
            references=[],
        )
    asked = store.ask(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ask-ok"),
        target_participant_id=owner_b.participant_id,
        question="what shape?",
        references=["api.beta"],
    )
    target_wake = _pending_for_activity(
        db, conversation_id, owner_b.participant_id, asked["activity_id"]
    )
    assert len(target_wake) == 1
    assert (
        _pending_for_activity(db, conversation_id, lead.participant_id, asked["activity_id"]) == []
    )
    assert (
        _pending_for_activity(db, conversation_id, owner_a.participant_id, asked["activity_id"])
        == []
    )


def test_read_inbox_cursor_and_contract_ref(tmp_path):
    ctx = _approved_board(tmp_path)
    members, store = ctx["members"], ctx["store"]
    lead, owner_a, owner_b = members
    leases = ctx["leases"]

    store.claim(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ro-claim-a"),
        module_id="alpha",
    )
    store.claim(
        **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="ro-claim-b"),
        module_id="beta",
    )
    store.report_progress(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ro-progress"),
        module_id="alpha",
        status="working",
        summary="steady",
        claims=[],
    )
    store.ask(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ro-ask"),
        target_participant_id=owner_b.participant_id,
        question="shape?",
        references=[],
    )
    store.publish_contract(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ro-rev"),
        contract_id="api.alpha",
        kind="api_schema",
        content='{"alpha": 2}',
        base_version=1,
        rationale="revise",
    )

    lead_view = store.read(
        **_lease_kwargs(lead, leases[lead.participant_id], request_id="ro-read-lead")
    )
    assert [item["activity_type"] for item in lead_view["inbox"]] == [
        "board.split_proposed",
        "board.claimed",
        "board.claimed",
        "board.progress",
    ]
    assert {item["module_id"] for item in lead_view["charters"]} == {"alpha", "beta"}
    assert {item["owner_participant_id"] for item in lead_view["charters"]} == {
        owner_a.participant_id,
        owner_b.participant_id,
    }
    assert {item["contract_id"] for item in lead_view["contracts"]} == {
        "api.alpha",
        "api.beta",
    }
    assert lead_view["contract"] is None
    # The cursor passes every scanned board activity, including ones addressed
    # only to others (the question and the revision), so they never stall it.
    assert lead_view["cursor_seq"] > lead_view["inbox"][-1]["seq"]

    owner_b_view = store.read(
        **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="ro-read-b")
    )
    assert [item["activity_type"] for item in owner_b_view["inbox"]] == [
        "board.charter_assigned",
        "board.question",
        "board.contract_revised",
    ]
    owner_a_view = store.read(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ro-read-a")
    )
    assert [item["activity_type"] for item in owner_a_view["inbox"]] == [
        "board.charter_assigned",
    ]

    second = store.read(
        **_lease_kwargs(lead, leases[lead.participant_id], request_id="ro-read-lead-2")
    )
    assert second["inbox"] == []
    # Foreign traffic followed by one addressed event: only that event arrives.
    for index in range(3):
        store.ask(
            **_lease_kwargs(
                owner_a, leases[owner_a.participant_id], request_id=f"ro-noise-{index}"
            ),
            target_participant_id=owner_b.participant_id,
            question=f"noise {index}",
            references=[],
        )
    store.report_progress(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ro-progress-2"),
        module_id="alpha",
        status="working",
        summary="still steady",
        claims=[],
    )
    third = store.read(
        **_lease_kwargs(lead, leases[lead.participant_id], request_id="ro-read-lead-3")
    )
    assert [item["activity_type"] for item in third["inbox"]] == ["board.progress"]

    latest = store.read(
        **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="ro-read-contract"),
        contract_ref="api.alpha",
    )
    assert latest["contract"] is not None
    assert latest["contract"]["content"] == '{"alpha": 2}'
    assert latest["contract"]["version"] == 2
    assert latest["contract"]["digest"] == contract_digest('{"alpha": 2}')
    pinned = store.read(
        **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="ro-read-contract-1"),
        contract_ref="api.alpha@1",
    )
    assert pinned["contract"] is not None
    assert pinned["contract"]["content"] == '{"alpha": 1}'
    with pytest.raises(ValueError, match="room_board_contract_unknown"):
        store.read(
            **_lease_kwargs(owner_b, leases[owner_b.participant_id], request_id="ro-read-missing"),
            contract_ref="api.missing",
        )


def test_every_board_write_leaves_exactly_one_activity(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead, owner_a, owner_b = members
    lead_obs = _claim(db, conversation_id, lead, owner="host-lead")
    obs_a = _claim(db, conversation_id, owner_a, owner="host-a")
    _claim(db, conversation_id, owner_b, owner="host-b")

    modules, assignments, contracts = _split_payload(members)
    solo_modules = [modules[0]]
    solo_assignments = {"alpha": assignments["alpha"]}
    solo_contracts = [contracts[0]]

    expected = 0
    proposed = store.propose_split(
        **_lease_kwargs(lead, lead_obs, request_id="one-propose"),
        modules=solo_modules,
        assignments=solo_assignments,
        contracts=solo_contracts,
    )
    expected += 1
    assert _board_activity_count(db, conversation_id) == expected

    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    expected += 1
    assert _board_activity_count(db, conversation_id) == expected

    store.claim(**_lease_kwargs(owner_a, obs_a, request_id="one-claim"), module_id="alpha")
    expected += 1
    assert _board_activity_count(db, conversation_id) == expected

    # The lead names the provider explicitly for a brand-new contract.
    store.publish_contract(
        **_lease_kwargs(lead, lead_obs, request_id="one-publish"),
        contract_id="api.alpha2",
        kind="text",
        content="second surface",
        base_version=None,
        rationale="extra",
        provider_module_id="alpha",
    )
    expected += 1
    assert _board_activity_count(db, conversation_id) == expected

    store.report_progress(
        **_lease_kwargs(owner_a, obs_a, request_id="one-progress"),
        module_id="alpha",
        status="working",
        summary="steady",
        claims=[],
    )
    expected += 1
    assert _board_activity_count(db, conversation_id) == expected

    store.ask(
        **_lease_kwargs(owner_a, obs_a, request_id="one-ask"),
        target_participant_id=owner_b.participant_id,
        question="hi?",
        references=[],
    )
    expected += 1
    assert _board_activity_count(db, conversation_id) == expected

    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select * from room_activities where conversation_id = ? "
            "and activity_type like 'board.%' order by seq",
            (conversation_id,),
        ).fetchall()
    assert len(rows) == expected
    seen_types = set()
    for row in rows:
        assert row["activity_type"].startswith("board.")
        assert row["actor_kind"] in ("participant", "operator")
        assert row["causation_id"]
        assert row["correlation_id"].startswith("board_correlation_")
        assert int(row["causal_depth"]) >= 1
        audience = json.loads(row["audience_json"])
        assert audience["type"] == "board"
        assert audience["conversation_id"] == conversation_id
        payload = json.loads(row["payload_json"])
        assert payload["schema_version"] == "room_board_activity/v1"
        # The visible text never carries raw contract bodies (those live only in
        # the contract table).
        assert isinstance(payload["content"], str) and payload["content"]
        assert '"alpha": ' not in row["payload_json"]
        assert '"beta": ' not in row["payload_json"]
        seen_types.add(row["activity_type"])
    assert {
        "board.split_proposed",
        "board.charter_assigned",
        "board.claimed",
        "board.contract_published",
        "board.progress",
        "board.question",
    } <= seen_types


def test_application_service_verifies_identity_and_maps_errors(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    registry = tmp_path / "god_sessions.json"
    sessions = {}
    for index, member in enumerate(members):
        sessions[member.participant_id] = GodSessionRegistry(registry).create(
            member.role,
            member.display_name,
            "codex",
            f"addr-{index}",
            f"inbox-{index}",
            conversation_id,
            member.participant_id,
        )
    service = RoomApplicationService(db, registry)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    proposed = service.board_propose_split(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        god_session_id=sessions[members[0].participant_id].god_session_id,
        observation_id=lead_obs["observation_id"],
        lease_token=lead_obs["lease_token"],
        client_request_id="svc-propose",
        modules=modules,
        assignments=assignments,
        contracts=contracts,
        now=NOW,
    )
    assert proposed["status"] == "proposed"
    decided = service.board_decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    assert decided["status"] == "approved"
    with pytest.raises(RoomApplicationError) as excinfo:
        service.board_propose_split(
            conversation_id=conversation_id,
            participant_id=members[1].participant_id,
            god_session_id=sessions[members[1].participant_id].god_session_id,
            observation_id=lead_obs["observation_id"],
            lease_token="wrong",
            client_request_id="svc-bad-lease",
            modules=modules,
            assignments=assignments,
            contracts=contracts,
            now=NOW,
        )
    assert excinfo.value.code == "room_observation_lease_lost"
    with pytest.raises(RoomApplicationError) as excinfo:
        service.board_claim(
            conversation_id=conversation_id,
            participant_id=members[0].participant_id,
            god_session_id="god-session-missing",
            observation_id=lead_obs["observation_id"],
            lease_token=lead_obs["lease_token"],
            client_request_id="svc-bad-session",
            module_id="alpha",
            now=NOW,
        )
    assert excinfo.value.code == "unknown_god_session"


def test_digest_matches_sha256_of_utf8_content():
    assert contract_digest("hello") == f"sha256:{sha256(b'hello').hexdigest()}"


def test_stale_base_version_error_names_latest_version(tmp_path):
    ctx = _approved_board(tmp_path)
    store, members, leases = ctx["store"], ctx["members"], ctx["leases"]
    owner_a = members[1]
    store.publish_contract(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ver-bump"),
        contract_id="api.alpha",
        kind="api_schema",
        content='{"alpha": 2}',
        base_version=1,
        rationale="revise",
    )
    with pytest.raises(ValueError, match="room_board_contract_conflict") as excinfo:
        store.publish_contract(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="ver-stale"),
            contract_id="api.alpha",
            kind="api_schema",
            content='{"alpha": 3}',
            base_version=1,
            rationale="stale",
        )
    assert "2" in str(excinfo.value)


def test_rejected_split_creates_no_board_state_but_one_activity(tmp_path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="rej-propose"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    before = _board_activity_count(db, conversation_id)
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="reject",
        operator_identity="operator:host",
    )
    assert _board_activity_count(db, conversation_id) == before + 1
    with RoomDatabase(db).connect() as conn:
        assert (
            conn.execute(
                "select count(*) from room_board_charters where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "select count(*) from room_board_contracts where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "select count(*) from room_observations where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 3
        )


def test_question_and_progress_payloads_stay_bounded_and_addressed(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    owner_a, owner_b = members[1], members[2]
    leases = ctx["leases"]
    big_claims = ["c" * 500 for _ in range(32)]
    reported = store.report_progress(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="bounded-rep"),
        module_id="alpha",
        status="blocked",
        summary="s" * 4000,
        claims=big_claims,
    )
    with pytest.raises(ValueError, match="room_board_summary_invalid"):
        store.report_progress(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="bounded-big"),
            module_id="alpha",
            status="working",
            summary="s" * 4001,
            claims=[],
        )
    with RoomDatabase(db).connect() as conn:
        activity = conn.execute(
            "select * from room_activities where activity_id = ?",
            (reported["activity_id"],),
        ).fetchone()
    assert activity is not None
    assert activity["activity_type"] == "board.progress"
    # Blocked status wakes the lead.
    lead_pending = _pending_observations(db, conversation_id, members[0].participant_id)
    assert [obs["activity_id"] for obs in lead_pending] == [reported["activity_id"]]
    asked = store.ask(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="bounded-ask"),
        target_participant_id=owner_b.participant_id,
        question="q" * 4000,
        references=[f"ref-{index}" for index in range(16)],
    )
    assert asked["target_participant_id"] == owner_b.participant_id
    with pytest.raises(ValueError, match="room_board_references_invalid"):
        store.ask(
            **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="bounded-refs"),
            target_participant_id=owner_b.participant_id,
            question="q",
            references=[f"ref-{index}" for index in range(17)],
        )
    with sqlite3.connect(db, factory=ClosingConnection) as raw:
        count = raw.execute(
            "select count(*) from room_observations where conversation_id = ? "
            "and activity_id = ? and status = 'pending'",
            (conversation_id, asked["activity_id"]),
        ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# module reassignment (charter version + 1 for another owner)
# ---------------------------------------------------------------------------


def _report_done(ctx, member, request_id: str, module_id: str = "alpha"):
    return ctx["store"].report_progress(
        **_lease_kwargs(member, ctx["leases"][member.participant_id], request_id=request_id),
        module_id=module_id,
        status="done",
        summary="finished",
        claims=[],
    )


def test_reassign_moves_an_unintegrated_module_to_a_new_owner(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members = ctx["db"], ctx["conversation_id"], ctx["members"]
    old_owner, new_owner = members[1], members[2]
    pending = _report_done(ctx, old_owner, "done-before-reassign")

    result = ctx["store"].reassign_module(
        conversation_id=conversation_id,
        module_id="alpha",
        owner_participant_id=new_owner.participant_id,
        expected_version=1,
        operator_identity="operator:host",
    )

    assert result["version"] == 2
    assert result["reassigned_from"] == old_owner.participant_id
    with RoomDatabase(db).connect() as conn:
        rows = conn.execute(
            "select version, owner_participant_id, status from room_board_charters "
            "where conversation_id = ? and module_id = 'alpha' order by version",
            (conversation_id,),
        ).fetchall()
        assert [(r["version"], r["owner_participant_id"], r["status"]) for r in rows] == [
            (1, old_owner.participant_id, "retired"),
            (2, new_owner.participant_id, "active"),
        ]
        verification = conn.execute(
            "select status from room_board_verifications where verification_id = ?",
            (pending["verification_id"],),
        ).fetchone()
        assert verification["status"] == "superseded"
        activity = conn.execute(
            "select payload_json from room_activities where activity_id = ?",
            (result["activity_id"],),
        ).fetchone()
    payload = json.loads(activity["payload_json"])
    assert payload["reassigned_from"] == old_owner.participant_id
    assert "reassigned module alpha to you" in payload["content"]
    assert ".xmuse/memory.md" in payload["content"]
    assert _pending_for_activity(
        db, conversation_id, new_owner.participant_id, result["activity_id"]
    )
    # The previous owner no longer owns the module.
    with pytest.raises(ValueError):
        _report_done(ctx, old_owner, "done-after-reassign")


def test_reassign_refusals(tmp_path, monkeypatch):
    ctx = _approved_board(tmp_path)
    conversation_id, members, store = ctx["conversation_id"], ctx["members"], ctx["store"]
    kwargs = {"conversation_id": conversation_id, "operator_identity": "operator:host"}

    with pytest.raises(ValueError, match="room_board_charter_version_mismatch"):
        store.reassign_module(
            **kwargs,
            module_id="alpha",
            owner_participant_id=members[2].participant_id,
            expected_version=2,
        )
    with pytest.raises(ValueError, match="room_board_reassign_same_owner"):
        store.reassign_module(
            **kwargs,
            module_id="alpha",
            owner_participant_id=members[1].participant_id,
            expected_version=1,
        )
    with pytest.raises(ValueError, match="room_board_module_unknown"):
        store.reassign_module(
            **kwargs,
            module_id="nope",
            owner_participant_id=members[2].participant_id,
            expected_version=1,
        )
    monkeypatch.setattr(
        RoomBoardStore,
        "_green_head_conn",
        staticmethod(lambda conn, *, conversation_id: {"applied": {"alpha": "v1"}}),
    )
    with pytest.raises(ValueError, match="room_board_reassign_integrated"):
        store.reassign_module(
            **kwargs,
            module_id="alpha",
            owner_participant_id=members[2].participant_id,
            expected_version=1,
        )


def test_previous_owner_work_is_never_an_integration_candidate_after_reassign(tmp_path):
    ctx = _approved_board(tmp_path)
    conversation_id, members, store = ctx["conversation_id"], ctx["members"], ctx["store"]
    reported = _report_done(ctx, members[1], "done-old")
    claimed = store.claim_next_board_verification(worker_id="w1")
    assert claimed is not None and claimed["verification_id"] == reported["verification_id"]
    store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="a" * 40,
        patch_digest="sha256:" + "b" * 64,
        changed_paths=["src/alpha/a.py"],
        gates=[{"gate_id": "patch_diff_check", "status": "passed", "exit_code": 0}],
        evidence={},
        patch_text="diff --git a/src/alpha/a.py b/src/alpha/a.py\n",
        stacked=[],
        base_commit="c" * 40,
    )
    with RoomDatabase(ctx["db"]).connect() as conn:
        # The fixture's leases run on a fixed test clock while the split was approved
        # on the wall clock; date the verification at the v1 charter so it is a
        # candidate before the reassignment.
        conn.execute(
            "update room_board_verifications set created_at = ("
            "select created_at from room_board_charters where conversation_id = ? "
            "and module_id = 'alpha' and version = 1) where verification_id = ?",
            (conversation_id, reported["verification_id"]),
        )
        conn.commit()
    assert "alpha" in {
        item["module_id"] for item in store.board_integration_inputs(conversation_id)["candidates"]
    }

    store.reassign_module(
        conversation_id=conversation_id,
        module_id="alpha",
        owner_participant_id=members[2].participant_id,
        expected_version=1,
        operator_identity="operator:host",
    )

    candidates = store.board_integration_inputs(conversation_id)["candidates"]
    assert "alpha" not in {item["module_id"] for item in candidates}


def test_a_held_reassign_wake_goes_out_once_memory_is_ready(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    new_owner = members[2].participant_id
    result = store.reassign_module(
        conversation_id=conversation_id,
        module_id="alpha",
        owner_participant_id=new_owner,
        expected_version=1,
        operator_identity="operator:host",
        hold_wake_s=60,
    )
    assert result["wake"] == "held"
    assert not _pending_for_activity(db, conversation_id, new_owner, result["activity_id"])

    asked: list[tuple[str, str, int]] = []

    def not_yet(conversation: str, module: str, seq: int) -> bool:
        asked.append((conversation, module, seq))
        return False

    assert store.release_held_wakes(memory_ready=not_yet) == []
    assert asked == [(conversation_id, "alpha", result["activity_seq"])]
    released = store.release_held_wakes(memory_ready=lambda *_args: True)
    assert [(item["participant_id"], item["reason"]) for item in released] == [
        (new_owner, "memory_ready")
    ]
    assert _pending_for_activity(db, conversation_id, new_owner, result["activity_id"])
    assert store.release_held_wakes(memory_ready=lambda *_args: True) == []


def test_a_held_reassign_wake_has_a_deadline_and_a_newer_reassign_drops_it(tmp_path):
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    kwargs = {
        "conversation_id": conversation_id,
        "module_id": "alpha",
        "operator_identity": "operator:host",
        "hold_wake_s": 60,
    }
    first = store.reassign_module(
        **kwargs, owner_participant_id=members[2].participant_id, expected_version=1
    )
    second = store.reassign_module(
        **kwargs, owner_participant_id=members[1].participant_id, expected_version=2
    )

    # Memory never catches up (the sidecar is down): only the deadline releases.
    assert store.release_held_wakes() == []
    later = datetime.now(UTC) + timedelta(seconds=120)
    released = {item["activity_id"]: item["reason"] for item in store.release_held_wakes(now=later)}
    assert released == {first["activity_id"]: "superseded", second["activity_id"]: "deadline"}
    assert not _pending_for_activity(
        db, conversation_id, members[2].participant_id, first["activity_id"]
    )
    assert _pending_for_activity(
        db, conversation_id, members[1].participant_id, second["activity_id"]
    )
