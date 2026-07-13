"""Safe, read-only Workroom status and receipt projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

STATUS_SCHEMA_VERSION = "xmuse_workroom_status/v2"

_SERVICE_SAFE_FIELDS = frozenset(
    {
        "service",
        "state",
        "live",
        "ready",
        "code",
        "host",
        "surface",
        "active_delivery_count",
        "retained_cleanup_count",
    }
)


class ServiceStatus(TypedDict, total=False):
    service: str
    state: str
    live: bool
    ready: bool
    code: str | None
    host: Mapping[str, Any] | None
    surface: str | None
    active_delivery_count: int
    retained_cleanup_count: int


def safe_service_status(record: Mapping[str, Any]) -> ServiceStatus:
    """Whitelist safe status fields and discard process identity and local paths."""

    projected: ServiceStatus = {}
    for key in _SERVICE_SAFE_FIELDS:
        if key in record:
            projected[key] = record[key]  # type: ignore[literal-required]
    return projected


def project_room_runner_receipt(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project only bounded host/readiness evidence from a Runner receipt."""

    if receipt is None:
        return {"state": "unknown", "ready": False, "code": "receipt_missing"}
    result: dict[str, Any] = {
        "state": receipt.get("state", "unknown"),
        "ready": receipt.get("state") == "ready",
    }
    code = receipt.get("code")
    if isinstance(code, str):
        result["code"] = code
    host = receipt.get("host")
    if isinstance(host, Mapping):
        result["host"] = {
            key: host[key]
            for key in (
                "state",
                "code",
                "active_delivery_count",
                "retained_cleanup_count",
            )
            if key in host
        }
    return result


def project_memoryos_receipt(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project optional-sidecar state without its process or binding authority."""

    if receipt is None:
        return {"enabled": False, "state": "disabled", "code": "memoryos_disabled"}
    result: dict[str, Any] = {
        "enabled": receipt.get("enabled") is True,
        "state": receipt.get("state", "unknown"),
    }
    for key in (
        "code",
        "consecutive_restart_count",
        "next_retry_at",
        "last_healthy_at",
    ):
        if key in receipt:
            result[key] = receipt[key]
    return result


def build_status_projection(
    manifest: Mapping[str, Any] | None,
    *,
    manager_live: bool,
    required_services: Sequence[Mapping[str, Any]],
    optional_services: Sequence[Mapping[str, Any]] = (),
    sanitize_services: bool = True,
) -> tuple[int, dict[str, Any]]:
    """Build status solely from explicit probe records; never probes or writes itself."""

    if manifest is None:
        return 1, {
            "schema_version": STATUS_SCHEMA_VERSION,
            "state": "stopped",
            "services": [],
        }

    projector = safe_service_status if sanitize_services else dict
    required = [projector(item) for item in required_services]
    optional = [projector(item) for item in optional_services]
    statuses = [*required, *optional]
    ready = manager_live and all(item.get("ready") is True for item in required)
    any_live = any(item.get("live") is True for item in statuses)
    if ready:
        state = "ready"
    elif manifest.get("state") == "stopped" and not any_live:
        state = "stopped"
    elif any_live or manager_live:
        state = "degraded"
    else:
        state = "stale"
    return (0 if ready else 1), {
        "schema_version": STATUS_SCHEMA_VERSION,
        "state": state,
        "manifest_state": manifest.get("state"),
        "manager_live": manager_live,
        "services": statuses,
    }
