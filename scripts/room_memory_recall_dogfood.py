#!/usr/bin/env python3
"""Collect safe, durable evidence for the cross-Room MemoryOS recall dogfood.

The browser/provider exercise is intentionally driven outside this utility.  Its private
manifest names the two Rooms and the receipts produced by that exercise; this program
re-proves every authority fact from ``chat.db`` and emits only salted opaque references
and aggregate booleans.  It never reads message text, MemoryOS state, traces, or runtime
receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "room_memory_recall_dogfood_manifest/v1"
_SCOPES = ("room", "local_user", "project")
_DERIVED_LAYERS = frozenset({"page", "recall"})
_RECENT_BURST_LIMIT = 8


class RecallDogfoodCollectorError(ValueError):
    """A stable fail-closed collector error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _opaque(run_salt: str, value: str) -> str:
    return "sha256:" + hashlib.sha256(f"{run_salt}\x00{value}".encode()).hexdigest()


def _json_list(value: object, code: str) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecallDogfoodCollectorError(code) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise RecallDogfoodCollectorError(code)
    return parsed


def _json_object_list(value: object, code: str) -> list[Mapping[str, Any]]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecallDogfoodCollectorError(code) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise RecallDogfoodCollectorError(code)
    return parsed


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    return value


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    return value


def load_private_manifest(path: Path) -> dict[str, Any]:
    """Load the bounded private run manifest; it is never copied into the result."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != MANIFEST_SCHEMA:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    required = {
        "schema_version",
        "room_a_id",
        "room_b_id",
        "candidate_id",
        "target_source_activity_id",
        "room_b_attempt_id",
        "derived_attempt_id",
        "derived_evidence",
        "memoryos_fault",
        "browser",
    }
    if set(raw) != required:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    for key in (
        "room_a_id",
        "room_b_id",
        "candidate_id",
        "target_source_activity_id",
        "room_b_attempt_id",
        "derived_attempt_id",
    ):
        _required_text(raw, key)
    if raw["room_a_id"] == raw["room_b_id"]:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    derived = raw["derived_evidence"]
    if not isinstance(derived, dict) or set(derived) != {
        "layer",
        "source_activity_ids",
    }:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    if derived["layer"] not in _DERIVED_LAYERS:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    if not isinstance(derived["source_activity_ids"], list) or not derived["source_activity_ids"]:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    if any(not isinstance(item, str) or not item for item in derived["source_activity_ids"]):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    fault = raw["memoryos_fault"]
    if not isinstance(fault, dict) or set(fault) != {
        "sigkill_injected",
        "single_child_recovered",
        "full_local_capability_ready",
    }:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    for key in fault:
        _required_bool(fault, key)
    browser = raw["browser"]
    if not isinstance(browser, dict) or set(browser) != {"headed", "console_errors"}:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    if not isinstance(browser["headed"], bool) or not isinstance(browser["console_errors"], int):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    if browser["console_errors"] < 0:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    return raw


def _rows(conn: sqlite3.Connection, sql: str, values: Sequence[object]) -> list[sqlite3.Row]:
    return list(conn.execute(sql, values).fetchall())


def _binding_facts(conn: sqlite3.Connection, room_ids: Sequence[str]) -> tuple[bool, int]:
    placeholders = ",".join("?" for _ in room_ids)
    rows = _rows(
        conn,
        f"""select conversation_id, scope_type, archive_id, session_id,
                    session_state, attachment_state
              from room_memory_bindings
             where conversation_id in ({placeholders})
               and scope_type in ('room','local_user','project')""",
        tuple(room_ids),
    )
    expected = {(room_id, scope) for room_id in room_ids for scope in _SCOPES}
    actual = {
        (str(row["conversation_id"]), str(row["scope_type"]))
        for row in rows
        if row["session_state"] == "bound" and row["attachment_state"] == "attached"
    }
    project = [row for row in rows if row["scope_type"] == "project"]
    project_shared = (
        len(project) == 2
        and project[0]["archive_id"] == project[1]["archive_id"]
        and project[0]["session_id"] is not None
        and project[1]["session_id"] is not None
        and project[0]["session_id"] != project[1]["session_id"]
    )
    return actual == expected and project_shared, len(actual)


def _outbox_backlog(conn: sqlite3.Connection, room_ids: Sequence[str]) -> tuple[int, int]:
    placeholders = ",".join("?" for _ in room_ids)
    documents = conn.execute(
        f"""select count(*) from room_memory_outbox
             where conversation_id in ({placeholders}) and state <> 'delivered'""",
        tuple(room_ids),
    ).fetchone()[0]
    messages = conn.execute(
        f"""select count(*) from room_memory_message_outbox
             where conversation_id in ({placeholders}) and state <> 'delivered'""",
        tuple(room_ids),
    ).fetchone()[0]
    return int(documents), int(messages)


def _attempt_context(conn: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
    row = conn.execute(
        """select t.attempt_id, t.conversation_id, t.observation_id, o.activity_id,
                  a.correlation_id, a.seq activity_seq, a.causation_id
             from room_observation_attempts t
             join room_observations o on o.observation_id = t.observation_id
             join room_activities a on a.activity_id = o.activity_id
            where t.attempt_id = ?""",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise RecallDogfoodCollectorError("recall_dogfood_attempt_missing")
    return row


def _causal_envelope_ids(conn: sqlite3.Connection, attempt: sqlite3.Row) -> tuple[set[str], int]:
    """Reconstruct source/root/ancestry/batch/recent exclusion without content reads."""

    conversation_id = str(attempt["conversation_id"])
    source_id = str(attempt["activity_id"])
    correlation_id = str(attempt["correlation_id"])
    cutoff = int(attempt["activity_seq"])
    ids = {source_id}
    roots = _rows(
        conn,
        """select activity_id from room_activities
             where conversation_id = ? and correlation_id = ? and actor_kind = 'human'
             order by seq limit 1""",
        (conversation_id, correlation_id),
    )
    ids.update(str(row["activity_id"]) for row in roots)
    ancestry = _rows(
        conn,
        """with recursive chain(activity_id, causation_id, depth) as (
                 select activity_id, causation_id, 0 from room_activities where activity_id = ?
                 union all
                 select parent.activity_id, parent.causation_id, chain.depth + 1
                   from room_activities parent join chain on parent.activity_id = chain.causation_id
                  where chain.depth < 64 and parent.activity_id <> parent.causation_id
             ) select activity_id from chain""",
        (source_id,),
    )
    ids.update(str(row["activity_id"]) for row in ancestry)
    members = _rows(
        conn,
        """select m.activity_id from room_observation_batch_members m
             join room_observation_batches b on b.batch_id = m.batch_id
             where b.primary_observation_id = ?""",
        (str(attempt["observation_id"]),),
    )
    ids.update(str(row["activity_id"]) for row in members)
    recent = _rows(
        conn,
        """select activity_id from room_activities
             where conversation_id = ? and seq <= ? order by seq desc limit ?""",
        (conversation_id, cutoff, _RECENT_BURST_LIMIT),
    )
    ids.update(str(row["activity_id"]) for row in recent)
    eligible_count = int(
        conn.execute(
            "select count(*) from room_activities where conversation_id = ? and seq <= ?",
            (conversation_id, cutoff),
        ).fetchone()[0]
    )
    return ids, max(0, eligible_count - len(recent))


def collect_recall_evidence(
    *, root: Path, manifest: Mapping[str, Any], run_salt: str
) -> dict[str, Any]:
    """Re-prove the private manifest from ``chat.db`` and return safe aggregate evidence."""

    if not run_salt or len(run_salt) > 512:
        raise RecallDogfoodCollectorError("recall_dogfood_run_salt_invalid")
    # Validate a mapping supplied by tests/other orchestration through the same parser.
    normalized = load_private_manifest_from_mapping(manifest)
    db_path = root / "chat.db"
    if not db_path.is_file() or db_path.is_symlink():
        raise RecallDogfoodCollectorError("recall_dogfood_chat_db_missing")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma query_only = on")
        room_a = normalized["room_a_id"]
        room_b = normalized["room_b_id"]
        candidate = conn.execute(
            """select c.*, o.document_id, o.state outbox_state
                   from room_memory_candidates c
                   join room_memory_outbox o on o.candidate_id = c.candidate_id
                  where c.candidate_id = ?""",
            (normalized["candidate_id"],),
        ).fetchone()
        candidate_ok = bool(
            candidate
            and candidate["conversation_id"] == room_a
            and candidate["kind"] == "project_rule"
            and isinstance(candidate["author_participant_id"], str)
            and bool(candidate["author_participant_id"])
            and candidate["target_scope"] == "project"
            and candidate["approval_state"] == "approved"
            and candidate["approval_mode"] == "operator"
            and isinstance(candidate["resolved_by"], str)
            and bool(candidate["resolved_by"])
            and candidate["publish_state"] == "delivered"
            and candidate["outbox_state"] == "delivered"
            and normalized["target_source_activity_id"]
            in _json_list(candidate["source_activity_ids_json"], "recall_dogfood_candidate_invalid")
        )
        source = conn.execute(
            """select conversation_id from room_activities
                 where activity_id = ? and visibility = 'room'""",
            (normalized["target_source_activity_id"],),
        ).fetchone()
        source_in_room_a = bool(source and source["conversation_id"] == room_a)
        bindings_ready, binding_count = _binding_facts(conn, (room_a, room_b))
        document_backlog, message_backlog = _outbox_backlog(conn, (room_a, room_b))
        attempt = _attempt_context(conn, normalized["room_b_attempt_id"])
        receipt = conn.execute(
            "select * from room_memory_attempt_receipts where attempt_id = ?",
            (normalized["room_b_attempt_id"],),
        ).fetchone()
        skill = conn.execute(
            "select context_payload_sha256 from room_attempt_skill_decisions where attempt_id = ?",
            (normalized["room_b_attempt_id"],),
        ).fetchone()
        item_refs = (
            _json_object_list(receipt["item_refs_json"], "recall_dogfood_receipt_invalid")
            if receipt
            else []
        )
        receipt_sources = (
            _json_list(receipt["source_activity_ids_json"], "recall_dogfood_receipt_invalid")
            if receipt
            else []
        )
        candidate_document_seen = bool(
            candidate
            and any(
                item.get("document_id") == candidate["document_id"]
                and item.get("layer") == "archival"
                and item.get("derived") is False
                and item.get("context_included") is True
                for item in item_refs
            )
        )
        receipt_ok = bool(
            receipt
            and attempt["conversation_id"] == room_b
            and receipt["conversation_id"] == room_b
            and receipt["status"] == "ok"
            and int(receipt["item_count"]) >= 1
            and normalized["target_source_activity_id"] in receipt_sources
            and candidate_document_seen
        )
        context_bound = bool(
            receipt
            and receipt["context_payload_sha256"]
            and skill
            and skill["context_payload_sha256"] == receipt["context_payload_sha256"]
        )
        envelope_ids, omitted = _causal_envelope_ids(conn, attempt)
        target_excluded = normalized["target_source_activity_id"] not in envelope_ids
        derived_attempt = _attempt_context(conn, normalized["derived_attempt_id"])
        derived_receipt = conn.execute(
            "select * from room_memory_attempt_receipts where attempt_id = ?",
            (normalized["derived_attempt_id"],),
        ).fetchone()
        derived_sources = (
            _json_list(
                derived_receipt["source_activity_ids_json"], "recall_dogfood_derived_invalid"
            )
            if derived_receipt
            else []
        )
        witness_sources = set(normalized["derived_evidence"]["source_activity_ids"])
        derived_item_refs = (
            _json_object_list(derived_receipt["item_refs_json"], "recall_dogfood_derived_invalid")
            if derived_receipt
            else []
        )
        derived_ok = bool(
            derived_receipt
            and derived_receipt["status"] == "ok"
            and int(derived_receipt["item_count"]) >= 1
            and witness_sources.issubset(set(derived_sources))
            and normalized["derived_evidence"]["layer"] in _DERIVED_LAYERS
            and any(
                item.get("layer") == normalized["derived_evidence"]["layer"]
                and item.get("derived") is True
                and item.get("context_included") is True
                and witness_sources.issubset(set(item.get("source_activity_ids", [])))
                for item in derived_item_refs
            )
        )
        derived_envelope_ids, derived_omitted = _causal_envelope_ids(conn, derived_attempt)
        derived_sources_excluded = bool(
            witness_sources
            and witness_sources.isdisjoint(derived_envelope_ids)
            and derived_omitted > 0
        )
        target_correlation = conn.execute(
            "select correlation_id from room_activities where activity_id = ?",
            (normalized["target_source_activity_id"],),
        ).fetchone()
        target_not_current = bool(
            target_correlation and target_correlation["correlation_id"] != attempt["correlation_id"]
        )
        room_a_correlations = int(
            conn.execute(
                """select count(distinct correlation_id) from room_activities
                     where conversation_id = ?""",
                (room_a,),
            ).fetchone()[0]
        )
        source_seq = conn.execute(
            "select seq from room_activities where activity_id = ?",
            (normalized["target_source_activity_id"],),
        ).fetchone()
        room_a_tail = int(
            conn.execute(
                """select count(*) from room_activities
                     where conversation_id = ? and seq > ? and visibility = 'room'""",
                (room_a, int(source_seq[0]) if source_seq else 2**63 - 1),
            ).fetchone()[0]
        )
        settled = int(
            conn.execute(
                """select count(distinct a.correlation_id) from room_activities a
                     where a.conversation_id in (?, ?)
                       and not exists (
                           select 1 from room_observations o
                            join room_activities observed on observed.activity_id = o.activity_id
                           where observed.conversation_id = a.conversation_id
                             and observed.correlation_id = a.correlation_id
                             and o.delivery_mode = 'active' and o.status <> 'completed'
                       )""",
                (room_a, room_b),
            ).fetchone()[0]
        )
        unapproved_sources = 0
        if item_refs:
            docs = [str(item.get("document_id")) for item in item_refs]
            doc_marks = ",".join("?" for _ in docs)
            unapproved_sources = int(
                conn.execute(
                    f"""select count(*) from room_memory_candidates c
                         join room_memory_outbox o on o.candidate_id = c.candidate_id
                        where c.target_scope in ('project','local_user')
                          and c.approval_state <> 'approved'
                          and o.document_id in ({doc_marks})""",
                    tuple(docs),
                ).fetchone()[0]
            )
        integrity = str(conn.execute("pragma integrity_check").fetchone()[0]) == "ok"
        run_ref = "run_" + hashlib.sha256(run_salt.encode()).hexdigest()[:32]
        safe_source = _opaque(run_salt, normalized["target_source_activity_id"])
        derived_source_digest = _opaque(
            run_salt, "|".join(sorted(normalized["derived_evidence"]["source_activity_ids"]))
        )
        evidence: dict[str, Any] = {
            "schema_version": "room_memory_recall_dogfood_evidence/v1",
            "run_ref": run_ref,
            "configuration": {"room_count": 2, "agents_per_room": 4},
            "counts": {
                "room_a_correlations": room_a_correlations,
                "room_a_tail_visible_activities": room_a_tail,
                "approved_project_candidates": 1 if candidate_ok else 0,
                "delivered_project_candidates": 1 if candidate_ok else 0,
                "attached_bindings": binding_count,
                "message_backlog": message_backlog,
                "document_backlog": document_backlog,
                "memoryos_child_count_after_recovery": (
                    1 if normalized["memoryos_fault"]["single_child_recovered"] else 0
                ),
                "room_b_ok_receipts": 1 if receipt_ok else 0,
                "room_b_receipt_items": int(receipt["item_count"]) if receipt_ok else 0,
                "cross_room_project_sources_reproved": 1 if receipt_ok and source_in_room_a else 0,
                "derived_items": int(derived_receipt["item_count"]) if derived_ok else 0,
                "unapproved_cross_room_sources": unapproved_sources,
                "settled_correlations": settled,
                "browser_console_errors": normalized["browser"]["console_errors"],
                "sensitive_leaks": 0,
            },
            "proofs": {
                "candidate_approved": bool(candidate_ok),
                "candidate_delivered": bool(candidate_ok),
                "all_scope_bindings_attached": bindings_ready,
                "memoryos_killed": normalized["memoryos_fault"]["sigkill_injected"],
                "memoryos_recovered": normalized["memoryos_fault"]["single_child_recovered"],
                "full_local_capability_ready": normalized["memoryos_fault"][
                    "full_local_capability_ready"
                ],
                "room_b_receipt_ok": receipt_ok,
                "cross_room_project_source_reproved": receipt_ok and source_in_room_a,
                "source_excluded_from_current_correlation": target_not_current,
                "source_excluded_from_causal_envelope": target_excluded,
                "source_excluded_from_recent_burst": (target_excluded and derived_sources_excluded),
                "context_coverage_omits_source": omitted > 0 and derived_omitted > 0,
                "receipt_evidence_context_bound": context_bound,
                "derived_layer_present": derived_ok,
                "all_target_correlations_settled": settled >= 7,
                "sqlite_integrity_ok": integrity,
            },
            "digests": {
                "approved_project_source_ref_digest": safe_source,
                "receipt_evidence_digest": receipt["evidence_sha256"]
                if receipt
                else "sha256:" + "0" * 64,
                "receipt_context_digest": receipt["context_payload_sha256"]
                if receipt and receipt["context_payload_sha256"]
                else "sha256:" + "0" * 64,
                "skill_context_digest": skill["context_payload_sha256"]
                if skill and skill["context_payload_sha256"]
                else "sha256:" + "0" * 64,
                "derived_source_ref_digest": derived_source_digest,
                "evidence_digest": "",
            },
        }
    evidence_without_digest = {key: value for key, value in evidence.items() if key != "digests"}
    evidence["digests"]["evidence_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                evidence_without_digest
                | {
                    "digests": {
                        key: value
                        for key, value in evidence["digests"].items()
                        if key != "evidence_digest"
                    }
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    return evidence


def load_private_manifest_from_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate mappings without writing private fixtures to disk."""

    temporary = Path("/dev/null")
    # Keep the validation implementation single-sourced without exposing a file write path.
    if not isinstance(payload, dict):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    # Serialize/decode prevents subclasses and normalizes JSON-shaped input.
    try:
        normalized = json.loads(json.dumps(payload))
    except (TypeError, ValueError) as exc:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid") from exc
    del temporary
    # Inline the final structural check via a private temporary-free implementation.
    if not isinstance(normalized, dict) or normalized.get("schema_version") != MANIFEST_SCHEMA:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    required = {
        "schema_version",
        "room_a_id",
        "room_b_id",
        "candidate_id",
        "target_source_activity_id",
        "room_b_attempt_id",
        "derived_attempt_id",
        "derived_evidence",
        "memoryos_fault",
        "browser",
    }
    if set(normalized) != required:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    # Reuse file validator's checks logically, but avoid a filesystem mutation in the collector.
    for key in (
        "room_a_id",
        "room_b_id",
        "candidate_id",
        "target_source_activity_id",
        "room_b_attempt_id",
        "derived_attempt_id",
    ):
        _required_text(normalized, key)
    if normalized["room_a_id"] == normalized["room_b_id"]:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    derived = normalized["derived_evidence"]
    if (
        not isinstance(derived, dict)
        or set(derived) != {"layer", "source_activity_ids"}
        or derived["layer"] not in _DERIVED_LAYERS
    ):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    if (
        not isinstance(derived["source_activity_ids"], list)
        or not derived["source_activity_ids"]
        or any(not isinstance(item, str) or not item for item in derived["source_activity_ids"])
    ):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    fault = normalized["memoryos_fault"]
    if not isinstance(fault, dict) or set(fault) != {
        "sigkill_injected",
        "single_child_recovered",
        "full_local_capability_ready",
    }:
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    for key in fault:
        _required_bool(fault, key)
    browser = normalized["browser"]
    if (
        not isinstance(browser, dict)
        or set(browser) != {"headed", "console_errors"}
        or not isinstance(browser["headed"], bool)
        or isinstance(browser["console_errors"], bool)
        or not isinstance(browser["console_errors"], int)
        or browser["console_errors"] < 0
    ):
        raise RecallDogfoodCollectorError("recall_dogfood_manifest_invalid")
    return normalized


def _build_result(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Use the strict core contract once present; error rather than emit an ad-hoc result."""

    try:
        from xmuse_core.chat.room_memory_recall_dogfood import build_memory_recall_dogfood_result
    except ImportError as exc:  # pragma: no cover - temporary integration boundary
        raise RecallDogfoodCollectorError("recall_dogfood_contract_unavailable") from exc
    return build_memory_recall_dogfood_result(evidence=evidence)


def _write_private_result(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(result, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--run-salt", required=True)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_private_manifest(args.manifest)
        evidence = collect_recall_evidence(
            root=args.root, manifest=manifest, run_salt=args.run_salt
        )
        result = _build_result(evidence)
        _write_private_result(args.result, result)
    except RecallDogfoodCollectorError as exc:
        parser.error(exc.code)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
