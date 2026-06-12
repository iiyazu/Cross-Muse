from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REQUIRED_STAGE_ORDER = (
    "ray_actor_delivery_start",
    "codex_app_server_turn_start",
    "chat_post_message",
    "trace_persisted",
)


def capture_real_provider_runtime_release_gate(
    *,
    artifact_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    payload, load_error = _load_artifact(artifact)
    gate = build_real_provider_runtime_release_gate(
        payload,
        artifact_path=artifact,
        load_error=load_error,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gate


def build_real_provider_runtime_release_gate(
    runtime_artifact: dict[str, Any] | None,
    *,
    artifact_path: str | Path,
    load_error: str | None = None,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    if runtime_artifact is None:
        return _blocked_gate(
            summary=load_error or "Real provider runtime artifact is unavailable.",
            artifact_path=artifact,
            source_refs=[],
            proof_level="manual_gap",
        )

    source_refs = _source_refs(runtime_artifact)
    schema_version = _text(runtime_artifact.get("schema_version"))
    if schema_version != "xmuse.real_provider_runtime.v1":
        return _blocked_gate(
            summary=(
                "Real provider runtime artifact schema_version must be "
                "xmuse.real_provider_runtime.v1."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    proof_level = _text(runtime_artifact.get("proof_level"))
    if proof_level != "real_provider_proof":
        return _blocked_gate(
            summary=(
                "Real provider runtime gate requires real_provider_proof; got "
                f"{proof_level or '<missing>'}."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    provider_runtime = _dict(runtime_artifact.get("provider_runtime"))
    provider_id = _text(provider_runtime.get("provider_id"))
    runtime_backend = _text(provider_runtime.get("runtime_backend"))
    transport = _text(provider_runtime.get("transport"))
    provider_session_id = _text(provider_runtime.get("provider_session_id"))
    if (
        provider_id is None
        or runtime_backend is None
        or transport is None
        or provider_session_id is None
        or provider_runtime.get("mcp_writeback") is not True
    ):
        return _blocked_gate(
            summary=(
                "Real provider runtime artifact is missing provider, session, "
                "runtime backend, transport, or MCP writeback metadata."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    if _is_fake_or_local(runtime_backend) or _is_fake_or_local(transport):
        return _blocked_gate(
            summary=(
                "Real provider runtime gate rejects fake/local/stdout runtime "
                f"evidence: runtime_backend={runtime_backend}, transport={transport}."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    turns = _dicts(runtime_artifact.get("turns"))
    if len(turns) < 2:
        return _blocked_gate(
            summary="Real provider runtime soak requires at least two provider turns.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    phases = {_text(turn.get("phase")) for turn in turns}
    if not {"fresh", "resume"}.issubset(phases):
        return _blocked_gate(
            summary="Real provider runtime soak requires both fresh and resume turns.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    restart_resume = _dict(runtime_artifact.get("restart_resume"))
    if (
        restart_resume.get("provider_session_reused") is not True
        or _text(restart_resume.get("fresh_provider_session_id")) != provider_session_id
        or _text(restart_resume.get("resumed_provider_session_id")) != provider_session_id
    ):
        return _blocked_gate(
            summary=(
                "Real provider runtime soak requires restart/resume evidence with "
                "the same provider session id."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    turn_gap = _first_turn_gap(
        turns,
        provider_id=provider_id,
        provider_session_id=provider_session_id,
        runtime_backend=runtime_backend,
        transport=transport,
    )
    if turn_gap is not None:
        return _blocked_gate(
            summary=turn_gap,
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    blockers = _dicts(runtime_artifact.get("blockers"))
    if _text(runtime_artifact.get("fact_state")) == "blocked" or blockers:
        return _blocked_gate(
            summary=f"Real provider runtime soak has {len(blockers) or 1} unresolved blockers.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="real_provider_proof",
            next_action="Resolve real provider runtime blockers before release readiness.",
        )

    return _ok_gate(
        summary=(
            "Real provider runtime soak captured MCP writeback and restart/resume "
            f"proof for {provider_id} through {runtime_backend}/{transport}."
        ),
        artifact_path=artifact,
        source_refs=source_refs,
    )


def _load_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"Real provider runtime artifact does not exist: {path}."
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Real provider runtime artifact could not be read: {exc}."
    if not isinstance(payload, dict):
        return None, "Real provider runtime artifact must be a JSON object."
    return payload, None


def _first_turn_gap(
    turns: list[dict[str, Any]],
    *,
    provider_id: str,
    provider_session_id: str,
    runtime_backend: str,
    transport: str,
) -> str | None:
    for index, turn in enumerate(turns, start=1):
        if _text(turn.get("delivery_mode")) != "mcp_writeback":
            return "Real provider runtime requires mcp_writeback delivery for every turn."
        if turn.get("degraded_reason") is not None:
            return "Real provider runtime turns must not contain degraded fallback reasons."
        if _text(turn.get("provider_id")) != provider_id:
            return f"Real provider runtime turn {index} provider_id does not match."
        if _text(turn.get("provider_session_id")) != provider_session_id:
            return f"Real provider runtime turn {index} provider_session_id does not match."
        if _text(turn.get("runtime_backend")) != runtime_backend:
            return f"Real provider runtime turn {index} runtime_backend does not match."
        if _text(turn.get("transport")) != transport:
            return f"Real provider runtime turn {index} transport does not match."
        if _is_fake_or_local(str(turn.get("runtime_backend") or "")) or _is_fake_or_local(
            str(turn.get("transport") or "")
        ):
            return "Real provider runtime turns must not use fake/local/stdout transports."
        if not _has_ordered_stage_timings(_dict(turn.get("stage_timings"))):
            return (
                "Real provider runtime turns require finite ordered stage timings for "
                f"{', '.join(_REQUIRED_STAGE_ORDER)}."
            )
    return None


def _has_ordered_stage_timings(stages: dict[str, Any]) -> bool:
    stage_times: list[float] = []
    for name in _REQUIRED_STAGE_ORDER:
        stage = _dict(stages.get(name))
        at = stage.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            return False
        stage_time = float(at)
        if not math.isfinite(stage_time):
            return False
        stage_times.append(stage_time)
    return stage_times == sorted(stage_times)


def _ok_gate(
    *,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
) -> dict[str, Any]:
    return _gate(
        status="ok",
        proof_level="real_provider_proof",
        summary=summary,
        artifact_path=artifact_path,
        source_refs=source_refs,
        next_action="Attach this real provider runtime gate to release readiness.",
    )


def _blocked_gate(
    *,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
    proof_level: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    return _gate(
        status="blocked",
        proof_level=proof_level,
        summary=summary,
        artifact_path=artifact_path,
        source_refs=source_refs,
        next_action=next_action
        or (
            "Run the configured real provider/Ray/Codex/OpenCode soak and capture "
            "a real-provider runtime artifact."
        ),
    )


def _gate(
    *,
    status: str,
    proof_level: str,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": "real-provider-runtime",
        "kind": "real_provider",
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "operator",
        "summary": summary,
        "attempted_command": "uv run xmuse-real-provider-runtime-gate-capture",
        "next_action": next_action,
        "source_refs": source_refs,
        "artifacts": [str(artifact_path)],
        "generated_at": _utc_now(),
    }


def _source_refs(runtime_artifact: dict[str, Any]) -> list[str]:
    refs = _string_list(runtime_artifact.get("source_refs"))
    run_id = _text(runtime_artifact.get("run_id"))
    conversation_id = _text(runtime_artifact.get("conversation_id"))
    provider_runtime = _dict(runtime_artifact.get("provider_runtime"))
    provider_id = _text(provider_runtime.get("provider_id"))
    provider_session_id = _text(provider_runtime.get("provider_session_id"))
    if run_id is not None:
        refs.append(f"provider_runtime:{run_id}")
    if conversation_id is not None:
        refs.append(f"conversation:{conversation_id}")
    if provider_id is not None:
        refs.append(f"provider:{provider_id}")
    if provider_session_id is not None:
        refs.append(f"provider_session:{provider_session_id}")
    return _dedupe(refs)


def _is_fake_or_local(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ("fake", "fixture", "local", "stdout"))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
