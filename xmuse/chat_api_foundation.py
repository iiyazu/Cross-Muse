"""Lifecycle and security foundation for the local Room Chat API."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from xmuse.chat_api_runtime import (
    WorkroomRuntimeInspector,
    WorkroomRuntimeRecoverer,
    WorkroomRuntimeStarter,
    WorkroomRuntimeStopper,
    ensure_workroom_room_runtime,
    inspect_workroom_room_runtime,
    recover_workroom_room_runtime,
    stop_workroom_room_runtime,
)
from xmuse.operator_auth import operator_token_matches
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.runtime.data_guard import assert_data_operation_complete
from xmuse_core.runtime.frontend_api import frontend_cors_kwargs

DEFAULT_RUNTIME_RECONCILE_INTERVAL_S = 5.0
DEFAULT_EXECUTION_RECONCILE_INTERVAL_S = 1.0
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatApiContext:
    root: Path
    execution_root: Path
    explicit_runtime_starter: bool
    runtime_starter: WorkroomRuntimeStarter
    runtime_stopper: WorkroomRuntimeStopper
    runtime_inspector: WorkroomRuntimeInspector
    runtime_recoverer: WorkroomRuntimeRecoverer


def _workroom_managed() -> bool:
    return os.environ.get("XMUSE_WORKROOM_MANAGED", "").strip() == "1"


async def _reconcile_workroom_runtime(
    *,
    context: ChatApiContext,
    interval_s: float,
    stop: asyncio.Event,
    app: FastAPI,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            continue
        except TimeoutError:
            pass
        try:
            app.state.workroom_runtime = await asyncio.to_thread(
                context.runtime_starter,
                context.root,
                context.execution_root,
            )
        except Exception as exc:
            logger.exception("Workroom Room runtime reconcile failed")
            app.state.workroom_runtime = {
                "schema_version": "workroom_room_runtime/v1",
                "state": "error",
                "source": "managed_reconcile",
                "detail": {
                    "code": "workroom_runtime_reconcile_failed",
                    "message": str(exc),
                },
                "authority": "backend_supervised_process",
            }


async def _reconcile_execution_runtime(
    *,
    reconcile: Callable[[], Any],
    interval_s: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            continue
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(reconcile)
        except Exception:
            logger.exception("Room execution runtime reconcile failed")


def create_chat_api_foundation(
    base_dir: Path | str,
    *,
    execution_worktree: Path | str,
    auth_token: str | None,
    auth_mode: Literal["api_key", "operator"] = "api_key",
    initialize_database: bool = True,
    workroom_runtime_starter: WorkroomRuntimeStarter | None,
    workroom_runtime_stopper: WorkroomRuntimeStopper | None,
    workroom_runtime_inspector: WorkroomRuntimeInspector | None,
    workroom_runtime_recoverer: WorkroomRuntimeRecoverer | None,
    workroom_runtime_reconcile_interval_s: float,
    title: str,
    execution_reconciler: Callable[[], Any] | None = None,
    execution_stopper: Callable[[], Any] | None = None,
    execution_reconcile_interval_s: float = DEFAULT_EXECUTION_RECONCILE_INTERVAL_S,
) -> tuple[FastAPI, ChatApiContext]:
    root = Path(base_dir)
    assert_data_operation_complete(root)
    execution_root = Path(execution_worktree)
    if (
        isinstance(workroom_runtime_reconcile_interval_s, bool)
        or not isinstance(workroom_runtime_reconcile_interval_s, int | float)
        or not math.isfinite(float(workroom_runtime_reconcile_interval_s))
        or workroom_runtime_reconcile_interval_s <= 0
    ):
        raise ValueError("workroom runtime reconcile interval must be a positive finite number")
    if (
        isinstance(execution_reconcile_interval_s, bool)
        or not isinstance(execution_reconcile_interval_s, int | float)
        or not math.isfinite(float(execution_reconcile_interval_s))
        or execution_reconcile_interval_s <= 0
    ):
        raise ValueError("execution reconcile interval must be a positive finite number")
    context = ChatApiContext(
        root=root,
        execution_root=execution_root,
        explicit_runtime_starter=workroom_runtime_starter is not None,
        runtime_starter=workroom_runtime_starter or ensure_workroom_room_runtime,
        runtime_stopper=workroom_runtime_stopper or stop_workroom_room_runtime,
        runtime_inspector=workroom_runtime_inspector or inspect_workroom_room_runtime,
        runtime_recoverer=workroom_runtime_recoverer or recover_workroom_room_runtime,
    )
    if initialize_database:
        RoomDatabase(root / "chat.db").initialize()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        managed = _workroom_managed()
        runtime_reconcile_stop = asyncio.Event()
        runtime_reconcile_task: asyncio.Task[None] | None = None
        execution_stop = asyncio.Event()
        execution_task: asyncio.Task[None] | None = None
        try:
            if managed:
                app.state.workroom_runtime_reclaimed = await asyncio.to_thread(
                    context.runtime_stopper,
                    context.root,
                )
                app.state.workroom_runtime = await asyncio.to_thread(
                    context.runtime_starter,
                    context.root,
                    context.execution_root,
                )
                runtime_reconcile_task = asyncio.create_task(
                    _reconcile_workroom_runtime(
                        context=context,
                        interval_s=float(workroom_runtime_reconcile_interval_s),
                        stop=runtime_reconcile_stop,
                        app=app,
                    ),
                    name="xmuse-workroom-runtime-reconcile",
                )
            if execution_reconciler is not None:
                try:
                    await asyncio.to_thread(execution_reconciler)
                except Exception:
                    # Execution is an optional privileged side path.  A stale
                    # controller binding or temporarily unavailable workspace must
                    # not prevent the Room API from serving durable conversation.
                    logger.exception("Initial Room execution runtime reconcile failed")
                execution_task = asyncio.create_task(
                    _reconcile_execution_runtime(
                        reconcile=execution_reconciler,
                        interval_s=float(execution_reconcile_interval_s),
                        stop=execution_stop,
                    ),
                    name="xmuse-room-execution-reconcile",
                )
            yield
        finally:
            execution_stop.set()
            if execution_task is not None:
                await asyncio.gather(execution_task, return_exceptions=True)
            if execution_stopper is not None:
                try:
                    app.state.execution_runtime_stop = await asyncio.to_thread(execution_stopper)
                except Exception:
                    # Continue stopping the Room runtime even when the Harness
                    # ledger or a controller cannot be inspected during teardown.
                    logger.exception("Room execution runtime stop failed")
                    app.state.execution_runtime_stop = {
                        "state": "error",
                        "code": "room_execution_runtime_stop_failed",
                    }
            runtime_reconcile_stop.set()
            if runtime_reconcile_task is not None:
                await asyncio.gather(runtime_reconcile_task, return_exceptions=True)
            if managed:
                app.state.workroom_runtime_stop = await asyncio.to_thread(
                    context.runtime_stopper,
                    context.root,
                )

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        **frontend_cors_kwargs(allow_credentials=True),
    )

    @app.middleware("http")
    async def require_write_auth(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        write_with_auth = auth_token and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }
        if auth_mode == "operator":
            authenticated = bool(auth_token and operator_token_matches(request, auth_token))
            detail: object = {
                "code": "operator_auth_invalid",
                "message": "operator token is missing or invalid",
            }
        else:
            authenticated = request.headers.get("X-XMUSE-API-Key") == auth_token
            detail = "authentication required"
        if write_with_auth and not authenticated:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": detail},
            )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, object]:
        try:
            runtime = context.runtime_inspector(context.root, context.execution_root)
        except Exception:
            logger.exception("Workroom Room runtime health inspection failed")
            runtime = {
                "state": "degraded",
                "code": "room_runtime_unverifiable",
                "ready": False,
            }
        runtime_ready = runtime.get("ready") is True and runtime.get("state") == "ready"
        return {
            "status": "ok" if runtime_ready else "degraded",
            "service": "xmuse-chat-api",
            "runtime": {
                "state": "ready" if runtime_ready else "degraded",
                "code": str(
                    runtime.get("code") or ("ready" if runtime_ready else "room_runtime_not_ready")
                ),
                "ready": runtime_ready,
            },
        }

    return app, context
