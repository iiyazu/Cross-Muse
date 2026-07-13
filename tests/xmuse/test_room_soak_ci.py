from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from xmuse_core.chat.room_soak_ci import (
    CI_SOAK_AGENT_COUNT,
    CI_SOAK_EVIDENCE_SCHEMA,
    CI_SOAK_MAX_ACTIVE_DELIVERIES,
    CI_SOAK_PROFILE_ID,
    CI_SOAK_ROOM_COUNT,
    CI_SOAK_TURN_COUNT,
    run_ci_sim,
)


@pytest.fixture(scope="module")
def ci_evidence(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, Any]:
    return run_ci_sim(runtime_root=tmp_path_factory.mktemp("room-soak-ci"))


def test_ci_sim_drives_fixed_production_room_load_and_settles(
    ci_evidence: Mapping[str, Any],
) -> None:
    expected_correlations = CI_SOAK_ROOM_COUNT * CI_SOAK_TURN_COUNT
    expected_root_attempts = expected_correlations * CI_SOAK_AGENT_COUNT
    expected_peer_attempts = expected_correlations * (CI_SOAK_AGENT_COUNT - 1)
    expected_attempts = expected_root_attempts + expected_peer_attempts

    assert ci_evidence["schema_version"] == CI_SOAK_EVIDENCE_SCHEMA
    assert ci_evidence["profile_id"] == CI_SOAK_PROFILE_ID
    assert ci_evidence["configuration"] == {
        "room_count": 12,
        "agents_per_room": 4,
        "human_turns_per_room": 20,
        "max_concurrent_provider_deliveries": 4,
    }
    assert ci_evidence["counts"] == {
        "human_posts": expected_correlations,
        "correlations": expected_correlations,
        "attempts": expected_attempts,
        "outcomes": expected_attempts,
        "root_attempts": expected_root_attempts,
        "peer_attempts": expected_peer_attempts,
        "respond": expected_correlations,
        "noop": expected_attempts - expected_correlations,
        "other_outcomes": 0,
        "skill_decisions": expected_attempts,
        "settled_correlations": expected_correlations,
    }
    assert ci_evidence["violations"] == {
        "duplicate_outcome": 0,
        "cross_room_identity": 0,
        "cross_room_causality": 0,
        "unsettled_correlation": 0,
    }
    assert ci_evidence["residual"] == {
        "live_leases": 0,
        "cleanup_pending": 0,
        "recovery_pending": 0,
        "exhausted": 0,
        "incomplete_attempts": 0,
    }


def test_ci_sim_proves_concurrent_posts_bounded_delivery_fairness_and_safe_output(
    ci_evidence: Mapping[str, Any],
) -> None:
    expected_correlations = CI_SOAK_ROOM_COUNT * CI_SOAK_TURN_COUNT
    concurrency = ci_evidence["concurrency"]
    assert concurrency["max_active_posts"] == CI_SOAK_ROOM_COUNT
    assert concurrency["queued_correlations_before_host"] == expected_correlations
    assert concurrency["max_active_deliveries"] == CI_SOAK_MAX_ACTIVE_DELIVERIES
    assert concurrency["rooms_first_claimed"] == CI_SOAK_ROOM_COUNT
    assert concurrency["attempts_until_all_rooms_first_claimed"] <= (
        CI_SOAK_ROOM_COUNT * CI_SOAK_AGENT_COUNT
    )

    latency = ci_evidence["latency_samples_ms"]
    assert set(latency) == {
        "post_to_claim",
        "post_to_outcome",
        "post_to_settled",
    }
    assert all(len(samples) == expected_correlations for samples in latency.values())
    assert all(
        claim["ordinal"] == outcome["ordinal"] == settled["ordinal"]
        and claim["latency_ms"] <= outcome["latency_ms"] <= settled["latency_ms"]
        for claim, outcome, settled in zip(
            latency["post_to_claim"],
            latency["post_to_outcome"],
            latency["post_to_settled"],
            strict=True,
        )
    )
    storage = ci_evidence["storage"]
    assert storage["sqlite_integrity"] == "ok"
    assert storage["database_bytes"] > 0
    assert storage["wal_bytes"] >= 0

    encoded = json.dumps(ci_evidence, sort_keys=True)
    for forbidden in (
        "conv_",
        "participant_",
        "activity_",
        "observation_",
        "god-",
        "ci-soak-human",
        "Deterministic CI turn",
        "Deterministic CI participant response",
    ):
        assert forbidden not in encoded


def test_ci_sim_refuses_to_mix_with_an_existing_runtime_root(tmp_path: Path) -> None:
    (tmp_path / "chat.db").touch()

    with pytest.raises(ValueError, match="room_soak_runtime_root_not_empty"):
        run_ci_sim(runtime_root=tmp_path)
