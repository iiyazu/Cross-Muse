from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xmuse_core.providers.adapters.base import ProviderFailureKind, ProviderInvocation
from xmuse_core.providers.adapters.opencode import OpenCodeProviderAdapter
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.health import ProviderHealthFailureKind
from xmuse_core.providers.models import RiskTier, TaskCapability
from xmuse_core.providers.registry import (
    DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME,
    DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME,
    build_default_provider_registry,
)


def _build_adapter(
    *,
    env: dict[str, str] | None = None,
    runner=None,
) -> OpenCodeProviderAdapter:
    profile = build_default_provider_registry().get("opencode.deepseek_flash_worker")
    return OpenCodeProviderAdapter(
        profile,
        env=env,
        runner=runner,
        checked_at_factory=lambda: datetime(2026, 5, 31, 13, 0, tzinfo=UTC),
    )


def _build_invocation(tmp_path, *, model_id: str = "deepseek-v4-flash") -> ProviderInvocation:
    profile = build_default_provider_registry(
        opencode_deepseek_model_id=model_id,
    ).get("opencode.deepseek_flash_worker")
    return ProviderInvocation(
        request_id="req-opencode-123",
        provider_id=profile.provider_id,
        profile_id=profile.profile_id,
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Summarize the provider contract.",
        workspace=tmp_path,
        timeout_seconds=120,
    )


def test_opencode_adapter_builds_non_interactive_run_command(tmp_path) -> None:
    invocation = _build_invocation(tmp_path, model_id="deepseek-v4-pro")
    profile = build_default_provider_registry(
        opencode_deepseek_model_id="deepseek-v4-pro",
    ).get("opencode.deepseek_flash_worker")
    adapter = OpenCodeProviderAdapter(profile)

    command = adapter.build_command(invocation)

    assert command == [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(tmp_path),
        "--model",
        "deepseek/deepseek-v4-pro",
        "Summarize the provider contract.",
    ]


def test_opencode_adapter_builds_inline_config_env_without_embedding_secrets() -> None:
    adapter = _build_adapter()

    env = adapter.build_env(
        {
            "PATH": "/usr/bin",
            "DEEPSEEK_API_KEY": "sk-secret",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/beta",
        }
    )
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])

    assert env["DEEPSEEK_MODEL"] == "deepseek-v4-flash"
    assert env["DEEPSEEK_API_KEY"] == "sk-secret"
    assert "sk-secret" not in env["OPENCODE_CONFIG_CONTENT"]
    assert config == {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "deepseek": {
                "options": {
                    "apiKey": "{env:DEEPSEEK_API_KEY}",
                    "baseURL": "{env:DEEPSEEK_BASE_URL}",
                }
            }
        },
    }


def test_opencode_adapter_reports_missing_required_env_vars() -> None:
    adapter = _build_adapter()

    assert adapter.missing_env_requirements({}) == ("DEEPSEEK_API_KEY",)
    assert adapter.missing_env_requirements({"DEEPSEEK_API_KEY": "  "}) == (
        "DEEPSEEK_API_KEY",
    )
    assert adapter.missing_env_requirements({"DEEPSEEK_API_KEY": "sk-ready"}) == ()


def test_opencode_health_check_reports_missing_required_env_as_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME, raising=False)
    adapter = _build_adapter(env={})

    snapshot = adapter.check_health()

    assert snapshot.failure_kind is ProviderHealthFailureKind.CONFIG_ERROR
    assert snapshot.is_available is False
    assert snapshot.is_configured is False
    assert snapshot.auth_ok is False
    assert snapshot.model_available is False
    assert DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME in (snapshot.diagnostic_summary or "")


def test_opencode_health_check_reports_ready_snapshot_when_smoke_succeeds() -> None:
    def runner(*, command, env, timeout_seconds):
        assert command == (
            "opencode",
            "run",
            "--format",
            "json",
            "--dir",
            str(Path.cwd()),
            "--model",
            "deepseek/deepseek-v4-flash",
            (
                "Run a non-mutating provider health smoke check. Do not edit files. "
                "Reply with READY."
            ),
        )
        assert env[DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME] == "sk-test"
        assert env[DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME] == "https://api.deepseek.com"
        assert timeout_seconds == 30
        return subprocess.CompletedProcess(command, 0, stdout="READY\n", stderr="")

    adapter = _build_adapter(
        env={
            DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME: "sk-test",
            DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME: "https://api.deepseek.com",
        },
        runner=runner,
    )

    snapshot = adapter.check_health()

    assert snapshot.failure_kind is None
    assert snapshot.is_available is True
    assert snapshot.is_configured is True
    assert snapshot.auth_ok is True
    assert snapshot.model_available is True


def test_opencode_health_check_uses_default_subprocess_runner_without_workspace_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        command,
        *,
        capture_output,
        text,
        env,
        cwd,
        timeout,
        check,
    ):
        assert command[:4] == (
            "opencode",
            "run",
            "--format",
            "json",
        )
        assert command[4:8] == (
            "--dir",
            str(Path.cwd()),
            "--model",
            "deepseek/deepseek-v4-flash",
        )
        assert env[DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME] == "sk-test"
        assert env[DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME] == "https://api.deepseek.com"
        assert cwd is None
        assert capture_output is True
        assert text is True
        assert timeout == 30
        assert check is False
        return subprocess.CompletedProcess(command, 0, stdout="READY\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter = _build_adapter(
        env={
            DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME: "sk-test",
            DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME: "https://api.deepseek.com",
        },
    )

    snapshot = adapter.check_health()

    assert snapshot.failure_kind is None
    assert snapshot.is_available is True
    assert snapshot.is_configured is True
    assert snapshot.auth_ok is True
    assert snapshot.model_available is True


def test_opencode_invoke_maps_unrecognized_non_zero_exit_to_worker_failure(
    tmp_path: Path,
) -> None:
    def runner(*, command, env, timeout_seconds, cwd):
        assert command == tuple(
            _build_adapter(
                env={DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME: "sk-test"}
            ).build_command(_build_invocation(tmp_path))
        )
        assert cwd == tmp_path
        assert timeout_seconds == 120
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="tests failed")

    adapter = _build_adapter(
        env={DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME: "sk-test"},
        runner=runner,
    )

    result = adapter.invoke(_build_invocation(tmp_path))

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.NON_ZERO_EXIT


@pytest.mark.parametrize(
    ("runner", "failure_kind", "expected_flags"),
    [
        (
            lambda **_: (_ for _ in ()).throw(FileNotFoundError("opencode not installed")),
            ProviderHealthFailureKind.UNAVAILABLE,
            {
                "is_available": False,
                "is_configured": True,
                "auth_ok": True,
                "model_available": True,
            },
        ),
        (
            lambda **_: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(cmd=("opencode", "run"), timeout=30)
            ),
            ProviderHealthFailureKind.TIMEOUT,
            {
                "is_available": False,
                "is_configured": True,
                "auth_ok": True,
                "model_available": True,
            },
        ),
        (
            lambda **_: subprocess.CompletedProcess(
                ("opencode", "run"),
                1,
                stdout="",
                stderr="401 unauthorized: invalid api key",
            ),
            ProviderHealthFailureKind.AUTH_ERROR,
            {
                "is_available": False,
                "is_configured": True,
                "auth_ok": False,
                "model_available": True,
            },
        ),
        (
            lambda **_: subprocess.CompletedProcess(
                ("opencode", "run"),
                1,
                stdout="",
                stderr="model deepseek-v4-flash not found",
            ),
            ProviderHealthFailureKind.MODEL_UNAVAILABLE,
            {
                "is_available": False,
                "is_configured": True,
                "auth_ok": True,
                "model_available": False,
            },
        ),
        (
            lambda **_: subprocess.CompletedProcess(
                ("opencode", "run"),
                1,
                stdout="",
                stderr="unsupported capability: one-shot json output",
            ),
            ProviderHealthFailureKind.UNSUPPORTED_CAPABILITY,
            {
                "is_available": False,
                "is_configured": True,
                "auth_ok": True,
                "model_available": True,
            },
        ),
    ],
)
def test_opencode_health_check_classifies_expected_smoke_failures(
    runner,
    failure_kind: ProviderHealthFailureKind,
    expected_flags: dict[str, bool],
) -> None:
    adapter = _build_adapter(
        env={DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME: "sk-test"},
        runner=runner,
    )

    snapshot = adapter.check_health()

    assert snapshot.failure_kind is failure_kind
    assert snapshot.is_available is expected_flags["is_available"]
    assert snapshot.is_configured is expected_flags["is_configured"]
    assert snapshot.auth_ok is expected_flags["auth_ok"]
    assert snapshot.model_available is expected_flags["model_available"]
