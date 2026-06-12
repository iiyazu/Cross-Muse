from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from xmuse_core.integrations.memoryos_lite_interop import (
    MEMORYOS_LITE_BASE_URL_ENV,
    live_memoryos_lite_enabled,
)
from xmuse_core.integrations.memoryos_namespace import task_namespace
from xmuse_core.platform.memoryos_live_release_gate import (
    capture_memoryos_live_release_gate,
)
from xmuse_core.platform.memoryos_live_trace_capture import (
    capture_memoryos_lite_live_trace_artifact,
)
from xmuse_core.platform.natural_deliberation_release_gate import (
    capture_natural_deliberation_release_gate,
)
from xmuse_core.platform.natural_deliberation_transcript_capture import (
    export_natural_deliberation_transcript_artifact,
)
from xmuse_core.platform.operator_actions import (
    OperatorActionBlockedError,
    OperatorActionRequest,
)
from xmuse_core.platform.real_provider_runtime_release_gate import (
    capture_real_provider_runtime_release_gate,
)
from xmuse_core.platform.real_provider_runtime_soak_capture import (
    export_real_provider_runtime_soak_artifact,
)

NATURAL_EXPORT_ACTIONS = {
    "export_natural_deliberation_transcript",
    "export_natural_transcript",
    "natural_deliberation_transcript_export",
    "natural_transcript_export",
}
PROVIDER_EXPORT_ACTIONS = {
    "export_real_provider_runtime_soak",
    "export_provider_runtime_soak",
    "real_provider_runtime_soak_export",
    "provider_runtime_soak_export",
}
MEMORYOS_EXPORT_ACTIONS = {
    "export_memoryos_live_trace",
    "capture_memoryos_live_trace",
    "memoryos_live_trace_export",
    "memoryos_live_trace_capture",
}
RELEASE_EVIDENCE_EXPORT_ACTIONS = (
    NATURAL_EXPORT_ACTIONS | PROVIDER_EXPORT_ACTIONS | MEMORYOS_EXPORT_ACTIONS
)


def run_release_evidence_export_action(
    request: OperatorActionRequest,
    *,
    xmuse_root: str | Path,
    release_readiness_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    action = request.action.strip().lower().replace("-", "_")
    root = Path(xmuse_root)
    release_root = Path(release_readiness_dir or root / "work" / "release_readiness")
    environment = os.environ if env is None else env
    if action in NATURAL_EXPORT_ACTIONS:
        return _export_natural(request, root=root, release_root=release_root)
    if action in PROVIDER_EXPORT_ACTIONS:
        return _export_provider(request, root=root, release_root=release_root)
    if action in MEMORYOS_EXPORT_ACTIONS:
        return _export_memoryos(
            request,
            root=root,
            release_root=release_root,
            env=environment,
        )
    raise OperatorActionBlockedError(
        f"unknown release evidence export action: {request.action}",
        proof_level="manual_gap",
    )


def _export_natural(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
) -> dict[str, Any]:
    conversation_id = _required_text(request.payload, "conversation_id")
    artifact_path = _release_path(
        request.payload.get("output_path") or request.payload.get("artifact_path"),
        release_root=release_root,
        default=release_root / "natural-transcript.json",
    )
    gate_path = _release_path(
        request.payload.get("gate_output_path") or request.payload.get("gate_path"),
        release_root=release_root,
        default=release_root / "artifacts" / "natural-deliberation.json",
    )
    artifact = export_natural_deliberation_transcript_artifact(
        chat_db_path=root / "chat.db",
        registry_path=root / "god_sessions.json",
        conversation_id=conversation_id,
        output_path=artifact_path,
        source_refs=_string_list(request.payload.get("source_refs")),
        target_refs=_string_list(request.payload.get("target_refs")),
    )
    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact_path,
        output_path=gate_path,
    )
    return _export_result(
        kind="natural_deliberation",
        artifact_path=artifact_path,
        gate_path=gate_path,
        artifact=artifact,
        gate=gate,
    )


def _export_provider(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
) -> dict[str, Any]:
    conversation_id = _required_text(request.payload, "conversation_id")
    artifact_path = _release_path(
        request.payload.get("output_path") or request.payload.get("artifact_path"),
        release_root=release_root,
        default=release_root / "real-provider-runtime.json",
    )
    gate_path = _release_path(
        request.payload.get("gate_output_path") or request.payload.get("gate_path"),
        release_root=release_root,
        default=release_root / "artifacts" / "real-provider-runtime.json",
    )
    artifact = export_real_provider_runtime_soak_artifact(
        chat_db_path=root / "chat.db",
        registry_path=root / "god_sessions.json",
        conversation_id=conversation_id,
        fresh_inbox_item_id=_required_text(request.payload, "fresh_inbox_item_id"),
        resume_inbox_item_id=_required_text(request.payload, "resume_inbox_item_id"),
        runtime_backend=_required_text(request.payload, "runtime_backend"),
        transport=_required_text(request.payload, "transport"),
        output_path=artifact_path,
        run_id=_text(request.payload.get("run_id")),
        source_refs=_string_list(request.payload.get("source_refs")),
    )
    gate = capture_real_provider_runtime_release_gate(
        artifact_path=artifact_path,
        output_path=gate_path,
    )
    return _export_result(
        kind="real_provider_runtime",
        artifact_path=artifact_path,
        gate_path=gate_path,
        artifact=artifact,
        gate=gate,
    )


def _export_memoryos(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    if not live_memoryos_lite_enabled(env):
        raise OperatorActionBlockedError(
            "set XMUSE_LIVE_MEMORYOS_LITE=1 and XMUSE_MEMORYOS_LITE_URL to run "
            "live MemoryOS Lite trace capture",
            proof_level="manual_gap",
        )
    _ensure_no_running_event_loop()
    conversation_id = _required_text(request.payload, "conversation_id")
    artifact_path = _release_path(
        request.payload.get("output_path") or request.payload.get("artifact_path"),
        release_root=release_root,
        default=release_root / "memoryos-trace.json",
    )
    gate_path = _release_path(
        request.payload.get("gate_output_path") or request.payload.get("gate_path"),
        release_root=release_root,
        default=release_root / "artifacts" / "live-memoryos.json",
    )
    binding_store_path = _release_path(
        request.payload.get("binding_store_path") or request.payload.get("binding_store"),
        release_root=release_root,
        default=release_root / "memoryos-lite-session-bindings.json",
    )
    namespace = task_namespace(
        repo_id=_required_text(request.payload, "repo_id"),
        workspace_id=_required_text(request.payload, "workspace_id"),
        god_id=_required_text(request.payload, "god_id"),
        conversation_id=conversation_id,
        thread_id=_required_text(request.payload, "thread_id"),
        blueprint_id=_required_text(request.payload, "blueprint_id"),
        feature_id=_required_text(request.payload, "feature_id"),
        lane_id=_required_text(request.payload, "lane_id"),
    )
    artifact = asyncio.run(
        capture_memoryos_lite_live_trace_artifact(
            base_url=env[MEMORYOS_LITE_BASE_URL_ENV],
            namespace=namespace,
            actor_id=_text(request.payload.get("actor_id")) or request.actor_id,
            content=_required_text(request.payload, "content"),
            query=_required_text(request.payload, "query"),
            output_path=artifact_path,
            source_refs=_string_list(request.payload.get("source_refs")),
            metadata=_mapping(request.payload.get("metadata")),
            budget=_int_value(request.payload.get("budget"), default=4096),
            binding_store_path=binding_store_path,
        )
    )
    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact_path,
        output_path=gate_path,
    )
    return _export_result(
        kind="live_memoryos",
        artifact_path=artifact_path,
        gate_path=gate_path,
        artifact=artifact,
        gate=gate,
    )


def _export_result(
    *,
    kind: str,
    artifact_path: Path,
    gate_path: Path,
    artifact: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "artifact_path": str(artifact_path.resolve(strict=False)),
        "gate_path": str(gate_path.resolve(strict=False)),
        "artifact": artifact,
        "gate": gate,
    }


def _release_path(value: Any, *, release_root: Path, default: Path) -> Path:
    text = _text(value)
    path = default if text is None else Path(text)
    if not path.is_absolute():
        path = release_root / path
    resolved_root = release_root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise OperatorActionBlockedError(
            f"release evidence path {path} must stay under release readiness root "
            f"{release_root}",
        )
    return resolved


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _text(payload.get(key))
    if value is None:
        raise OperatorActionBlockedError(
            f"release evidence export requires payload.{key}",
            proof_level="manual_gap",
        )
    return value


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _mapping(value: Any) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return None


def _int_value(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _ensure_no_running_event_loop() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop.is_running():
        raise OperatorActionBlockedError(
            "MemoryOS live trace export requires Chat API or a non-async operator "
            "context so the live REST capture can run to completion",
            proof_level="manual_gap",
        )


__all__ = [
    "MEMORYOS_EXPORT_ACTIONS",
    "NATURAL_EXPORT_ACTIONS",
    "PROVIDER_EXPORT_ACTIONS",
    "RELEASE_EVIDENCE_EXPORT_ACTIONS",
    "run_release_evidence_export_action",
]
