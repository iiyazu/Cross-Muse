from __future__ import annotations

import json

import pytest

from xmuse_core.chat.room_execution_projection import (
    build_room_execution_candidate_projection,
    build_room_execution_list_projection,
)


class _ReadStore:
    def __init__(self) -> None:
        self.policy = {
            "conversation_id": "conv-execution",
            "mode": "consensus",
            "revision": 3,
            "risk_policy_revision": "room_execution_low_risk/v1",
            "kill_switch_enabled": False,
            "updated_at": "2026-07-12T08:00:00Z",
            "pid": 999,
        }
        self.candidates = [
            {
                "candidate_id": f"candidate-{index}",
                "proposal_id": f"proposal-{index}",
                "conversation_id": "conv-execution",
                "author_participant_id": "participant-author",
                "author_display_name": "Builder",
                "base_head": "a" * 40,
                "summary": f"Candidate {index}",
                "unified_diff": f"diff --git a/file{index}.py b/file{index}.py\n+safe = {index}\n",
                "allowed_files": [f"file{index}.py"],
                "candidate_digest": f"sha256:candidate-{index}",
                "patch_sha256": f"sha256:patch-{index}",
                "peer_snapshot_digest": f"sha256:snapshot-{index}",
                "state": "authorized" if index == 0 else "open",
                "consensus_state": "waiting",
                "revision": index + 1,
                "policy_snapshot": {
                    "mode": "consensus",
                    "revision": 3,
                    "risk_policy_revision": "room_execution_low_risk/v1",
                },
                "members": [
                    {
                        "participant_id": "participant-reviewer",
                        "display_name": "Reviewer",
                        "status_snapshot": "active",
                    }
                ],
                "assessments": [
                    {
                        "assessor_participant_id": "participant-reviewer",
                        "assessment": "endorse",
                        "rationale": "The exact digest is bounded.",
                        "created_at": "2026-07-12T08:01:00Z",
                    }
                ],
                "vote_counts": {
                    "required": 1,
                    "endorse": 1,
                    "object": 0,
                    "abstain": 0,
                    "pending": 0,
                },
                "run": {
                    "run_id": f"run-{index}",
                    "state": "verifying" if index == 0 else "failed",
                    "revision": 4,
                },
                "created_at": f"2026-07-12T08:0{index}:00Z",
                "updated_at": f"2026-07-12T08:0{index}:00Z",
                "workspace_path": "/secret/worktree",
                "operator_token": "do-not-project",
            }
            for index in range(3)
        ]
        self.runs = [
            {
                "run_id": f"run-{index}",
                "candidate_id": f"candidate-{index}",
                "state": "verifying" if index == 0 else "failed",
                "revision": 4,
                "attempt_number": 1,
                "reason_code": None,
                "created_at": "2026-07-12T08:10:00Z",
                "updated_at": "2026-07-12T08:11:00Z",
                "pid": 1234,
                "generation": "secret-generation",
                "raw_log": "provider output must not project",
                "gates": [
                    {
                        "gate_id": "backend-tests",
                        "label": "Backend tests",
                        "state": "running" if index == 0 else "failed",
                        "evidence_digest": "sha256:gate",
                        "raw_log": "traceback with /secret/path",
                    }
                ],
            }
            for index in range(3)
        ]

    def get_policy(self, conversation_id: str):
        return self.policy if conversation_id == "conv-execution" else None

    def get_candidate(self, candidate_id: str, *, include_patch: bool = False):
        assert isinstance(include_patch, bool)
        return next(
            (item for item in self.candidates if item["candidate_id"] == candidate_id),
            None,
        )

    def list_conversation_candidates(self, conversation_id: str, *, limit: int = 50):
        assert limit <= 50
        return (
            {"candidates": self.candidates[:limit]}
            if conversation_id == "conv-execution"
            else {"candidates": []}
        )

    def get_run(self, run_id: str):
        return next((item for item in self.runs if item["run_id"] == run_id), None)

    def list_conversation_runs(self, conversation_id: str, *, limit: int = 50):
        assert limit <= 50
        return {"runs": self.runs[:limit]} if conversation_id == "conv-execution" else {"runs": []}


def test_execution_list_is_bounded_paginated_and_never_contains_exact_diff_or_secrets() -> None:
    store = _ReadStore()

    first = build_room_execution_list_projection(
        store,
        "conv-execution",
        limit=2,
        generated_at="2026-07-12T09:00:00Z",
    )

    assert first["schema_version"] == "room_execution_list_projection/v1"
    assert len(first["candidates"]) == 2
    assert first["page"] == {
        "limit": 2,
        "cursor": None,
        "has_more": True,
        "next_cursor": "candidate-1",
    }
    assert first["policy"]["mode"] == "consensus"
    assert first["policy"]["automatic_execution_available"] is False
    assert first["policy"]["automatic_execution_code"] == ("execution_gate_profile_unavailable")
    encoded = json.dumps(first)
    for forbidden in (
        "unified_diff",
        "diff --git",
        "do-not-project",
        "/secret/worktree",
        "secret-generation",
        "provider output",
        "raw_log",
        '"pid"',
    ):
        assert forbidden not in encoded

    second = build_room_execution_list_projection(
        store, "conv-execution", limit=2, cursor="candidate-1"
    )
    assert [item["candidate_id"] for item in second["candidates"]] == ["candidate-2"]
    assert second["page"]["has_more"] is False
    with pytest.raises(ValueError, match="cursor_invalid"):
        build_room_execution_list_projection(store, "conv-execution", cursor="missing-candidate")
    with pytest.raises(ValueError, match="limit_invalid"):
        build_room_execution_list_projection(store, "conv-execution", limit=51)


def test_candidate_detail_is_the_only_projection_with_exact_diff_and_safe_votes_gates_actions() -> (
    None
):
    store = _ReadStore()

    detail = build_room_execution_candidate_projection(
        store, "candidate-0", generated_at="2026-07-12T09:00:00Z"
    )

    assert detail["schema_version"] == "room_execution_candidate_projection/v1"
    assert detail["candidate"]["unified_diff"].startswith("diff --git")
    assert detail["candidate"]["allowed_files"] == ["file0.py"]
    assert detail["votes"] == [
        {
            "participant_id": "participant-reviewer",
            "display_name": "Reviewer",
            "status_snapshot": "active",
            "assessment": "endorse",
            "rationale": "The exact digest is bounded.",
            "created_at": "2026-07-12T08:01:00Z",
        }
    ]
    assert detail["run"]["gates"] == [
        {
            "gate_id": "backend-tests",
            "label": "Backend tests",
            "state": "running",
            "evidence_digest": "sha256:gate",
            "started_at": None,
            "finished_at": None,
            "reason_code": None,
        }
    ]
    assert detail["actions"]["execute"]["available"] is False
    assert detail["run"]["actions"]["cancel"] == {
        "available": True,
        "method": "POST",
        "href": "/api/chat/operator/execution-runs/run-0/cancel",
        "expected_run_state": "verifying",
        "expected_run_revision": 4,
    }
    encoded = json.dumps(detail)
    for forbidden in (
        "do-not-project",
        "/secret/worktree",
        "secret-generation",
        "provider output",
        "raw_log",
        '"pid"',
    ):
        assert forbidden not in encoded


def test_candidate_detail_rejects_missing_and_oversized_diff() -> None:
    store = _ReadStore()
    with pytest.raises(KeyError):
        build_room_execution_candidate_projection(store, "missing")
    store.candidates[0]["unified_diff"] = "x" * (200 * 1024 + 1)
    with pytest.raises(ValueError, match="diff_invalid"):
        build_room_execution_candidate_projection(store, "candidate-0")


@pytest.mark.parametrize(
    "selected_gate_ids",
    [
        (
            "patch_diff_check",
            "backend_ruff",
            "backend_mypy",
            "backend_pytest",
        ),
        (
            "patch_diff_check",
            "frontend_typecheck",
            "frontend_lint",
            "frontend_vitest",
            "frontend_build",
        ),
    ],
)
def test_profile_projection_preserves_safe_selected_gate_subset_without_private_evidence(
    selected_gate_ids: tuple[str, ...],
) -> None:
    store = _ReadStore()
    bound = {
        "schema_version": "room_execution_gate_profile/v1",
        "profile_id": "xmuse-monorepo/v2",
        "revision": 2,
        "gate_ids": list(selected_gate_ids),
        "gate_plan_digest": "sha256:private-plan",
        "repository_manifest_digest": "sha256:private-repository",
        "workspace_path": "/secret/execution-workspace",
    }
    store.candidates[0]["gate_profile"] = bound
    store.runs[0]["gate_profile"] = bound
    configured = {
        "schema_version": "room_execution_gate_profile/v1",
        "profile_id": "xmuse-monorepo/v2",
        "revision": 2,
        "gate_ids": [
            "patch_diff_check",
            "backend_ruff",
            "backend_mypy",
            "backend_pytest",
            "frontend_typecheck",
            "frontend_lint",
            "frontend_vitest",
            "frontend_build",
        ],
        "readiness": {"state": "ready", "ready": True, "code": "ready"},
        "workspace_path": "/secret/execution-workspace",
        "toolchain_capability_digest": "sha256:private-toolchain",
    }

    listing = build_room_execution_list_projection(
        store,
        "conv-execution",
        execution_profile=configured,
    )
    detail = build_room_execution_candidate_projection(
        store,
        "candidate-0",
        execution_profile=configured,
    )

    assert listing["gate_profile"]["gate_ids"] == configured["gate_ids"]
    assert listing["gate_profile"]["readiness"] == {
        "state": "ready",
        "ready": True,
        "code": "ready",
    }
    assert listing["candidates"][0]["gate_profile"]["gate_ids"] == list(selected_gate_ids)
    assert detail["run"]["gate_profile"]["gate_ids"] == list(selected_gate_ids)
    encoded = json.dumps({"listing": listing, "detail": detail})
    for forbidden in (
        "private-plan",
        "private-repository",
        "private-toolchain",
        "/secret/execution-workspace",
        "gate_plan_digest",
        "repository_manifest_digest",
        "toolchain_capability_digest",
    ):
        assert forbidden not in encoded


def test_projection_rejects_forged_or_reordered_gate_profile_reference() -> None:
    store = _ReadStore()
    store.candidates[0]["gate_profile"] = {
        "schema_version": "room_execution_gate_profile/v1",
        "profile_id": "xmuse-monorepo/v2",
        "revision": 2,
        "gate_ids": ["patch_diff_check", "backend_pytest", "backend_ruff"],
    }

    listing = build_room_execution_list_projection(store, "conv-execution")

    assert listing["candidates"][0]["gate_profile"] is None


def test_blocked_profile_disables_execution_without_hiding_rejection() -> None:
    store = _ReadStore()
    store.candidates[1]["run"] = None
    configured = {
        "schema_version": "room_execution_gate_profile/v1",
        "profile_id": "xmuse-monorepo/v2",
        "revision": 2,
        "gate_ids": [
            "patch_diff_check",
            "backend_ruff",
            "backend_mypy",
            "backend_pytest",
            "frontend_typecheck",
            "frontend_lint",
            "frontend_vitest",
            "frontend_build",
        ],
        "readiness": {
            "state": "blocked",
            "ready": False,
            "code": "execution_frontend_dependencies_unavailable",
        },
    }

    detail = build_room_execution_candidate_projection(
        store,
        "candidate-1",
        execution_profile=configured,
    )

    assert detail["gate_profile"]["readiness"]["state"] == "blocked"
    assert detail["policy"]["automatic_execution_code"] == ("execution_gate_profile_unavailable")
    assert detail["actions"]["execute"]["available"] is False
    assert detail["actions"]["reject"]["available"] is True


def test_missing_profile_fails_closed_for_automatic_and_manual_execution() -> None:
    store = _ReadStore()
    store.candidates[1]["run"] = None

    listing = build_room_execution_list_projection(
        store,
        "conv-execution",
        consensus_kill_switch_enabled=True,
        execution_profile=None,
    )
    detail = build_room_execution_candidate_projection(
        store,
        "candidate-1",
        consensus_kill_switch_enabled=True,
        execution_profile=None,
    )

    assert listing["gate_profile"] is None
    assert listing["policy"]["automatic_execution_available"] is False
    assert listing["policy"]["automatic_execution_code"] == ("execution_gate_profile_unavailable")
    assert detail["gate_profile"] is None
    assert detail["actions"]["execute"]["available"] is False
    assert detail["actions"]["reject"]["available"] is True
