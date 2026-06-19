#!/usr/bin/env python3
"""FastAPI MCP-over-HTTP server for xmuse control-plane operations."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from xmuse_core.platform import mcp_responses, mcp_search
from xmuse_core.platform.projection.allowlist import (
    normalize_mutation_audit,
    stamp_mutation_audit,
)
from xmuse_core.platform.projection.syncer import (
    DuplicateLaneError,
    LaneProjectionSyncer,
    ProjectionRevisionConflict,
)
from xmuse_core.platform.read_contracts import (
    READ_CONTRACT_TOOL_SCHEMAS,
    build_tool_inventory,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)
SERVER_NAME = "xmuse-mcp"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

_content_json = mcp_responses.content_json
_error_content = mcp_responses.error_content
_json_rpc_response = mcp_responses.json_rpc_response
_json_rpc_error = mcp_responses.json_rpc_error
_text_for_search = mcp_search.text_for_search
_query_terms = mcp_search.query_terms


def _read_json_object(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} JSON root must be an object")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _audit_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "reason": {"type": "string"},
            "request_id": {"type": "string"},
        },
        "required": ["actor", "reason", "request_id"],
        "additionalProperties": False,
    }


def _expected_revision_guard(guard: Any, *, tool_name: str) -> int:
    if not isinstance(guard, dict):
        raise ValueError(f"{tool_name} requires guard.expected_revision")
    expected_revision = guard.get("expected_revision")
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise ValueError(f"{tool_name} guard.expected_revision must be a non-negative integer")
    return expected_revision


def _abort_lane_guards(guard: Any) -> tuple[str, str | None]:
    if not isinstance(guard, dict):
        raise ValueError("abort_lane requires guard.lane_status")
    lane_status = guard.get("lane_status")
    if not isinstance(lane_status, str) or not lane_status.strip():
        raise ValueError("abort_lane guard.lane_status is required")
    session_status = guard.get("session_status")
    if session_status is not None and (
        not isinstance(session_status, str) or not session_status.strip()
    ):
        raise ValueError("abort_lane guard.session_status must be a non-empty string")
    return lane_status.strip(), session_status.strip() if isinstance(session_status, str) else None


def _find_lane_entry(data: dict[str, Any], feature_id: str) -> dict[str, Any]:
    lanes = data.get("lanes", [])
    if not isinstance(lanes, list):
        raise ValueError("feature_lanes.json lanes must be a list")
    for lane in lanes:
        if isinstance(lane, dict) and lane.get("feature_id") == feature_id:
            return lane
    raise KeyError(f"lane not found: {feature_id}")


class XmuseOperations:
    def __init__(self, xmuse_root: str | Path = DEFAULT_XMUSE_ROOT) -> None:
        self.xmuse_root = Path(xmuse_root)
        self.lanes_path = self.xmuse_root / "feature_lanes.json"
        self.sessions_path = self.xmuse_root / "active_sessions.json"
        self.error_knowledge_path = self.xmuse_root / "error_knowledge.json"
        self.logs_dir = self.xmuse_root / "logs"

    def list_lanes(self) -> dict[str, Any]:
        try:
            return LaneProjectionSyncer(self.lanes_path).read()
        except FileNotFoundError:
            return {"lanes": []}

    def enqueue_lane(
        self,
        *,
        feature_id: str,
        prompt: str,
        capabilities: list[str],
        audit: dict[str, Any],
        guard: dict[str, Any],
    ) -> dict[str, Any]:
        feature_id = feature_id.strip()
        prompt = prompt.strip()
        if not feature_id:
            raise ValueError("feature_id is required")
        if not prompt:
            raise ValueError("prompt is required")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise ValueError("capabilities must be a non-empty string list")
        audit = normalize_mutation_audit(audit, tool_name="enqueue_lane")
        expected_revision = _expected_revision_guard(
            guard,
            tool_name="enqueue_lane",
        )

        lane = {
            "feature_id": feature_id,
            "task_type": "execute",
            "prompt": prompt,
            "capabilities": [item.strip() for item in capabilities],
            "status": "pending",
        }
        lane = stamp_mutation_audit(lane, audit=audit, tool_name="enqueue_lane")
        try:
            created = LaneProjectionSyncer(self.lanes_path).append_lane(
                lane,
                expected_revision=expected_revision,
            )
        except DuplicateLaneError as exc:
            raise ValueError(str(exc)) from exc
        except ProjectionRevisionConflict as exc:
            raise ValueError(str(exc)) from exc
        return {key: value for key, value in created.items() if key != "projection_revision"}

    def get_status(self, *, feature_id: str) -> dict[str, Any]:
        feature_id = feature_id.strip()
        if not feature_id:
            raise ValueError("feature_id is required")
        lane = self._find_lane(feature_id)
        active_session = self._find_active_session(feature_id)
        return {
            "feature_id": feature_id,
            "lane": lane or {"feature_id": feature_id, "status": "unknown"},
            "active_session": active_session,
        }

    def abort_lane(
        self,
        *,
        feature_id: str,
        audit: dict[str, Any],
        guard: dict[str, Any],
    ) -> dict[str, Any]:
        feature_id = feature_id.strip()
        if not feature_id:
            raise ValueError("feature_id is required")
        audit = normalize_mutation_audit(audit, tool_name="abort_lane")
        lane_status_guard, session_status_guard = _abort_lane_guards(guard)

        sessions = _read_json_object(self.sessions_path, {})
        active_session = self._find_active_session(feature_id, sessions=sessions)
        if active_session is not None and session_status_guard is None:
            raise ValueError(
                "abort_lane requires guard.session_status when an active session exists"
            )
        if (
            active_session is not None
            and session_status_guard is not None
            and active_session.get("status") != session_status_guard
        ):
            raise ValueError(
                "abort_lane guard.session_status mismatch: "
                f"expected {session_status_guard}"
            )

        lane = self._mark_lane_abort_requested(
            feature_id,
            lane_status=lane_status_guard,
            audit=audit,
        )
        if active_session is not None:
            active_session["status"] = "abort_requested"
            active_session["abort_requested"] = True
            self._replace_active_session(feature_id, active_session, sessions)
            _atomic_write_json(self.sessions_path, sessions)

        return {
            "feature_id": feature_id,
            "aborted": lane is not None or active_session is not None,
            "lane": lane or {"feature_id": feature_id, "status": "unknown"},
            "active_session": active_session,
        }

    def get_error_knowledge(self, *, query: str, top_k: int = 3) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("query is required")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        entries = self._error_entries()
        terms = _query_terms(query)
        matches: list[dict[str, Any]] = []
        for entry in entries:
            haystack = _text_for_search(entry).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                matches.append({"score": score, "entry": entry})
        matches.sort(
            key=lambda item: (
                -int(item["score"]),
                str(item["entry"].get("entry_id") or item["entry"].get("id") or ""),
            )
        )
        return {"query": query, "matches": matches[:top_k]}

    def get_logs(self, *, feature_id: str, max_bytes: int = 200_000) -> dict[str, Any]:
        feature_id = feature_id.strip()
        if not feature_id:
            raise ValueError("feature_id is required")
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")

        logs: list[dict[str, str]] = []
        combined_parts: list[str] = []
        total_bytes = 0
        if self.logs_dir.exists():
            for path in sorted(self.logs_dir.glob(f"*{feature_id}*")):
                if not path.is_file():
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
                remaining = max_bytes - total_bytes
                if remaining <= 0:
                    break
                truncated = content[:remaining]
                total_bytes += len(truncated.encode("utf-8"))
                rel_path = path.relative_to(self.xmuse_root).as_posix()
                logs.append({"path": rel_path, "content": truncated})
                combined_parts.append(f"== {rel_path} ==\n{truncated}")
        return {
            "feature_id": feature_id,
            "logs": logs,
            "combined": "\n".join(combined_parts),
            "truncated": total_bytes >= max_bytes,
        }

    def _find_lane(self, feature_id: str) -> dict[str, Any] | None:
        for lane in self.list_lanes().get("lanes", []):
            if isinstance(lane, dict) and lane.get("feature_id") == feature_id:
                return dict(lane)
        return None

    def _mark_lane_abort_requested(
        self,
        feature_id: str,
        *,
        lane_status: str,
        audit: dict[str, str],
    ) -> dict[str, Any] | None:
        updated: dict[str, Any] | None = None

        def mutate(data: dict[str, Any]) -> None:
            nonlocal updated
            lane = _find_lane_entry(data, feature_id)
            if lane.get("status") != lane_status:
                raise ValueError(
                    "abort_lane guard.lane_status mismatch: "
                    f"expected {lane_status}"
                )
            lane["abort_requested"] = True
            stamp_mutation_audit(lane, audit=audit, tool_name="abort_lane")
            updated = dict(lane)

        try:
            LaneProjectionSyncer(self.lanes_path).update(mutate)
        except KeyError:
            return None
        return updated

    def _find_active_session(
        self,
        feature_id: str,
        *,
        sessions: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = sessions if sessions is not None else _read_json_object(self.sessions_path, {})
        raw_sessions = payload.get("sessions", payload)
        if isinstance(raw_sessions, dict):
            session = raw_sessions.get(feature_id)
            if isinstance(session, dict):
                return dict(session)
            for item in raw_sessions.values():
                if isinstance(item, dict) and item.get("feature_id") == feature_id:
                    return dict(item)
        if isinstance(raw_sessions, list):
            for item in raw_sessions:
                if isinstance(item, dict) and item.get("feature_id") == feature_id:
                    return dict(item)
        return None

    def _replace_active_session(
        self,
        feature_id: str,
        session: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        raw_sessions = payload.setdefault("sessions", {})
        if isinstance(raw_sessions, dict):
            if feature_id in raw_sessions:
                raw_sessions[feature_id] = session
                return
            for key, item in raw_sessions.items():
                if isinstance(item, dict) and item.get("feature_id") == feature_id:
                    raw_sessions[key] = session
                    return
            raw_sessions[feature_id] = session
            return
        if isinstance(raw_sessions, list):
            for index, item in enumerate(raw_sessions):
                if isinstance(item, dict) and item.get("feature_id") == feature_id:
                    raw_sessions[index] = {"feature_id": feature_id, **session}
                    return
            raw_sessions.append({"feature_id": feature_id, **session})

    def _error_entries(self) -> list[dict[str, Any]]:
        payload = _read_json_object(self.error_knowledge_path, {})
        entries = payload.get("entries", payload.get("errors", []))
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            entries = []
        aggregate_entries = [entry for entry in entries if isinstance(entry, dict)]
        if aggregate_entries:
            return aggregate_entries

        discovered: list[dict[str, Any]] = []
        knowledge_dir = self.xmuse_root / "knowledge"
        for path in sorted(knowledge_dir.glob("error_records/**/*.json")):
            try:
                entry = _read_json_object(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            entry.setdefault("source_path", path.relative_to(self.xmuse_root).as_posix())
            discovered.append(entry)
        return discovered


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_lanes",
        "description": "Return current xmuse feature_lanes.json content.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "enqueue_lane",
        "description": "Append a queued xmuse lane to feature_lanes.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "feature_id": {"type": "string"},
                "prompt": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
                "audit": _audit_schema(),
                "guard": {
                    "type": "object",
                    "properties": {"expected_revision": {"type": "integer", "minimum": 0}},
                    "required": ["expected_revision"],
                    "additionalProperties": False,
                },
            },
            "required": ["feature_id", "prompt", "capabilities", "audit", "guard"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_status",
        "description": "Return lane status and active session information.",
        "inputSchema": {
            "type": "object",
            "properties": {"feature_id": {"type": "string"}},
            "required": ["feature_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "abort_lane",
        "description": "Record an audited abort request without direct process control.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "feature_id": {"type": "string"},
                "audit": _audit_schema(),
                "guard": {
                    "type": "object",
                    "properties": {
                        "lane_status": {"type": "string"},
                        "session_status": {"type": "string"},
                    },
                    "required": ["lane_status"],
                    "additionalProperties": False,
                },
            },
            "required": ["feature_id", "audit", "guard"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_error_knowledge",
        "description": "Keyword-search xmuse error knowledge entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_logs",
        "description": "Return per-round execution logs matching a feature id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "feature_id": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 200000},
            },
            "required": ["feature_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_tool_inventory",
        "description": "Return an inventory of existing MCP tools grouped by family.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

# Platform God tools (used by Execution God and Review God agents)
PLATFORM_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_lane",
        "description": "Get full lane details by feature_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_gate_report",
        "description": "Get the most recent gate execution report for a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_diff",
        "description": "Get the git diff of a lane's worktree.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_knowledge",
        "description": "Search error_knowledge for relevant past failures.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_lane_status",
        "description": "Update lane status (drives the state machine).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lane_id": {"type": "string"},
                "status": {"type": "string"},
                "metadata": {"type": "object"},
                "audit": _audit_schema(),
                "guard": {
                    "type": "object",
                    "properties": {"current_status": {"type": "string"}},
                    "required": ["current_status"],
                    "additionalProperties": False,
                },
            },
            "required": ["lane_id", "status", "audit", "guard"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_takeover_decision",
        "description": "Apply a Review GOD takeover decision with audited evidence refs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision": {"type": "object"},
                "audit": _audit_schema(),
                "guard": {
                    "type": "object",
                    "properties": {
                        "lane_status": {"type": "string"},
                        "projection_revision": {"type": "integer", "minimum": 0},
                        "lease_id": {"type": "string"},
                        "lane_context_hash": {"type": "string"},
                        "evidence_bundle_hash": {"type": "string"},
                    },
                    "required": [
                        "lane_status",
                        "projection_revision",
                        "lease_id",
                        "lane_context_hash",
                        "evidence_bundle_hash",
                    ],
                    "additionalProperties": False,
                },
                "created_at": {"type": "string"},
            },
            "required": ["decision", "audit", "guard"],
            "additionalProperties": False,
        },
    },
]

CHAT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "chat_list_conversations",
        "description": (
            "List xmuse chat conversations with compact participant, inbox, and card summaries."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "chat_create_conversation",
        "description": "Create an xmuse chat conversation with provider-compatible peer fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "participants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "display_name": {"type": "string"},
                            "provider_id": {"type": "string"},
                            "profile_id": {"type": "string"},
                            "cli_kind": {"type": "string", "enum": ["codex"]},
                            "model": {"type": "string"},
                            "role_template_id": {"type": "string"},
                        },
                        "required": ["role"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_list_participants",
        "description": (
            "List provider-compatible participants scoped to one xmuse chat "
            "conversation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"conversation_id": {"type": "string"}},
            "required": ["conversation_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_post_message",
        "description": "Post a GOD chat message to an xmuse conversation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "client_request_id": {"type": "string"},
                "content": {"type": "string"},
                "envelope": {"type": "object"},
                "reply_to_inbox_item_id": {"type": "string"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "client_request_id",
                "content",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_read_inbox",
        "description": "Read unread xmuse peer-chat inbox items for a GOD participant.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "limit": {"type": "integer"},
                "include_claimed": {"type": "boolean"},
            },
            "required": ["conversation_id", "participant_id", "god_session_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_mark_inbox",
        "description": "Mark one xmuse peer-chat inbox item read or failed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "inbox_item_id": {"type": "string"},
                "status": {"type": "string", "enum": ["read", "failed"]},
                "reason": {"type": "string"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "inbox_item_id",
                "status",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_mention",
        "description": (
            "Post a GOD message and enqueue an inbox item for a mentioned GOD participant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "client_request_id": {"type": "string"},
                "target_address": {"type": "string"},
                "content": {"type": "string"},
                "envelope": {"type": "object"},
                "reply_to_inbox_item_id": {"type": "string"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "client_request_id",
                "target_address",
                "content",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_emit_proposal",
        "description": "Create an xmuse proposal row and proposal chat card.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "client_request_id": {"type": "string"},
                "summary": {"type": "string"},
                "lanes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "feature_id": {"type": "string"},
                            "prompt": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                            "capabilities": {"type": "array", "items": {"type": "string"}},
                            "feature_group": {"type": "string"},
                            "review_runtime": {"type": "string"},
                        },
                        "required": ["feature_id", "prompt", "depends_on", "capabilities"],
                        "additionalProperties": True,
                    },
                },
                "references": {"type": "array", "items": {"type": "string"}},
                "resolution_content": {"type": "object"},
                "reply_to_inbox_item_id": {"type": "string"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "client_request_id",
                "summary",
                "lanes",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_inspect_conversation",
        "description": (
            "Inspect an xmuse chat conversation with full summary including "
            "participants, inbox, recent activity, blueprint, feature plan, and graph set."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"conversation_id": {"type": "string"}},
            "required": ["conversation_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_create_collaboration_request",
        "description": (
            "Create a bounded structured GOD collaboration request with response aggregation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "client_request_id": {"type": "string"},
                "goal": {"type": "string"},
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                },
                "callback_target": {"type": "string"},
                "question": {"type": "string"},
                "context_refs": {"type": "array", "items": {"type": "string"}},
                "idempotency_key": {"type": "string"},
                "timeout_s": {"type": "integer"},
                "orchestration_mode": {
                    "type": "string",
                    "enum": ["peer_consensus", "leader_assisted"],
                },
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "client_request_id",
                "goal",
                "targets",
                "callback_target",
                "question",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_record_collaboration_response",
        "description": (
            "Record this GOD participant's response to a collaboration request. "
            "For executable dispatch, execute must send content shaped exactly "
            'like {"type":"execute_feasibility_verdict","status":"executable",'
            '"summary":"<why dispatch is safe>","evidence_refs":["<ref>"]}; '
            "looser fields such as verdict=feasible do not satisfy approval gates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "run_id": {"type": "string"},
                "content": {"type": "string"},
                "status": {"type": "string", "enum": ["received", "timeout", "failed"]},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "run_id",
                "content",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_raise_collaboration_blocker",
        "description": "Raise a structured blocker or veto against a collaboration run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "run_id": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "blocker", "veto"],
                },
                "reason": {"type": "string"},
                "affected_ref": {"type": "string"},
                "suggested_fix": {"type": "string"},
                "blocks_dispatch": {"type": "boolean"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "run_id",
                "severity",
                "reason",
                "affected_ref",
                "suggested_fix",
                "blocks_dispatch",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_resolve_collaboration_blocker",
        "description": "Resolve a structured blocker or veto with traceable evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "blocker_id": {"type": "string"},
                "resolution_evidence": {"type": "string"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "blocker_id",
                "resolution_evidence",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_evaluate_dispatch_gate",
        "description": (
            "Evaluate whether a structured collaboration run may dispatch to a real provider."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "run_id": {"type": "string"},
                "proposal_ref": {"type": "string"},
                "artifact_ref": {"type": "string"},
                "execute_confirmed": {"type": "boolean"},
                "policy_allows_real_provider": {"type": "boolean"},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "run_id",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_emit_blueprint_proposal",
        "description": "Create a mission-blueprint proposal row and visible chat card.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "participant_id": {"type": "string"},
                "god_session_id": {"type": "string"},
                "client_request_id": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "revises_blueprint_ref": {"type": "string"},
                "references": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "conversation_id",
                "participant_id",
                "god_session_id",
                "client_request_id",
                "title",
                "body",
                "acceptance_criteria",
            ],
            "additionalProperties": False,
        },
    },
]


def _with_chat_mention_routing(
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if "message" not in result or "inbox_items" not in result:
        return result

    message = result.get("message")
    inbox_items = result.get("inbox_items")
    if not isinstance(message, dict) or not isinstance(inbox_items, list):
        return result

    mentions = message.get("mentions")
    normalized_mentions = mentions if isinstance(mentions, list) else []
    resolved_mentions: list[dict[str, Any]] = []
    for index, item in enumerate(inbox_items):
        if not isinstance(item, dict):
            continue
        normalized = item.get("target_address")
        if index < len(normalized_mentions) and isinstance(normalized_mentions[index], str):
            normalized = normalized_mentions[index]
        resolved_mentions.append(
            {
                "normalized": normalized,
                "conversation_id": item.get("conversation_id"),
                "target_participant_id": item.get("target_participant_id"),
                "target_role": item.get("target_role"),
                "target_address": item.get("target_address"),
                "inbox_item_id": item.get("id"),
            }
        )

    return {
        **result,
        "mention_routing": {
            "requested_target": arguments.get("target_address"),
            "resolved_mentions": resolved_mentions,
        },
    }


def _tool_result(ops: XmuseOperations, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "list_lanes":
        return _content_json(ops.list_lanes())
    if name == "enqueue_lane":
        return _content_json(ops.enqueue_lane(**arguments))
    if name == "get_status":
        return _content_json(ops.get_status(**arguments))
    if name == "abort_lane":
        return _content_json(ops.abort_lane(**arguments))
    if name == "get_error_knowledge":
        return _content_json(ops.get_error_knowledge(**arguments))
    if name == "get_logs":
        return _content_json(ops.get_logs(**arguments))
    if name == "get_tool_inventory":
        return _content_json(
            build_tool_inventory(
                control_schemas=TOOL_SCHEMAS,
                platform_schemas=PLATFORM_TOOL_SCHEMAS,
                chat_schemas=CHAT_TOOL_SCHEMAS,
                contract_schemas=READ_CONTRACT_TOOL_SCHEMAS,
            )
        )
    # Platform God tools — delegate to McpToolHandler
    if name in (
        "get_lane",
        "get_gate_report",
        "get_diff",
        "query_knowledge",
        "read_lane_contract",
        "read_blueprint_contract",
        "read_feature_plan_contract",
        "read_review_contract",
        "read_health_contract",
        "read_graph_set_contract",
        "read_graph_set_summary",
        "read_evidence_refs",
        "read_review_verdict",
        "read_takeover_context",
        "read_run_health",
        "read_provider_inventory",
        "apply_takeover_decision",
        "update_lane_status",
    ):
        from xmuse_core.platform.mcp_tools import McpToolHandler
        from xmuse_core.platform.state_machine import LaneStateMachine
        sm = LaneStateMachine(ops.lanes_path)
        handler = McpToolHandler(state_machine=sm, xmuse_root=ops.xmuse_root)
        return _content_json(handler.call(name, arguments))
    if name.startswith("chat_"):
        from xmuse_core.chat.peer_service import PeerChatError, PeerChatService

        service = PeerChatService(ops.xmuse_root / "chat.db")
        registry_path = ops.xmuse_root / "god_sessions.json"
        try:
            result = service.call_mcp_tool(name, arguments, registry_path=registry_path)
        except PeerChatError as exc:
            return _content_json({"error": {"code": exc.code, "message": exc.message}})
        except (TypeError, ValueError) as exc:
            return _content_json({"error": {"code": "invalid_arguments", "message": str(exc)}})
        if name == "chat_mention":
            result = _with_chat_mention_routing(arguments, result)
        return _content_json(result)
    raise ValueError(f"unknown tool: {name}")


def _all_tool_schemas() -> list[dict[str, Any]]:
    return TOOL_SCHEMAS + PLATFORM_TOOL_SCHEMAS + READ_CONTRACT_TOOL_SCHEMAS + CHAT_TOOL_SCHEMAS


def _peer_chat_tool_schemas() -> list[dict[str, Any]]:
    structured_peer_tool_names = {
        "chat_create_collaboration_request",
        "chat_record_collaboration_response",
        "chat_raise_collaboration_blocker",
        "chat_resolve_collaboration_blocker",
        "chat_evaluate_dispatch_gate",
        "chat_emit_proposal",
        "chat_inspect_conversation",
    }
    schemas: list[dict[str, Any]] = []
    for schema in CHAT_TOOL_SCHEMAS:
        name = schema.get("name")
        if name == "chat_read_inbox":
            schemas.append(schema)
        elif name == "chat_post_message":
            narrowed = json.loads(json.dumps(schema))
            required = list(narrowed["inputSchema"].get("required", []))
            if "reply_to_inbox_item_id" not in required:
                required.append("reply_to_inbox_item_id")
            narrowed["inputSchema"]["required"] = required
            narrowed["description"] = (
                "Post a GOD chat reply to an xmuse peer-chat inbox item; "
                "reply_to_inbox_item_id is required on this peer writeback endpoint."
            )
            schemas.append(narrowed)
        elif name == "chat_mention":
            narrowed = json.loads(json.dumps(schema))
            narrowed["description"] = (
                "Explicitly hand off work to another GOD participant from a peer "
                "chat turn. Pass reply_to_inbox_item_id=xmuse_context.inbox_item.id "
                "when the handoff is the durable response to the current inbox item; "
                "natural-language @mentions in chat_post_message do not enqueue "
                "peer work."
            )
            schemas.append(narrowed)
        elif name in structured_peer_tool_names:
            narrowed = json.loads(json.dumps(schema))
            if name == "chat_emit_proposal":
                narrowed["description"] = (
                    "Submit an actionable lane_graph proposal after peer discussion "
                    "has produced executable work. This creates an approval card; "
                    "it does not approve or dispatch the proposal by itself."
                )
            elif name == "chat_create_collaboration_request":
                narrowed["description"] = (
                    "Create a bounded peer collaboration run before asking review or "
                    "execute for dispatchable work."
                )
            elif name == "chat_record_collaboration_response":
                narrowed["description"] = (
                    "Record this GOD's structured response to a collaboration run; "
                    "execute must use the approval-gate "
                    "execute_feasibility_verdict JSON object before emitting a "
                    "dispatchable proposal: "
                    '{"type":"execute_feasibility_verdict","status":"executable",'
                    '"summary":"<why dispatch is safe>","evidence_refs":["<ref>"]}. '
                    "Looser fields such as verdict=feasible do not satisfy dispatch."
                )
            schemas.append(narrowed)
    return schemas


async def _handle_json_rpc(
    payload: dict[str, Any],
    ops: XmuseOperations,
    *,
    tool_schemas: list[dict[str, Any]] | None = None,
) -> Response:
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    allowed_tool_names = (
        {schema["name"] for schema in tool_schemas}
        if tool_schemas is not None
        else None
    )
    scoped_tool_schemas = (
        {schema["name"]: schema for schema in tool_schemas}
        if tool_schemas is not None
        else {}
    )
    try:
        if method == "initialize":
            requested_version = None
            if isinstance(params, dict):
                value = params.get("protocolVersion")
                requested_version = value if isinstance(value, str) else None
            protocol_version = (
                requested_version
                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                else DEFAULT_PROTOCOL_VERSION
            )
            result = {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": "xmuse MCP",
                    "version": SERVER_VERSION,
                },
            }
            return JSONResponse(_json_rpc_response(request_id, result))
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list":
            return JSONResponse(
                _json_rpc_response(
                    request_id,
                    {"tools": tool_schemas if tool_schemas is not None else _all_tool_schemas()},
                )
            )
        if method == "tools/call":
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str):
                raise ValueError("tool name is required")
            if allowed_tool_names is not None and name not in allowed_tool_names:
                raise ValueError(f"tool is not exposed on this MCP endpoint: {name}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
            if name in scoped_tool_schemas:
                _validate_required_tool_arguments(scoped_tool_schemas[name], arguments)
            return JSONResponse(_json_rpc_response(request_id, _tool_result(ops, name, arguments)))
        return JSONResponse(_json_rpc_error(request_id, -32601, f"method not found: {method}"))
    except Exception as exc:
        return JSONResponse(_json_rpc_response(request_id, _error_content(str(exc))))


def _validate_required_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    input_schema = schema.get("inputSchema")
    if not isinstance(input_schema, dict):
        return
    required = input_schema.get("required", [])
    if not isinstance(required, list):
        return
    missing = [
        name
        for name in required
        if isinstance(name, str) and name not in arguments
    ]
    if missing:
        raise ValueError(
            f"{schema.get('name', 'tool')} missing required arguments: "
            + ", ".join(sorted(missing))
        )


def create_app(xmuse_root: str | Path = DEFAULT_XMUSE_ROOT) -> FastAPI:
    ops = XmuseOperations(xmuse_root)
    app = FastAPI(title="xmuse MCP Server", version=SERVER_VERSION)
    app.state.xmuse_ops = ops

    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": SERVER_NAME,
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "endpoints": {
                "mcp": "/mcp",
                "mcp_chat": "/mcp/chat",
                "sse": "/sse",
            },
            "state_files": {
                "chat_db": {
                    "path": str(ops.xmuse_root / "chat.db"),
                    "exists": (ops.xmuse_root / "chat.db").exists(),
                },
                "god_sessions": {
                    "path": str(ops.xmuse_root / "god_sessions.json"),
                    "exists": (ops.xmuse_root / "god_sessions.json").exists(),
                },
            },
        }

    @app.get("/sse")
    def sse() -> StreamingResponse:
        session_id = uuid.uuid4().hex

        def events():
            yield f"event: endpoint\ndata: /messages?session_id={session_id}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/sse")
    async def sse_json_rpc(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(_json_rpc_error(None, -32600, "request must be an object"))
        return await _handle_json_rpc(payload, ops)

    @app.post("/messages")
    async def messages(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(_json_rpc_error(None, -32600, "request must be an object"))
        return await _handle_json_rpc(payload, ops)

    @app.post("/mcp")
    async def mcp(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(_json_rpc_error(None, -32600, "request must be an object"))
        return await _handle_json_rpc(payload, ops)

    @app.post("/mcp/chat")
    async def mcp_chat(request: Request) -> Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(_json_rpc_error(None, -32600, "request must be an object"))
        return await _handle_json_rpc(payload, ops, tool_schemas=_peer_chat_tool_schemas())

    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8100)


if __name__ == "__main__":
    main()
