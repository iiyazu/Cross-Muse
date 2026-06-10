#!/usr/bin/env python3
"""Multi-round autonomous xmuse orchestrator."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent.parent
XMUSE_CODE_DIR = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(XMUSE_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(XMUSE_CODE_DIR))

from error_knowledge import ErrorKnowledge

from xmuse_core.agents.consumer import TaskDescriptor, WorklistConsumer
from xmuse_core.agents.launchers.codex import CodexLauncher
from xmuse_core.agents.manager import SessionManager
from xmuse_core.agents.memoryos_client import MemoryOSClient
from xmuse_core.agents.registry import AgentRegistry, AgentRuntime
from xmuse_core.platform import (
    master_loop_cli,
    master_loop_full_gate,
    master_loop_git,
    master_loop_lanes,
    master_loop_state,
    master_loop_tasks,
)
from xmuse_core.platform.master_loop_lanes import (
    FULL_QUALITY_GATE_PRIORITY,
    FULL_QUALITY_GATE_TASK_TYPE,
)
from xmuse_core.platform.projection.syncer import LaneProjectionSyncer
from xmuse_core.runtime.paths import default_xmuse_root

logger = logging.getLogger("xmuse.master_loop")
WORKTREE_BASE = master_loop_lanes.WORKTREE_BASE
XMUSE_ROOT = default_xmuse_root(XMUSE_CODE_DIR)
DEFAULT_LANES_PATH = XMUSE_ROOT / "feature_lanes.json"
DEFAULT_AGENTS_PATH = XMUSE_ROOT / "agents.json"
DEFAULT_ACTIVE_SESSIONS_PATH = XMUSE_ROOT / "active_sessions.json"
DEFAULT_AUTO_DISCOVERY_PATH = XMUSE_CODE_DIR / "auto_discovery.py"
DEFAULT_GATE_PROFILES_PATH = XMUSE_ROOT / "gate_profiles.json"
subprocess = master_loop_lanes.subprocess


ProcessResult = master_loop_git.ProcessResult


def _coerce_priority(value: Any) -> int:
    return master_loop_lanes.coerce_priority(value)


def _root_head_sha() -> str:
    return master_loop_lanes.root_head_sha()


def _lane_metadata(lane: dict[str, Any]) -> dict[str, Any]:
    return master_loop_lanes.lane_metadata(lane)


def _is_full_gate_family_lane(lane: dict[str, Any]) -> bool:
    return master_loop_lanes.is_full_gate_family_lane(lane)


def _is_terminal_lane(lane: dict[str, Any]) -> bool:
    return master_loop_lanes.is_terminal_lane(lane)


def _should_retry_lane(lane: dict[str, Any]) -> bool:
    """Check if a failed lane is eligible for automatic retry."""
    return master_loop_lanes.should_retry_lane(lane)


def _is_active_full_gate_family_lane(lane: dict[str, Any]) -> bool:
    return master_loop_lanes.is_active_full_gate_family_lane(lane)


def ensure_worktree(feature_id: str, branch: str | None = None) -> Path:
    """Create or reuse a git worktree for a feature lane."""
    return master_loop_lanes.ensure_worktree(
        feature_id,
        branch,
        worktree_base=WORKTREE_BASE,
        root_head_sha_fn=_root_head_sha,
        fast_forward_fn=lambda path, **_kwargs: _fast_forward_existing_worktree(path),
    )


def _fast_forward_existing_worktree(wt_path: Path) -> None:
    master_loop_lanes.fast_forward_existing_worktree(
        wt_path,
        root_head_sha_fn=_root_head_sha,
    )


def load_lanes(path: Path) -> list[TaskDescriptor]:
    """Load pending lanes whose dependencies are complete."""
    return master_loop_lanes.load_lanes(
        path,
        ensure_worktree_fn=ensure_worktree,
        root_head_sha_fn=_root_head_sha,
        fast_forward_fn=_fast_forward_existing_worktree,
    )


def update_lane_status(lanes_path: Path, feature_id: str, status: str) -> None:
    """Write lane status back to feature_lanes.json through the projection syncer."""
    master_loop_lanes.update_lane_status(lanes_path, feature_id, status)


def _update_lane_fields(
    lanes_path: Path,
    feature_id: str,
    fields: dict[str, Any],
) -> None:
    """Update a lane atomically through the shared projection syncer."""
    master_loop_lanes.update_lane_fields(lanes_path, feature_id, fields)


class GateResultLike(Protocol):
    passed: bool
    errors: list[str]
    gate_report: dict[str, object] | None
    gate_warnings: list[str]


class QualityGateLike(Protocol):
    async def check(self, worktree: Path, **kwargs: Any) -> GateResultLike: ...


class LaneResultLike(Protocol):
    status: str
    final_errors: list[str] | None


class ReworkLoopLike(Protocol):
    async def run(
        self,
        lane: TaskDescriptor,
        initial_gate_result: GateResultLike,
        dispatch_fn: Any,
        gate: QualityGateLike,
        max_retries: int = 3,
    ) -> LaneResultLike: ...


class ConsumerLike(Protocol):
    async def dispatch_task(self, task: TaskDescriptor) -> str: ...
    def shutdown(self) -> None: ...


class ErrorKnowledgeLike(Protocol):
    def record_failure(
        self,
        lane_id: str,
        error_output: str,
        fix_output: str | None = None,
    ) -> dict[str, Any]: ...

    def inject_context(self, prompt: str) -> str: ...


@dataclass
class MasterLoopSummary:
    rounds: int = 0
    successful_lanes: int = 0
    failed_lanes: int = 0
    zero_success_rounds: int = 0
    exit_reason: str = ""


class MasterLoop:
    """Run discovery, dispatch, quality gate, and rework rounds until quiescent."""

    def __init__(
        self,
        *,
        lanes_path: Path = DEFAULT_LANES_PATH,
        auto_discovery_path: Path = DEFAULT_AUTO_DISCOVERY_PATH,
        consumer: ConsumerLike | None,
        quality_gate: QualityGateLike,
        rework_loop: ReworkLoopLike,
        review_gate: Any | None = None,
        error_knowledge: ErrorKnowledgeLike | None = None,
        max_hours: float = 10.0,
        max_concurrent: int = 2,
        discovery_enabled: bool = True,
        python_executable: str = sys.executable,
        gate_profiles_path: Path = DEFAULT_GATE_PROFILES_PATH,
        monotonic: Any = time.monotonic,
    ) -> None:
        self.lanes_path = lanes_path
        self.auto_discovery_path = auto_discovery_path
        self.consumer = consumer
        self.quality_gate = quality_gate
        self.rework_loop = rework_loop
        self.review_gate = review_gate
        self.error_knowledge = error_knowledge
        self.max_hours = max_hours
        self.max_concurrent = max(1, max_concurrent)
        self.discovery_enabled = discovery_enabled
        self.python_executable = python_executable
        self.gate_profiles_path = gate_profiles_path
        self._monotonic = monotonic
        self._shutdown_requested = asyncio.Event()
        self._merge_lock = asyncio.Lock()
        self._lane_mutation_lock = asyncio.Lock()

    @classmethod
    def from_defaults(
        cls,
        *,
        lanes_path: Path = DEFAULT_LANES_PATH,
        auto_discovery_path: Path = DEFAULT_AUTO_DISCOVERY_PATH,
        agents_path: Path = DEFAULT_AGENTS_PATH,
        memoryos_url: str = "http://127.0.0.1:8000",
        max_hours: float = 10.0,
        max_concurrent: int = 2,
        discovery_enabled: bool = True,
    ) -> MasterLoop:
        from xmuse_core.agents.quality_gate import QualityGate
        from xmuse_core.agents.rework_loop import ReworkLoop

        registry = AgentRegistry.from_file(agents_path)
        memoryos = MemoryOSClient(base_url=memoryos_url)
        session_mgr = SessionManager(
            launchers={AgentRuntime.CODEX: CodexLauncher()},
            state_file=DEFAULT_ACTIVE_SESSIONS_PATH,
            memoryos_client=memoryos,
        )
        consumer = WorklistConsumer(
            registry=registry,
            session_mgr=session_mgr,
            max_concurrent=max_concurrent,
            on_complete=lambda fid, st: update_lane_status(lanes_path, fid, st),
        )
        error_knowledge = ErrorKnowledge()
        return cls(
            lanes_path=lanes_path,
            auto_discovery_path=auto_discovery_path,
            consumer=consumer,
            quality_gate=QualityGate(
                profile_config_path=DEFAULT_GATE_PROFILES_PATH,
                repo_root=ROOT,
            ),
            rework_loop=ReworkLoop(error_knowledge=error_knowledge),
            review_gate=cls._build_review_gate(),
            error_knowledge=error_knowledge,
            max_hours=max_hours,
            max_concurrent=max_concurrent,
            discovery_enabled=discovery_enabled,
            gate_profiles_path=DEFAULT_GATE_PROFILES_PATH,
        )

    @staticmethod
    def _build_review_gate() -> Any:
        import os

        enabled = os.environ.get("XMUSE_REVIEW_GATE", "1").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return None
        from xmuse_core.gates.review_gate import CodexReviewGate

        return CodexReviewGate(
            codex_cmd=os.environ.get("XMUSE_REVIEW_CODEX_CMD", "codex"),
            model=os.environ.get("XMUSE_REVIEW_MODEL", "gpt-5.5"),
            timeout_s=float(os.environ.get("XMUSE_REVIEW_TIMEOUT_S", "300")),
        )

    async def run(self) -> MasterLoopSummary:
        summary = MasterLoopSummary()
        deadline = self._monotonic() + self.max_hours * 3600

        while True:
            if self._shutdown_requested.is_set():
                summary.exit_reason = "shutdown"
                break
            if self._monotonic() >= deadline:
                summary.exit_reason = "timeout"
                break

            summary.rounds += 1
            self._gc_stale_lanes()
            new_discovered_count = 0
            if self.discovery_enabled:
                discovered = await self._run_auto_discovery()
                new_discovered_count = self._merge_discovered_lanes(discovered)
            pending = load_lanes(self.lanes_path)

            if not pending and new_discovered_count == 0:
                summary.exit_reason = "idle"
                break

            round_successes, round_failures = await self._dispatch_round(pending, deadline)
            summary.successful_lanes += round_successes
            summary.failed_lanes += round_failures

            if round_successes == 0:
                summary.zero_success_rounds += 1
            else:
                summary.zero_success_rounds = 0

            if self._shutdown_requested.is_set():
                summary.exit_reason = "shutdown"
                break
            if self._monotonic() >= deadline:
                summary.exit_reason = "timeout"
                break
            if summary.zero_success_rounds >= 3:
                summary.exit_reason = "zero_success_rounds"
                break

        if self.consumer is not None:
            self.consumer.shutdown()
        return summary

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_shutdown)
            except NotImplementedError:
                signal.signal(sig, lambda _signum, _frame: self.request_shutdown())

    async def _run_auto_discovery(self) -> list[dict[str, Any]]:
        process = await asyncio.create_subprocess_exec(
            self.python_executable,
            str(self.auto_discovery_path),
            "--all",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ROOT,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(
                "auto discovery failed with exit %s: %s",
                process.returncode,
                stderr.decode(errors="replace")[:1000],
            )
            return []
        output = stdout.decode(errors="replace").strip()
        if not output:
            return []
        try:
            lanes = json.loads(output)
        except json.JSONDecodeError:
            logger.warning("auto discovery returned invalid JSON: %s", output[:1000])
            return []
        if not isinstance(lanes, list):
            logger.warning("auto discovery returned %s, expected list", type(lanes).__name__)
            return []
        return [lane for lane in lanes if isinstance(lane, dict) and lane.get("feature_id")]

    def _merge_discovered_lanes(self, discovered: list[dict[str, Any]]) -> int:
        data = self._read_lanes_json()
        lanes = data.setdefault("lanes", [])
        existing_ids = {lane.get("feature_id") for lane in lanes}
        new_count = 0
        changed = False
        for lane in discovered:
            if lane.get("feature_id") in existing_ids:
                continue
            lane.setdefault("status", "pending")
            lane.setdefault("depends_on", [])
            lanes.append(lane)
            existing_ids.add(lane.get("feature_id"))
            new_count += 1
            changed = True
        if changed:
            self._write_lanes_json(data)
        return new_count

    async def _dispatch_round(
        self,
        pending: list[TaskDescriptor],
        deadline: float,
    ) -> tuple[int, int]:
        successful = 0
        failed = 0
        sequence = 0
        seen_ids: set[str] = set()
        queue: asyncio.PriorityQueue[tuple[int, int, TaskDescriptor]] = (
            asyncio.PriorityQueue()
        )

        def enqueue(task: TaskDescriptor) -> None:
            nonlocal sequence
            if task.feature_id in seen_ids:
                return
            seen_ids.add(task.feature_id)
            queue.put_nowait((-task.priority, sequence, task))
            sequence += 1

        for task in pending:
            enqueue(task)

        async def worker() -> None:
            nonlocal successful, failed
            while not self._shutdown_requested.is_set() and self._monotonic() < deadline:
                try:
                    _, _, task = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    status = await self._run_lane(task)
                    if status == "done":
                        successful += 1
                        if task.task_type != FULL_QUALITY_GATE_TASK_TYPE:
                            await self._maybe_append_full_quality_gate_lane()
                    else:
                        failed += 1
                    for new_task in self._load_new_high_priority_lanes(seen_ids):
                        enqueue(new_task)
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(self.max_concurrent, max(1, len(pending))))
        ]
        await asyncio.gather(*workers)
        return successful, failed

    async def _run_lane(self, task: TaskDescriptor) -> str:
        if task.task_type == FULL_QUALITY_GATE_TASK_TYPE:
            return await self._run_full_quality_gate_lane(task)

        if self.consumer is None:
            raise RuntimeError("MasterLoop.consumer is required before dispatching lanes")

        # Design-type lanes route to the DesignPipelineSkill
        if task.task_type == "design":
            return await self._run_design_lane(task)

        self._update_lane_status(task.feature_id, "running")
        await self._clean_worktree_before_dispatch(task)
        dispatch_task = self._inject_error_knowledge(task)
        dispatch_task = self._inject_scope_constraint(dispatch_task)
        dispatch_status = await self.consumer.dispatch_task(dispatch_task)
        if dispatch_status != "done":
            self._update_lane_status(task.feature_id, "failed")
            return "failed"

        gate_result = await self._check_quality_gate(
            self.quality_gate,
            Path(task.worktree),
            feature_id=task.feature_id,
            gate_profile=task.gate_profile,
            gate_profiles=task.gate_profiles,
            base_head_sha=task.base_head_sha,
        )
        self._record_gate_report(task.feature_id, gate_result)
        if gate_result.passed:
            if not await self._review_lane_before_merge(task, gate_result):
                self._update_lane_status(task.feature_id, "failed")
                return "failed"
            merged = await self._auto_merge_worktree(task)
            self._update_lane_status(task.feature_id, "done" if merged else "merge_failed")
            return "done" if merged else "failed"

        async def dispatch_rework(rework_prompt: str, worktree: str | Path) -> str:
            enriched_prompt = self._inject_error_knowledge_text(rework_prompt)
            rework_task = TaskDescriptor(
                feature_id=task.feature_id,
                task_type="rework",
                prompt=enriched_prompt,
                worktree=str(worktree),
                required_capabilities=task.required_capabilities,
                developed_by_runtime=task.developed_by_runtime,
                priority=task.priority,
                gate_profile=task.gate_profile,
                gate_profiles=task.gate_profiles,
                lane_metadata=task.lane_metadata,
                base_head_sha=task.base_head_sha,
            )
            return await self.consumer.dispatch_task(rework_task)

        lane_result = await self.rework_loop.run(
            task,
            gate_result,
            dispatch_rework,
            self.quality_gate,
            max_retries=3,
        )
        status = "done" if lane_result.status == "done" else "failed"
        if status == "done":
            final_gate_result = getattr(lane_result, "final_gate_result", None)
            if final_gate_result is not None:
                self._record_gate_report(task.feature_id, final_gate_result)
            else:
                final_gate_result = gate_result
            if not await self._review_lane_before_merge(task, final_gate_result):
                status = "failed"
                self._update_lane_status(task.feature_id, status)
                return "failed"
            merged = await self._auto_merge_worktree(task)
            if not merged:
                status = "merge_failed"
        elif status == "failed":
            self._record_failed_rework(task, gate_result, lane_result)
        self._update_lane_status(task.feature_id, status)
        return "done" if status == "done" else "failed"

    def _update_lane_status(self, feature_id: str, status: str) -> None:
        update_lane_status(self.lanes_path, feature_id, status)

    def _record_gate_report(self, feature_id: str, result: GateResultLike) -> None:
        report = getattr(result, "gate_report", None)
        warnings = getattr(result, "gate_warnings", None) or []
        if report is None and not warnings:
            return
        fields: dict[str, Any] = {}
        if report is not None:
            fields["gate_report"] = report
        if warnings:
            fields["gate_warnings"] = list(warnings)
        _update_lane_fields(self.lanes_path, feature_id, fields)

    async def _run_full_quality_gate_lane(self, task: TaskDescriptor) -> str:
        self._update_lane_status(task.feature_id, "running")
        gate_result = await self._check_quality_gate(
            self.quality_gate,
            ROOT,
            feature_id=task.feature_id,
            gate_profile=task.gate_profile,
            gate_profiles=task.gate_profiles or ["strict-product"],
            changed_paths=[],
            base_head_sha=task.base_head_sha,
        )
        self._record_gate_report(task.feature_id, gate_result)
        if gate_result.passed:
            self._update_lane_status(task.feature_id, "done")
            return "done"

        artifact_path = self._write_full_gate_artifact_from_errors(
            task.feature_id,
            gate_result.errors,
        )
        await self._append_full_gate_repair_lane(task, gate_result, artifact_path)
        self._update_lane_status(task.feature_id, "failed")
        return "failed"

    async def _check_quality_gate(
        self,
        gate: QualityGateLike,
        worktree: Path,
        **kwargs: Any,
    ) -> GateResultLike:
        signature = inspect.signature(gate.check)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        accepted = {
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind
            in {
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        }
        if accepts_kwargs or any(name in accepted for name in kwargs):
            filtered = kwargs if accepts_kwargs else {
                key: value for key, value in kwargs.items() if key in accepted
            }
            return await gate.check(worktree, **filtered)
        return await gate.check(worktree)

    async def _run_process(self, worktree: Path, *cmd: str) -> ProcessResult:
        return await master_loop_git.run_process(worktree, *cmd)

    def _write_full_gate_artifact_from_errors(
        self,
        feature_id: str,
        errors: list[str],
    ) -> Path:
        artifact_dir = XMUSE_ROOT / "logs" / "full_quality_gate"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{feature_id}.log"
        artifact_path.write_text("\n\n".join(errors) + "\n", encoding="utf-8")
        return artifact_path

    def _full_gate_interval(self) -> int:
        from xmuse_core.gates.loader import load_gate_config

        config = load_gate_config(self.gate_profiles_path, repo_root=ROOT)
        return config.defaults.full_gate_interval

    async def _maybe_append_full_quality_gate_lane(self) -> str | None:
        async with self._lane_mutation_lock:
            data = self._read_lanes_json()
            lanes = data.setdefault("lanes", [])
            if self._compact_full_gate_family_queue(lanes):
                self._write_lanes_json(data)
            if self._has_active_full_quality_gate(lanes):
                return None
            batch_lane_ids = self._next_full_gate_batch(lanes)
            if len(batch_lane_ids) < self._full_gate_interval():
                return None

            head_sha = self._current_head_sha()
            feature_id = self._full_gate_feature_id(batch_lane_ids, head_sha)
            if any(lane.get("feature_id") == feature_id for lane in lanes):
                return None

            lanes.append(
                master_loop_full_gate.build_full_gate_lane(
                    feature_id=feature_id,
                    batch_lane_ids=batch_lane_ids,
                    head_sha=head_sha,
                )
            )
            self._write_lanes_json(data)
            logger.info(
                "queued full quality gate %s for %d lanes",
                feature_id,
                len(batch_lane_ids),
            )
            return feature_id

    def _has_active_full_quality_gate(self, lanes: list[dict[str, Any]]) -> bool:
        return master_loop_full_gate.has_active_full_quality_gate(lanes)

    def _compact_full_gate_family_queue(
        self,
        lanes: list[dict[str, Any]],
        *,
        preferred_feature_id: str | None = None,
    ) -> bool:
        return master_loop_full_gate.compact_full_gate_family_queue(
            lanes,
            preferred_feature_id=preferred_feature_id,
        )

    def _next_full_gate_batch(self, lanes: list[dict[str, Any]]) -> list[str]:
        return master_loop_full_gate.next_full_gate_batch(
            lanes,
            interval=self._full_gate_interval(),
        )

    def _full_gate_feature_id(self, batch_lane_ids: list[str], head_sha: str) -> str:
        return master_loop_full_gate.full_gate_feature_id(batch_lane_ids, head_sha)

    def _current_head_sha(self) -> str:
        return master_loop_git.current_head_sha(ROOT)

    async def _append_full_gate_repair_lane(
        self,
        task: TaskDescriptor,
        result: GateResultLike,
        artifact_path: Path,
    ) -> str | None:
        async with self._lane_mutation_lock:
            data = self._read_lanes_json()
            lanes = data.setdefault("lanes", [])
            gate_lane = next(
                (
                    lane
                    for lane in lanes
                    if lane.get("feature_id") == task.feature_id
                    and isinstance(lane, dict)
                ),
                {},
            )
            repair_id = f"full-quality-gate-repair-{task.feature_id}"
            if any(lane.get("feature_id") == repair_id for lane in lanes):
                return None
            if self._compact_full_gate_family_queue(
                lanes,
                preferred_feature_id=task.feature_id,
            ):
                self._write_lanes_json(data)
            if any(
                _is_active_full_gate_family_lane(lane)
                and lane.get("feature_id") != task.feature_id
                for lane in lanes
            ):
                return None

            batch_lane_ids = gate_lane.get("batch_lane_ids", [])
            head_sha = gate_lane.get("head_sha", self._current_head_sha())
            lanes.append(
                master_loop_full_gate.build_full_gate_repair_lane(
                    repair_id=repair_id,
                    gate_feature_id=task.feature_id,
                    artifact_path=artifact_path,
                    artifact_rel=str(artifact_path.relative_to(ROOT)),
                    errors=result.errors,
                    batch_lane_ids=batch_lane_ids,
                    head_sha=head_sha,
                )
            )
            self._write_lanes_json(data)
            logger.info("queued full quality gate repair lane %s", repair_id)
            return repair_id

    def _load_new_high_priority_lanes(
        self,
        seen_ids: set[str],
    ) -> list[TaskDescriptor]:
        tasks = load_lanes(self.lanes_path)
        return [
            task
            for task in tasks
            if task.feature_id not in seen_ids
            and task.priority >= FULL_QUALITY_GATE_PRIORITY
        ]

    async def _run_design_lane(self, task: TaskDescriptor) -> str:
        """Route design-type lanes to the DesignPipelineSkill."""
        self._update_lane_status(task.feature_id, "running")
        try:
            from xmuse_core.skills import SkillContext, create_default_registry
            from xmuse_core.skills.models import PipelineInput

            skill_registry = create_default_registry()
            ctx = SkillContext(
                registry=self._build_agent_registry(),
                session_manager=self._build_session_manager(),
                skill_registry=skill_registry,
                feature_root=XMUSE_ROOT / "work" / "features",
                prompt_dir=XMUSE_ROOT / "prompts",
                lanes_path=self.lanes_path,
            )
            pipeline = skill_registry.instantiate("design_pipeline", ctx)
            result = await pipeline.run(PipelineInput(
                feature_id=task.feature_id,
                goal=task.prompt,
            ))
            status = "done" if result.status == "success" else "failed"
        except Exception:
            logger.exception("design lane failed: %s", task.feature_id)
            status = "failed"
        self._update_lane_status(task.feature_id, status)
        return "done" if status == "done" else "failed"

    def _build_agent_registry(self) -> Any:
        """Return the agent registry used by the consumer."""
        if self.consumer and hasattr(self.consumer, "_registry"):
            return self.consumer._registry
        return None

    def _build_session_manager(self) -> Any:
        """Return the session manager used by the consumer."""
        if self.consumer and hasattr(self.consumer, "_session_mgr"):
            return self.consumer._session_mgr
        return None

    async def _review_lane_before_merge(
        self,
        task: TaskDescriptor,
        gate_result: GateResultLike,
    ) -> bool:
        review_verdict = await self._run_review_gate(task, gate_result)
        if review_verdict is None:
            return True
        self._record_review_verdict(task.feature_id, review_verdict)
        if review_verdict.approved:
            return True
        if getattr(review_verdict, "infrastructure_failure", False):
            return False

        logger.info(
            "Review gate rejected %s: %s",
            task.feature_id,
            review_verdict.summary,
        )
        if self.consumer is None:
            return False

        rework_task = self._build_review_rework_task(task, review_verdict)
        rework_status = await self.consumer.dispatch_task(rework_task)
        if rework_status != "done":
            return False

        second_gate = await self._check_quality_gate(
            self.quality_gate,
            Path(task.worktree),
            feature_id=task.feature_id,
            gate_profile=task.gate_profile,
            gate_profiles=task.gate_profiles,
            base_head_sha=task.base_head_sha,
        )
        self._record_gate_report(task.feature_id, second_gate)
        if not second_gate.passed:
            return False

        second_verdict = await self._run_review_gate(task, second_gate)
        if second_verdict is None:
            return True
        self._record_review_verdict(task.feature_id, second_verdict)
        if second_verdict.approved:
            return True

        logger.warning(
            "Review gate rejected %s twice, marking failed",
            task.feature_id,
        )
        return False

    def _build_review_rework_task(
        self,
        task: TaskDescriptor,
        review_verdict: Any,
    ) -> TaskDescriptor:
        rework_prompt = master_loop_tasks.render_review_rejection_prompt(review_verdict)
        return master_loop_tasks.build_review_rework_task(
            task,
            review_verdict,
            error_context=self._inject_error_knowledge_text(rework_prompt),
            diff_context=self._get_worktree_diff(task.worktree, task.base_head_sha),
        )

    async def _run_review_gate(
        self,
        task: TaskDescriptor,
        gate_result: GateResultLike | None = None,
    ) -> Any:
        if self.review_gate is None:
            return None
        try:
            kwargs = {
                "feature_id": task.feature_id,
                "worktree": Path(task.worktree),
                "original_prompt": task.prompt,
                "base_ref": task.base_head_sha,
            }
            if self._review_accepts_gate_context():
                kwargs["gate_context"] = self._format_gate_context(gate_result)
            review = self.review_gate.review(**kwargs)
            if inspect.isawaitable(review):
                return await review
            return review
        except Exception as exc:
            logger.exception("review gate failed for %s", task.feature_id)
            return SimpleNamespace(
                approved=False,
                concerns=[f"review_gate_exception: {exc!s}"[:500]],
                summary="review gate unavailable, blocking merge",
                confidence=0.0,
                self_modification=False,
                infrastructure_failure=True,
            )

    def _review_accepts_gate_context(self) -> bool:
        try:
            signature = inspect.signature(self.review_gate.review)
        except (TypeError, ValueError):
            return True
        parameters = signature.parameters
        return "gate_context" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

    def _format_gate_context(self, gate_result: GateResultLike | None) -> str:
        return master_loop_tasks.format_gate_context(gate_result)

    def _record_review_verdict(self, feature_id: str, verdict: Any) -> None:
        _update_lane_fields(
            self.lanes_path,
            feature_id,
            {
                "review_verdict": {
                    "approved": bool(getattr(verdict, "approved", False)),
                    "concerns": list(getattr(verdict, "concerns", [])),
                    "summary": str(getattr(verdict, "summary", "")),
                    "confidence": float(getattr(verdict, "confidence", 0.0)),
                    "self_modification": bool(
                        getattr(verdict, "self_modification", False)
                    ),
                }
            },
        )

    def _get_worktree_diff(self, worktree: str | Path, base_ref: str | None) -> str:
        return master_loop_git.get_worktree_diff(worktree, base_ref)

    async def _auto_merge_worktree(self, task: TaskDescriptor) -> bool:
        return await master_loop_git.auto_merge_worktree(
            task=task,
            root=ROOT,
            merge_lock=self._merge_lock,
        )

    def _record_failed_rework(
        self,
        task: TaskDescriptor,
        gate_result: GateResultLike,
        lane_result: LaneResultLike,
    ) -> None:
        if self.error_knowledge is None:
            return
        final_errors = lane_result.final_errors or gate_result.errors
        error_output = "\n\n".join(final_errors)
        try:
            self.error_knowledge.record_failure(task.feature_id, error_output)
        except Exception as exc:
            logger.warning("error knowledge record_failure failed: %s", exc)

    def _inject_error_knowledge(self, task: TaskDescriptor) -> TaskDescriptor:
        enriched_prompt = self._inject_error_knowledge_text(task.prompt)
        if enriched_prompt == task.prompt:
            return task
        return master_loop_tasks.clone_task_with_prompt(task, prompt=enriched_prompt)

    def _inject_error_knowledge_text(self, prompt: str) -> str:
        if self.error_knowledge is None:
            return prompt
        try:
            return self.error_knowledge.inject_context(prompt)
        except Exception as exc:
            logger.warning("error knowledge injection failed: %s", exc)
            return prompt

    def _inject_scope_constraint(self, task: TaskDescriptor) -> TaskDescriptor:
        """Append a scope constraint to prevent codex from modifying unrelated files."""
        return master_loop_tasks.with_scope_constraint(task)

    _STALE_RUNNING_HOURS = 4

    def _gc_stale_lanes(self) -> None:
        """Archive lanes stuck in running state for too long."""
        data = self._read_lanes_json()
        lanes = data.get("lanes", [])
        now = time.time()
        if master_loop_state.mark_stale_running_lanes(
            lanes,
            now=now,
            stale_hours=self._STALE_RUNNING_HOURS,
        ):
            self._write_lanes_json(data)

    async def _clean_worktree_before_dispatch(self, task: TaskDescriptor) -> None:
        """Reset worktree to clean state before dispatch to avoid scope-creep residue."""
        dirty_count = master_loop_git.clean_worktree_before_dispatch(task.worktree)
        if dirty_count:
            logger.info("Cleaning worktree for %s: %d dirty files", task.feature_id, dirty_count)

    def _read_lanes_json(self) -> dict[str, Any]:
        try:
            data = LaneProjectionSyncer(self.lanes_path).read()
        except (json.JSONDecodeError, ValueError):
            logger.warning("invalid lanes JSON in %s; resetting", self.lanes_path)
            return {"lanes": []}
        return data

    def _write_lanes_json(self, data: dict[str, Any]) -> None:
        LaneProjectionSyncer(self.lanes_path).update(lambda _data: data)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return master_loop_cli.parse_args(argv)


async def main(args: argparse.Namespace) -> MasterLoopSummary:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    loop = MasterLoop.from_defaults(
        lanes_path=Path(args.lanes),
        auto_discovery_path=Path(args.auto_discovery),
        agents_path=Path(args.config),
        memoryos_url=args.memoryos_url,
        max_hours=args.max_hours,
        max_concurrent=args.concurrency,
        discovery_enabled=not args.no_discovery,
    )
    loop.install_signal_handlers()
    summary = await loop.run()
    logger.info("master loop exited: %s", summary)
    return summary


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
