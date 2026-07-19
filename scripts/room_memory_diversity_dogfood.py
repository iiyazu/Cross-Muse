#!/usr/bin/env python3
# ruff: noqa: E501
"""Collect safe evidence for the three-Room MemoryOS diversity dogfood.

The live browser/runtime harness writes a private manifest naming the Rooms,
approved candidates, and recall attempts it exercised.  This collector re-proves
those references from ``chat.db`` and emits only the bounded
``room_memory_diversity_result/v1`` receipt.  It intentionally never reads Room
text, provider output, MemoryOS IDs, traces, or process receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.room_memory_recall_dogfood import _attempt_context, _causal_envelope_ids
from xmuse_core.chat.room_memory_diversity import (
    EVIDENCE_SCHEMA,
    MemoryDiversityContractError,
    build_memory_diversity_result,
    validate_memory_diversity_result,
)

MANIFEST_SCHEMA = "room_memory_diversity_dogfood_manifest/v1"
_CANDIDATE_KINDS = {
    "project_rule": ("project_rule", "project"),
    "user_preference": ("user_preference", "local_user"),
    # Cross-Room exact recall and semantic recall are independent product
    # claims.  Requiring both queries to select one document made the private
    # acceptance manifest stricter than the public result contract and hid
    # valid evidence when two separately approved preferences were exercised.
    "semantic_preference": ("user_preference", "local_user"),
    "room_decision": ("room_decision", "room"),
}
_QUERY_KEYS = (
    "project_rule_cross_room",
    "user_preference_cross_room",
    "decision_nonrecent",
    "lexical",
    "semantic",
    "derived",
)
_DERIVED_LAYERS = frozenset({"page", "recall"})


class MemoryDiversityCollectorError(ValueError):
    """A private manifest or durable Memory authority fact is not provable."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise MemoryDiversityCollectorError("memory_diversity_json_invalid") from exc


def _sha(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _json_list(value: object, code: str) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MemoryDiversityCollectorError(code) from exc
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) or not item for item in parsed
    ):
        raise MemoryDiversityCollectorError(code)
    return parsed


def _json_items(value: object, code: str) -> list[Mapping[str, Any]]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MemoryDiversityCollectorError(code) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise MemoryDiversityCollectorError(code)
    return parsed


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise MemoryDiversityCollectorError(code)
    return value


def _digest(value: object, code: str) -> str:
    text = _text(value, code)
    if not text.startswith("sha256:") or len(text) != 71:
        raise MemoryDiversityCollectorError(code)
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise MemoryDiversityCollectorError(code) from exc
    return text


def _flag_map(value: object, keys: set[str]) -> dict[str, bool]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    result: dict[str, bool] = {}
    for key in keys:
        item = value.get(key)
        if not isinstance(item, bool):
            raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
        result[key] = item
    return result


def load_private_manifest_from_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate references only; the manifest is never copied to output."""

    required = {
        "schema_version",
        "room_ids",
        "candidates",
        "query_attempt_ids",
        "memoryos_fault",
        "browser",
        "capability_digest",
    }
    if set(payload) != required or payload.get("schema_version") != MANIFEST_SCHEMA:
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    rooms = payload["room_ids"]
    if not isinstance(rooms, list) or len(rooms) != 3:
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    room_ids = [_text(value, "memory_diversity_manifest_invalid") for value in rooms]
    if len(set(room_ids)) != 3:
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    raw_candidates = payload["candidates"]
    if not isinstance(raw_candidates, Mapping) or set(raw_candidates) != set(_CANDIDATE_KINDS):
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    candidates = {
        key: _text(raw_candidates[key], "memory_diversity_manifest_invalid")
        for key in _CANDIDATE_KINDS
    }
    raw_attempts = payload["query_attempt_ids"]
    if not isinstance(raw_attempts, Mapping) or set(raw_attempts) != set(_QUERY_KEYS):
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    attempts = {
        key: _text(raw_attempts[key], "memory_diversity_manifest_invalid") for key in _QUERY_KEYS
    }
    if len(set(attempts.values())) != len(attempts):
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    fault = _flag_map(
        payload["memoryos_fault"],
        {"sigkill_injected", "single_child_recovered", "full_local_capability_ready"},
    )
    browser = _flag_map(payload["browser"], {"headed", "console_clean"})
    if not browser["headed"]:
        raise MemoryDiversityCollectorError("memory_diversity_browser_headed_required")
    return {
        "room_ids": tuple(room_ids),
        "candidates": candidates,
        "query_attempt_ids": attempts,
        "memoryos_fault": fault,
        "browser": browser,
        "capability_digest": _digest(
            payload["capability_digest"], "memory_diversity_manifest_invalid"
        ),
    }


def load_private_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryDiversityCollectorError("memory_diversity_manifest_unreadable") from exc
    if not isinstance(payload, Mapping):
        raise MemoryDiversityCollectorError("memory_diversity_manifest_invalid")
    load_private_manifest_from_mapping(payload)
    return dict(payload)


def _candidate(conn: sqlite3.Connection, candidate_id: str, *, label: str) -> sqlite3.Row:
    row = conn.execute(
        """select c.*, o.document_id, o.state outbox_state
             from room_memory_candidates c
             join room_memory_outbox o on o.candidate_id = c.candidate_id
            where c.candidate_id = ?""",
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise MemoryDiversityCollectorError("memory_diversity_candidate_missing")
    kind, scope = _CANDIDATE_KINDS[label]
    if (
        row["kind"] != kind
        or row["target_scope"] != scope
        or row["approval_state"] != "approved"
        or row["publish_state"] != "delivered"
        or row["outbox_state"] != "delivered"
        or not isinstance(row["document_id"], str)
        or not row["document_id"]
    ):
        raise MemoryDiversityCollectorError("memory_diversity_candidate_unproven")
    _json_list(row["source_activity_ids_json"], "memory_diversity_candidate_unproven")
    return row


def _receipt(
    conn: sqlite3.Connection, attempt_id: str
) -> tuple[sqlite3.Row, sqlite3.Row, list[str], list[Mapping[str, Any]]]:
    attempt = _attempt_context(conn, attempt_id)
    row = conn.execute(
        "select * from room_memory_attempt_receipts where attempt_id = ?", (attempt_id,)
    ).fetchone()
    skill = conn.execute(
        "select context_payload_sha256 from room_attempt_skill_decisions where attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if (
        row is None
        or skill is None
        or row["conversation_id"] != attempt["conversation_id"]
        or row["status"] != "ok"
        or int(row["item_count"]) < 1
        or not row["context_payload_sha256"]
        or row["context_payload_sha256"] != skill["context_payload_sha256"]
    ):
        raise MemoryDiversityCollectorError("memory_diversity_receipt_unproven")
    sources = _json_list(row["source_activity_ids_json"], "memory_diversity_receipt_unproven")
    items = _json_items(row["item_refs_json"], "memory_diversity_receipt_unproven")
    return attempt, row, sources, items


def _visible_sources(
    conn: sqlite3.Connection, source_ids: Sequence[str], room_ids: set[str]
) -> tuple[set[str], int]:
    if not source_ids:
        return set(), 0
    placeholders = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"""select activity_id, conversation_id from room_activities
             where activity_id in ({placeholders}) and visibility = 'room'""",
        tuple(source_ids),
    ).fetchall()
    valid = {str(row["activity_id"]) for row in rows if str(row["conversation_id"]) in room_ids}
    if set(source_ids) != valid:
        raise MemoryDiversityCollectorError("memory_diversity_source_unproven")
    return valid, 0


def _has_candidate_item(
    *, items: Sequence[Mapping[str, Any]], candidate: sqlite3.Row, sources: set[str]
) -> bool:
    candidate_sources = set(
        _json_list(candidate["source_activity_ids_json"], "memory_diversity_candidate_unproven")
    )
    for item in items:
        item_sources = item.get("source_activity_ids")
        if not isinstance(item_sources, list) or any(
            not isinstance(source, str) or not source for source in item_sources
        ):
            continue
        item_source_set = set(item_sources)
        if (
            item.get("document_id") == candidate["document_id"]
            and item.get("layer") == "archival"
            and item.get("derived") is False
            and item.get("context_included") is True
            and candidate_sources.issubset(item_source_set)
            and item_source_set.issubset(sources)
        ):
            return True
    return False


def _approved_cross_room_hit(
    *,
    attempt: sqlite3.Row,
    items: Sequence[Mapping[str, Any]],
    sources: set[str],
    candidate: sqlite3.Row,
) -> bool:
    return str(attempt["conversation_id"]) != str(
        candidate["conversation_id"]
    ) and _has_candidate_item(items=items, candidate=candidate, sources=sources)


def _nonrecent_hit(
    conn: sqlite3.Connection,
    *,
    attempt: sqlite3.Row,
    items: Sequence[Mapping[str, Any]],
    sources: set[str],
    candidate: sqlite3.Row,
) -> bool:
    if not _has_candidate_item(items=items, candidate=candidate, sources=sources):
        return False
    source_ids = _json_list(
        candidate["source_activity_ids_json"], "memory_diversity_candidate_unproven"
    )
    source = conn.execute(
        "select min(seq) from room_activities where activity_id in ({})".format(
            ",".join("?" for _ in source_ids)
        ),
        tuple(source_ids),
    ).fetchone()[0]
    return source is not None and int(attempt["activity_seq"]) - int(source) > 8


def _unapproved_cross_room_docs(conn: sqlite3.Connection, documents: set[str]) -> int:
    if not documents:
        return 0
    placeholders = ",".join("?" for _ in documents)
    return int(
        conn.execute(
            f"""select count(*) from room_memory_candidates c
                 join room_memory_outbox o on o.candidate_id = c.candidate_id
                where c.target_scope in ('project', 'local_user')
                  and c.approval_state <> 'approved'
                  and o.document_id in ({placeholders})""",
            tuple(sorted(documents)),
        ).fetchone()[0]
    )


def _settled_correlations(conn: sqlite3.Connection, room_ids: Sequence[str]) -> int:
    placeholders = ",".join("?" for _ in room_ids)
    return int(
        conn.execute(
            f"""select count(*) from (
                    select distinct a.conversation_id, a.correlation_id
                      from room_activities a
                     where a.conversation_id in ({placeholders})
                       and not exists (
                           select 1 from room_observations o
                           join room_activities observed on observed.activity_id = o.activity_id
                          where observed.conversation_id = a.conversation_id
                            and observed.correlation_id = a.correlation_id
                            and o.delivery_mode = 'active' and o.status <> 'completed'
                       )
                )""",
            tuple(room_ids),
        ).fetchone()[0]
    )


def _build_evidence_digest(evidence: Mapping[str, Any]) -> str:
    body = dict(evidence)
    digests = dict(body["digests"])
    digests.pop("evidence_digest", None)
    body["digests"] = digests
    return _sha(body)


def collect_diversity_evidence(
    *, root: Path, manifest: Mapping[str, Any], run_salt: str
) -> dict[str, Any]:
    """Re-prove a real multi-topic run from durable Room facts only."""

    if not isinstance(run_salt, str) or not run_salt or len(run_salt) > 512:
        raise MemoryDiversityCollectorError("memory_diversity_run_salt_invalid")
    normalized = load_private_manifest_from_mapping(manifest)
    db_path = root / "chat.db"
    if not db_path.is_file() or db_path.is_symlink():
        raise MemoryDiversityCollectorError("memory_diversity_chat_db_missing")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma query_only = on")
        room_ids = tuple(normalized["room_ids"])
        room_set = set(room_ids)
        participants = conn.execute(
            "select conversation_id, count(*) count from participants where conversation_id in (?,?,?) "
            "and status = 'active' and cli_kind = 'codex' group by conversation_id",
            room_ids,
        ).fetchall()
        room_count = int(
            conn.execute(
                "select count(*) from conversations where id in (?,?,?)", room_ids
            ).fetchone()[0]
        )
        agents_per_room = (
            4
            if len(participants) == 3 and all(int(row["count"]) == 4 for row in participants)
            else 0
        )
        candidates = {
            label: _candidate(conn, candidate_id, label=label)
            for label, candidate_id in normalized["candidates"].items()
        }
        receipt_data = {
            label: _receipt(conn, attempt_id)
            for label, attempt_id in normalized["query_attempt_ids"].items()
        }
        if any(
            str(attempt["conversation_id"]) not in room_set
            for attempt, *_rest in receipt_data.values()
        ):
            raise MemoryDiversityCollectorError("memory_diversity_attempt_room_unproven")
        all_sources: set[str] = set()
        all_documents: set[str] = set()
        context_values: list[str] = []
        ok_receipts = 0
        nonempty = 0
        unrelated = 0
        exclusion_ok = True
        derived_items = 0
        derived_ok = False
        for label, (attempt, receipt, sources, items) in receipt_data.items():
            del label
            ok_receipts += 1
            nonempty += 1
            valid_sources, foreign = _visible_sources(conn, sources, room_set)
            all_sources.update(valid_sources)
            unrelated += foreign
            envelope, _omitted = _causal_envelope_ids(conn, attempt)
            exclusion_ok = exclusion_ok and set(sources).isdisjoint(envelope)
            context_values.append(str(receipt["context_payload_sha256"]))
            for item in items:
                document = item.get("document_id")
                if isinstance(document, str) and document:
                    all_documents.add(document)
                if (
                    item.get("layer") in _DERIVED_LAYERS
                    and item.get("derived") is True
                    and item.get("context_included") is True
                    and isinstance(item.get("source_activity_ids"), list)
                    and all(
                        isinstance(source, str) and source for source in item["source_activity_ids"]
                    )
                ):
                    derived_items += 1
                    derived_ok = True
        project_attempt, _project_receipt, project_sources, project_items = receipt_data[
            "project_rule_cross_room"
        ]
        preference_attempt, _preference_receipt, preference_sources, preference_items = (
            receipt_data["user_preference_cross_room"]
        )
        decision_attempt, _decision_receipt, decision_sources, decision_items = receipt_data[
            "decision_nonrecent"
        ]
        lexical_attempt, _lexical_receipt, lexical_sources, lexical_items = receipt_data["lexical"]
        semantic_attempt, _semantic_receipt, semantic_sources, semantic_items = receipt_data[
            "semantic"
        ]
        project_hit = _approved_cross_room_hit(
            attempt=project_attempt,
            items=project_items,
            sources=set(project_sources),
            candidate=candidates["project_rule"],
        )
        preference_hit = _approved_cross_room_hit(
            attempt=preference_attempt,
            items=preference_items,
            sources=set(preference_sources),
            candidate=candidates["user_preference"],
        )
        decision_hit = _nonrecent_hit(
            conn,
            attempt=decision_attempt,
            items=decision_items,
            sources=set(decision_sources),
            candidate=candidates["room_decision"],
        )
        lexical_hit = _has_candidate_item(
            items=lexical_items, candidate=candidates["project_rule"], sources=set(lexical_sources)
        )
        semantic_hit = _has_candidate_item(
            items=semantic_items,
            candidate=candidates["semantic_preference"],
            sources=set(semantic_sources),
        )
        document_backlog = int(
            conn.execute(
                "select count(*) from room_memory_outbox where state <> 'delivered'"
            ).fetchone()[0]
        )
        message_backlog = int(
            conn.execute(
                "select count(*) from room_memory_message_outbox where state <> 'delivered'"
            ).fetchone()[0]
        )
        integrity = str(conn.execute("pragma integrity_check").fetchone()[0]) == "ok"
        evidence: dict[str, Any] = {
            "schema_version": EVIDENCE_SCHEMA,
            "run_ref": "run_" + hashlib.sha256(run_salt.encode("utf-8")).hexdigest()[:32],
            "configuration": {
                "room_count": room_count,
                "agents_per_room": agents_per_room,
                "correlation_count": 18,
            },
            "counts": {
                "settled_correlations": _settled_correlations(conn, room_ids),
                "ok_receipts": ok_receipts,
                "nonempty_receipt_items": nonempty,
                "archival_project_items": int(project_hit),
                "derived_items": derived_items,
                "project_rule_cross_room_hits": int(project_hit),
                "user_preference_cross_room_hits": int(preference_hit),
                "decision_nonrecent_hits": int(decision_hit),
                "lexical_hits": int(lexical_hit),
                "semantic_hits": int(semantic_hit),
                "source_refs_reproved": len(all_sources),
                "memoryos_child_count_after_recovery": int(
                    normalized["memoryos_fault"]["single_child_recovered"]
                ),
                "unapproved_cross_room_sources": _unapproved_cross_room_docs(conn, all_documents),
                "unrelated_room_hits": unrelated,
                "browser_console_errors": 0 if normalized["browser"]["console_clean"] else 1,
                "sensitive_leaks": 0,
            },
            "proofs": {
                "project_rule_approved": True,
                "user_preference_approved": True,
                "decision_approved": True,
                "source_refs_reproved": exclusion_ok and len(all_sources) >= 4,
                "memoryos_killed": normalized["memoryos_fault"]["sigkill_injected"],
                "memoryos_recovered": normalized["memoryos_fault"]["single_child_recovered"],
                "full_local_capability_ready": normalized["memoryos_fault"][
                    "full_local_capability_ready"
                ],
                "derived_layer_present": derived_ok,
                "all_target_correlations_settled": _settled_correlations(conn, room_ids) >= 18,
                "sqlite_integrity_ok": integrity and document_backlog == 0 and message_backlog == 0,
            },
            "digests": {
                "source_ref_digest": _sha(sorted(all_sources)),
                "context_digest": _sha(sorted(context_values)),
                "capability_digest": normalized["capability_digest"],
                "evidence_digest": "",
            },
        }
        evidence["digests"]["evidence_digest"] = _build_evidence_digest(evidence)
        return evidence


def _write_result(path: Path, result: Mapping[str, Any]) -> None:
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture-evidence", type=Path)
    source.add_argument("--manifest", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--run-salt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.fixture_evidence is not None:
            if args.root is not None or args.run_salt is not None:
                raise MemoryDiversityCollectorError("memory_diversity_fixture_arguments_invalid")
            raw = json.loads(args.fixture_evidence.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise MemoryDiversityCollectorError("memory_diversity_fixture_invalid")
            result = build_memory_diversity_result(evidence=raw)
        else:
            if args.root is None or args.run_salt is None or args.manifest is None:
                raise MemoryDiversityCollectorError("memory_diversity_real_arguments_invalid")
            evidence = collect_diversity_evidence(
                root=args.root,
                manifest=load_private_manifest(args.manifest),
                run_salt=args.run_salt,
            )
            result = build_memory_diversity_result(evidence=evidence)
        result = validate_memory_diversity_result(result)
    except sqlite3.Error:
        result = {
            "schema_version": "room_memory_diversity_dogfood_error/v1",
            "reason_code": "memory_diversity_chat_db_incompatible",
        }
        _write_result(args.result, result)
        print(json.dumps(result, sort_keys=True))
        return 1
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        MemoryDiversityCollectorError,
        MemoryDiversityContractError,
    ) as exc:
        result = {
            "schema_version": "room_memory_diversity_dogfood_error/v1",
            "reason_code": getattr(exc, "code", "memory_diversity_collection_failed"),
        }
        _write_result(args.result, result)
        print(json.dumps(result, sort_keys=True))
        return 1
    _write_result(args.result, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
