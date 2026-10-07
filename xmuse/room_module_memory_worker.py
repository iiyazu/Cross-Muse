"""Module memory worker: curate module windows through MemoryOS ``/curate``.

Contract ``docs/contracts/module_memory_v1.md``. Composed only when the switch
``XMUSE_MODULE_MEMORY=on`` is set and the MemoryOS sidecar is configured;
otherwise ``compose_module_memory_worker`` returns ``None`` and nothing runs.
Memory is derived: every MemoryOS failure is recorded on the window and retried
or skipped, never raised into the Room.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from xmuse.memoryos_http_client import MemoryOSAdapterError, MemoryOSHTTPClient
from xmuse_core.chat.memoryos_supervisor import MemoryOSProfile
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_module_memory import (
    EMPTY_MAX_SENDS,
    ModuleMemoryStore,
    module_memory_enabled,
    response_has_storable_memory,
)

logger = logging.getLogger(__name__)


class CurateClient(Protocol):
    def curate(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RoomModuleMemoryWorker:
    """One pass: at most one window per active module, then refresh the views."""

    def __init__(self, *, xmuse_root: Path, client: CurateClient) -> None:
        self._root = Path(xmuse_root)
        self._client = client

    def reconcile_once(self) -> dict[str, int]:
        store = ModuleMemoryStore(self._root / "chat.db")
        counts = {"module_memory_windows": 0, "module_memory_stored": 0, "module_memory_failed": 0}
        touched: set[str] = set()
        for module in store.active_modules():
            window = store.next_window(module)
            if window is None:
                continue
            counts["module_memory_windows"] += 1
            # Empty successes are resent with the identical payload (provider
            # sampling varies) up to the retry budget; the first storable
            # response wins, otherwise the last empty one is recorded. A
            # transport failure anywhere in the sends follows the failed-call
            # path above. One runs row per window either way.
            response: Mapping[str, Any] | None = None
            for _ in range(EMPTY_MAX_SENDS):
                try:
                    response = self._client.curate(window.curate_request())
                except MemoryOSAdapterError as exc:
                    status = store.record_failure(window, exc.code)
                    counts["module_memory_failed"] += 1
                    logger.warning("module memory curate %s: %s", status, exc.code)
                    response = None
                    break
                except Exception:
                    status = store.record_failure(window, "module_memory_error")
                    counts["module_memory_failed"] += 1
                    logger.exception("module memory curate %s", status)
                    response = None
                    break
                if response_has_storable_memory(response):
                    break
            if response is None:
                continue
            try:
                result = store.store_result(window, dict(response))
            except Exception:
                # Storing never raises into the Room either: a broken store is
                # recorded like a failed call and retried, then skipped.
                status = store.record_failure(window, "module_memory_error")
                counts["module_memory_failed"] += 1
                logger.exception("module memory store %s", status)
                continue
            if int(result.get("stored", 0)) == 0:
                logger.warning(
                    "module memory empty window %s..%s recorded as empty",
                    window.first_seq,
                    window.last_seq,
                )
            counts["module_memory_stored"] += int(result["stored"])
            touched.add(module.conversation_id)
        for conversation_id in sorted(touched):
            refresh_board_views(self._root, conversation_id)
        return counts


def compose_module_memory_worker(
    *, xmuse_root: Path, environ: Mapping[str, str]
) -> RoomModuleMemoryWorker | None:
    """The worker when the switch is on and the sidecar is configured, else None."""

    if not module_memory_enabled(environ):
        return None
    url = str(environ.get("XMUSE_MEMORYOS_URL") or "").strip()
    api_key = str(environ.get("XMUSE_MEMORYOS_API_KEY") or "").strip()
    if not url or not api_key:
        logger.warning("module_memory_unavailable: the MemoryOS sidecar is not configured")
        return None
    try:
        client = MemoryOSHTTPClient(
            base_url=url,
            api_key=api_key,
            profile=cast(MemoryOSProfile, environ.get("XMUSE_MEMORYOS_PROFILE", "archive-only")),
        )
    except MemoryOSAdapterError as exc:
        logger.warning("module_memory_unavailable: %s", exc.code)
        return None
    return RoomModuleMemoryWorker(xmuse_root=xmuse_root, client=client)


__all__ = ["RoomModuleMemoryWorker", "compose_module_memory_worker"]
