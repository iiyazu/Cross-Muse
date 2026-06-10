from __future__ import annotations

import json
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from xmuse_core.platform.run_health import summarize_coordinator_incidents
from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_dashboard_dead_letters(base_dir: Path) -> dict[str, Any]:
    coordinator = summarize_coordinator_incidents(xmuse_root=base_dir)
    counts = dict(coordinator.get("counts", {}))
    return {
        "kind": "dashboard_dead_letters",
        "read_only": True,
        "source_authority": "coordinator_incidents",
        "generated_at": _utc_now(),
        "degraded": bool(
            int(counts.get("dead_letter") or 0) > 0
            or int(counts.get("degraded") or 0) > 0
        ),
        **coordinator,
    }


def build_read_model_status(base_dir: Path) -> dict[str, Any]:
    specs = [
        ("resolutions", "resolutions.json", ("resolutions",)),
        ("verdicts", "verdicts.json", ("verdicts",)),
        ("self_evolution_audit", SelfEvolutionAuditWriter.AUDIT_FILE, ("entries",)),
        (
            "self_evolution_conversations",
            SelfEvolutionAuditWriter.CONVERSATIONS_FILE,
            ("conversations",),
        ),
        (
            "self_evolution_clarifications",
            SelfEvolutionAuditWriter.CLARIFICATION_FILE,
            ("clarification_requests", "clarification_resolutions"),
        ),
    ]
    models: list[dict[str, Any]] = []
    degraded_models: list[str] = []
    for name, file_name, keys in specs:
        model = read_model_file_status(
            name=name,
            path=base_dir / "read_models" / file_name,
            keys=keys,
        )
        models.append(model)
        if model["status"] != "ok":
            degraded_models.append(name)
    return {
        "kind": "read_model_status",
        "read_only": True,
        "source_authority": "read_models_directory",
        "generated_at": _utc_now(),
        "degraded": bool(degraded_models),
        "degraded_models": degraded_models,
        "models": models,
    }


def read_model_file_status(
    *,
    name: str,
    path: Path,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "keys": list(keys),
        "status": "missing",
        "item_count": 0,
    }
    if not path.exists():
        return base
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return {
            **base,
            "status": "invalid_json",
            "error": exc.msg,
        }
    except OSError as exc:
        return {
            **base,
            "status": "read_error",
            "error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            **base,
            "status": "invalid_shape",
            "error": "read model root must be an object",
        }
    item_count = 0
    missing_keys: list[str] = []
    invalid_keys: list[str] = []
    for key in keys:
        value = payload.get(key)
        if value is None:
            missing_keys.append(key)
            continue
        if not isinstance(value, list):
            invalid_keys.append(key)
            continue
        item_count += len(value)
    status_value = "invalid_shape" if missing_keys or invalid_keys else "ok"
    result = {
        **base,
        "status": status_value,
        "item_count": item_count,
        "generated_at": payload.get("generated_at"),
    }
    if missing_keys:
        result["missing_keys"] = missing_keys
    if invalid_keys:
        result["invalid_keys"] = invalid_keys
    return result
