from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CliWorkerGoalSkillContract:
    contract_id: str
    output_schema_version: str
    allowed_operations: tuple[str, ...]
    forbidden_operations: tuple[str, ...]
    required_output_fields: tuple[str, ...]


CLI_WORKER_GOAL_SKILL_CONTRACT_V1 = CliWorkerGoalSkillContract(
    contract_id="xmuse.cli_worker_goal.v1",
    output_schema_version="worker_goal_result.v1",
    allowed_operations=(
        "read_context",
        "edit_expected_touched_areas",
        "run_required_verification",
        "return_structured_worker_result",
    ),
    forbidden_operations=(
        "write_durable_store",
        "update_lane_status",
        "modify_feature_lanes_json_directly",
        "modify_runner_or_orchestrator_state_machine",
        "create_autonomous_god_chain",
    ),
    required_output_fields=(
        "request_id",
        "provider_id",
        "provider_profile_id",
        "status",
        "changed_files",
        "tests_run",
        "evidence_refs",
        "evidence",
        "verification",
        "blockers",
        "blocker_details",
        "confidence",
        "touched_areas",
        "summary",
    ),
)


__all__ = [
    "CLI_WORKER_GOAL_SKILL_CONTRACT_V1",
    "CliWorkerGoalSkillContract",
]
