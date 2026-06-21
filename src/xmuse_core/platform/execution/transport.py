from __future__ import annotations

from pathlib import Path

from xmuse_core.platform.agent_spawner import AgentSpawner, GodConfig, SpawnResult
from xmuse_core.platform.execution.review import review_infra_failure_reason
from xmuse_core.platform.messages import (
    ExecuteRequest,
    ExecuteResponse,
    ReviewRequest,
    ReviewVerdict,
    Transport,
)
from xmuse_core.self_evolution.recovery import TransientRecoveryError


class SubprocessTransport(Transport):
    """Default Transport: spawn a god via AgentSpawner and translate infra
    failures (usage/rate limits, transient outages) into a
    TransientRecoveryError so the recovery layer can retry or trip the circuit.

    Holds the spawner instance and calls ``.spawn`` at call time so tests that
    patch ``orchestrator._spawner.spawn`` continue to take effect.
    """

    def __init__(self, spawner: AgentSpawner) -> None:
        self._spawner = spawner

    async def send_execute(self, req: ExecuteRequest) -> ExecuteResponse:
        result = await self.spawn_god(
            god=req.god_config,
            lane_id=req.lane_id,
            prompt=req.prompt,
            worktree=req.worktree,
            provider_invocation=req.provider_invocation,
            provider_session_binding=req.provider_session_binding,
        )
        provider_result = self._provider_result_for_spawn(
            req.provider_invocation,
            result,
        )
        return ExecuteResponse(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
            process_pid=result.process_pid,
            memoryos_session_id=result.memoryos_session_id,
            memoryos_context_attached=result.memoryos_context_attached,
            memoryos_ingested=result.memoryos_ingested,
            memoryos_degraded_reason=result.memoryos_degraded_reason,
            provider_result=provider_result,
        )

    async def send_review(self, req: ReviewRequest) -> ReviewVerdict:
        result = await self.spawn_god(
            god=req.god_config,
            lane_id=req.lane_id,
            prompt=req.prompt,
            worktree=req.worktree,
            provider_invocation=req.provider_invocation,
            provider_session_binding=req.provider_session_binding,
        )
        provider_result = self._provider_result_for_spawn(
            req.provider_invocation,
            result,
        )
        return ReviewVerdict(
            passed=result.exit_code == 0 and not result.timed_out,
            verdict="raw",
            feedback=result.stderr,
            raw_output=result.stdout,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            provider_result=provider_result,
            prompt_log_path=result.prompt_log_path,
            stdout_log_path=result.stdout_log_path,
            stderr_log_path=result.stderr_log_path,
            result_log_path=result.result_log_path,
        )

    async def spawn_god(
        self,
        *,
        god: GodConfig,
        lane_id: str,
        prompt: str,
        worktree: Path,
        provider_invocation=None,
        provider_session_binding=None,
    ) -> SpawnResult:
        try:
            spawn_kwargs = {
                "god_config": god,
                "lane_id": lane_id,
                "prompt": prompt,
                "worktree": worktree,
                "provider_invocation": provider_invocation,
            }
            if provider_session_binding is not None:
                spawn_kwargs["provider_session_binding"] = provider_session_binding
            result = await self._spawner.spawn(**spawn_kwargs)
        except TypeError as exc:
            if provider_session_binding is not None and _is_provider_binding_signature_error(exc):
                raise
            if provider_invocation is None or not _is_provider_invocation_signature_error(exc):
                raise
            result = await self._spawner.spawn(
                god_config=god,
                lane_id=lane_id,
                prompt=prompt,
                worktree=worktree,
            )
        infra_reason = review_infra_failure_reason(result)
        if infra_reason is not None:
            output = getattr(result, "stderr", "") or getattr(result, "stdout", "")
            raise TransientRecoveryError(
                f"{infra_reason}: {output or 'spawn infrastructure failure'}"
            )
        return result

    def _provider_result_for_spawn(self, provider_invocation, result: SpawnResult):
        if provider_invocation is None:
            return result.provider_result
        if result.provider_result is not None:
            return result.provider_result
        provider_service = getattr(self._spawner, "_provider_service", None)
        if provider_service is None:
            return None
        return provider_service.build_result_from_spawn_result(
            provider_invocation,
            result,
        )


def _is_provider_invocation_signature_error(exc: TypeError) -> bool:
    message = str(exc)
    return "provider_invocation" in message and "unexpected keyword" in message


def _is_provider_binding_signature_error(exc: TypeError) -> bool:
    message = str(exc)
    return "provider_session_binding" in message and "unexpected keyword" in message


SpawnerTransport = SubprocessTransport
