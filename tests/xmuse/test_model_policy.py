from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.execution.executor import (
    ExecutePeerContract,
    _persistent_execute_prompt,
)
from xmuse_core.platform.messages import ExecuteResponse, ReviewVerdict
from xmuse_core.platform.model_policy import (
    CodexModelPolicy,
    evaluate_model_tier_adjustment,
    has_ambiguous_review_signal,
    has_high_risk_files,
    is_low_risk_bounded_task,
    is_repeated_failure_lane,
    resolve_codex_model_policy,
)
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.providers.policy import ProviderPolicyService

PROJECT = Path(__file__).resolve().parents[2]
PLATFORM_RUNNER_PATH = PROJECT / "xmuse" / "platform_runner.py"


def _load_platform_runner():
    spec = importlib.util.spec_from_file_location(
        "xmuse_platform_runner_for_model_policy_tests",
        PLATFORM_RUNNER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_model_policy_default_preserves_legacy_behavior() -> None:
    policy = CodexModelPolicy.default()

    assert policy.enabled is False
    assert policy.runtime == "codex"
    assert policy.review_model == "gpt-5.4"
    assert policy.coordinator_model == "gpt-5.4"
    assert policy.worker_model == "gpt-5.4-mini"
    assert policy.delegation_mode == "legacy_single_agent"
    assert policy.metadata_defaults() == {}


def test_codex_model_policy_tiered_defaults_are_opt_in_metadata() -> None:
    policy = CodexModelPolicy.tiered()

    assert policy.enabled is True
    assert policy.review_model == "gpt-5.4"
    assert policy.coordinator_model == "gpt-5.4"
    assert policy.worker_model == "gpt-5.4-mini"
    assert policy.delegation_mode == "bounded_worker"
    assert policy.metadata_defaults() == {
        "model_policy_runtime": "codex",
        "model_policy_enabled": True,
        "review_model": "gpt-5.4",
        "coordinator_model": "gpt-5.4",
        "worker_model": "gpt-5.4-mini",
        "delegation_mode": "bounded_worker",
        "delegation_contract": "bounded_code_writing_v1",
        "model_selection_records": [
            {
                "peer_type": "review",
                "lane_risk": "high",
                "task_type": "review",
                "model_tier": "frontier_high_reasoning",
                "selected_model": "gpt-5.4",
                "selection_reason": (
                    "Persistent review and high-risk decisions stay on the "
                    "frontier high-reasoning tier."
                ),
            },
            {
                "peer_type": "coordinator",
                "lane_risk": "medium",
                "task_type": "lane_coordination",
                "model_tier": "mid_tier",
                "selected_model": "gpt-5.4",
                "selection_reason": (
                    "Lane coordination and integration default to the mid-tier "
                    "Codex model."
                ),
            },
            {
                "peer_type": "worker",
                "lane_risk": "low",
                "task_type": "bounded_code_writing",
                "model_tier": "low_cost",
                "selected_model": "gpt-5.4-mini",
                "selection_reason": (
                    "Bounded low-risk code writing defaults to the low-cost "
                    "worker tier."
                ),
            },
        ],
    }


def test_codex_model_policy_selection_records_use_lane_context() -> None:
    policy = CodexModelPolicy.tiered()

    escalated_records = policy.selection_records(
        lane={
            "status": "reworking",
            "retry_count": 2,
            "review_summary": "Review decision: no blocking findings",
            "changed_files": [
                "src/xmuse_core/platform/orchestrator.py",
                "src/xmuse_core/self_evolution/evidence/aggregator.py",
            ],
        }
    )
    escalated_worker = next(
        record for record in escalated_records if record["peer_type"] == "worker"
    )
    escalated_coordinator = next(
        record for record in escalated_records if record["peer_type"] == "coordinator"
    )

    assert escalated_worker["lane_risk"] == "high"
    assert escalated_worker["model_tier"] == "frontier_high_reasoning"
    assert escalated_worker["selected_model"] == "gpt-5.4"
    assert "repeated failure" in escalated_worker["selection_reason"]
    assert "ambiguous review" in escalated_worker["selection_reason"]
    assert "cross-module blast radius" in escalated_worker["selection_reason"]
    assert escalated_coordinator["model_tier"] == "frontier_high_reasoning"

    downgraded_records = policy.selection_records(
        lane={
            "risk": "low",
            "task_type": "mechanical_cleanup",
            "bounded_context": True,
            "well_specified": True,
            "changed_files": ["README.md"],
        }
    )
    downgraded_coordinator = next(
        record for record in downgraded_records if record["peer_type"] == "coordinator"
    )

    assert downgraded_coordinator["lane_risk"] == "low"
    assert downgraded_coordinator["model_tier"] == "low_cost"
    assert downgraded_coordinator["selected_model"] == "gpt-5.4-mini"
    assert "bounded" in downgraded_coordinator["selection_reason"]
    assert "well-specified" in downgraded_coordinator["selection_reason"]


def test_codex_model_policy_escalation_matches_provider_policy_escalation() -> None:
    lane = {
        "status": "reworking",
        "retry_count": 2,
        "review_summary": "Review decision: no blocking findings",
        "changed_files": [
            "src/xmuse_core/platform/orchestrator.py",
            "src/xmuse_core/providers/policy.py",
        ],
    }

    provider_decision = ProviderPolicyService().select_worker(lane=lane)
    policy = CodexModelPolicy.tiered()
    worker_record = next(
        record for record in policy.selection_records(lane=lane) if record["peer_type"] == "worker"
    )

    assert provider_decision.provider_profile_ref == "codex.god"
    assert provider_decision.escalation_level == "high"
    assert worker_record["lane_risk"] == "high"
    assert worker_record["model_tier"] == "frontier_high_reasoning"
    assert worker_record["selected_model"] == "gpt-5.4"


def test_model_policy_rule_helpers_return_deterministic_adjustment_summary() -> None:
    escalated_lane = {
        "status": "reworking",
        "retry_count": 1,
        "review_retry_count": 1,
        "review_summary": "Approved with no blocking findings",
        "changed_files": [
            "src/xmuse_core/platform/orchestrator.py",
            "src/xmuse_core/self_evolution/evidence/aggregator.py",
        ],
    }

    assert is_repeated_failure_lane(escalated_lane) is True
    assert has_ambiguous_review_signal(escalated_lane) is True
    assert has_high_risk_files(escalated_lane) is True
    assert is_low_risk_bounded_task(escalated_lane) is False
    assert evaluate_model_tier_adjustment(escalated_lane) == {
        "repeated_failure": True,
        "ambiguous_review": True,
        "cross_module_blast_radius": True,
        "high_risk_files": True,
        "bounded_context": False,
        "well_specified": False,
        "low_risk_bounded_task": False,
        "downgrade_to_low_cost": False,
        "escalation_level": "high",
        "escalation_reasons": [
            "repeated failure",
            "ambiguous review",
            "high-risk files",
            "cross-module blast radius",
        ],
    }

    downgraded_lane = {
        "risk": "low",
        "task_type": "mechanical_cleanup",
        "bounded_context": True,
        "well_specified": True,
        "changed_files": ["README.md"],
    }

    assert is_repeated_failure_lane(downgraded_lane) is False
    assert has_ambiguous_review_signal(downgraded_lane) is False
    assert has_high_risk_files(downgraded_lane) is False
    assert is_low_risk_bounded_task(downgraded_lane) is True
    assert evaluate_model_tier_adjustment(downgraded_lane) == {
        "repeated_failure": False,
        "ambiguous_review": False,
        "cross_module_blast_radius": False,
        "high_risk_files": False,
        "bounded_context": True,
        "well_specified": True,
        "low_risk_bounded_task": True,
        "downgrade_to_low_cost": True,
        "escalation_level": "none",
        "escalation_reasons": [],
    }


def test_codex_model_policy_rejects_non_codex_runtime() -> None:
    with pytest.raises(ValidationError):
        CodexModelPolicy(runtime="claude_code")


def test_resolve_codex_model_policy_applies_overrides_only_when_enabled() -> None:
    assert resolve_codex_model_policy(enabled=False) is None

    policy = resolve_codex_model_policy(
        enabled=True,
        review_model="gpt-5.5-high",
        coordinator_model="gpt-5.4-coordinator",
        worker_model="gpt-5.4-mini-fast",
        delegation_mode="legacy_single_agent",
    )

    assert policy is not None
    assert policy.review_model == "gpt-5.4"
    assert policy.coordinator_model == "gpt-5.4-coordinator"
    assert policy.worker_model == "gpt-5.4-mini-fast"
    assert policy.delegation_mode == "legacy_single_agent"


def test_platform_runner_parses_opt_in_codex_model_policy() -> None:
    platform_runner = _load_platform_runner()

    args = platform_runner.main_arg_parser().parse_args(
        [
            "--codex-model-policy",
            "tiered",
            "--review-model",
            "gpt-5.5-high",
            "--coordinator-model",
            "gpt-5.4-coordinator",
            "--worker-model",
            "gpt-5.4-mini-fast",
            "--delegation-mode",
            "bounded_worker",
        ]
    )

    platform_runner.validate_args(args)
    policy = platform_runner._model_policy_from_args(args)

    assert policy is not None
    assert policy.metadata_defaults()["review_model"] == "gpt-5.4"
    assert policy.metadata_defaults()["coordinator_model"] == "gpt-5.4-coordinator"
    assert policy.metadata_defaults()["worker_model"] == "gpt-5.4-mini-fast"


def test_codex_model_policy_sanitizes_reserved_final_quality_models_for_ordinary_roles() -> None:
    policy = CodexModelPolicy.tiered(
        review_model="gpt-5.5",
        coordinator_model="gpt-5.5",
        worker_model="gpt-5.5",
    )

    assert policy.review_model == "gpt-5.4"
    assert policy.coordinator_model == "gpt-5.4"
    assert policy.worker_model == "gpt-5.4-mini"
    assert policy.metadata_defaults()["delegation_mode"] == "bounded_worker"
    assert (
        policy.metadata_defaults()["delegation_contract"]
        == "bounded_code_writing_v1"
    )


@pytest.mark.asyncio
async def test_orchestrator_records_enabled_model_policy_defaults_on_dispatch(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "fix bug",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "god_prompts").mkdir()
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec", encoding="utf-8")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review", encoding="utf-8")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        model_policy=CodexModelPolicy.tiered(),
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock):
        await orch.dispatch_lane("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["model_policy_runtime"] == "codex"
    assert lane["model_policy_enabled"] is True
    assert lane["review_model"] == "gpt-5.4"
    assert lane["coordinator_model"] == "gpt-5.4"
    assert lane["worker_model"] == "gpt-5.4-mini"
    assert lane["delegation_mode"] == "bounded_worker"
    assert lane["delegation_contract"] == "bounded_code_writing_v1"


@pytest.mark.asyncio
async def test_orchestrator_sends_tiered_coordinator_command_and_worker_target_metadata(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-tiered-command",
                        "status": "pending",
                        "prompt": "fix the runner model wiring",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "god_prompts").mkdir()
    (tmp_path / "god_prompts" / "execution_god.md").write_text(
        "execution skill",
        encoding="utf-8",
    )
    (tmp_path / "god_prompts" / "review_god.md").write_text("review", encoding="utf-8")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        model_policy=CodexModelPolicy.tiered(),
    )
    captured: dict[str, object] = {}

    async def fake_send_execute(req):
        captured["model"] = req.god_config.model
        captured["worker_model"] = req.god_config.worker_model
        captured["delegation_mode"] = req.god_config.delegation_mode
        captured["prompt"] = req.prompt
        return ExecuteResponse(exit_code=1, stdout="", stderr="", timed_out=False)

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        await orch.dispatch_lane("lane-tiered-command")

    assert captured["model"] == "gpt-5.4"
    assert captured["worker_model"] == "gpt-5.4-mini"
    assert captured["delegation_mode"] == "bounded_worker"
    assert "- coordinator_model: gpt-5.4" in str(captured["prompt"])
    assert "- worker_model: gpt-5.4-mini" in str(captured["prompt"])
    assert "- delegation_mode: bounded_worker" in str(captured["prompt"])
    assert "## Bounded Worker Delegation Contract" in str(captured["prompt"])
    assert "delegate bounded code-writing work" in str(captured["prompt"])
    assert "collect diffs, changed files, tests run, and summaries" in str(
        captured["prompt"]
    )
    assert "do not choose other runtimes or autonomously optimize model/cost" in str(
        captured["prompt"]
    )


@pytest.mark.asyncio
async def test_orchestrator_records_worker_failure_layer_for_bounded_worker_failure(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-worker-failure",
                        "status": "pending",
                        "prompt": "fix the worker path",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "god_prompts").mkdir()
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec", encoding="utf-8")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review", encoding="utf-8")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        model_policy=CodexModelPolicy.tiered(),
    )

    async def fake_send_execute(_req):
        return ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="worker failed",
            timed_out=False,
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        await orch.dispatch_lane("lane-worker-failure")

    lane = orch._sm.get_lane("lane-worker-failure")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "non_zero_exit"
    assert lane["failure_layer"] == "worker"


@pytest.mark.asyncio
async def test_orchestrator_records_coordinator_failure_layer_for_spawn_failure(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-coordinator-failure",
                        "status": "pending",
                        "prompt": "fix the coordinator path",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "god_prompts").mkdir()
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec", encoding="utf-8")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review", encoding="utf-8")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def fake_send_execute(_req):
        raise RuntimeError("coordinator spawn failed")

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        await orch.dispatch_lane("lane-coordinator-failure")

    lane = orch._sm.get_lane("lane-coordinator-failure")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "execution_spawn_failed"
    assert lane["failure_layer"] == "coordinator"


@pytest.mark.asyncio
async def test_orchestrator_records_review_failure_layer(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-review-failure",
                        "status": "gated",
                        "prompt": "review this lane",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "god_prompts").mkdir()
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec", encoding="utf-8")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review", encoding="utf-8")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def fake_send_review(_req):
        return ReviewVerdict(
            passed=False,
            verdict="",
            feedback="review failed",
            raw_output="",
            exit_code=1,
        )

    with patch.object(orch._transport, "send_review", new=fake_send_review):
        await orch._run_review_god("lane-review-failure")

    lane = orch._sm.get_lane("lane-review-failure")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_non_zero_exit"
    assert lane["failure_layer"] == "review"


def test_persistent_execute_prompt_honors_legacy_single_agent_delegation_mode() -> None:
    prompt = _persistent_execute_prompt(
        "Implement the lane.",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
            model="gpt-5.4",
            worker_model="gpt-5.4-mini",
            delegation_mode="legacy_single_agent",
        ),
        execute_request_id="execute-req-1",
        identity_key="conv-1:execute-peer-1",
        execute_peer_contract=ExecutePeerContract(
            execute_peer_id="execute-peer-1",
            request_id="execute-peer-req-1",
        ),
    )

    assert "- delegation_mode: legacy_single_agent" in prompt
    assert "temporary_child_worker" not in prompt


def test_persistent_execute_prompt_honors_bounded_worker_delegation_mode() -> None:
    prompt = _persistent_execute_prompt(
        "Implement the lane.",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
            model="gpt-5.4",
            worker_model="gpt-5.4-mini",
            delegation_mode="bounded_worker",
        ),
        execute_request_id="execute-req-1",
        identity_key="conv-1:execute-peer-1",
        execute_peer_contract=ExecutePeerContract(
            execute_peer_id="execute-peer-1",
            request_id="execute-peer-req-1",
        ),
    )

    assert "- delegation_mode: bounded_worker" in prompt
    assert "## Bounded Worker Delegation Contract" in prompt
    assert "temporary_child_worker" in prompt
    assert "worker_model gpt-5.4-mini" in prompt
    assert "collect diffs, changed files, tests run, and summaries" in prompt
    assert "do not choose other runtimes or autonomously optimize model/cost" in prompt


def test_persistent_execute_prompt_preserves_unset_delegation_default() -> None:
    prompt = _persistent_execute_prompt(
        "Implement the lane.",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
        ),
        execute_request_id="execute-req-1",
        identity_key="conv-1:execute-peer-1",
        execute_peer_contract=ExecutePeerContract(
            execute_peer_id="execute-peer-1",
            request_id="execute-peer-req-1",
        ),
    )

    assert "temporary_child_worker" not in prompt
