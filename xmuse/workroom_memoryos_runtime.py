"""Lifecycle coordinator for one optional, generation-bound MemoryOS child.

The coordinator owns process orchestration, health/capability proof, bounded
recovery, and guarded derived-index rebuilds.  Durable Room and memory authority
remain in ``chat.db``; process records and receipts remain evidence only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from xmuse.workroom_contracts import (
    WorkroomDependencies,
    WorkroomError,
    WorkroomPaths,
    workroom_lifecycle_lock,
)
from xmuse.workroom_manifest import (
    ManifestError,
    atomic_write_manifest,
    read_manifest,
    update_manifest,
)
from xmuse.workroom_memoryos import (
    MemoryOSRuntimeControl,
    defer_memoryos_for_unknown_port,
    mark_memoryos_healthy,
    memoryos_record_for_identity,
    prepare_memoryos_spawn,
    schedule_memoryos_recovery,
    set_memoryos_rebuilding,
)
from xmuse.workroom_processes import (
    ManagedProcess,
    ProcessSpec,
    service_is_live,
    stop_service_record,
)
from xmuse_core.chat.memoryos_supervisor import (
    MEMORYOS_HOST,
    MEMORYOS_PORT,
    MEMORYOS_RUNTIME_SCHEMA,
    MemoryOSRuntimeState,
    MemoryOSSupervisorError,
    clear_memoryos_derived_cache,
    memoryos_child_environment,
    memoryos_command,
    memoryos_incident_guard,
    memoryos_rebuildability,
    prepare_memoryos_derived_cache,
    read_memoryos_status,
    resolve_memoryos_executable,
    safe_memoryos_status,
    write_memoryos_status,
)
from xmuse_core.chat.room_memory_rebuild_store import RoomMemoryRebuildActionStore


@dataclass(frozen=True)
class MemoryOSChatAPIBinding:
    """Server-only binding handed to Chat API process composition."""

    url: str
    api_key: str = field(repr=False)
    profile: Literal["archive-only", "full-local"]


@dataclass(repr=False)
class MemoryOSRuntimeCoordinator:
    """Coordinate exactly one MemoryOS child in one Workroom generation."""

    control: MemoryOSRuntimeControl
    manifest: dict[str, Any]
    paths: WorkroomPaths
    deps: WorkroomDependencies
    _rebuild_store: RoomMemoryRebuildActionStore | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        *,
        executable: Path,
        profile: str,
        api_key: str,
        manifest: dict[str, Any],
        paths: WorkroomPaths,
        deps: WorkroomDependencies,
    ) -> MemoryOSRuntimeCoordinator:
        """Build the generation-local control and rebuild ledger safely."""

        if profile not in {"archive-only", "full-local"}:
            raise WorkroomError(
                "memory_profile_invalid",
                "memory profile must be archive-only or full-local",
            )
        try:
            resolved = resolve_memoryos_executable(executable)
        except (FileNotFoundError, OSError, MemoryOSSupervisorError) as exc:
            code = getattr(exc, "code", "memoryos_executable_invalid")
            raise WorkroomError(
                str(code),
                "the configured MemoryOS executable is invalid",
            ) from exc
        if not isinstance(api_key, str) or not api_key:
            raise WorkroomError(
                "memoryos_runtime_configuration_invalid",
                "the MemoryOS server binding is invalid",
            )
        control = MemoryOSRuntimeControl(
            executable=resolved,
            api_key=api_key,
            url=f"http://{MEMORYOS_HOST}:{MEMORYOS_PORT}",
            profile=cast(Literal["archive-only", "full-local"], profile),
        )
        return cls(
            control=control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            _rebuild_store=RoomMemoryRebuildActionStore(paths.xmuse_root / "chat.db"),
        )

    def __repr__(self) -> str:
        return f"MemoryOSRuntimeCoordinator(profile={self.control.profile!r})"

    def chat_api_binding(self) -> MemoryOSChatAPIBinding:
        """Return the server-only endpoint binding without a mapping repr leak."""

        return MemoryOSChatAPIBinding(
            url=self.control.url,
            api_key=self.control.api_key,
            profile=self.control.profile,
        )

    def reconcile(self, *, lifecycle_locked: bool = False) -> dict[str, Any]:
        """Reconcile once without replacing or signalling an unverified process."""

        if lifecycle_locked:
            return self._reconcile_if_current()
        with workroom_lifecycle_lock(self.paths):
            return self._reconcile_if_current()

    def reconcile_optional(self, *, lifecycle_locked: bool = False) -> dict[str, Any]:
        """Keep optional-sidecar failure outside required Workroom readiness."""

        try:
            return self.reconcile(lifecycle_locked=lifecycle_locked)
        except Exception:
            return self.record_status(
                state="degraded",
                code="memoryos_reconcile_failed",
            )

    def reconcile_rebuild_action(
        self,
        action_store: RoomMemoryRebuildActionStore | None = None,
        *,
        lifecycle_locked: bool = False,
        stop_timeout_s: float = 10.0,
    ) -> dict[str, Any] | None:
        """Advance at most one durable, generation-fenced rebuild phase."""

        store = action_store or self._rebuild_store
        if store is None:
            raise WorkroomError(
                "memoryos_rebuild_store_unavailable",
                "the MemoryOS rebuild ledger is unavailable",
            )

        def reconcile_if_current() -> dict[str, Any] | None:
            if not self._generation_is_current():
                return None
            action = store.next_requested()
            if action is None:
                if self.control.rebuilding:
                    set_memoryos_rebuilding(self.control, False)
                return None
            phase = action.get("phase")
            generation = self.manifest.get("generation")
            action_generation = action.get("_runtime_generation")
            if (
                phase == "requested"
                and action_generation is not None
                and action_generation != generation
            ):
                return self._finish_rebuild_failure(
                    store,
                    action,
                    status="rejected",
                    reason_code="memoryos_rebuild_generation_changed",
                )
            client_action_id = str(action["client_action_id"])
            if phase == "requested":
                receipt = read_memoryos_status(self.paths.xmuse_root)
                rebuildability = memoryos_rebuildability(receipt or {})
                guard_matches = (
                    receipt is not None
                    and receipt.get("generation") == generation
                    and memoryos_incident_guard(receipt) == action.get("_incident_guard")
                )
                if not guard_matches:
                    return self._finish_rebuild_failure(
                        store,
                        action,
                        status="rejected",
                        reason_code="memoryos_rebuild_incident_changed",
                    )
                if not rebuildability.get("available"):
                    return self._finish_rebuild_failure(
                        store,
                        action,
                        status="rejected",
                        reason_code="memoryos_rebuild_not_available",
                    )
                self.control.rebuild_blocked_code = None
                set_memoryos_rebuilding(self.control, True)
                return store.advance(
                    client_action_id=client_action_id,
                    expected_phase="requested",
                    phase="stopping",
                )

            if phase == "stopping":
                set_memoryos_rebuilding(self.control, True)
                try:
                    self._stop_for_rebuild(timeout_s=stop_timeout_s)
                except WorkroomError as exc:
                    return self._finish_rebuild_failure(
                        store,
                        action,
                        status="failed",
                        reason_code=exc.code,
                    )
                return store.advance(
                    client_action_id=client_action_id,
                    expected_phase="stopping",
                    phase="stopped",
                )

            if phase == "stopped":
                set_memoryos_rebuilding(self.control, True)
                self.control.rebuild_blocked_code = None
                try:
                    self._stop_for_rebuild(timeout_s=stop_timeout_s)
                    cache_cleared = clear_memoryos_derived_cache(self.paths.xmuse_root)
                except (MemoryOSSupervisorError, WorkroomError) as exc:
                    return self._block_rebuild(action, reason_code=exc.code)
                return store.advance(
                    client_action_id=client_action_id,
                    expected_phase="stopped",
                    phase="cache_cleared",
                    result={"cache_cleared": cache_cleared},
                )

            if phase == "cache_cleared":
                set_memoryos_rebuilding(self.control, True)
                self.control.rebuild_blocked_code = None
                try:
                    self._stop_for_rebuild(timeout_s=stop_timeout_s)
                    clear_memoryos_derived_cache(self.paths.xmuse_root)
                except (MemoryOSSupervisorError, WorkroomError) as exc:
                    return self._block_rebuild(action, reason_code=exc.code)
                return store.reset_authority(client_action_id=client_action_id)

            if phase == "authority_reset":
                self.control.rebuild_blocked_code = None
                set_memoryos_rebuilding(self.control, False)
                return store.advance(
                    client_action_id=client_action_id,
                    expected_phase="authority_reset",
                    phase="restarting",
                )

            if phase == "restarting":
                self.control.rebuild_blocked_code = None
                status = self.reconcile_optional(lifecycle_locked=True)
                if status.get("state") != "ready":
                    return action
                return store.advance(
                    client_action_id=client_action_id,
                    expected_phase="restarting",
                    phase="replaying",
                )

            if phase == "replaying":
                status = self.reconcile_optional(lifecycle_locked=True)
                if status.get("state") != "ready":
                    return action
                replay = store.replay_status()
                if replay.get("conflict", 0) > 0:
                    return self._finish_rebuild_failure(
                        store,
                        action,
                        status="failed",
                        reason_code="memoryos_rebuild_replay_conflict",
                    )
                if all(value == 0 for value in replay.values()):
                    return store.finish(
                        client_action_id=client_action_id,
                        status="applied",
                        after_state="ready",
                        after_code="ready",
                        reason_code=None,
                    )
                return action
            return action

        if lifecycle_locked:
            return reconcile_if_current()
        with workroom_lifecycle_lock(self.paths):
            return reconcile_if_current()

    def record_status(
        self,
        *,
        state: MemoryOSRuntimeState,
        code: str,
    ) -> dict[str, Any]:
        """Write private evidence, returning a bounded fallback on receipt failure."""

        generation = self.manifest.get("generation")
        record = self.control.record
        try:
            return write_memoryos_status(
                self.paths.xmuse_root,
                enabled=True,
                state=state,
                code=code,
                generation=generation if isinstance(generation, str) else None,
                pid=record.get("pid") if isinstance(record, Mapping) else None,
                start_identity=(
                    record.get("start_identity") if isinstance(record, Mapping) else None
                ),
                started_at=self.control.started_at,
                consecutive_restart_count=self.control.consecutive_restart_count,
                next_retry_at=self.control.next_retry_at,
                last_healthy_at=self.control.last_healthy_at,
                profile=self.control.profile,
            )
        except Exception:
            return {
                "schema_version": MEMORYOS_RUNTIME_SCHEMA,
                "enabled": True,
                "state": "degraded",
                "code": "memoryos_status_write_failed",
                "consecutive_restart_count": self.control.consecutive_restart_count,
                "next_retry_at": self.control.next_retry_at,
                "last_healthy_at": self.control.last_healthy_at,
            }

    def safe_status(self) -> dict[str, Any]:
        """Return browser-safe receipt evidence without identity, key, or paths."""

        return safe_memoryos_status(read_memoryos_status(self.paths.xmuse_root))

    def finalize_after_stop(self) -> None:
        """Stop recovery scheduling after the owning Workroom generation exits."""

        process = self.control.process
        safely_stopped = process is None or process.poll() is not None
        if not safely_stopped and isinstance(self.control.record, Mapping):
            generation = self.manifest.get("generation")
            safely_stopped = not (
                isinstance(generation, str)
                and service_is_live(
                    self.control.record,
                    generation=generation,
                    xmuse_root=self.paths.xmuse_root,
                    inspector=self.deps.inspect_process,
                )
            )
        self.control.next_retry_monotonic = None
        self.control.next_retry_at = None
        self.control.retry_state = None
        self.control.retry_code = None
        if safely_stopped:
            self.control.process = None
            self.control.record = None
        self.record_status(
            state="stopped" if safely_stopped else "degraded",
            code=(
                "memoryos_stopped" if safely_stopped else "memoryos_process_identity_unavailable"
            ),
        )

    def _reconcile_if_current(self) -> dict[str, Any]:
        if not self._generation_is_current():
            return {
                "schema_version": MEMORYOS_RUNTIME_SCHEMA,
                "enabled": True,
                "state": "stopped",
                "code": "memoryos_reconcile_not_current",
            }
        return self._reconcile_locked()

    def _generation_is_current(self) -> bool:
        try:
            current = read_manifest(self.paths.manifest)
        except ManifestError as exc:
            raise WorkroomError(exc.code, str(exc)) from exc
        return bool(
            current is not None
            and current.get("generation") == self.manifest.get("generation")
            and current.get("state") not in {"stopping", "stopped", "failed"}
        )

    def _reconcile_locked(self) -> dict[str, Any]:
        if self.control.rebuild_blocked_code is not None:
            return self.record_status(
                state="degraded",
                code=self.control.rebuild_blocked_code,
            )
        if self.control.rebuilding:
            return self.record_status(state="rebuilding", code="memoryos_rebuilding")
        process = self.control.process
        if process is not None:
            if process.poll() is not None:
                if self.control.next_retry_monotonic is None:
                    return self._schedule_recovery(code="memoryos_process_exited")
            elif self.control.record is None:
                generation = self.manifest.get("generation")
                try:
                    identity = self.deps.inspect_process(process.pid)
                except Exception:
                    identity = None
                if identity is None:
                    return self.record_status(
                        state="degraded",
                        code="memoryos_process_identity_unavailable",
                    )
                record = (
                    memoryos_record_for_identity(
                        process,
                        identity,
                        generation=generation,
                        xmuse_root=self.paths.xmuse_root,
                    )
                    if isinstance(generation, str)
                    else None
                )
                if record is None:
                    return self.record_status(
                        state="degraded",
                        code="memoryos_process_identity_mismatch",
                    )
                self.control.record = record
                self._publish_record(record)
                return self._assess_live()
            else:
                return self._assess_live()

        deadline = self.control.next_retry_monotonic
        if deadline is not None and self.deps.monotonic() < deadline:
            state: MemoryOSRuntimeState = (
                "degraded" if self.control.retry_state == "degraded" else "recovering"
            )
            return self.record_status(
                state=state,
                code=self.control.retry_code or "memoryos_recovering",
            )
        services = self.manifest.get("services")
        unmanaged = services.get("memoryos") if isinstance(services, Mapping) else None
        if isinstance(unmanaged, Mapping):
            pid = unmanaged.get("pid")
            try:
                identity = self.deps.inspect_process(pid) if isinstance(pid, int) else None
            except Exception:
                identity = None
            code = "memoryos_process_identity_unavailable"
            if identity is not None and identity.start_identity != unmanaged.get("start_identity"):
                code = "memoryos_process_identity_mismatch"
            return self.record_status(state="degraded", code=code)
        if not self.deps.port_available(MEMORYOS_HOST, MEMORYOS_PORT):
            decision = defer_memoryos_for_unknown_port(
                self.control,
                monotonic_now=self.deps.monotonic(),
                wall_time_now=self.deps.now(),
            )
            return self.record_status(state=decision.state, code=decision.code)
        return self._attempt_spawn()

    def _attempt_spawn(self) -> dict[str, Any]:
        generation = self.manifest.get("generation")
        if not isinstance(generation, str) or not generation:
            return self.record_status(
                state="degraded",
                code="memoryos_generation_invalid",
            )
        decision = prepare_memoryos_spawn(self.control, started_at=self.deps.now())
        self.record_status(state=decision.state, code=decision.code)
        try:
            process = self._spawn(generation=generation)
        except MemoryOSSupervisorError as exc:
            return self._schedule_recovery(code=exc.code)
        except (OSError, WorkroomError):
            return self._schedule_recovery(code="memoryos_spawn_failed")
        self.control.process = process
        if process.poll() is not None:
            return self._schedule_recovery(code="memoryos_process_exited")
        try:
            identity = self.deps.inspect_process(process.pid)
        except Exception:
            identity = None
        if identity is None:
            return self.record_status(
                state="degraded",
                code="memoryos_process_identity_unavailable",
            )
        record = memoryos_record_for_identity(
            process,
            identity,
            generation=generation,
            xmuse_root=self.paths.xmuse_root,
        )
        if record is None:
            return self.record_status(
                state="degraded",
                code="memoryos_process_identity_mismatch",
            )
        self.control.record = record
        self._publish_record(record)
        return self._assess_live()

    def _spawn(self, *, generation: str) -> ManagedProcess:
        prepare_memoryos_derived_cache(self.paths.xmuse_root)
        environment = memoryos_child_environment(
            self.deps.environ,
            xmuse_root=self.paths.xmuse_root,
            generation=generation,
            api_key=self.control.api_key,
            profile=self.control.profile,
        )
        spec = ProcessSpec(
            service="memoryos",
            command=memoryos_command(self.control.executable),
            cwd=self.paths.memoryos_derived_dir,
            env=environment,
            log_path=self.paths.xmuse_root / "logs" / "workroom-memoryos.log",
        )
        return self.deps.spawn(spec)

    def _assess_live(self) -> dict[str, Any]:
        process = self.control.process
        record = self.control.record
        generation = self.manifest.get("generation")
        if process is None or not isinstance(record, Mapping) or not isinstance(generation, str):
            return self.record_status(
                state="degraded",
                code="memoryos_process_identity_unavailable",
            )
        try:
            identity = self.deps.inspect_process(process.pid)
        except Exception:
            identity = None
        if identity is None:
            self.control.healthy_since_monotonic = None
            return self.record_status(
                state="degraded",
                code="memoryos_process_identity_unavailable",
            )
        observed = memoryos_record_for_identity(
            process,
            identity,
            generation=generation,
            xmuse_root=self.paths.xmuse_root,
        )
        if observed is None or observed.get("start_identity") != record.get("start_identity"):
            self.control.healthy_since_monotonic = None
            return self.record_status(
                state="degraded",
                code="memoryos_process_identity_mismatch",
            )
        try:
            healthy = self.deps.http_ready(f"{self.control.url}/health")
        except Exception:
            healthy = False
        if not healthy:
            self.control.healthy_since_monotonic = None
            return self.record_status(
                state="degraded",
                code="memoryos_health_unavailable",
            )
        if self.control.profile == "full-local" and not self._full_local_ready():
            self.control.healthy_since_monotonic = None
            return self.record_status(
                state="degraded",
                code="memoryos_full_local_capability_missing",
            )
        decision = mark_memoryos_healthy(
            self.control,
            monotonic_now=self.deps.monotonic(),
            wall_time_now=self.deps.now(),
        )
        return self.record_status(state=decision.state, code=decision.code)

    def _full_local_ready(self) -> bool:
        try:
            health_payload = self.deps.http_json(f"{self.control.url}/health")
        except Exception:
            health_payload = None
        capabilities = (
            health_payload.get("capabilities") if isinstance(health_payload, Mapping) else None
        )
        hybrid = capabilities.get("hybrid") if isinstance(capabilities, Mapping) else None
        return bool(
            isinstance(capabilities, Mapping)
            and isinstance(hybrid, Mapping)
            and hybrid.get("lexical") is True
            and hybrid.get("semantic") is True
            and hybrid.get("rrf") is True
            and capabilities.get("message_ingest") is True
            and capabilities.get("agentic_advisory") is True
            and capabilities.get("paging") is True
        )

    def _schedule_recovery(self, *, code: str) -> dict[str, Any]:
        decision = schedule_memoryos_recovery(
            self.control,
            code=code,
            monotonic_now=self.deps.monotonic(),
            wall_time_now=self.deps.now(),
        )
        services = self.manifest.get("services")
        if isinstance(services, dict) and "memoryos" in services:
            services.pop("memoryos", None)
            self._persist_manifest()
        return self.record_status(state=decision.state, code=decision.code)

    def _publish_record(self, record: Mapping[str, Any]) -> None:
        services = self.manifest.setdefault("services", {})
        if not isinstance(services, dict):
            raise WorkroomError("invalid_manifest", "Workroom services manifest is invalid")
        services["memoryos"] = dict(record)
        self._persist_manifest()

    def _persist_manifest(self) -> None:
        updated = update_manifest(self.manifest, updated_at=self.deps.now())
        self.manifest.clear()
        self.manifest.update(updated)
        atomic_write_manifest(self.paths.manifest, self.manifest)

    def _record_is_live(self, record: Mapping[str, Any], *, generation: str) -> bool:
        return service_is_live(
            record,
            generation=generation,
            xmuse_root=self.paths.xmuse_root,
            inspector=self.deps.inspect_process,
        )

    def _stop_for_rebuild(self, *, timeout_s: float) -> None:
        generation = self.manifest.get("generation")
        if not isinstance(generation, str) or not generation:
            raise WorkroomError(
                "memoryos_rebuild_generation_invalid",
                "cannot prove the Workroom generation for a MemoryOS rebuild",
            )
        services = self.manifest.get("services")
        manifest_record = services.get("memoryos") if isinstance(services, dict) else None
        record = (
            self.control.record if isinstance(self.control.record, Mapping) else manifest_record
        )
        process = self.control.process

        if process is not None and process.poll() is None:
            if not isinstance(record, Mapping) or not self._record_is_live(
                record, generation=generation
            ):
                if process.poll() is None:
                    raise WorkroomError(
                        "memoryos_rebuild_process_unverifiable",
                        "cannot safely identify the live MemoryOS process",
                    )
            elif not self._stop_record(record, generation=generation, timeout_s=timeout_s):
                raise WorkroomError(
                    "memoryos_rebuild_stop_timeout",
                    "MemoryOS did not stop before the rebuild deadline",
                )
        elif process is None and isinstance(record, Mapping):
            pid = record.get("pid")
            if not isinstance(pid, int):
                raise WorkroomError(
                    "memoryos_rebuild_process_unverifiable",
                    "cannot safely identify the MemoryOS process",
                )
            try:
                identity = self.deps.inspect_process(pid)
            except Exception as exc:
                raise WorkroomError(
                    "memoryos_rebuild_process_unverifiable",
                    "cannot inspect the MemoryOS process identity",
                ) from exc
            if identity is not None:
                if not self._record_is_live(record, generation=generation):
                    raise WorkroomError(
                        "memoryos_rebuild_process_unverifiable",
                        "the recorded MemoryOS identity no longer matches",
                    )
                if not self._stop_record(record, generation=generation, timeout_s=timeout_s):
                    raise WorkroomError(
                        "memoryos_rebuild_stop_timeout",
                        "MemoryOS did not stop before the rebuild deadline",
                    )

        if not self.deps.port_available(MEMORYOS_HOST, MEMORYOS_PORT):
            raise WorkroomError(
                "memoryos_rebuild_port_occupied",
                "the fixed MemoryOS port is still occupied",
            )
        self.control.process = None
        self.control.record = None
        self.control.started_at = None
        self.control.next_retry_monotonic = None
        self.control.next_retry_at = None
        self.control.retry_state = None
        self.control.retry_code = None
        self.control.rebuild_blocked_code = None
        if isinstance(services, dict):
            services.pop("memoryos", None)
            self._persist_manifest()
        self.record_status(state="rebuilding", code="memoryos_rebuilding")

    def _stop_record(
        self,
        record: Mapping[str, Any],
        *,
        generation: str,
        timeout_s: float,
    ) -> bool:
        return stop_service_record(
            record,
            generation=generation,
            xmuse_root=self.paths.xmuse_root,
            inspector=self.deps.inspect_process,
            signal_group=self.deps.signal_group,
            monotonic=self.deps.monotonic,
            sleep=self.deps.sleep,
            timeout_s=timeout_s,
        )

    def _finish_rebuild_failure(
        self,
        action_store: RoomMemoryRebuildActionStore,
        action: Mapping[str, Any],
        *,
        status: str,
        reason_code: str,
    ) -> dict[str, Any]:
        set_memoryos_rebuilding(self.control, False)
        self.control.rebuild_blocked_code = None
        self.record_status(state="degraded", code=reason_code)
        return action_store.finish(
            client_action_id=str(action["client_action_id"]),
            status=status,  # type: ignore[arg-type]
            after_state="degraded",
            after_code=reason_code,
            reason_code=reason_code,
        )

    def _block_rebuild(
        self,
        action: Mapping[str, Any],
        *,
        reason_code: str,
    ) -> dict[str, Any]:
        set_memoryos_rebuilding(self.control, True)
        self.control.rebuild_blocked_code = reason_code
        self.record_status(state="degraded", code=reason_code)
        return dict(action)


def _record_lifecycle_status(
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    *,
    enabled: bool,
    state: MemoryOSRuntimeState,
    code: str,
) -> dict[str, Any]:
    generation = manifest.get("generation")
    try:
        receipt = write_memoryos_status(
            paths.xmuse_root,
            enabled=enabled,
            state=state,
            code=code,
            generation=generation if isinstance(generation, str) else None,
        )
        return safe_memoryos_status(receipt)
    except Exception:
        return {
            "schema_version": MEMORYOS_RUNTIME_SCHEMA,
            "enabled": True,
            "state": "degraded",
            "code": "memoryos_status_write_failed",
            "heartbeat_at": None,
            "started_at": None,
        }


def record_memoryos_disabled(
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    """Write and return a safe disabled-sidecar receipt."""

    del deps
    return _record_lifecycle_status(
        manifest,
        paths,
        enabled=False,
        state="disabled",
        code="memoryos_disabled",
    )


def record_memoryos_stopped(
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    """Write safe stopped evidence after an identity-fenced stop."""

    del deps
    return _record_lifecycle_status(
        manifest,
        paths,
        enabled=True,
        state="stopped",
        code="memoryos_stopped",
    )


def stop_recorded_memoryos(
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    """Identity-fence one recorded MemoryOS child and return only safe evidence."""

    generation = manifest.get("generation")
    services = manifest.get("services")
    record = services.get("memoryos") if isinstance(services, Mapping) else None
    if not isinstance(generation, str) or not generation:
        return {
            "stopped": False,
            "code": "memoryos_stop_generation_invalid",
            "status": None,
        }
    if record is None:
        return {
            "stopped": True,
            "code": "memoryos_not_recorded",
            "status": record_memoryos_stopped(manifest, paths, deps),
        }
    if (
        not isinstance(record, Mapping)
        or record.get("service") != "memoryos"
        or record.get("generation") != generation
    ):
        return {
            "stopped": False,
            "code": "memoryos_process_identity_mismatch",
            "status": None,
        }
    pid = record.get("pid")
    expected_identity = record.get("start_identity")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or not isinstance(expected_identity, str)
        or not expected_identity
    ):
        return {
            "stopped": False,
            "code": "memoryos_process_identity_unavailable",
            "status": None,
        }
    try:
        observed = deps.inspect_process(pid)
    except Exception:
        observed = None
        inspection_failed = True
    else:
        inspection_failed = False
    if inspection_failed:
        return {
            "stopped": False,
            "code": "memoryos_process_identity_unavailable",
            "status": None,
        }
    if observed is None:
        return {
            "stopped": True,
            "code": "memoryos_stopped",
            "status": record_memoryos_stopped(manifest, paths, deps),
        }
    if (
        observed.start_identity != expected_identity
        or observed.environment.get("XMUSE_WORKROOM_GENERATION") != generation
        or observed.environment.get("XMUSE_ROOT") != str(paths.xmuse_root)
        or observed.environment.get("XMUSE_WORKROOM_SERVICE") != "memoryos"
    ):
        return {
            "stopped": False,
            "code": "memoryos_process_identity_mismatch",
            "status": None,
        }
    stopped = stop_service_record(
        record,
        generation=generation,
        xmuse_root=paths.xmuse_root,
        inspector=deps.inspect_process,
        signal_group=deps.signal_group,
        monotonic=deps.monotonic,
        sleep=deps.sleep,
        timeout_s=timeout_s,
    )
    if not stopped:
        return {
            "stopped": False,
            "code": "memoryos_stop_timeout",
            "status": None,
        }
    try:
        after = deps.inspect_process(pid)
    except Exception:
        return {
            "stopped": False,
            "code": "memoryos_process_identity_unavailable",
            "status": None,
        }
    if after is not None and (
        after.start_identity != expected_identity
        or after.environment.get("XMUSE_WORKROOM_GENERATION") != generation
        or after.environment.get("XMUSE_ROOT") != str(paths.xmuse_root)
        or after.environment.get("XMUSE_WORKROOM_SERVICE") != "memoryos"
    ):
        return {
            "stopped": False,
            "code": "memoryos_process_identity_mismatch",
            "status": None,
        }
    if after is not None:
        return {
            "stopped": False,
            "code": "memoryos_stop_timeout",
            "status": None,
        }
    return {
        "stopped": True,
        "code": "memoryos_stopped",
        "status": record_memoryos_stopped(manifest, paths, deps),
    }


__all__ = [
    "MemoryOSChatAPIBinding",
    "MemoryOSRuntimeCoordinator",
    "record_memoryos_disabled",
    "record_memoryos_stopped",
    "stop_recorded_memoryos",
]
