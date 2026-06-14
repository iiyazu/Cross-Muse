from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.platform.god_runtime_continuity import (
    build_selected_god_runtime_continuity_view,
)
from xmuse_core.platform.memoryos_live_release_gate import (
    build_memoryos_live_release_gate,
)
from xmuse_core.platform.natural_deliberation_release_gate import (
    build_natural_deliberation_release_gate,
)
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import (
    GodCliRegistry,
    build_default_god_cli_registry,
)
from xmuse_core.providers.god_cli_selection_store import (
    GodCliSelectionRecord,
    GodCliSelectionStore,
)

_MEMORYOS_REQUIRED_ENV = ("XMUSE_LIVE_MEMORYOS_LITE", "XMUSE_MEMORYOS_LITE_URL")
_MEMORYOS_LIVE_TRACE_ARTIFACT_ENV = "XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT"
_GOD_ROOM_REVIEW_CLOSURE_ARTIFACT_ENV = "XMUSE_GOD_ROOM_REVIEW_CLOSURE_ARTIFACT"
_GOD_ROOM_RUNTIME_CLOSURE_ARTIFACT_ENV = "XMUSE_GOD_ROOM_RUNTIME_CLOSURE_ARTIFACT"
_NATURAL_TRANSCRIPT_ARTIFACT_ENV = "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH"
_NATURAL_RUNTIME_ARTIFACT_ENV = "XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT"
_MEMORYOS_REQUIRED_PAYLOAD = (
    "repo_id",
    "workspace_id",
    "god_id",
    "conversation_id",
    "thread_id",
    "blueprint_id",
    "feature_id",
    "lane_id",
    "content",
    "query",
)
_PROVIDER_NEXT_ACTION = (
    "Capture fresh and resume MCP writeback provider turns, then run "
    "attempt_release_evidence for real_provider_runtime with real "
    "runtime_backend and transport labels."
)
_MEMORYOS_NEXT_ACTION = (
    "Configure live MemoryOS Lite and provide a complete task payload, then "
    "run attempt_release_evidence for live_memoryos to capture a live trace."
)
_NATURAL_NEXT_ACTION = (
    "Capture a natural multi-GOD transcript and selected GOD runtime "
    "continuity, then run attempt_release_evidence for natural_deliberation."
)
_GITHUB_NEXT_ACTION = (
    "Provide repo and pull_request_number, then run attempt_release_evidence "
    "for github_server_truth to capture read-only GitHub server truth."
)
_MEMORYOS_PAYLOAD_HINT_KEYS = (
    "conversation_id",
    "repo_id",
    "workspace_id",
    "god_id",
    "thread_id",
    "blueprint_id",
    "feature_id",
    "lane_id",
)


def build_release_evidence_candidate_report(
    xmuse_root: str | Path,
    *,
    conversation_id: str | None = None,
    env: Mapping[str, str] | None = None,
    memoryos_payload: Mapping[str, Any] | None = None,
    trace_limit: int = 20,
) -> dict[str, Any]:
    root = Path(xmuse_root)
    chat_db_path = root / "chat.db"
    environment = dict(env or {})
    session_records = _session_records(root / "god_sessions.json")
    sessions = _session_index(session_records)
    god_cli_registry = _god_cli_registry(root)
    god_cli_selections = GodCliSelectionStore(root / "god_cli_selections.json").list_records()
    memoryos_inputs = dict(memoryos_payload or {})
    if conversation_id and not _text(memoryos_inputs.get("conversation_id")):
        memoryos_inputs["conversation_id"] = conversation_id
    return {
        "schema_version": "xmuse.release_evidence_candidates.v1",
        "generated_at": _utc_now(),
        "conversation_id": conversation_id,
        "natural_deliberation": _natural_candidates(
            chat_db_path,
            env=environment,
            sessions=sessions,
            session_records=session_records,
            god_cli_registry=god_cli_registry,
            god_cli_selections=god_cli_selections,
            conversation_id=conversation_id,
        ),
        "real_provider_runtime": _provider_candidates(
            chat_db_path,
            sessions=sessions,
            conversation_id=conversation_id,
            trace_limit=trace_limit,
        ),
        "live_memoryos": _memoryos_candidates(
            env=environment,
            payload=memoryos_inputs,
        ),
        "github_server_truth": _github_candidates(payload=memoryos_inputs),
    }


def _natural_candidates(
    chat_db_path: Path,
    *,
    env: Mapping[str, str],
    sessions: Mapping[tuple[str, str], GodSessionRecord],
    session_records: list[GodSessionRecord],
    god_cli_registry: GodCliRegistry,
    god_cli_selections: list[GodCliSelectionRecord],
    conversation_id: str | None,
) -> dict[str, Any]:
    artifact = _natural_artifact_candidate(env)
    conversations = []
    if not chat_db_path.exists():
        return {
            "conversation_count": 0,
            "conversations": [],
            "export_ready": False,
            "blockers": ["chat_db_missing"],
            **artifact,
        }
    with _connect(chat_db_path) as conn:
        for conversation in _conversation_rows(conn, conversation_id=conversation_id):
            message_rows = conn.execute(
                """
                select id, author, role, envelope_type, envelope_json
                from messages
                where conversation_id = ?
                order by created_at asc
                """,
                (conversation["id"],),
            ).fetchall()
            messages = [
                message
                for message in (_speech_message(row) for row in message_rows)
                if message is not None
            ]
            god_ids = _ordered_unique(
                _text(message.get("god_id")) for message in messages
            )
            participant_ids = _ordered_unique(
                _text(message.get("participant_id")) for message in messages
            )
            missing_sessions = [
                participant_id
                for participant_id in participant_ids
                if not _provider_session_id(
                    sessions.get((conversation["id"], participant_id))
                )
            ]
            transcript_blockers = []
            if not messages:
                transcript_blockers.append("natural_god_speech_act_messages_missing")
            if messages and len(god_ids) < 2:
                transcript_blockers.append("natural_deliberation_requires_two_gods")
            if missing_sessions:
                transcript_blockers.append("provider_session_metadata_missing")
            runtime = _selected_runtime_candidate(
                conversation_id=conversation["id"],
                god_ids=god_ids,
                sessions=session_records,
                god_cli_registry=god_cli_registry,
                selections=god_cli_selections,
            )
            blockers = [
                *transcript_blockers,
                *_string_list(runtime.get("blockers")),
            ]
            conversations.append(
                {
                    "conversation_id": conversation["id"],
                    "title": conversation["title"],
                    "god_speech_act_count": len(messages),
                    "distinct_god_count": len(god_ids),
                    "god_ids": god_ids,
                    "participant_ids": participant_ids,
                    "missing_provider_session_participant_ids": missing_sessions,
                    "transcript_export_ready": not transcript_blockers,
                    "selected_god_runtime": runtime,
                    "export_ready": not blockers,
                    "blockers": blockers,
                    **_natural_candidate_guidance(conversation_id=conversation["id"]),
                }
            )
    return {
        "conversation_count": len(conversations),
        "conversations": conversations,
        "export_ready": any(item["export_ready"] for item in conversations),
        **artifact,
    }


def _natural_artifact_candidate(env: Mapping[str, str]) -> dict[str, Any]:
    transcript_path = _text(env.get(_NATURAL_TRANSCRIPT_ARTIFACT_ENV))
    runtime_path = _text(env.get(_NATURAL_RUNTIME_ARTIFACT_ENV))
    base = {
        "artifact_configured": transcript_path is not None,
        "artifact_path": transcript_path,
        "runtime_artifact_configured": runtime_path is not None,
        "runtime_artifact_path": runtime_path,
        "artifact_gate_ready": False,
        "artifact_gate_status": None,
        "artifact_proof_level": None,
        "artifact_summary": None,
        "artifact_message_count": 0,
        "artifact_distinct_god_count": 0,
        "artifact_runtime_peer_god_ready_count": 0,
    }
    if transcript_path is None:
        return base
    transcript, transcript_error = _json_file(
        Path(transcript_path),
        subject="Natural deliberation transcript",
    )
    runtime = None
    runtime_error = None
    if runtime_path is not None:
        runtime, runtime_error = _json_file(
            Path(runtime_path),
            subject="Selected GOD runtime continuity",
        )
    gate = build_natural_deliberation_release_gate(
        transcript,
        artifact_path=transcript_path,
        load_error=transcript_error,
        god_runtime_continuity=runtime,
        god_runtime_path=runtime_path,
        god_runtime_load_error=runtime_error,
    )
    detail = gate.get("deliberation_transcript")
    if not isinstance(detail, dict):
        detail = {}
    result = {
        **base,
        "artifact_gate_ready": gate.get("status") == "ok",
        "artifact_gate_status": _text(gate.get("status")),
        "artifact_proof_level": _text(gate.get("proof_level")),
        "artifact_summary": _text(gate.get("summary")),
        "artifact_message_count": _non_negative_int(detail.get("message_count")),
        "artifact_distinct_god_count": _non_negative_int(
            detail.get("distinct_god_count")
        ),
        "artifact_runtime_peer_god_ready_count": _non_negative_int(
            detail.get("runtime_peer_god_ready_count")
        ),
        "source_authority": _natural_artifact_source_authority(
            transcript_path=transcript_path,
            runtime_path=runtime_path,
        ),
        "suggested_existing_artifact_action": _natural_existing_artifact_action(
            transcript_path=transcript_path,
            runtime_path=runtime_path,
        ),
    }
    return result


def _natural_artifact_source_authority(
    *,
    transcript_path: str,
    runtime_path: str | None,
) -> list[str]:
    authority = ["natural_deliberation_transcript_artifact"]
    if runtime_path is not None:
        authority.append("selected_god_runtime_artifact")
    authority.append("natural_deliberation_release_gate")
    return authority


def _natural_existing_artifact_action(
    *,
    transcript_path: str,
    runtime_path: str | None,
) -> dict[str, Any]:
    payload_hints = {"natural_deliberation_transcript": transcript_path}
    if runtime_path is not None:
        payload_hints["natural_deliberation_god_runtime"] = runtime_path
    return {
        "action": "capture_release_evidence_pack",
        "kind": "natural_deliberation",
        "payload_hints": payload_hints,
    }


def _natural_candidate_guidance(conversation_id: str) -> dict[str, Any]:
    return {
        "proof_boundary": "candidate_report_is_not_natural_deliberation_proof",
        "required_transcript_schema": "xmuse.operator_transcript.v1",
        "required_runtime_schema": "xmuse.god_runtime_continuity.v1",
        "required_proof_level": "real_provider_proof",
        "source_authority": [
            "chat_store.messages.god_speech_act",
            "god_session_registry.provider_session_bindings",
            "god_cli_selection_store",
            "god_cli_registry",
        ],
        "next_action": _NATURAL_NEXT_ACTION,
        "suggested_operator_action": {
            "action": "attempt_release_evidence",
            "kind": "natural_deliberation",
            "required_payload_keys": ["conversation_id"],
            "payload_hints": {"conversation_id": conversation_id},
        },
    }


def _selected_runtime_candidate(
    *,
    conversation_id: str,
    god_ids: list[str],
    sessions: list[GodSessionRecord],
    god_cli_registry: GodCliRegistry,
    selections: list[GodCliSelectionRecord],
) -> dict[str, Any]:
    runtime = build_selected_god_runtime_continuity_view(
        conversation_id=conversation_id,
        selections=selections,
        sessions=sessions,
        god_cli_registry=god_cli_registry,
    )
    items = _dicts(runtime.get("items"))
    present_god_ids = _ordered_unique(_text(item.get("god_id")) for item in items)
    missing_god_ids = [god_id for god_id in god_ids if god_id not in present_god_ids]
    not_ready_god_ids = [
        _text(item.get("god_id")) or _text(item.get("cli_id")) or "unknown"
        for item in items
        if item.get("peer_god_ready") is not True
    ]
    blockers: list[str] = []
    if not items:
        blockers.append("selected_god_runtime_missing")
    if missing_god_ids:
        blockers.append("selected_god_runtime_missing_transcript_gods")
    if not_ready_god_ids:
        blockers.append("selected_god_runtime_not_peer_god_ready")
    return {
        "schema_version": runtime.get("schema_version"),
        "fact_state": runtime.get("fact_state"),
        "proof_level": runtime.get("proof_level"),
        "manual_gap_reason": runtime.get("manual_gap_reason"),
        "peer_god_ready_count": sum(
            1 for item in items if item.get("peer_god_ready") is True
        ),
        "required_god_ids": god_ids,
        "present_god_ids": present_god_ids,
        "missing_god_ids": missing_god_ids,
        "not_ready_god_ids": not_ready_god_ids,
        "source_refs": _string_list(runtime.get("source_refs")),
        "blockers": blockers,
    }


def _provider_candidates(
    chat_db_path: Path,
    *,
    sessions: Mapping[tuple[str, str], GodSessionRecord],
    conversation_id: str | None,
    trace_limit: int,
) -> dict[str, Any]:
    if not chat_db_path.exists():
        return _provider_gap("chat_db_missing", trace_table_present=False)
    with _connect(chat_db_path) as conn:
        if not _table_exists(conn, "peer_turn_latency_traces"):
            return _provider_gap(
                "peer_turn_latency_traces_table_missing",
                trace_table_present=False,
            )
        query = (
            "select * from peer_turn_latency_traces "
            "where conversation_id = ? "
            "order by writeback_at asc limit ?"
            if conversation_id
            else "select * from peer_turn_latency_traces order by writeback_at asc limit ?"
        )
        params: tuple[Any, ...] = (
            (conversation_id, trace_limit) if conversation_id else (trace_limit,)
        )
        rows = conn.execute(query, params).fetchall()
    traces = [_trace_candidate(dict(row), sessions=sessions) for row in rows]
    eligible = [
        trace
        for trace in traces
        if trace["delivery_mode"] == "mcp_writeback"
        and trace["degraded_reason"] is None
        and trace["provider_session_id"]
    ]
    suggested = _suggest_fresh_resume(eligible)
    blockers = []
    if len(eligible) < 2:
        blockers.append("provider_runtime_requires_two_mcp_writeback_traces")
    if any(trace["provider_session_id_missing"] for trace in traces):
        blockers.append("provider_session_metadata_missing")
    export_ready = suggested is not None and not blockers
    return {
        "trace_table_present": True,
        "trace_count": len(traces),
        "traces": traces,
        "export_ready": export_ready,
        "suggested_fresh_inbox_item_id": suggested[0] if suggested else None,
        "suggested_resume_inbox_item_id": suggested[1] if suggested else None,
        "blockers": [] if export_ready else blockers,
        **_provider_candidate_guidance(
            conversation_id=conversation_id,
            suggested=suggested,
        ),
    }


def _memoryos_candidates(
    *,
    env: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _memoryos_trace_artifact_candidate(env)
    review_closure = _memoryos_review_closure_candidate(env, payload)
    runtime_closure = _memoryos_runtime_closure_candidate(env, payload)
    missing_env = [
        key
        for key in _MEMORYOS_REQUIRED_ENV
        if not _text(env.get(key))
        or (key == "XMUSE_LIVE_MEMORYOS_LITE" and env.get(key) != "1")
    ]
    missing_payload = [
        key for key in _MEMORYOS_REQUIRED_PAYLOAD if not _text(payload.get(key))
    ]
    artifact_blockers = (
        []
        if not artifact["artifact_configured"] or artifact["artifact_gate_ready"]
        else ["memoryos_live_trace_artifact_not_ready"]
    )
    review_closure_blockers = (
        []
        if not review_closure["artifact_configured"]
        or review_closure["artifact_gate_ready"]
        else ["god_room_review_closure_artifact_not_ready"]
    )
    runtime_closure_blockers = (
        []
        if not runtime_closure["artifact_configured"]
        or runtime_closure["artifact_gate_ready"]
        else ["god_room_runtime_closure_artifact_not_ready"]
    )
    return {
        "configured": not missing_env or artifact["artifact_configured"],
        "export_ready": not missing_env and not missing_payload,
        "env_keys_present": sorted(
            key
            for key in (
                *_MEMORYOS_REQUIRED_ENV,
                _MEMORYOS_LIVE_TRACE_ARTIFACT_ENV,
                _GOD_ROOM_REVIEW_CLOSURE_ARTIFACT_ENV,
                _GOD_ROOM_RUNTIME_CLOSURE_ARTIFACT_ENV,
            )
            if key in env
        ),
        "missing_env_keys": missing_env,
        "missing_payload_keys": missing_payload,
        "blockers": [
            *(
                ["memoryos_lite_live_environment_missing"]
                if missing_env
                else []
            ),
            *(
                ["memoryos_task_payload_incomplete"]
                if missing_payload
                else []
            ),
            *artifact_blockers,
            *review_closure_blockers,
            *runtime_closure_blockers,
        ],
        **artifact,
        "review_closure_artifact_configured": review_closure["artifact_configured"],
        "review_closure_artifact_path": review_closure["artifact_path"],
        "review_closure_artifact_gate_ready": review_closure["artifact_gate_ready"],
        "review_closure_artifact_summary": review_closure["artifact_summary"],
        "review_closure_source_ref_count": review_closure["source_ref_count"],
        "runtime_closure_artifact_configured": runtime_closure["artifact_configured"],
        "runtime_closure_artifact_path": runtime_closure["artifact_path"],
        "runtime_closure_artifact_gate_ready": runtime_closure["artifact_gate_ready"],
        "runtime_closure_artifact_summary": runtime_closure["artifact_summary"],
        "runtime_closure_source_ref_count": runtime_closure["source_ref_count"],
        **_memoryos_candidate_guidance(
            payload,
            artifact=artifact,
            review_closure=review_closure,
            runtime_closure=runtime_closure,
        ),
    }


def _memoryos_trace_artifact_candidate(env: Mapping[str, str]) -> dict[str, Any]:
    artifact_path = _text(env.get(_MEMORYOS_LIVE_TRACE_ARTIFACT_ENV))
    base = {
        "artifact_configured": artifact_path is not None,
        "artifact_path": artifact_path,
        "artifact_gate_ready": False,
        "artifact_gate_status": None,
        "artifact_proof_level": None,
        "artifact_summary": None,
        "artifact_trace_event_count": 0,
        "artifact_source_ref_count": 0,
    }
    if artifact_path is None:
        return base
    payload, load_error = _json_file(
        Path(artifact_path),
        subject="MemoryOS Lite trace artifact",
    )
    gate = build_memoryos_live_release_gate(
        payload,
        artifact_path=artifact_path,
        load_error=load_error,
    )
    trace_detail = gate.get("memoryos_trace")
    if not isinstance(trace_detail, dict):
        trace_detail = {}
    return {
        **base,
        "artifact_gate_ready": gate.get("status") == "ok",
        "artifact_gate_status": _text(gate.get("status")),
        "artifact_proof_level": _text(gate.get("proof_level")),
        "artifact_summary": _text(gate.get("summary")),
        "artifact_trace_event_count": _non_negative_int(
            trace_detail.get("trace_event_count")
        ),
        "artifact_source_ref_count": _non_negative_int(
            trace_detail.get("source_ref_count")
        ),
    }


def _memoryos_review_closure_candidate(
    env: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    artifact_path = _text(payload.get("god_room_review_closure")) or _text(
        env.get(_GOD_ROOM_REVIEW_CLOSURE_ARTIFACT_ENV)
    )
    base = {
        "artifact_configured": artifact_path is not None,
        "artifact_path": artifact_path,
        "artifact_gate_ready": False,
        "artifact_summary": None,
        "source_refs": [],
        "source_ref_count": 0,
    }
    if artifact_path is None:
        return base
    artifact, load_error = _json_file(
        Path(artifact_path),
        subject="GOD room review closure artifact",
    )
    if artifact is None:
        return {
            **base,
            "artifact_summary": load_error,
        }
    schema_version = _text(artifact.get("schema_version"))
    proof_level = _text(artifact.get("proof_level"))
    server_truth_status = _text(artifact.get("server_truth_status"))
    forbidden_claims = _string_list(artifact.get("forbidden_claims"))
    required_forbidden = {"ready_to_merge", "pr_merged", "github_review_truth"}
    if schema_version != "xmuse.god_room_lane_review_closure.v1":
        return {
            **base,
            "artifact_summary": "GOD room review closure schema is unsupported.",
        }
    if proof_level != "contract_proof":
        return {
            **base,
            "artifact_summary": "GOD room review closure must remain contract_proof.",
        }
    if server_truth_status != "not_server_truth":
        return {
            **base,
            "artifact_summary": "GOD room review closure overclaims server truth.",
        }
    if not required_forbidden.issubset(set(forbidden_claims)):
        return {
            **base,
            "artifact_summary": "GOD room review closure missing forbidden claims.",
        }
    source_refs = _review_closure_source_refs(artifact)
    return {
        **base,
        "artifact_gate_ready": True,
        "artifact_summary": "GOD room review closure can seed MemoryOS source refs.",
        "source_refs": source_refs,
        "source_ref_count": len(source_refs),
    }


def _review_closure_source_refs(artifact: Mapping[str, Any]) -> list[str]:
    terminal_verdict = artifact.get("terminal_review_verdict")
    verdict_refs = (
        _string_list(terminal_verdict.get("evidence_refs"))
        if isinstance(terminal_verdict, dict)
        else []
    )
    graph_id = _text(artifact.get("graph_id"))
    failed_lane_id = _text(artifact.get("failed_lane_id"))
    terminal_lane_id = _text(artifact.get("terminal_lane_id"))
    synthetic_ref = (
        f"god-room-review-closure:{graph_id}:{failed_lane_id}:{terminal_lane_id}"
        if graph_id and failed_lane_id and terminal_lane_id
        else None
    )
    return _ordered_unique(
        [
            synthetic_ref,
            f"lane:{failed_lane_id}" if failed_lane_id else None,
            f"lane:{terminal_lane_id}" if terminal_lane_id else None,
            _text(artifact.get("patch_forward_artifact")),
            _text(artifact.get("patch_lane_review_intake_artifact")),
            _text(artifact.get("patch_lane_review_verdict_artifact")),
            *_string_list(artifact.get("candidate_refs")),
            *_string_list(artifact.get("cited_candidate_refs")),
            *verdict_refs,
        ]
    )


def _memoryos_runtime_closure_candidate(
    env: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    artifact_path = _text(payload.get("god_room_runtime_closure")) or _text(
        env.get(_GOD_ROOM_RUNTIME_CLOSURE_ARTIFACT_ENV)
    )
    base = {
        "artifact_configured": artifact_path is not None,
        "artifact_path": artifact_path,
        "artifact_gate_ready": False,
        "artifact_summary": None,
        "source_refs": [],
        "source_ref_count": 0,
    }
    if artifact_path is None:
        return base
    artifact, load_error = _json_file(
        Path(artifact_path),
        subject="GOD room runtime closure evidence",
    )
    if artifact is None:
        return {
            **base,
            "artifact_summary": load_error,
        }
    schema_version = _text(artifact.get("schema_version"))
    action = _text(artifact.get("action"))
    proof_level = _text(artifact.get("proof_level"))
    status = _text(artifact.get("status"))
    source_authority = _text(artifact.get("source_authority"))
    source_refs = _string_list(artifact.get("source_refs"))
    if schema_version != "xmuse.production_evidence.v1":
        return {
            **base,
            "artifact_summary": "GOD room runtime closure evidence schema is unsupported.",
        }
    if action != "god_room_runtime_closure_indexed":
        return {
            **base,
            "artifact_summary": "GOD room runtime closure evidence action is unsupported.",
        }
    if source_authority != "god_room_runtime_closure_contract":
        return {
            **base,
            "artifact_summary": (
                "GOD room runtime closure evidence source authority is unsupported."
            ),
        }
    if proof_level not in {"contract_proof", "manual_gap"}:
        return {
            **base,
            "artifact_summary": "GOD room runtime closure evidence overclaims proof level.",
        }
    if status not in {"ok", "manual_gap"}:
        return {
            **base,
            "artifact_summary": "GOD room runtime closure evidence status is unsupported.",
        }
    if not source_refs:
        return {
            **base,
            "artifact_summary": "GOD room runtime closure evidence has no source refs.",
        }
    return {
        **base,
        "artifact_gate_ready": True,
        "artifact_summary": (
            "GOD room runtime closure evidence can seed MemoryOS source refs; "
            f"closure status is {status}."
        ),
        "source_refs": source_refs,
        "source_ref_count": len(source_refs),
    }


def _memoryos_candidate_guidance(
    payload: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any],
    review_closure: Mapping[str, Any],
    runtime_closure: Mapping[str, Any],
) -> dict[str, Any]:
    payload_hints = {
        key: text
        for key in _MEMORYOS_PAYLOAD_HINT_KEYS
        if (text := _text(payload.get(key))) is not None
    }
    source_refs = _ordered_unique(
        [
            *_string_list(payload.get("source_refs")),
            *_string_list(review_closure.get("source_refs")),
            *_string_list(runtime_closure.get("source_refs")),
        ]
    )
    if source_refs:
        payload_hints["source_refs"] = source_refs
    source_authority = [
        "redacted_environment_presence",
        "operator_release_candidate_payload",
    ]
    artifact_path = _text(artifact.get("artifact_path"))
    if artifact_path is not None:
        source_authority.extend(
            [
                "memoryos_live_trace_artifact",
                "memoryos_live_release_gate",
            ]
        )
    if review_closure.get("artifact_gate_ready") is True:
        source_authority.append("god_room_review_closure_artifact")
    if runtime_closure.get("artifact_gate_ready") is True:
        source_authority.append("god_room_runtime_closure_evidence")
    guidance: dict[str, Any] = {
        "proof_boundary": "candidate_report_is_not_live_memoryos_proof",
        "required_artifact_schema": "xmuse.memoryos_lite_trace.v1",
        "required_proof_level": "live_service_proof",
        "source_authority": source_authority,
        "next_action": _MEMORYOS_NEXT_ACTION,
        "suggested_operator_action": {
            "action": "attempt_release_evidence",
            "kind": "live_memoryos",
            "required_payload_keys": list(_MEMORYOS_REQUIRED_PAYLOAD),
            "payload_hints": payload_hints,
        },
    }
    if artifact_path is not None:
        guidance["suggested_existing_artifact_action"] = {
            "action": "capture_release_evidence_pack",
            "kind": "live_memoryos",
            "payload_hints": {"memoryos_live_trace": artifact_path},
        }
    return guidance


def _github_candidates(*, payload: Mapping[str, Any]) -> dict[str, Any]:
    repo = _text(payload.get("repo"))
    pull_request_number = _positive_int(
        payload.get("pull_request_number")
        or payload.get("pull_request")
        or payload.get("pr")
    )
    missing_payload_keys = []
    if repo is None:
        missing_payload_keys.append("repo")
    if pull_request_number is None:
        missing_payload_keys.append("pull_request_number")
    export_ready = not missing_payload_keys
    return {
        "target_configured": export_ready,
        "export_ready": export_ready,
        "repo": repo,
        "pull_request_number": pull_request_number,
        "missing_payload_keys": missing_payload_keys,
        "blockers": [] if export_ready else ["github_server_truth_target_missing"],
        "can_emit_pr_merged": False,
        **_github_candidate_guidance(
            payload,
            repo=repo,
            pull_request_number=pull_request_number,
        ),
    }


def _github_candidate_guidance(
    payload: Mapping[str, Any],
    *,
    repo: str | None,
    pull_request_number: int | None,
) -> dict[str, Any]:
    payload_hints: dict[str, Any] = {}
    if repo is not None:
        payload_hints["repo"] = repo
    if pull_request_number is not None:
        payload_hints["pull_request_number"] = pull_request_number
    if (expected_head := _text(payload.get("expected_head_sha"))) is not None:
        payload_hints["expected_head_sha"] = expected_head
    if (base_branch := _text(payload.get("base_branch"))) is not None:
        payload_hints["base_branch"] = base_branch
    if required_checks := _string_list(payload.get("required_checks")):
        payload_hints["required_checks"] = required_checks
    return {
        "proof_boundary": "candidate_report_is_not_github_server_truth_proof",
        "required_gate_kind": "github_server_truth",
        "required_proof_level": "server_side_enforcement_proof",
        "source_authority": [
            "operator_release_candidate_payload",
            "github_server_truth_export_action",
        ],
        "next_action": _GITHUB_NEXT_ACTION,
        "suggested_operator_action": {
            "action": "attempt_release_evidence",
            "kind": "github_server_truth",
            "required_payload_keys": ["repo", "pull_request_number"],
            "payload_hints": payload_hints,
        },
    }


def _session_records(registry_path: Path) -> list[GodSessionRecord]:
    if not registry_path.exists():
        return []
    return GodSessionRegistry(registry_path).list()


def _session_index(
    session_records: list[GodSessionRecord],
) -> dict[tuple[str, str], GodSessionRecord]:
    sessions: dict[tuple[str, str], GodSessionRecord] = {}
    for session in session_records:
        if session.conversation_id and session.participant_id:
            sessions[(session.conversation_id, session.participant_id)] = session
    return sessions


def _god_cli_registry(root: Path) -> GodCliRegistry:
    registrations = GodCliRegistrationStore(
        root / "god_cli_registrations.json"
    ).list_registrations()
    return build_default_god_cli_registry(extra_registrations=registrations)


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _conversation_rows(
    conn: sqlite3.Connection,
    *,
    conversation_id: str | None,
) -> list[sqlite3.Row]:
    if conversation_id:
        return conn.execute(
            "select id, title, created_at from conversations where id = ?",
            (conversation_id,),
        ).fetchall()
    return conn.execute(
        "select id, title, created_at from conversations order by created_at desc",
    ).fetchall()


def _speech_message(row: sqlite3.Row) -> dict[str, str] | None:
    if row["role"] != "assistant":
        return None
    envelope_type = _text(row["envelope_type"])
    envelope = _json_object(row["envelope_json"])
    if envelope_type != "god_speech_act" and envelope.get("type") != "god_speech_act":
        return None
    payload = envelope.get("message") or envelope.get("god_speech_act")
    if not isinstance(payload, dict):
        return None
    return {
        "message_id": _text(payload.get("message_id")) or row["id"],
        "participant_id": row["author"],
        "god_id": _text(payload.get("sender_god")) or row["author"],
    }


def _trace_candidate(
    row: dict[str, Any],
    *,
    sessions: Mapping[tuple[str, str], GodSessionRecord],
) -> dict[str, Any]:
    conversation_id = str(row.get("conversation_id") or "")
    participant_id = _text(row.get("participant_id"))
    session = sessions.get((conversation_id, participant_id or ""))
    provider_session_id = _provider_session_id(session)
    return {
        "conversation_id": conversation_id,
        "inbox_item_id": str(row.get("inbox_item_id") or ""),
        "participant_id": participant_id,
        "target_role": _text(row.get("target_role")),
        "delivery_mode": str(row.get("delivery_mode") or ""),
        "degraded_reason": row.get("degraded_reason"),
        "provider_session_id": provider_session_id,
        "provider_session_id_missing": not bool(provider_session_id),
        "writeback_at": row.get("writeback_at"),
    }


def _suggest_fresh_resume(traces: list[dict[str, Any]]) -> tuple[str, str] | None:
    by_session: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trace in traces:
        key = (trace["conversation_id"], trace["provider_session_id"])
        by_session.setdefault(key, []).append(trace)
    for grouped in by_session.values():
        if len(grouped) < 2:
            continue
        grouped.sort(key=lambda item: item.get("writeback_at") or 0)
        return (
            str(grouped[0]["inbox_item_id"]),
            str(grouped[-1]["inbox_item_id"]),
        )
    return None


def _provider_gap(reason: str, *, trace_table_present: bool) -> dict[str, Any]:
    return {
        "trace_table_present": trace_table_present,
        "trace_count": 0,
        "traces": [],
        "export_ready": False,
        "suggested_fresh_inbox_item_id": None,
        "suggested_resume_inbox_item_id": None,
        "blockers": [reason],
        **_provider_candidate_guidance(conversation_id=None, suggested=None),
    }


def _provider_candidate_guidance(
    *,
    conversation_id: str | None,
    suggested: tuple[str, str] | None,
) -> dict[str, Any]:
    payload_hints: dict[str, str] = {}
    if conversation_id:
        payload_hints["conversation_id"] = conversation_id
    if suggested is not None:
        payload_hints["fresh_inbox_item_id"] = suggested[0]
        payload_hints["resume_inbox_item_id"] = suggested[1]
    return {
        "proof_boundary": "candidate_report_is_not_release_proof",
        "required_artifact_schema": "xmuse.real_provider_runtime.v1",
        "required_proof_level": "real_provider_proof",
        "source_authority": [
            "chat_store.peer_turn_latency_traces",
            "god_session_registry.provider_session_bindings",
        ],
        "next_action": _PROVIDER_NEXT_ACTION,
        "suggested_operator_action": {
            "action": "attempt_release_evidence",
            "kind": "real_provider_runtime",
            "required_payload_keys": [
                "conversation_id",
                "runtime_backend",
                "transport",
            ],
            "payload_hints": payload_hints,
        },
    }


def _provider_session_id(session: GodSessionRecord | None) -> str:
    if session is None or not session.provider_session_id:
        return ""
    return session.provider_session_id


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _json_file(path: Path, *, subject: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"{subject} does not exist: {path}."
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{subject} could not be read: {exc}."
    if not isinstance(loaded, dict):
        return None, f"{subject} must be a JSON object."
    return loaded, None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _ordered_unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["build_release_evidence_candidate_report"]
