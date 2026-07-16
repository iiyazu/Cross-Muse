from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse import data_cli, data_restore, data_runtime_guard
from xmuse.data_authority import database_evidence, inspect_database
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.memoryos_supervisor import memoryos_derived_dir
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_database import ROOM_SCHEMA_ID, RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_memory_binding_store import RoomMemoryBindingStore
from xmuse_core.chat.room_memory_rebuild_store import RoomMemoryRebuildActionStore
from xmuse_core.chat.room_operations import RoomRuntimeOperatorActionStore


def _json_output(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return payload


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_does_not_load_chat_store_or_legacy_execution_graph() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
import sys
import xmuse.data_cli

forbidden = (
    "xmuse_core.chat.store",
    "xmuse_core.platform",
    "xmuse_core.structuring",
    "xmuse_core.self_evolution",
)
print(json.dumps(sorted(
    name for name in sys.modules
    if name == forbidden[0] or name.startswith(forbidden[1:])
)))
""",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(probe.stdout) == []


def _build_root(root: Path, *, with_session: bool = True) -> tuple[str, str]:
    db_path = root / data_cli.CHAT_DB_NAME
    conversation = CompatDataTestStore(db_path).create_conversation("Data lifecycle room")
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
        content="Preserve this durable room activity.",
        client_request_id="data-cli-fixture",
    )
    if with_session:
        registry = GodSessionRegistry(root / data_cli.SESSION_NAME)
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
            provider_session_id="provider-thread-before-backup",
            provider_session_kind="codex_app_server_thread",
            provider_binding_status="active",
            provider_binding_failure_reason=None,
        )
    return conversation.id, participant.participant_id


def _build_completed_peer_batch(root: Path) -> tuple[str, str]:
    db_path = root / data_cli.CHAT_DB_NAME
    conversation = CompatDataTestStore(db_path).create_conversation("Batched data room")
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
        content="produce a durable peer batch",
        client_request_id="batch-root",
    )
    root_claims = [
        kernel.claim_next_observation_batch(
            conversation_id=conversation.id,
            participant_id=member.participant_id,
            lease_owner=f"root-{index}",
        )
        for index, member in enumerate(members)
    ]
    for index, (member, claim) in enumerate(zip(members, root_claims, strict=True)):
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
    return conversation.id, str(peer["batch"]["batch_id"])


def _backup(
    root: Path,
    destination: Path,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    assert data_cli.run_cli(["backup", str(destination), "--root", str(root)]) == 0
    return _json_output(capsys)


def test_doctor_is_read_only_for_authority_files_and_runtime_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    _build_root(root, with_session=False)
    before = {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            path.stat().st_size,
            _digest(path),
        )
        for path in root.iterdir()
        if path.is_file()
    }

    assert data_cli.run_cli(["doctor", "--root", str(root)]) == 0

    payload = _json_output(capsys)
    assert payload["schema_version"] == data_cli.DOCTOR_SCHEMA
    assert payload["state"] == "degraded"
    after = {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            path.stat().st_size,
            _digest(path),
        )
        for path in root.iterdir()
        if path.is_file()
    }
    assert after == before


def test_backup_publishes_verified_manifest_and_canonical_missing_sessions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    conversation_id, _participant_id = _build_root(root, with_session=False)
    destination = tmp_path / "backup"

    output = _backup(root, destination, capsys)

    assert output["state"] == "succeeded"
    assert sorted(path.name for path in destination.iterdir()) == [
        data_cli.CHAT_DB_NAME,
        data_cli.SESSION_NAME,
        data_cli.BACKUP_MANIFEST_NAME,
    ]
    manifest = json.loads((destination / data_cli.BACKUP_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == data_cli.BACKUP_SCHEMA
    assert manifest["data_schema_version"] == data_cli.DATA_SCHEMA_VERSION
    assert manifest["files"]["god_sessions"]["source_present"] is False
    assert manifest["files"]["god_sessions"]["session_count"] == 0
    assert json.loads((destination / data_cli.SESSION_NAME).read_text()) == {"sessions": []}
    room = next(item for item in manifest["rooms"] if item["conversation_id"] == conversation_id)
    assert room["activity_count"] == 1
    assert room["latest_activity_seq"] == 1
    for key in ("chat_db", "god_sessions"):
        entry = manifest["files"][key]
        artifact = destination / entry["name"]
        assert entry["size_bytes"] == artifact.stat().st_size
        assert entry["sha256"] == _digest(artifact)


def test_minimal_room_backup_restore_and_compact_preserve_schema_variant(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "room-source"
    RoomDatabase(source / data_cli.CHAT_DB_NAME).initialize()
    backup = tmp_path / "room-backup"

    _backup(source, backup, capsys)
    manifest = json.loads((backup / data_cli.BACKUP_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["database"]["schema_contract"] == data_cli.ROOM_SCHEMA_CONTRACT
    assert manifest["database"]["schema_contract_version"] == 1
    with sqlite3.connect(backup / data_cli.CHAT_DB_NAME) as conn:
        markers = dict(conn.execute("select schema_id, version from chat_schema_meta"))
    assert markers == {ROOM_SCHEMA_ID: 1}

    target = tmp_path / "room-target"
    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 0
    _json_output(capsys)
    assert data_cli.run_cli(["compact", "--root", str(target)]) == 0
    _json_output(capsys)

    inspection = inspect_database(target / data_cli.CHAT_DB_NAME, require_current=True)
    assert inspection["schema"]["schema_contract"] == data_cli.ROOM_SCHEMA_CONTRACT
    with sqlite3.connect(target / data_cli.CHAT_DB_NAME) as conn:
        markers = dict(conn.execute("select schema_id, version from chat_schema_meta"))
        tables = {
            str(row[0])
            for row in conn.execute("select name from sqlite_schema where type = 'table'")
        }
    assert markers == {ROOM_SCHEMA_ID: 1}
    assert "role_templates" not in tables
    assert "schema_migrations" not in tables


def test_offline_room_v1_backup_restore_allows_additive_codex_action_migration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "pre-stage-room"
    conversation_id, participant_id = _build_root(source, with_session=False)
    database = source / data_cli.CHAT_DB_NAME
    with sqlite3.connect(database) as conn:
        conn.execute(
            """insert into room_codex_delivery_holds
               (participant_id, conversation_id, hold_revision, next_control_seq, state,
                session_guard, created_at, updated_at)
               values (?, ?, 1, 3, 'reconciling', 'session-guard', 'now', 'now')""",
            (participant_id, conversation_id),
        )
        for control_seq, status in enumerate(("requested", "applying", "applied"), start=1):
            conn.execute(
                """insert into room_codex_bridge_actions
                   (action_id, conversation_id, participant_id, control_seq,
                    client_action_id, operator_identity, request_fingerprint,
                    capability_id, expected_session_guard, request_json, status,
                    requested_at, updated_at)
                   values (?, ?, ?, ?, ?, 'operator:local', ?, 'goal_get',
                           'session-guard', '{}', ?, 'now', 'now')""",
                (
                    f"action-{control_seq}",
                    conversation_id,
                    participant_id,
                    control_seq,
                    f"client-{control_seq}",
                    f"fingerprint-{control_seq}",
                    status,
                ),
            )
        conn.execute("alter table room_codex_bridge_actions drop column failure_stage")
        conn.execute("alter table room_codex_bridge_actions drop column execution_stage")

    backup = tmp_path / "pre-stage-backup"
    _backup(source, backup, capsys)
    target = tmp_path / "restored-pre-stage-room"
    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 0
    _json_output(capsys)
    with sqlite3.connect(target / data_cli.CHAT_DB_NAME) as conn:
        assert {
            str(row[1]) for row in conn.execute("pragma table_info(room_codex_bridge_actions)")
        }.isdisjoint({"execution_stage", "failure_stage"})

    RoomDatabase(target / data_cli.CHAT_DB_NAME).initialize()
    with sqlite3.connect(target / data_cli.CHAT_DB_NAME) as conn:
        rows = conn.execute(
            """select status, execution_stage, failure_stage
               from room_codex_bridge_actions order by control_seq"""
        ).fetchall()
    assert rows == [
        ("requested", "queued", None),
        ("applying", "dispatching", None),
        ("applied", "completed", None),
    ]


def test_backup_accepts_legacy_chat_v1_without_room_marker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "legacy-chat"
    _build_root(root, with_session=False)
    with sqlite3.connect(root / data_cli.CHAT_DB_NAME) as conn:
        conn.execute("delete from chat_schema_meta where schema_id = ?", (ROOM_SCHEMA_ID,))

    destination = tmp_path / "legacy-backup"
    _backup(root, destination, capsys)
    manifest, _db, _sessions, _records = data_cli.verify_backup(destination)
    assert manifest["database"]["schema_contract"] == data_cli.CHAT_SCHEMA_CONTRACT


def test_backup_refuses_an_incomplete_data_operation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    _build_root(root, with_session=False)
    (root / data_cli.OPERATION_JOURNAL_NAME).write_text("{}\n", encoding="utf-8")
    destination = tmp_path / "backup"

    assert data_cli.run_cli(["backup", str(destination), "--root", str(root)]) == 1

    assert _json_output(capsys)["error"]["code"] == "data_operation_incomplete"
    assert not destination.exists()


def test_backup_fails_closed_for_incomplete_compat_schema(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    _build_root(root, with_session=False)
    with sqlite3.connect(root / data_cli.CHAT_DB_NAME) as conn:
        conn.execute("drop table role_templates")

    destination = tmp_path / "backup"
    assert data_cli.run_cli(["backup", str(destination), "--root", str(root)]) == 1

    payload = _json_output(capsys)
    assert payload["error"]["code"] == "backup_schema_unsupported"
    assert not destination.exists()


def test_backup_fails_closed_for_future_room_marker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "future-room"
    RoomDatabase(root / data_cli.CHAT_DB_NAME).initialize()
    with sqlite3.connect(root / data_cli.CHAT_DB_NAME) as conn:
        conn.execute(
            "update chat_schema_meta set version = 2 where schema_id = ?",
            (ROOM_SCHEMA_ID,),
        )

    destination = tmp_path / "backup"
    assert data_cli.run_cli(["backup", str(destination), "--root", str(root)]) == 1
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "backup_schema_unsupported"
    assert payload["error"]["details"]["schema"]["state"] == "future"
    assert not destination.exists()


def test_backup_fails_closed_for_future_compat_marker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "future-compat"
    _build_root(root, with_session=False)
    with sqlite3.connect(root / data_cli.CHAT_DB_NAME) as conn:
        conn.execute(
            "update chat_schema_meta set version = 2 where schema_id = ?",
            (data_cli.CHAT_SCHEMA_ID,),
        )

    destination = tmp_path / "backup"
    assert data_cli.run_cli(["backup", str(destination), "--root", str(root)]) == 1

    payload = _json_output(capsys)
    assert payload["error"]["code"] == "backup_schema_unsupported"
    assert payload["error"]["details"]["schema"]["state"] == "future"
    assert not destination.exists()


def test_restore_rejects_checksum_mismatch_and_checksum_valid_bad_session_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    _build_root(root)
    backup = tmp_path / "backup"
    _backup(root, backup, capsys)
    sessions_path = backup / data_cli.SESSION_NAME

    sessions_path.write_text("{}\n", encoding="utf-8")
    assert data_cli.run_cli(["restore", str(backup), "--root", str(tmp_path / "target")]) == 1
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "backup_checksum_mismatch"

    manifest_path = backup / data_cli.BACKUP_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["god_sessions"].update(
        {"size_bytes": sessions_path.stat().st_size, "sha256": _digest(sessions_path)}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert data_cli.run_cli(["restore", str(backup), "--root", str(tmp_path / "target")]) == 1
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "session_registry_invalid"


def test_restore_requires_replace_and_sanitizes_transport_binding_without_identity_loss(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    conversation_id, participant_id = _build_root(source)
    RoomRuntimeOperatorActionStore(source / data_cli.CHAT_DB_NAME).reserve(
        client_action_id="recover-before-backup",
        request_fingerprint="recover-fingerprint",
        incident_guard="incident-before-backup",
        before_state="degraded",
        before_code="room_runner_heartbeat_stale",
    )
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    target = tmp_path / "target"
    CompatDataTestStore(target / data_cli.CHAT_DB_NAME).create_conversation("Existing target")

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 1
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "restore_target_exists"

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target), "--replace"]) == 0
    payload = _json_output(capsys)
    assert payload["state"] == "succeeded"
    assert not (target / data_cli.OPERATION_JOURNAL_NAME).exists()
    restored = GodSessionRegistry(target / data_cli.SESSION_NAME).list()
    assert len(restored) == 1
    record = restored[0]
    assert (record.conversation_id, record.participant_id) == (
        conversation_id,
        participant_id,
    )
    assert record.status == "starting"
    assert record.pid is None
    assert record.provider_session_id is None
    assert record.provider_session_kind is None
    assert record.provider_binding_status is None
    assert record.provider_binding_failure_reason is None
    assert conversation_id in {
        item.id for item in CompatDataTestStore(target / data_cli.CHAT_DB_NAME).list_conversations()
    }
    restored_action, created = RoomRuntimeOperatorActionStore(
        target / data_cli.CHAT_DB_NAME
    ).reserve(
        client_action_id="recover-before-backup",
        request_fingerprint="recover-fingerprint",
        incident_guard="incident-before-backup",
        before_state="degraded",
        before_code="room_runner_heartbeat_stale",
    )
    assert created is False
    assert restored_action["status"] == "requested"


def test_restore_without_replace_preserves_a_sidecar_only_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    _build_root(source, with_session=False)
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    target = tmp_path / "target"
    target.mkdir()
    wal = target / f"{data_cli.CHAT_DB_NAME}-wal"
    wal.write_bytes(b"unreconciled authority residue")

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 1

    assert _json_output(capsys)["error"]["code"] == "restore_target_exists"
    assert wal.read_bytes() == b"unreconciled authority residue"
    assert not (target / data_cli.CHAT_DB_NAME).exists()


def test_restore_fences_a_claimed_attempt_before_installing_authority(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    conversation_id, participant_id = _build_root(source, with_session=False)
    now = datetime(2026, 7, 11, tzinfo=UTC)
    claim = RoomKernelStore(source / data_cli.CHAT_DB_NAME).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant_id,
        lease_owner="room-host:old-generation",
        lease_ttl_s=300,
        base_attempt_limit=2,
        now=now,
    )
    assert claim is not None
    old_token = claim["observation"]["lease_token"]
    observation_id = claim["observation"]["observation_id"]
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    target = tmp_path / "target"

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 0
    payload = _json_output(capsys)

    assert payload["runtime_fence"]["reopened_pending_count"] == 1
    observation = RoomKernelStore(target / data_cli.CHAT_DB_NAME).get_observation(observation_id)
    assert observation["status"] == "pending"
    assert observation["lease_token"] is None
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        RoomKernelStore(target / data_cli.CHAT_DB_NAME).complete_observation(
            conversation_id=conversation_id,
            participant_id=participant_id,
            caller_identity=f"god:old:{participant_id}",
            observation_id=observation_id,
            lease_token=old_token,
            client_request_id="late-after-restore",
            outcome_type="noop",
            now=now + timedelta(seconds=1),
        )


def test_restore_reopens_memory_index_and_clears_only_derived_cache(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    conversation_id, _participant_id = _build_root(source, with_session=False)
    kernel = RoomKernelStore(source / data_cli.CHAT_DB_NAME)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="A second source-backed activity.",
        client_request_id="memory-restore-second-activity",
    )
    RoomMemoryBindingStore(source / data_cli.CHAT_DB_NAME).ensure_binding(
        conversation_id=conversation_id
    )
    with sqlite3.connect(source / data_cli.CHAT_DB_NAME) as conn:
        conn.execute(
            """update room_memory_bindings
               set session_id = 'old-memory-session', session_state = 'bound',
                   attachment_id = 'old-memory-attachment-' || scope_type,
                   attachment_state = 'attached'"""
        )
        rows = conn.execute(
            "select outbox_id from room_memory_outbox order by created_at, outbox_id"
        ).fetchall()
        assert len(rows) == 2
        conn.execute(
            """update room_memory_outbox
               set state = 'delivered', delivered_at = updated_at
               where outbox_id = ?""",
            (rows[0][0],),
        )
        conn.execute(
            """insert into room_memory_deliveries
               (delivery_id, outbox_id, attempt_number, worker_id,
                lease_token_sha256, state, request_digest, claimed_at, updated_at)
               values ('memory-delivery-before-restore', ?, 1, 'old-memory-runner',
                       ?, 'claimed', ?, '2026-07-12T00:00:00Z',
                       '2026-07-12T00:00:00Z')""",
            (rows[1][0], "sha256:" + "a" * 64, "sha256:" + "b" * 64),
        )
        conn.execute(
            """update room_memory_outbox
               set state = 'claimed', attempt_count = 1,
                   lease_owner = 'old-memory-runner', lease_token = 'secret-lease',
                   acquired_at = '2026-07-12T00:00:00Z',
                   expires_at = '2026-07-12T01:00:00Z',
                   current_delivery_id = 'memory-delivery-before-restore'
               where outbox_id = ?""",
            (rows[1][0],),
        )
    RoomMemoryRebuildActionStore(source / data_cli.CHAT_DB_NAME).reserve(
        client_action_id="memory-rebuild-before-restore",
        request_fingerprint="memory-rebuild-fingerprint",
        incident_guard="memoryos_incident_before_restore",
        before_state="degraded",
        before_code="memoryos_crash_loop",
    )

    source_derived = memoryos_derived_dir(source)
    source_derived.mkdir(parents=True)
    (source_derived / "memoryos.db").write_bytes(b"must not enter backup")
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    assert sorted(path.name for path in backup.iterdir()) == [
        data_cli.CHAT_DB_NAME,
        data_cli.SESSION_NAME,
        data_cli.BACKUP_MANIFEST_NAME,
    ]
    target = tmp_path / "target"
    derived = memoryos_derived_dir(target)
    derived.mkdir(parents=True)
    (derived / "memoryos.db").write_bytes(b"derived index bytes")
    sibling = target / "runtime" / "room-codex-home" / "sentinel"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("preserve", encoding="utf-8")

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 0
    payload = _json_output(capsys)

    assert payload["memory_cache_cleared"] is True
    assert payload["memory_index_fence"] == {
        "bindings_reset": 3,
        "deliveries_reopened": 2,
        "claimed_attempts_fenced": 1,
        "candidates_requeued": 0,
        "actions_fenced": 1,
    }
    assert not derived.exists()
    assert sibling.read_text(encoding="utf-8") == "preserve"
    with sqlite3.connect(target / data_cli.CHAT_DB_NAME) as conn:
        bindings = conn.execute(
            """select session_id, session_state, attachment_id, attachment_state
               from room_memory_bindings"""
        ).fetchall()
        outbox = conn.execute(
            """select state, lease_owner, lease_token, current_delivery_id,
                      next_attempt_at, delivered_at
               from room_memory_outbox"""
        ).fetchall()
        delivery = conn.execute("select state, reason_code from room_memory_deliveries").fetchone()
        rebuild_action = conn.execute(
            """select status, phase, after_code, reason_code
               from room_memory_rebuild_actions
               where client_action_id = 'memory-rebuild-before-restore'"""
        ).fetchone()
    assert bindings == [(None, "unbound", None, "pending")] * 3
    assert outbox == [("pending", None, None, None, None, None)] * 2
    assert delivery == ("failed", "room_memory_restore_rebuild_required")
    assert rebuild_action == (
        "failed",
        "complete",
        "room_memory_restore_action_not_replayed",
        "room_memory_restore_action_not_replayed",
    )


def test_completed_peer_batch_survives_doctor_backup_and_restore(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    _conversation_id, peer_batch_id = _build_completed_peer_batch(source)

    assert data_cli.run_cli(["doctor", "--root", str(source)]) == 0
    doctor = _json_output(capsys)
    authority = next(
        check for check in doctor["checks"] if check["name"] == "chat_authority_invariants"
    )
    assert authority["detail"]["attempt_binding_mismatch_count"] == 0
    assert authority["detail"]["observation_batch_invalid_count"] == 0

    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    target = tmp_path / "target"
    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 0
    _json_output(capsys)

    with sqlite3.connect(target / data_cli.CHAT_DB_NAME) as conn:
        batch = conn.execute(
            "select phase, member_count from room_observation_batches where batch_id = ?",
            (peer_batch_id,),
        ).fetchone()
        completed_members = conn.execute(
            """select count(*) from room_observation_batch_members bm
               join room_observations o on o.observation_id = bm.observation_id
               where bm.batch_id = ? and o.status = 'completed'""",
            (peer_batch_id,),
        ).fetchone()[0]
    assert batch == ("peer", 2)
    assert completed_members == 2
    assert data_cli.run_cli(["doctor", "--root", str(target)]) == 0
    restored_doctor = _json_output(capsys)
    restored_authority = next(
        check for check in restored_doctor["checks"] if check["name"] == "chat_authority_invariants"
    )
    assert restored_authority["detail"]["observation_batch_invalid_count"] == 0


@pytest.mark.parametrize(
    "corruption",
    ["digest", "member_count", "primary_membership", "attempt_batch_binding"],
)
def test_batch_authority_corruption_is_rejected(
    tmp_path: Path,
    corruption: str,
) -> None:
    source = tmp_path / corruption
    _conversation_id, peer_batch_id = _build_completed_peer_batch(source)
    with sqlite3.connect(source / data_cli.CHAT_DB_NAME) as conn:
        if corruption == "digest":
            conn.execute(
                "update room_observation_batches set digest = ? where batch_id = ?",
                ("0" * 64, peer_batch_id),
            )
        elif corruption == "member_count":
            conn.execute(
                "update room_observation_batches set member_count = 1 where batch_id = ?",
                (peer_batch_id,),
            )
        elif corruption == "primary_membership":
            conn.execute(
                """update room_observation_batches set primary_observation_id = (
                       select observation_id from room_observation_batch_members
                       where batch_id = ? and ordinal = 1
                   ) where batch_id = ?""",
                (peer_batch_id, peer_batch_id),
            )
        else:
            conn.execute(
                "update room_observation_attempts set batch_id = null where batch_id = ?",
                (peer_batch_id,),
            )

    with pytest.raises(data_cli.DataError, match="chat authority invariants failed") as error:
        inspect_database(
            source / data_cli.CHAT_DB_NAME,
            require_current=True,
        )
    assert error.value.code == "chat_db_corrupt"


def test_backup_rejects_a_legacy_claim_without_a_durable_attempt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "source"
    _conversation_id, _participant_id = _build_root(root, with_session=False)
    with sqlite3.connect(root / data_cli.CHAT_DB_NAME) as conn:
        conn.execute(
            """update room_observations set status = 'claimed',
                   lease_owner = 'legacy-host', lease_token = 'legacy-token',
                   acquired_at = '2026-07-11T00:00:00Z',
                   expires_at = '2099-01-01T00:00:00Z', current_attempt_id = null"""
        )

    assert data_cli.run_cli(["backup", str(tmp_path / "backup"), "--root", str(root)]) == 1

    payload = _json_output(capsys)
    assert payload["error"]["code"] == "chat_db_corrupt"
    assert not (tmp_path / "backup").exists()


def test_restore_and_compact_reject_live_workroom_probe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _build_root(source)
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    target = tmp_path / "target"
    _build_root(target)
    monkeypatch.setattr(
        data_runtime_guard,
        "runtime_probe",
        lambda _root: {
            "managed": {
                "state": "ready",
                "manager_live": True,
                "services": [{"service": "chat_api", "live": True, "pid": 9911}],
            },
            "inventory": {"services": []},
        },
    )

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target), "--replace"]) == 1
    assert _json_output(capsys)["error"]["code"] == "workroom_running"
    assert data_cli.run_cli(["compact", "--root", str(target)]) == 1
    assert _json_output(capsys)["error"]["code"] == "workroom_running"


@pytest.mark.parametrize(
    "service",
    ["chat_api", "room_runner", "room_mcp", "execution_controller", "memoryos"],
)
def test_restore_rejects_an_unscoped_authority_process(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    service: str,
) -> None:
    source = tmp_path / "source"
    _build_root(source)
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    target = tmp_path / "target"
    monkeypatch.setattr(
        data_runtime_guard,
        "runtime_probe",
        lambda _root: {
            "managed": {"state": "stopped", "manager_live": False, "services": []},
            "inventory": {"services": []},
            "global_inventory": {"services": [{"service": service, "pids": [8811]}]},
        },
    )

    assert data_cli.run_cli(["restore", str(backup), "--root", str(target)]) == 1
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "workroom_running"
    assert payload["error"]["details"]["pids"] == [8811]


def test_restore_revalidates_the_database_bytes_copied_after_preflight(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _build_root(source)
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    replacement_root = tmp_path / "replacement"
    _build_root(replacement_root, with_session=False)
    original_copy = data_restore.shutil.copy2

    def replace_verified_source(_source: Path, destination: Path) -> Path:
        return original_copy(replacement_root / data_cli.CHAT_DB_NAME, destination)

    monkeypatch.setattr(data_restore.shutil, "copy2", replace_verified_source)

    assert data_cli.run_cli(["restore", str(backup), "--root", str(tmp_path / "target")]) == 1
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "backup_checksum_mismatch"
    assert not (tmp_path / "target" / data_cli.CHAT_DB_NAME).exists()


def test_restore_rejects_session_metadata_that_conflicts_with_participant_authority(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    _build_root(source)
    backup = tmp_path / "backup"
    _backup(source, backup, capsys)
    sessions_path = backup / data_cli.SESSION_NAME
    sessions = json.loads(sessions_path.read_text(encoding="utf-8"))
    sessions["sessions"][0]["role"] = "wrong-role"
    sessions_path.write_text(json.dumps(sessions), encoding="utf-8")
    manifest_path = backup / data_cli.BACKUP_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["god_sessions"].update(
        {"size_bytes": sessions_path.stat().st_size, "sha256": _digest(sessions_path)}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert data_cli.run_cli(["restore", str(backup), "--root", str(tmp_path / "target")]) == 1
    assert _json_output(capsys)["error"]["code"] == "session_registry_invalid"


def test_compact_preserves_logical_authority_and_room_high_water(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    conversation_id, _participant_id = _build_root(root)
    db_path = root / data_cli.CHAT_DB_NAME
    chat = CompatDataTestStore(db_path)
    disposable_ids = [
        chat.add_message(conversation_id, "Human", "human", f"temporary-{index}").id
        for index in range(80)
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "delete from messages where id = ?",
            [(message_id,) for message_id in disposable_ids[::2]],
        )
    before = database_evidence(db_path)

    assert data_cli.run_cli(["compact", "--root", str(root)]) == 0

    payload = _json_output(capsys)
    assert payload["state"] == "succeeded"
    assert payload["after_size_bytes"] <= payload["before_size_bytes"]
    assert database_evidence(db_path) == before
    assert not (root / data_cli.OPERATION_JOURNAL_NAME).exists()


def test_online_backup_captures_consistent_snapshot_during_wal_writes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    conversation_id, _participant_id = _build_root(root, with_session=False)
    db_path = root / data_cli.CHAT_DB_NAME
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("pragma journal_mode = wal").fetchone()[0] == "wal"
    stop = threading.Event()
    started = threading.Event()
    errors: list[BaseException] = []

    def write_messages() -> None:
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                index = 0
                while not stop.is_set():
                    conn.execute(
                        "insert into messages(id, conversation_id, author, role, content, "
                        "created_at) values (?, ?, 'Human', 'human', ?, ?)",
                        (
                            f"wal-message-{index}",
                            conversation_id,
                            f"wal-{index}",
                            "2026-07-11T00:00:00Z",
                        ),
                    )
                    conn.commit()
                    index += 1
                    started.set()
                    time.sleep(0.001)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writer = threading.Thread(target=write_messages, daemon=True)
    writer.start()
    assert started.wait(timeout=5)
    backup = tmp_path / "wal-backup"
    try:
        output = _backup(root, backup, capsys)
    finally:
        stop.set()
        writer.join(timeout=5)

    assert not errors
    assert not writer.is_alive()
    assert output["source_journal_mode"] == "wal"
    assert {item.name for item in backup.iterdir()} == {
        data_cli.BACKUP_MANIFEST_NAME,
        data_cli.CHAT_DB_NAME,
        data_cli.SESSION_NAME,
    }
    manifest, backup_db, _sessions, _records = data_cli.verify_backup(backup)
    assert manifest["database"]["source_journal_mode"] == "wal"
    with sqlite3.connect(backup_db) as conn:
        assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert (
            conn.execute("select count(*) from messages where id like 'wal-message-%'").fetchone()[
                0
            ]
            >= 1
        )


def test_doctor_and_backup_remain_bounded_with_ten_thousand_room_activities(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    db_path = root / data_cli.CHAT_DB_NAME
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
            "2026-07-11T00:00:00Z",
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
    (root / data_cli.SESSION_NAME).write_text('{"sessions":[]}\n', encoding="utf-8")

    started = time.monotonic()
    assert data_cli.run_cli(["doctor", "--root", str(root)]) == 0
    _json_output(capsys)
    backup = tmp_path / "backup-10k"
    output = _backup(root, backup, capsys)
    elapsed = time.monotonic() - started

    assert elapsed < 30
    assert output["rooms"] == 1
    manifest = json.loads((backup / data_cli.BACKUP_MANIFEST_NAME).read_text())
    assert manifest["totals"]["room_activity_count"] == 10_000
    assert manifest["rooms"] == [
        {
            "conversation_id": conversation.id,
            "activity_count": 10_000,
            "latest_activity_seq": 10_000,
            "frontend_event_count": 0,
            "latest_frontend_event_seq": 0,
        }
    ]
    assert (backup / data_cli.BACKUP_MANIFEST_NAME).stat().st_size < 10_000
