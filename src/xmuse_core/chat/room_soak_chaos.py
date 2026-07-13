"""Safe, deterministic result contract for Room soak and chaos runs.

The lab runner owns raw observations.  This module accepts only aggregate numeric
evidence and emits a bounded receipt that cannot contain Room or provider content.
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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

SOAK_RESULT_SCHEMA = "room_soak_chaos_result/v1"
CI_EVIDENCE_SCHEMA = "room_soak_ci_evidence/v1"
LIVE_EVIDENCE_SCHEMA = "room_soak_live_evidence/v1"
SOAK_PROOF_BOUNDARY = "aggregate_soak_evidence_not_room_or_provider_authority"
MAX_RESULT_BYTES = 64 * 1024

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_LATENCY_MS = 7 * 24 * 60 * 60 * 1000


class RoomSoakChaosError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SoakProfile:
    profile_id: str
    room_count: int
    agents_per_room: int
    human_turns_per_room: int
    transport: Literal["scripted", "codex"]
    max_attempts: int | None
    minimum_duration_s: int
    provider_cost_confirmation_required: bool
    memory_recovery: bool


_PROFILES = {
    profile.profile_id: profile
    for profile in (
        SoakProfile("ci-sim", 12, 4, 20, "scripted", None, 0, False, False),
        SoakProfile("live-short", 4, 2, 2, "codex", 48, 0, False, False),
        SoakProfile("live-soak", 6, 2, 4, "codex", 128, 3600, True, False),
        SoakProfile("memory-recovery", 2, 2, 10, "codex", None, 0, False, True),
    )
}

_CONFIG_KEYS = frozenset(
    {
        "room_count",
        "agents_per_room",
        "human_turns_per_room",
        "max_concurrent_provider_deliveries",
    }
)
_COUNT_KEYS = frozenset(
    {
        "human_posts",
        "correlations",
        "attempts",
        "outcomes",
        "root_attempts",
        "peer_attempts",
        "respond",
        "noop",
        "other_outcomes",
        "skill_decisions",
        "settled_correlations",
    }
)
_CONCURRENCY_KEYS = frozenset(
    {
        "max_active_deliveries",
        "rooms_first_claimed",
        "attempts_until_all_rooms_first_claimed",
        "max_active_posts",
        "queued_correlations_before_host",
    }
)
_LATENCY_KEYS = frozenset({"post_to_claim", "post_to_outcome", "post_to_settled"})
_VIOLATION_KEYS = frozenset(
    {"duplicate_outcome", "cross_room_identity", "cross_room_causality", "unsettled_correlation"}
)
_RESIDUAL_KEYS = frozenset(
    {"live_leases", "cleanup_pending", "recovery_pending", "exhausted", "incomplete_attempts"}
)
_STORAGE_KEYS = frozenset({"database_bytes", "wal_bytes", "sqlite_integrity"})
_RESOURCE_KEYS = frozenset(
    {
        "rss_warmup_median_bytes",
        "rss_steady_state_max_bytes",
        "fd_warmup",
        "fd_steady_state_max",
        "process_count_max",
    }
)
_BROWSER_KEYS = frozenset({"refreshes", "console_errors", "page_errors"})
_WORKTREE_KEYS = frozenset({"before_digest", "after_digest"})
_MEMORY_KEYS = frozenset(
    {
        "enabled",
        "restart_count",
        "outbox_delivered",
        "outbox_pending",
        "outbox_conflict",
        "recall_receipts",
        "recall_source_refs",
    }
)
_EVENT_KEYS = frozenset(
    {
        "seq",
        "kind",
        "reason_code",
        "offset_ms",
        "recovery_ms",
        "runner_count",
        "mcp_count",
        "active_delivery_count",
        "managed_reconcile",
        "recovery_wave_settled",
    }
)
_EVENT_REASON_BY_KIND = {
    "codex_app_server_sigkill": "codex_app_server_cleanup_confirmed",
    "runner_sigkill": "runner_reconciled",
    "memoryos_sigkill": "memoryos_reconciled",
}
_LATENCY_SAMPLE_KEYS = frozenset({"ordinal", "latency_ms"})


def get_soak_profile(profile_id: str) -> SoakProfile:
    try:
        return _PROFILES[profile_id]
    except (KeyError, TypeError) as exc:
        raise RoomSoakChaosError("room_soak_profile_unknown") from exc


def _exact_mapping(value: object, keys: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RoomSoakChaosError(code)
    return value


def _count(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_SAFE_INTEGER:
        raise RoomSoakChaosError(code)
    return value


def _timestamp(value: object, code: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or len(value) > 100:
        raise RoomSoakChaosError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RoomSoakChaosError(code) from exc
    if parsed.tzinfo is None:
        raise RoomSoakChaosError(code)
    utc = parsed.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"), utc


def _latency_samples(value: object, code: str) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) > 10_000:
        raise RoomSoakChaosError(code)
    result: list[int] = []
    for expected_ordinal, item in enumerate(value, 1):
        sample = _exact_mapping(item, _LATENCY_SAMPLE_KEYS, code)
        if _count(sample.get("ordinal"), code) != expected_ordinal:
            raise RoomSoakChaosError(code)
        raw_latency = sample.get("latency_ms")
        if isinstance(raw_latency, bool) or not isinstance(raw_latency, (int, float)):
            raise RoomSoakChaosError(code)
        number = float(raw_latency)
        if not math.isfinite(number) or not 0 <= number <= _MAX_LATENCY_MS:
            raise RoomSoakChaosError(code)
        result.append(int(round(number)))
    return result


def _percentile(values: Sequence[int], percentage: int) -> int | None:
    """Deterministic nearest-rank percentile over non-negative milliseconds."""

    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percentage / 100) * len(ordered)))
    return ordered[rank - 1]


def _summary(values: Sequence[int]) -> dict[str, int | None]:
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "max": max(values) if values else None,
    }


def _configuration(profile: SoakProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "room_count": profile.room_count,
        "agents_per_room": profile.agents_per_room,
        "human_turns_per_room": profile.human_turns_per_room,
        "transport": profile.transport,
        "max_attempts": profile.max_attempts,
        "minimum_duration_s": profile.minimum_duration_s,
        "provider_cost_confirmation_required": profile.provider_cost_confirmation_required,
        "memory_recovery": profile.memory_recovery,
        "max_concurrent_provider_deliveries": 4,
    }


def _normalize_base_evidence(
    profile: SoakProfile, evidence: Mapping[str, Any], *, live: bool
) -> dict[str, Any]:
    expected_top = {
        "schema_version",
        "profile_id",
        "configuration",
        "counts",
        "concurrency",
        "latency_samples_ms",
        "violations",
        "residual",
        "storage",
    }
    if live:
        expected_top.update(
            {
                "provider_cost_confirmed",
                "resources",
                "chaos_events",
                "browser",
                "worktree",
                "memory",
                "monotonic_elapsed_ms",
            }
        )
    if set(evidence) != expected_top:
        raise RoomSoakChaosError("room_soak_evidence_fields_invalid")
    expected_schema = LIVE_EVIDENCE_SCHEMA if live else CI_EVIDENCE_SCHEMA
    if (
        evidence.get("schema_version") != expected_schema
        or evidence.get("profile_id") != profile.profile_id
    ):
        raise RoomSoakChaosError("room_soak_evidence_identity_invalid")

    configuration = _exact_mapping(
        evidence.get("configuration"), _CONFIG_KEYS, "room_soak_configuration_invalid"
    )
    expected_configuration = {
        "room_count": profile.room_count,
        "agents_per_room": profile.agents_per_room,
        "human_turns_per_room": profile.human_turns_per_room,
        "max_concurrent_provider_deliveries": 4,
    }
    normalized_configuration = {
        key: _count(configuration.get(key), "room_soak_configuration_invalid")
        for key in _CONFIG_KEYS
    }
    if normalized_configuration != expected_configuration:
        raise RoomSoakChaosError("room_soak_configuration_mismatch")

    counts_raw = _exact_mapping(evidence.get("counts"), _COUNT_KEYS, "room_soak_counts_invalid")
    counts = {key: _count(counts_raw.get(key), "room_soak_counts_invalid") for key in _COUNT_KEYS}
    concurrency_raw = _exact_mapping(
        evidence.get("concurrency"), _CONCURRENCY_KEYS, "room_soak_concurrency_invalid"
    )
    concurrency = {
        key: _count(concurrency_raw.get(key), "room_soak_concurrency_invalid")
        for key in _CONCURRENCY_KEYS
    }
    latency_raw = _exact_mapping(
        evidence.get("latency_samples_ms"), _LATENCY_KEYS, "room_soak_latency_invalid"
    )
    latency_samples = {
        key: _latency_samples(latency_raw.get(key), "room_soak_latency_invalid")
        for key in _LATENCY_KEYS
    }
    violation_keys = _VIOLATION_KEYS | ({"provider_orphans"} if live else set())
    violations_raw = _exact_mapping(
        evidence.get("violations"), frozenset(violation_keys), "room_soak_violations_invalid"
    )
    violations = {
        key: _count(violations_raw.get(key), "room_soak_violations_invalid")
        for key in violation_keys
    }
    violations.setdefault("provider_orphans", 0)
    residual_raw = _exact_mapping(
        evidence.get("residual"), _RESIDUAL_KEYS, "room_soak_residual_invalid"
    )
    residual = {
        key: _count(residual_raw.get(key), "room_soak_residual_invalid") for key in _RESIDUAL_KEYS
    }
    storage_raw = _exact_mapping(
        evidence.get("storage"), _STORAGE_KEYS, "room_soak_storage_invalid"
    )
    integrity = storage_raw.get("sqlite_integrity")
    if integrity not in {"ok", "failed"}:
        raise RoomSoakChaosError("room_soak_storage_invalid")
    storage = {
        "database_bytes": _count(storage_raw.get("database_bytes"), "room_soak_storage_invalid"),
        "wal_bytes": _count(storage_raw.get("wal_bytes"), "room_soak_storage_invalid"),
        "sqlite_integrity": integrity,
    }
    return {
        "counts": counts,
        "concurrency": concurrency,
        "latency_samples": latency_samples,
        "violations": violations,
        "residual": residual,
        "storage": storage,
    }


def _normalize_live_extensions(evidence: Mapping[str, Any], profile: SoakProfile) -> dict[str, Any]:
    confirmed = evidence.get("provider_cost_confirmed")
    if not isinstance(confirmed, bool):
        raise RoomSoakChaosError("room_soak_provider_cost_confirmation_invalid")
    if profile.provider_cost_confirmation_required and not confirmed:
        raise RoomSoakChaosError("room_soak_provider_cost_confirmation_required")
    monotonic_elapsed_ms = _count(
        evidence.get("monotonic_elapsed_ms"), "room_soak_monotonic_elapsed_invalid"
    )
    if monotonic_elapsed_ms > _MAX_LATENCY_MS:
        raise RoomSoakChaosError("room_soak_monotonic_elapsed_invalid")
    resources_raw = _exact_mapping(
        evidence.get("resources"), _RESOURCE_KEYS, "room_soak_resources_invalid"
    )
    resources = {
        key: _count(resources_raw.get(key), "room_soak_resources_invalid") for key in _RESOURCE_KEYS
    }
    browser_raw = _exact_mapping(
        evidence.get("browser"), _BROWSER_KEYS, "room_soak_browser_invalid"
    )
    browser = {
        key: _count(browser_raw.get(key), "room_soak_browser_invalid") for key in _BROWSER_KEYS
    }
    worktree_raw = _exact_mapping(
        evidence.get("worktree"), _WORKTREE_KEYS, "room_soak_worktree_invalid"
    )
    worktree: dict[str, str] = {}
    for key in _WORKTREE_KEYS:
        value = worktree_raw.get(key)
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise RoomSoakChaosError("room_soak_worktree_invalid")
        worktree[key] = value
    memory_raw = _exact_mapping(evidence.get("memory"), _MEMORY_KEYS, "room_soak_memory_invalid")
    memory_enabled = memory_raw.get("enabled")
    if not isinstance(memory_enabled, bool) or memory_enabled is not profile.memory_recovery:
        raise RoomSoakChaosError("room_soak_memory_invalid")
    memory: dict[str, int | bool] = {"enabled": memory_enabled}
    for key in _MEMORY_KEYS - {"enabled"}:
        memory[key] = _count(memory_raw.get(key), "room_soak_memory_invalid")
    if not profile.memory_recovery and any(memory[key] != 0 for key in _MEMORY_KEYS - {"enabled"}):
        raise RoomSoakChaosError("room_soak_memory_invalid")
    events_value = evidence.get("chaos_events")
    if (
        isinstance(events_value, (str, bytes))
        or not isinstance(events_value, Sequence)
        or not 1 <= len(events_value) <= 64
    ):
        raise RoomSoakChaosError("room_soak_chaos_events_invalid")
    events: list[dict[str, Any]] = []
    for expected_seq, raw in enumerate(events_value, 1):
        event = _exact_mapping(raw, _EVENT_KEYS, "room_soak_chaos_events_invalid")
        seq = _count(event.get("seq"), "room_soak_chaos_events_invalid")
        if seq != expected_seq:
            raise RoomSoakChaosError("room_soak_chaos_events_invalid")
        kind = event.get("kind")
        if not isinstance(kind, str) or kind not in _EVENT_REASON_BY_KIND:
            raise RoomSoakChaosError("room_soak_chaos_events_invalid")
        reason_code = event.get("reason_code")
        if reason_code != _EVENT_REASON_BY_KIND[kind]:
            raise RoomSoakChaosError("room_soak_chaos_events_invalid")
        recovery = event.get("recovery_ms")
        if recovery is not None:
            recovery = _count(recovery, "room_soak_chaos_events_invalid")
            if recovery > _MAX_LATENCY_MS:
                raise RoomSoakChaosError("room_soak_chaos_events_invalid")
        counts: dict[str, int | None] = {}
        for key in ("runner_count", "mcp_count", "active_delivery_count"):
            value = event.get(key)
            counts[key] = None if value is None else _count(value, "room_soak_chaos_events_invalid")
        booleans: dict[str, bool] = {}
        for key in ("managed_reconcile", "recovery_wave_settled"):
            value = event.get(key)
            if not isinstance(value, bool):
                raise RoomSoakChaosError("room_soak_chaos_events_invalid")
            booleans[key] = value
        events.append(
            {
                "seq": seq,
                "kind": kind,
                "reason_code": reason_code,
                "offset_ms": _count(event.get("offset_ms"), "room_soak_chaos_events_invalid"),
                "recovery_ms": recovery,
                **counts,
                **booleans,
            }
        )
    return {
        "provider_cost_confirmed": confirmed,
        "monotonic_elapsed_ms": monotonic_elapsed_ms,
        "resources": resources,
        "browser": browser,
        "worktree": worktree,
        "memory": memory,
        "chaos_events": events,
    }


def _gate(
    gate_id: str,
    passed: bool | None,
    observed: int | str | None,
    limit: int | str | None,
) -> dict[str, Any]:
    status = "not_applicable" if passed is None else "passed" if passed else "failed"
    return {
        "gate_id": gate_id,
        "status": status,
        "observed": observed,
        "limit": limit,
        "reason_code": f"room_soak_{gate_id}_{status}",
    }


def _gates(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    profile = get_soak_profile(str(result["profile_id"]))
    counts = result["counts"]
    latency = result["latency_ms"]
    resources = result["resources"]
    browser = result["browser"]
    worktree = result["worktree"]
    events = result["chaos_events"]
    memory = result["memory"]
    expected_correlations = profile.room_count * profile.human_turns_per_room
    gates = [
        _gate(
            "correlation_count",
            counts["correlations"] == expected_correlations,
            counts["correlations"],
            expected_correlations,
        ),
        _gate(
            "all_correlations_settled",
            counts["settled_correlations"] == counts["correlations"]
            and counts["unsettled_correlation"] == 0,
            counts["settled_correlations"],
            counts["correlations"],
        ),
        _gate(
            "post_count_consistent",
            counts["human_posts"] == counts["correlations"],
            counts["human_posts"],
            counts["correlations"],
        ),
        _gate(
            "attempt_count_consistent",
            counts["attempts"] == counts["root_attempts"] + counts["peer_attempts"],
            counts["root_attempts"] + counts["peer_attempts"],
            counts["attempts"],
        ),
        _gate(
            "root_attempt_coverage",
            counts["root_attempts"] >= counts["correlations"] * profile.agents_per_room
            and counts["outcomes"] >= counts["correlations"] * profile.agents_per_room,
            min(counts["root_attempts"], counts["outcomes"]),
            counts["correlations"] * profile.agents_per_room,
        ),
        _gate(
            "outcome_count_consistent",
            counts["outcomes"] <= counts["attempts"]
            and counts["outcomes"] == counts["respond"] + counts["noop"] + counts["other_outcomes"],
            counts["respond"] + counts["noop"] + counts["other_outcomes"],
            counts["outcomes"],
        ),
        _gate(
            "skill_decision_evidence",
            counts["skill_decisions"] == counts["attempts"],
            counts["skill_decisions"],
            counts["attempts"],
        ),
        _gate(
            "duplicate_outcome_zero",
            counts["duplicate_outcome"] == 0,
            counts["duplicate_outcome"],
            0,
        ),
        _gate(
            "cross_room_identity_zero",
            counts["cross_room_identity"] == 0,
            counts["cross_room_identity"],
            0,
        ),
        _gate(
            "cross_room_causality_zero",
            counts["cross_room_causality"] == 0,
            counts["cross_room_causality"],
            0,
        ),
        _gate(
            "provider_orphans_zero", counts["provider_orphans"] == 0, counts["provider_orphans"], 0
        ),
        _gate(
            "residual_zero",
            all(
                counts[key] == 0
                for key in (
                    "live_leases",
                    "cleanup_pending",
                    "recovery_pending",
                    "exhausted",
                    "incomplete_attempts",
                )
            ),
            sum(
                counts[key]
                for key in (
                    "live_leases",
                    "cleanup_pending",
                    "recovery_pending",
                    "exhausted",
                    "incomplete_attempts",
                )
            ),
            0,
        ),
        _gate(
            "active_delivery_limit",
            counts["max_active_deliveries"] <= 4,
            counts["max_active_deliveries"],
            4,
        ),
        _gate(
            "concurrent_posts_observed",
            counts["max_active_posts"] >= 2,
            counts["max_active_posts"],
            2,
        ),
        _gate(
            "overlapping_correlations_observed",
            counts["queued_correlations_before_host"] >= 2,
            counts["queued_correlations_before_host"],
            2,
        ),
        _gate(
            "all_rooms_first_claimed",
            counts["rooms_first_claimed"] == profile.room_count,
            counts["rooms_first_claimed"],
            profile.room_count,
        ),
        _gate(
            "first_claim_evidence",
            latency["post_to_claim"]["count"] == counts["correlations"],
            latency["post_to_claim"]["count"],
            counts["correlations"],
        ),
        _gate(
            "first_claim_deadline",
            latency["post_to_claim"]["max"] is not None
            and latency["post_to_claim"]["max"] <= 240_000,
            latency["post_to_claim"]["max"],
            240_000,
        ),
        _gate(
            "settle_evidence",
            latency["post_to_settled"]["count"] == counts["correlations"],
            latency["post_to_settled"]["count"],
            counts["correlations"],
        ),
        _gate(
            "outcome_latency_evidence",
            latency["post_to_outcome"]["count"] == counts["correlations"],
            latency["post_to_outcome"]["count"],
            counts["correlations"],
        ),
        _gate(
            "sqlite_integrity",
            resources["sqlite_integrity"] == "ok",
            resources["sqlite_integrity"],
            "ok",
        ),
    ]
    if profile.max_attempts is not None:
        gates.append(
            _gate(
                "attempt_budget",
                counts["attempts"] <= profile.max_attempts,
                counts["attempts"],
                profile.max_attempts,
            )
        )
    else:
        gates.append(_gate("attempt_budget", None, counts["attempts"], None))
    if profile.minimum_duration_s:
        elapsed_ms = result["monotonic_elapsed_ms"]
        gates.append(
            _gate(
                "minimum_duration",
                elapsed_ms is not None
                and elapsed_ms >= profile.minimum_duration_s * 1000
                and result["duration_ms"] >= profile.minimum_duration_s * 1000,
                elapsed_ms,
                profile.minimum_duration_s * 1000,
            )
        )
    else:
        gates.append(_gate("minimum_duration", None, result["duration_ms"], None))

    first_p95 = latency["settle_first_half"]["p95"]
    second_p95 = latency["settle_second_half"]["p95"]
    stable = (
        first_p95 is not None
        and second_p95 is not None
        and second_p95 <= int(first_p95 * 2.5 + 60_000)
    )
    gates.append(
        _gate(
            "settle_latency_stability",
            stable,
            second_p95,
            int(first_p95 * 2.5 + 60_000) if first_p95 is not None else None,
        )
    )

    live = profile.transport == "codex"
    if live:
        expected_faults = (
            ("memoryos_sigkill",)
            if profile.memory_recovery
            else ("codex_app_server_sigkill", "runner_sigkill")
        )
        observed_faults = tuple(event["kind"] for event in events)
        recovery_complete = bool(events) and all(
            event["recovery_ms"] is not None for event in events
        )
        recovery_max = (
            max(int(event["recovery_ms"]) for event in events) if recovery_complete else None
        )
        topology_complete = bool(events) and all(
            event["runner_count"] == 1 and event["mcp_count"] == 1 for event in events
        )
        fault_preconditions = (
            len(events) == len(expected_faults)
            and all(event["active_delivery_count"] is not None for event in events)
            and (
                profile.memory_recovery
                or (
                    int(events[0]["active_delivery_count"]) >= 1
                    and int(events[1]["active_delivery_count"]) >= 2
                )
            )
        )
        reconcile_proven = len(events) == len(expected_faults) and (
            events[0]["managed_reconcile"] is True
            if profile.memory_recovery
            else events[0]["managed_reconcile"] is False and events[1]["managed_reconcile"] is True
        )
        recovery_wave_proven = (
            len(events) == len(expected_faults) and events[-1]["recovery_wave_settled"] is True
        )
        rss_growth = resources["rss_growth_bytes"]
        rss_limit = resources["rss_growth_limit_bytes"]
        gates.extend(
            [
                _gate(
                    "fault_recovery_deadline",
                    recovery_max is not None and recovery_max <= 45_000,
                    recovery_max,
                    45_000,
                ),
                _gate(
                    "fault_sequence",
                    observed_faults == expected_faults,
                    len(observed_faults),
                    len(expected_faults),
                ),
                _gate(
                    "fault_preconditions",
                    fault_preconditions,
                    (
                        events[-1]["active_delivery_count"]
                        if len(events) == len(expected_faults)
                        else None
                    ),
                    2 if not profile.memory_recovery else 0,
                ),
                _gate(
                    "managed_reconcile_observed",
                    reconcile_proven,
                    int(reconcile_proven),
                    1,
                ),
                _gate(
                    "recovery_wave_settled",
                    recovery_wave_proven,
                    int(recovery_wave_proven),
                    1,
                ),
                _gate(
                    "single_runner_final",
                    topology_complete,
                    events[-1]["runner_count"] if events else None,
                    1,
                ),
                _gate(
                    "single_mcp_final",
                    topology_complete,
                    events[-1]["mcp_count"] if events else None,
                    1,
                ),
                _gate("fd_growth_limit", resources["fd_delta"] <= 16, resources["fd_delta"], 16),
                _gate("rss_growth_limit", rss_growth <= rss_limit, rss_growth, rss_limit),
                _gate(
                    "browser_console_clean",
                    browser["console_errors"] == 0 and browser["page_errors"] == 0,
                    browser["console_errors"] + browser["page_errors"],
                    0,
                ),
                _gate(
                    "browser_refresh_observed", browser["refreshes"] > 0, browser["refreshes"], 1
                ),
                _gate(
                    "worktree_unchanged",
                    worktree["before_digest"] == worktree["after_digest"],
                    worktree["after_digest"],
                    worktree["before_digest"],
                ),
            ]
        )
        if profile.memory_recovery:
            gates.extend(
                [
                    _gate("memory_enabled", memory["enabled"] is True, 1, 1),
                    _gate(
                        "memory_restart_observed",
                        memory["restart_count"] >= 1,
                        memory["restart_count"],
                        1,
                    ),
                    _gate(
                        "memory_outbox_replayed",
                        memory["outbox_delivered"] > 0,
                        memory["outbox_delivered"],
                        1,
                    ),
                    _gate(
                        "memory_outbox_clean",
                        memory["outbox_pending"] == 0 and memory["outbox_conflict"] == 0,
                        memory["outbox_pending"] + memory["outbox_conflict"],
                        0,
                    ),
                    _gate(
                        "memory_recall_observed",
                        memory["recall_receipts"] > 0 and memory["recall_source_refs"] > 0,
                        memory["recall_source_refs"],
                        1,
                    ),
                ]
            )
        else:
            for gate_id in (
                "memory_enabled",
                "memory_restart_observed",
                "memory_outbox_replayed",
                "memory_outbox_clean",
                "memory_recall_observed",
            ):
                gates.append(_gate(gate_id, None, None, None))
    else:
        for gate_id in (
            "fault_recovery_deadline",
            "single_runner_final",
            "single_mcp_final",
            "fd_growth_limit",
            "rss_growth_limit",
            "browser_console_clean",
            "browser_refresh_observed",
            "worktree_unchanged",
            "fault_sequence",
            "fault_preconditions",
            "managed_reconcile_observed",
            "recovery_wave_settled",
            "memory_enabled",
            "memory_restart_observed",
            "memory_outbox_replayed",
            "memory_outbox_clean",
            "memory_recall_observed",
        ):
            gates.append(_gate(gate_id, None, None, None))
    return gates


def build_soak_result(
    *,
    profile: SoakProfile,
    evidence: Mapping[str, Any],
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    if not isinstance(profile, SoakProfile) or get_soak_profile(profile.profile_id) != profile:
        raise RoomSoakChaosError("room_soak_profile_invalid")
    if not isinstance(evidence, Mapping):
        raise RoomSoakChaosError("room_soak_evidence_invalid")
    started, started_dt = _timestamp(started_at, "room_soak_started_at_invalid")
    finished, finished_dt = _timestamp(finished_at, "room_soak_finished_at_invalid")
    duration_ms = int(round((finished_dt - started_dt).total_seconds() * 1000))
    if duration_ms < 0:
        raise RoomSoakChaosError("room_soak_time_order_invalid")
    live = profile.transport == "codex"
    normalized = _normalize_base_evidence(profile, evidence, live=live)
    extensions = _normalize_live_extensions(evidence, profile) if live else None
    samples = normalized["latency_samples"]
    settle_samples = samples["post_to_settled"]
    split = (len(settle_samples) + 1) // 2
    counts = {
        **normalized["counts"],
        **normalized["concurrency"],
        **normalized["violations"],
        **normalized["residual"],
    }
    resources: dict[str, Any] = {
        **normalized["storage"],
        "rss_warmup_median_bytes": None,
        "rss_steady_state_max_bytes": None,
        "rss_growth_bytes": None,
        "rss_growth_limit_bytes": None,
        "fd_warmup": None,
        "fd_steady_state_max": None,
        "fd_delta": None,
        "process_count_max": None,
    }
    if extensions is not None:
        live_resources = extensions["resources"]
        rss_growth = max(
            0,
            live_resources["rss_steady_state_max_bytes"]
            - live_resources["rss_warmup_median_bytes"],
        )
        resources.update(
            {
                **live_resources,
                "rss_growth_bytes": rss_growth,
                "rss_growth_limit_bytes": max(
                    live_resources["rss_warmup_median_bytes"] // 2,
                    128 * 1024 * 1024,
                ),
                "fd_delta": max(
                    0,
                    live_resources["fd_steady_state_max"] - live_resources["fd_warmup"],
                ),
            }
        )
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    run_id = (
        "soak_"
        + hashlib.sha256(
            f"{profile.profile_id}\0{started}\0{finished}\0{canonical}".encode()
        ).hexdigest()[:32]
    )
    result: dict[str, Any] = {
        "schema_version": SOAK_RESULT_SCHEMA,
        "run_id": run_id,
        "profile_id": profile.profile_id,
        "status": "failed",
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "monotonic_elapsed_ms": (
            extensions["monotonic_elapsed_ms"] if extensions is not None else None
        ),
        "configuration": _configuration(profile),
        "counts": counts,
        "latency_ms": {
            **{key: _summary(values) for key, values in samples.items()},
            "settle_first_half": _summary(settle_samples[:split]),
            "settle_second_half": _summary(settle_samples[split:]),
        },
        "resources": resources,
        "chaos_events": extensions["chaos_events"] if extensions else [],
        "browser": (
            {**extensions["browser"], "applicable": True}
            if extensions
            else {"refreshes": 0, "console_errors": 0, "page_errors": 0, "applicable": False}
        ),
        "worktree": (
            {**extensions["worktree"], "applicable": True}
            if extensions
            else {"before_digest": None, "after_digest": None, "applicable": False}
        ),
        "memory": (
            dict(extensions["memory"])
            if extensions
            else {
                "enabled": False,
                "restart_count": 0,
                "outbox_delivered": 0,
                "outbox_pending": 0,
                "outbox_conflict": 0,
                "recall_receipts": 0,
                "recall_source_refs": 0,
            }
        ),
        "provider_cost_confirmed": (extensions["provider_cost_confirmed"] if extensions else False),
        "gates": [],
        "proof_boundary": SOAK_PROOF_BOUNDARY,
    }
    result["gates"] = _gates(result)
    result["status"] = (
        "passed" if all(gate["status"] != "failed" for gate in result["gates"]) else "failed"
    )
    return validate_soak_result(result)


def _validate_summary(value: object) -> dict[str, int | None]:
    raw = _exact_mapping(
        value, frozenset({"count", "p50", "p95", "max"}), "room_soak_result_invalid"
    )
    count = _count(raw.get("count"), "room_soak_result_invalid")
    values: dict[str, int | None] = {"count": count}
    for key in ("p50", "p95", "max"):
        item = raw.get(key)
        values[key] = None if item is None else _count(item, "room_soak_result_invalid")
    if count == 0:
        if any(values[key] is not None for key in ("p50", "p95", "max")):
            raise RoomSoakChaosError("room_soak_result_invalid")
    elif (
        values["p50"] is None
        or values["p95"] is None
        or values["max"] is None
        or not values["p50"] <= values["p95"] <= values["max"]
    ):
        raise RoomSoakChaosError("room_soak_result_invalid")
    return values


def _validate_result_extensions(
    payload: Mapping[str, Any], profile: SoakProfile
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, int | bool],
]:
    live = profile.transport == "codex"
    numeric_resource_keys = _RESOURCE_KEYS | {
        "rss_growth_bytes",
        "rss_growth_limit_bytes",
        "fd_delta",
    }
    raw_resources = _exact_mapping(
        payload.get("resources"),
        frozenset(_STORAGE_KEYS | numeric_resource_keys),
        "room_soak_result_invalid",
    )
    integrity = raw_resources.get("sqlite_integrity")
    if integrity not in {"ok", "failed"}:
        raise RoomSoakChaosError("room_soak_result_invalid")
    resources: dict[str, Any] = {
        "database_bytes": _count(raw_resources.get("database_bytes"), "room_soak_result_invalid"),
        "wal_bytes": _count(raw_resources.get("wal_bytes"), "room_soak_result_invalid"),
        "sqlite_integrity": integrity,
    }
    for key in numeric_resource_keys:
        value = raw_resources.get(key)
        if live:
            resources[key] = _count(value, "room_soak_result_invalid")
        elif value is not None:
            raise RoomSoakChaosError("room_soak_result_invalid")
        else:
            resources[key] = None
    if live:
        expected_rss_growth = max(
            0,
            resources["rss_steady_state_max_bytes"] - resources["rss_warmup_median_bytes"],
        )
        expected_rss_limit = max(
            resources["rss_warmup_median_bytes"] // 2,
            128 * 1024 * 1024,
        )
        expected_fd_delta = max(0, resources["fd_steady_state_max"] - resources["fd_warmup"])
        if (
            resources["rss_growth_bytes"] != expected_rss_growth
            or resources["rss_growth_limit_bytes"] != expected_rss_limit
            or resources["fd_delta"] != expected_fd_delta
        ):
            raise RoomSoakChaosError("room_soak_result_invalid")

    raw_browser = _exact_mapping(
        payload.get("browser"),
        frozenset({*_BROWSER_KEYS, "applicable"}),
        "room_soak_result_invalid",
    )
    if raw_browser.get("applicable") is not live:
        raise RoomSoakChaosError("room_soak_result_invalid")
    browser = {
        key: _count(raw_browser.get(key), "room_soak_result_invalid") for key in _BROWSER_KEYS
    }
    browser["applicable"] = live

    raw_worktree = _exact_mapping(
        payload.get("worktree"),
        frozenset({*_WORKTREE_KEYS, "applicable"}),
        "room_soak_result_invalid",
    )
    if raw_worktree.get("applicable") is not live:
        raise RoomSoakChaosError("room_soak_result_invalid")
    worktree: dict[str, Any] = {"applicable": live}
    for key in _WORKTREE_KEYS:
        value = raw_worktree.get(key)
        if live:
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise RoomSoakChaosError("room_soak_result_invalid")
            worktree[key] = value
        elif value is not None:
            raise RoomSoakChaosError("room_soak_result_invalid")
        else:
            worktree[key] = None

    raw_memory = _exact_mapping(payload.get("memory"), _MEMORY_KEYS, "room_soak_result_invalid")
    enabled = raw_memory.get("enabled")
    if not isinstance(enabled, bool) or enabled is not profile.memory_recovery:
        raise RoomSoakChaosError("room_soak_result_invalid")
    memory: dict[str, int | bool] = {"enabled": enabled}
    for key in _MEMORY_KEYS - {"enabled"}:
        memory[key] = _count(raw_memory.get(key), "room_soak_result_invalid")
    if not profile.memory_recovery and any(memory[key] != 0 for key in _MEMORY_KEYS - {"enabled"}):
        raise RoomSoakChaosError("room_soak_result_invalid")

    raw_events = payload.get("chaos_events")
    if isinstance(raw_events, (str, bytes)) or not isinstance(raw_events, Sequence):
        raise RoomSoakChaosError("room_soak_result_invalid")
    if (live and not 1 <= len(raw_events) <= 64) or (not live and len(raw_events) != 0):
        raise RoomSoakChaosError("room_soak_result_invalid")
    events: list[dict[str, Any]] = []
    for expected_seq, raw in enumerate(raw_events, 1):
        event = _exact_mapping(raw, _EVENT_KEYS, "room_soak_result_invalid")
        seq = _count(event.get("seq"), "room_soak_result_invalid")
        if seq != expected_seq:
            raise RoomSoakChaosError("room_soak_result_invalid")
        kind = event.get("kind")
        if not isinstance(kind, str) or kind not in _EVENT_REASON_BY_KIND:
            raise RoomSoakChaosError("room_soak_result_invalid")
        reason_code = event.get("reason_code")
        if reason_code != _EVENT_REASON_BY_KIND[kind]:
            raise RoomSoakChaosError("room_soak_result_invalid")
        recovery = event.get("recovery_ms")
        if recovery is not None:
            recovery = _count(recovery, "room_soak_result_invalid")
        normalized_event: dict[str, Any] = {
            "seq": seq,
            "kind": kind,
            "reason_code": reason_code,
            "offset_ms": _count(event.get("offset_ms"), "room_soak_result_invalid"),
            "recovery_ms": recovery,
        }
        for key in ("runner_count", "mcp_count", "active_delivery_count"):
            value = event.get(key)
            normalized_event[key] = (
                None if value is None else _count(value, "room_soak_result_invalid")
            )
        for key in ("managed_reconcile", "recovery_wave_settled"):
            value = event.get(key)
            if not isinstance(value, bool):
                raise RoomSoakChaosError("room_soak_result_invalid")
            normalized_event[key] = value
        events.append(normalized_event)
    return resources, events, browser, worktree, memory


def validate_soak_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise RoomSoakChaosError("room_soak_result_invalid")
    expected = {
        "schema_version",
        "run_id",
        "profile_id",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "monotonic_elapsed_ms",
        "configuration",
        "counts",
        "latency_ms",
        "resources",
        "chaos_events",
        "browser",
        "worktree",
        "memory",
        "provider_cost_confirmed",
        "gates",
        "proof_boundary",
    }
    if (
        set(payload) != expected
        or payload.get("schema_version") != SOAK_RESULT_SCHEMA
        or payload.get("proof_boundary") != SOAK_PROOF_BOUNDARY
    ):
        raise RoomSoakChaosError("room_soak_result_invalid")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or re.fullmatch(r"soak_[0-9a-f]{32}", run_id) is None:
        raise RoomSoakChaosError("room_soak_result_invalid")
    profile = get_soak_profile(str(payload.get("profile_id")))
    if payload.get("configuration") != _configuration(profile):
        raise RoomSoakChaosError("room_soak_result_invalid")
    started, started_dt = _timestamp(payload.get("started_at"), "room_soak_result_invalid")
    finished, finished_dt = _timestamp(payload.get("finished_at"), "room_soak_result_invalid")
    duration = _count(payload.get("duration_ms"), "room_soak_result_invalid")
    if duration != int(round((finished_dt - started_dt).total_seconds() * 1000)):
        raise RoomSoakChaosError("room_soak_result_invalid")
    if payload.get("started_at") != started or payload.get("finished_at") != finished:
        raise RoomSoakChaosError("room_soak_result_invalid")
    monotonic_elapsed = payload.get("monotonic_elapsed_ms")
    if profile.transport == "codex":
        monotonic_elapsed = _count(monotonic_elapsed, "room_soak_result_invalid")
        if monotonic_elapsed > _MAX_LATENCY_MS:
            raise RoomSoakChaosError("room_soak_result_invalid")
    elif monotonic_elapsed is not None:
        raise RoomSoakChaosError("room_soak_result_invalid")
    if payload.get("status") not in {"passed", "failed"}:
        raise RoomSoakChaosError("room_soak_result_invalid")
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        raise RoomSoakChaosError("room_soak_result_invalid")
    expected_count_keys = (
        _COUNT_KEYS | _CONCURRENCY_KEYS | _VIOLATION_KEYS | {"provider_orphans"} | _RESIDUAL_KEYS
    )
    if set(counts) != expected_count_keys:
        raise RoomSoakChaosError("room_soak_result_invalid")
    normalized_counts = {
        key: _count(counts.get(key), "room_soak_result_invalid") for key in expected_count_keys
    }
    latency = payload.get("latency_ms")
    expected_latency = _LATENCY_KEYS | {"settle_first_half", "settle_second_half"}
    if not isinstance(latency, Mapping) or set(latency) != expected_latency:
        raise RoomSoakChaosError("room_soak_result_invalid")
    normalized_latency = {key: _validate_summary(latency[key]) for key in expected_latency}
    resources, events, browser, worktree, memory = _validate_result_extensions(payload, profile)
    confirmed = payload.get("provider_cost_confirmed")
    if not isinstance(confirmed, bool) or (
        profile.provider_cost_confirmation_required and not confirmed
    ):
        raise RoomSoakChaosError("room_soak_result_invalid")
    normalized = dict(payload)
    normalized["counts"] = normalized_counts
    normalized["latency_ms"] = normalized_latency
    normalized["resources"] = resources
    normalized["chaos_events"] = events
    normalized["browser"] = browser
    normalized["worktree"] = worktree
    normalized["memory"] = memory
    normalized["gates"] = _gates(normalized)
    expected_status = (
        "passed" if all(gate["status"] != "failed" for gate in normalized["gates"]) else "failed"
    )
    if payload.get("gates") != normalized["gates"] or payload.get("status") != expected_status:
        raise RoomSoakChaosError("room_soak_result_gates_invalid")
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES:
        raise RoomSoakChaosError("room_soak_result_too_large")
    return json.loads(encoded)


def evaluate_soak_result(payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    normalized = validate_soak_result(payload)
    failed = tuple(
        str(gate["gate_id"]) for gate in normalized["gates"] if gate["status"] == "failed"
    )
    return not failed, failed


def write_soak_result(path: Path | str, payload: Mapping[str, Any]) -> None:
    normalized = validate_soak_result(payload)
    target = Path(path)
    if not target.name or target.name in {".", ".."}:
        raise RoomSoakChaosError("room_soak_result_path_unsafe")
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
        raise RoomSoakChaosError("room_soak_result_path_unsafe") from exc
    temporary = f".{target.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    encoded = (json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        try:
            existing = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise RoomSoakChaosError("room_soak_result_path_unsafe")
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
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary,
            target.name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        os.fsync(directory)
    except RoomSoakChaosError:
        raise
    except OSError as exc:
        raise RoomSoakChaosError("room_soak_result_write_failed") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        finally:
            os.close(directory)


__all__ = [
    "SOAK_RESULT_SCHEMA",
    "SoakProfile",
    "get_soak_profile",
    "build_soak_result",
    "validate_soak_result",
    "evaluate_soak_result",
    "write_soak_result",
]
