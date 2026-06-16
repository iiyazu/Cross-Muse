#!/usr/bin/env python3
"""xmuse Platform Runner — MVP entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import inspect
import json
import logging
import math
import os
import signal
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.memoryos_client import MemoryOSClient
from xmuse_core.chat.driver import ChatDriver
from xmuse_core.platform.coordinator_control import CoordinatorControlService
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
    capture_local_execution_candidate,
)
from xmuse_core.platform.model_policy import CodexModelPolicy, resolve_codex_model_policy
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.platform.orchestrator_lane_flow import (
    build_lane_recovery_dispatch_block_metadata,
)
from xmuse_core.platform.run_health import (
    DEFAULT_STALE_AFTER_S,
    build_run_health_model,
    discover_xmuse_runtime_processes,
    list_live_pids,
    summarize_run_health,
)
from xmuse_core.platform.runner_recovery_proof import capture_runner_recovery_proof
from xmuse_core.platform.runner_session import (
    RUNNER_SESSION_COMPLETED_STATUS,
    RUNNER_SESSION_FAILED_STATUS,
    capture_runner_session_finished,
    capture_runner_session_started,
)
from xmuse_core.providers.registry import DEFAULT_CODEX_GOD_MODEL_ID
from xmuse_core.runtime.paths import default_xmuse_root, resolve_xmuse_root
from xmuse_core.self_evolution import SelfEvolutionController
from xmuse_core.self_evolution.watcher import TerminalRunWatcher
from xmuse_core.structuring.blueprint_execution import BlueprintAutomationService
from xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts import (
    lane_recovery_artifact_path,
)
from xmuse_core.structuring.feature_review_contracts import (
    CommandEvidence,
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureVerificationEvidence,
    FeatureWorkerNotes,
    LaneGraphEvidenceSummary,
)
from xmuse_core.structuring.ready_set import (
    build_graph_ready_set,
    build_ready_set_parity_evidence,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XMUSE_ROOT = default_xmuse_root(ROOT / "xmuse")
DEFAULT_BLUEPRINT = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-05-28-xmuse-initial-self-evolution-blueprint.md"
)
logger = logging.getLogger(__name__)
PLANNING_AUTOMATION_WORKER_ID = "platform-runner"
WRITER_LEASE_TTL_S = 60.0
WRITER_LEASE_RENEW_INTERVAL_S = WRITER_LEASE_TTL_S / 3


async def run(
    lanes_path: Path,
    xmuse_root: Path,
    mcp_port: int,
    max_hours: float,
    max_concurrent: int,
    graph_id: str | None = None,
    resolution_id: str | None = None,
    require_final_action_approval: bool = False,
    god_runtime: str | None = None,
    auto_evolve: bool = False,
    blueprint_path: Path | None = None,
    decomposer_kind: str = "single",
    chat_driver_enabled: bool = False,
    chat_driver_model: str = DEFAULT_CODEX_GOD_MODEL_ID,
    peer_chat_enabled: bool = False,
    persistent_review_god_enabled: bool = False,
    persistent_review_timeout_s: float | None = None,
    default_review_peer_routing_enabled: bool = False,
    persistent_execute_god_enabled: bool = False,
    peer_chat_scheduler=None,
    memoryos_url: str | None = None,
    model_policy: CodexModelPolicy | None = None,
    execution_provider_profile_ref: str | None = None,
    review_provider_profile_ref: str | None = None,
    runner_recovery_proof_output: Path | None = None,
    local_execution_candidate_output_dir: Path | None = None,
    local_execution_candidate_capture_enabled: bool = True,
) -> None:
    runner_id = _default_runner_id()
    local_execution_run_id = f"local-execution-{runner_id}"
    runner_session_id = f"runner-session-{uuid.uuid4().hex}"
    runner_session_ref = f"work/runner_sessions/{runner_session_id}.json"
    runner_session_path = xmuse_root / runner_session_ref
    runner_session_candidate_refs: list[str] = []
    runner_session_candidate_lane_ids: list[str] = []
    runner_session_worker_evidence_bundle_refs: list[str] = []
    runner_session_failure: str | None = None
    runner_session_dispatch_failures: dict[str, str] = {}
    runner_session_candidate_capture_failures: dict[str, str] = {}
    control_service = CoordinatorControlService(
        xmuse_root=xmuse_root,
        runner_id=runner_id,
    )
    writer_lease: dict[str, Any] | None = None
    writer_lease_heartbeat_task: asyncio.Task | None = None
    writer_lease_heartbeat_stop: asyncio.Event | None = None
    writer_lease_lost: asyncio.Event | None = None
    in_flight: set[asyncio.Task] = set()
    in_flight_lane_ids: set[str] = set()
    reconcile_task: asyncio.Task | None = None
    runtime_god_layers: list[Any] = []
    chat_dispatch_bridge = None
    try:
        memoryos_client = (
            MemoryOSClient(base_url=memoryos_url)
            if memoryos_url is not None
            else None
        )
        from xmuse_core.agents.god_session_layer import GodSessionLayer
        from xmuse_core.agents.launchers import build_default_launchers

        if model_policy is not None:
            launchers = build_default_launchers(
                mcp_port=mcp_port,
                codex_model=model_policy.review_model,
            )
        else:
            launchers = build_default_launchers(mcp_port=mcp_port)
        if (
            persistent_review_god_enabled or persistent_execute_god_enabled
        ) and not _has_persistent_session_launcher(launchers):
            raise RuntimeError(
                "--persistent-review-god/--persistent-execute-god requires "
                "a launcher that supports xmuse persistent sessions"
            )
        writer_lease = _acquire_writer_lease(lanes_path, runner_id=runner_id)
        capture_runner_session_started(
            output_path=runner_session_path,
            session_id=runner_session_id,
            run_id=local_execution_run_id,
            runner_id=runner_id,
            lanes_path=lanes_path,
            xmuse_root=xmuse_root,
            graph_id=graph_id,
            resolution_id=resolution_id,
            writer_lease_id=str(writer_lease["lease_id"]),
        )
        control_service.record_lifecycle(
            "writer_lease_acquired",
            details={
                "lanes_path": str(lanes_path),
                "lease_id": str(writer_lease["lease_id"]),
                "runner_session_id": runner_session_id,
                "runner_session_ref": runner_session_ref,
            },
        )
        god_session_layer = GodSessionLayer(
            registry_path=xmuse_root / "god_sessions.json",
            launchers=launchers,
        )
        orchestrator_kwargs: dict[str, Any] = {
            "lanes_path": lanes_path,
            "xmuse_root": xmuse_root,
            "mcp_port": mcp_port,
            "require_final_action_approval": require_final_action_approval,
            "god_runtime": god_runtime,
            "runner_id": runner_id,
            "memoryos_client": memoryos_client,
            "review_god_session_layer": None,
        }
        if persistent_review_god_enabled:
            review_god_layer = _build_review_god_layer(
                backend=os.environ.get("XMUSE_REVIEW_GOD_BACKEND", "ray"),
                native_layer=god_session_layer,
                launchers=launchers,
                xmuse_root=xmuse_root,
            )
            prewarm = getattr(review_god_layer, "prewarm", None)
            if callable(prewarm):
                await prewarm()
            orchestrator_kwargs["review_god_session_layer"] = review_god_layer
            runtime_god_layers.append(review_god_layer)
        if persistent_review_timeout_s is not None:
            orchestrator_kwargs["persistent_review_receive_timeout_s"] = (
                persistent_review_timeout_s
            )
        if model_policy is not None:
            orchestrator_kwargs["model_policy"] = model_policy
        if default_review_peer_routing_enabled:
            orchestrator_kwargs["default_review_peer_routing_enabled"] = True
        if persistent_execute_god_enabled:
            execute_god_layer = _build_execution_god_layer(
                backend=os.environ.get("XMUSE_EXECUTE_GOD_BACKEND", "ray"),
                native_layer=god_session_layer,
                launchers=launchers,
                xmuse_root=xmuse_root,
            )
            prewarm = getattr(execute_god_layer, "prewarm", None)
            if callable(prewarm):
                await prewarm()
            orchestrator_kwargs["persistent_execute_enabled"] = True
            orchestrator_kwargs["persistent_execute_session_layer"] = execute_god_layer
            runtime_god_layers.append(execute_god_layer)
        if execution_provider_profile_ref is not None:
            orchestrator_kwargs["execution_provider_profile_ref"] = (
                execution_provider_profile_ref
            )
        if review_provider_profile_ref is not None:
            orchestrator_kwargs["review_provider_profile_ref"] = review_provider_profile_ref
        orch = PlatformOrchestrator(**orchestrator_kwargs)
        resolved_local_execution_candidate_output_dir = (
            _local_execution_candidate_output_dir(
                xmuse_root=xmuse_root,
                configured=local_execution_candidate_output_dir,
                enabled=local_execution_candidate_capture_enabled,
            )
        )

        watcher: TerminalRunWatcher | None = None
        if auto_evolve:
            decomposer = _build_decomposer(decomposer_kind)
            controller = SelfEvolutionController(
                xmuse_root=xmuse_root,
                blueprint_path=blueprint_path or DEFAULT_BLUEPRINT,
                decomposer=decomposer,
            )
            watcher = TerminalRunWatcher(controller)
            logger.info(
                "Auto-evolve enabled (blueprint=%s, decomposer=%s)",
                controller._blueprint_path,
                decomposer_kind,
            )

        chat_driver: ChatDriver | None = None
        if chat_driver_enabled:
            chat_driver = ChatDriver(
                chat_db_path=xmuse_root / "chat.db",
                model=chat_driver_model,
            )
            logger.info("Chat driver enabled (model=%s)", chat_driver_model)

        if (
            peer_chat_enabled
            and peer_chat_scheduler is None
            and _has_persistent_session_launcher(launchers)
        ):
            from xmuse_core.chat.peer_scheduler import PeerChatScheduler

            peer_god_layer = _build_peer_god_layer(
                backend=os.environ.get("XMUSE_PEER_GOD_BACKEND", "ray"),
                native_layer=god_session_layer,
                launchers=launchers,
                xmuse_root=xmuse_root,
            )
            peer_god_layer = await _prewarm_peer_god_layer_or_fallback(
                peer_god_layer,
                native_layer=god_session_layer,
            )
            runtime_god_layers.append(peer_god_layer)
            peer_chat_scheduler = PeerChatScheduler(
                db_path=xmuse_root / "chat.db",
                god_layer=peer_god_layer,
                worktree=ROOT,
                scheduler_id="platform-runner",
                claim_ttl_s=240,
                response_wait_s=180.0,
                degraded_fallback_enabled=False,
            )
            logger.info(
                "Peer chat scheduler enabled (god_backend=%s)",
                type(peer_god_layer).__name__,
            )
            from xmuse_core.chat.dispatch_bridge import ChatDispatchBridge

            chat_dispatch_bridge = ChatDispatchBridge(
                db_path=xmuse_root / "chat.db",
                god_layer=peer_god_layer,
                worktree=ROOT,
                bridge_id="platform-runner-dispatch",
                claim_ttl_s=240,
                response_wait_s=180.0,
            )
        elif peer_chat_enabled and peer_chat_scheduler is None:
            logger.warning(
                "Peer chat scheduler disabled: no launcher supports xmuse persistent sessions"
            )

        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, shutdown.set)
            except NotImplementedError:
                pass
        writer_lease_heartbeat_stop = asyncio.Event()
        writer_lease_lost = asyncio.Event()
        writer_lease_heartbeat_task = asyncio.create_task(
            _writer_lease_heartbeat_loop(
                lanes_path,
                lease_id=writer_lease["lease_id"],
                runner_id=runner_id,
                stop=writer_lease_heartbeat_stop,
                lost=writer_lease_lost,
            )
        )

        deadline = loop.time() + max_hours * 3600
        semaphore = asyncio.Semaphore(max_concurrent)
        blueprint_automation_service: BlueprintAutomationService | None = None
        logger.info("Platform started, max_hours=%.1f, concurrency=%d", max_hours, max_concurrent)
        control_service.record_lifecycle(
            "started",
            details={
                "lanes_path": str(lanes_path),
                "max_hours": max_hours,
                "max_concurrent": max_concurrent,
            },
        )

        while not shutdown.is_set() and loop.time() < deadline:
            if writer_lease_lost.is_set():
                raise RuntimeError(
                    "writer lease lost during heartbeat; refusing to continue dispatch"
                )
            renewed = _renew_writer_lease(
                lanes_path,
                lease_id=writer_lease["lease_id"],
                runner_id=runner_id,
            )
            if renewed is None:
                writer_lease_lost.set()
                raise RuntimeError(
                    "writer lease lost before reconcile; refusing to continue dispatch"
                )
            writer_lease = renewed
            _repair_stale_dispatched_lanes(
                orch,
                xmuse_root=xmuse_root,
                owned_lane_ids=in_flight_lane_ids,
            )
            if blueprint_automation_service is None:
                blueprint_automation_service = BlueprintAutomationService(base_dir=xmuse_root)
            control_service.drive_blueprint_automation(
                blueprint_automation_service,
                worker_id=PLANNING_AUTOMATION_WORKER_ID,
            )
            if watcher is not None and not in_flight:
                control_service.drive_auto_evolve(watcher)
            if chat_driver is not None:
                control_service.drive_chat(chat_driver)
            if peer_chat_scheduler is not None:
                await control_service.tick_peer_chat_scheduler(peer_chat_scheduler)
            if chat_dispatch_bridge is not None:
                await _tick_chat_dispatch_bridge(chat_dispatch_bridge, xmuse_root=xmuse_root)
            pending = _candidate_lanes(
                orch,
                xmuse_root=xmuse_root,
                graph_id=graph_id,
                resolution_id=resolution_id,
            )
            _capture_runner_recovery_proof_if_requested(
                output_path=runner_recovery_proof_output,
                run_id=f"local-runner-recovery-{runner_id}",
                runner_id=runner_id,
                orch=orch,
                candidate_lanes=pending,
                lanes_path=lanes_path,
                xmuse_root=xmuse_root,
                graph_id=graph_id,
                resolution_id=resolution_id,
            )
            if pending:
                pending.sort(key=lambda lane: -lane.get("priority", 0))

                for lane in pending:
                    if writer_lease_lost.is_set():
                        raise RuntimeError(
                            "writer lease lost during heartbeat; refusing to dispatch lane"
                        )
                    if len(in_flight) >= max_concurrent:
                        done, in_flight = await asyncio.wait(
                            in_flight, return_when=asyncio.FIRST_COMPLETED
                        )
                        in_flight = set(in_flight)
                        if writer_lease_lost.is_set():
                            raise RuntimeError(
                                "writer lease lost during heartbeat; refusing to dispatch lane"
                            )
                    lane_id = lane["feature_id"]
                    logger.info(
                        "Dispatching lane: %s (priority=%d)", lane_id, lane.get("priority", 0)
                    )

                    async def _run(lid: str, lane_snapshot: dict[str, Any]) -> None:
                        async with semaphore:
                            await orch.dispatch_lane(lid)
                            worker_evidence_ref: str | None = None
                            try:
                                worker_evidence = (
                                    _submit_graph_native_worker_evidence_if_possible(
                                        run_id=local_execution_run_id,
                                        runner_id=runner_id,
                                        runner_session_id=runner_session_id,
                                        runner_session_ref=runner_session_ref,
                                        xmuse_root=xmuse_root,
                                        orch=orch,
                                        lane_id=lid,
                                        lane_snapshot=lane_snapshot,
                                    )
                                )
                                if worker_evidence is not None:
                                    worker_evidence_ref = _text(
                                        worker_evidence.get("artifact_ref")
                                    )
                                    if worker_evidence_ref is not None:
                                        runner_session_worker_evidence_bundle_refs.append(
                                            worker_evidence_ref
                                        )
                            except Exception:
                                logger.warning(
                                    "Graph-native worker evidence handoff failed for "
                                    "lane %s; local execution candidate will remain "
                                    "candidate-only or manual-gap evidence",
                                    lid,
                                    exc_info=True,
                                )
                            try:
                                latest_lane = _latest_lane_snapshot(
                                    orch=orch,
                                    lane_id=lid,
                                    fallback=lane_snapshot,
                                )
                                candidate_capture = (
                                    _capture_local_execution_candidate_if_requested(
                                        output_dir=(
                                            resolved_local_execution_candidate_output_dir
                                        ),
                                        run_id=local_execution_run_id,
                                        runner_id=runner_id,
                                        runner_session_id=runner_session_id,
                                        runner_session_ref=runner_session_ref,
                                        xmuse_root=xmuse_root,
                                        orch=orch,
                                        lane=latest_lane,
                                        graph_id=graph_id,
                                        resolution_id=resolution_id,
                                        worker_evidence_ref=worker_evidence_ref,
                                    )
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Local execution candidate capture failed for "
                                    "lane %s; dispatch result remains candidate-only "
                                    "unproven",
                                    lid,
                                    exc_info=True,
                                )
                                runner_session_candidate_capture_failures.setdefault(
                                    lid,
                                    (
                                        f"{lid}: {type(exc).__name__}: "
                                        f"{exc}"
                                    ),
                                )
                                candidate_capture = None
                            candidate_artifact = (
                                candidate_capture.get("artifact")
                                if candidate_capture is not None
                                else None
                            )
                            candidate_is_runtime_proof = (
                                isinstance(candidate_artifact, dict)
                                and candidate_artifact.get("status") == "candidate_only"
                                and candidate_artifact.get("proof_level")
                                == "local_runtime_proof"
                            )
                            if candidate_capture is not None and candidate_is_runtime_proof:
                                runner_session_candidate_refs.append(
                                    candidate_capture["artifact_ref"]
                                )
                                runner_session_candidate_lane_ids.append(lid)

                    task = asyncio.create_task(_run(lane_id, dict(lane)))
                    in_flight.add(task)
                    in_flight_lane_ids.add(lane_id)

                    def _record_finished_lane_task(
                        finished: asyncio.Task,
                        *,
                        finished_lane_id: str = lane_id,
                    ) -> None:
                        in_flight_lane_ids.discard(finished_lane_id)
                        if finished.cancelled():
                            runner_session_dispatch_failures.setdefault(
                                finished_lane_id,
                                f"{finished_lane_id}: CancelledError",
                            )
                            return
                        exc = finished.exception()
                        if exc is None:
                            return
                        failure = f"{finished_lane_id}: {type(exc).__name__}: {exc}"
                        runner_session_dispatch_failures.setdefault(
                            finished_lane_id,
                            failure,
                        )
                        logger.error(
                            "runner dispatch task failed for lane %s: %s",
                            finished_lane_id,
                            exc,
                            exc_info=(type(exc), exc, exc.__traceback__),
                        )

                    task.add_done_callback(in_flight.discard)
                    task.add_done_callback(_record_finished_lane_task)

            if reconcile_task is None or reconcile_task.done():
                reconcile_task = asyncio.create_task(
                    _reconcile_status_changes(orch, dispatch_reworking=False)
                )
                reconcile_task.add_done_callback(_log_background_task_exception)
            if pending:
                await asyncio.sleep(5.0)
            else:
                try:
                    idle_wait_s = 1.0 if peer_chat_scheduler is not None else 10.0
                    await asyncio.wait_for(shutdown.wait(), timeout=idle_wait_s)
                except TimeoutError:
                    pass

        if in_flight:
            await asyncio.gather(*in_flight, return_exceptions=True)
        if runner_session_dispatch_failures:
            runner_session_failure = "dispatch task failure: " + "; ".join(
                runner_session_dispatch_failures[lane_id]
                for lane_id in sorted(runner_session_dispatch_failures)
            )
        elif runner_session_candidate_capture_failures:
            runner_session_failure = (
                "local execution candidate capture failure: "
                + "; ".join(
                    runner_session_candidate_capture_failures[lane_id]
                    for lane_id in sorted(runner_session_candidate_capture_failures)
                )
            )
        logger.info("Platform shutting down")
    except BaseException as exc:
        runner_session_failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if runner_session_path.exists():
            try:
                capture_runner_session_finished(
                    output_path=runner_session_path,
                    status=(
                        RUNNER_SESSION_FAILED_STATUS
                        if runner_session_failure
                        else RUNNER_SESSION_COMPLETED_STATUS
                    ),
                    candidate_artifact_refs=runner_session_candidate_refs,
                    candidate_lane_ids=runner_session_candidate_lane_ids,
                    worker_evidence_bundle_refs=(
                        runner_session_worker_evidence_bundle_refs
                    ),
                    failure=runner_session_failure,
                )
            except Exception:
                logger.exception(
                    "runner session finish capture failed; continuing shutdown",
                    extra={
                        "runner_session_id": runner_session_id,
                        "runner_session_ref": runner_session_ref,
                    },
                )
        control_service.record_lifecycle(
            "stopping",
            details={
                "lanes_path": str(lanes_path),
                "in_flight_count": len(in_flight),
                "runner_session_id": runner_session_id,
                "runner_session_ref": runner_session_ref,
            },
        )
        if reconcile_task is not None and not reconcile_task.done():
            reconcile_task.cancel()
            with suppress(asyncio.CancelledError):
                await reconcile_task
        if writer_lease_heartbeat_stop is not None:
            writer_lease_heartbeat_stop.set()
        if writer_lease_heartbeat_task is not None:
            writer_lease_heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await writer_lease_heartbeat_task
        if in_flight:
            for task in list(in_flight):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*list(in_flight), return_exceptions=True)
            in_flight.clear()
            in_flight_lane_ids.clear()
        await _shutdown_runtime_god_layers(runtime_god_layers)
        if writer_lease is not None:
            _release_writer_lease(
                lanes_path,
                lease_id=writer_lease["lease_id"],
                runner_id=runner_id,
            )


def _default_runner_id() -> str:
    return f"runner-{os.getpid()}"


async def _shutdown_runtime_god_layers(layers: list[Any]) -> None:
    seen: set[int] = set()
    for layer in layers:
        layer_id = id(layer)
        if layer_id in seen:
            continue
        seen.add(layer_id)
        shutdown = getattr(layer, "shutdown", None)
        if not callable(shutdown):
            continue
        result = shutdown()
        if inspect.isawaitable(result):
            await result


def _writer_lease_path(lanes_path: Path) -> Path:
    return lanes_path.with_name(f"{lanes_path.name}.writer_lease.json")


@contextmanager
def _locked_writer_lease(lanes_path: Path):
    lease_path = _writer_lease_path(lanes_path)
    lock_path = lease_path.with_name(f"{lease_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield lease_path
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read_writer_lease(lease_path: Path) -> dict[str, Any] | None:
    if not lease_path.exists():
        return None
    return json.loads(lease_path.read_text(encoding="utf-8"))


def _lease_is_active(lease: dict[str, Any] | None, *, now: float) -> bool:
    if not isinstance(lease, dict):
        return False
    expires_at = lease.get("expires_at")
    return (
        isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and now < expires_at
    )


def _acquire_writer_lease(
    lanes_path: Path,
    *,
    runner_id: str,
    now: float | None = None,
    ttl_s: float = WRITER_LEASE_TTL_S,
) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    with _locked_writer_lease(lanes_path) as lease_path:
        existing = _read_writer_lease(lease_path)
        if _lease_is_active(existing, now=current_time):
            existing_runner_id = existing.get("runner_id")
            if existing_runner_id != runner_id:
                raise RuntimeError(
                    "active writer lease already held by "
                    f"{existing_runner_id} until {existing.get('expires_at')}"
                )
        reclaimed_from_runner_id = None
        if isinstance(existing, dict) and not _lease_is_active(existing, now=current_time):
            reclaimed_from_runner_id = existing.get("runner_id")
        lease = {
            "runner_id": runner_id,
            "lease_id": f"lease-{uuid.uuid4().hex[:12]}",
            "heartbeat_at": current_time,
            "expires_at": current_time + ttl_s,
        }
        if reclaimed_from_runner_id and reclaimed_from_runner_id != runner_id:
            lease["reclaimed_from_runner_id"] = reclaimed_from_runner_id
        lease_path.write_text(json.dumps(lease, indent=2) + "\n", encoding="utf-8")
        return lease


def _renew_writer_lease(
    lanes_path: Path,
    *,
    lease_id: str,
    runner_id: str,
    now: float | None = None,
    ttl_s: float = WRITER_LEASE_TTL_S,
) -> dict[str, Any] | None:
    current_time = time.time() if now is None else now
    with _locked_writer_lease(lanes_path) as lease_path:
        existing = _read_writer_lease(lease_path)
        if not isinstance(existing, dict):
            return None
        if existing.get("lease_id") != lease_id or existing.get("runner_id") != runner_id:
            return None
        existing["heartbeat_at"] = current_time
        existing["expires_at"] = current_time + ttl_s
        lease_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return existing


def _release_writer_lease(
    lanes_path: Path,
    *,
    lease_id: str,
    runner_id: str,
) -> None:
    with _locked_writer_lease(lanes_path) as lease_path:
        existing = _read_writer_lease(lease_path)
        if not isinstance(existing, dict):
            return
        if existing.get("lease_id") != lease_id or existing.get("runner_id") != runner_id:
            return
        lease_path.unlink(missing_ok=True)


async def _writer_lease_heartbeat_loop(
    lanes_path: Path,
    *,
    lease_id: str,
    runner_id: str,
    stop: asyncio.Event,
    lost: asyncio.Event,
    interval_s: float = WRITER_LEASE_RENEW_INTERVAL_S,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            continue
        except TimeoutError:
            pass

        renewed = _renew_writer_lease(
            lanes_path,
            lease_id=lease_id,
            runner_id=runner_id,
        )
        if renewed is None:
            lost.set()
            stop.set()
            log_payload = {
                "runner_id": runner_id,
                "lease_id": lease_id,
                "lanes_path": str(lanes_path),
            }
            logger.error("writer lease heartbeat lost: %s", log_payload)
            return


def _drive_auto_evolve(watcher: TerminalRunWatcher) -> None:
    try:
        outcomes = watcher.tick()
    except Exception:
        logger.exception("auto-evolve tick failed; continuing")
        return
    for outcome in outcomes:
        if outcome.spawned is not None:
            logger.info(
                "auto-evolve: spawned %s from %s",
                outcome.spawned.spawned_graph_id,
                outcome.source_run_id,
            )
        elif outcome.skip_reason:
            logger.debug(
                "auto-evolve: skipped %s (%s)",
                outcome.source_run_id,
                outcome.skip_reason,
            )


def _drive_blueprint_automation(
    service: BlueprintAutomationService,
    *,
    worker_id: str,
) -> None:
    try:
        outcome = service.tick(worker_id=worker_id)
    except Exception:
        logger.exception("blueprint automation tick failed; continuing")
        return
    if outcome is not None:
        logger.info(
            "blueprint automation: started planning_run=%s from event=%s",
            outcome.planning_run_id,
            outcome.claimed_event_id,
        )


def _drive_chat(driver: ChatDriver) -> None:
    try:
        outcomes = driver.tick()
    except Exception:
        logger.exception("chat-driver tick failed; continuing")
        return
    for outcome in outcomes:
        if outcome.reply_message_id:
            logger.info(
                "chat-driver: %s replied in %s (envelope=%s)",
                outcome.god_role,
                outcome.conversation_id,
                outcome.envelope_type,
            )
        elif outcome.skip_reason:
            logger.warning(
                "chat-driver: %s skipped %s (%s)",
                outcome.god_role,
                outcome.source_message_id,
                outcome.skip_reason,
            )


async def _tick_chat_dispatch_bridge(chat_dispatch_bridge, *, xmuse_root: Path) -> None:
    from xmuse_core.chat.store import ChatStore

    try:
        conversations = ChatStore(xmuse_root / "chat.db").list_conversations()
    except Exception:
        logger.exception("chat dispatch bridge could not list conversations")
        return
    for conversation in conversations:
        try:
            await chat_dispatch_bridge.tick_once(conversation_id=conversation.id)
        except Exception:
            logger.exception(
                "chat dispatch bridge tick failed for conversation %s",
                conversation.id,
            )


async def _reconcile_status_changes(
    orch: PlatformOrchestrator,
    *,
    dispatch_reworking: bool,
) -> None:
    signature = inspect.signature(orch.reconcile_status_changes)
    if (
        "dispatch_reworking" in signature.parameters
        or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
    ):
        await orch.reconcile_status_changes(dispatch_reworking=dispatch_reworking)
        return
    await orch.reconcile_status_changes()


def _log_background_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("background reconcile task failed")


def _build_decomposer(kind: str):
    """Pick the decomposer backend.

    ``single`` (default) is the backward-compatible one-rich-lane behavior.
    ``deterministic-multi`` produces a 3-lane design/impl/tests chain per
    track. ``peer-chat`` shells out to codex exec once per chain step and
    parses a multi-feature JSON plan; falls back to ``single`` on failure.
    Returning ``None`` lets the controller construct its built-in default.
    """
    if kind == "single":
        return None  # controller wires SingleLaneDecomposer with its own factories
    if kind == "deterministic-multi":
        from xmuse_core.self_evolution.decomposer import DeterministicMultiLaneDecomposer

        return DeterministicMultiLaneDecomposer()
    if kind == "peer-chat":
        from xmuse_core.self_evolution.decomposer import SingleLaneDecomposer
        from xmuse_core.self_evolution.peer_chat_decomposer import PeerChatDecomposer

        # Closures referencing the controller's per-track factories happen
        # *after* controller construction; here we use track-only fallback
        # factories so PeerChatDecomposer can degrade without controller refs.
        fallback = SingleLaneDecomposer(
            lane_id_factory=lambda evidence, track: (
                f"self-evolution-{track}-{evidence.source_run_id}"[:120]
            ),
            prompt_factory=lambda evidence, track: (
                f"Implement the next xmuse self-evolution improvement for "
                f"track {track}. Use evidence bundle {evidence.bundle_id}. "
                f"Preserve chat -> proposal -> approved resolution -> lane "
                f"graph -> execution as the mainline."
            ),
        )
        return PeerChatDecomposer(fallback=fallback)
    raise ValueError(f"unknown decomposer kind: {kind!r}")


def _candidate_lanes(
    orch: PlatformOrchestrator,
    *,
    xmuse_root: Path,
    graph_id: str | None,
    resolution_id: str | None,
) -> list[dict]:
    all_lanes = orch._sm.get_lanes()
    lane_status_by_id = {
        lane.get("feature_id"): lane.get("status")
        for lane in all_lanes
        if isinstance(lane.get("feature_id"), str)
    }
    lanes_by_id: dict[str, dict] = {}
    for status in ("pending", "reworking"):
        for lane in orch._sm.get_lanes(status=status):
            lane_id = lane.get("feature_id")
            if isinstance(lane_id, str):
                lanes_by_id[lane_id] = lane

    lanes = list(lanes_by_id.values())
    if graph_id is not None:
        lanes = [lane for lane in lanes if lane.get("graph_id") == graph_id]
    if resolution_id is not None:
        lanes = [lane for lane in lanes if lane.get("resolution_id") == resolution_id]
    legacy_candidates = [
        lane for lane in lanes
        if _dependencies_satisfied(lane, lane_status_by_id)
    ]
    dispatchable_candidates = [
        lane
        for lane in legacy_candidates
        if _runner_recovery_authority_allows_lane(
            orch,
            lane,
            xmuse_root=xmuse_root,
        )
    ]
    ready_set_candidates = build_graph_ready_set(
        all_lanes,
        graph_id=graph_id,
        resolution_id=resolution_id,
    )
    parity_evidence = build_ready_set_parity_evidence(
        legacy_candidates=dispatchable_candidates,
        ready_set_candidates=ready_set_candidates,
        graph_id=graph_id,
        resolution_id=resolution_id,
    )
    return [
        {**lane, "ready_set_parity": dict(parity_evidence)}
        for lane in dispatchable_candidates
    ]


def _runner_recovery_authority_allows_lane(
    orch: PlatformOrchestrator,
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
) -> bool:
    """Apply durable L8 recovery authority before runner task scheduling."""
    recovery_authority = _RunnerRecoveryAuthority(root=xmuse_root)
    recovery_lane = _runner_recovery_authority_lane(lane)
    recovery_block = build_lane_recovery_dispatch_block_metadata(
        recovery_authority,
        recovery_lane,
    )
    if recovery_block is None:
        return True

    lane_id = str(lane.get("feature_id") or "")
    update_metadata = getattr(getattr(orch, "_sm", None), "update_metadata", None)
    if lane_id and callable(update_metadata):
        update_metadata(lane_id, recovery_block)
    logger.warning(
        "runner_candidate_blocked_by_recovery_decision",
        extra={
            "lane_id": lane_id,
            "graph_id": lane.get("graph_id"),
            "reason": recovery_block["recovery_dispatch_block_reason"],
            "source_authority": "lane_recovery_artifact",
        },
    )
    return False


class _RunnerRecoveryAuthority:
    def __init__(self, *, root: Path) -> None:
        self._root = root


def _runner_recovery_authority_lane(lane: dict[str, Any]) -> dict[str, Any]:
    recovery_lane_id = _text(lane.get("lane_local_id")) or _text(lane.get("feature_id"))
    if recovery_lane_id is None or recovery_lane_id == _text(lane.get("feature_id")):
        return lane
    return {**lane, "feature_id": recovery_lane_id}


def _capture_runner_recovery_proof_if_requested(
    *,
    output_path: Path | None,
    run_id: str,
    runner_id: str,
    orch: PlatformOrchestrator,
    candidate_lanes: list[dict[str, Any]],
    lanes_path: Path,
    xmuse_root: Path,
    graph_id: str | None,
    resolution_id: str | None,
) -> dict[str, Any] | None:
    if output_path is None:
        return None
    process_inventory = discover_xmuse_runtime_processes()
    lanes = list(orch._sm.get_lanes())
    runner_status = {
        "pid_file": None,
        "health": build_run_health_model(
            lanes_path,
            runner_pids=process_inventory["runner_pids"],
            mcp_pids=process_inventory["mcp_pids"],
            live_pids=_live_pids(),
            xmuse_root=xmuse_root,
            process_inventory=process_inventory,
        ),
    }
    return capture_runner_recovery_proof(
        output_path=output_path,
        run_id=run_id,
        runner_id=runner_id,
        lanes=lanes,
        candidate_lanes=candidate_lanes,
        runner_status=runner_status,
        lanes_path=lanes_path,
        xmuse_root=xmuse_root,
        graph_id=graph_id,
        resolution_id=resolution_id,
    )


def _submit_graph_native_worker_evidence_if_possible(
    *,
    run_id: str,
    runner_id: str,
    runner_session_id: str,
    runner_session_ref: str,
    xmuse_root: Path,
    orch: PlatformOrchestrator,
    lane_id: str,
    lane_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    lane = _latest_lane_snapshot(orch=orch, lane_id=lane_id, fallback=lane_snapshot)
    if _lane_status_blocks_worker_evidence_submission(lane):
        return None
    lane_ref = _text(lane.get("feature_id") or lane.get("lane_id") or lane_id)
    if lane_ref is None:
        return None
    lane_local_id = _text(lane.get("lane_local_id")) or lane_ref
    graph_set_id = _text(lane.get("graph_set_id"))
    feature_graph_id = _text(lane.get("graph_id"))
    conversation_id = _text(lane.get("conversation_id"))
    if graph_set_id is None or feature_graph_id is None or conversation_id is None:
        return None

    status = _feature_graph_status_record(
        orch=orch,
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
    )
    if status is None:
        return None

    provider_session_binding_ref = _provider_session_binding_ref(lane)
    blueprint_refs = _string_list(lane.get("blueprint_refs"))
    acceptance_criteria = _string_list(lane.get("acceptance_criteria"))
    required_checks = _string_list(lane.get("required_checks"))
    if (
        provider_session_binding_ref is None
        or _text(status.planning_run_id) is None
        or not blueprint_refs
        or not acceptance_criteria
        or not required_checks
    ):
        return None

    status_value = _feature_graph_status_value(status)
    active_lane_id = _status_lane_identity(
        status=status,
        lane_id=lane_ref,
        lane_local_id=lane_local_id,
    )
    if status_value == FeatureGraphExecutionStatus.RUNNING.value and (
        status.active_worker_session_id != runner_session_id
        or status.active_provider_session_binding_ref != provider_session_binding_ref
    ):
        return None

    evidence_bundle = _build_platform_runner_feature_evidence_bundle(
        status=status,
        lane=lane,
        run_id=run_id,
        runner_id=runner_id,
        runner_session_id=runner_session_id,
        runner_session_ref=runner_session_ref,
        completed_lane_id=active_lane_id,
        provider_session_binding_ref=provider_session_binding_ref,
        blueprint_refs=blueprint_refs,
        acceptance_criteria=acceptance_criteria,
        required_checks=required_checks,
    )
    updated_at = _utc_now()
    if status_value == FeatureGraphExecutionStatus.READY.value:
        claim_worker = getattr(orch, "claim_next_ready_feature_graph_worker", None)
        if not callable(claim_worker):
            return None
        outcome = claim_worker(
            graph_set_id=graph_set_id,
            conversation_id=conversation_id,
            feature_graph_id=feature_graph_id,
            worker_session_id=runner_session_id,
            provider_session_binding_ref=provider_session_binding_ref,
            updated_at=updated_at,
            active_lane_ids=[active_lane_id],
        )
        if outcome is None:
            return None
        status = outcome.status
        status_value = _feature_graph_status_value(status)

    if status_value != FeatureGraphExecutionStatus.RUNNING.value:
        return None
    if (
        status.active_worker_session_id != runner_session_id
        or status.active_provider_session_binding_ref != provider_session_binding_ref
    ):
        return None
    evidence_bundle_ref = f"feature_evidence_bundle:{evidence_bundle.bundle_id}:v1"
    submit_evidence = getattr(orch, "submit_feature_graph_worker_evidence", None)
    if not callable(submit_evidence):
        return None
    outcome = submit_evidence(
        evidence_bundle=evidence_bundle,
        evidence_bundle_ref=evidence_bundle_ref,
        updated_at=_utc_now(),
    )
    return {
        "artifact_ref": evidence_bundle_ref,
        "status": outcome.status,
        "evidence_bundle": evidence_bundle,
    }


def _build_platform_runner_feature_evidence_bundle(
    *,
    status: FeatureGraphExecutionStatusRecord,
    lane: dict[str, Any],
    run_id: str,
    runner_id: str,
    runner_session_id: str,
    runner_session_ref: str,
    completed_lane_id: str,
    provider_session_binding_ref: str,
    blueprint_refs: list[str],
    acceptance_criteria: list[str],
    required_checks: list[str],
) -> FeatureEvidenceBundle:
    lane_ref = _text(lane.get("feature_id") or lane.get("lane_id")) or completed_lane_id
    safe_graph = _safe_artifact_fragment(status.feature_graph_id)
    safe_lane = _safe_artifact_fragment(lane_ref)
    allowed_files = _string_list(lane.get("allowed_files"))
    feature_goal = (
        _text(lane.get("prompt"))
        or _text(lane.get("prompt_summary"))
        or _text(lane.get("title"))
        or lane_ref
    )
    return FeatureEvidenceBundle(
        bundle_id=f"platform_runner_worker_evidence_{safe_graph}_{safe_lane}",
        conversation_id=status.conversation_id,
        planning_run_id=str(status.planning_run_id),
        feature_plan_id=status.feature_plan_id,
        feature_plan_version=status.feature_plan_version,
        graph_set_id=status.graph_set_id,
        graph_set_version=status.graph_set_version,
        feature_id=status.feature_id,
        feature_graph_id=status.feature_graph_id,
        worker_session_id=runner_session_id,
        provider_session_binding_ref=provider_session_binding_ref,
        blueprint_refs=blueprint_refs,
        blueprint_proof_level=status.blueprint_proof_level,
        feature_goal=feature_goal,
        acceptance_criteria=acceptance_criteria,
        lane_graph_summary=LaneGraphEvidenceSummary(
            feature_graph_id=status.feature_graph_id,
            lane_count=_graph_lane_count(status, completed_lane_id),
            completed_lane_ids=[completed_lane_id],
            blocked_lane_ids=list(status.blocked_lane_ids),
        ),
        touched_files=allowed_files,
        base_head_sha=_text(lane.get("base_head_sha")),
        branch=_text(lane.get("branch")),
        worktree=_text(lane.get("worktree")),
        changed_files=allowed_files,
        dependency_changes=[],
        verification=FeatureVerificationEvidence(
            commands_run=required_checks,
            test_results=[
                CommandEvidence(
                    command=command,
                    status="declared_for_independent_review",
                    evidence_ref=runner_session_ref,
                )
                for command in required_checks
            ],
            screenshots_or_logs=[runner_session_ref],
        ),
        worker_notes=FeatureWorkerNotes(
            implementation_summary=(
                "Platform runner dispatch returned and produced graph-native "
                "candidate evidence for independent review."
            ),
            decisions_made=[
                "Worker evidence is candidate input only; review truth requires "
                "an independent review verdict."
            ],
            risks_or_open_questions=[
                "Local runner evidence is not server truth, GitHub review truth, "
                "or merge truth."
            ],
        ),
        created_at=_utc_now(),
    )


def _latest_lane_snapshot(
    *,
    orch: PlatformOrchestrator,
    lane_id: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    state_machine = getattr(orch, "_sm", None)
    get_lane = getattr(state_machine, "get_lane", None)
    if not callable(get_lane):
        return dict(fallback)
    try:
        latest = get_lane(lane_id)
    except (KeyError, AttributeError, TypeError):
        return dict(fallback)
    return dict(latest) if isinstance(latest, dict) else dict(fallback)


def _lane_status_blocks_worker_evidence_submission(lane: dict[str, Any]) -> bool:
    status = _text(lane.get("status"))
    return status in {
        None,
        "pending",
        "reworking",
        "exec_failed",
        "gate_failed",
        "failed",
        "blocked",
    }


def _provider_session_binding_ref(lane: dict[str, Any]) -> str | None:
    value = _text(lane.get("provider_session_binding_ref")) or _text(
        lane.get("provider_session_binding_id")
    )
    if value is None or value.startswith("manual_gap:"):
        return None
    return value


def _feature_graph_status_record(
    *,
    orch: PlatformOrchestrator,
    graph_set_id: str | None,
    feature_graph_id: str | None,
) -> FeatureGraphExecutionStatusRecord | None:
    if graph_set_id is None or feature_graph_id is None:
        return None
    store = getattr(orch, "_feature_graph_status_store", None)
    get_status = getattr(store, "get", None)
    if not callable(get_status):
        return None
    try:
        record = get_status(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
    except (KeyError, ValueError, AttributeError):
        return None
    try:
        return FeatureGraphExecutionStatusRecord.model_validate(
            record.model_dump(mode="json")
            if hasattr(record, "model_dump")
            else {
                "status_id": record.status_id,
                "conversation_id": record.conversation_id,
                "planning_run_id": getattr(record, "planning_run_id", None),
                "graph_set_id": record.graph_set_id,
                "graph_set_version": record.graph_set_version,
                "feature_plan_id": record.feature_plan_id,
                "feature_plan_version": record.feature_plan_version,
                "feature_id": record.feature_id,
                "feature_graph_id": record.feature_graph_id,
                "blueprint_proof_level": getattr(
                    record,
                    "blueprint_proof_level",
                    None,
                ),
                "source_event_lineage": getattr(record, "source_event_lineage", []),
                "status": record.status,
                "ready_lane_ids": getattr(record, "ready_lane_ids", []),
                "active_lane_ids": getattr(record, "active_lane_ids", []),
                "completed_lane_ids": getattr(record, "completed_lane_ids", []),
                "blocked_lane_ids": getattr(record, "blocked_lane_ids", []),
                "projection_lane_ids": getattr(record, "projection_lane_ids", []),
                "feature_lanes_projection_ref": getattr(
                    record,
                    "feature_lanes_projection_ref",
                    None,
                ),
                "provider_session_binding_degradations": getattr(
                    record,
                    "provider_session_binding_degradations",
                    [],
                ),
                "updated_at": record.updated_at,
            }
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _feature_graph_status_value(record: FeatureGraphExecutionStatusRecord) -> str:
    status = record.status
    return getattr(status, "value", str(status))


def _status_lane_identity(
    *,
    status: FeatureGraphExecutionStatusRecord,
    lane_id: str,
    lane_local_id: str,
) -> str:
    known_ids = [
        *status.ready_lane_ids,
        *status.active_lane_ids,
        *status.completed_lane_ids,
    ]
    if lane_local_id in known_ids:
        return lane_local_id
    if lane_id in known_ids:
        return lane_id
    return lane_local_id


def _graph_lane_count(
    status: FeatureGraphExecutionStatusRecord,
    completed_lane_id: str,
) -> int:
    lane_ids = {
        *status.ready_lane_ids,
        *status.active_lane_ids,
        *status.completed_lane_ids,
        *status.blocked_lane_ids,
        completed_lane_id,
    }
    return len(lane_ids)


def _capture_local_execution_candidate_if_requested(
    *,
    output_dir: Path | None,
    run_id: str,
    runner_id: str,
    runner_session_id: str,
    runner_session_ref: str,
    xmuse_root: Path,
    orch: PlatformOrchestrator,
    lane: dict[str, Any],
    graph_id: str | None,
    resolution_id: str | None,
    worker_evidence_ref: str | None = None,
) -> dict[str, Any] | None:
    if output_dir is None:
        return None
    lane_id = _text(lane.get("feature_id") or lane.get("lane_id") or lane.get("id"))
    if lane_id is None:
        return None
    lane_local_id = _text(lane.get("lane_local_id")) or lane_id
    conversation_id = _text(lane.get("conversation_id"))
    feature_graph_id = _text(lane.get("graph_id"))
    graph_set_id = _text(lane.get("graph_set_id"))
    root_graph_id = graph_id or _root_graph_id_from_graph_set_id(graph_set_id)
    candidate_graph_id = root_graph_id or feature_graph_id
    graph_status_lineage = _local_execution_candidate_graph_status_lineage(
        orch=orch,
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
    )
    graph_status = (
        _text(graph_status_lineage.get("status"))
        if graph_status_lineage is not None
        else None
    )
    graph_status_reviewable = graph_status == "reviewing"
    candidate_status = (
        "candidate_only"
        if graph_status_lineage is not None and graph_status_reviewable
        else "manual_gap"
    )
    candidate_proof_level = (
        "local_runtime_proof"
        if graph_status_lineage is not None and graph_status_reviewable
        else "manual_gap"
    )
    manual_gaps = []
    if graph_status_lineage is not None and not graph_status_reviewable:
        manual_gaps = [
            "graph_native_worker_evidence_not_submitted",
            "local_execution_candidate_not_reviewable",
        ]
    output_path = output_dir / (
        f"{_safe_artifact_fragment(candidate_graph_id or 'graph')}"
        f".{_safe_artifact_fragment(lane_id)}.json"
    )
    artifact_ref = _relative_artifact_ref(root=xmuse_root, path=output_path)
    artifact = capture_local_execution_candidate(
        output_path=output_path,
        lane_id=lane_id,
        lane_local_id=lane_local_id,
        candidate_id=f"platform-runner:{run_id}:{lane_id}",
        conversation_id=conversation_id,
        graph_id=candidate_graph_id,
        graph_status_lineage=graph_status_lineage,
        run_id=run_id,
        worker_id=runner_id,
        runner_session_id=runner_session_id,
        runner_session_ref=runner_session_ref,
        producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        source_refs=_candidate_source_refs(
            lane_id=lane_id,
            lane_local_id=lane_local_id,
            graph_id=candidate_graph_id,
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
            feature_graph_status_id=(
                str(graph_status_lineage["status_id"])
                if graph_status_lineage is not None
                else None
            ),
            resolution_id=resolution_id,
            worker_evidence_ref=worker_evidence_ref,
        ),
        changed_file_refs=_string_list(lane.get("allowed_files")),
        verification_refs=_string_list(lane.get("required_checks")),
        proof_level=candidate_proof_level,
        status=candidate_status,
        manual_gaps=manual_gaps,
    )
    return {"artifact_ref": artifact_ref, "lane_id": lane_id, "artifact": artifact}


def _local_execution_candidate_output_dir(
    *,
    xmuse_root: Path,
    configured: Path | None,
    enabled: bool,
) -> Path | None:
    if not enabled:
        return None
    return configured or (xmuse_root / "work" / "local_execution_candidates")


def _relative_artifact_ref(*, root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _local_execution_candidate_graph_status_lineage(
    *,
    orch: PlatformOrchestrator,
    graph_set_id: str | None,
    feature_graph_id: str | None,
) -> dict[str, Any] | None:
    if graph_set_id is None or feature_graph_id is None:
        return None
    store = getattr(orch, "_feature_graph_status_store", None)
    get_status = getattr(store, "get", None)
    if not callable(get_status):
        return None
    try:
        record = get_status(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
    except (KeyError, ValueError, AttributeError):
        return None
    status = getattr(record, "status", None)
    status_value = getattr(status, "value", status)
    try:
        return {
            "source_authority": "feature_graph_status_store",
            "graph_set_id": str(record.graph_set_id),
            "feature_graph_id": str(record.feature_graph_id),
            "status_id": str(record.status_id),
            "status": str(status_value),
            "blueprint_proof_level": record.blueprint_proof_level,
            "active_lane_ids": list(record.active_lane_ids),
            "completed_lane_ids": list(record.completed_lane_ids),
            "source_event_lineage": [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in record.source_event_lineage
            ],
        }
    except (AttributeError, TypeError, ValueError):
        return None


def _candidate_source_refs(
    *,
    lane_id: str,
    lane_local_id: str | None,
    graph_id: str | None,
    graph_set_id: str | None,
    feature_graph_id: str | None,
    feature_graph_status_id: str | None,
    resolution_id: str | None,
    worker_evidence_ref: str | None = None,
) -> list[str]:
    refs = [f"lane:{lane_id}"]
    if lane_local_id and lane_local_id != lane_id:
        refs.append(f"lane_local:{lane_local_id}")
    if graph_id:
        refs.append(f"graph:{graph_id}")
    if graph_set_id:
        refs.append(f"graph_set:{graph_set_id}")
    if feature_graph_id:
        refs.append(f"feature_graph:{feature_graph_id}")
    if feature_graph_status_id:
        refs.append(f"feature_graph_status:{feature_graph_status_id}")
    if resolution_id:
        refs.append(f"resolution:{resolution_id}")
    if worker_evidence_ref:
        refs.append(worker_evidence_ref)
    return refs


def _root_graph_id_from_graph_set_id(graph_set_id: str | None) -> str | None:
    if graph_set_id is None:
        return None
    suffix = "-graph-set"
    if graph_set_id.endswith(suffix):
        return graph_set_id[: -len(suffix)] or None
    return None


def _safe_artifact_fragment(value: str) -> str:
    result = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value.strip()
    ).strip("-_.")
    return result or "artifact"


def _text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _dedupe_texts(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _live_pids() -> set[int]:
    return list_live_pids()


def _has_persistent_session_launcher(launchers: dict[Any, object]) -> bool:
    return any(
        getattr(launcher, "supports_persistent_sessions", False) is True
        and callable(getattr(launcher, "build_persistent_command", None))
        for launcher in launchers.values()
    )


def _build_peer_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
):
    return _build_optional_ray_god_layer(
        backend=backend,
        native_layer=native_layer,
        launchers=launchers,
        xmuse_root=xmuse_root,
        purpose="peer",
    )


async def _prewarm_peer_god_layer_or_fallback(peer_god_layer, *, native_layer):
    prewarm = getattr(peer_god_layer, "prewarm", None)
    if not callable(prewarm):
        return peer_god_layer
    try:
        await prewarm()
    except Exception as exc:
        if not _degraded_local_god_mode_enabled():
            raise RuntimeError(
                f"Ray peer GOD backend unavailable and native fallback is disabled: {exc}"
            ) from exc
        logger.warning(
            "Ray peer GOD backend prewarm failed; degraded local mode using native: %s",
            exc,
        )
        return _mark_degraded_native_god_layer(
            native_layer,
            purpose="peer",
            reason="ray_unavailable_degraded_local_mode",
        )
    return peer_god_layer


def _build_review_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
):
    return _build_optional_ray_god_layer(
        backend=backend,
        native_layer=native_layer,
        launchers=launchers,
        xmuse_root=xmuse_root,
        purpose="review",
    )


def _build_execution_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
):
    return _build_optional_ray_god_layer(
        backend=backend,
        native_layer=native_layer,
        launchers=launchers,
        xmuse_root=xmuse_root,
        purpose="execution",
    )


def _build_optional_ray_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
    purpose: str,
):
    normalized = (backend or "ray").strip().lower()
    if normalized in {"native", "local"}:
        return _mark_degraded_native_god_layer(
            native_layer,
            purpose=purpose,
            reason="explicit_native_backend",
        )
    if normalized not in {"ray", "auto"}:
        raise RuntimeError(
            f"Unknown {purpose} GOD backend '{backend}'; "
            "native fallback requires explicit backend=native/local"
        )
    try:
        from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

        return RayGodSessionLayer(
            registry_path=xmuse_root / "god_sessions.json",
            db_path=xmuse_root / "chat.db",
            launchers=launchers,
        )
    except Exception as exc:
        if not _degraded_local_god_mode_enabled():
            raise RuntimeError(
                f"Ray {purpose} GOD backend unavailable and native fallback is disabled: {exc}"
            ) from exc
        logger.warning(
            "Ray %s GOD backend unavailable; degraded local mode using native: %s",
            purpose,
            exc,
        )
        return _mark_degraded_native_god_layer(
            native_layer,
            purpose=purpose,
            reason="ray_unavailable_degraded_local_mode",
        )


def _degraded_local_god_mode_enabled() -> bool:
    value = os.environ.get("XMUSE_DEGRADED_LOCAL_GOD_MODE", "")
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _mark_degraded_native_god_layer(native_layer, *, purpose: str, reason: str):
    setattr(native_layer, f"degraded_{purpose}_runtime", "native_exec_shim")
    setattr(native_layer, f"degraded_{purpose}_runtime_reason", reason)
    return native_layer


def health_once(
    lanes_path: Path,
    *,
    xmuse_root: Path | None = None,
    mcp_port: int = 8100,
    chat_api_url: str | None = None,
    check_http: bool = False,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    live_pids: set[int] | None = None,
) -> dict[str, Any]:
    """Return the same operational health summary used by stale repair."""
    process_inventory = discover_xmuse_runtime_processes()
    live_pid_set = _live_pids() if live_pids is None else live_pids
    summary = build_run_health_model(
        lanes_path,
        now=now,
        stale_after_s=stale_after_s,
        live_pids=live_pid_set,
        runner_pids=process_inventory["runner_pids"],
        mcp_pids=process_inventory["mcp_pids"],
        process_inventory=process_inventory,
    )
    summary["operations"] = _build_runtime_operations_health(
        xmuse_root=xmuse_root or lanes_path.parent,
        mcp_port=mcp_port,
        chat_api_url=chat_api_url,
        check_http=check_http,
        process_inventory=process_inventory,
    )
    return summary


def _build_runtime_operations_health(
    *,
    xmuse_root: Path,
    mcp_port: int,
    chat_api_url: str,
    check_http: bool,
    process_inventory: dict[str, Any],
) -> dict[str, Any]:
    chat_url = _normalize_base_url(chat_api_url)
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"
    counts = process_inventory.get("counts_by_service") or {}
    runner_count = _service_count(counts, "runner")
    mcp_count = _service_count(counts, "mcp")
    chat_api_count = _service_count(counts, "chat_api")
    return {
        "ports": {
            "mcp": {"port": mcp_port, "url": mcp_url},
            "mcp_chat": {"port": mcp_port, "url": f"{mcp_url}/chat"},
            "chat_api": {"port": _url_port(chat_url, default=8201), "url": chat_url},
        },
        "readiness": {
            "chat_api": _endpoint_readiness(
                service_count=chat_api_count,
                url=f"{chat_url}/health",
                check_http=check_http,
            ),
            "mcp": _endpoint_readiness(
                service_count=mcp_count,
                url=f"http://127.0.0.1:{mcp_port}/health",
                check_http=check_http,
            ),
            "runner": _process_readiness(runner_count),
            "ray_god_layer": _ray_god_layer_readiness(),
            "codex_app_server": _codex_app_server_readiness(
                counts,
                runner_count=runner_count,
            ),
        },
        "durable_state": _durable_state_health(xmuse_root),
        "scheduler_progress": _scheduler_progress_health(xmuse_root / "chat.db"),
        "chat_dispatch_bridge": _chat_dispatch_bridge_health(xmuse_root / "chat.db"),
        "cleanup": _cleanup_health(counts, runner_count=runner_count),
    }


def _endpoint_readiness(
    *,
    service_count: int,
    url: str,
    check_http: bool,
) -> dict[str, Any]:
    if not check_http:
        return {
            "status": "observed" if service_count else "unchecked",
            "process_count": service_count,
            "check_url": url,
        }
    status_code = _http_status(url)
    return {
        "status": "ready" if status_code == 200 else "unreachable",
        "process_count": service_count,
        "check_url": url,
        "http_status": status_code,
    }


def _process_readiness(service_count: int) -> dict[str, Any]:
    if service_count == 1:
        status = "ready"
    elif service_count > 1:
        status = "duplicate"
    else:
        status = "missing"
    return {"status": status, "process_count": service_count}


def _ray_god_layer_readiness() -> dict[str, Any]:
    backend = os.environ.get("XMUSE_PEER_GOD_BACKEND", "ray").strip().lower() or "ray"
    transport = os.environ.get("XMUSE_RAY_GOD_TRANSPORT", "app-server").strip().lower()
    mcp_enabled = os.environ.get("XMUSE_RAY_GOD_MCP", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    status = "degraded" if backend in {"native", "local"} else "configured"
    return {
        "status": status,
        "backend": backend,
        "transport": "app-server" if transport in {"app-server", "appserver"} else transport,
        "mcp_enabled": mcp_enabled,
    }


def _codex_app_server_readiness(
    counts: dict[str, Any],
    *,
    runner_count: int,
) -> dict[str, Any]:
    count = _service_count(counts, "codex_app_server")
    if count == 0:
        status = "not_observed"
    elif runner_count == 0:
        status = "orphaned"
    else:
        status = "observed"
    return {"status": status, "process_count": count}


def _durable_state_health(xmuse_root: Path) -> dict[str, Any]:
    return {
        "chat_db": _state_file_health(xmuse_root / "chat.db"),
        "god_sessions": _state_file_health(xmuse_root / "god_sessions.json"),
    }


def _state_file_health(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.exists()}


def _scheduler_progress_health(chat_db_path: Path) -> dict[str, Any]:
    if not chat_db_path.exists():
        return {"status": "missing_chat_db", "trace_count": 0}
    try:
        with sqlite3.connect(chat_db_path) as conn:
            table_exists = conn.execute(
                """
                select 1 from sqlite_master
                where type = 'table' and name = 'peer_turn_latency_traces'
                """
            ).fetchone()
            if table_exists is None:
                return {"status": "no_traces", "trace_count": 0}
            row = conn.execute(
                """
                select count(*) as trace_count, max(writeback_at) as last_writeback_at
                from peer_turn_latency_traces
                """
            ).fetchone()
            trace_count = int(row[0] or 0)
            if trace_count == 0:
                return {"status": "no_traces", "trace_count": 0}
            modes = [
                str(item[0])
                for item in conn.execute(
                    """
                    select distinct delivery_mode from peer_turn_latency_traces
                    order by delivery_mode
                    """
                ).fetchall()
                if item[0]
            ]
            return {
                "status": "observed",
                "trace_count": trace_count,
                "last_writeback_at": row[1],
                "delivery_modes": modes,
            }
    except sqlite3.Error as exc:
        return {
            "status": "unreadable",
            "trace_count": 0,
            "error": str(exc),
        }


def _chat_dispatch_bridge_health(chat_db_path: Path) -> dict[str, Any]:
    empty = {
        "status": "no_entries",
        "total": 0,
        "queued": 0,
        "processing": 0,
        "dispatched": 0,
        "failed": 0,
        "latest": None,
    }
    if not chat_db_path.exists():
        return {**empty, "status": "missing_chat_db"}
    try:
        with sqlite3.connect(chat_db_path) as conn:
            conn.row_factory = sqlite3.Row
            table_exists = conn.execute(
                """
                select 1 from sqlite_master
                where type = 'table' and name = 'chat_dispatch_queue'
                """
            ).fetchone()
            if table_exists is None:
                return empty
            rows = conn.execute(
                """
                select status, count(*) as c
                from chat_dispatch_queue
                group by status
                """
            ).fetchall()
            counts = {str(row["status"]): int(row["c"] or 0) for row in rows}
            total = sum(counts.values())
            if total == 0:
                return empty
            latest = conn.execute(
                """
                select
                    entry_id, conversation_id, status, source, target, auto_execute,
                    proposal_id, resolution_id, collaboration_run_id, artifact_ref,
                    dispatch_evidence
                from chat_dispatch_queue
                order by
                    coalesce(completed_at, updated_at, claimed_at, created_at) desc,
                    completed_at is not null desc,
                    rowid desc
                limit 1
                """
            ).fetchone()
            return {
                "status": "observed",
                "total": total,
                "queued": counts.get("queued", 0),
                "processing": counts.get("processing", 0),
                "dispatched": counts.get("dispatched", 0),
                "failed": counts.get("failed", 0),
                "latest": _chat_dispatch_bridge_latest(latest),
            }
    except sqlite3.Error as exc:
        return {
            **empty,
            "status": "unreadable",
            "error": str(exc),
        }


def _chat_dispatch_bridge_latest(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entry_id": row["entry_id"],
        "conversation_id": row["conversation_id"],
        "status": row["status"],
        "source": row["source"],
        "target": row["target"],
        "auto_execute": bool(row["auto_execute"]),
        "proposal_id": row["proposal_id"],
        "resolution_id": row["resolution_id"],
        "collaboration_run_id": row["collaboration_run_id"],
        "artifact_ref": row["artifact_ref"],
        "dispatch_evidence": row["dispatch_evidence"],
    }


def _cleanup_health(counts: dict[str, Any], *, runner_count: int) -> dict[str, Any]:
    leftover_services = (
        "codex_app_server",
        "raylet",
        "gcs_server",
        "ray_worker",
    )
    leftovers = []
    if runner_count == 0:
        for service in leftover_services:
            count = _service_count(counts, service)
            if count:
                leftovers.append(
                    {
                        "code": f"leftover_{service}",
                        "service": service,
                        "count": count,
                        "action": "report_only",
                        "automated_cleanup": False,
                        "operator_action": "inspect_and_cleanup_manually",
                    }
                )
    return {
        "status": "dirty" if leftovers else "clean",
        "leftovers": leftovers,
    }


def _service_count(counts: dict[str, Any], service: str) -> int:
    value = counts.get(service, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _normalize_base_url(url: str | None) -> str:
    normalized = (
        url
        or os.environ.get("XMUSE_CHAT_API_URL")
        or "http://127.0.0.1:8201"
    ).strip().rstrip("/")
    return normalized or "http://127.0.0.1:8201"


def _url_port(url: str, *, default: int) -> int:
    parsed = urllib.parse.urlparse(url)
    return parsed.port or default


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return int(response.status)
    except (OSError, urllib.error.URLError):
        return None


def _repair_stale_dispatched_lanes(
    orch: PlatformOrchestrator,
    *,
    xmuse_root: Path,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    owned_lane_ids: set[str] | None = None,
) -> None:
    current_time = time.time() if now is None else now
    lanes = orch._sm.get_lanes(status="dispatched")
    if not lanes:
        return
    live_pids = _live_pids()
    health = summarize_run_health(
        lanes,
        now=current_time,
        stale_after_s=stale_after_s,
        live_pids=live_pids,
    )
    stale_ids = set(health["groups"]["stale"])
    owned = owned_lane_ids or set()
    for lane in lanes:
        lane_id = str(lane.get("feature_id") or "")
        worker_pid = lane.get("worker_pid")
        worker_pid_is_int = isinstance(worker_pid, int) and not isinstance(worker_pid, bool)
        worker_pid_missing = worker_pid is None and _text(lane.get("graph_id")) is not None
        if (
            lane_id not in stale_ids
            or lane_id in owned
            or not (worker_pid_is_int or worker_pid_missing)
        ):
            continue
        failure_class = (
            "stale_worker_lost" if worker_pid_is_int else "dispatch_no_worker_pid"
        )
        metadata: dict[str, Any] = {
            "failure_reason": failure_class,
            "stale_repaired_at": current_time,
        }
        if worker_pid_is_int:
            metadata["stale_worker_pid"] = worker_pid
        else:
            metadata["stale_worker_pid_missing"] = True
        logger.warning(
            "repairing stale dispatched lane: %s worker_pid=%s",
            lane_id,
            worker_pid,
        )
        expected_metadata: dict[str, Any] = {"status": "dispatched"}
        if worker_pid_is_int or worker_pid is None:
            expected_metadata["worker_pid"] = worker_pid
        repaired_lane = orch._sm.transition_if_metadata(
            lane_id,
            "exec_failed",
            expected_metadata=expected_metadata,
            metadata=metadata,
        )
        if repaired_lane is not None:
            _record_stale_repair_recovery_artifact(
                orch,
                lane=repaired_lane,
                lane_id=lane_id,
                worker_pid=worker_pid if worker_pid_is_int else None,
                failure_class=failure_class,
                repaired_at=current_time,
                xmuse_root=xmuse_root,
            )


def _record_stale_repair_recovery_artifact(
    orch: PlatformOrchestrator,
    *,
    lane: dict[str, Any],
    lane_id: str,
    worker_pid: int | None,
    failure_class: str,
    repaired_at: float,
    xmuse_root: Path,
) -> None:
    """Write durable recovery authority after a stale-dispatch repair succeeds."""
    graph_id = _text(lane.get("graph_id"))
    recovery_lane_id = _text(lane.get("lane_local_id")) or _text(lane.get("feature_id"))
    update_metadata = getattr(getattr(orch, "_sm", None), "update_metadata", None)
    if graph_id is None or recovery_lane_id is None:
        recovery_metadata = {
            "recovery_artifact_status": "manual_gap",
            "recovery_artifact_source_authority": "platform_runner_stale_repair",
            "manual_gaps": [
                "stale_repair_recovery_artifact_missing_graph_or_lane_id",
                "live_runner_recovery_enforcement_not_proven",
            ],
            "forbidden_claims": [
                "overnight_safe_recovery",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
            ],
        }
        if callable(update_metadata):
            update_metadata(lane_id, recovery_metadata)
        return

    source_refs = _dedupe_texts(
        [
            f"lane:{lane_id}",
            f"graph:{graph_id}",
            (
                f"stale_worker_pid:{worker_pid}"
                if worker_pid is not None
                else "worker_pid:missing"
            ),
            f"platform_runner_stale_repair:{repaired_at}",
        ]
    )
    attempt = _stale_repair_attempt(lane)
    next_action = (
        "inspect stale worker loss and record recovery or refactor evidence "
        "before retrying this lane"
        if failure_class == "stale_worker_lost"
        else "inspect dispatch startup failure and record recovery or refactor "
        "evidence before retrying this lane"
    )
    recovery_payload = {
        "schema_version": "xmuse.god_room_lane_recovery.v1",
        "source_authority": "platform_runner_stale_repair",
        "graph_id": graph_id,
        "lane_id": recovery_lane_id,
        "projection_lane_id": lane_id if recovery_lane_id != lane_id else None,
        "source_refs": source_refs,
        "decision": {
            "lane_id": recovery_lane_id,
            "decision": "suspended",
            "retry_allowed": False,
            "failure_class": failure_class,
            "attempt": attempt,
            "suspend_reason": failure_class,
            "next_action": next_action,
            "source_refs": source_refs,
        },
        "manual_gaps": [
            "live_runner_recovery_enforcement_not_proven",
            "review_truth_not_proven",
            "server_truth_not_proven",
            "overnight_safe_recovery_not_proven",
        ],
        "forbidden_claims": [
            "overnight_safe_recovery",
            "end_to_end_execution_review_closure",
            "worker_output_is_review_truth",
            "ready_to_merge",
            "pr_merged",
        ],
    }
    try:
        recovery_path = lane_recovery_artifact_path(
            xmuse_root,
            graph_id=graph_id,
            lane_id=recovery_lane_id,
        )
        recovery_path.parent.mkdir(parents=True, exist_ok=True)
        recovery_path.write_text(
            json.dumps(recovery_payload, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        recovery_metadata = {
            "recovery_artifact_status": "manual_gap",
            "recovery_artifact_source_authority": "platform_runner_stale_repair",
            "recovery_artifact_error": str(exc),
            "manual_gaps": [
                "stale_repair_recovery_artifact_write_failed",
                "live_runner_recovery_enforcement_not_proven",
            ],
            "forbidden_claims": [
                "overnight_safe_recovery",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
            ],
        }
    else:
        recovery_metadata = {
            "recovery_artifact_status": "written",
            "recovery_artifact_source_authority": "platform_runner_stale_repair",
            "recovery_artifact_ref": _relative_artifact_ref(
                root=xmuse_root,
                path=recovery_path,
            ),
            "recovery_decision": recovery_payload["decision"],
            "recovery_source_refs": source_refs,
        }
    if callable(update_metadata):
        update_metadata(lane_id, recovery_metadata)


def _stale_repair_attempt(lane: dict[str, Any]) -> int:
    for key in ("attempt", "attempts"):
        value = lane.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    retry_count = lane.get("retry_count")
    if isinstance(retry_count, int) and not isinstance(retry_count, bool):
        return max(1, retry_count + 1)
    return 1


def _dependencies_satisfied(lane: dict, lane_status_by_id: dict[str, str | None]) -> bool:
    success_statuses = {"done", "merged", "completed"}
    for dependency_id in lane.get("depends_on", []):
        if lane_status_by_id.get(dependency_id) not in success_statuses:
            return False
    return True


def main_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="xmuse Platform Runner (MVP)")
    parser.add_argument(
        "--xmuse-root",
        type=Path,
        default=DEFAULT_XMUSE_ROOT,
        help="xmuse runtime root; defaults to XMUSE_ROOT or ./xmuse",
    )
    parser.add_argument(
        "--lanes",
        type=Path,
        default=None,
        help="lane projection path; defaults to <xmuse-root>/feature_lanes.json",
    )
    parser.add_argument("--mcp-port", type=int, default=8100)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--graph-id")
    parser.add_argument("--resolution-id")
    parser.add_argument(
        "--require-final-action-approval",
        action="store_true",
        help="hold merge/terminate verdicts for external final-action approval",
    )
    parser.add_argument(
        "--god-runtime",
        choices=("codex",),
        default=None,
        help="GOD CLI runtime; xmuse is currently codex-only",
    )
    parser.add_argument(
        "--auto-evolve",
        action="store_true",
        help="auto-spawn next self-evolution run when a graph terminalizes",
    )
    parser.add_argument(
        "--blueprint",
        type=Path,
        default=DEFAULT_BLUEPRINT,
        help="path to the active EvolutionBlueprintSet markdown",
    )
    parser.add_argument(
        "--decomposer",
        choices=("single", "deterministic-multi", "peer-chat"),
        default="single",
        help="how to decompose each chain step into lanes",
    )
    parser.add_argument(
        "--chat-driver",
        action="store_true",
        help="enable multi-GOD chat driver (architect/review reply to human messages)",
    )
    parser.add_argument(
        "--chat-driver-model",
        default=DEFAULT_CODEX_GOD_MODEL_ID,
        help="Codex model for chat-driver GOD replies",
    )
    parser.add_argument(
        "--peer-chat",
        action="store_true",
        help="enable MCP peer-chat scheduler for long-lived GOD sessions",
    )
    parser.add_argument(
        "--persistent-review-god",
        action="store_true",
        help=(
            "route review through long-lived GOD sessions; requires a launcher "
            "that speaks the xmuse persistent session protocol"
        ),
    )
    parser.add_argument(
        "--persistent-review-timeout-s",
        type=float,
        default=None,
        help=(
            "seconds to wait for a persistent Review GOD result before one-shot "
            "fallback; defaults to 1800 seconds"
        ),
    )
    parser.add_argument(
        "--default-review-peer-routing",
        action="store_true",
        help=(
            "with --persistent-review-god, create/reuse a default chat review "
            "peer per conversation feature and route review through that peer"
        ),
    )
    parser.add_argument(
        "--persistent-execute-god",
        action="store_true",
        help=(
            "route execution through long-lived Execute GOD sessions; requires a "
            "launcher that speaks the xmuse persistent session protocol"
        ),
    )
    parser.add_argument(
        "--execution-provider-profile-ref",
        default=None,
        help="provider profile ref override for execution transport, e.g. codex.default",
    )
    parser.add_argument(
        "--review-provider-profile-ref",
        default=None,
        help="provider profile ref override for review transport, e.g. codex.review",
    )
    parser.add_argument(
        "--codex-model-policy",
        choices=("tiered",),
        default=None,
        help=(
            "opt into codex-only tiered model policy metadata and model config"
        ),
    )
    parser.add_argument(
        "--review-model",
        default=None,
        help="Codex model for review layer when --codex-model-policy is enabled",
    )
    parser.add_argument(
        "--coordinator-model",
        default=None,
        help="Codex model for one-shot coordinator layer when policy is enabled",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="Codex model target for bounded workers when policy is enabled",
    )
    parser.add_argument(
        "--delegation-mode",
        choices=("legacy_single_agent", "bounded_worker"),
        default=None,
        help="delegation mode recorded when --codex-model-policy is enabled",
    )
    parser.add_argument(
        "--memoryos-url",
        default=None,
        help="optional MemoryOS API base URL for lane context and execution memory",
    )
    parser.add_argument(
        "--runner-recovery-proof-output",
        type=Path,
        default=None,
        help=(
            "optional path for a local runner recovery proof artifact; "
            "records candidate selection plus shared run-health recovery state"
        ),
    )
    parser.add_argument(
        "--local-execution-candidate-output-dir",
        type=Path,
        default=None,
        help=(
            "directory for xmuse.local_execution_candidate.v1 artifacts captured "
            "after runner dispatch_lane returns successfully; defaults to "
            "<xmuse-root>/work/local_execution_candidates"
        ),
    )
    parser.add_argument(
        "--disable-local-execution-candidate-capture",
        action="store_true",
        help=(
            "disable default local execution candidate artifact capture; use only "
            "for diagnostics that must not emit runtime evidence"
        ),
    )
    parser.add_argument(
        "--health-once",
        action="store_true",
        help="print a JSON run health summary and exit without starting the runner",
    )
    parser.add_argument(
        "--health-check-http",
        action="store_true",
        help="with --health-once, probe Chat API and MCP /health endpoints",
    )
    parser.add_argument(
        "--stale-after-s",
        type=float,
        default=DEFAULT_STALE_AFTER_S,
        help="worker inactivity threshold used by --health-once",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.peer_chat and args.chat_driver:
        raise SystemExit("--peer-chat and --chat-driver are mutually exclusive")
    if args.default_review_peer_routing and not args.persistent_review_god:
        raise SystemExit(
            "--default-review-peer-routing requires --persistent-review-god"
        )
    if args.persistent_review_timeout_s is not None:
        if not args.persistent_review_god:
            raise SystemExit(
                "--persistent-review-timeout-s requires --persistent-review-god"
            )
        if (
            not math.isfinite(args.persistent_review_timeout_s)
            or args.persistent_review_timeout_s <= 0
        ):
            raise SystemExit(
                "--persistent-review-timeout-s must be a positive finite number"
            )
    model_override_args = (
        args.review_model,
        args.coordinator_model,
        args.worker_model,
        args.delegation_mode,
    )
    if any(value is not None for value in model_override_args) and not args.codex_model_policy:
        raise SystemExit(
            "--review-model/--coordinator-model/--worker-model/--delegation-mode "
            "require --codex-model-policy"
        )


def _model_policy_from_args(args: argparse.Namespace) -> CodexModelPolicy | None:
    return resolve_codex_model_policy(
        enabled=args.codex_model_policy == "tiered",
        review_model=args.review_model,
        coordinator_model=args.coordinator_model,
        worker_model=args.worker_model,
        delegation_mode=args.delegation_mode,
    )


def _runtime_paths_from_args(args: argparse.Namespace) -> tuple[Path, Path]:
    xmuse_root = resolve_xmuse_root(args.xmuse_root, fallback=DEFAULT_XMUSE_ROOT)
    lanes_path = args.lanes or (xmuse_root / "feature_lanes.json")
    return xmuse_root, lanes_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = main_arg_parser()
    args = parser.parse_args()
    validate_args(args)
    model_policy = _model_policy_from_args(args)
    xmuse_root, lanes_path = _runtime_paths_from_args(args)

    if args.health_once:
        print(
            json.dumps(
                health_once(
                    lanes_path,
                    xmuse_root=xmuse_root,
                    mcp_port=args.mcp_port,
                    chat_api_url=os.environ.get("XMUSE_CHAT_API_URL"),
                    check_http=args.health_check_http,
                    stale_after_s=args.stale_after_s,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    asyncio.run(run(
        lanes_path=lanes_path,
        xmuse_root=xmuse_root,
        mcp_port=args.mcp_port,
        max_hours=args.max_hours,
        max_concurrent=args.max_concurrent,
        graph_id=args.graph_id,
        resolution_id=args.resolution_id,
        require_final_action_approval=args.require_final_action_approval,
        god_runtime=args.god_runtime,
        auto_evolve=args.auto_evolve,
        blueprint_path=args.blueprint,
        decomposer_kind=args.decomposer,
        chat_driver_enabled=args.chat_driver,
        chat_driver_model=args.chat_driver_model,
        peer_chat_enabled=args.peer_chat,
        persistent_review_god_enabled=args.persistent_review_god,
        persistent_review_timeout_s=args.persistent_review_timeout_s,
        default_review_peer_routing_enabled=args.default_review_peer_routing,
        persistent_execute_god_enabled=args.persistent_execute_god,
        memoryos_url=args.memoryos_url,
        model_policy=model_policy,
        execution_provider_profile_ref=args.execution_provider_profile_ref,
        review_provider_profile_ref=args.review_provider_profile_ref,
        runner_recovery_proof_output=args.runner_recovery_proof_output,
        local_execution_candidate_output_dir=args.local_execution_candidate_output_dir,
        local_execution_candidate_capture_enabled=(
            not args.disable_local_execution_candidate_capture
        ),
    ))


if __name__ == "__main__":
    main()
