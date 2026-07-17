"""Safe aggregate receipt for the source-backed MemoryOS recall dogfood.

The browser exercise and its database inspection are intentionally private.  This
contract permits only bounded aggregate evidence, opaque references, and digests;
it is not a second Room or MemoryOS authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

EVIDENCE_SCHEMA = "room_memory_recall_dogfood_evidence/v1"
RESULT_SCHEMA = "room_memory_recall_dogfood_result/v1"
PROOF_BOUNDARY = "aggregate_recall_dogfood_evidence_not_room_or_memoryos_authority"
MAX_RESULT_BYTES = 16 * 1024

_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OPAQUE_REF = re.compile(r"(?:ref|run)_[0-9a-f]{32}\Z")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_TOP_LEVEL = frozenset(
    {"schema_version", "run_ref", "configuration", "counts", "proofs", "digests"}
)
_CONFIGURATION = frozenset({"room_count", "agents_per_room"})
_COUNTS = frozenset(
    {
        "room_a_correlations",
        "room_a_tail_visible_activities",
        "approved_project_candidates",
        "delivered_project_candidates",
        "attached_bindings",
        "message_backlog",
        "document_backlog",
        "memoryos_child_count_after_recovery",
        "room_b_ok_receipts",
        "room_b_receipt_items",
        "cross_room_project_sources_reproved",
        "derived_items",
        "unapproved_cross_room_sources",
        "settled_correlations",
        "browser_console_errors",
        "sensitive_leaks",
    }
)
_PROOFS = frozenset(
    {
        "candidate_approved",
        "candidate_delivered",
        "all_scope_bindings_attached",
        "memoryos_killed",
        "memoryos_recovered",
        "full_local_capability_ready",
        "room_b_receipt_ok",
        "cross_room_project_source_reproved",
        "source_excluded_from_current_correlation",
        "source_excluded_from_causal_envelope",
        "source_excluded_from_recent_burst",
        "context_coverage_omits_source",
        "receipt_evidence_context_bound",
        "derived_layer_present",
        "all_target_correlations_settled",
        "sqlite_integrity_ok",
    }
)
_DIGESTS = frozenset(
    {
        "approved_project_source_ref_digest",
        "receipt_evidence_digest",
        "receipt_context_digest",
        "skill_context_digest",
        "derived_source_ref_digest",
        "evidence_digest",
    }
)


class RecallDogfoodContractError(ValueError):
    """A private lab receipt was malformed or does not faithfully encode its gates."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise RecallDogfoodContractError("contract_json_invalid") from exc


def _sha(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: object, keys: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RecallDogfoodContractError(code)
    return value


def _count(value: object, code: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_SAFE_INTEGER
    ):
        raise RecallDogfoodContractError(code)
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise RecallDogfoodContractError(code)
    return value


def _opaque(value: object, code: str) -> str:
    if not isinstance(value, str) or _OPAQUE_REF.fullmatch(value) is None:
        raise RecallDogfoodContractError(code)
    return value


def _bool(value: object, code: str) -> bool:
    if not isinstance(value, bool):
        raise RecallDogfoodContractError(code)
    return value


def _normalize_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _exact(payload, _TOP_LEVEL, "evidence_invalid")
    if raw.get("schema_version") != EVIDENCE_SCHEMA:
        raise RecallDogfoodContractError("evidence_invalid")
    configuration = _exact(raw.get("configuration"), _CONFIGURATION, "evidence_invalid")
    if configuration.get("room_count") != 2 or configuration.get("agents_per_room") != 4:
        raise RecallDogfoodContractError("evidence_invalid")
    counts = _exact(raw.get("counts"), _COUNTS, "evidence_invalid")
    proofs = _exact(raw.get("proofs"), _PROOFS, "evidence_invalid")
    digests = _exact(raw.get("digests"), _DIGESTS, "evidence_invalid")
    normalized: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "run_ref": _opaque(raw.get("run_ref"), "evidence_invalid"),
        "configuration": {
            key: _count(configuration[key], "evidence_invalid") for key in _CONFIGURATION
        },
        "counts": {key: _count(counts[key], "evidence_invalid") for key in _COUNTS},
        "proofs": {key: _bool(proofs[key], "evidence_invalid") for key in _PROOFS},
        "digests": {key: _digest(digests[key], "evidence_invalid") for key in _DIGESTS},
    }
    normalized_digests = normalized["digests"]
    if normalized_digests["evidence_digest"] != _sha(
        {key: value for key, value in normalized.items() if key != "digests"}
        | {
            "digests": {
                key: value for key, value in normalized_digests.items() if key != "evidence_digest"
            }
        }
    ):
        raise RecallDogfoodContractError("evidence_digest_invalid")
    return normalized


def _gate(
    gate_id: str, passed: bool, observed: int | bool | str, expected: int | bool | str
) -> dict[str, int | bool | str]:
    if _REASON.fullmatch(gate_id) is None:
        raise AssertionError("invalid internal gate id")
    return {
        "gate_id": gate_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
    }


def _gates(evidence: Mapping[str, Any]) -> list[dict[str, int | bool | str]]:
    counts = evidence["counts"]
    proofs = evidence["proofs"]
    digests = evidence["digests"]
    derived_present = proofs["derived_layer_present"] and counts["derived_items"] >= 1
    return [
        _gate(
            "room_topology",
            evidence["configuration"] == {"room_count": 2, "agents_per_room": 4},
            2,
            2,
        ),
        _gate(
            "room_a_correlations",
            counts["room_a_correlations"] >= 6,
            counts["room_a_correlations"],
            6,
        ),
        _gate(
            "tail_visible_activities",
            counts["room_a_tail_visible_activities"] >= 9,
            counts["room_a_tail_visible_activities"],
            9,
        ),
        _gate(
            "project_candidate_approved_delivered",
            proofs["candidate_approved"]
            and proofs["candidate_delivered"]
            and counts["approved_project_candidates"] >= 1
            and counts["delivered_project_candidates"] >= 1,
            counts["delivered_project_candidates"],
            1,
        ),
        _gate(
            "scope_bindings_attached",
            proofs["all_scope_bindings_attached"] and counts["attached_bindings"] >= 6,
            counts["attached_bindings"],
            6,
        ),
        _gate(
            "outbox_drained",
            counts["message_backlog"] == 0 and counts["document_backlog"] == 0,
            counts["message_backlog"] + counts["document_backlog"],
            0,
        ),
        _gate(
            "memoryos_recovered_single_child",
            proofs["memoryos_killed"]
            and proofs["memoryos_recovered"]
            and proofs["full_local_capability_ready"]
            and counts["memoryos_child_count_after_recovery"] == 1,
            counts["memoryos_child_count_after_recovery"],
            1,
        ),
        _gate(
            "room_b_nonempty_receipt",
            proofs["room_b_receipt_ok"]
            and counts["room_b_ok_receipts"] >= 1
            and counts["room_b_receipt_items"] >= 1,
            counts["room_b_receipt_items"],
            1,
        ),
        _gate(
            "cross_room_project_source",
            proofs["cross_room_project_source_reproved"]
            and counts["cross_room_project_sources_reproved"] >= 1,
            counts["cross_room_project_sources_reproved"],
            1,
        ),
        _gate(
            "long_memory_exclusion",
            proofs["source_excluded_from_current_correlation"]
            and proofs["source_excluded_from_causal_envelope"]
            and proofs["source_excluded_from_recent_burst"]
            and proofs["context_coverage_omits_source"],
            True
            if all(
                proofs[key]
                for key in (
                    "source_excluded_from_current_correlation",
                    "source_excluded_from_causal_envelope",
                    "source_excluded_from_recent_burst",
                    "context_coverage_omits_source",
                )
            )
            else False,
            True,
        ),
        _gate(
            "context_digest_binding",
            proofs["receipt_evidence_context_bound"]
            and digests["receipt_context_digest"] == digests["skill_context_digest"],
            digests["receipt_context_digest"] == digests["skill_context_digest"],
            True,
        ),
        _gate("derived_evidence", derived_present, counts["derived_items"], 1),
        _gate(
            "unapproved_cross_room_blocked",
            counts["unapproved_cross_room_sources"] == 0,
            counts["unapproved_cross_room_sources"],
            0,
        ),
        _gate(
            "settled",
            proofs["all_target_correlations_settled"] and counts["settled_correlations"] >= 7,
            counts["settled_correlations"],
            7,
        ),
        _gate(
            "browser_clean",
            counts["browser_console_errors"] == 0,
            counts["browser_console_errors"],
            0,
        ),
        _gate(
            "sqlite_integrity", proofs["sqlite_integrity_ok"], proofs["sqlite_integrity_ok"], True
        ),
        _gate("sensitive_leak_free", counts["sensitive_leaks"] == 0, counts["sensitive_leaks"], 0),
    ]


def build_memory_recall_dogfood_result(*, evidence: Mapping[str, Any]) -> dict[str, Any]:
    normalized_evidence = _normalize_evidence(evidence)
    gates = _gates(normalized_evidence)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "run_ref": normalized_evidence["run_ref"],
        "status": "passed" if all(gate["status"] == "passed" for gate in gates) else "failed",
        "configuration": normalized_evidence["configuration"],
        "counts": normalized_evidence["counts"],
        "proofs": normalized_evidence["proofs"],
        "digests": normalized_evidence["digests"],
        "gates": gates,
        "proof_boundary": PROOF_BOUNDARY,
        "result_digest": "",
    }
    result["result_digest"] = _sha(
        {key: value for key, value in result.items() if key != "result_digest"}
    )
    return validate_memory_recall_dogfood_result(result)


def validate_memory_recall_dogfood_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = _TOP_LEVEL - {"schema_version"} | frozenset(
        {"schema_version", "status", "gates", "proof_boundary", "result_digest"}
    )
    raw = _exact(payload, expected, "result_invalid")
    evidence = _normalize_evidence(
        {
            "schema_version": EVIDENCE_SCHEMA,
            "run_ref": raw.get("run_ref"),
            "configuration": raw.get("configuration"),
            "counts": raw.get("counts"),
            "proofs": raw.get("proofs"),
            "digests": raw.get("digests"),
        }
    )
    if raw.get("schema_version") != RESULT_SCHEMA or raw.get("proof_boundary") != PROOF_BOUNDARY:
        raise RecallDogfoodContractError("result_invalid")
    gates = _gates(evidence)
    status = "passed" if all(gate["status"] == "passed" for gate in gates) else "failed"
    if raw.get("gates") != gates or raw.get("status") != status:
        raise RecallDogfoodContractError("result_gates_invalid")
    normalized: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "run_ref": evidence["run_ref"],
        "status": status,
        "configuration": evidence["configuration"],
        "counts": evidence["counts"],
        "proofs": evidence["proofs"],
        "digests": evidence["digests"],
        "gates": gates,
        "proof_boundary": PROOF_BOUNDARY,
        "result_digest": _digest(raw.get("result_digest"), "result_invalid"),
    }
    if normalized["result_digest"] != _sha(
        {key: value for key, value in normalized.items() if key != "result_digest"}
    ):
        raise RecallDogfoodContractError("result_digest_invalid")
    if len(_canonical(normalized)) > MAX_RESULT_BYTES:
        raise RecallDogfoodContractError("result_too_large")
    return json.loads(_canonical(normalized))


def evaluate_memory_recall_dogfood_result(
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    normalized = validate_memory_recall_dogfood_result(payload)
    failed = tuple(
        str(gate["gate_id"]) for gate in normalized["gates"] if gate["status"] == "failed"
    )
    return not failed, failed
