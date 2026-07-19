"""Safe aggregate contract for the multi-topic MemoryOS diversity dogfood.

The real run is performed by a private browser/database harness.  This module only
validates bounded counts, opaque references and digests; it is not a Room or MemoryOS
authority and deliberately cannot carry message text, paths, provider output or IDs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

EVIDENCE_SCHEMA = "room_memory_diversity_evidence/v1"
RESULT_SCHEMA = "room_memory_diversity_result/v1"
PROOF_BOUNDARY = "aggregate_memory_diversity_evidence_not_room_or_memoryos_authority"
MAX_RESULT_BYTES = 16 * 1024
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OPAQUE_REF = re.compile(r"(?:ref|run)_[0-9a-f]{32}\Z")

_TOP_LEVEL = frozenset(
    {"schema_version", "run_ref", "configuration", "counts", "proofs", "digests"}
)
_CONFIGURATION = frozenset({"room_count", "agents_per_room", "correlation_count"})
_COUNTS = frozenset(
    {
        "settled_correlations",
        "ok_receipts",
        "nonempty_receipt_items",
        "archival_project_items",
        "derived_items",
        "project_rule_cross_room_hits",
        "user_preference_cross_room_hits",
        "decision_nonrecent_hits",
        "lexical_hits",
        "semantic_hits",
        "source_refs_reproved",
        "memoryos_child_count_after_recovery",
        "unapproved_cross_room_sources",
        "unrelated_room_hits",
        "browser_console_errors",
        "sensitive_leaks",
    }
)
_PROOFS = frozenset(
    {
        "project_rule_approved",
        "user_preference_approved",
        "decision_approved",
        "source_refs_reproved",
        "memoryos_killed",
        "memoryos_recovered",
        "full_local_capability_ready",
        "derived_layer_present",
        "all_target_correlations_settled",
        "sqlite_integrity_ok",
    }
)
_DIGESTS = frozenset(
    {"source_ref_digest", "context_digest", "capability_digest", "evidence_digest"}
)


class MemoryDiversityContractError(ValueError):
    """A private diversity receipt is malformed or fails its safety envelope."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise MemoryDiversityContractError("contract_json_invalid") from exc


def _sha(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: object, keys: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise MemoryDiversityContractError(code)
    return value


def _count(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_SAFE_INTEGER:
        raise MemoryDiversityContractError(code)
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise MemoryDiversityContractError(code)
    return value


def _opaque(value: object, code: str) -> str:
    if not isinstance(value, str) or _OPAQUE_REF.fullmatch(value) is None:
        raise MemoryDiversityContractError(code)
    return value


def _bool(value: object, code: str) -> bool:
    if not isinstance(value, bool):
        raise MemoryDiversityContractError(code)
    return value


def _normalize_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _exact(payload, _TOP_LEVEL, "evidence_invalid")
    if raw.get("schema_version") != EVIDENCE_SCHEMA:
        raise MemoryDiversityContractError("evidence_invalid")
    configuration = _exact(raw.get("configuration"), _CONFIGURATION, "evidence_invalid")
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
    digest_values = normalized["digests"]
    expected = _sha(
        {key: value for key, value in normalized.items() if key != "digests"}
        | {
            "digests": {
                key: value for key, value in digest_values.items() if key != "evidence_digest"
            }
        }
    )
    if digest_values["evidence_digest"] != expected:
        raise MemoryDiversityContractError("evidence_digest_invalid")
    return normalized


def _gate(
    gate_id: str, passed: bool, observed: int | bool, expected: int | bool
) -> dict[str, int | bool | str]:
    return {
        "gate_id": gate_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
    }


def _gates(evidence: Mapping[str, Any]) -> list[dict[str, int | bool | str]]:
    config = evidence["configuration"]
    counts = evidence["counts"]
    proofs = evidence["proofs"]
    return [
        _gate(
            "room_topology",
            config == {"room_count": 3, "agents_per_room": 4, "correlation_count": 18},
            3,
            3,
        ),
        _gate(
            "settled_correlations",
            proofs["all_target_correlations_settled"] and counts["settled_correlations"] >= 18,
            counts["settled_correlations"],
            18,
        ),
        _gate(
            "nonempty_receipts",
            counts["ok_receipts"] >= 4 and counts["nonempty_receipt_items"] >= 4,
            counts["ok_receipts"],
            4,
        ),
        _gate(
            "archival_and_derived_layers",
            counts["archival_project_items"] >= 1
            and proofs["derived_layer_present"]
            and counts["derived_items"] >= 1,
            counts["derived_items"],
            1,
        ),
        _gate(
            "approved_topics",
            proofs["project_rule_approved"]
            and proofs["user_preference_approved"]
            and proofs["decision_approved"],
            True,
            True,
        ),
        _gate(
            "cross_room_sources",
            counts["project_rule_cross_room_hits"] >= 1
            and counts["user_preference_cross_room_hits"] >= 1,
            counts["project_rule_cross_room_hits"],
            1,
        ),
        _gate(
            "decision_nonrecent",
            counts["decision_nonrecent_hits"] >= 1,
            counts["decision_nonrecent_hits"],
            1,
        ),
        _gate(
            "lexical_and_semantic",
            counts["lexical_hits"] >= 1 and counts["semantic_hits"] >= 1,
            counts["lexical_hits"],
            1,
        ),
        _gate(
            "source_reproof",
            proofs["source_refs_reproved"] and counts["source_refs_reproved"] >= 4,
            counts["source_refs_reproved"],
            4,
        ),
        _gate(
            "memoryos_recovery",
            proofs["memoryos_killed"]
            and proofs["memoryos_recovered"]
            and proofs["full_local_capability_ready"]
            and counts["memoryos_child_count_after_recovery"] == 1,
            counts["memoryos_child_count_after_recovery"],
            1,
        ),
        _gate(
            "exclusions",
            counts["unapproved_cross_room_sources"] == 0 and counts["unrelated_room_hits"] == 0,
            counts["unapproved_cross_room_sources"],
            0,
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


def build_memory_diversity_result(*, evidence: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_evidence(evidence)
    gates = _gates(normalized)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "run_ref": normalized["run_ref"],
        "status": "passed" if all(gate["status"] == "passed" for gate in gates) else "failed",
        "configuration": normalized["configuration"],
        "counts": normalized["counts"],
        "proofs": normalized["proofs"],
        "digests": normalized["digests"],
        "gates": gates,
        "proof_boundary": PROOF_BOUNDARY,
        "result_digest": "",
    }
    result["result_digest"] = _sha(
        {key: value for key, value in result.items() if key != "result_digest"}
    )
    return validate_memory_diversity_result(result)


def validate_memory_diversity_result(payload: Mapping[str, Any]) -> dict[str, Any]:
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
        raise MemoryDiversityContractError("result_invalid")
    gates = _gates(evidence)
    status = "passed" if all(gate["status"] == "passed" for gate in gates) else "failed"
    if raw.get("gates") != gates or raw.get("status") != status:
        raise MemoryDiversityContractError("result_gates_invalid")
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
        raise MemoryDiversityContractError("result_digest_invalid")
    if len(_canonical(normalized)) > MAX_RESULT_BYTES:
        raise MemoryDiversityContractError("result_too_large")
    return json.loads(_canonical(normalized))


def evaluate_memory_diversity_result(payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    normalized = validate_memory_diversity_result(payload)
    failed = tuple(
        str(gate["gate_id"]) for gate in normalized["gates"] if gate["status"] == "failed"
    )
    return not failed, failed
