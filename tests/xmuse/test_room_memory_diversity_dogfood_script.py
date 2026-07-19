# ruff: noqa: E501
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import room_memory_diversity_dogfood as dogfood


def _evidence() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "room_memory_diversity_evidence/v1",
        "run_ref": "run_" + "a" * 32,
        "configuration": {"room_count": 3, "agents_per_room": 4, "correlation_count": 18},
        "counts": {
            "settled_correlations": 18,
            "ok_receipts": 6,
            "nonempty_receipt_items": 6,
            "archival_project_items": 1,
            "derived_items": 1,
            "project_rule_cross_room_hits": 1,
            "user_preference_cross_room_hits": 1,
            "decision_nonrecent_hits": 1,
            "lexical_hits": 1,
            "semantic_hits": 1,
            "source_refs_reproved": 4,
            "memoryos_child_count_after_recovery": 1,
            "unapproved_cross_room_sources": 0,
            "unrelated_room_hits": 0,
            "browser_console_errors": 0,
            "sensitive_leaks": 0,
        },
        "proofs": {
            "project_rule_approved": True,
            "user_preference_approved": True,
            "decision_approved": True,
            "source_refs_reproved": True,
            "memoryos_killed": True,
            "memoryos_recovered": True,
            "full_local_capability_ready": True,
            "derived_layer_present": True,
            "all_target_correlations_settled": True,
            "sqlite_integrity_ok": True,
        },
        "digests": {
            "source_ref_digest": "sha256:" + "1" * 64,
            "context_digest": "sha256:" + "2" * 64,
            "capability_digest": "sha256:" + "3" * 64,
            "evidence_digest": "",
        },
    }
    value["digests"]["evidence_digest"] = dogfood._build_evidence_digest(value)  # type: ignore[index]
    return value


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table conversations (id text primary key);
        create table participants (participant_id text, conversation_id text, status text, cli_kind text);
        create table room_activities (
            activity_id text primary key, conversation_id text, correlation_id text,
            seq integer, causation_id text, visibility text, actor_kind text
        );
        create table room_observations (
            observation_id text primary key, activity_id text, delivery_mode text, status text
        );
        create table room_observation_attempts (
            attempt_id text primary key, conversation_id text, observation_id text
        );
        create table room_observation_batch_members (batch_id text, activity_id text);
        create table room_observation_batches (batch_id text, primary_observation_id text);
        create table room_memory_candidates (
            candidate_id text primary key, conversation_id text, kind text, target_scope text,
            approval_state text, publish_state text, source_activity_ids_json text
        );
        create table room_memory_outbox (candidate_id text, document_id text, state text);
        create table room_memory_attempt_receipts (
            attempt_id text primary key, conversation_id text, status text, item_count integer,
            context_payload_sha256 text, source_activity_ids_json text, item_refs_json text
        );
        create table room_attempt_skill_decisions (attempt_id text, context_payload_sha256 text);
        create table room_memory_message_outbox (state text);
        """
    )


def _seed(root: Path) -> dict[str, object]:
    root.mkdir()
    db = root / "chat.db"
    with sqlite3.connect(db) as conn:
        _schema(conn)
        rooms = ("room-a", "room-b", "room-c")
        conn.executemany("insert into conversations values (?)", ((room,) for room in rooms))
        conn.executemany(
            "insert into participants values (?,?,?,?)",
            ((f"{room}-p{index}", room, "active", "codex") for room in rooms for index in range(4)),
        )
        source_rows = (
            ("source-project", "room-a", "a-0", 1),
            ("source-preference", "room-b", "b-0", 1),
            ("source-decision", "room-c", "c-0", 1),
            ("source-derived", "room-c", "c-1", 2),
        )
        for activity_id, room, correlation, seq in source_rows:
            conn.execute(
                "insert into room_activities values (?,?,?,?,?,?,?)",
                (activity_id, room, correlation, seq, None, "room", "human"),
            )
        for room, prefix in zip(rooms, ("a", "b", "c"), strict=True):
            for ordinal in range(2, 6):
                conn.execute(
                    "insert into room_activities values (?,?,?,?,?,?,?)",
                    (
                        f"{prefix}-filler-{ordinal}",
                        room,
                        f"{prefix}-{ordinal}",
                        ordinal,
                        None,
                        "room",
                        "agent",
                    ),
                )
        conn.execute(
            "insert into room_activities values (?,?,?,?,?,?,?)",
            ("b-filler-1", "room-b", "b-1", 1, None, "room", "agent"),
        )
        conn.execute(
            "insert into room_activities values (?,?,?,?,?,?,?)",
            ("a-filler-1", "room-a", "a-1", 1, None, "room", "agent"),
        )
        candidates = (
            (
                "candidate-project",
                "room-a",
                "project_rule",
                "project",
                "source-project",
                "doc-project",
            ),
            (
                "candidate-preference",
                "room-b",
                "user_preference",
                "local_user",
                "source-preference",
                "doc-preference",
            ),
            (
                "candidate-semantic-preference",
                "room-b",
                "user_preference",
                "local_user",
                "source-preference",
                "doc-semantic-preference",
            ),
            (
                "candidate-decision",
                "room-c",
                "room_decision",
                "room",
                "source-decision",
                "doc-decision",
            ),
        )
        for candidate_id, room, kind, scope, source, document in candidates:
            conn.execute(
                "insert into room_memory_candidates values (?,?,?,?,?,?,?)",
                (candidate_id, room, kind, scope, "approved", "delivered", json.dumps([source])),
            )
            conn.execute(
                "insert into room_memory_outbox values (?,?,?)",
                (candidate_id, document, "delivered"),
            )
        attempts = {
            "project_rule_cross_room": (
                "attempt-project",
                "room-b",
                "doc-project",
                ["source-project"],
            ),
            "user_preference_cross_room": (
                "attempt-preference",
                "room-c",
                "doc-preference",
                ["source-preference"],
            ),
            "decision_nonrecent": (
                "attempt-decision",
                "room-a",
                "doc-decision",
                ["source-decision"],
            ),
            "lexical": ("attempt-lexical", "room-b", "doc-project", ["source-project"]),
            "semantic": (
                "attempt-semantic",
                "room-c",
                "doc-semantic-preference",
                ["source-preference"],
            ),
            "derived": ("attempt-derived", "room-a", None, ["source-derived"]),
        }
        for index, (label, (attempt_id, room, document, sources)) in enumerate(attempts.items()):
            activity_id = f"query-{label}"
            correlation = {"room-a": "a-5", "room-b": "b-5", "room-c": "c-5"}[room]
            conn.execute(
                "insert into room_activities values (?,?,?,?,?,?,?)",
                (activity_id, room, correlation, 20 + index, None, "room", "human"),
            )
            observation_id = f"observation-{label}"
            conn.execute(
                "insert into room_observations values (?,?,?,?)",
                (observation_id, activity_id, "active", "completed"),
            )
            conn.execute(
                "insert into room_observation_attempts values (?,?,?)",
                (attempt_id, room, observation_id),
            )
            item: dict[str, object] = {
                "layer": "archival",
                "derived": False,
                "context_included": True,
                "source_activity_ids": sources,
            }
            if document is not None:
                item["document_id"] = document
            else:
                item.update({"layer": "page", "derived": True})
            context = "sha256:" + str(index + 1) * 64
            conn.execute(
                "insert into room_memory_attempt_receipts values (?,?,?,?,?,?,?)",
                (attempt_id, room, "ok", 1, context, json.dumps(sources), json.dumps([item])),
            )
            conn.execute(
                "insert into room_attempt_skill_decisions values (?,?)", (attempt_id, context)
            )
    return {
        "schema_version": dogfood.MANIFEST_SCHEMA,
        "room_ids": ["room-a", "room-b", "room-c"],
        "candidates": {
            "project_rule": "candidate-project",
            "user_preference": "candidate-preference",
            "semantic_preference": "candidate-semantic-preference",
            "room_decision": "candidate-decision",
        },
        "query_attempt_ids": {
            "project_rule_cross_room": "attempt-project",
            "user_preference_cross_room": "attempt-preference",
            "decision_nonrecent": "attempt-decision",
            "lexical": "attempt-lexical",
            "semantic": "attempt-semantic",
            "derived": "attempt-derived",
        },
        "memoryos_fault": {
            "sigkill_injected": True,
            "single_child_recovered": True,
            "full_local_capability_ready": True,
        },
        "browser": {"headed": True, "console_clean": True},
        "capability_digest": "sha256:" + "a" * 64,
    }


def test_fixture_mode_builds_only_safe_contract_result(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.json"
    destination = tmp_path / "result.json"
    fixture.write_text(json.dumps(_evidence()), encoding="utf-8")

    assert dogfood.main(["--fixture-evidence", str(fixture), "--result", str(destination)]) == 0

    result = json.loads(destination.read_text(encoding="utf-8"))
    assert result["schema_version"] == "room_memory_diversity_result/v1"
    assert result["status"] == "passed"
    assert "fixture.json" not in json.dumps(result)


def test_real_collector_reproves_safe_durable_facts(tmp_path: Path) -> None:
    manifest = _seed(tmp_path / "runtime")

    evidence = dogfood.collect_diversity_evidence(
        root=tmp_path / "runtime", manifest=manifest, run_salt="test-run"
    )

    result = dogfood.build_memory_diversity_result(evidence=evidence)
    assert result["status"] == "passed"
    rendered = json.dumps(result)
    for private in ("room-a", "candidate-project", "attempt-project", "source-project"):
        assert private not in rendered


def test_real_collector_rejects_manifest_attempt_aliasing(tmp_path: Path) -> None:
    manifest = _seed(tmp_path / "runtime")
    manifest["query_attempt_ids"]["semantic"] = manifest["query_attempt_ids"]["lexical"]

    with pytest.raises(dogfood.MemoryDiversityCollectorError) as raised:
        dogfood.collect_diversity_evidence(
            root=tmp_path / "runtime", manifest=manifest, run_salt="salt"
        )

    assert raised.value.code == "memory_diversity_manifest_invalid"


def test_real_collector_rejects_missing_receipt_source(tmp_path: Path) -> None:
    manifest = _seed(tmp_path / "runtime")
    with sqlite3.connect(tmp_path / "runtime" / "chat.db") as conn:
        conn.execute(
            "update room_memory_attempt_receipts set source_activity_ids_json = ? where attempt_id = ?",
            (json.dumps(["source-missing"]), "attempt-project"),
        )

    with pytest.raises(dogfood.MemoryDiversityCollectorError) as raised:
        dogfood.collect_diversity_evidence(
            root=tmp_path / "runtime", manifest=manifest, run_salt="salt"
        )

    assert raised.value.code == "memory_diversity_source_unproven"


def test_item_source_must_be_reproved_before_candidate_hit(tmp_path: Path) -> None:
    manifest = _seed(tmp_path / "runtime")
    with sqlite3.connect(tmp_path / "runtime" / "chat.db") as conn:
        row = conn.execute(
            "select item_refs_json from room_memory_attempt_receipts where attempt_id = ?",
            ("attempt-project",),
        ).fetchone()
        assert row is not None
        item = json.loads(row[0])[0]
        item["source_activity_ids"] = ["source-forged"]
        conn.execute(
            "update room_memory_attempt_receipts set item_refs_json = ? where attempt_id = ?",
            (json.dumps([item]), "attempt-project"),
        )

    evidence = dogfood.collect_diversity_evidence(
        root=tmp_path / "runtime", manifest=manifest, run_salt="salt"
    )
    assert evidence["counts"]["project_rule_cross_room_hits"] == 0


def test_real_collector_rejects_attempt_outside_manifest_rooms(tmp_path: Path) -> None:
    manifest = _seed(tmp_path / "runtime")
    with sqlite3.connect(tmp_path / "runtime" / "chat.db") as conn:
        conn.execute(
            "update room_observation_attempts set conversation_id = 'other-room' where attempt_id = ?",
            ("attempt-project",),
        )
        conn.execute(
            "update room_memory_attempt_receipts set conversation_id = 'other-room' where attempt_id = ?",
            ("attempt-project",),
        )

    with pytest.raises(dogfood.MemoryDiversityCollectorError) as raised:
        dogfood.collect_diversity_evidence(
            root=tmp_path / "runtime", manifest=manifest, run_salt="salt"
        )

    assert raised.value.code == "memory_diversity_attempt_room_unproven"


def test_headless_manifest_is_rejected_and_old_schema_writes_safe_error(tmp_path: Path) -> None:
    manifest = _seed(tmp_path / "runtime")
    manifest["browser"]["headed"] = False
    with pytest.raises(dogfood.MemoryDiversityCollectorError) as raised:
        dogfood.load_private_manifest_from_mapping(manifest)
    assert raised.value.code == "memory_diversity_browser_headed_required"

    root = tmp_path / "old-runtime"
    root.mkdir()
    sqlite3.connect(root / "chat.db").close()
    manifest_path = tmp_path / "manifest.json"
    result_path = tmp_path / "error.json"
    manifest_path.write_text(json.dumps(_seed(tmp_path / "separate-runtime")), encoding="utf-8")

    assert (
        dogfood.main(
            [
                "--root",
                str(root),
                "--manifest",
                str(manifest_path),
                "--run-salt",
                "salt",
                "--result",
                str(result_path),
            ]
        )
        == 1
    )
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "schema_version": "room_memory_diversity_dogfood_error/v1",
        "reason_code": "memory_diversity_chat_db_incompatible",
    }
