"""Strict aggregate contract for the Goal + MemoryOS production soak.

Raw prompts, Room content, provider output, process identity, and local paths stay in
the private lab runner.  This module only accepts bounded numeric evidence and stable
digests, computes the hard gates, and writes a revalidated private receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "room_goal_memory_soak_manifest/v1"
EVIDENCE_SCHEMA = "room_goal_memory_soak_evidence/v1"
RESULT_SCHEMA = "room_goal_memory_soak_result/v1"
PROFILE_ID = "live-goal-memory-soak"
PROOF_BOUNDARY = "aggregate_goal_memory_soak_evidence_not_room_provider_or_memory_authority"

ROOM_COUNT = 4
AGENTS_PER_ROOM = 2
WAVE_COUNT = 4
EXPECTED_CORRELATIONS = ROOM_COUNT * WAVE_COUNT
MINIMUM_DURATION_MS = 3_600_000
MAX_ACTIVE_DELIVERIES = 4
MAX_RESULT_BYTES = 64 * 1024
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}\Z")

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "profile_id",
        "seed",
        "xmuse_sha",
        "memoryos_sha",
        "codex_version",
        "native_capability_descriptor_digest",
        "task_manifest_digest",
        "started_at",
        "finished_at",
    }
)
_COUNT_KEYS = frozenset(
    {
        "correlations",
        "settled_correlations",
        "attempts",
        "outcomes",
        "duplicate_outcomes",
        "cross_room_identity",
        "cross_room_causality",
        "cross_room_source",
        "provider_orphans",
        "live_leases",
        "cleanup_pending",
        "recovery_pending",
        "exhausted",
        "max_active_deliveries",
    }
)
_LATENCY_KEYS = frozenset({"post_to_claim", "post_to_outcome", "post_to_settled"})
_NATIVE_KEYS = frozenset(
    {
        "participant_count",
        "settings_participants_covered",
        "settings_assignment_digest",
        "distinct_settings_combinations",
        "max_effort_observed",
        "goal_auto_continuations",
        "goal_terminal_state",
        "goal_hold_claim_violations",
        "goal_resume_count",
        "goal_resume_max_ms",
        "other_agent_root_deliveries",
        "peer_wait_projections",
        "steer_actions",
        "review_actions",
    }
)
_USAGE_KEYS = frozenset({"input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"})
_MEMORY_KEYS = frozenset(
    {
        "compact_response_upper_bound_bytes",
        "raw_response_upper_bound_bytes",
        "accepted_evidence_upper_bound_bytes",
        "source_ref_count",
        "source_proof_failures",
        "restart_count",
        "outbox_pending",
        "outbox_conflict",
        "room_readiness_degraded",
        "settlement_blocked",
    }
)
_FAULT_KEYS = frozenset(
    {
        "seq",
        "kind",
        "reason_code",
        "recovery_ms",
        "active_delivery_count",
        "runner_count",
        "mcp_count",
    }
)
_FAULTS = (
    ("codex_app_server_sigkill", "codex_app_server_cleanup_confirmed"),
    ("runner_sigkill", "runner_reconciled"),
    ("memoryos_sigkill", "memoryos_reconciled"),
    ("codex_projection_cache_deleted", "codex_projection_cache_rebuilt"),
)
_VIEWPORT_KEYS = frozenset(
    {
        "width",
        "height",
        "refreshes",
        "console_errors",
        "page_errors",
        "current_state_available",
        "history_fabricated",
    }
)
_VIEWPORTS = ((640, 900), (1280, 720), (1440, 900))
_RESOURCE_KEYS = frozenset(
    {
        "rss_warmup_median_bytes",
        "rss_steady_state_max_bytes",
        "fd_warmup",
        "fd_steady_state_max",
        "process_count_max",
        "database_bytes",
        "wal_bytes",
        "sqlite_integrity",
    }
)
_WORKTREE_KEYS = frozenset(
    {
        "sentinel_before_digest",
        "sentinel_after_digest",
        "repository_before_digest",
        "repository_after_digest",
        "git_status_before_digest",
        "git_status_after_digest",
    }
)
_TERMINAL_GOAL_STATES = frozenset(
    {"paused", "blocked", "usageLimited", "budgetLimited", "complete"}
)


class GoalMemorySoakContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GoalMemorySoakContractError("contract_json_invalid") from exc


def _sha(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


def _exact(value: object, keys: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise GoalMemorySoakContractError(code)
    return value


def _count(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_SAFE_INTEGER:
        raise GoalMemorySoakContractError(code)
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise GoalMemorySoakContractError(code)
    return value


def _stamp(value: object, code: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or len(value) > 100:
        raise GoalMemorySoakContractError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoalMemorySoakContractError(code) from exc
    if parsed.tzinfo is None:
        raise GoalMemorySoakContractError(code)
    utc = parsed.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"), utc


def validate_goal_memory_soak_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _exact(payload, _MANIFEST_KEYS, "manifest_invalid")
    if raw.get("schema_version") != MANIFEST_SCHEMA or raw.get("profile_id") != PROFILE_ID:
        raise GoalMemorySoakContractError("manifest_invalid")
    seed = _count(raw.get("seed"), "manifest_invalid")
    xmuse_sha = raw.get("xmuse_sha")
    memoryos_sha = raw.get("memoryos_sha")
    version = raw.get("codex_version")
    if (
        not isinstance(xmuse_sha, str)
        or _COMMIT.fullmatch(xmuse_sha) is None
        or not isinstance(memoryos_sha, str)
        or _COMMIT.fullmatch(memoryos_sha) is None
        or not isinstance(version, str)
        or _VERSION.fullmatch(version) is None
    ):
        raise GoalMemorySoakContractError("manifest_invalid")
    started, started_dt = _stamp(raw.get("started_at"), "manifest_invalid")
    finished, finished_dt = _stamp(raw.get("finished_at"), "manifest_invalid")
    if finished_dt < started_dt:
        raise GoalMemorySoakContractError("manifest_invalid")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "profile_id": PROFILE_ID,
        "seed": seed,
        "xmuse_sha": xmuse_sha,
        "memoryos_sha": memoryos_sha,
        "codex_version": version,
        "native_capability_descriptor_digest": _digest(
            raw.get("native_capability_descriptor_digest"), "manifest_invalid"
        ),
        "task_manifest_digest": _digest(raw.get("task_manifest_digest"), "manifest_invalid"),
        "started_at": started,
        "finished_at": finished,
    }


def _normalize_counts(value: object) -> dict[str, int]:
    raw = _exact(value, _COUNT_KEYS, "evidence_counts_invalid")
    return {key: _count(raw.get(key), "evidence_counts_invalid") for key in _COUNT_KEYS}


def _samples(value: object) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) > 10_000:
        raise GoalMemorySoakContractError("evidence_latency_invalid")
    return [_count(item, "evidence_latency_invalid") for item in value]


def _percentile(values: Sequence[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil((percentile / 100) * len(ordered)) - 1)]


def _summary(values: Sequence[int]) -> dict[str, int | None]:
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "max": max(values) if values else None,
    }


def _normalize_native(value: object) -> dict[str, Any]:
    raw = _exact(value, _NATIVE_KEYS, "evidence_native_invalid")
    state = raw.get("goal_terminal_state")
    if state not in _TERMINAL_GOAL_STATES:
        raise GoalMemorySoakContractError("evidence_native_invalid")
    result: dict[str, Any] = {
        key: _count(raw.get(key), "evidence_native_invalid")
        for key in _NATIVE_KEYS - {"settings_assignment_digest", "goal_terminal_state"}
    }
    result["settings_assignment_digest"] = _digest(
        raw.get("settings_assignment_digest"), "evidence_native_invalid"
    )
    result["goal_terminal_state"] = state
    return result


def _normalize_numeric(value: object, keys: frozenset[str], code: str) -> dict[str, int]:
    raw = _exact(value, keys, code)
    return {key: _count(raw.get(key), code) for key in keys}


def _normalize_faults(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 4:
        raise GoalMemorySoakContractError("evidence_faults_invalid")
    result: list[dict[str, Any]] = []
    for expected_seq, raw_value in enumerate(value, 1):
        raw = _exact(raw_value, _FAULT_KEYS, "evidence_faults_invalid")
        result.append(
            {
                "seq": _count(raw.get("seq"), "evidence_faults_invalid"),
                "kind": raw.get("kind"),
                "reason_code": raw.get("reason_code"),
                "recovery_ms": _count(raw.get("recovery_ms"), "evidence_faults_invalid"),
                "active_delivery_count": _count(
                    raw.get("active_delivery_count"), "evidence_faults_invalid"
                ),
                "runner_count": _count(raw.get("runner_count"), "evidence_faults_invalid"),
                "mcp_count": _count(raw.get("mcp_count"), "evidence_faults_invalid"),
            }
        )
        if result[-1]["seq"] != expected_seq:
            raise GoalMemorySoakContractError("evidence_faults_invalid")
    return result


def _normalize_browser(value: object) -> dict[str, Any]:
    raw = _exact(value, frozenset({"headed", "viewports"}), "evidence_browser_invalid")
    if not isinstance(raw.get("headed"), bool):
        raise GoalMemorySoakContractError("evidence_browser_invalid")
    viewports = raw.get("viewports")
    if isinstance(viewports, (str, bytes)) or not isinstance(viewports, Sequence):
        raise GoalMemorySoakContractError("evidence_browser_invalid")
    normalized = []
    for value_item in viewports:
        item = _exact(value_item, _VIEWPORT_KEYS, "evidence_browser_invalid")
        normalized.append(
            {key: _count(item.get(key), "evidence_browser_invalid") for key in _VIEWPORT_KEYS}
        )
    return {"headed": raw["headed"], "viewports": normalized}


def _normalize_resources(value: object) -> dict[str, Any]:
    raw = _exact(value, _RESOURCE_KEYS, "evidence_resources_invalid")
    integrity = raw.get("sqlite_integrity")
    if integrity not in {"ok", "failed"}:
        raise GoalMemorySoakContractError("evidence_resources_invalid")
    result: dict[str, Any] = {
        key: _count(raw.get(key), "evidence_resources_invalid")
        for key in _RESOURCE_KEYS - {"sqlite_integrity"}
    }
    result["sqlite_integrity"] = integrity
    result["rss_growth_bytes"] = max(
        0, result["rss_steady_state_max_bytes"] - result["rss_warmup_median_bytes"]
    )
    result["rss_growth_limit_bytes"] = max(
        result["rss_warmup_median_bytes"] // 2, 128 * 1024 * 1024
    )
    result["fd_delta"] = max(0, result["fd_steady_state_max"] - result["fd_warmup"])
    return result


def _normalize_worktree(value: object) -> dict[str, str]:
    raw = _exact(value, _WORKTREE_KEYS, "evidence_worktree_invalid")
    return {key: _digest(raw.get(key), "evidence_worktree_invalid") for key in _WORKTREE_KEYS}


def _configuration() -> dict[str, Any]:
    return {
        "profile_id": PROFILE_ID,
        "room_count": ROOM_COUNT,
        "agents_per_room": AGENTS_PER_ROOM,
        "wave_count": WAVE_COUNT,
        "minimum_duration_ms": MINIMUM_DURATION_MS,
        "max_active_deliveries": MAX_ACTIVE_DELIVERIES,
    }


def _gate(gate_id: str, passed: bool, observed: int | str, limit: int | str) -> dict[str, Any]:
    status = "passed" if passed else "failed"
    return {
        "gate_id": gate_id,
        "status": status,
        "observed": observed,
        "limit": limit,
        "reason_code": f"goal_memory_soak_{gate_id}_{status}",
    }


def _gates(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = result["manifest"]
    counts = result["counts"]
    latency = result["latency_ms"]
    native = result["native"]
    memory = result["memory"]
    faults = result["faults"]
    browser = result["browser"]
    resources = result["resources"]
    worktree = result["worktree"]
    duration_ms = int(
        round(
            (
                datetime.fromisoformat(manifest["finished_at"].replace("Z", "+00:00"))
                - datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00"))
            ).total_seconds()
            * 1000
        )
    )
    residual = sum(
        counts[key] for key in ("live_leases", "cleanup_pending", "recovery_pending", "exhausted")
    )
    violations = sum(
        counts[key]
        for key in (
            "duplicate_outcomes",
            "cross_room_identity",
            "cross_room_causality",
            "cross_room_source",
            "provider_orphans",
        )
    )
    first_p95 = latency["settle_first_half"]["p95"]
    second_p95 = latency["settle_second_half"]["p95"]
    expected_faults = [pair[0] for pair in _FAULTS]
    expected_reasons = [pair[1] for pair in _FAULTS]
    viewport_pairs = [(item["width"], item["height"]) for item in browser["viewports"]]
    browser_errors = sum(
        item["console_errors"] + item["page_errors"] + item["history_fabricated"]
        for item in browser["viewports"]
    )
    browser_coverage = all(
        item["refreshes"] >= ROOM_COUNT
        and item["current_state_available"] >= ROOM_COUNT * AGENTS_PER_ROOM
        for item in browser["viewports"]
    )
    return [
        _gate(
            "minimum_duration",
            duration_ms >= MINIMUM_DURATION_MS
            and result["monotonic_elapsed_ms"] >= MINIMUM_DURATION_MS,
            min(duration_ms, result["monotonic_elapsed_ms"]),
            MINIMUM_DURATION_MS,
        ),
        _gate(
            "all_correlations_settled",
            counts["correlations"] == EXPECTED_CORRELATIONS
            and counts["settled_correlations"] == EXPECTED_CORRELATIONS,
            counts["settled_correlations"],
            EXPECTED_CORRELATIONS,
        ),
        _gate("room_invariants", violations == 0, violations, 0),
        _gate("residual_zero", residual == 0, residual, 0),
        _gate(
            "active_delivery_limit",
            counts["max_active_deliveries"] <= MAX_ACTIVE_DELIVERIES,
            counts["max_active_deliveries"],
            MAX_ACTIVE_DELIVERIES,
        ),
        _gate(
            "first_claim_deadline",
            latency["post_to_claim"]["count"] == EXPECTED_CORRELATIONS
            and latency["post_to_claim"]["max"] is not None
            and latency["post_to_claim"]["max"] <= 240_000,
            latency["post_to_claim"]["max"] or 0,
            240_000,
        ),
        _gate(
            "settle_latency_stability",
            first_p95 is not None
            and second_p95 is not None
            and second_p95 <= int(first_p95 * 2.5 + 60_000),
            second_p95 or 0,
            int(first_p95 * 2.5 + 60_000) if first_p95 is not None else 0,
        ),
        _gate(
            "native_settings_coverage",
            native["participant_count"] == ROOM_COUNT * AGENTS_PER_ROOM
            and native["settings_participants_covered"] == ROOM_COUNT * AGENTS_PER_ROOM
            and native["distinct_settings_combinations"] >= 2
            and native["max_effort_observed"] >= 1,
            native["settings_participants_covered"],
            ROOM_COUNT * AGENTS_PER_ROOM,
        ),
        _gate(
            "native_goal_terminal",
            native["goal_auto_continuations"] >= 1
            and native["goal_terminal_state"] in _TERMINAL_GOAL_STATES,
            native["goal_auto_continuations"],
            1,
        ),
        _gate(
            "goal_hold_respected",
            native["goal_hold_claim_violations"] == 0,
            native["goal_hold_claim_violations"],
            0,
        ),
        _gate(
            "goal_resume_deadline",
            native["goal_resume_count"] >= 1 and native["goal_resume_max_ms"] <= 30_000,
            native["goal_resume_max_ms"],
            30_000,
        ),
        _gate(
            "native_collaboration_observed",
            min(
                native["other_agent_root_deliveries"],
                native["peer_wait_projections"],
                native["steer_actions"],
                native["review_actions"],
            )
            >= 1,
            min(
                native["other_agent_root_deliveries"],
                native["peer_wait_projections"],
                native["steer_actions"],
                native["review_actions"],
            ),
            1,
        ),
        _gate(
            "memory_compact_size",
            memory["compact_response_upper_bound_bytes"] <= 65_536,
            memory["compact_response_upper_bound_bytes"],
            65_536,
        ),
        _gate(
            "memory_raw_size",
            memory["raw_response_upper_bound_bytes"] <= 131_072,
            memory["raw_response_upper_bound_bytes"],
            131_072,
        ),
        _gate(
            "memory_accepted_size",
            memory["accepted_evidence_upper_bound_bytes"] <= 8_192,
            memory["accepted_evidence_upper_bound_bytes"],
            8_192,
        ),
        _gate(
            "memory_source_proven",
            memory["source_ref_count"] > 0 and memory["source_proof_failures"] == 0,
            memory["source_proof_failures"],
            0,
        ),
        _gate(
            "memory_recovered",
            memory["restart_count"] >= 1
            and memory["outbox_pending"] == 0
            and memory["outbox_conflict"] == 0
            and memory["room_readiness_degraded"] == 0
            and memory["settlement_blocked"] == 0,
            memory["restart_count"],
            1,
        ),
        _gate(
            "fault_sequence",
            [item["kind"] for item in faults] == expected_faults
            and [item["reason_code"] for item in faults] == expected_reasons,
            len(faults),
            4,
        ),
        _gate(
            "fault_preconditions",
            faults[0]["active_delivery_count"] >= 1 and faults[1]["active_delivery_count"] >= 2,
            faults[1]["active_delivery_count"],
            2,
        ),
        _gate(
            "fault_recovery_deadline",
            all(item["recovery_ms"] <= 45_000 for item in faults),
            max(item["recovery_ms"] for item in faults),
            45_000,
        ),
        _gate(
            "single_runtime_topology",
            all(item["runner_count"] == 1 and item["mcp_count"] == 1 for item in faults),
            max(item["runner_count"] + item["mcp_count"] for item in faults),
            2,
        ),
        _gate(
            "browser_viewports",
            browser["headed"] is True and viewport_pairs == list(_VIEWPORTS),
            len(viewport_pairs),
            3,
        ),
        _gate("browser_clean", browser_errors == 0, browser_errors, 0),
        _gate("browser_state_recovered", browser_coverage, int(browser_coverage), 1),
        _gate(
            "sqlite_integrity",
            resources["sqlite_integrity"] == "ok",
            resources["sqlite_integrity"],
            "ok",
        ),
        _gate("fd_growth_limit", resources["fd_delta"] <= 16, resources["fd_delta"], 16),
        _gate(
            "rss_growth_limit",
            resources["rss_growth_bytes"] <= resources["rss_growth_limit_bytes"],
            resources["rss_growth_bytes"],
            resources["rss_growth_limit_bytes"],
        ),
        _gate(
            "worktree_unchanged",
            worktree["sentinel_before_digest"] == worktree["sentinel_after_digest"]
            and worktree["repository_before_digest"] == worktree["repository_after_digest"]
            and worktree["git_status_before_digest"] == worktree["git_status_after_digest"],
            worktree["repository_after_digest"],
            worktree["repository_before_digest"],
        ),
    ]


def build_goal_memory_soak_result(
    *, manifest: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    manifest_value = validate_goal_memory_soak_manifest(manifest)
    expected_evidence = frozenset(
        {
            "schema_version",
            "monotonic_elapsed_ms",
            "counts",
            "latency_samples_ms",
            "native",
            "numeric_usage",
            "memory",
            "faults",
            "browser",
            "resources",
            "worktree",
        }
    )
    raw = _exact(evidence, expected_evidence, "evidence_invalid")
    if raw.get("schema_version") != EVIDENCE_SCHEMA:
        raise GoalMemorySoakContractError("evidence_invalid")
    latency_raw = _exact(raw.get("latency_samples_ms"), _LATENCY_KEYS, "evidence_latency_invalid")
    latency_samples = {key: _samples(latency_raw.get(key)) for key in _LATENCY_KEYS}
    settle = latency_samples["post_to_settled"]
    split = (len(settle) + 1) // 2
    resources = _normalize_resources(raw.get("resources"))
    run_digest = _sha({"manifest": manifest_value, "seed": manifest_value["seed"]})
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "run_id": f"goal_memory_soak_{run_digest[7:39]}",
        "manifest": manifest_value,
        "status": "failed",
        "monotonic_elapsed_ms": _count(raw.get("monotonic_elapsed_ms"), "evidence_invalid"),
        "configuration": _configuration(),
        "counts": _normalize_counts(raw.get("counts")),
        "latency_ms": {
            **{key: _summary(values) for key, values in latency_samples.items()},
            "settle_first_half": _summary(settle[:split]),
            "settle_second_half": _summary(settle[split:]),
        },
        "native": _normalize_native(raw.get("native")),
        "numeric_usage": _normalize_numeric(
            raw.get("numeric_usage"), _USAGE_KEYS, "evidence_usage_invalid"
        ),
        "memory": _normalize_numeric(raw.get("memory"), _MEMORY_KEYS, "evidence_memory_invalid"),
        "faults": _normalize_faults(raw.get("faults")),
        "browser": _normalize_browser(raw.get("browser")),
        "resources": resources,
        "worktree": _normalize_worktree(raw.get("worktree")),
        "gates": [],
        "result_digest": "",
        "proof_boundary": PROOF_BOUNDARY,
    }
    result["gates"] = _gates(result)
    result["status"] = (
        "passed" if all(item["status"] == "passed" for item in result["gates"]) else "failed"
    )
    result["result_digest"] = _sha(
        {key: value for key, value in result.items() if key != "result_digest"}
    )
    return validate_goal_memory_soak_result(result)


def _validate_summary(value: object) -> dict[str, int | None]:
    raw = _exact(value, frozenset({"count", "p50", "p95", "max"}), "result_invalid")
    count = _count(raw.get("count"), "result_invalid")
    result: dict[str, int | None] = {"count": count}
    for key in ("p50", "p95", "max"):
        item = raw.get(key)
        result[key] = None if item is None else _count(item, "result_invalid")
    if (count == 0) != (result["max"] is None):
        raise GoalMemorySoakContractError("result_invalid")
    if count and not (
        result["p50"] is not None
        and result["p95"] is not None
        and result["max"] is not None
        and result["p50"] <= result["p95"] <= result["max"]
    ):
        raise GoalMemorySoakContractError("result_invalid")
    return result


def validate_goal_memory_soak_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = frozenset(
        {
            "schema_version",
            "run_id",
            "manifest",
            "status",
            "monotonic_elapsed_ms",
            "configuration",
            "counts",
            "latency_ms",
            "native",
            "numeric_usage",
            "memory",
            "faults",
            "browser",
            "resources",
            "worktree",
            "gates",
            "result_digest",
            "proof_boundary",
        }
    )
    raw = _exact(payload, expected, "result_invalid")
    run_id = raw.get("run_id")
    if (
        raw.get("schema_version") != RESULT_SCHEMA
        or raw.get("proof_boundary") != PROOF_BOUNDARY
        or raw.get("status") not in {"passed", "failed"}
        or not isinstance(run_id, str)
        or re.fullmatch(r"goal_memory_soak_[0-9a-f]{32}", run_id) is None
        or raw.get("configuration") != _configuration()
    ):
        raise GoalMemorySoakContractError("result_invalid")
    normalized = dict(raw)
    normalized["manifest"] = validate_goal_memory_soak_manifest(raw["manifest"])
    normalized["monotonic_elapsed_ms"] = _count(raw.get("monotonic_elapsed_ms"), "result_invalid")
    normalized["counts"] = _normalize_counts(raw.get("counts"))
    latency = _exact(
        raw.get("latency_ms"),
        _LATENCY_KEYS | {"settle_first_half", "settle_second_half"},
        "result_invalid",
    )
    normalized["latency_ms"] = {key: _validate_summary(latency[key]) for key in latency}
    normalized["native"] = _normalize_native(raw.get("native"))
    normalized["numeric_usage"] = _normalize_numeric(
        raw.get("numeric_usage"), _USAGE_KEYS, "result_invalid"
    )
    normalized["memory"] = _normalize_numeric(raw.get("memory"), _MEMORY_KEYS, "result_invalid")
    normalized["faults"] = _normalize_faults(raw.get("faults"))
    normalized["browser"] = _normalize_browser(raw.get("browser"))
    resources_expected = _RESOURCE_KEYS | {"rss_growth_bytes", "rss_growth_limit_bytes", "fd_delta"}
    resource_raw = _exact(raw.get("resources"), resources_expected, "result_invalid")
    base_resources = {key: resource_raw[key] for key in _RESOURCE_KEYS}
    normalized_resources = _normalize_resources(base_resources)
    if any(resource_raw[key] != normalized_resources[key] for key in resources_expected):
        raise GoalMemorySoakContractError("result_invalid")
    normalized["resources"] = normalized_resources
    normalized["worktree"] = _normalize_worktree(raw.get("worktree"))
    expected_gates = _gates(normalized)
    expected_status = (
        "passed" if all(item["status"] == "passed" for item in expected_gates) else "failed"
    )
    if raw.get("gates") != expected_gates or raw.get("status") != expected_status:
        raise GoalMemorySoakContractError("result_gates_invalid")
    expected_digest = _sha(
        {key: value for key, value in normalized.items() if key != "result_digest"}
    )
    if raw.get("result_digest") != expected_digest:
        raise GoalMemorySoakContractError("result_digest_invalid")
    normalized["gates"] = expected_gates
    normalized["result_digest"] = expected_digest
    if len(_canonical(normalized)) > MAX_RESULT_BYTES:
        raise GoalMemorySoakContractError("result_too_large")
    return json.loads(_canonical(normalized))


def evaluate_goal_memory_soak_result(
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    normalized = validate_goal_memory_soak_result(payload)
    failed = tuple(
        str(item["gate_id"]) for item in normalized["gates"] if item["status"] == "failed"
    )
    return not failed, failed


def write_goal_memory_soak_result(path: Path | str, payload: Mapping[str, Any]) -> None:
    normalized = validate_goal_memory_soak_result(payload)
    target = Path(path)
    if not target.name or target.name in {".", ".."}:
        raise GoalMemorySoakContractError("result_path_unsafe")
    try:
        parent = target.parent.resolve(strict=True)
        directory = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise GoalMemorySoakContractError("result_path_unsafe") from exc
    temporary = f".{target.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    try:
        try:
            existing = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise GoalMemorySoakContractError("result_path_unsafe")
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(_canonical(normalized) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except GoalMemorySoakContractError:
        raise
    except OSError as exc:
        raise GoalMemorySoakContractError("result_write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        finally:
            os.close(directory)


__all__ = [
    "MANIFEST_SCHEMA",
    "RESULT_SCHEMA",
    "GoalMemorySoakContractError",
    "build_goal_memory_soak_result",
    "validate_goal_memory_soak_manifest",
    "validate_goal_memory_soak_result",
    "evaluate_goal_memory_soak_result",
    "write_goal_memory_soak_result",
]
