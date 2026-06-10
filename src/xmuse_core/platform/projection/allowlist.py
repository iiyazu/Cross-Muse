from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

RUNTIME_TELEMETRY_FIELDS = frozenset(
    {
        "recovery_events",
        "last_recovery_event",
        "failure_error",
        "provider_health",
        "runtime_telemetry",
        "stdout",
        "stderr",
        "worker_command",
        "worker_logs",
        "review_text",
        "dashboard_summary",
    }
)
_PROMPT_REF_DIR = Path("logs/lane_prompts")
_PROMPT_SUMMARY_MAX_CHARS = 160


class ProjectionFieldPolicy:
    def sanitize_lane(
        self,
        payload: dict[str, Any],
        *,
        projection_root: Path,
    ) -> dict[str, Any]:
        sanitized = self._sanitize_fields(payload)
        prompt = sanitized.pop("prompt", None)
        if isinstance(prompt, str):
            prompt = prompt.strip()
            if prompt:
                sanitized.setdefault("prompt_summary", _prompt_summary(prompt))
                if not _has_prompt_ref(sanitized):
                    sanitized["prompt_ref"] = _write_prompt_artifact(
                        projection_root=projection_root,
                        lane_id=_projection_lane_artifact_id(sanitized),
                        prompt=prompt,
                    )
        return sanitized

    def sanitize_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._sanitize_fields(payload)

    def _sanitize_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = {
            key: value
            for key, value in payload.items()
            if key not in RUNTIME_TELEMETRY_FIELDS
        }
        command_hash = _command_hash(payload.get("worker_command"))
        if command_hash is not None:
            sanitized["command_hash"] = command_hash
        return sanitized


_DEFAULT_POLICY = ProjectionFieldPolicy()


def strip_runtime_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    return _DEFAULT_POLICY.sanitize_metadata(payload)


def sanitize_projection_lane(
    payload: dict[str, Any],
    *,
    projection_root: Path,
) -> dict[str, Any]:
    return _DEFAULT_POLICY.sanitize_lane(payload, projection_root=projection_root)


def normalize_mutation_audit(audit: Any, *, tool_name: str) -> dict[str, str]:
    if not isinstance(audit, dict):
        raise ValueError(f"{tool_name} requires audit metadata")
    normalized: dict[str, str] = {}
    for field_name in ("actor", "reason", "request_id"):
        value = audit.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{tool_name} audit.{field_name} is required")
        normalized[field_name] = value.strip()
    return normalized


def stamp_mutation_audit(
    payload: dict[str, Any],
    *,
    audit: dict[str, str],
    tool_name: str,
) -> dict[str, Any]:
    payload["last_mutation_audit"] = {
        "actor": audit["actor"],
        "reason": audit["reason"],
        "request_id": audit["request_id"],
        "tool": tool_name,
    }
    return payload


def _command_hash(command: Any) -> str | None:
    if command is None:
        return None
    normalized = _normalize_hashable_value(command)
    digest = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _normalize_hashable_value(value: Any) -> Any:
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, dict):
        return {
            str(key): _normalize_hashable_value(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_hashable_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _has_prompt_ref(lane: dict[str, Any]) -> bool:
    prompt_ref = lane.get("prompt_ref")
    return isinstance(prompt_ref, str) and bool(prompt_ref.strip())


def _projection_lane_artifact_id(lane: dict[str, Any]) -> str:
    value = lane.get("feature_id") or lane.get("lane_id") or "lane"
    text = str(value).strip() or "lane"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "lane"
    if len(safe) <= 96:
        return safe
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{safe[:83]}-{digest}"


def _write_prompt_artifact(
    *,
    projection_root: Path,
    lane_id: str,
    prompt: str,
) -> str:
    relative_path = _PROMPT_REF_DIR / f"{lane_id}.md"
    artifact_path = projection_root / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    if not artifact_path.exists() or artifact_path.read_text(encoding="utf-8") != prompt:
        artifact_path.write_text(prompt, encoding="utf-8")
    return relative_path.as_posix()


def _prompt_summary(prompt: str) -> str:
    compact = " ".join(prompt.split())
    if len(compact) <= _PROMPT_SUMMARY_MAX_CHARS:
        return compact
    return compact[: _PROMPT_SUMMARY_MAX_CHARS - 14].rstrip() + "...<truncated>"
