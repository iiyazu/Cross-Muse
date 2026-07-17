from __future__ import annotations

from copy import deepcopy

import pytest

from xmuse_core.chat.room_execution_repository_matrix import (
    RESULT_SCHEMA,
    RepositoryMatrixContractError,
    build_repository_matrix_result,
    evaluate_repository_matrix_result,
    normalize_repository_matrix_result,
    validate_repository_matrix_result,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _scenario(
    scenario_id: str,
    profile_id: str,
    status: str,
    reason: str,
    *,
    index: int,
) -> dict[str, object]:
    passed = status == "passed"
    return {
        "scenario_id": scenario_id,
        "profile_id": profile_id,
        "frozen_commit_digest": _digest(format(index, "x")),
        "frozen_tree_digest": _digest(format(index + 5, "x")),
        "expected_status": status,
        "observed_status": status,
        "reason_code": reason,
        "gate_count": 4 if passed else 0,
        "changed_file_count": 2 if passed else 0,
        "execution_started": passed,
        "source_guard_unchanged": True,
        "promotion_applied": passed,
        "target_bytes_exact": True,
        "sandbox_boundary_preserved": True,
        "evidence_digest": _digest(format(index + 10, "x")),
    }


def _scenarios() -> list[dict[str, object]]:
    return [
        _scenario("memu-python", "python-uv/v1", "passed", "accepted", index=1),
        _scenario("clowder-docs", "docs/v1", "passed", "accepted", index=2),
        _scenario("memoryos-control", "python-uv/v1", "passed", "accepted", index=3),
        _scenario(
            "letta-blocked",
            "python-uv/v1",
            "blocked",
            "execution_backend_dependencies_unavailable",
            index=4,
        ),
        _scenario(
            "mem0-blocked",
            "python-uv/v1",
            "blocked",
            "execution_gate_profile_marker_missing",
            index=5,
        ),
    ]


def test_fixed_two_new_repositories_and_control_pass_with_exact_blocks() -> None:
    result = build_repository_matrix_result(scenarios=_scenarios())

    assert result["schema_version"] == RESULT_SCHEMA
    assert result["scenario_count"] == 5
    assert result["positive_promotions"] == 3
    assert result["expected_blocks"] == 2
    assert evaluate_repository_matrix_result(result) == (True, ())
    assert normalize_repository_matrix_result(result) == result
    assert validate_repository_matrix_result(result) == result


@pytest.mark.parametrize(
    ("scenario_id", "wrong_reason"),
    [
        ("letta-blocked", "execution_gate_profile_marker_missing"),
        ("mem0-blocked", "execution_backend_dependencies_unavailable"),
    ],
)
def test_negative_scenarios_require_the_exact_fail_closed_reason(
    scenario_id: str,
    wrong_reason: str,
) -> None:
    scenarios = _scenarios()
    item = next(value for value in scenarios if value["scenario_id"] == scenario_id)
    item["reason_code"] = wrong_reason
    result = build_repository_matrix_result(scenarios=scenarios)

    assert evaluate_repository_matrix_result(result) == (False, (scenario_id,))


@pytest.mark.parametrize("forbidden", ["path", "patch", "log", "argv", "token"])
def test_scenario_rejects_forbidden_or_other_extra_fields(forbidden: str) -> None:
    scenarios = _scenarios()
    scenarios[0][forbidden] = "/private/repository secret-value"

    with pytest.raises(RepositoryMatrixContractError) as raised:
        build_repository_matrix_result(scenarios=scenarios)

    assert raised.value.code == "repository_matrix_scenario_invalid"


def test_profile_scenario_order_counts_and_digest_are_fail_closed() -> None:
    result = build_repository_matrix_result(scenarios=_scenarios())

    reordered = deepcopy(result)
    reordered["scenarios"] = list(reversed(reordered["scenarios"]))
    with pytest.raises(RepositoryMatrixContractError) as order_error:
        validate_repository_matrix_result(reordered)
    assert order_error.value.code == "repository_matrix_scenarios_invalid"

    wrong_profile = _scenarios()
    wrong_profile[0]["profile_id"] = "docs/v1"
    with pytest.raises(RepositoryMatrixContractError) as profile_error:
        build_repository_matrix_result(scenarios=wrong_profile)
    assert profile_error.value.code == "repository_matrix_profile_mismatch"

    wrong_count = deepcopy(result)
    wrong_count["scenario_count"] = 4
    with pytest.raises(RepositoryMatrixContractError) as count_error:
        validate_repository_matrix_result(wrong_count)
    assert count_error.value.code == "repository_matrix_result_invalid"

    tampered = deepcopy(result)
    tampered["scenarios"][0]["gate_count"] += 1
    with pytest.raises(RepositoryMatrixContractError) as digest_error:
        validate_repository_matrix_result(tampered)
    assert digest_error.value.code == "repository_matrix_digest_invalid"


def test_invalid_source_reference_and_non_boolean_proofs_are_rejected() -> None:
    invalid_ref = _scenarios()
    invalid_ref[0]["frozen_commit_digest"] = "1" * 40
    with pytest.raises(RepositoryMatrixContractError) as ref_error:
        build_repository_matrix_result(scenarios=invalid_ref)
    assert ref_error.value.code == "repository_matrix_source_ref_invalid"

    invalid_flag = _scenarios()
    invalid_flag[0]["source_guard_unchanged"] = 1
    with pytest.raises(RepositoryMatrixContractError) as flag_error:
        build_repository_matrix_result(scenarios=invalid_flag)
    assert flag_error.value.code == "repository_matrix_scenario_invalid"


def test_valid_result_can_report_a_failed_positive_without_losing_evidence() -> None:
    scenarios = _scenarios()
    scenarios[0].update(
        {
            "observed_status": "blocked",
            "reason_code": "execution_backend_dependencies_unavailable",
            "gate_count": 0,
            "changed_file_count": 0,
            "execution_started": False,
            "promotion_applied": False,
        }
    )

    result = build_repository_matrix_result(scenarios=scenarios)

    assert evaluate_repository_matrix_result(result) == (False, ("memu-python",))
