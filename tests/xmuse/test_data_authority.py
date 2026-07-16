from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse.data_authority import (
    authority_invariants,
    database_evidence,
    inspect_database,
    read_sessions,
    sanitize_sessions,
    schema_contract,
    validate_session_references,
    validate_sessions,
)
from xmuse.data_contracts import CHAT_SCHEMA_CONTRACT, SESSION_NAME, DataError
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_database import ROOM_SCHEMA_ID
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.runtime.root_contract import CHAT_DB_NAME


def _build_root(root: Path, *, with_session: bool = False) -> tuple[str, str]:
    db_path = root / CHAT_DB_NAME
    conversation = CompatDataTestStore(db_path).create_conversation("Authority room")
    participant = ParticipantStore(db_path).add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5",
    )
    RoomKernelStore(db_path).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="Preserve this authority fact.",
        client_request_id="authority-fixture",
    )
    if with_session:
        registry = GodSessionRegistry(root / SESSION_NAME)
        record = registry.create(
            role="architect",
            agent_name="Architect",
            runtime="codex",
            session_address=f"@architect-{participant.participant_id}",
            session_inbox_id=f"inbox-{participant.participant_id}",
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            model="gpt-5",
            worktree="/tmp/xmuse-worktree",
        )
        registry.promote_running(record.god_session_id, pid=4242)
        registry.update_provider_binding(
            record.god_session_id,
            provider_session_id="provider-before-backup",
            provider_session_kind="codex_app_server_thread",
            provider_binding_status="active",
            provider_binding_failure_reason=None,
        )
    return conversation.id, participant.participant_id


def _build_completed_peer_batch(root: Path) -> str:
    db_path = root / CHAT_DB_NAME
    conversation = CompatDataTestStore(db_path).create_conversation("Batch authority room")
    participants = ParticipantStore(db_path)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(3)
    ]
    kernel = RoomKernelStore(db_path)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="produce a peer batch",
        client_request_id="batch-root",
    )
    for index, member in enumerate(members):
        claim = kernel.claim_next_observation_batch(
            conversation_id=conversation.id,
            participant_id=member.participant_id,
            lease_owner=f"root-{index}",
        )
        assert claim is not None
        kernel.submit_participant_outcome(
            conversation_id=conversation.id,
            participant_id=member.participant_id,
            caller_identity=f"god:session:{member.participant_id}",
            observation_id=claim["observation"]["observation_id"],
            observation_batch_id=claim["batch"]["batch_id"],
            lease_token=claim["observation"]["lease_token"],
            client_request_id=f"root-outcome-{index}",
            outcome_type="respond",
            outcome_payload={"content": f"root response {index}"},
        )
    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation.id,
        participant_id=members[0].participant_id,
        lease_owner="peer-batch",
    )
    assert peer is not None and peer["batch"]["member_count"] == 2
    kernel.submit_participant_outcome(
        conversation_id=conversation.id,
        participant_id=members[0].participant_id,
        caller_identity=f"god:session:{members[0].participant_id}",
        observation_id=peer["observation"]["observation_id"],
        observation_batch_id=peer["batch"]["batch_id"],
        lease_token=peer["observation"]["lease_token"],
        client_request_id="peer-outcome",
        outcome_type="noop",
    )
    return str(peer["batch"]["batch_id"])


def test_schema_contract_accepts_current_and_legacy_and_rejects_future(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    _build_root(root)
    db_path = root / CHAT_DB_NAME

    current = inspect_database(db_path, require_current=True)
    assert current["schema"]["state"] == "current"
    assert current["schema"]["schema_contract"] == CHAT_SCHEMA_CONTRACT

    with sqlite3.connect(db_path) as conn:
        conn.execute("delete from chat_schema_meta where schema_id = ?", (ROOM_SCHEMA_ID,))
    legacy = inspect_database(db_path, require_current=True)
    assert legacy["schema"]["state"] == "current"
    assert legacy["schema"]["schema_contract"] == CHAT_SCHEMA_CONTRACT

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into chat_schema_meta(schema_id, version, updated_at) values (?, 2, ?)",
            (ROOM_SCHEMA_ID, "2026-07-16T00:00:00Z"),
        )
    with pytest.raises(DataError) as error:
        inspect_database(db_path, require_current=True)
    assert error.value.code == "backup_schema_unsupported"
    assert error.value.details["schema"]["state"] == "future"


def test_inspection_rejects_corrupt_json_and_legacy_claim(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _build_root(root)
    db_path = root / CHAT_DB_NAME
    with sqlite3.connect(db_path) as conn:
        conn.execute("update messages set envelope_json = '{'")
        conn.execute(
            """update room_observations set status = 'claimed',
                   lease_owner = 'legacy-host', lease_token = 'legacy-token',
                   acquired_at = '2026-07-16T00:00:00Z',
                   expires_at = '2099-01-01T00:00:00Z', current_attempt_id = null"""
        )

    with pytest.raises(DataError) as error:
        inspect_database(db_path, require_current=True)
    assert error.value.code == "chat_db_corrupt"
    invariants = error.value.details["invariants"]
    assert invariants["invalid_json"]
    assert invariants["claimed_without_attempt_count"] > 0


@pytest.mark.parametrize("corruption", ["digest", "member_count", "attempt_binding"])
def test_batch_authority_corruption_is_rejected(tmp_path: Path, corruption: str) -> None:
    root = tmp_path / corruption
    batch_id = _build_completed_peer_batch(root)
    db_path = root / CHAT_DB_NAME
    with sqlite3.connect(db_path) as conn:
        if corruption == "digest":
            conn.execute(
                "update room_observation_batches set digest = ? where batch_id = ?",
                ("0" * 64, batch_id),
            )
        elif corruption == "member_count":
            conn.execute(
                "update room_observation_batches set member_count = 1 where batch_id = ?",
                (batch_id,),
            )
        else:
            conn.execute(
                "update room_observation_attempts set batch_id = null where batch_id = ?",
                (batch_id,),
            )

    with pytest.raises(DataError, match="chat authority invariants failed") as error:
        inspect_database(db_path, require_current=True)
    assert error.value.code == "chat_db_corrupt"
    invariants = error.value.details["invariants"]
    assert (
        invariants["observation_batch_invalid_count"] + invariants["attempt_binding_mismatch_count"]
        > 0
    )


def test_connection_authority_functions_preserve_caller_transaction(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _build_root(root)
    with sqlite3.connect(root / CHAT_DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("begin")
        assert conn.in_transaction
        assert schema_contract(conn)["compatible"] is True
        assert authority_invariants(conn)["valid"] is True
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 1


def test_session_validation_reference_proof_and_sanitization(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _build_root(root, with_session=True)
    payload, records, present = read_sessions(root)

    assert present is True
    assert validate_sessions(payload) == records
    validate_session_references(root / CHAT_DB_NAME, records)
    sanitized = sanitize_sessions(records)
    assert sanitized["sessions"][0]["status"] == "starting"
    assert sanitized["sessions"][0]["pid"] is None
    assert sanitized["sessions"][0]["provider_session_id"] is None
    assert sanitized["sessions"][0]["provider_binding_status"] is None

    with pytest.raises(DataError) as error:
        validate_session_references(
            root / CHAT_DB_NAME,
            [replace(records[0], role="reviewer")],
        )
    assert error.value.code == "session_registry_invalid"

    duplicated = {"sessions": [asdict(records[0]), asdict(records[0])]}
    with pytest.raises(DataError) as duplicate_error:
        validate_sessions(duplicated)
    assert duplicate_error.value.code == "session_registry_invalid"


def test_database_evidence_is_bounded_for_ten_thousand_activities(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    db_path = root / CHAT_DB_NAME
    conversation = CompatDataTestStore(db_path).create_conversation("10k room")
    rows = [
        (
            f"activity-{index}",
            conversation.id,
            index,
            "message.posted",
            "human",
            "human",
            f"cause-{index}",
            f"correlation-{index}",
            "room",
            "[]",
            "{}",
            "active",
            "2026-07-16T00:00:00Z",
        )
        for index in range(1, 10_001)
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """insert into room_activities(
                   activity_id, conversation_id, seq, activity_type, actor_kind,
                   actor_identity, causation_id, correlation_id, visibility,
                   audience_json, payload_json, delivery_mode, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    started = time.monotonic()
    evidence = database_evidence(db_path)
    inspection = inspect_database(db_path, require_current=True)
    elapsed = time.monotonic() - started

    assert elapsed < 30
    assert evidence["totals"]["room_activity_count"] == 10_000
    assert evidence["rooms"] == [
        {
            "conversation_id": conversation.id,
            "activity_count": 10_000,
            "latest_activity_seq": 10_000,
            "frontend_event_count": 0,
            "latest_frontend_event_seq": 0,
        }
    ]
    assert inspection["invariants"]["valid"] is True
