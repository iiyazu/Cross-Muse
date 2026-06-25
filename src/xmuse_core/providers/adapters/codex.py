from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.protocol import AgentOutput, StdoutMessage
from xmuse_core.providers.adapters.base import (
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.goal_contract import (
    WorkerGoalContract,
    WorkerGoalResult,
    WorkerResultStatus,
)
from xmuse_core.providers.health import ProviderHealthSnapshot
from xmuse_core.providers.models import (
    ProviderProfile,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)
from xmuse_core.providers.registry import (
    build_default_provider_registry,
    normalize_codex_model_id,
)
from xmuse_core.structuring.feature_review_contracts import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_text_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text is not None:
            cleaned.append(text)
    return cleaned


def _is_explicit_provider_session_id(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized not in {"last", "--last", "latest", "--latest"}


def _extract_session_id_from_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("session_id", "sessionId", "id"):
        value = _clean_text(payload.get(key))
        if value is not None and _is_explicit_provider_session_id(value):
            return value
    for key in ("session", "session_meta", "sessionMeta"):
        nested = payload.get(key)
        found = _extract_session_id_from_payload(nested)
        if found is not None:
            return found
    return None


def extract_codex_provider_session_id(stdout: str) -> str | None:
    """Extract an explicit Codex provider session id from JSON event output."""

    for line in stdout.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        found = _extract_session_id_from_payload(payload)
        if found is not None:
            return found
    return None


@dataclass
class CodexProviderAdapter:
    mcp_port: int = 8100
    model: str | None = None
    profile_id: ProviderProfileId = ProviderProfileId.DEFAULT
    codex_command: str = "codex"
    persistent_module: str = "xmuse_core.agents.codex_persistent"
    profile: ProviderProfile = field(init=False)

    def __post_init__(self) -> None:
        registry = build_default_provider_registry()
        base_profile = registry.get(f"codex.{self.profile_id.value}")
        self.profile = self._resolve_profile(base_profile)
        self.model = self.profile.model_id

    def _resolve_profile(self, base_profile: ProviderProfile) -> ProviderProfile:
        resolved_model = normalize_codex_model_id(
            self.model,
            profile_id=base_profile.profile_id,
            allow_final_quality=base_profile.profile_id is ProviderProfileId.FINAL_QUALITY,
        )
        if resolved_model == base_profile.model_id:
            return base_profile
        return base_profile.model_copy(update={"model_id": resolved_model})

    def build_invocation(
        self,
        *,
        request_id: str,
        task_type: TaskCapability,
        risk_tier: RiskTier,
        prompt: str,
        workspace: Path,
        timeout_seconds: int,
        goal_contract: WorkerGoalContract | None = None,
    ) -> ProviderInvocation:
        return ProviderInvocation(
            request_id=request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            task_type=task_type,
            risk_tier=risk_tier,
            prompt=prompt,
            workspace=workspace,
            timeout_seconds=timeout_seconds,
            goal_contract=goal_contract,
        )

    def build_command(self, worktree: Path) -> list[str]:
        return [
            self.codex_command,
            "exec",
            "--ignore-user-config",
            "-m",
            self.profile.model_id,
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            'mcp_servers.xmuse-platform.type="sse"',
            "-c",
            f'mcp_servers.xmuse-platform.url="http://localhost:{self.mcp_port}/sse"',
            "-C",
            str(worktree),
        ]

    def build_resume_command(
        self,
        *,
        worktree: Path,
        provider_session_id: str,
    ) -> list[str]:
        cleaned_session_id = _clean_text(provider_session_id)
        if cleaned_session_id is None or not _is_explicit_provider_session_id(
            cleaned_session_id
        ):
            raise ValueError(
                "provider_session_id must be explicit; "
                "last-session aliases are forbidden"
            )
        return [
            self.codex_command,
            "exec",
            "resume",
            "--ignore-user-config",
            cleaned_session_id,
            "-m",
            self.profile.model_id,
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            'mcp_servers.xmuse-platform.type="sse"',
            "-c",
            f'mcp_servers.xmuse-platform.url="http://localhost:{self.mcp_port}/sse"',
            "-C",
            str(worktree),
        ]

    def build_command_for_invocation(
        self,
        invocation: ProviderInvocation,
        *,
        provider_session_binding: ProviderSessionBindingRecord | None = None,
    ) -> list[str]:
        self._validate_invocation(invocation)
        if provider_session_binding is not None:
            self._validate_resume_binding(provider_session_binding, invocation)
            return self.build_resume_command(
                worktree=invocation.workspace,
                provider_session_id=provider_session_binding.provider_session_id,
            )
        return self.build_command(invocation.workspace)

    def _validate_resume_binding(
        self,
        binding: ProviderSessionBindingRecord,
        invocation: ProviderInvocation,
    ) -> None:
        validated = ProviderSessionBindingRecord.model_validate(
            binding.model_dump(mode="json")
        )
        if validated.provider != "codex":
            raise ValueError("Codex resume binding must use provider=codex")
        expected_session_kind = (
            "review"
            if invocation.task_type is TaskCapability.REVIEW
            else "exec"
        )
        if validated.session_kind != expected_session_kind:
            raise ValueError(
                "Codex resume binding must use "
                f"session_kind={expected_session_kind}"
            )
        if validated.status is not ProviderSessionBindingStatus.ACTIVE:
            raise ValueError("Codex resume binding must be active")
        if validated.model is not None and validated.model != self.profile.model_id:
            raise ValueError("Codex resume binding model must match adapter profile")
        if validated.worktree is not None and validated.worktree != str(invocation.workspace):
            raise ValueError("Codex resume binding worktree must match invocation workspace")

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            self.persistent_module,
            "--model",
            self.profile.model_id,
            "--mcp-port",
            str(self.mcp_port),
            "--worktree",
            str(worktree),
            "--role",
            role,
        ]

    def build_env(self, feature_id: str) -> dict[str, str]:
        env = dict(os.environ)
        env["XMUSE_FEATURE_ID"] = feature_id
        return env

    def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult:
        self._validate_invocation(invocation)
        feature_id = (
            invocation.goal_contract.lane_id
            if invocation.goal_contract is not None
            else invocation.request_id
        )
        try:
            completed = subprocess.run(
                self.build_command_for_invocation(invocation),
                input=invocation.prompt,
                capture_output=True,
                text=True,
                cwd=invocation.workspace,
                env=self.build_env(feature_id),
                timeout=invocation.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=self.profile.provider_id,
                profile_id=self.profile.profile_id,
                status=WorkerResultStatus.FAILED,
                evidence_refs=[],
                failure_kind=ProviderFailureKind.TIMEOUT,
            )
        except FileNotFoundError:
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=self.profile.provider_id,
                profile_id=self.profile.profile_id,
                status=WorkerResultStatus.FAILED,
                evidence_refs=[],
                failure_kind=ProviderFailureKind.UNAVAILABLE,
            )
        except OSError:
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=self.profile.provider_id,
                profile_id=self.profile.profile_id,
                status=WorkerResultStatus.FAILED,
                evidence_refs=[],
                failure_kind=ProviderFailureKind.TRANSPORT_CRASH,
            )

        if completed.returncode == 0:
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=self.profile.provider_id,
                profile_id=self.profile.profile_id,
                status=WorkerResultStatus.COMPLETED,
                provider_session_id=extract_codex_provider_session_id(completed.stdout),
                evidence_refs=[],
            )

        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=WorkerResultStatus.FAILED,
            evidence_refs=[],
            failure_kind=ProviderFailureKind.NON_ZERO_EXIT,
        )

    def build_result_from_output(
        self,
        invocation: ProviderInvocation,
        output: AgentOutput,
    ) -> ProviderInvocationResult:
        self._validate_invocation(invocation)
        worker_result = self._extract_worker_result(output.artifacts)
        status = self._resolve_worker_status(output.status, worker_result)
        failure_kind = self._resolve_failure_kind(output.status, output.error_code)
        changed_files, tests_run, evidence_refs = self._resolve_result_lists(
            output.artifacts,
            worker_result,
        )
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=status,
            stdout_ref=_clean_text(output.artifacts.get("stdout_ref")),
            stderr_ref=_clean_text(output.artifacts.get("stderr_ref")),
            provider_session_id=self._extract_provider_session_id(output.artifacts),
            worker_result=worker_result,
            changed_files=changed_files,
            tests_run=tests_run,
            evidence_refs=evidence_refs,
            failure_kind=failure_kind,
        )

    def build_result_from_message(
        self,
        invocation: ProviderInvocation,
        msg: StdoutMessage,
    ) -> ProviderInvocationResult | None:
        if msg.type == "result":
            return self.build_result_from_output(
                invocation,
                AgentOutput(status=msg.status or "success", artifacts=msg.artifacts),
            )
        if msg.type == "error":
            return self.build_result_from_output(
                invocation,
                AgentOutput(
                    status="error",
                    artifacts=msg.artifacts,
                    error_code=msg.code,
                    error_message=msg.message,
                ),
            )
        return None

    def check_health(self) -> ProviderHealthSnapshot:
        command_path = shutil.which(self.codex_command)
        is_available = command_path is not None
        diagnostic_summary = (
            f"{self.codex_command} CLI is ready"
            if is_available
            else f"{self.codex_command} CLI is not installed"
        )
        return ProviderHealthSnapshot(
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            checked_at=datetime.now(UTC),
            is_available=is_available,
            is_configured=is_available,
            auth_ok=True,
            model_available=is_available,
            diagnostic_summary=diagnostic_summary,
        )

    def _validate_invocation(self, invocation: ProviderInvocation) -> None:
        if (
            invocation.provider_id is not self.profile.provider_id
            or invocation.profile_id is not self.profile.profile_id
        ):
            raise ValueError("provider/profile must match the codex adapter profile")
        if invocation.task_type not in self.profile.task_capabilities:
            raise ValueError("task capability is not supported by the codex adapter profile")

    def _extract_worker_result(self, artifacts: dict[str, Any]) -> WorkerGoalResult | None:
        payload = artifacts.get("worker_result")
        if payload is None:
            return None
        if isinstance(payload, WorkerGoalResult):
            return payload
        return WorkerGoalResult.model_validate(payload)

    def _extract_provider_session_id(self, artifacts: dict[str, Any]) -> str | None:
        explicit = _clean_text(artifacts.get("provider_session_id"))
        if explicit is not None:
            if not _is_explicit_provider_session_id(explicit):
                raise ValueError(
                    "provider_session_id must be explicit; "
                    "last-session aliases are forbidden"
                )
            return explicit
        stdout = _clean_text(artifacts.get("stdout"))
        if stdout is None:
            return None
        return extract_codex_provider_session_id(stdout)

    def _resolve_result_lists(
        self,
        artifacts: dict[str, Any],
        worker_result: WorkerGoalResult | None,
    ) -> tuple[list[str], list[str], list[str]]:
        changed_files = _clean_text_list(artifacts.get("changed_files"))
        tests_run = _clean_text_list(artifacts.get("tests_run"))
        evidence_refs = _clean_text_list(artifacts.get("evidence_refs"))
        if worker_result is not None:
            if not changed_files:
                changed_files = list(worker_result.changed_files)
            if not tests_run:
                tests_run = list(worker_result.tests_run)
            if not evidence_refs:
                evidence_refs = list(worker_result.evidence_refs)
        return changed_files, tests_run, evidence_refs

    def _resolve_worker_status(
        self,
        status_text: str,
        worker_result: WorkerGoalResult | None,
    ) -> WorkerResultStatus:
        normalized = status_text.strip().lower()
        if normalized in {"success", "completed"}:
            return WorkerResultStatus.COMPLETED
        if normalized == "blocked":
            return WorkerResultStatus.BLOCKED
        if normalized in {"", "unknown"} and worker_result is not None:
            return worker_result.status
        return WorkerResultStatus.FAILED

    def _resolve_failure_kind(
        self,
        status_text: str,
        error_code: str | None,
    ) -> ProviderFailureKind | None:
        normalized_status = status_text.strip().lower()
        if normalized_status in {"success", "completed", "blocked"}:
            return None
        if normalized_status == "timeout":
            return ProviderFailureKind.TIMEOUT
        normalized_error_code = (error_code or "").strip().lower()
        if not normalized_error_code:
            return ProviderFailureKind.TRANSPORT_CRASH
        if normalized_error_code in {
            ProviderFailureKind.UNAVAILABLE.value,
            ProviderFailureKind.AUTH_ERROR.value,
            ProviderFailureKind.CONFIG_ERROR.value,
            ProviderFailureKind.TIMEOUT.value,
            ProviderFailureKind.TRANSPORT_CRASH.value,
            ProviderFailureKind.NON_ZERO_EXIT.value,
            ProviderFailureKind.UNSUPPORTED_CAPABILITY.value,
            ProviderFailureKind.MODEL_UNAVAILABLE.value,
            ProviderFailureKind.CONTRACT_VIOLATION.value,
            ProviderFailureKind.STALE_REQUEST.value,
        }:
            return ProviderFailureKind(normalized_error_code)
        if normalized_error_code.startswith("exit_") or normalized_error_code.startswith(
            "codex_exit_"
        ):
            return ProviderFailureKind.NON_ZERO_EXIT
        return ProviderFailureKind.TRANSPORT_CRASH
