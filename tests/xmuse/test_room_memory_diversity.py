from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from xmuse_core.chat.room_memory_diversity import (
    EVIDENCE_SCHEMA,
    RESULT_SCHEMA,
    MemoryDiversityContractError,
    build_memory_diversity_result,
    evaluate_memory_diversity_result,
    validate_memory_diversity_result,
)


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _evidence() -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA,
        "run_ref": "run_" + "a" * 32,
        "configuration": {"room_count": 3, "agents_per_room": 4, "correlation_count": 18},
        "counts": {
            "settled_correlations": 18,
            "ok_receipts": 4,
            "nonempty_receipt_items": 5,
            "archival_project_items": 1,
            "derived_items": 2,
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
            "source_ref_digest": _digest("a"),
            "context_digest": _digest("b"),
            "capability_digest": _digest("c"),
            "evidence_digest": "",
        },
    }
    material = {key: value for key, value in evidence.items() if key != "digests"}
    material["digests"] = {
        key: value for key, value in evidence["digests"].items() if key != "evidence_digest"
    }
    evidence["digests"]["evidence_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    return evidence


def _with_digest(evidence: dict[str, object]) -> dict[str, object]:
    copied = deepcopy(evidence)
    material = {key: value for key, value in copied.items() if key != "digests"}
    material["digests"] = {
        key: value for key, value in copied["digests"].items() if key != "evidence_digest"
    }
    copied["digests"]["evidence_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    return copied


def test_passing_result_is_bounded_and_round_trips() -> None:
    result = build_memory_diversity_result(evidence=_evidence())

    assert result["schema_version"] == RESULT_SCHEMA
    assert evaluate_memory_diversity_result(result) == (True, ())
    assert validate_memory_diversity_result(result) == result
    assert len(json.dumps(result, ensure_ascii=False)) < 16 * 1024
    for forbidden in ("/home/", "session_id", "document_id", "provider", "trace"):
        assert forbidden not in json.dumps(result)


def test_missing_topic_or_recovery_is_a_failed_gate() -> None:
    evidence = _evidence()
    evidence["counts"]["semantic_hits"] = 0
    evidence["counts"]["memoryos_child_count_after_recovery"] = 2
    result = build_memory_diversity_result(evidence=_with_digest(evidence))

    passed, failures = evaluate_memory_diversity_result(result)
    assert not passed
    assert {"lexical_and_semantic", "memoryos_recovery"}.issubset(failures)


def _unknown_top_level(value: dict[str, object]) -> dict[str, object]:
    value["path"] = "/private/root"
    return value


def _unknown_count(value: dict[str, object]) -> dict[str, object]:
    value["counts"]["provider_output"] = 1
    return value


def _unknown_proof(value: dict[str, object]) -> dict[str, object]:
    value["proofs"]["trace"] = True
    return value


def _unknown_digest(value: dict[str, object]) -> dict[str, object]:
    value["digests"]["message_id"] = _digest("f")
    return value


@pytest.mark.parametrize(
    "mutate", [_unknown_top_level, _unknown_count, _unknown_proof, _unknown_digest]
)
def test_uncontracted_or_sensitive_fields_fail_closed(mutate) -> None:
    with pytest.raises(MemoryDiversityContractError):
        build_memory_diversity_result(evidence=mutate(deepcopy(_evidence())))


def test_forged_gate_or_result_digest_fails_closed() -> None:
    result = build_memory_diversity_result(evidence=_evidence())
    forged = deepcopy(result)
    forged["gates"][0]["status"] = "failed"
    with pytest.raises(MemoryDiversityContractError, match="result_gates_invalid"):
        validate_memory_diversity_result(forged)
    forged = deepcopy(result)
    forged["result_digest"] = _digest("f")
    with pytest.raises(MemoryDiversityContractError, match="result_digest_invalid"):
        validate_memory_diversity_result(forged)
