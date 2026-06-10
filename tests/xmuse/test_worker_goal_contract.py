import pytest

from xmuse.skills.cli_worker_goal_contract import CLI_WORKER_GOAL_SKILL_CONTRACT_V1
from xmuse_core.platform.prompts.builders import build_worker_goal_prompt
from xmuse_core.providers.goal_contract import (
    WorkerBlocker,
    WorkerBlockerKind,
    WorkerEvidence,
    WorkerEvidenceKind,
    WorkerGoalContract,
    WorkerResultStatus,
    WorkerVerification,
    WorkerVerificationStatus,
    validate_worker_goal_result,
)
from xmuse_core.providers.models import ProviderId, ProviderProfileId
from xmuse_core.structuring.feature_graph_builder import build_feature_graph_set
from xmuse_core.structuring.models import FeaturePlan, FeaturePlanFeature


def _worker_goal_contract() -> WorkerGoalContract:
    return WorkerGoalContract(
        request_id="req-worker-123",
        lane_id="lane-contract-1",
        provider_id=ProviderId.CODEX,
        provider_profile_id=ProviderProfileId.WORKER,
        goal="Implement the worker goal contract lane.",
        acceptance_criteria=[
            "Worker results validate request id, provider/profile, and evidence.",
        ],
        blueprint_refs=[
            "docs/superpowers/specs/2026-05-31-xmuse-provider-platform-autonomous-recovery-blueprint-design.md",
        ],
        dependencies=["C0a-01-provider-profile-models"],
        expected_touched_areas=[
            "src/xmuse_core/providers/*",
            "src/xmuse_core/structuring/*",
            "tests/xmuse/test_worker_goal_contract.py",
        ],
        required_verification_commands=[
            "uv run pytest tests/xmuse/test_worker_goal_contract.py -q",
        ],
    )


def _completed_result_payload() -> dict[str, object]:
    return {
        "request_id": "req-worker-123",
        "provider_id": "codex",
        "provider_profile_id": "worker",
        "status": "completed",
        "changed_files": [
            "src/xmuse_core/providers/goal_contract.py",
            "src/xmuse_core/structuring/models.py",
        ],
        "tests_run": [
            "uv run pytest tests/xmuse/test_worker_goal_contract.py -q",
        ],
        "evidence_refs": [
            "tests/xmuse/test_worker_goal_contract.py::test_validate_worker_goal_result_accepts_matching_completed_result",
        ],
        "blockers": [],
        "confidence": 0.82,
        "touched_areas": [
            "src/xmuse_core/providers/goal_contract.py",
            "src/xmuse_core/structuring/models.py",
            "tests/xmuse/test_worker_goal_contract.py",
        ],
        "summary": "Validated the worker goal contract result schema.",
    }


def test_feature_graph_builder_carries_expected_touched_areas_to_lane_nodes() -> None:
    feature_plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="worker-goal-contracts",
                title="Worker goal contracts",
                goal="Define the contract and validator.",
                acceptance_criteria=["Touched-area bounds are preserved."],
                graph_id="graph-worker-goal-contracts",
                expected_touched_areas=[
                    "src/xmuse_core/providers/*",
                    "src/xmuse_core/structuring/*",
                ],
            )
        ],
    )

    graph_set = build_feature_graph_set(feature_plan, graph_set_id="graph-set-1")

    assert graph_set.feature_plan.features[0].expected_touched_areas == [
        "src/xmuse_core/providers/*",
        "src/xmuse_core/structuring/*",
    ]
    assert graph_set.graphs[0].lanes[0].expected_touched_areas == [
        "src/xmuse_core/providers/*",
    ]
    assert graph_set.graphs[0].lanes[-1].expected_touched_areas == [
        "src/xmuse_core/providers/*",
        "src/xmuse_core/structuring/*",
    ]


def test_validate_worker_goal_result_accepts_matching_completed_result() -> None:
    result = validate_worker_goal_result(
        _completed_result_payload(),
        contract=_worker_goal_contract(),
    )

    assert result.status is WorkerResultStatus.COMPLETED
    assert result.provider_profile_ref == "codex.worker"
    assert result.changed_files == [
        "src/xmuse_core/providers/goal_contract.py",
        "src/xmuse_core/structuring/models.py",
    ]


def test_worker_goal_contract_declares_controlled_cli_invocation_bounds() -> None:
    contract = _worker_goal_contract()

    assert contract.output_schema_version == "worker_goal_result.v1"
    assert contract.skill_contract_refs == ["xmuse.cli_worker_goal.v1"]
    assert any("durable store" in action for action in contract.forbidden_actions)
    assert any("lane status" in action for action in contract.forbidden_actions)
    assert any("autonomous GOD" in action for action in contract.forbidden_actions)


def test_cli_worker_skill_contract_documents_tool_boundaries() -> None:
    skill_contract = CLI_WORKER_GOAL_SKILL_CONTRACT_V1

    assert skill_contract.contract_id == "xmuse.cli_worker_goal.v1"
    assert skill_contract.output_schema_version == "worker_goal_result.v1"
    assert "read_context" in skill_contract.allowed_operations
    assert "write_durable_store" in skill_contract.forbidden_operations
    assert "create_autonomous_god_chain" in skill_contract.forbidden_operations
    assert "blocker_details" in skill_contract.required_output_fields
    assert "verification" in skill_contract.required_output_fields


def test_validate_worker_goal_result_accepts_typed_evidence_and_verification() -> None:
    verification_ref = (
        "tests/xmuse/test_worker_goal_contract.py::"
        "test_validate_worker_goal_result_accepts_typed_evidence_and_verification"
    )
    payload = _completed_result_payload() | {
        "evidence": [
            {
                "kind": "changed_file",
                "ref": "src/xmuse_core/providers/goal_contract.py",
                "summary": "Contract models were updated.",
            },
            {
                "kind": "verification",
                "ref": verification_ref,
                "summary": "Focused contract test passed.",
            },
        ],
        "verification": [
            {
                "command": "uv run pytest tests/xmuse/test_worker_goal_contract.py -q",
                "status": "passed",
                "exit_code": 0,
                "evidence_refs": [verification_ref],
                "summary": "Focused contract tests passed.",
            }
        ],
    }

    result = validate_worker_goal_result(payload, contract=_worker_goal_contract())

    assert result.evidence == [
        WorkerEvidence(
            kind=WorkerEvidenceKind.CHANGED_FILE,
            ref="src/xmuse_core/providers/goal_contract.py",
            summary="Contract models were updated.",
        ),
        WorkerEvidence(
            kind=WorkerEvidenceKind.VERIFICATION,
            ref=verification_ref,
            summary="Focused contract test passed.",
        ),
    ]
    assert result.verification == [
        WorkerVerification(
            command="uv run pytest tests/xmuse/test_worker_goal_contract.py -q",
            status=WorkerVerificationStatus.PASSED,
            exit_code=0,
            evidence_refs=[verification_ref],
            summary="Focused contract tests passed.",
        )
    ]


def test_validate_worker_goal_result_allows_blocked_result_with_explicit_blocker() -> None:
    payload = _completed_result_payload() | {
        "status": "blocked",
        "changed_files": [],
        "tests_run": [],
        "blockers": ["DEEPSEEK_API_KEY is not configured in this workspace."],
        "summary": "Blocked on provider credentials before verification could run.",
    }

    result = validate_worker_goal_result(payload, contract=_worker_goal_contract())

    assert result.status is WorkerResultStatus.BLOCKED
    assert result.blockers == [
        "DEEPSEEK_API_KEY is not configured in this workspace."
    ]


def test_validate_worker_goal_result_accepts_typed_blocker_classification() -> None:
    payload = _completed_result_payload() | {
        "status": "blocked",
        "changed_files": [],
        "tests_run": [],
        "blockers": [],
        "blocker_details": [
            {
                "kind": "provider_config",
                "message": "DEEPSEEK_API_KEY is not configured in this workspace.",
                "retryable": True,
                "evidence_refs": ["provider.health.opencode.deepseek_flash_worker"],
            }
        ],
        "summary": "Blocked on provider credentials before verification could run.",
    }

    result = validate_worker_goal_result(payload, contract=_worker_goal_contract())

    assert result.blocker_details == [
        WorkerBlocker(
            kind=WorkerBlockerKind.PROVIDER_CONFIG,
            message="DEEPSEEK_API_KEY is not configured in this workspace.",
            retryable=True,
            evidence_refs=["provider.health.opencode.deepseek_flash_worker"],
        )
    ]


def test_build_worker_goal_prompt_renders_skill_contract_and_output_schema() -> None:
    prompt = build_worker_goal_prompt(
        _worker_goal_contract(),
        task_context="Use the existing provider contract models.",
    )

    assert "## CLI Worker Goal Contract" in prompt
    assert "request_id: req-worker-123" in prompt
    assert "lane_id: lane-contract-1" in prompt
    assert "worker_goal_result.v1" in prompt
    assert "xmuse.cli_worker_goal.v1" in prompt
    assert "Do not write durable stores" in prompt
    assert "Do not update lane status" in prompt
    assert "Do not create autonomous GOD chains" in prompt
    assert "changed_files" in prompt
    assert "verification" in prompt
    assert "blocker_details" in prompt


@pytest.mark.parametrize("missing_field", ["evidence_refs", "touched_areas"])
def test_validate_worker_goal_result_rejects_missing_required_lists(
    missing_field: str,
) -> None:
    payload = _completed_result_payload()
    payload.pop(missing_field)

    with pytest.raises(ValueError, match=missing_field):
        validate_worker_goal_result(payload, contract=_worker_goal_contract())


@pytest.mark.parametrize(
    ("payload_updates", "match"),
    [
        ({"request_id": "req-worker-stale"}, "stale request id"),
        (
            {"provider_profile_id": "review"},
            "provider/profile must match the worker goal contract",
        ),
        (
            {"tests_run": [], "blockers": []},
            "tests_run or verification must contain at least one item when blockers are empty",
        ),
        (
            {"changed_files": []},
            "changed_files must contain at least one item for edit lanes",
        ),
        (
            {"evidence_refs": []},
            "evidence_refs must contain at least one item",
        ),
        (
            {"touched_areas": []},
            "touched_areas must contain at least one item",
        ),
        (
            {"touched_areas": ["src/xmuse_core/platform/orchestrator.py"]},
            "touched areas fall outside expected_touched_areas",
        ),
    ],
)
def test_validate_worker_goal_result_rejects_contract_violations(
    payload_updates: dict[str, object],
    match: str,
) -> None:
    payload = _completed_result_payload() | payload_updates

    with pytest.raises(ValueError, match=match):
        validate_worker_goal_result(payload, contract=_worker_goal_contract())
