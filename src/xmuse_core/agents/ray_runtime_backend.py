from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        return [str(value)]
    return [str(item) for item in value]


def _shadow_result(
    *,
    backend: str,
    status: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "backend": backend,
        "status": status,
        "session_id": str(request.get("session_id") or ""),
        "event_refs": _string_list(request.get("event_refs")),
        "artifact_refs": _string_list(request.get("artifact_refs")),
    }


class FakeRayRuntimeBackend:
    """Local Ray-shaped backend for shadow tests without making Ray authoritative."""

    def __init__(self) -> None:
        self.dispatch_requests: list[dict[str, Any]] = []

    @property
    def memory_state(self) -> dict[str, Any]:
        return {}

    async def shadow_dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        copied = {
            "session_id": str(request.get("session_id") or ""),
            "event_refs": _string_list(request.get("event_refs")),
            "artifact_refs": _string_list(request.get("artifact_refs")),
        }
        self.dispatch_requests.append(copied)
        return _shadow_result(
            backend="fake-ray",
            status="shadow-dispatched",
            request=request,
        )


class RayRuntimeAdapter:
    def __init__(
        self,
        *,
        enabled: bool = True,
        backend: FakeRayRuntimeBackend | None = None,
    ) -> None:
        self._enabled = enabled
        self._backend = backend or FakeRayRuntimeBackend()

    async def shadow_dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self._enabled:
            return _shadow_result(
                backend="ray-disabled",
                status="skipped",
                request=request,
            )
        return await self._backend.shadow_dispatch(request)


__all__ = ["FakeRayRuntimeBackend", "RayRuntimeAdapter"]
