from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.providers.adapters.base import (
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.health import (
    MAX_DIAGNOSTIC_SUMMARY_LENGTH,
    ProviderHealthFailureKind,
    ProviderHealthSnapshot,
)
from xmuse_core.providers.models import AdapterKind, ProviderId, ProviderProfile

OPENCODE_CONFIG_CONTENT_ENV_NAME = "OPENCODE_CONFIG_CONTENT"
OPENCODE_EXECUTABLE = "opencode"
OPENCODE_RUN_PROVIDER_NAME = "deepseek"
OPENCODE_CONFIG_SCHEMA_URL = "https://opencode.ai/config.json"
HEALTH_CHECK_TIMEOUT_SECONDS = 30
_HEALTH_PROMPT = (
    "Run a non-mutating provider health smoke check. Do not edit files. "
    "Reply with READY."
)

_HEALTH_FLAGS_BY_FAILURE_KIND: dict[
    ProviderHealthFailureKind,
    tuple[bool, bool, bool, bool],
] = {
    ProviderHealthFailureKind.UNAVAILABLE: (False, True, True, True),
    ProviderHealthFailureKind.AUTH_ERROR: (False, True, False, True),
    ProviderHealthFailureKind.CONFIG_ERROR: (False, False, False, False),
    ProviderHealthFailureKind.TIMEOUT: (False, True, True, True),
    ProviderHealthFailureKind.MODEL_UNAVAILABLE: (False, True, True, False),
    ProviderHealthFailureKind.UNSUPPORTED_CAPABILITY: (False, True, True, True),
}


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


class OpenCodeProviderAdapter:
    def __init__(
        self,
        profile: ProviderProfile,
        *,
        env: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        checked_at_factory: Callable[[], datetime] | None = None,
        opencode_binary: str = OPENCODE_EXECUTABLE,
    ) -> None:
        if profile.provider_id is not ProviderId.OPENCODE:
            raise ValueError("OpenCodeProviderAdapter requires an opencode profile")
        if profile.adapter_kind is not AdapterKind.OPENCODE_CLI:
            raise ValueError("OpenCodeProviderAdapter requires an opencode_cli profile")
        if profile.model_id_env_name is None:
            raise ValueError("OpenCodeProviderAdapter requires profile.model_id_env_name")
        self.profile = profile
        self._env = dict(env or {})
        self._runner = runner or _run_subprocess
        self._checked_at_factory = checked_at_factory or (lambda: datetime.now(UTC))
        self._opencode_binary = opencode_binary

    @property
    def model_ref(self) -> str:
        return f"{OPENCODE_RUN_PROVIDER_NAME}/{self.profile.model_id}"

    def build_command(self, invocation: ProviderInvocation) -> list[str]:
        self._validate_invocation(invocation)
        return list(self._build_run_command(invocation.prompt, invocation.workspace))

    def _build_run_command(self, prompt: str, workspace: Path) -> tuple[str, ...]:
        return (
            self._opencode_binary,
            "run",
            "--format",
            "json",
            "--dir",
            str(workspace),
            "--model",
            self.model_ref,
            prompt,
        )

    def build_env(self, env: Mapping[str, str] | None = None) -> dict[str, str]:
        runtime_env = dict(env or {})
        runtime_env[self.profile.model_id_env_name] = self.profile.model_id
        runtime_env[OPENCODE_CONFIG_CONTENT_ENV_NAME] = json.dumps(
            self._build_inline_config(runtime_env),
            separators=(",", ":"),
            sort_keys=True,
        )
        return runtime_env

    def missing_env_requirements(
        self,
        env: Mapping[str, str] | None = None,
    ) -> tuple[str, ...]:
        runtime_env = env or {}
        return tuple(
            env_name
            for env_name in self.profile.env_requirement_names
            if not _has_text(runtime_env.get(env_name))
        )

    def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult:
        if (
            invocation.provider_id is not self.profile.provider_id
            or invocation.profile_id is not self.profile.profile_id
        ):
            return self._build_failure_result(
                invocation=invocation,
                failure_kind=ProviderFailureKind.CONTRACT_VIOLATION,
            )

        if invocation.task_type not in self.profile.task_capabilities:
            return self._build_failure_result(
                invocation=invocation,
                failure_kind=ProviderFailureKind.UNSUPPORTED_CAPABILITY,
            )

        preflight_failure = self._preflight_snapshot()
        if preflight_failure is not None:
            return self._build_failure_result(
                invocation=invocation,
                failure_kind=_to_provider_failure_kind(preflight_failure.failure_kind),
            )

        try:
            completed_process = self._run_command(
                command=tuple(self.build_command(invocation)),
                timeout_seconds=invocation.timeout_seconds,
                cwd=Path(invocation.workspace),
            )
        except FileNotFoundError:
            return self._build_failure_result(
                invocation=invocation,
                failure_kind=ProviderFailureKind.UNAVAILABLE,
            )
        except subprocess.TimeoutExpired:
            return self._build_failure_result(
                invocation=invocation,
                failure_kind=ProviderFailureKind.TIMEOUT,
            )

        if completed_process.returncode != 0:
            return self._build_failure_result(
                invocation=invocation,
                failure_kind=_classify_invocation_failure(completed_process),
            )

        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=WorkerResultStatus.COMPLETED,
        )

    def check_health(self) -> ProviderHealthSnapshot:
        checked_at = self._checked_at_factory()

        preflight_failure = self._preflight_snapshot(checked_at=checked_at)
        if preflight_failure is not None:
            return preflight_failure

        try:
            completed_process = self._run_command(
                command=self._build_health_command(),
                timeout_seconds=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            return self._build_health_snapshot(
                checked_at=checked_at,
                failure_kind=ProviderHealthFailureKind.UNAVAILABLE,
                diagnostic_summary=str(exc),
            )
        except subprocess.TimeoutExpired as exc:
            return self._build_health_snapshot(
                checked_at=checked_at,
                failure_kind=ProviderHealthFailureKind.TIMEOUT,
                diagnostic_summary=str(exc),
            )

        if completed_process.returncode == 0:
            return ProviderHealthSnapshot(
                provider_id=self.profile.provider_id,
                profile_id=self.profile.profile_id,
                checked_at=checked_at,
                is_available=True,
                is_configured=True,
                auth_ok=True,
                model_available=True,
            )

        return self._build_health_snapshot(
            checked_at=checked_at,
            failure_kind=_classify_health_failure(completed_process),
            diagnostic_summary=_command_summary(completed_process),
        )

    def _validate_invocation(self, invocation: ProviderInvocation) -> None:
        if (
            invocation.provider_id is not self.profile.provider_id
            or invocation.profile_id is not self.profile.profile_id
        ):
            raise ValueError("invocation provider/profile must match adapter profile")

    def _build_inline_config(self, env: Mapping[str, str]) -> dict[str, object]:
        options: dict[str, str] = {
            "apiKey": f"{{env:{self._api_key_env_name()}}}",
        }
        if self.profile.api_base_env_name and _has_text(env.get(self.profile.api_base_env_name)):
            options["baseURL"] = f"{{env:{self.profile.api_base_env_name}}}"
        return {
            "$schema": OPENCODE_CONFIG_SCHEMA_URL,
            "provider": {
                OPENCODE_RUN_PROVIDER_NAME: {
                    "options": options,
                }
            },
        }

    def _api_key_env_name(self) -> str:
        if not self.profile.env_requirement_names:
            raise ValueError("OpenCodeProviderAdapter requires an API key env requirement")
        return self.profile.env_requirement_names[0]

    def _preflight_snapshot(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> ProviderHealthSnapshot | None:
        missing = _missing_required_env(
            self.profile.env_requirement_names,
            self._build_command_env(),
        )
        if not missing:
            return None
        summary = "Missing required provider environment: " + ", ".join(missing) + "."
        return self._build_health_snapshot(
            checked_at=checked_at or self._checked_at_factory(),
            failure_kind=ProviderHealthFailureKind.CONFIG_ERROR,
            diagnostic_summary=summary,
        )

    def _build_health_snapshot(
        self,
        *,
        checked_at: datetime,
        failure_kind: ProviderHealthFailureKind,
        diagnostic_summary: str | None = None,
    ) -> ProviderHealthSnapshot:
        is_available, is_configured, auth_ok, model_available = (
            _HEALTH_FLAGS_BY_FAILURE_KIND[failure_kind]
        )
        return ProviderHealthSnapshot(
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            checked_at=checked_at,
            is_available=is_available,
            is_configured=is_configured,
            auth_ok=auth_ok,
            model_available=model_available,
            failure_kind=failure_kind,
            diagnostic_summary=_bounded_summary(diagnostic_summary),
        )

    def _build_command_env(self) -> dict[str, str]:
        command_env = dict(os.environ)
        command_env.update(self._env)
        return self.build_env(command_env)

    def _run_command(
        self,
        *,
        command: tuple[str, ...],
        timeout_seconds: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        kwargs = {
            "command": command,
            "env": self._build_command_env(),
            "timeout_seconds": timeout_seconds,
        }
        if cwd is not None:
            kwargs["cwd"] = cwd
        return self._runner(**kwargs)

    def _build_health_command(self) -> tuple[str, ...]:
        return self._build_run_command(_HEALTH_PROMPT, Path.cwd())

    def _build_failure_result(
        self,
        *,
        invocation: ProviderInvocation,
        failure_kind: ProviderFailureKind,
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=WorkerResultStatus.FAILED,
            failure_kind=failure_kind,
        )


def _run_subprocess(
    *,
    command: tuple[str, ...],
    env: Mapping[str, str],
    timeout_seconds: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=dict(env),
        cwd=cwd,
        timeout=timeout_seconds,
        check=False,
    )


def _missing_required_env(
    names: tuple[str, ...],
    env: Mapping[str, str],
) -> list[str]:
    return [
        name
        for name in names
        if not isinstance(env.get(name), str) or not env[name].strip()
    ]


def _command_summary(completed_process: subprocess.CompletedProcess[str]) -> str | None:
    return _bounded_summary(
        completed_process.stderr.strip() or completed_process.stdout.strip() or None
    )


def _classify_health_failure(
    completed_process: subprocess.CompletedProcess[str],
) -> ProviderHealthFailureKind:
    summary = _command_summary(completed_process)
    lowered = (summary or "").lower()

    if any(marker in lowered for marker in ("timed out", "timeout", "deadline exceeded")):
        return ProviderHealthFailureKind.TIMEOUT
    if any(
        marker in lowered
        for marker in (
            "missing required provider environment",
            "missing api key",
            "missing configuration",
            "config error",
            "configuration error",
            "must set",
            "not set",
            "deepseek_api_key",
        )
    ):
        return ProviderHealthFailureKind.CONFIG_ERROR
    if any(
        marker in lowered
        for marker in (
            "unauthorized",
            "authentication failed",
            "auth failed",
            "invalid api key",
            "invalid key",
            "forbidden",
            "401",
            "403",
        )
    ):
        return ProviderHealthFailureKind.AUTH_ERROR
    if any(
        marker in lowered
        for marker in (
            "model unavailable",
            "model not found",
            "unknown model",
            "no such model",
            "unsupported model",
            "does not exist",
        )
    ) or ("model" in lowered and "not found" in lowered):
        return ProviderHealthFailureKind.MODEL_UNAVAILABLE
    if any(
        marker in lowered
        for marker in (
            "unsupported capability",
            "does not support",
            "unsupported feature",
            "not implemented",
        )
    ):
        return ProviderHealthFailureKind.UNSUPPORTED_CAPABILITY
    return ProviderHealthFailureKind.UNAVAILABLE


def _to_provider_failure_kind(
    failure_kind: ProviderHealthFailureKind | None,
) -> ProviderFailureKind:
    if failure_kind is None:
        return ProviderFailureKind.UNAVAILABLE
    return ProviderFailureKind(failure_kind.value)


def _classify_invocation_failure(
    completed_process: subprocess.CompletedProcess[str],
) -> ProviderFailureKind:
    failure_kind = _classify_health_failure(completed_process)
    if failure_kind is ProviderHealthFailureKind.UNAVAILABLE:
        return ProviderFailureKind.NON_ZERO_EXIT
    return _to_provider_failure_kind(failure_kind)


def _bounded_summary(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) <= MAX_DIAGNOSTIC_SUMMARY_LENGTH:
        return cleaned
    return cleaned[: MAX_DIAGNOSTIC_SUMMARY_LENGTH - 3].rstrip() + "..."


__all__ = [
    "HEALTH_CHECK_TIMEOUT_SECONDS",
    "OPENCODE_CONFIG_CONTENT_ENV_NAME",
    "OPENCODE_CONFIG_SCHEMA_URL",
    "OPENCODE_EXECUTABLE",
    "OPENCODE_RUN_PROVIDER_NAME",
    "OpenCodeProviderAdapter",
]
