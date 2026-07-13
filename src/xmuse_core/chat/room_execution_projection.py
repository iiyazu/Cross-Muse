"""Safe, bounded read models for Room exact-patch execution.

The execution ledger remains authoritative.  These projections deliberately
whitelist fields so workspace guards, controller identity, paths, raw gate logs,
and process details cannot cross the browser boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from xmuse_core.chat.room_execution_profiles import (
    RoomExecutionProfileError,
    get_execution_gate_profile,
)

ROOM_EXECUTION_LIST_SCHEMA = "room_execution_list_projection/v1"
ROOM_EXECUTION_CANDIDATE_SCHEMA = "room_execution_candidate_projection/v1"
ROOM_EXECUTION_PROOF_BOUNDARY = "execution_projection_not_room_or_workspace_authority"

_ACTIONABLE_CANDIDATE_STATES = {"open"}
_CANCELLABLE_RUN_STATES = {
    "requested",
    "preparing",
    "staging",
    "verifying",
    "ready_to_promote",
}
_TERMINAL_RUN_STATES = {"succeeded", "failed", "blocked", "cancelled"}
_MAX_DIFF_BYTES = 200 * 1024
_SAFE_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,199}\Z")


class RoomExecutionReadStore(Protocol):
    def get_policy(self, conversation_id: str) -> Mapping[str, Any] | None: ...

    def get_candidate(
        self, candidate_id: str, *, include_patch: bool = False
    ) -> Mapping[str, Any] | None: ...

    def list_conversation_candidates(self, conversation_id: str, *, limit: int = 50) -> object: ...

    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...

    def list_conversation_runs(self, conversation_id: str, *, limit: int = 50) -> object: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: object, *, maximum: int = 2_000) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        return None
    return cleaned


def _integer(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return minimum
    return value


def _boolean(value: object) -> bool:
    return value is True


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: object, *keys: str) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                return [item for item in nested if isinstance(item, Mapping)]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _strings(value: object, *, maximum: int = 32) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    for item in value[:maximum]:
        cleaned = _text(item, maximum=500)
        if cleaned is not None:
            result.append(cleaned)
    return result


def _id(source: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text(source.get(key), maximum=200)
        if value is not None:
            return value
    return None


def _allowed_files(source: Mapping[str, Any]) -> list[str]:
    value = source.get("allowed_files")
    if value is None:
        value = source.get("allowed_files_json")
    return _strings(value, maximum=32)


def _gate_profile_payload(
    value: object, *, include_readiness: bool = False
) -> dict[str, Any] | None:
    """Whitelist one fixed profile reference without projecting private digests."""

    source = _mapping(value)
    profile_id = _text(source.get("profile_id"), maximum=100)
    if profile_id is None:
        return None
    try:
        profile = get_execution_gate_profile(profile_id)
    except RoomExecutionProfileError:
        return None
    if source.get("schema_version") != profile.schema_version:
        return None
    if source.get("revision") != profile.revision:
        return None
    raw_gate_ids = source.get("gate_ids")
    if not isinstance(raw_gate_ids, Sequence) or isinstance(raw_gate_ids, (str, bytes)):
        return None
    gate_ids = tuple(raw_gate_ids)
    if (
        not gate_ids
        or gate_ids[0] != "patch_diff_check"
        or any(not isinstance(value, str) for value in gate_ids)
        or len(set(gate_ids)) != len(gate_ids)
        or gate_ids != tuple(value for value in profile.gate_ids if value in set(gate_ids))
    ):
        return None
    payload = {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "revision": profile.revision,
        "gate_ids": list(gate_ids),
    }
    if not include_readiness:
        return payload
    readiness = _mapping(source.get("readiness"))
    ready = readiness.get("ready") is True and readiness.get("state") == "ready"
    raw_code = _text(readiness.get("code"), maximum=200)
    code = raw_code if raw_code is not None and _SAFE_REASON_CODE.fullmatch(raw_code) else None
    payload["readiness"] = {
        "state": "ready" if ready else "blocked",
        "ready": ready,
        "code": code or ("ready" if ready else "room_execution_gate_profile_unavailable"),
    }
    return payload


def _policy_payload(
    policy: Mapping[str, Any] | None,
    *,
    conversation_id: str,
    consensus_kill_switch_enabled: bool | None = None,
) -> dict[str, Any]:
    source = policy or {}
    mode = source.get("mode") if source.get("mode") in {"manual", "consensus"} else "manual"
    revision = _integer(source.get("revision"))
    kill_switch = (
        consensus_kill_switch_enabled
        if consensus_kill_switch_enabled is not None
        else _boolean(
            source.get("kill_switch_enabled") or source.get("consensus_kill_switch_enabled")
        )
    )
    automatic_available = mode == "consensus" and kill_switch
    return {
        "mode": mode,
        "revision": revision,
        "risk_policy_revision": _text(source.get("risk_policy_revision"), maximum=200)
        or "room_execution_low_risk/v1",
        "kill_switch_enabled": kill_switch,
        "automatic_execution_available": automatic_available,
        "automatic_execution_code": (
            None
            if automatic_available
            else "execution_consensus_kill_switch_disabled"
            if mode == "consensus"
            else "execution_policy_manual"
        ),
        "updated_at": _text(source.get("updated_at"), maximum=100),
        "actions": {
            "update": {
                "available": True,
                "method": "PUT",
                "href": f"/api/chat/operator/conversations/{conversation_id}/execution-policy",
                "expected_revision": revision,
                "allowed_modes": ["manual", "consensus"],
            }
        },
    }


def _vote_summary(candidate: Mapping[str, Any]) -> dict[str, int]:
    provided = _mapping(candidate.get("vote_counts") or candidate.get("votes"))
    assessments = _records(candidate.get("assessments"), "assessments", "items")
    counts = {
        "required": _integer(
            provided.get("required")
            or candidate.get("required_assessment_count")
            or candidate.get("snapshot_peer_count")
            or len(_records(candidate.get("members"), "members", "items"))
        ),
        "endorse": _integer(provided.get("endorse")),
        "object": _integer(provided.get("object")),
        "abstain": _integer(provided.get("abstain")),
        "pending": _integer(provided.get("pending")),
    }
    if assessments and not any(counts[key] for key in ("endorse", "object", "abstain")):
        for item in assessments:
            assessment = item.get("assessment")
            if assessment in {"endorse", "object", "abstain"}:
                counts[str(assessment)] += 1
        counts["pending"] = max(
            0,
            counts["required"] - counts["endorse"] - counts["object"] - counts["abstain"],
        )
    return counts


def _gate_summary(run: Mapping[str, Any] | None) -> dict[str, int]:
    source = run or {}
    provided = _mapping(source.get("gate_summary"))
    gates = _records(source.get("gates"), "gates", "items")
    if provided:
        return {
            key: _integer(provided.get(key))
            for key in ("total", "pending", "running", "passed", "failed")
        }
    result = {"total": len(gates), "pending": 0, "running": 0, "passed": 0, "failed": 0}
    for gate in gates:
        state = gate.get("state") or gate.get("status")
        bucket = state if state in {"pending", "running", "passed", "failed"} else "pending"
        result[str(bucket)] += 1
    return result


def _safe_run_summary(run: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    run_id = _id(run, "run_id", "id")
    if run_id is None:
        return None
    state = _text(run.get("state"), maximum=64) or "unknown"
    return {
        "run_id": run_id,
        "state": state,
        "revision": _integer(run.get("revision")),
        "attempt_number": _integer(run.get("attempt_number")),
        "created_at": _text(run.get("created_at") or run.get("requested_at"), maximum=100),
        "updated_at": _text(run.get("updated_at"), maximum=100),
        "finished_at": _text(run.get("finished_at"), maximum=100),
        "reason_code": _text(run.get("reason_code"), maximum=200),
        "gate_profile": _gate_profile_payload(run.get("gate_profile")),
        "gate_summary": _gate_summary(run),
    }


def _candidate_summary(
    candidate: Mapping[str, Any],
    *,
    run: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    candidate_id = _id(candidate, "candidate_id", "id")
    digest = _id(candidate, "candidate_digest", "digest")
    if candidate_id is None or digest is None:
        return None
    allowed_files = _allowed_files(candidate)
    state = _text(candidate.get("state"), maximum=64) or "unknown"
    safe_run = _safe_run_summary(run)
    return {
        "candidate_id": candidate_id,
        "proposal_id": _id(candidate, "proposal_id"),
        "digest": digest,
        "revision": _integer(candidate.get("revision")),
        "state": state,
        "consensus_state": _text(candidate.get("consensus_state"), maximum=64),
        "reason_code": _text(candidate.get("reason_code"), maximum=200),
        "gate_profile": _gate_profile_payload(candidate.get("gate_profile")),
        "summary": _text(candidate.get("summary"), maximum=2_000) or "Exact patch candidate",
        "author": {
            "participant_id": _id(candidate, "author_participant_id", "author"),
            "display_name": _text(candidate.get("author_display_name"), maximum=120),
        },
        "allowed_files": allowed_files,
        "file_count": len(allowed_files),
        "byte_count": _integer(candidate.get("byte_count") or candidate.get("patch_bytes")),
        "votes": _vote_summary(candidate),
        "run": safe_run,
        "gate_summary": _gate_summary(run),
        "created_at": _text(candidate.get("created_at"), maximum=100),
        "updated_at": _text(candidate.get("updated_at"), maximum=100),
    }


def _run_by_candidate(runs: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for run in runs:
        candidate_id = _id(run, "candidate_id")
        if candidate_id is None:
            continue
        prior = result.get(candidate_id)
        if prior is None or str(run.get("created_at") or "") > str(prior.get("created_at") or ""):
            result[candidate_id] = run
    return result


def build_room_execution_list_projection(
    store: RoomExecutionReadStore,
    conversation_id: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    generated_at: str | None = None,
    consensus_kill_switch_enabled: bool | None = None,
    execution_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ValueError("room_execution_projection_limit_invalid")
    if cursor is not None and _text(cursor, maximum=200) is None:
        raise ValueError("room_execution_projection_cursor_invalid")
    raw_candidates = _records(
        store.list_conversation_candidates(conversation_id, limit=50),
        "candidates",
        "items",
    )
    raw_runs = _records(
        store.list_conversation_runs(conversation_id, limit=50),
        "runs",
        "items",
    )
    runs = _run_by_candidate(raw_runs)
    summaries = [
        summary
        for candidate in raw_candidates
        if (
            summary := _candidate_summary(
                candidate,
                run=runs.get(_id(candidate, "candidate_id", "id") or ""),
            )
        )
        is not None
    ]
    start = 0
    if cursor is not None:
        positions = [
            index for index, item in enumerate(summaries) if item["candidate_id"] == cursor
        ]
        if not positions:
            raise ValueError("room_execution_projection_cursor_invalid")
        start = positions[0] + 1
    page = summaries[start : start + limit]
    has_more = start + len(page) < len(summaries)
    profile_payload = _gate_profile_payload(execution_profile, include_readiness=True)
    policy_payload = _policy_payload(
        store.get_policy(conversation_id),
        conversation_id=conversation_id,
        consensus_kill_switch_enabled=consensus_kill_switch_enabled,
    )
    if profile_payload is None or profile_payload["readiness"]["ready"] is False:
        policy_payload["automatic_execution_available"] = False
        policy_payload["automatic_execution_code"] = "execution_gate_profile_unavailable"
    return {
        "schema_version": ROOM_EXECUTION_LIST_SCHEMA,
        "projection_only": True,
        "proof_boundary": ROOM_EXECUTION_PROOF_BOUNDARY,
        "generated_at": generated_at or _now(),
        "conversation_id": conversation_id,
        "gate_profile": profile_payload,
        "policy": policy_payload,
        "candidate_total": len(summaries),
        "candidates": page,
        "page": {
            "limit": limit,
            "cursor": cursor,
            "has_more": has_more,
            "next_cursor": page[-1]["candidate_id"] if has_more and page else None,
        },
    }


def _assessment_payload(value: Mapping[str, Any]) -> dict[str, Any] | None:
    participant_id = _id(value, "participant_id", "assessor_participant_id", "assessor")
    if participant_id is None:
        return None
    assessment = value.get("assessment")
    if assessment not in {"endorse", "object", "abstain", "pending", None}:
        assessment = None
    return {
        "participant_id": participant_id,
        "display_name": _text(value.get("display_name"), maximum=120),
        "status_snapshot": _text(value.get("status_snapshot"), maximum=64),
        "assessment": assessment or "pending",
        "rationale": _text(value.get("rationale"), maximum=2_000),
        "created_at": _text(value.get("created_at"), maximum=100),
    }


def _gate_payload(value: Mapping[str, Any]) -> dict[str, Any] | None:
    gate_id = _id(value, "gate_id", "id")
    if gate_id is None:
        return None
    return {
        "gate_id": gate_id,
        "label": _text(value.get("label") or value.get("gate_name"), maximum=200) or gate_id,
        "state": _text(value.get("state") or value.get("status"), maximum=64) or "pending",
        "evidence_digest": _id(value, "evidence_digest"),
        "started_at": _text(value.get("started_at"), maximum=100),
        "finished_at": _text(value.get("finished_at"), maximum=100),
        "reason_code": _text(value.get("reason_code"), maximum=200),
    }


def build_room_execution_candidate_projection(
    store: RoomExecutionReadStore,
    candidate_id: str,
    *,
    generated_at: str | None = None,
    consensus_kill_switch_enabled: bool | None = None,
    execution_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = store.get_candidate(candidate_id, include_patch=True)
    if candidate is None:
        raise KeyError(candidate_id)
    conversation_id = _id(candidate, "conversation_id")
    digest = _id(candidate, "candidate_digest", "digest")
    actual_id = _id(candidate, "candidate_id", "id")
    if conversation_id is None or digest is None or actual_id != candidate_id:
        raise ValueError("room_execution_candidate_invalid")
    diff = candidate.get("unified_diff")
    if not isinstance(diff, str) or len(diff.encode("utf-8")) > _MAX_DIFF_BYTES:
        raise ValueError("room_execution_candidate_diff_invalid")
    embedded_run = candidate.get("run")
    run = embedded_run if isinstance(embedded_run, Mapping) else None
    run_id = _id(run or {}, "run_id", "id") or _id(candidate, "latest_run_id", "run_id")
    if run_id and (run is None or "gates" not in run):
        run = store.get_run(run_id) or run
    if run is None:
        runs = _records(store.list_conversation_runs(conversation_id, limit=50), "runs", "items")
        run = _run_by_candidate(runs).get(candidate_id)
    summary = _candidate_summary(candidate, run=run)
    if summary is None:
        raise ValueError("room_execution_candidate_invalid")
    profile_payload = _gate_profile_payload(execution_profile, include_readiness=True)
    profile_ready = profile_payload is not None and profile_payload["readiness"]["ready"] is True
    policy = _policy_payload(
        store.get_policy(conversation_id),
        conversation_id=conversation_id,
        consensus_kill_switch_enabled=consensus_kill_switch_enabled,
    )
    if not profile_ready:
        policy["automatic_execution_available"] = False
        policy["automatic_execution_code"] = "execution_gate_profile_unavailable"
    members = _records(
        candidate.get("members")
        or candidate.get("snapshot_members")
        or candidate.get("candidate_members"),
        "members",
        "items",
    )
    assessments = _records(candidate.get("assessments"), "assessments", "items")
    assessment_by_id = {
        _id(item, "participant_id", "assessor_participant_id", "assessor"): item
        for item in assessments
    }
    votes = []
    for member in members:
        participant_id = _id(member, "participant_id")
        merged = {**member, **(assessment_by_id.get(participant_id) or {})}
        payload = _assessment_payload(merged)
        if payload is not None:
            votes.append(payload)
    if not votes:
        votes = [payload for item in assessments if (payload := _assessment_payload(item))]
    state = str(summary["state"])
    run_summary = summary["run"]
    run_state = str(run_summary.get("state")) if isinstance(run_summary, Mapping) else None
    candidate_actionable = state in _ACTIONABLE_CANDIDATE_STATES and (
        run_state is None or run_state in _TERMINAL_RUN_STATES
    )
    execution_actionable = profile_ready and candidate_actionable
    gates = [
        payload
        for item in _records((run or {}).get("gates"), "gates", "items")
        if (payload := _gate_payload(item)) is not None
    ]
    run_payload = dict(run_summary) if isinstance(run_summary, Mapping) else None
    if run_payload is not None:
        cancellable = run_state in _CANCELLABLE_RUN_STATES
        run_payload["gates"] = gates
        run_payload["actions"] = {
            "cancel": {
                "available": cancellable,
                "method": "POST",
                "href": f"/api/chat/operator/execution-runs/{run_payload['run_id']}/cancel",
                "expected_run_state": run_state,
                "expected_run_revision": run_payload["revision"],
            }
        }
    decision_base = {
        "method": "POST",
        "href": f"/api/chat/operator/execution-candidates/{candidate_id}/decision",
        "expected_candidate_digest": digest,
        "expected_candidate_revision": summary["revision"],
        "expected_policy_revision": policy["revision"],
    }
    files = [
        {
            "path": path,
            "change_type": _text(item.get("change_type"), maximum=64) or "modify",
            "hunk_count": _integer(item.get("hunk_count")),
        }
        for item in _records(candidate.get("files"), "files", "items")
        if (path := _text(item.get("path"), maximum=500)) is not None
    ][:32]
    policy_snapshot = _mapping(candidate.get("policy_snapshot"))
    return {
        "schema_version": ROOM_EXECUTION_CANDIDATE_SCHEMA,
        "projection_only": True,
        "proof_boundary": ROOM_EXECUTION_PROOF_BOUNDARY,
        "generated_at": generated_at or _now(),
        "conversation_id": conversation_id,
        "gate_profile": profile_payload,
        "candidate": {
            **summary,
            "base_head": _id(candidate, "base_head"),
            "unified_diff": diff,
            "files": files,
            "review_material_digest": _id(candidate, "review_material_digest"),
            "patch_sha256": _id(candidate, "patch_sha256"),
            "snapshot_digest": _id(candidate, "peer_snapshot_digest", "snapshot_digest"),
            "policy_mode_snapshot": _text(
                policy_snapshot.get("mode") or candidate.get("policy_mode"), maximum=64
            ),
            "policy_revision_snapshot": _integer(
                policy_snapshot.get("revision") or candidate.get("policy_revision")
            ),
            "risk_policy_revision_snapshot": _text(
                policy_snapshot.get("risk_policy_revision")
                or candidate.get("risk_policy_revision"),
                maximum=200,
            )
            or "room_execution_low_risk/v1",
        },
        "policy": policy,
        "votes": votes,
        "vote_counts": _vote_summary(candidate),
        "run": run_payload,
        "actions": {
            "execute": {"available": execution_actionable, **decision_base},
            "reject": {"available": candidate_actionable, **decision_base},
        },
    }
