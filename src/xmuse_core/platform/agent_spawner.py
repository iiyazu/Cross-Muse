from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from xmuse_core.observability import current_observability_context
from xmuse_core.providers.adapters.base import ProviderInvocation, ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderProfileId
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    normalize_codex_model_id,
)
from xmuse_core.runtime.child_env import normalize_child_temp_env

if TYPE_CHECKING:
    from xmuse_core.providers.service import RunnerProviderService
    from xmuse_core.structuring.feature_review_contracts import ProviderSessionBindingRecord


@dataclass
class GodConfig:
    name: str
    runtime: str
    timeout_s: int
    skill_prompt_path: str
    model: str | None = None
    worker_model: str | None = None
    delegation_mode: str | None = None

    def __post_init__(self) -> None:
        if self.runtime != "codex":
            return
        if self.model is not None:
            self.model = normalize_codex_model_id(
                self.model,
                profile_id=ProviderProfileId.GOD,
            )
        if self.worker_model is not None:
            self.worker_model = normalize_codex_model_id(
                self.worker_model,
                profile_id=ProviderProfileId.WORKER,
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GodConfig:
        return cls(
            name=data["name"],
            runtime=data["runtime"],
            timeout_s=data["timeout_s"],
            skill_prompt_path=data.get("skill_prompt_path", ""),
            model=data.get("model"),
            worker_model=data.get("worker_model"),
            delegation_mode=data.get("delegation_mode"),
        )


@dataclass
class SpawnResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    process_pid: int | None = None
    memoryos_session_id: str | None = None
    memoryos_context_attached: bool = False
    memoryos_ingested: bool = False
    memoryos_degraded_reason: str | None = None
    provider_result: ProviderInvocationResult | None = None
    provider_profile_ref: str | None = None
    prompt_log_path: str | None = None
    stdout_log_path: str | None = None
    stderr_log_path: str | None = None
    result_log_path: str | None = None


class AgentSpawner:
    def __init__(
        self,
        *,
        repo_root: Path,
        mcp_port: int,
        memoryos_client: Any | None = None,
        provider_service: RunnerProviderService | None = None,
        on_process_start: Callable[[str, int, list[str], Path], None] | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._mcp_port = mcp_port
        self._memoryos_client = memoryos_client
        self._provider_service = provider_service
        self._on_process_start = on_process_start

    def _build_command(
        self,
        god_config: GodConfig,
        worktree: Path,
        *,
        provider_invocation: ProviderInvocation | None = None,
        provider_session_binding: ProviderSessionBindingRecord | None = None,
    ) -> list[str]:
        if provider_invocation is not None and self._provider_service is not None:
            return self._provider_service.build_command(
                provider_invocation,
                model_override=god_config.model,
                provider_session_binding=provider_session_binding,
            )
        if provider_session_binding is not None:
            raise ValueError(
                "provider_session_binding requires provider_invocation and provider_service"
            )
        if god_config.runtime == "codex":
            model = normalize_codex_model_id(
                god_config.model or os.environ.get(
                    "XMUSE_CODEX_MODEL",
                    DEFAULT_CODEX_GOD_MODEL_ID,
                ),
                profile_id=ProviderProfileId.GOD,
            )
            return [
                "codex",
                "exec",
                "-m",
                model,
                "--dangerously-bypass-approvals-and-sandbox",
                "-c",
                'mcp_servers.xmuse-platform.type="sse"',
                "-c",
                f'mcp_servers.xmuse-platform.url="http://localhost:{self._mcp_port}/sse"',
                "-C",
                str(worktree),
            ]
        raise ValueError(f"unsupported god runtime: {god_config.runtime!r}; xmuse is codex-only")

    def _write_mcp_config(self) -> str:
        config = {
            "mcpServers": {
                "xmuse-platform": {
                    "type": "sse",
                    "url": f"http://localhost:{self._mcp_port}/sse",
                }
            }
        }
        path = Path(tempfile.gettempdir()) / "xmuse-mcp-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return str(path)

    def _build_env(
        self,
        god_config: GodConfig,
        lane_id: str,
        *,
        provider_invocation: ProviderInvocation | None = None,
    ) -> dict[str, str]:
        env = dict(os.environ)
        env["XMUSE_GOD_NAME"] = god_config.name
        env["XMUSE_LANE_ID"] = lane_id
        env["XMUSE_MCP_URL"] = f"http://localhost:{self._mcp_port}"
        if god_config.model:
            env["XMUSE_GOD_MODEL"] = god_config.model
        if god_config.worker_model:
            env["XMUSE_WORKER_MODEL"] = god_config.worker_model
        if god_config.delegation_mode:
            env["XMUSE_DELEGATION_MODE"] = god_config.delegation_mode
        context = current_observability_context()
        if trace_id := context.get("trace_id"):
            env["XMUSE_TRACE_ID"] = trace_id
        if request_id := context.get("request_id"):
            env["XMUSE_REQUEST_ID"] = request_id
        if session_id := context.get("session_id"):
            env["MEMORYOS_SESSION_ID"] = session_id
        if graph_id := context.get("graph_id"):
            env["XMUSE_GRAPH_ID"] = graph_id
        if provider_invocation is not None and self._provider_service is not None:
            return normalize_child_temp_env(
                self._provider_service.build_env(
                    provider_invocation,
                    lane_id=lane_id,
                    base_env=env,
                )
            )
        return normalize_child_temp_env(env)

    def _spawn_log_dir(self, lane_id: str) -> Path:
        safe_lane_id = "".join(
            char if char.isalnum() or char in {"-", "_", "."} else "-"
            for char in lane_id
        )
        return self._repo_root / "logs" / "agent_spawns" / safe_lane_id

    def _write_spawn_log(
        self,
        *,
        lane_id: str,
        god_config: GodConfig,
        command: list[str],
        prompt: str,
        result: SpawnResult,
    ) -> dict[str, str]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        log_dir = self._spawn_log_dir(lane_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = log_dir / f"{timestamp}.prompt.md"
        stdout_path = log_dir / f"{timestamp}.stdout.log"
        stderr_path = log_dir / f"{timestamp}.stderr.log"
        result_path = log_dir / f"{timestamp}.result.json"
        prompt_path.write_text(prompt, encoding="utf-8")
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        result_path.write_text(
            json.dumps(
                {
                    "lane_id": lane_id,
                    "god": god_config.name,
                    "runtime": god_config.runtime,
                    "model": god_config.model,
                    "worker_model": god_config.worker_model,
                    "delegation_mode": god_config.delegation_mode,
                    "command": command,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "memoryos_session_id": result.memoryos_session_id,
                    "memoryos_context_attached": result.memoryos_context_attached,
                    "memoryos_ingested": result.memoryos_ingested,
                    "memoryos_degraded_reason": result.memoryos_degraded_reason,
                    "provider_result": (
                        result.provider_result.model_dump(mode="json")
                        if result.provider_result is not None
                        else None
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "prompt_log_path": str(prompt_path),
            "stdout_log_path": str(stdout_path),
            "stderr_log_path": str(stderr_path),
            "result_log_path": str(result_path),
        }

    async def spawn(
        self,
        *,
        god_config: GodConfig,
        lane_id: str,
        prompt: str,
        worktree: Path,
        provider_invocation: ProviderInvocation | None = None,
        provider_session_binding: ProviderSessionBindingRecord | None = None,
    ) -> SpawnResult:
        memoryos_session_id, prompt, context_attached, degraded_reason = (
            await self._prepare_memoryos_prompt(lane_id, prompt)
        )
        provider_invocation = self._with_final_prompt(provider_invocation, prompt)
        if self._uses_direct_provider_adapter(provider_invocation):
            assert provider_invocation is not None
            return await self._spawn_direct_provider_adapter(
                god_config=god_config,
                lane_id=lane_id,
                prompt=prompt,
                provider_invocation=provider_invocation,
                memoryos_session_id=memoryos_session_id,
                memoryos_context_attached=context_attached,
                memoryos_degraded_reason=degraded_reason,
            )
        cmd = self._build_command(
            god_config,
            worktree,
            provider_invocation=provider_invocation,
            provider_session_binding=provider_session_binding,
        )
        env = self._build_env(
            god_config,
            lane_id,
            provider_invocation=provider_invocation,
        )
        stdin_payload = self._stdin_payload_for_invocation(prompt, provider_invocation)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=worktree,
            env=env,
        )
        if self._on_process_start is not None:
            try:
                self._on_process_start(lane_id, process.pid, cmd, worktree)
            except Exception:
                process.kill()
                await process.wait()
                raise

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin_payload),
                timeout=god_config.timeout_s,
            )
            result = SpawnResult(
                exit_code=process.returncode or 0,
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
                process_pid=process.pid,
                memoryos_session_id=memoryos_session_id,
                memoryos_context_attached=context_attached,
                memoryos_degraded_reason=degraded_reason,
            )
            if memoryos_session_id is not None:
                result.memoryos_ingested = await self._ingest_memoryos_result(
                    memoryos_session_id,
                    original_prompt=self._strip_memoryos_context(prompt),
                    result=result,
                )
            log_paths = self._write_spawn_log(
                lane_id=lane_id,
                god_config=god_config,
                command=cmd,
                prompt=prompt,
                result=result,
            )
            self._attach_provider_metadata(
                result,
                provider_invocation=provider_invocation,
                log_paths=log_paths,
            )
            return result
        except TimeoutError:
            process.kill()
            await process.wait()
            result = SpawnResult(
                exit_code=-1,
                stdout="",
                stderr="timeout",
                timed_out=True,
                process_pid=process.pid,
                memoryos_session_id=memoryos_session_id,
                memoryos_context_attached=context_attached,
                memoryos_degraded_reason=degraded_reason,
            )
            if memoryos_session_id is not None:
                result.memoryos_ingested = await self._ingest_memoryos_result(
                    memoryos_session_id,
                    original_prompt=self._strip_memoryos_context(prompt),
                    result=result,
                )
            log_paths = self._write_spawn_log(
                lane_id=lane_id,
                god_config=god_config,
                command=cmd,
                prompt=prompt,
                result=result,
            )
            self._attach_provider_metadata(
                result,
                provider_invocation=provider_invocation,
                log_paths=log_paths,
            )
            return result

    async def _spawn_direct_provider_adapter(
        self,
        *,
        god_config: GodConfig,
        lane_id: str,
        prompt: str,
        provider_invocation: ProviderInvocation,
        memoryos_session_id: str | None,
        memoryos_context_attached: bool,
        memoryos_degraded_reason: str | None,
    ) -> SpawnResult:
        if self._provider_service is None:
            raise ValueError("direct provider adapter requires provider_service")
        provider_result = self._provider_service.invoke_provider_adapter(
            provider_invocation
        )
        result = SpawnResult(
            exit_code=(
                0 if provider_result.status is WorkerResultStatus.COMPLETED else 1
            ),
            stdout="",
            stderr=_provider_result_stderr(provider_result),
            memoryos_session_id=memoryos_session_id,
            memoryos_context_attached=memoryos_context_attached,
            memoryos_degraded_reason=memoryos_degraded_reason,
            provider_result=provider_result,
            provider_profile_ref=provider_invocation.provider_profile_ref,
        )
        if memoryos_session_id is not None:
            result.memoryos_ingested = await self._ingest_memoryos_result(
                memoryos_session_id,
                original_prompt=self._strip_memoryos_context(prompt),
                result=result,
            )
        log_paths = self._write_spawn_log(
            lane_id=lane_id,
            god_config=god_config,
            command=[
                "xmuse-provider-adapter",
                provider_invocation.provider_profile_ref,
            ],
            prompt=prompt,
            result=result,
        )
        self._attach_provider_metadata(
            result,
            provider_invocation=provider_invocation,
            log_paths=log_paths,
        )
        return result

    def _uses_direct_provider_adapter(
        self,
        provider_invocation: ProviderInvocation | None,
    ) -> bool:
        if provider_invocation is None or self._provider_service is None:
            return False
        return self._provider_service.runtime_for_invocation(provider_invocation) == "a2a"

    def _with_final_prompt(
        self,
        provider_invocation: ProviderInvocation | None,
        prompt: str,
    ) -> ProviderInvocation | None:
        if provider_invocation is None or provider_invocation.prompt == prompt:
            return provider_invocation
        return provider_invocation.model_copy(update={"prompt": prompt})

    def _stdin_payload_for_invocation(
        self,
        prompt: str,
        provider_invocation: ProviderInvocation | None,
    ) -> bytes:
        if provider_invocation is None or self._provider_service is None:
            return prompt.encode()
        if self._provider_service.prompt_delivery_for_invocation(provider_invocation) == "argv":
            return b""
        return prompt.encode()

    def _attach_provider_metadata(
        self,
        result: SpawnResult,
        *,
        provider_invocation: ProviderInvocation | None,
        log_paths: dict[str, str],
    ) -> None:
        result.prompt_log_path = log_paths["prompt_log_path"]
        result.stdout_log_path = log_paths["stdout_log_path"]
        result.stderr_log_path = log_paths["stderr_log_path"]
        result.result_log_path = log_paths["result_log_path"]
        if provider_invocation is None or self._provider_service is None:
            return
        result.provider_profile_ref = provider_invocation.provider_profile_ref
        if result.provider_result is None:
            result.provider_result = self._provider_service.build_result_from_spawn_result(
                provider_invocation,
                result,
            )

    async def _prepare_memoryos_prompt(
        self,
        lane_id: str,
        prompt: str,
    ) -> tuple[str | None, str, bool, str | None]:
        if self._memoryos_client is None:
            return None, prompt, False, None
        try:
            session_id = await self._memoryos_client.create_session(f"xmuse:{lane_id}")
        except Exception as exc:
            return None, prompt, False, str(exc)
        if not session_id:
            return None, prompt, False, "create_session_returned_empty"
        try:
            context = await self._memoryos_client.build_context(session_id, prompt)
        except Exception as exc:
            return str(session_id), prompt, False, str(exc)
        if not context:
            return str(session_id), prompt, False, None
        wrapped = f"<memoryos_context>\n{context}\n</memoryos_context>\n\n{prompt}"
        return str(session_id), wrapped, True, None

    async def _ingest_memoryos_result(
        self,
        session_id: str,
        *,
        original_prompt: str,
        result: SpawnResult,
    ) -> bool:
        if self._memoryos_client is None:
            return False
        try:
            await self._memoryos_client.ingest(session_id, "user", original_prompt)
            assistant_text = result.stdout.strip()
            if not assistant_text and result.stderr.strip():
                assistant_text = result.stderr.strip()
            if assistant_text:
                await self._memoryos_client.ingest(
                    session_id,
                    "assistant",
                    assistant_text[:4000],
                )
            return True
        except Exception as exc:
            result.memoryos_degraded_reason = str(exc)
            return False

    def _strip_memoryos_context(self, prompt: str) -> str:
        end_tag = "</memoryos_context>"
        if prompt.startswith("<memoryos_context>") and end_tag in prompt:
            return prompt.split(end_tag, 1)[1].lstrip()
        return prompt


def _provider_result_stderr(result: ProviderInvocationResult) -> str:
    if result.status is WorkerResultStatus.COMPLETED:
        return ""
    if result.failure_kind is not None:
        return result.failure_kind.value
    return result.status.value
