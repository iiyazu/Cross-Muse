from __future__ import annotations

from copy import deepcopy

import pytest

from xmuse_core.chat.room_memory_recall_dogfood import (
    EVIDENCE_SCHEMA,
    RESULT_SCHEMA,
    RecallDogfoodContractError,
    build_memory_recall_dogfood_result,
    evaluate_memory_recall_dogfood_result,
    validate_memory_recall_dogfood_result,
)


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _evidence() -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA,
        "run_ref": "run_" + "a" * 32,
        "configuration": {"room_count": 2, "agents_per_room": 4},
        "counts": {
            "room_a_correlations": 6,
            "room_a_tail_visible_activities": 9,
            "approved_project_candidates": 1,
            "delivered_project_candidates": 1,
            "attached_bindings": 6,
            "message_backlog": 0,
            "document_backlog": 0,
            "memoryos_child_count_after_recovery": 1,
            "room_b_ok_receipts": 1,
            "room_b_receipt_items": 2,
            "cross_room_project_sources_reproved": 1,
            "derived_items": 1,
            "unapproved_cross_room_sources": 0,
            "settled_correlations": 7,
            "browser_console_errors": 0,
            "sensitive_leaks": 0,
        },
        "proofs": {
            "candidate_approved": True,
            "candidate_delivered": True,
            "all_scope_bindings_attached": True,
            "memoryos_killed": True,
            "memoryos_recovered": True,
            "full_local_capability_ready": True,
            "room_b_receipt_ok": True,
            "cross_room_project_source_reproved": True,
            "source_excluded_from_current_correlation": True,
            "source_excluded_from_causal_envelope": True,
            "source_excluded_from_recent_burst": True,
            "context_coverage_omits_source": True,
            "receipt_evidence_context_bound": True,
            "derived_layer_present": True,
            "all_target_correlations_settled": True,
            "sqlite_integrity_ok": True,
        },
        "digests": {
            "approved_project_source_ref_digest": _digest("a"),
            "receipt_evidence_digest": _digest("b"),
            "receipt_context_digest": _digest("c"),
            "skill_context_digest": _digest("c"),
            "derived_source_ref_digest": _digest("d"),
            "evidence_digest": "",
        },
    }
    material = {key: value for key, value in result.items() if key != "digests"}
    material["digests"] = {
        key: value for key, value in result["digests"].items() if key != "evidence_digest"
    }
    import hashlib
    import json

    result["digests"]["evidence_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    return result


def test_build_validate_and_evaluate_safe_passing_result() -> None:
    result = build_memory_recall_dogfood_result(evidence=_evidence())

    assert result["schema_version"] == RESULT_SCHEMA
    assert result["status"] == "passed"
    assert evaluate_memory_recall_dogfood_result(result) == (True, ())
    assert validate_memory_recall_dogfood_result(result) == result
    encoded = str(result)
    for forbidden in ("/home/", "session_id", "message_id", "document_id", "trace", "raw evidence"):
        assert forbidden not in encoded


def test_all_hard_gate_categories_fail_stably() -> None:
    evidence = _evidence()
    evidence["counts"]["room_a_correlations"] = 5
    evidence["counts"]["message_backlog"] = 1
    evidence["counts"]["memoryos_child_count_after_recovery"] = 2
    evidence["proofs"]["source_excluded_from_recent_burst"] = False
    evidence["digests"]["skill_context_digest"] = _digest("e")
    evidence["counts"]["derived_items"] = 0
    evidence["counts"]["sensitive_leaks"] = 1
    # Recompute the evidence digest after deliberately changing aggregate evidence.
    evidence["digests"]["evidence_digest"] = ""
    result = _evidence_digest(evidence)
    built = build_memory_recall_dogfood_result(evidence=result)
    passed, failures = evaluate_memory_recall_dogfood_result(built)

    assert not passed
    assert {
        "room_a_correlations",
        "outbox_drained",
        "memoryos_recovered_single_child",
        "long_memory_exclusion",
        "context_digest_binding",
        "derived_evidence",
        "sensitive_leak_free",
    }.issubset(failures)


def test_non_matching_topology_is_a_failed_gate_not_an_invalid_contract() -> None:
    evidence = _evidence()
    evidence["configuration"] = {"room_count": 2, "agents_per_room": 0}
    built = build_memory_recall_dogfood_result(evidence=_evidence_digest(evidence))

    assert built["status"] == "failed"
    assert evaluate_memory_recall_dogfood_result(built) == (False, ("room_topology",))


def _evidence_digest(evidence: dict[str, object]) -> dict[str, object]:
    import hashlib
    import json

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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"path": "/private/root"}),
        lambda value: value.update({"session_id": "memory-secret"}),
        lambda value: value["counts"].update({"provider_output": 1}),
        lambda value: value["proofs"].update({"trace": True}),
        lambda value: value["digests"].update({"message_id": _digest("f")}),
    ],
)
def test_private_or_uncontracted_fields_fail_closed(mutate) -> None:
    result = build_memory_recall_dogfood_result(evidence=_evidence())
    mutate(result)
    with pytest.raises(RecallDogfoodContractError):
        validate_memory_recall_dogfood_result(result)


def test_forged_gates_and_digest_fail_closed() -> None:
    result = build_memory_recall_dogfood_result(evidence=_evidence())
    forged = deepcopy(result)
    forged["gates"][0]["status"] = "failed"
    with pytest.raises(RecallDogfoodContractError, match="result_gates_invalid"):
        validate_memory_recall_dogfood_result(forged)
    forged = deepcopy(result)
    forged["result_digest"] = _digest("f")
    with pytest.raises(RecallDogfoodContractError, match="result_digest_invalid"):
        validate_memory_recall_dogfood_result(forged)
