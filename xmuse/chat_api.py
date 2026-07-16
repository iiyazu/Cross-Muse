#!/usr/bin/env python3
"""Room-only REST API used by the default xmuse Workroom."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from xmuse.chat_api_agent_streams import register_room_agent_stream_routes
from xmuse.chat_api_codex import register_room_codex_routes
from xmuse.chat_api_execution_runtime import RoomExecutionRuntime
from xmuse.chat_api_executions import register_room_execution_routes
from xmuse.chat_api_foundation import (
    DEFAULT_EXECUTION_RECONCILE_INTERVAL_S,
    DEFAULT_RUNTIME_RECONCILE_INTERVAL_S,
    create_chat_api_foundation,
)
from xmuse.chat_api_memory import register_room_memory_routes
from xmuse.chat_api_operations import register_room_operations_routes
from xmuse.chat_api_room_controls import register_room_control_routes
from xmuse.chat_api_room_messages import register_room_message_routes
from xmuse.chat_api_room_projection import register_room_projection_routes
from xmuse.chat_api_room_setup import register_room_setup_routes
from xmuse.chat_api_runtime import (
    WorkroomRuntimeInspector,
    WorkroomRuntimeRecoverer,
    WorkroomRuntimeStarter,
    WorkroomRuntimeStopper,
)
from xmuse.operator_auth import resolve_operator_token
from xmuse_core.chat.memoryos_supervisor import browser_memoryos_status
from xmuse_core.chat.room_execution_operator_store import RoomExecutionOperatorStore
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader
from xmuse_core.chat.room_memory_advisory_store import RoomMemoryAdvisoryStore
from xmuse_core.chat.room_memory_binding_store import RoomMemoryBindingStore
from xmuse_core.chat.room_memory_document_outbox_store import RoomMemoryDocumentOutboxStore
from xmuse_core.chat.room_memory_governance_store import RoomMemoryGovernanceStore
from xmuse_core.chat.room_memory_message_outbox_store import RoomMemoryMessageOutboxStore
from xmuse_core.chat.room_memory_recall_receipt_store import RoomMemoryRecallReceiptStore
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_PORT = 8201
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTION_PROFILE_ID = "xmuse-monorepo/v2"
DEFAULT_BASE_DIR = default_xmuse_root(Path(__file__).resolve().parent)


def create_app(
    base_dir: Path | str = DEFAULT_BASE_DIR,
    *,
    execution_worktree: Path | str | None = None,
    execution_profile_id: str = DEFAULT_EXECUTION_PROFILE_ID,
    auth_token: str | None = None,
    workroom_runtime_starter: WorkroomRuntimeStarter | None = None,
    workroom_runtime_stopper: WorkroomRuntimeStopper | None = None,
    workroom_runtime_inspector: WorkroomRuntimeInspector | None = None,
    workroom_runtime_recoverer: WorkroomRuntimeRecoverer | None = None,
    workroom_runtime_reconcile_interval_s: float = DEFAULT_RUNTIME_RECONCILE_INTERVAL_S,
    execution_reconcile_interval_s: float = DEFAULT_EXECUTION_RECONCILE_INTERVAL_S,
    memory_runtime_status_provider: Callable[[], Mapping[str, Any]] | None = None,
) -> FastAPI:
    operator_token = resolve_operator_token(auth_token)
    resolved_root = Path(base_dir).expanduser().resolve()
    resolved_execution_root = Path(execution_worktree or REPO_ROOT).expanduser().resolve()
    execution_runtime = RoomExecutionRuntime(
        root=resolved_root,
        execution_root=resolved_execution_root,
        launcher_root=REPO_ROOT,
        execution_profile_id=execution_profile_id,
    )
    app, context = create_chat_api_foundation(
        resolved_root,
        execution_worktree=resolved_execution_root,
        auth_token=operator_token,
        auth_mode="operator",
        workroom_runtime_starter=workroom_runtime_starter,
        workroom_runtime_stopper=workroom_runtime_stopper,
        workroom_runtime_inspector=workroom_runtime_inspector,
        workroom_runtime_recoverer=workroom_runtime_recoverer,
        workroom_runtime_reconcile_interval_s=workroom_runtime_reconcile_interval_s,
        title="xmuse Room API",
        execution_reconciler=execution_runtime.reconcile_once,
        execution_stopper=execution_runtime.stop_all,
        execution_reconcile_interval_s=execution_reconcile_interval_s,
    )
    register_room_setup_routes(app, root=context.root)
    register_room_projection_routes(app, root=context.root)
    register_room_control_routes(
        app,
        root=context.root,
        operator_token=operator_token,
    )
    register_room_codex_routes(
        app,
        root=context.root,
        operator_token=operator_token,
    )
    register_room_agent_stream_routes(app, root=context.root)
    register_room_operations_routes(
        app,
        root=context.root,
        execution_root=context.execution_root,
        runtime_inspector=context.runtime_inspector,
        runtime_recoverer=context.runtime_recoverer,
        operator_token=operator_token,
    )
    register_room_execution_routes(
        app,
        root=context.root,
        store_factory=RoomExecutionOperatorStore,
        read_store_factory=RoomExecutionLedgerReader,
        operator_token=operator_token,
        decision_context_provider=execution_runtime.decision_context,
        run_starter=execution_runtime.start_run,
        execution_profile_provider=execution_runtime.profile_status,
        consensus_kill_switch_enabled=execution_runtime.consensus_kill_switch_enabled,
    )
    register_room_memory_routes(
        app,
        root=context.root,
        binding_store_factory=RoomMemoryBindingStore,
        governance_store_factory=RoomMemoryGovernanceStore,
        delivery_store_factory=RoomMemoryDocumentOutboxStore,
        message_delivery_store_factory=RoomMemoryMessageOutboxStore,
        recall_store_factory=RoomMemoryRecallReceiptStore,
        advisory_store_factory=RoomMemoryAdvisoryStore,
        operator_token=operator_token,
        runtime_status_provider=(
            memory_runtime_status_provider or (lambda: browser_memoryos_status(context.root))
        ),
    )
    register_room_message_routes(
        app,
        root=context.root,
        execution_root=context.execution_root,
        runtime_starter=context.runtime_starter,
        explicit_runtime_starter=context.explicit_runtime_starter,
    )
    return app


def main() -> None:
    operator_token = resolve_operator_token()
    if os.environ.get("XMUSE_WORKROOM_MANAGED", "").strip() == "1" and not operator_token:
        raise RuntimeError("managed_operator_token_required")
    uvicorn.run(
        create_app(
            auth_token=operator_token,
            execution_worktree=(os.environ.get("XMUSE_WORKSPACE_ROOT", "").strip() or REPO_ROOT),
            execution_profile_id=(
                os.environ.get("XMUSE_EXECUTION_PROFILE_ID", "").strip()
                or DEFAULT_EXECUTION_PROFILE_ID
            ),
        ),
        host="127.0.0.1",
        port=DEFAULT_PORT,
    )


if __name__ == "__main__":
    main()
