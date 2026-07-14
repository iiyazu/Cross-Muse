from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from xmuse_core.chat.room_goal_memory_soak import (
    MANIFEST_SCHEMA,
    RESULT_SCHEMA,
    GoalMemorySoakContractError,
    build_goal_memory_soak_result,
    evaluate_goal_memory_soak_result,
    validate_goal_memory_soak_manifest,
    validate_goal_memory_soak_result,
    write_goal_memory_soak_result,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _manifest() -> dict[str, object]:
    return {
        "schema_version": MANIFEST_SCHEMA,
        "profile_id": "live-goal-memory-soak",
        "seed": 1701,
        "xmuse_sha": "1" * 40,
        "memoryos_sha": "2" * 40,
        "codex_version": "0.144.0",
        "native_capability_descriptor_digest": DIGEST_A,
        "task_manifest_digest": DIGEST_B,
        "started_at": "2026-07-13T00:00:00.000Z",
        "finished_at": "2026-07-13T01:00:00.000Z",
    }


def _event(seq: int, kind: str, reason: str, *, active: int) -> dict[str, object]:
    return {
        "seq": seq,
        "kind": kind,
        "reason_code": reason,
        "recovery_ms": 20_000,
        "active_delivery_count": active,
        "runner_count": 1,
        "mcp_count": 1,
    }


def _evidence() -> dict[str, object]:
    samples = list(range(100, 116))
    return {
        "schema_version": "room_goal_memory_soak_evidence/v1",
        "monotonic_elapsed_ms": 3_600_000,
        "counts": {
            "correlations": 16,
            "settled_correlations": 16,
            "attempts": 32,
            "outcomes": 32,
            "duplicate_outcomes": 0,
            "cross_room_identity": 0,
            "cross_room_causality": 0,
            "cross_room_source": 0,
            "provider_orphans": 0,
            "live_leases": 0,
            "cleanup_pending": 0,
            "recovery_pending": 0,
            "exhausted": 0,
            "max_active_deliveries": 4,
        },
        "latency_samples_ms": {
            "post_to_claim": samples,
            "post_to_outcome": [value + 100 for value in samples],
            "post_to_settled": [value + 200 for value in samples],
        },
        "native": {
            "participant_count": 8,
            "settings_participants_covered": 8,
            "settings_assignment_digest": DIGEST_A,
            "distinct_settings_combinations": 2,
            "max_effort_observed": 1,
            "goal_auto_continuations": 1,
            "goal_terminal_state": "complete",
            "goal_hold_claim_violations": 0,
            "goal_resume_count": 1,
            "goal_resume_max_ms": 20_000,
            "other_agent_root_deliveries": 1,
            "peer_wait_projections": 1,
            "steer_actions": 1,
            "review_actions": 1,
        },
        "numeric_usage": {
            "input_tokens": 10_000,
            "cached_input_tokens": 2_000,
            "output_tokens": 4_000,
            "total_tokens": 16_000,
        },
        "memory": {
            "compact_response_upper_bound_bytes": 65_536,
            "raw_response_upper_bound_bytes": 131_072,
            "accepted_evidence_upper_bound_bytes": 8_192,
            "source_ref_count": 4,
            "source_proof_failures": 0,
            "restart_count": 1,
            "outbox_pending": 0,
            "outbox_conflict": 0,
            "room_readiness_degraded": 0,
            "settlement_blocked": 0,
        },
        "faults": [
            _event(
                1,
                "codex_app_server_sigkill",
                "codex_app_server_cleanup_confirmed",
                active=1,
            ),
            _event(2, "runner_sigkill", "runner_reconciled", active=2),
            _event(3, "memoryos_sigkill", "memoryos_reconciled", active=0),
            _event(
                4,
                "codex_projection_cache_deleted",
                "codex_projection_cache_rebuilt",
                active=0,
            ),
        ],
        "browser": {
            "headed": True,
            "viewports": [
                {
                    "width": 640,
                    "height": 900,
                    "refreshes": 4,
                    "console_errors": 0,
                    "page_errors": 0,
                    "current_state_available": 8,
                    "history_fabricated": 0,
                },
                {
                    "width": 1280,
                    "height": 720,
                    "refreshes": 4,
                    "console_errors": 0,
                    "page_errors": 0,
                    "current_state_available": 8,
                    "history_fabricated": 0,
                },
                {
                    "width": 1440,
                    "height": 900,
                    "refreshes": 4,
                    "console_errors": 0,
                    "page_errors": 0,
                    "current_state_available": 8,
                    "history_fabricated": 0,
                },
            ],
        },
        "resources": {
            "rss_warmup_median_bytes": 256 * 1024 * 1024,
            "rss_steady_state_max_bytes": 384 * 1024 * 1024,
            "fd_warmup": 40,
            "fd_steady_state_max": 56,
            "process_count_max": 12,
            "database_bytes": 4096,
            "wal_bytes": 1024,
            "sqlite_integrity": "ok",
        },
        "worktree": {
            "sentinel_before_digest": DIGEST_A,
            "sentinel_after_digest": DIGEST_A,
            "repository_before_digest": DIGEST_B,
            "repository_after_digest": DIGEST_B,
            "git_status_before_digest": DIGEST_A,
            "git_status_after_digest": DIGEST_A,
        },
    }


def test_builds_strict_safe_passing_contract() -> None:
    result = build_goal_memory_soak_result(manifest=_manifest(), evidence=_evidence())

    assert result["schema_version"] == RESULT_SCHEMA
    assert result["status"] == "passed"
    assert result["configuration"] == {
        "profile_id": "live-goal-memory-soak",
        "room_count": 4,
        "agents_per_room": 2,
        "wave_count": 4,
        "minimum_duration_ms": 3_600_000,
        "max_active_deliveries": 4,
    }
    assert result["latency_ms"]["post_to_claim"] == {
        "count": 16,
        "p50": 107,
        "p95": 115,
        "max": 115,
    }
    assert result["native"]["goal_terminal_state"] == "complete"
    assert result["numeric_usage"]["total_tokens"] == 16_000
    assert result["result_digest"].startswith("sha256:")
    assert evaluate_goal_memory_soak_result(result) == (True, ())
    assert validate_goal_memory_soak_result(result) == result
    encoded = json.dumps(result, sort_keys=True)
    for forbidden in ("/home/", "objective", "provider_output", "session_id", "model"):
        assert forbidden not in encoded


def test_hard_gate_failures_are_stable_and_cannot_be_forged() -> None:
    evidence = _evidence()
    evidence["counts"]["settled_correlations"] = 15
    evidence["native"]["goal_hold_claim_violations"] = 1
    evidence["memory"]["raw_response_upper_bound_bytes"] = 131_073
    evidence["faults"][1]["recovery_ms"] = 45_001
    evidence["browser"]["viewports"][0]["console_errors"] = 1
    evidence["resources"]["fd_steady_state_max"] = 57

    result = build_goal_memory_soak_result(manifest=_manifest(), evidence=evidence)
    passed, failed = evaluate_goal_memory_soak_result(result)
    assert passed is False
    assert {
        "all_correlations_settled",
        "goal_hold_respected",
        "memory_raw_size",
        "fault_recovery_deadline",
        "browser_clean",
        "fd_growth_limit",
    }.issubset(failed)

    forged = deepcopy(result)
    forged["status"] = "passed"
    with pytest.raises(GoalMemorySoakContractError, match="result_gates_invalid"):
        validate_goal_memory_soak_result(forged)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result.update({"path": "/private/workspace"}),
        lambda result: result["manifest"].update({"model": "private-model"}),
        lambda result: result["manifest"].update({"session_id": "private-session"}),
        lambda result: result["native"].update({"objective": "secret task"}),
        lambda result: result["faults"][0].update({"pid": 123}),
    ],
)
def test_private_or_uncontracted_fields_fail_closed(mutation) -> None:
    result = build_goal_memory_soak_result(manifest=_manifest(), evidence=_evidence())
    mutation(result)
    with pytest.raises(GoalMemorySoakContractError):
        validate_goal_memory_soak_result(result)


def test_manifest_is_strict_and_requires_canonical_hour_window() -> None:
    assert validate_goal_memory_soak_manifest(_manifest()) == _manifest()
    future = _manifest()
    future["schema_version"] = "room_goal_memory_soak_manifest/v2"
    with pytest.raises(GoalMemorySoakContractError, match="manifest_invalid"):
        validate_goal_memory_soak_manifest(future)

    short = _manifest()
    short["finished_at"] = "2026-07-13T00:59:59.999Z"
    result = build_goal_memory_soak_result(manifest=short, evidence=_evidence())
    assert "minimum_duration" in evaluate_goal_memory_soak_result(result)[1]


def test_write_is_private_atomic_and_revalidates(tmp_path: Path) -> None:
    result = build_goal_memory_soak_result(manifest=_manifest(), evidence=_evidence())
    target = tmp_path / "result.json"

    write_goal_memory_soak_result(target, result)

    assert json.loads(target.read_text(encoding="utf-8")) == result
    assert os.stat(target).st_mode & 0o777 == 0o600
    forged = deepcopy(result)
    forged["result_digest"] = DIGEST_A
    with pytest.raises(GoalMemorySoakContractError):
        write_goal_memory_soak_result(target, forged)
