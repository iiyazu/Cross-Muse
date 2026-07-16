"""Required Chat API and frontend lifecycle coordination for Workroom.

This module owns no lifecycle lock and writes no Workroom manifest.  The caller
serializes the global lifecycle and persists each process record through the
``record_service`` callback.  Room Runtime/MCP and optional MemoryOS lifecycle
remain separate authorities.
"""

from __future__ import annotations

import shutil
import signal
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse.workroom_contracts import WorkroomDependencies, WorkroomError, WorkroomPaths
from xmuse.workroom_processes import (
    ManagedProcess,
    ProcessLifecycleError,
    ProcessSpec,
    identity_matches,
    record_process,
    stop_service_record,
    stop_spawned_processes,
)
from xmuse_core.runtime.child_env import normalize_child_temp_env

CHAT_API_HOST = "127.0.0.1"
CHAT_API_PORT = 8201
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 3000

ServiceRecordCallback = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class RequiredServiceRuntime:
    """Live required children returned to the manager supervision loop."""

    chat_api: ManagedProcess
    frontend: ManagedProcess
    records: Mapping[str, Mapping[str, Any]]

    def processes_by_name(self) -> dict[str, ManagedProcess]:
        return {"chat_api": self.chat_api, "frontend": self.frontend}


class WorkroomServicesCoordinator:
    """Coordinate only the required Chat API and standalone frontend children."""

    def __init__(self, paths: WorkroomPaths, deps: WorkroomDependencies) -> None:
        self._paths = paths
        self._deps = deps

    def preflight(self) -> str:
        """Prove required binaries, build assets, operation state, and ports."""

        if self._paths.data_operation_journal.exists():
            raise WorkroomError(
                "data_operation_incomplete",
                "an interrupted xmuse-data operation must be recovered before Workroom start",
            )
        node = self._deps.which("node")
        if not node:
            raise WorkroomError("node_missing", "Node.js is required to run the Workroom frontend")
        if not self._deps.which("codex"):
            raise WorkroomError(
                "codex_missing",
                "Codex CLI is required to run Workroom Room Agents",
            )
        if not self._paths.standalone_server.is_file():
            raise WorkroomError(
                "standalone_build_missing",
                "frontend/.next/standalone/server.js is missing; run npm run build in frontend",
            )
        if not self._paths.static_source.is_dir():
            raise WorkroomError(
                "static_assets_missing",
                "frontend/.next/static is missing; run npm run build in frontend",
            )
        for service, host, port in (
            ("chat_api", CHAT_API_HOST, CHAT_API_PORT),
            ("frontend", FRONTEND_HOST, FRONTEND_PORT),
        ):
            if not self._deps.port_available(host, port):
                raise WorkroomError(
                    "port_in_use",
                    f"{service} port is already in use: {host}:{port}",
                )
        return node

    def sync_assets(self) -> None:
        """Copy immutable standalone static/public assets into the Next runtime tree."""

        self._replace_tree(self._paths.static_source, self._paths.static_destination)
        self._replace_tree(self._paths.public_source, self._paths.public_destination)

    def start(
        self,
        *,
        node: str,
        generation: str,
        operator_token: str,
        execution_workspace: Path,
        execution_profile_id: str,
        readiness_timeout_s: float,
        record_service: ServiceRecordCallback,
        memoryos_url: str | None = None,
        memoryos_api_key: str | None = None,
        memoryos_profile: str = "full-local",
        cleanup_timeout_s: float = 2.0,
    ) -> RequiredServiceRuntime:
        """Start required children in dependency order and clean partial starts.

        The callback is invoked immediately after each identity-fenced process
        record is established.  It is the caller's responsibility to persist
        that record while holding the lifecycle lock.
        """

        started: list[tuple[ManagedProcess, dict[str, Any] | None]] = []
        records: dict[str, Mapping[str, Any]] = {}
        try:
            chat_api, chat_spec = self._spawn_chat_api(
                generation=generation,
                operator_token=operator_token,
                execution_workspace=execution_workspace,
                execution_profile_id=execution_profile_id,
                memoryos_url=memoryos_url,
                memoryos_api_key=memoryos_api_key,
                memoryos_profile=memoryos_profile,
            )
            started.append((chat_api, None))
            chat_record = self._record(
                chat_api,
                service="chat_api",
                generation=generation,
                host=CHAT_API_HOST,
                port=CHAT_API_PORT,
                url=f"http://{CHAT_API_HOST}:{CHAT_API_PORT}/health",
                log_path=chat_spec.log_path,
            )
            started[-1] = (chat_api, chat_record)
            records["chat_api"] = chat_record
            record_service("chat_api", chat_record)
            self._wait_for_ready(
                service="chat_api",
                url=str(chat_record["url"]),
                process=chat_api,
                timeout_s=readiness_timeout_s,
            )

            frontend, frontend_spec = self._spawn_frontend(
                node=node,
                generation=generation,
                operator_token=operator_token,
            )
            started.append((frontend, None))
            frontend_record = self._record(
                frontend,
                service="frontend",
                generation=generation,
                host=FRONTEND_HOST,
                port=FRONTEND_PORT,
                url=f"http://{FRONTEND_HOST}:{FRONTEND_PORT}",
                log_path=frontend_spec.log_path,
            )
            started[-1] = (frontend, frontend_record)
            records["frontend"] = frontend_record
            record_service("frontend", frontend_record)
            self._wait_for_ready(
                service="frontend",
                url=str(frontend_record["url"]),
                process=frontend,
                timeout_s=readiness_timeout_s,
            )
        except Exception:
            self._cleanup_partial_start(
                started,
                generation=generation,
                timeout_s=cleanup_timeout_s,
            )
            raise
        return RequiredServiceRuntime(
            chat_api=chat_api,
            frontend=frontend,
            records=records,
        )

    def stop(self, manifest: Mapping[str, Any], *, timeout_s: float) -> list[str]:
        """Stop only required services recorded for the manifest generation."""

        generation = manifest.get("generation")
        services = manifest.get("services")
        if not isinstance(generation, str) or not isinstance(services, Mapping):
            return []
        stopped: list[str] = []
        for name in ("frontend", "chat_api"):
            record = services.get(name)
            if not isinstance(record, Mapping):
                continue
            if not self._stop_record(record, generation=generation, timeout_s=timeout_s):
                raise WorkroomError("stop_timeout", f"could not stop {name} safely")
            stopped.append(name)
        return stopped

    def stop_manager(self, record: Mapping[str, Any], *, timeout_s: float) -> bool:
        """Signal a manager PID only while its exact start identity remains live."""

        pid = record.get("pid")
        if not isinstance(pid, int) or not identity_matches(record, self._deps.inspect_process):
            return True
        try:
            self._deps.signal_pid(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        deadline = self._deps.monotonic() + timeout_s
        while identity_matches(record, self._deps.inspect_process):
            if self._deps.monotonic() >= deadline:
                # Re-prove the identity immediately before escalation.  A reused
                # PID must never receive the old generation's SIGKILL.
                if not identity_matches(record, self._deps.inspect_process):
                    return True
                try:
                    self._deps.signal_pid(pid, signal.SIGKILL)
                except ProcessLookupError:
                    return True
                kill_deadline = self._deps.monotonic() + 2.0
                while identity_matches(record, self._deps.inspect_process):
                    if self._deps.monotonic() >= kill_deadline:
                        return False
                    self._deps.sleep(0.05)
                return True
            self._deps.sleep(0.05)
        return True

    def _child_environment(
        self,
        *,
        generation: str,
        operator_token: str,
        service: str,
    ) -> dict[str, str]:
        environment = normalize_child_temp_env(self._deps.environ)
        environment.update(
            {
                "XMUSE_ROOT": str(self._paths.xmuse_root),
                "XMUSE_OPERATOR_TOKEN": operator_token,
                "XMUSE_WORKROOM_MANAGED": "1",
                "XMUSE_WORKROOM_GENERATION": generation,
                "XMUSE_WORKROOM_SERVICE": service,
            }
        )
        return environment

    def _spawn_chat_api(
        self,
        *,
        generation: str,
        operator_token: str,
        execution_workspace: Path,
        execution_profile_id: str,
        memoryos_url: str | None,
        memoryos_api_key: str | None,
        memoryos_profile: str,
    ) -> tuple[ManagedProcess, ProcessSpec]:
        environment = self._child_environment(
            generation=generation,
            operator_token=operator_token,
            service="chat_api",
        )
        environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "XMUSE_CHAT_API_URL": f"http://{CHAT_API_HOST}:{CHAT_API_PORT}",
                "XMUSE_WORKSPACE_ROOT": str(execution_workspace),
                "XMUSE_EXECUTION_PROFILE_ID": execution_profile_id,
            }
        )
        if memoryos_url is not None and memoryos_api_key is not None:
            environment.update(
                {
                    "XMUSE_MEMORYOS_URL": memoryos_url,
                    "XMUSE_MEMORYOS_API_KEY": memoryos_api_key,
                    "XMUSE_MEMORYOS_PROFILE": memoryos_profile,
                }
            )
        spec = ProcessSpec(
            service="chat_api",
            command=(sys.executable, "-m", "xmuse.chat_api"),
            cwd=self._paths.repo_root,
            env=environment,
            log_path=self._paths.xmuse_root / "logs" / "workroom-chat-api.log",
        )
        return self._deps.spawn(spec), spec

    def _spawn_frontend(
        self,
        *,
        node: str,
        generation: str,
        operator_token: str,
    ) -> tuple[ManagedProcess, ProcessSpec]:
        environment = self._child_environment(
            generation=generation,
            operator_token=operator_token,
            service="frontend",
        )
        environment.update(
            {
                "HOSTNAME": FRONTEND_HOST,
                "PORT": str(FRONTEND_PORT),
                "NODE_ENV": "production",
                "XMUSE_CHAT_API_BASE_URL": (f"http://{CHAT_API_HOST}:{CHAT_API_PORT}/api/chat"),
            }
        )
        spec = ProcessSpec(
            service="frontend",
            command=(node, str(self._paths.standalone_server)),
            cwd=self._paths.standalone_dir,
            env=environment,
            log_path=self._paths.xmuse_root / "logs" / "workroom-frontend.log",
        )
        return self._deps.spawn(spec), spec

    def _record(
        self,
        process: ManagedProcess,
        *,
        service: str,
        generation: str,
        host: str,
        port: int,
        url: str,
        log_path: Path,
    ) -> dict[str, Any]:
        try:
            return record_process(
                process,
                service=service,
                generation=generation,
                host=host,
                port=port,
                url=url,
                log_path=log_path,
                xmuse_root=self._paths.xmuse_root,
                inspector=self._deps.inspect_process,
                monotonic=self._deps.monotonic,
                sleep=self._deps.sleep,
            )
        except ProcessLifecycleError as exc:
            raise WorkroomError(exc.code, str(exc)) from exc

    def _wait_for_ready(
        self,
        *,
        service: str,
        url: str,
        process: ManagedProcess,
        timeout_s: float,
    ) -> None:
        deadline = self._deps.monotonic() + timeout_s
        while True:
            return_code = process.poll()
            if return_code is not None:
                raise WorkroomError(
                    "service_exited",
                    f"{service} exited before readiness (code {return_code})",
                )
            if self._deps.http_ready(url):
                return
            if self._deps.monotonic() >= deadline:
                raise WorkroomError(
                    "readiness_timeout",
                    f"{service} did not become ready within {timeout_s:g} seconds",
                )
            self._deps.sleep(0.1)

    def _cleanup_partial_start(
        self,
        started: list[tuple[ManagedProcess, dict[str, Any] | None]],
        *,
        generation: str,
        timeout_s: float,
    ) -> None:
        unrecorded: list[ManagedProcess] = []
        cleanup_failed = False
        for process, record in reversed(started):
            if record is None:
                unrecorded.append(process)
                continue
            if not self._stop_record(record, generation=generation, timeout_s=timeout_s):
                cleanup_failed = True
        if unrecorded:
            stop_spawned_processes(
                unrecorded,
                signal_group=self._deps.signal_group,
                monotonic=self._deps.monotonic,
                sleep=self._deps.sleep,
                timeout_s=timeout_s,
            )
        if cleanup_failed:
            raise WorkroomError(
                "partial_start_cleanup_failed",
                "a required Workroom child could not be stopped safely",
            )

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
            xmuse_root=self._paths.xmuse_root,
            inspector=self._deps.inspect_process,
            signal_group=self._deps.signal_group,
            monotonic=self._deps.monotonic,
            sleep=self._deps.sleep,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _replace_tree(source: Path, destination: Path) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        if source.is_dir():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)


__all__ = [
    "CHAT_API_HOST",
    "CHAT_API_PORT",
    "FRONTEND_HOST",
    "FRONTEND_PORT",
    "RequiredServiceRuntime",
    "ServiceRecordCallback",
    "WorkroomServicesCoordinator",
]
