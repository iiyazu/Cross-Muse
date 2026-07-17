from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import room_memory_recall_dogfood as dogfood
from xmuse_core.chat.room_memory_recall_dogfood import build_memory_recall_dogfood_result


def _manifest() -> dict[str, object]:
    return {
        "schema_version": dogfood.MANIFEST_SCHEMA,
        "room_a_id": "room-a-private",
        "room_b_id": "room-b-private",
        "candidate_id": "candidate-private",
        "target_source_activity_id": "activity-a-source-private",
        "room_b_attempt_id": "attempt-b-private",
        "derived_attempt_id": "attempt-a-derived-private",
        "derived_evidence": {
            "layer": "recall",
            "source_activity_ids": ["activity-a-source-private"],
        },
        "memoryos_fault": {
            "sigkill_injected": True,
            "single_child_recovered": True,
            "full_local_capability_ready": True,
        },
        "browser": {"headed": True, "console_errors": 0},
    }


def _create_db(root: Path) -> None:
    root.mkdir()
    conn = sqlite3.connect(root / "chat.db")
    conn.executescript(
        """
        create table room_memory_bindings (
          conversation_id text, scope_type text, archive_id text, session_id text,
          session_state text, attachment_state text
        );
        create table room_memory_candidates (
          candidate_id text, conversation_id text, author_participant_id text,
          kind text, target_scope text, approval_state text, approval_mode text,
          resolved_by text, publish_state text, source_activity_ids_json text
        );
        create table room_memory_outbox (
          candidate_id text, conversation_id text, document_id text, state text
        );
        create table room_memory_message_outbox (conversation_id text, state text);
        create table room_observation_attempts (
          attempt_id text, conversation_id text, observation_id text
        );
        create table room_observations (
          observation_id text, activity_id text, delivery_mode text, status text
        );
        create table room_activities (
          activity_id text, conversation_id text, correlation_id text, seq integer,
          causation_id text, actor_kind text, visibility text
        );
        create table room_memory_attempt_receipts (
          attempt_id text, conversation_id text, status text, item_count integer,
          item_refs_json text, source_activity_ids_json text, context_payload_sha256 text,
          evidence_sha256 text
        );
        create table room_attempt_skill_decisions (attempt_id text, context_payload_sha256 text);
        create table room_observation_batches (batch_id text, primary_observation_id text);
        create table room_observation_batch_members (batch_id text, activity_id text);
        """
    )
    for room in ("room-a-private", "room-b-private"):
        conn.executemany(
            "insert into room_memory_bindings values (?, ?, ?, ?, 'bound', 'attached')",
            [
                (
                    room,
                    scope,
                    "archive-project-shared" if scope == "project" else f"archive-{room}-{scope}",
                    f"session-{room}",
                )
                for scope in ("room", "local_user", "project")
            ],
        )
        conn.execute("insert into room_memory_message_outbox values (?, 'delivered')", (room,))
    conn.execute(
        """insert into room_memory_candidates
           values (?, ?, 'participant-author', 'project_rule', 'project', 'approved',
                   'operator', 'operator', 'delivered', ?)""",
        ("candidate-private", "room-a-private", json.dumps(["activity-a-source-private"])),
    )
    conn.execute(
        "insert into room_memory_outbox values (?, ?, ?, 'delivered')",
        ("candidate-private", "room-a-private", "xmuse-room-memory-candidate-candidate-private"),
    )
    conn.execute(
        "insert into room_activities values (?, ?, 'corr-a', 1, ?, 'human', 'room')",
        ("activity-a-source-private", "room-a-private", "activity-a-source-private"),
    )
    conn.execute(
        "insert into room_activities values (?, ?, 'corr-a-derived', 2, ?, 'agent', 'room')",
        ("activity-a-derived-private", "room-a-private", "activity-a-derived-private"),
    )
    for seq in range(3, 12):
        activity = f"activity-a-tail-{seq}"
        conn.execute(
            "insert into room_activities values (?, 'room-a-private', ?, ?, ?, 'agent', 'room')",
            (activity, f"corr-a-tail-{seq}", seq, activity),
        )
    for seq in range(1, 11):
        activity = f"activity-b-{seq}"
        conn.execute(
            "insert into room_activities values (?, 'room-b-private', 'corr-b', ?, ?, ?, 'room')",
            (activity, seq, activity, "human" if seq == 1 else "agent"),
        )
    conn.executemany(
        "insert into room_observations values (?, ?, 'active', 'completed')",
        [("obs-b-private", "activity-b-10"), ("obs-a-private", "activity-a-tail-11")],
    )
    conn.executemany(
        "insert into room_observation_attempts values (?, ?, ?)",
        [
            ("attempt-b-private", "room-b-private", "obs-b-private"),
            ("attempt-a-derived-private", "room-a-private", "obs-a-private"),
        ],
    )
    candidate_doc = "xmuse-room-memory-candidate-candidate-private"
    conn.executemany(
        "insert into room_memory_attempt_receipts values (?, ?, 'ok', 1, ?, ?, ?, ?)",
        [
            (
                "attempt-b-private",
                "room-b-private",
                json.dumps(
                    [
                        {
                            "document_id": candidate_doc,
                            "layer": "archival",
                            "derived": False,
                            "context_included": True,
                            "source_activity_ids": ["activity-a-source-private"],
                        }
                    ]
                ),
                json.dumps(["activity-a-source-private"]),
                "sha256:" + "b" * 64,
                "sha256:" + "d" * 64,
            ),
            (
                "attempt-a-derived-private",
                "room-a-private",
                json.dumps(
                    [
                        {
                            "document_id": "xmuse-room-activity-activity-a-derived-private",
                            "layer": "recall",
                            "derived": True,
                            "context_included": True,
                            "source_activity_ids": ["activity-a-source-private"],
                        }
                    ]
                ),
                json.dumps(["activity-a-source-private"]),
                "sha256:" + "c" * 64,
                "sha256:" + "e" * 64,
            ),
        ],
    )
    conn.execute(
        "insert into room_attempt_skill_decisions values (?, ?)",
        ("attempt-b-private", "sha256:" + "b" * 64),
    )
    conn.commit()
    conn.close()


def test_collects_reproved_safe_cross_room_evidence(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _create_db(root)

    evidence = dogfood.collect_recall_evidence(
        root=root, manifest=_manifest(), run_salt="unshared-run-salt"
    )

    assert evidence["configuration"] == {"room_count": 2, "agents_per_room": 4}
    assert evidence["counts"]["attached_bindings"] == 6
    assert evidence["counts"]["room_a_correlations"] >= 6
    assert evidence["counts"]["room_a_tail_visible_activities"] >= 9
    assert evidence["counts"]["message_backlog"] == 0
    assert evidence["proofs"]["cross_room_project_source_reproved"] is True
    assert evidence["proofs"]["receipt_evidence_context_bound"] is True
    assert evidence["proofs"]["derived_layer_present"] is True
    assert build_memory_recall_dogfood_result(evidence=evidence)["status"] == "passed"
    encoded = json.dumps(evidence, sort_keys=True)
    for forbidden in (
        "room-a-private",
        "room-b-private",
        "candidate-private",
        "activity-a-source-private",
        "/tmp/",
        "session_id",
        "document_id",
    ):
        assert forbidden not in encoded


def test_collects_failed_candidate_gate_without_trusting_private_manifest(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _create_db(root)
    conn = sqlite3.connect(root / "chat.db")
    conn.execute("update room_memory_candidates set publish_state = 'queued'")
    conn.commit()
    conn.close()

    evidence = dogfood.collect_recall_evidence(root=root, manifest=_manifest(), run_salt="salt")

    assert evidence["proofs"]["candidate_approved"] is False
    assert evidence["counts"]["delivered_project_candidates"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.__setitem__("room_a_id", "room-b-private"),
        lambda manifest: manifest["derived_evidence"].__setitem__("layer", "archival"),
        lambda manifest: manifest["browser"].__setitem__("console_errors", -1),
    ],
)
def test_rejects_private_manifest_that_cannot_be_safely_reproved(mutate: object) -> None:
    manifest = _manifest()
    mutate(manifest)  # type: ignore[operator]

    with pytest.raises(dogfood.RecallDogfoodCollectorError):
        dogfood.load_private_manifest_from_mapping(manifest)
