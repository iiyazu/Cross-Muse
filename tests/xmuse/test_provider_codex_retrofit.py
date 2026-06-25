from __future__ import annotations

import subprocess
from pathlib import Path

from xmuse_core.agents.protocol import AgentOutput, StdoutMessage
from xmuse_core.platform.agent_spawner import SpawnResult
from xmuse_core.providers.adapters.base import (
    ProviderAdapter,
    ProviderFailureKind,
    ProviderInvocation,
)
from xmuse_core.providers.adapters.codex import (
    CodexProviderAdapter,
    extract_codex_provider_session_id,
)
from xmuse_core.providers.goal_contract import WorkerGoalResult, WorkerResultStatus
from xmuse_core.providers.models import (
    ProviderId,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.structuring.models import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


def _build_worker_result() -> WorkerGoalResult:
    return WorkerGoalResult(
        request_id="req-123",
        provider_id=ProviderId.CODEX,
        provider_profile_id=ProviderProfileId.DEFAULT,
        status=WorkerResultStatus.COMPLETED,
        changed_files=["src/xmuse_core/providers/adapters/codex.py"],
        tests_run=["uv run pytest tests/xmuse/test_provider_codex_retrofit.py -q"],
        evidence_refs=["artifacts/provider-codex.md"],
        confidence=0.91,
        touched_areas=["src/xmuse_core/providers", "src/xmuse_core/agents/launchers"],
        summary="Retrofit codex launcher behavior through provider contracts.",
    )


def _provider_session_binding(
    *,
    provider: str = "codex",
    session_kind: str = "exec",
    status: ProviderSessionBindingStatus = ProviderSessionBindingStatus.ACTIVE,
    model: str = "gpt-5.4",
    worktree: str,
) -> ProviderSessionBindingRecord:
    return ProviderSessionBindingRecord(
        binding_id="psb-codex-demo",
        god_session_id="god-worker-demo",
        provider=provider,
        provider_session_id="codex-session-11111111-2222-3333-4444-555555555555",
        session_kind=session_kind,
        status=status,
        conversation_id="conv-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
        role="feature_worker",
        cwd="/repo",
        worktree=worktree,
        model=model,
        prompt_fingerprint="sha256:prompt-demo",
        created_at="2026-06-03T02:10:00Z",
        last_used_at="2026-06-03T02:11:00Z",
        last_verified_at="2026-06-03T02:11:30Z",
        resume_command_template="codex exec resume {provider_session_id} {prompt}",
    )


def test_codex_provider_adapter_builds_compatibility_command_from_invocation(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter(mcp_port=8123, model="gpt-5.4")

    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    assert invocation.provider_id is ProviderId.CODEX
    assert invocation.profile_id is ProviderProfileId.DEFAULT
    assert invocation.provider_profile_ref == "codex.default"
    assert adapter.build_command_for_invocation(invocation) == [
        "codex",
        "exec",
        "--ignore-user-config",
        "-m",
        "gpt-5.4",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        'mcp_servers.xmuse-platform.type="sse"',
        "-c",
        'mcp_servers.xmuse-platform.url="http://localhost:8123/sse"',
        "-C",
        str(tmp_path),
    ]
    assert adapter.build_persistent_command("review", tmp_path) == [
        __import__("sys").executable,
        "-m",
        "xmuse_core.agents.codex_persistent",
        "--model",
        "gpt-5.4",
        "--mcp-port",
        "8123",
        "--worktree",
        str(tmp_path),
        "--role",
        "review",
    ]
    assert adapter.build_env("lane-123")["XMUSE_FEATURE_ID"] == "lane-123"


def test_codex_provider_adapter_builds_resume_command_from_active_binding(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter(mcp_port=8123, model="gpt-5.4")
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Continue the feature graph.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    command = adapter.build_command_for_invocation(
        invocation,
        provider_session_binding=_provider_session_binding(worktree=str(tmp_path)),
    )

    assert command[:5] == [
        "codex",
        "exec",
        "resume",
        "--ignore-user-config",
        "codex-session-11111111-2222-3333-4444-555555555555",
    ]
    assert command[-2:] == ["-C", str(tmp_path)]


def test_runner_provider_service_builds_codex_resume_command_from_explicit_binding(
    tmp_path: Path,
) -> None:
    service = RunnerProviderService(mcp_port=8123)
    invocation = service.build_execution_invocation(
        lane_id="lane-1",
        prompt="Continue the feature graph.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="codex.default",
    )

    command = service.build_command(
        invocation,
        model_override="gpt-5.4",
        provider_session_binding=_provider_session_binding(worktree=str(tmp_path)),
    )

    assert command[:5] == [
        "codex",
        "exec",
        "resume",
        "--ignore-user-config",
        "codex-session-11111111-2222-3333-4444-555555555555",
    ]
    assert command[-2:] == ["-C", str(tmp_path)]


def test_runner_provider_service_builds_codex_review_resume_command_from_explicit_binding(
    tmp_path: Path,
) -> None:
    service = RunnerProviderService(mcp_port=8123)
    invocation = service.build_review_invocation(
        lane_id="lane-1",
        prompt="Review the feature graph.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="codex.review",
    )

    command = service.build_command(
        invocation,
        model_override="gpt-5.4",
        provider_session_binding=_provider_session_binding(
            worktree=str(tmp_path),
            session_kind="review",
        ),
    )

    assert command[:5] == [
        "codex",
        "exec",
        "resume",
        "--ignore-user-config",
        "codex-session-11111111-2222-3333-4444-555555555555",
    ]
    assert command[-2:] == ["-C", str(tmp_path)]


def test_runner_provider_service_rejects_binding_for_unsupported_provider(
    tmp_path: Path,
) -> None:
    service = RunnerProviderService(mcp_port=8123)
    invocation = ProviderInvocation(
        request_id="lane-1:execute",
        provider_id=ProviderId.OPENCODE,
        profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Run a low-risk worker.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    try:
        service.build_command(
            invocation,
            provider_session_binding=_provider_session_binding(worktree=str(tmp_path)),
        )
    except ValueError as exc:
        assert "provider session binding is only supported for Codex exec" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("accepted provider session binding for OpenCode")


def test_codex_provider_adapter_rejects_incompatible_resume_binding(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter(mcp_port=8123, model="gpt-5.4")
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Continue the feature graph.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    incompatible_bindings = [
        _provider_session_binding(
            worktree=str(tmp_path),
            provider="opencode",
        ),
        _provider_session_binding(
            worktree=str(tmp_path),
            session_kind="app_server_thread",
        ),
        _provider_session_binding(
            worktree=str(tmp_path),
            status=ProviderSessionBindingStatus.STALE,
        ),
        _provider_session_binding(
            worktree=str(tmp_path),
            model="gpt-5.2-codex",
        ),
        _provider_session_binding(
            worktree="/other/worktree",
        ),
    ]

    for binding in incompatible_bindings:
        try:
            adapter.build_command_for_invocation(
                invocation,
                provider_session_binding=binding,
            )
        except ValueError:
            continue
        raise AssertionError(f"accepted incompatible binding: {binding.model_dump(mode='json')}")


def test_codex_provider_adapter_builds_explicit_resume_command(tmp_path: Path) -> None:
    adapter = CodexProviderAdapter(mcp_port=8123, model="gpt-5.4")

    assert adapter.build_resume_command(
        worktree=tmp_path,
        provider_session_id="codex-session-11111111-2222-3333-4444-555555555555",
    ) == [
        "codex",
        "exec",
        "resume",
        "--ignore-user-config",
        "codex-session-11111111-2222-3333-4444-555555555555",
        "-m",
        "gpt-5.4",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        'mcp_servers.xmuse-platform.type="sse"',
        "-c",
        'mcp_servers.xmuse-platform.url="http://localhost:8123/sse"',
        "-C",
        str(tmp_path),
    ]

    for forbidden in ("--last", "last", "--latest"):
        try:
            adapter.build_resume_command(
                worktree=tmp_path,
                provider_session_id=forbidden,
            )
        except ValueError as exc:
            assert "provider_session_id must be explicit" in str(exc)
        else:  # pragma: no cover - assertion branch
            raise AssertionError(f"accepted forbidden provider session id: {forbidden}")


def test_extract_codex_provider_session_id_from_json_events() -> None:
    stdout = "\n".join(
        [
            '{"type":"session","id":"codex-session-11111111-2222-3333-4444-555555555555"}',
            '{"type":"result","status":"success"}',
        ]
    )

    assert (
        extract_codex_provider_session_id(stdout)
        == "codex-session-11111111-2222-3333-4444-555555555555"
    )


def test_extract_codex_provider_session_id_uses_nested_metadata() -> None:
    stdout = (
        '{"type":"event","session":{"id":'
        '"codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}}\n'
    )

    assert (
        extract_codex_provider_session_id(stdout)
        == "codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )


def test_extract_codex_provider_session_id_rejects_last_alias() -> None:
    assert extract_codex_provider_session_id('{"type":"session","id":"--last"}') is None


def test_codex_provider_adapter_builds_provider_result_from_structured_message(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter()
    worker_result = _build_worker_result()
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    result = adapter.build_result_from_message(
        invocation,
        StdoutMessage(
            type="result",
            status="success",
            artifacts={
                "stdout_ref": "artifacts/stdout.log",
                "worker_result": worker_result.model_dump(mode="python"),
            },
        ),
    )

    assert result is not None
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.stdout_ref == "artifacts/stdout.log"
    assert result.worker_result == worker_result
    assert result.changed_files == worker_result.changed_files
    assert result.tests_run == worker_result.tests_run
    assert result.evidence_refs == worker_result.evidence_refs


def test_codex_provider_adapter_captures_provider_session_id_from_structured_message(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter()
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    result = adapter.build_result_from_message(
        invocation,
        StdoutMessage(
            type="result",
            status="success",
            artifacts={
                "provider_session_id": (
                    "codex-session-11111111-2222-3333-4444-555555555555"
                ),
            },
        ),
    )

    assert result is not None
    assert (
        result.provider_session_id
        == "codex-session-11111111-2222-3333-4444-555555555555"
    )


def test_codex_provider_adapter_invoke_extracts_provider_session_id_from_stdout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter()
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout=(
                '{"type":"session","id":'
                '"codex-session-11111111-2222-3333-4444-555555555555"}\n'
                '{"type":"result","status":"success"}'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = adapter.invoke(invocation)

    assert result.status is WorkerResultStatus.COMPLETED
    assert (
        result.provider_session_id
        == "codex-session-11111111-2222-3333-4444-555555555555"
    )


def test_provider_invocation_result_rejects_last_session_aliases(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter()
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    try:
        adapter.build_result_from_output(
            invocation,
            AgentOutput(
                status="success",
                artifacts={"provider_session_id": "--last"},
            ),
        )
    except ValueError as exc:
        assert "provider_session_id must be explicit" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("accepted last-session alias in provider result")


def test_codex_provider_adapter_maps_agent_output_failures(
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter()
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    timeout_result = adapter.build_result_from_output(
        invocation,
        AgentOutput(
            status="timeout",
            artifacts={"stderr_ref": "artifacts/timeout.stderr.log"},
        ),
    )
    exit_result = adapter.build_result_from_output(
        invocation,
        AgentOutput(
            status="error",
            error_code="codex_exit_2",
            artifacts={"stderr_ref": "artifacts/exit.stderr.log"},
        ),
    )

    assert timeout_result.status is WorkerResultStatus.FAILED
    assert timeout_result.failure_kind is ProviderFailureKind.TIMEOUT
    assert timeout_result.stderr_ref == "artifacts/timeout.stderr.log"
    assert exit_result.status is WorkerResultStatus.FAILED
    assert exit_result.failure_kind is ProviderFailureKind.NON_ZERO_EXIT
    assert exit_result.stderr_ref == "artifacts/exit.stderr.log"


def test_codex_provider_adapter_implements_provider_invoke_compatibility(
    monkeypatch,
    tmp_path: Path,
) -> None:
    adapter = CodexProviderAdapter()
    invocation = adapter.build_invocation(
        request_id="req-123",
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=2,
            stdout="",
            stderr="failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = adapter.invoke(invocation)

    assert isinstance(adapter, ProviderAdapter)
    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.NON_ZERO_EXIT


def test_runner_provider_service_builds_adapter_backed_compatibility_result(
    tmp_path: Path,
) -> None:
    service = RunnerProviderService(mcp_port=8123)
    invocation = service.build_execution_invocation(
        lane_id="lane-1",
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    result = service.build_result_from_spawn_result(
        invocation,
        SpawnResult(
            exit_code=2,
            stdout="",
            stderr="failed",
            stdout_log_path="logs/provider.stdout.log",
            stderr_log_path="logs/provider.stderr.log",
        ),
    )

    assert result.provider_profile_ref == "codex.default"
    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.NON_ZERO_EXIT
    assert result.stderr_ref == "logs/provider.stderr.log"


def test_runner_provider_service_extracts_codex_provider_session_id_from_spawn_stdout(
    tmp_path: Path,
) -> None:
    service = RunnerProviderService(mcp_port=8123)
    invocation = service.build_execution_invocation(
        lane_id="lane-1",
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=120,
    )

    result = service.build_result_from_spawn_result(
        invocation,
        SpawnResult(
            exit_code=0,
            stdout=(
                '{"type":"session","id":'
                '"codex-session-11111111-2222-3333-4444-555555555555"}\n'
                '{"type":"result","status":"success"}'
            ),
            stderr="",
            stdout_log_path="logs/provider.stdout.log",
            stderr_log_path="logs/provider.stderr.log",
        ),
    )

    assert result.status is WorkerResultStatus.COMPLETED
    assert result.stdout_ref == "logs/provider.stdout.log"
    assert (
        result.provider_session_id
        == "codex-session-11111111-2222-3333-4444-555555555555"
    )
