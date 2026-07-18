"""Safe aggregate result contract for the fixed repository acceptance matrix.

The contract deliberately carries only bounded counts, booleans, trusted profile
identifiers, and opaque SHA-256 references.  Repository paths, patch content,
process arguments, logs, and credentials are outside this boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

RESULT_SCHEMA: Final = "room_execution_repository_matrix_result/v1"
MAX_RESULT_BYTES: Final = 16 * 1024

SCENARIO_IDS: Final = (
    "memu-python",
    "clowder-next-probe",
    "memoryos-control",
    "letta-ty-probe",
    "mem0-ts-probe",
)

_SCENARIO_POLICY: Final = {
    "memu-python": ("python-uv/v1", "passed", "accepted"),
    "clowder-next-probe": (
        "node-pnpm-next-workspace/v1",
        "blocked",
        "execution_frontend_dependencies_unavailable",
    ),
    "memoryos-control": ("python-uv/v1", "passed", "accepted"),
    "letta-ty-probe": (
        "python-uv-ty/v1",
        "blocked",
        "execution_backend_dependencies_unavailable",
    ),
    "mem0-ts-probe": (
        "node-pnpm-library/v1",
        "blocked",
        "execution_frontend_dependencies_unavailable",
    ),
}
_REASONS: Final = frozenset(
    {
        "accepted",
        "execution_backend_dependencies_unavailable",
        "execution_frontend_dependencies_unavailable",
    }
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SCENARIO_FIELDS: Final = frozenset(
    {
        "scenario_id",
        "profile_id",
        "frozen_commit_digest",
        "frozen_tree_digest",
        "expected_status",
        "observed_status",
        "reason_code",
        "gate_count",
        "changed_file_count",
        "execution_started",
        "source_guard_unchanged",
        "promotion_applied",
        "target_bytes_exact",
        "sandbox_boundary_preserved",
        "evidence_digest",
    }
)
_RESULT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "scenario_count",
        "positive_promotions",
        "expected_blocks",
        "scenarios",
        "matrix_digest",
    }
)


class RepositoryMatrixContractError(ValueError):
    """Stable fail-closed rejection for malformed matrix evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RepositoryMatrixContractError("repository_matrix_result_invalid") from exc


def _sha(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


def _exact_mapping(value: object, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RepositoryMatrixContractError(code)
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise RepositoryMatrixContractError(code)
    return value


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
        raise RepositoryMatrixContractError("repository_matrix_scenario_invalid")
    return value


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise RepositoryMatrixContractError("repository_matrix_scenario_invalid")
    return value


def _normalize_scenario(value: object) -> dict[str, Any]:
    raw = _exact_mapping(
        value,
        _SCENARIO_FIELDS,
        "repository_matrix_scenario_invalid",
    )
    scenario_id = raw.get("scenario_id")
    if not isinstance(scenario_id, str) or scenario_id not in _SCENARIO_POLICY:
        raise RepositoryMatrixContractError("repository_matrix_scenario_unknown")
    profile_id, expected_status, expected_reason = _SCENARIO_POLICY[scenario_id]
    if raw.get("profile_id") != profile_id:
        raise RepositoryMatrixContractError("repository_matrix_profile_mismatch")
    if raw.get("expected_status") != expected_status or raw.get("reason_code") not in _REASONS:
        raise RepositoryMatrixContractError("repository_matrix_expectation_invalid")
    observed_status = raw.get("observed_status")
    reason_code = raw.get("reason_code")
    if observed_status not in {"passed", "blocked"}:
        raise RepositoryMatrixContractError("repository_matrix_scenario_invalid")
    if (observed_status == "passed") != (reason_code == "accepted"):
        raise RepositoryMatrixContractError("repository_matrix_reason_invalid")
    # The expected blocker is immutable policy, even when the observed outcome differs.
    if expected_status == "blocked" and expected_reason not in _REASONS:
        raise RepositoryMatrixContractError("repository_matrix_expectation_invalid")
    return {
        "scenario_id": scenario_id,
        "profile_id": profile_id,
        "frozen_commit_digest": _digest(
            raw.get("frozen_commit_digest"), "repository_matrix_source_ref_invalid"
        ),
        "frozen_tree_digest": _digest(
            raw.get("frozen_tree_digest"), "repository_matrix_source_ref_invalid"
        ),
        "expected_status": expected_status,
        "observed_status": observed_status,
        "reason_code": reason_code,
        "gate_count": _count(raw.get("gate_count")),
        "changed_file_count": _count(raw.get("changed_file_count")),
        "execution_started": _flag(raw.get("execution_started")),
        "source_guard_unchanged": _flag(raw.get("source_guard_unchanged")),
        "promotion_applied": _flag(raw.get("promotion_applied")),
        "target_bytes_exact": _flag(raw.get("target_bytes_exact")),
        "sandbox_boundary_preserved": _flag(raw.get("sandbox_boundary_preserved")),
        "evidence_digest": _digest(
            raw.get("evidence_digest"), "repository_matrix_evidence_digest_invalid"
        ),
    }


def _normalize_scenarios(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise RepositoryMatrixContractError("repository_matrix_scenarios_invalid")
    normalized = [_normalize_scenario(item) for item in value]
    identifiers = tuple(item["scenario_id"] for item in normalized)
    if identifiers != SCENARIO_IDS:
        raise RepositoryMatrixContractError("repository_matrix_scenarios_invalid")
    return normalized


def build_repository_matrix_result(*, scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build one canonical, digest-bound result from fixed-scenario evidence."""

    normalized = _normalize_scenarios(scenarios)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "scenario_count": len(SCENARIO_IDS),
        "positive_promotions": 2,
        "expected_blocks": 3,
        "scenarios": normalized,
        "matrix_digest": "",
    }
    result["matrix_digest"] = _sha(
        {key: value for key, value in result.items() if key != "matrix_digest"}
    )
    return validate_repository_matrix_result(result)


def validate_repository_matrix_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate exact shape, fixed policy, ordering, bounds, and aggregate digest."""

    raw = _exact_mapping(payload, _RESULT_FIELDS, "repository_matrix_result_invalid")
    if (
        raw.get("schema_version") != RESULT_SCHEMA
        or raw.get("scenario_count") != len(SCENARIO_IDS)
        or raw.get("positive_promotions") != 2
        or raw.get("expected_blocks") != 3
    ):
        raise RepositoryMatrixContractError("repository_matrix_result_invalid")
    normalized: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "scenario_count": len(SCENARIO_IDS),
        "positive_promotions": 2,
        "expected_blocks": 3,
        "scenarios": _normalize_scenarios(raw.get("scenarios")),
        "matrix_digest": _digest(raw.get("matrix_digest"), "repository_matrix_digest_invalid"),
    }
    expected_digest = _sha(
        {key: value for key, value in normalized.items() if key != "matrix_digest"}
    )
    if normalized["matrix_digest"] != expected_digest:
        raise RepositoryMatrixContractError("repository_matrix_digest_invalid")
    if len(_canonical(normalized)) > MAX_RESULT_BYTES:
        raise RepositoryMatrixContractError("repository_matrix_result_too_large")
    return json.loads(_canonical(normalized))


def normalize_repository_matrix_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical representation of a validated result."""

    return validate_repository_matrix_result(payload)


def _scenario_satisfies_policy(scenario: Mapping[str, Any]) -> bool:
    _profile_id, expected_status, expected_reason = _SCENARIO_POLICY[str(scenario["scenario_id"])]
    common = (
        scenario["observed_status"] == expected_status
        and scenario["reason_code"] == expected_reason
        and scenario["source_guard_unchanged"] is True
        and scenario["target_bytes_exact"] is True
        and scenario["sandbox_boundary_preserved"] is True
    )
    if expected_status == "passed":
        return bool(
            common
            and scenario["execution_started"] is True
            and scenario["promotion_applied"] is True
            and scenario["gate_count"] > 0
            and scenario["changed_file_count"] > 0
        )
    return bool(
        common
        and scenario["execution_started"] is False
        and scenario["promotion_applied"] is False
        and scenario["gate_count"] == 0
        and scenario["changed_file_count"] == 0
    )


def evaluate_repository_matrix_result(
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    """Return matrix success and the fixed IDs that failed their policy."""

    normalized = validate_repository_matrix_result(payload)
    failed = tuple(
        str(scenario["scenario_id"])
        for scenario in normalized["scenarios"]
        if not _scenario_satisfies_policy(scenario)
    )
    return not failed, failed
