from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from xmuse_core.chat.room_soak_chaos import (
    SOAK_RESULT_SCHEMA,
    RoomSoakChaosError,
    build_soak_result,
    evaluate_soak_result,
    get_soak_profile,
    validate_soak_result,
    write_soak_result,
)


def _configuration(profile_id: str) -> dict[str, int]:
    profile = get_soak_profile(profile_id)
    return {
        "room_count": profile.room_count,
        "agents_per_room": profile.agents_per_room,
        "human_turns_per_room": profile.human_turns_per_room,
        "max_concurrent_provider_deliveries": 4,
    }


def _base_evidence(profile_id: str, *, live: bool) -> dict[str, object]:
    profile = get_soak_profile(profile_id)
    correlations = profile.room_count * profile.human_turns_per_room
    agents = correlations * profile.agents_per_room
    evidence: dict[str, object] = {
        "schema_version": ("room_soak_live_evidence/v1" if live else "room_soak_ci_evidence/v1"),
        "profile_id": profile_id,
        "configuration": _configuration(profile_id),
        "counts": {
            "human_posts": correlations,
            "correlations": correlations,
            "attempts": agents,
            "outcomes": agents,
            "root_attempts": agents,
            "peer_attempts": 0,
            "respond": correlations,
            "noop": agents - correlations,
            "other_outcomes": 0,
            "skill_decisions": agents,
            "settled_correlations": correlations,
        },
        "concurrency": {
            "max_active_deliveries": 4,
            "rooms_first_claimed": profile.room_count,
            "attempts_until_all_rooms_first_claimed": profile.room_count,
            "max_active_posts": profile.room_count,
            "queued_correlations_before_host": profile.room_count,
        },
        "latency_samples_ms": {
            "post_to_claim": [
                {"ordinal": index + 1, "latency_ms": float(100 + index)}
                for index in range(correlations)
            ],
            "post_to_outcome": [
                {"ordinal": index + 1, "latency_ms": float(200 + index)}
                for index in range(correlations)
            ],
            "post_to_settled": [
                {"ordinal": index + 1, "latency_ms": float(300 + index)}
                for index in range(correlations)
            ],
        },
        "violations": {
            "duplicate_outcome": 0,
            "cross_room_identity": 0,
            "cross_room_causality": 0,
            "unsettled_correlation": 0,
        },
        "residual": {
            "live_leases": 0,
            "cleanup_pending": 0,
            "recovery_pending": 0,
            "exhausted": 0,
            "incomplete_attempts": 0,
        },
        "storage": {
            "database_bytes": 1024,
            "wal_bytes": 256,
            "sqlite_integrity": "ok",
        },
    }
    if live:
        violations = evidence["violations"]
        assert isinstance(violations, dict)
        violations["provider_orphans"] = 0
        evidence.update(
            {
                "provider_cost_confirmed": profile.provider_cost_confirmation_required,
                "monotonic_elapsed_ms": max(3_600_000, profile.minimum_duration_s * 1000),
                "resources": {
                    "rss_warmup_median_bytes": 256 * 1024 * 1024,
                    "rss_steady_state_max_bytes": 384 * 1024 * 1024,
                    "fd_warmup": 40,
                    "fd_steady_state_max": 56,
                    "process_count_max": 12,
                },
                "browser": {"refreshes": 1, "console_errors": 0, "page_errors": 0},
                "worktree": {
                    "before_digest": "sha256:" + "a" * 64,
                    "after_digest": "sha256:" + "a" * 64,
                },
                "memory": (
                    {
                        "enabled": True,
                        "restart_count": 1,
                        "outbox_delivered": 8,
                        "outbox_pending": 0,
                        "outbox_conflict": 0,
                        "recall_receipts": 4,
                        "recall_source_refs": 2,
                    }
                    if profile.memory_recovery
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
            }
        )
        evidence["chaos_events"] = (
            [
                {
                    "seq": 1,
                    "kind": "codex_app_server_sigkill",
                    "reason_code": "codex_app_server_cleanup_confirmed",
                    "offset_ms": 1_000,
                    "recovery_ms": 10_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 1,
                    "managed_reconcile": False,
                    "recovery_wave_settled": True,
                },
                {
                    "seq": 2,
                    "kind": "runner_sigkill",
                    "reason_code": "runner_reconciled",
                    "offset_ms": 1_440_000,
                    "recovery_ms": 45_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 2,
                    "managed_reconcile": True,
                    "recovery_wave_settled": True,
                },
                {
                    "seq": 3,
                    "kind": "memoryos_sigkill",
                    "reason_code": "memoryos_reconciled",
                    "offset_ms": 2_880_000,
                    "recovery_ms": 45_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 1,
                    "managed_reconcile": True,
                    "recovery_wave_settled": True,
                },
                {
                    "seq": 4,
                    "kind": "agent_stream_cache_delete",
                    "reason_code": "agent_stream_cache_epoch_rotated",
                    "offset_ms": 4_320_000,
                    "recovery_ms": 45_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 0,
                    "managed_reconcile": True,
                    "recovery_wave_settled": True,
                },
            ]
            if profile_id == "live-endurance"
            else [
                {
                    "seq": 1,
                    "kind": "memoryos_sigkill",
                    "reason_code": "memoryos_reconciled",
                    "offset_ms": 1_000,
                    "recovery_ms": 45_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 0,
                    "managed_reconcile": True,
                    "recovery_wave_settled": True,
                }
            ]
            if profile.memory_recovery
            else [
                {
                    "seq": 1,
                    "kind": "codex_app_server_sigkill",
                    "reason_code": "codex_app_server_cleanup_confirmed",
                    "offset_ms": 1_000,
                    "recovery_ms": 10_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 1,
                    "managed_reconcile": False,
                    "recovery_wave_settled": False,
                },
                {
                    "seq": 2,
                    "kind": "runner_sigkill",
                    "reason_code": "runner_reconciled",
                    "offset_ms": 2_000,
                    "recovery_ms": 45_000,
                    "runner_count": 1,
                    "mcp_count": 1,
                    "active_delivery_count": 2,
                    "managed_reconcile": True,
                    "recovery_wave_settled": True,
                },
            ]
        )
    return evidence


def _build(profile_id: str, evidence: dict[str, object] | None = None) -> dict:
    profile = get_soak_profile(profile_id)
    duration = profile.minimum_duration_s if profile.minimum_duration_s else 120
    return build_soak_result(
        profile=profile,
        evidence=evidence or _base_evidence(profile_id, live=profile.transport == "codex"),
        started_at="2026-07-12T00:00:00Z",
        finished_at=f"2026-07-12T{duration // 3600:02d}:{duration % 3600 // 60:02d}:00Z",
    )


def test_fixed_profiles_match_the_cost_and_transport_contract() -> None:
    assert get_soak_profile("ci-sim").room_count == 12
    assert get_soak_profile("ci-sim").agents_per_room == 4
    assert get_soak_profile("ci-sim").human_turns_per_room == 20
    assert get_soak_profile("ci-sim").transport == "scripted"
    assert get_soak_profile("live-short").max_attempts == 48
    live = get_soak_profile("live-soak")
    assert (live.room_count, live.agents_per_room, live.human_turns_per_room) == (6, 2, 4)
    assert live.max_attempts == 128
    assert live.minimum_duration_s == 3600
    assert live.provider_cost_confirmation_required is True
    memory = get_soak_profile("memory-recovery")
    assert (memory.room_count, memory.agents_per_room, memory.human_turns_per_room) == (
        2,
        2,
        10,
    )
    assert memory.memory_recovery is True
    endurance = get_soak_profile("live-endurance")
    assert (endurance.room_count, endurance.agents_per_room, endurance.human_turns_per_room) == (
        8,
        2,
        5,
    )
    assert endurance.max_attempts == 192
    assert endurance.minimum_duration_s == 7200
    assert endurance.provider_cost_confirmation_required is True
    assert endurance.chaos_kinds == (
        "codex_app_server_sigkill",
        "runner_sigkill",
        "memoryos_sigkill",
        "agent_stream_cache_delete",
    )
    with pytest.raises(RoomSoakChaosError) as unknown:
        get_soak_profile("invented")
    assert unknown.value.code == "room_soak_profile_unknown"


def test_ci_evidence_builds_a_bounded_deterministic_pass_receipt() -> None:
    evidence = _base_evidence("ci-sim", live=False)
    first = _build("ci-sim", evidence)
    replay = _build("ci-sim", evidence)

    assert first == replay
    assert first["schema_version"] == SOAK_RESULT_SCHEMA
    assert first["status"] == "passed"
    assert first["run_id"].startswith("soak_")
    assert first["latency_ms"]["post_to_claim"] == {
        "count": 240,
        "p50": 219,
        "p95": 327,
        "max": 339,
    }
    assert first["resources"]["sqlite_integrity"] == "ok"
    assert first["browser"]["applicable"] is False
    assert evaluate_soak_result(first) == (True, ())
    encoded = json.dumps(first, sort_keys=True)
    assert len(encoded.encode()) < 64 * 1024
    for forbidden in ("message", "provider_output", "token", "session_binding", "/home/"):
        assert forbidden not in encoded


def test_builder_rejects_missing_unknown_and_wrong_profile_evidence() -> None:
    profile = get_soak_profile("ci-sim")
    missing = _base_evidence("ci-sim", live=False)
    missing.pop("storage")
    with pytest.raises(RoomSoakChaosError) as missing_error:
        build_soak_result(
            profile=profile,
            evidence=missing,
            started_at="2026-07-12T00:00:00Z",
            finished_at="2026-07-12T00:02:00Z",
        )
    assert missing_error.value.code == "room_soak_evidence_fields_invalid"

    unknown = _base_evidence("ci-sim", live=False)
    unknown["provider_output"] = "must not survive"
    with pytest.raises(RoomSoakChaosError):
        _build("ci-sim", unknown)

    mismatch = _base_evidence("ci-sim", live=False)
    mismatch["profile_id"] = "live-short"
    with pytest.raises(RoomSoakChaosError) as mismatch_error:
        _build("ci-sim", mismatch)
    assert mismatch_error.value.code == "room_soak_evidence_identity_invalid"


def test_live_result_enforces_every_resource_recovery_and_browser_gate() -> None:
    result = _build("live-short")
    assert result["status"] == "passed"
    assert result["resources"]["rss_growth_bytes"] == 128 * 1024 * 1024
    assert result["resources"]["rss_growth_limit_bytes"] == 128 * 1024 * 1024
    assert result["resources"]["fd_delta"] == 16
    assert result["chaos_events"][-1]["recovery_ms"] == 45_000
    assert evaluate_soak_result(result) == (True, ())


def test_failed_evidence_returns_stable_failed_gate_ids() -> None:
    evidence = _base_evidence("live-short", live=True)
    counts = evidence["counts"]
    concurrency = evidence["concurrency"]
    latency = evidence["latency_samples_ms"]
    violations = evidence["violations"]
    residual = evidence["residual"]
    resources = evidence["resources"]
    events = evidence["chaos_events"]
    browser = evidence["browser"]
    worktree = evidence["worktree"]
    assert all(
        isinstance(item, dict)
        for item in (
            counts,
            concurrency,
            latency,
            violations,
            residual,
            resources,
            browser,
            worktree,
        )
    )
    assert isinstance(events, list) and isinstance(events[0], dict)
    counts["settled_correlations"] = 7
    concurrency["max_active_deliveries"] = 5
    latency["post_to_claim"] = [
        {"ordinal": index + 1, "latency_ms": 240_001.0} for index in range(8)
    ]
    latency["post_to_settled"] = [
        {
            "ordinal": index + 1,
            "latency_ms": 1_000.0 if index < 4 else 63_000.0,
        }
        for index in range(8)
    ]
    violations["duplicate_outcome"] = 1
    violations["provider_orphans"] = 1
    residual["live_leases"] = 1
    resources["rss_steady_state_max_bytes"] = 500 * 1024 * 1024
    resources["fd_steady_state_max"] = 57
    events[-1]["recovery_ms"] = 45_001
    events[-1]["runner_count"] = 2
    browser["console_errors"] = 1
    worktree["after_digest"] = "sha256:" + "b" * 64

    result = _build("live-short", evidence)
    passed, failed = evaluate_soak_result(result)
    assert passed is False
    assert {
        "all_correlations_settled",
        "duplicate_outcome_zero",
        "provider_orphans_zero",
        "residual_zero",
        "active_delivery_limit",
        "first_claim_deadline",
        "settle_latency_stability",
        "fault_recovery_deadline",
        "single_runner_final",
        "fd_growth_limit",
        "rss_growth_limit",
        "browser_console_clean",
        "worktree_unchanged",
    }.issubset(failed)


def test_live_soak_requires_explicit_cost_confirmation_duration_and_attempt_budget() -> None:
    evidence = _base_evidence("live-soak", live=True)
    evidence["provider_cost_confirmed"] = False
    with pytest.raises(RoomSoakChaosError) as unconfirmed:
        _build("live-soak", evidence)
    assert unconfirmed.value.code == "room_soak_provider_cost_confirmation_required"

    evidence["provider_cost_confirmed"] = True
    profile = get_soak_profile("live-soak")
    short = build_soak_result(
        profile=profile,
        evidence=evidence,
        started_at="2026-07-12T00:00:00Z",
        finished_at="2026-07-12T00:59:59Z",
    )
    assert "minimum_duration" in evaluate_soak_result(short)[1]
    counts = evidence["counts"]
    assert isinstance(counts, dict)
    counts["attempts"] = 129
    over_budget = _build("live-soak", evidence)
    assert "attempt_budget" in evaluate_soak_result(over_budget)[1]


def test_live_endurance_requires_the_strict_four_fault_sequence_and_memory_recovery() -> None:
    passed = _build("live-endurance")
    assert passed["status"] == "passed"
    assert [event["kind"] for event in passed["chaos_events"]] == list(
        get_soak_profile("live-endurance").chaos_kinds
    )
    assert passed["memory"]["enabled"] is True
    assert passed["memory"]["outbox_delivered"] > 0
    assert passed["memory"]["recall_source_refs"] > 0
    assert {
        "endurance_provider_fault_precondition",
        "endurance_runner_fault_precondition",
        "endurance_memory_managed",
        "endurance_stream_cache_precondition",
        "minimum_duration",
        "attempt_budget",
        "memory_outbox_replayed",
        "memory_recall_observed",
    }.isdisjoint(set(evaluate_soak_result(passed)[1]))

    wrong = _base_evidence("live-endurance", live=True)
    events = wrong["chaos_events"]
    assert isinstance(events, list) and isinstance(events[3], dict)
    events[3]["active_delivery_count"] = 1
    result = _build("live-endurance", wrong)
    assert "fault_preconditions" in evaluate_soak_result(result)[1]

    reordered = _base_evidence("live-endurance", live=True)
    events = reordered["chaos_events"]
    assert isinstance(events, list) and isinstance(events[2], dict)
    events[2]["kind"] = "agent_stream_cache_delete"
    events[2]["reason_code"] = "agent_stream_cache_epoch_rotated"
    result = _build("live-endurance", reordered)
    assert "fault_sequence" in evaluate_soak_result(result)[1]

    unsettled_recovery = _base_evidence("live-endurance", live=True)
    events = unsettled_recovery["chaos_events"]
    assert isinstance(events, list) and isinstance(events[0], dict)
    events[0]["recovery_wave_settled"] = False
    result = _build("live-endurance", unsettled_recovery)
    assert "recovery_wave_settled" in evaluate_soak_result(result)[1]


def test_memory_recovery_requires_replay_recall_and_exact_fault_evidence() -> None:
    passed = _build("memory-recovery")
    assert passed["status"] == "passed"
    assert passed["memory"]["enabled"] is True

    evidence = _base_evidence("memory-recovery", live=True)
    memory = evidence["memory"]
    assert isinstance(memory, dict)
    memory["restart_count"] = 0
    memory["outbox_pending"] = 1
    memory["recall_source_refs"] = 0
    failed = _build("memory-recovery", evidence)
    assert {
        "memory_restart_observed",
        "memory_outbox_clean",
        "memory_recall_observed",
    }.issubset(evaluate_soak_result(failed)[1])

    wrong_fault = _base_evidence("memory-recovery", live=True)
    events = wrong_fault["chaos_events"]
    assert isinstance(events, list) and isinstance(events[0], dict)
    events[0]["kind"] = "runner_sigkill"
    events[0]["reason_code"] = "runner_reconciled"
    wrong_result = _build("memory-recovery", wrong_fault)
    assert "fault_sequence" in evaluate_soak_result(wrong_result)[1]


def test_validator_rejects_forged_gates_and_nested_private_fields() -> None:
    result = _build("live-short")
    forged = deepcopy(result)
    forged["status"] = "failed"
    with pytest.raises(RoomSoakChaosError) as forged_error:
        validate_soak_result(forged)
    assert forged_error.value.code == "room_soak_result_gates_invalid"

    private = deepcopy(result)
    private["resources"]["provider_output"] = "secret"
    with pytest.raises(RoomSoakChaosError):
        validate_soak_result(private)

    event_private = deepcopy(result)
    event_private["chaos_events"][0]["session_binding"] = "secret"
    with pytest.raises(RoomSoakChaosError):
        validate_soak_result(event_private)


def test_cross_field_chronology_and_fault_proof_cannot_be_omitted_or_reordered() -> None:
    evidence = _base_evidence("live-short", live=True)
    counts = evidence["counts"]
    latency = evidence["latency_samples_ms"]
    events = evidence["chaos_events"]
    assert isinstance(counts, dict) and isinstance(latency, dict)
    assert isinstance(events, list) and all(isinstance(event, dict) for event in events)
    counts.update(
        {
            "human_posts": 0,
            "attempts": 0,
            "outcomes": 0,
            "root_attempts": 0,
            "peer_attempts": 0,
            "respond": 0,
            "noop": 0,
            "other_outcomes": 0,
            "skill_decisions": 0,
        }
    )
    latency["post_to_outcome"] = []
    failed = _build("live-short", evidence)
    assert {
        "post_count_consistent",
        "root_attempt_coverage",
        "outcome_latency_evidence",
    }.issubset(evaluate_soak_result(failed)[1])

    missing_fault = _base_evidence("live-short", live=True)
    missing_events = missing_fault["chaos_events"]
    assert isinstance(missing_events, list) and isinstance(missing_events[0], dict)
    missing_events[0]["recovery_ms"] = None
    missing_events[0]["runner_count"] = None
    missing_events[0]["mcp_count"] = None
    missing_result = _build("live-short", missing_fault)
    assert {
        "fault_recovery_deadline",
        "single_runner_final",
        "single_mcp_final",
    }.issubset(evaluate_soak_result(missing_result)[1])

    reordered = _base_evidence("live-short", live=True)
    reordered_latency = reordered["latency_samples_ms"]
    assert isinstance(reordered_latency, dict)
    settled = reordered_latency["post_to_settled"]
    assert isinstance(settled, list)
    settled.reverse()
    with pytest.raises(RoomSoakChaosError) as chronology:
        _build("live-short", reordered)
    assert chronology.value.code == "room_soak_latency_invalid"


def test_live_soak_duration_uses_monotonic_evidence_and_reason_codes_are_closed() -> None:
    evidence = _base_evidence("live-soak", live=True)
    evidence["monotonic_elapsed_ms"] = 1
    result = _build("live-soak", evidence)
    assert "minimum_duration" in evaluate_soak_result(result)[1]

    unsafe = _base_evidence("live-short", live=True)
    events = unsafe["chaos_events"]
    assert isinstance(events, list) and isinstance(events[0], dict)
    events[0]["reason_code"] = "a" * 64
    with pytest.raises(RoomSoakChaosError) as rejected:
        _build("live-short", unsafe)
    assert rejected.value.code == "room_soak_chaos_events_invalid"


def test_write_result_is_atomic_private_and_revalidates(tmp_path: Path) -> None:
    result = _build("ci-sim")
    target = tmp_path / "soak-result.json"
    write_soak_result(target, result)

    assert validate_soak_result(json.loads(target.read_text(encoding="utf-8"))) == result
    assert os.stat(target).st_mode & 0o777 == 0o600
    target.unlink()
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(RoomSoakChaosError) as unsafe:
        write_soak_result(target, result)
    assert unsafe.value.code == "room_soak_result_path_unsafe"
