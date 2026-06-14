from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.operator_actions import (
    OperatorActionBlockedError,
    OperatorActionRequest,
)
from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)
from xmuse_core.platform.release_evidence_export_actions import (
    run_release_evidence_export_action,
)

_DEFAULT_KINDS = (
    "natural_deliberation",
    "real_provider_runtime",
    "live_memoryos",
    "github_server_truth",
)
_KIND_ALIASES = {
    "all": "all",
    "natural": "natural_deliberation",
    "natural_deliberation": "natural_deliberation",
    "natural-deliberation": "natural_deliberation",
    "natural-god": "natural_deliberation",
    "natural_god": "natural_deliberation",
    "transcript": "natural_deliberation",
    "provider": "real_provider_runtime",
    "real_provider": "real_provider_runtime",
    "real-provider": "real_provider_runtime",
    "real_provider_runtime": "real_provider_runtime",
    "real-provider-runtime": "real_provider_runtime",
    "runtime": "real_provider_runtime",
    "soak": "real_provider_runtime",
    "memoryos": "live_memoryos",
    "live_memoryos": "live_memoryos",
    "live-memoryos": "live_memoryos",
    "github": "github_server_truth",
    "github-truth": "github_server_truth",
    "github_truth": "github_server_truth",
    "github-server-truth": "github_server_truth",
    "github_server_truth": "github_server_truth",
}


def run_release_evidence_attempt_action(
    request: OperatorActionRequest,
    *,
    xmuse_root: str | Path,
    release_readiness_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Attempt configured release evidence exports without weakening proof gates."""

    root = Path(xmuse_root)
    release_root = Path(release_readiness_dir or root / "work" / "release_readiness")
    environment = os.environ if env is None else env
    payload = dict(request.payload)
    conversation_id = _text(payload.get("conversation_id"))
    trace_limit = _int_value(payload.get("trace_limit"), default=20)
    candidates = build_release_evidence_candidate_report(
        root,
        conversation_id=conversation_id,
        env=environment,
        memoryos_payload=payload,
        trace_limit=trace_limit,
    )
    attempts = [
        _attempt_kind(
            kind,
            request=request,
            root=root,
            release_root=release_root,
            env=environment,
            candidates=candidates,
        )
        for kind in _requested_kinds(payload)
    ]
    decision = "ok" if attempts and all(_attempt_ok(attempt) for attempt in attempts) else "blocked"
    report_path = _release_path(
        payload.get("attempt_report_path") or payload.get("report_path"),
        release_root=release_root,
        default=release_root / "release-evidence-attempt.json",
    )
    report = {
        "schema_version": "xmuse.release_evidence_attempt.v1",
        "decision": decision,
        "actor_id": request.actor_id,
        "idempotency_key": request.idempotency_key,
        "source": request.source,
        "conversation_id": conversation_id,
        "attempted_kinds": [attempt["kind"] for attempt in attempts],
        "attempts": attempts,
        "candidate_report": candidates,
        "source_authority": "operator_action_contract",
        "generated_at": _utc_now(),
    }
    _write_json(report_path, report)
    return {
        **report,
        "report_path": str(report_path.resolve(strict=False)),
    }


def _attempt_kind(
    kind: str,
    *,
    request: OperatorActionRequest,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
    candidates: Mapping[str, Any],
) -> dict[str, Any]:
    if kind == "natural_deliberation":
        return _attempt_natural(
            request,
            root=root,
            release_root=release_root,
            env=env,
            candidates=candidates,
        )
    if kind == "real_provider_runtime":
        return _attempt_provider(
            request,
            root=root,
            release_root=release_root,
            env=env,
            candidates=candidates,
        )
    if kind == "live_memoryos":
        return _attempt_memoryos(
            request,
            root=root,
            release_root=release_root,
            env=env,
            candidates=candidates,
        )
    if kind == "github_server_truth":
        return _attempt_github(
            request,
            root=root,
            release_root=release_root,
            env=env,
            candidates=candidates,
        )
    return _blocked_attempt(
        kind=kind,
        blockers=["unknown_release_evidence_kind"],
        summary=f"Unknown release evidence kind: {kind}",
    )


def _attempt_natural(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
    candidates: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = _ready_natural_candidate(candidates)
    if candidate is None:
        return _blocked_attempt(
            kind="natural_deliberation",
            blockers=_natural_blockers(candidates),
            summary="Natural GOD transcript inputs are not export-ready.",
            next_action=_natural_next_action(candidates),
        )
    payload = {
        **_export_payload(request.payload),
        "conversation_id": candidate["conversation_id"],
    }
    return _execute_export(
        kind="natural_deliberation",
        action="export_natural_deliberation_transcript",
        payload=payload,
        request=request,
        root=root,
        release_root=release_root,
        env=env,
    )


def _attempt_provider(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
    candidates: Mapping[str, Any],
) -> dict[str, Any]:
    provider = _mapping(candidates.get("real_provider_runtime"))
    blockers = list(_string_list(provider.get("blockers")))
    if provider.get("export_ready") is not True:
        return _blocked_attempt(
            kind="real_provider_runtime",
            blockers=blockers or ["provider_runtime_candidate_not_ready"],
            summary="Real provider runtime inputs are not export-ready.",
            next_action=_text(provider.get("next_action")),
        )
    runtime_backend = _text(request.payload.get("runtime_backend"))
    transport = _text(request.payload.get("transport"))
    missing = []
    if runtime_backend is None:
        missing.append("runtime_backend_missing")
    if transport is None:
        missing.append("transport_missing")
    if missing:
        return _blocked_attempt(
            kind="real_provider_runtime",
            blockers=missing,
            summary="Real provider runtime attempt requires runtime_backend and transport.",
            next_action=_text(provider.get("next_action")),
        )
    payload = {
        **_export_payload(request.payload),
        "conversation_id": _required_text(request.payload, "conversation_id"),
        "fresh_inbox_item_id": _required_text(provider, "suggested_fresh_inbox_item_id"),
        "resume_inbox_item_id": _required_text(provider, "suggested_resume_inbox_item_id"),
        "runtime_backend": runtime_backend,
        "transport": transport,
    }
    return _execute_export(
        kind="real_provider_runtime",
        action="export_real_provider_runtime_soak",
        payload=payload,
        request=request,
        root=root,
        release_root=release_root,
        env=env,
    )


def _attempt_memoryos(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
    candidates: Mapping[str, Any],
) -> dict[str, Any]:
    memoryos = _mapping(candidates.get("live_memoryos"))
    if memoryos.get("export_ready") is not True:
        return _blocked_attempt(
            kind="live_memoryos",
            blockers=list(_string_list(memoryos.get("blockers")))
            or ["memoryos_candidate_not_ready"],
            summary="Live MemoryOS inputs are not export-ready.",
            next_action=_text(memoryos.get("next_action")),
        )
    return _execute_export(
        kind="live_memoryos",
        action="export_memoryos_live_trace",
        payload=_export_payload(request.payload),
        request=request,
        root=root,
        release_root=release_root,
        env=env,
    )


def _attempt_github(
    request: OperatorActionRequest,
    *,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
    candidates: Mapping[str, Any],
) -> dict[str, Any]:
    missing: list[str] = []
    if _text(request.payload.get("repo")) is None:
        missing.append("github_repo_missing")
    if not _has_value(
        request.payload.get("pull_request_number")
        or request.payload.get("pull_request")
        or request.payload.get("pr")
    ):
        missing.append("github_pull_request_missing")
    if missing:
        return _blocked_attempt(
            kind="github_server_truth",
            blockers=missing,
            summary="GitHub server truth attempt requires repo and pull request target.",
            next_action=_github_next_action(candidates),
        )
    return _execute_export(
        kind="github_server_truth",
        action="export_github_server_truth",
        payload=_export_payload(request.payload),
        request=request,
        root=root,
        release_root=release_root,
        env=env,
    )


def _execute_export(
    *,
    kind: str,
    action: str,
    payload: Mapping[str, Any],
    request: OperatorActionRequest,
    root: Path,
    release_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    export_request = OperatorActionRequest(
        action=action,
        actor_id=request.actor_id,
        capabilities=request.capabilities,
        idempotency_key=f"{request.idempotency_key}:{action}",
        payload=dict(payload),
        source=request.source,
    )
    try:
        exported = run_release_evidence_export_action(
            export_request,
            xmuse_root=root,
            release_readiness_dir=release_root,
            env=env,
        )
    except OperatorActionBlockedError as exc:
        return _blocked_attempt(
            kind=kind,
            blockers=[exc.fact_state if exc.fact_state != "blocked" else exc.summary],
            summary=exc.summary,
            payload=exc.payload,
            proof_level=exc.proof_level,
        )
    gate = _mapping(exported.get("gate"))
    gate_status = _text(gate.get("status")) or "unknown"
    gate_proof_level = _text(gate.get("proof_level")) or "manual_gap"
    return {
        "kind": kind,
        "status": "ok",
        "proof_level": gate_proof_level,
        "fact_state": "release_evidence_exported",
        "summary": f"Attempted {kind} export.",
        "artifact_path": exported.get("artifact_path"),
        "gate_path": exported.get("gate_path"),
        "gate_status": gate_status,
        "gate_proof_level": gate_proof_level,
        "gate_id": gate.get("gate_id"),
        "blockers": _gate_blockers(gate),
    }


def _blocked_attempt(
    *,
    kind: str,
    blockers: Sequence[str],
    summary: str,
    payload: Mapping[str, Any] | None = None,
    proof_level: str = "manual_gap",
    next_action: str | None = None,
) -> dict[str, Any]:
    result = {
        "kind": kind,
        "status": "blocked",
        "proof_level": proof_level,
        "fact_state": "blocked",
        "summary": summary,
        "blockers": _dedupe([str(blocker) for blocker in blockers if str(blocker).strip()]),
        "payload": dict(payload or {}),
    }
    if next_action:
        result["next_action"] = next_action
    return result


def _attempt_ok(attempt: Mapping[str, Any]) -> bool:
    return attempt.get("status") == "ok" and attempt.get("gate_status") == "ok"


def _ready_natural_candidate(candidates: Mapping[str, Any]) -> Mapping[str, Any] | None:
    natural = _mapping(candidates.get("natural_deliberation"))
    conversations = natural.get("conversations")
    if not isinstance(conversations, Sequence) or isinstance(conversations, (str, bytes)):
        return None
    for conversation in conversations:
        if isinstance(conversation, Mapping) and conversation.get("export_ready") is True:
            return conversation
    return None


def _natural_blockers(candidates: Mapping[str, Any]) -> list[str]:
    natural = _mapping(candidates.get("natural_deliberation"))
    conversations = natural.get("conversations")
    blockers: list[str] = []
    if isinstance(conversations, Sequence) and not isinstance(conversations, (str, bytes)):
        for conversation in conversations:
            if isinstance(conversation, Mapping):
                blockers.extend(_string_list(conversation.get("blockers")))
    return blockers or _string_list(natural.get("blockers")) or [
        "natural_deliberation_candidate_not_ready"
    ]


def _natural_next_action(candidates: Mapping[str, Any]) -> str | None:
    natural = _mapping(candidates.get("natural_deliberation"))
    conversations = natural.get("conversations")
    if isinstance(conversations, Sequence) and not isinstance(conversations, (str, bytes)):
        for conversation in conversations:
            if isinstance(conversation, Mapping):
                next_action = _text(conversation.get("next_action"))
                if next_action is not None:
                    return next_action
    return _text(natural.get("next_action"))


def _github_next_action(candidates: Mapping[str, Any]) -> str | None:
    github = _mapping(candidates.get("github_server_truth"))
    return _text(github.get("next_action"))


def _requested_kinds(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw_values: list[str] = []
    for key in ("kinds", "kind"):
        value = payload.get(key)
        if isinstance(value, str):
            raw_values.extend(item.strip() for item in value.split(",") if item.strip())
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            raw_values.extend(str(item).strip() for item in value if str(item).strip())
    if not raw_values:
        return _DEFAULT_KINDS
    normalized: list[str] = []
    for raw in raw_values:
        kind = _KIND_ALIASES.get(raw.strip().lower().replace("_", "-"))
        if kind == "all":
            return _DEFAULT_KINDS
        if kind and kind not in normalized:
            normalized.append(kind)
    return tuple(normalized or _DEFAULT_KINDS)


def _export_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    blocked_keys = {"kind", "kinds", "attempt_report_path", "report_path", "trace_limit"}
    return {str(key): value for key, value in payload.items() if str(key) not in blocked_keys}


def _release_path(value: Any, *, release_root: Path, default: Path) -> Path:
    text = _text(value)
    path = default if text is None else Path(text)
    if text is not None and not path.is_absolute():
        path = release_root / path
    resolved_root = release_root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise OperatorActionBlockedError(
            f"release evidence attempt path {path} must stay under release readiness root "
            f"{release_root}",
        )
    return resolved


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _text(payload.get(key))
    if value is None:
        raise OperatorActionBlockedError(
            f"release evidence attempt requires payload.{key}",
            proof_level="manual_gap",
        )
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _has_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _gate_blockers(gate: Mapping[str, Any]) -> list[str]:
    blockers = _string_list(gate.get("blockers"))
    if blockers:
        return blockers
    if _text(gate.get("status")) == "ok":
        return []
    summary = _text(gate.get("summary"))
    return [summary] if summary else []


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["run_release_evidence_attempt_action"]
