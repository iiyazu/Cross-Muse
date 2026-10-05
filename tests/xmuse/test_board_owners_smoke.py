from __future__ import annotations

import json

import pytest

from scripts import board_owners_smoke as smoke


def test_validate_model_accepts_only_the_two_allowed_models() -> None:
    assert (
        smoke.validate_model("opencode-go/muse-spark-1.3-contributor")
        == "opencode-go/muse-spark-1.3-contributor"
    )
    assert (
        smoke.validate_model("opencode-go/muse-spark-1.2-contributor")
        == "opencode-go/muse-spark-1.2-contributor"
    )
    with pytest.raises(ValueError):
        smoke.validate_model("opencode-go/other-model")
    with pytest.raises(ValueError):
        smoke.validate_model("")


def test_build_split_spec_has_the_exact_smoke_topology() -> None:
    spec = smoke.build_split_spec(backend_id="backend-1", frontend_id="frontend-1")

    by_module = {module["module_id"]: module for module in spec["modules"]}
    assert set(by_module) == {"backend", "frontend"}
    # src/-rooted paths: the only Python layout the python-uv/v1 gate profile
    # covers, so owner patches stay verifiable by real gates.
    assert by_module["backend"]["paths"] == ["src/api/**"]
    assert by_module["backend"]["provides"] == ["api.greeting"]
    assert by_module["frontend"]["paths"] == ["src/client/**"]
    assert by_module["frontend"]["depends"] == ["api.greeting"]
    assert by_module["backend"]["acceptance"] == ["python -m pytest -q src/api"]
    assert by_module["frontend"]["acceptance"] == ["python -m pytest -q src/client"]
    assert spec["assignments"] == {"backend": "backend-1", "frontend": "frontend-1"}

    assert len(spec["contracts"]) == 1
    contract = spec["contracts"][0]
    assert contract["contract_id"] == "api.greeting"
    assert contract["kind"] == "protocol"
    assert contract["provider_module_id"] == "backend"
    assert "Hello, <name>!" in contract["content"]


def test_split_human_message_embeds_the_exact_split_json() -> None:
    message = smoke.build_split_human_message(backend_id="b", frontend_id="f")

    assert "chat_room_board_propose_split" in message
    payload_text = message.split(":\n", 1)[1].rsplit("\n", 1)[0]
    assert json.loads(payload_text) == smoke.build_split_spec(backend_id="b", frontend_id="f")


def test_revise_human_message_orders_publish_before_code() -> None:
    message = smoke.build_revise_human_message()

    assert "base_version=1" in message
    assert '"lang": "en"' in message
    assert "[en]" in message
    assert message.index("FIRST publish") < message.index("ONLY after the publish succeeds")


def test_resolve_smoke_claude_argv() -> None:
    assert smoke.resolve_smoke_claude_argv("opencode") is None
    assert smoke.resolve_smoke_claude_argv("claude") == tuple(smoke.ROOM_ACP_DEFAULT_COMMAND)


def test_resolve_smoke_claude_argv_honors_the_command_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XMUSE_CLAUDE_ACP_COMMAND", "node /tmp/bridge.js --flag")
    assert smoke.resolve_smoke_claude_argv("claude") == ("node", "/tmp/bridge.js", "--flag")


def test_build_git_argv_uses_the_owner_clone_hardening() -> None:
    argv = smoke.build_git_argv(["log", "--oneline"])

    assert argv[:5] == ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
    assert argv[5:] == ["log", "--oneline"]


def test_frontend_session_reused_requires_a_shared_session() -> None:
    assert smoke.frontend_session_reused(["s1", "s2"], ["s2", "s3"]) is True
    assert smoke.frontend_session_reused(["s1"], ["s2"]) is False
    assert smoke.frontend_session_reused([], ["s1"]) is False
    assert smoke.frontend_session_reused([""], [""]) is False


def _evidence(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "split_approved": True,
        "backend_charter_claimed": True,
        "frontend_charter_claimed": True,
        "contract_v2_published_by_backend": True,
        "frontend_completed_revision": True,
        "frontend_render_mentions_lang": True,
    }
    base.update(overrides)
    return base


def test_board_smoke_ok_requires_every_check() -> None:
    assert smoke.board_smoke_ok(_evidence()) is True

    for key in (
        "split_approved",
        "backend_charter_claimed",
        "frontend_charter_claimed",
        "contract_v2_published_by_backend",
        "frontend_completed_revision",
        "frontend_render_mentions_lang",
    ):
        assert smoke.board_smoke_ok(_evidence(**{key: False})) is False


def test_compute_board_smoke_checks_reports_each_condition() -> None:
    checks = smoke.compute_board_smoke_checks(_evidence(frontend_render_mentions_lang=False))

    assert checks == {
        "split_approved": True,
        "backend_charter_claimed": True,
        "frontend_charter_claimed": True,
        "contract_v2_published_by_backend": True,
        "frontend_completed_revision": True,
        "frontend_render_mentions_lang": False,
    }


def test_validate_agy_model_accepts_only_gemini_names() -> None:
    assert smoke.validate_agy_model("gemini-3.8-flash-high") == "gemini-3.8-flash-high"
    assert smoke.validate_agy_model("  gemini-2.0-pro  ") == "gemini-2.0-pro"
    with pytest.raises(ValueError):
        smoke.validate_agy_model("opencode-go/muse-spark-1.3-contributor")
    with pytest.raises(ValueError):
        smoke.validate_agy_model("")


def test_frontend_cli_accepts_antigravity() -> None:
    assert "antigravity" in smoke.ALLOWED_FRONTEND_CLIS
    assert set(smoke.ALLOWED_FRONTEND_CLIS) == {"opencode", "claude", "antigravity"}


def test_scenario_defaults_to_revision() -> None:
    assert smoke.DEFAULT_SCENARIO == "revision"
    assert set(smoke.ALLOWED_SCENARIOS) == {
        "revision",
        "verify",
        "false-done",
        "review",
        "integration",
    }


def test_default_execution_profile_runs_pytest() -> None:
    assert smoke.DEFAULT_EXECUTION_PROFILE_ID == "python-uv/v1"
    profile = smoke.get_execution_gate_profile(smoke.DEFAULT_EXECUTION_PROFILE_ID)
    assert "python_uv_pytest" in profile.gate_ids


def test_drill_human_message_is_explicit_fault_injection() -> None:
    message = smoke.build_drill_human_message()

    # The drill names the backend file and the done report the verifier must
    # catch; exact wording is free.
    assert "src/api/greeting.py" in message
    assert "status done" in message
    assert "backend" in message


def test_sessions_shared_requires_a_shared_session() -> None:
    assert smoke.sessions_shared(["s1", "s2"], ["s2", "s3"]) is True
    assert smoke.sessions_shared(["s1"], ["s2"]) is False
    assert smoke.sessions_shared([], ["s1"]) is False
    assert smoke.sessions_shared([""], [""]) is False


def _failed_gate_detail(**overrides: object) -> dict[str, object]:
    detail: dict[str, object] = {
        "status": "failed",
        "reason_code": smoke.BOARD_VERIFICATION_GATE_FAILED,
        "failed_gate_ids": ["python_uv_pytest"],
    }
    detail.update(overrides)
    return detail


def test_verification_failed_gate_needs_a_failed_gate() -> None:
    assert smoke.verification_failed_gate(_failed_gate_detail()) is True
    assert smoke.verification_failed_gate(_failed_gate_detail(status="passed")) is False
    assert smoke.verification_failed_gate(_failed_gate_detail(status="error")) is False
    assert (
        smoke.verification_failed_gate(
            _failed_gate_detail(reason_code="board_verification_outside_charter")
        )
        is False
    )
    assert (
        smoke.verification_failed_gate(
            _failed_gate_detail(reason_code="owner_patch_empty", failed_gate_ids=[])
        )
        is False
    )
    assert smoke.verification_failed_gate(_failed_gate_detail(failed_gate_ids=[])) is False
    assert smoke.verification_failed_gate({"status": "failed"}) is False


def test_verification_seconds_done_to_result() -> None:
    detail = {
        "done_at": "2026-01-01T00:00:00.000000Z",
        "result_at": "2026-01-01T00:01:30.000000Z",
    }
    assert smoke.verification_seconds_done_to_result(detail) == 90.0
    assert smoke.verification_seconds_done_to_result({"done_at": None, "result_at": None}) is None
    assert (
        smoke.verification_seconds_done_to_result(
            {"done_at": "not-a-time", "result_at": "2026-01-01T00:01:30.000000Z"}
        )
        is None
    )


def test_summarize_module_verifications_counts_rework() -> None:
    failed = {"status": "failed"}
    passed = {"status": "passed"}

    assert smoke.summarize_module_verifications([failed, failed, passed]) == {
        "verifications_passed": 1,
        "verifications_failed": 2,
        "rework_rounds": 2,
    }
    assert smoke.summarize_module_verifications([failed])["rework_rounds"] == 1
    assert smoke.summarize_module_verifications([passed])["rework_rounds"] == 0
    # A failure after the first pass is not rework.
    assert smoke.summarize_module_verifications([passed, failed]) == {
        "verifications_passed": 1,
        "verifications_failed": 1,
        "rework_rounds": 0,
    }
    # Pending/running rows never count.
    assert smoke.summarize_module_verifications([{"status": "pending"}, {"status": "running"}]) == {
        "verifications_passed": 0,
        "verifications_failed": 0,
        "rework_rounds": 0,
    }


def test_build_verification_detail_reports_gates_and_seconds() -> None:
    detail = smoke.build_verification_detail(
        {
            "verification_id": "boardverify_1",
            "module_id": "backend",
            "status": "failed",
            "created_at": "2026-01-01T00:00:00.000000Z",
            "updated_at": "2026-01-01T00:02:00.000000Z",
            "done_at": "2026-01-01T00:00:00.000000Z",
            "result": {
                "reason_code": smoke.BOARD_VERIFICATION_GATE_FAILED,
                "gates": [
                    {"gate_id": "patch_diff_check", "status": "passed", "exit_code": 0},
                    {
                        "gate_id": "python_uv_pytest",
                        "status": "failed",
                        "exit_code": 1,
                        "reason_code": "execution_gate_failed",
                    },
                ],
            },
        }
    )

    assert detail["status"] == "failed"
    assert detail["reason_code"] == smoke.BOARD_VERIFICATION_GATE_FAILED
    assert detail["failed_gate_ids"] == ["python_uv_pytest"]
    assert detail["done_to_result_s"] == 120.0
    assert smoke.verification_failed_gate(detail) is True


def test_build_verification_detail_for_pending_rows() -> None:
    detail = smoke.build_verification_detail(
        {
            "verification_id": "boardverify_2",
            "module_id": "backend",
            "status": "running",
            "created_at": "2026-01-01T00:00:00.000000Z",
            "updated_at": "2026-01-01T00:00:05.000000Z",
            "done_at": "2026-01-01T00:00:00.000000Z",
            "result": None,
        }
    )

    assert detail["reason_code"] is None
    assert detail["failed_gate_ids"] == []
    assert detail["result_at"] is None
    assert detail["done_to_result_s"] is None


def test_build_module_verification_summary() -> None:
    details = [
        {"status": "failed", "verification_id": "v1"},
        {"status": "passed", "verification_id": "v2"},
    ]
    summary = smoke.build_module_verification_summary(
        module_id="backend", details=details, done_reports=2
    )

    assert summary["module_id"] == "backend"
    assert summary["done_reports"] == 2
    assert summary["verifications_passed"] == 1
    assert summary["verifications_failed"] == 1
    assert summary["rework_rounds"] == 1
    assert summary["verifications"] == details


def _false_done_evidence(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "backend_drill_verifications": [
            _failed_gate_detail(),
            {"status": "passed", "reason_code": None, "failed_gate_ids": []},
        ],
        "backend_woken_by_verification": True,
        "backend_drill_session_ids": ["session-1"],
        "backend_woken_session_ids": ["session-1", "session-2"],
    }
    base.update(overrides)
    return base


def test_false_done_ok_requires_every_check() -> None:
    assert smoke.false_done_ok(_false_done_evidence()) is True

    assert (
        smoke.false_done_ok(
            _false_done_evidence(
                backend_drill_verifications=[
                    {
                        "status": "passed",
                        "reason_code": None,
                        "failed_gate_ids": [],
                    }
                ]
            )
        )
        is False
    )
    assert smoke.false_done_ok(_false_done_evidence(backend_woken_by_verification=False)) is False
    assert smoke.false_done_ok(_false_done_evidence(backend_woken_session_ids=["other"])) is False
    assert (
        smoke.false_done_ok(
            _false_done_evidence(
                backend_drill_verifications=[_failed_gate_detail()],
            )
        )
        is False
    )
    assert smoke.false_done_ok(_false_done_evidence(backend_drill_verifications=[])) is False


def _loop_evidence(*, frontend_wake_session: str = "s-front") -> dict[str, object]:
    failed = {
        "status": "failed",
        "reason_code": "board_verification_gate_failed",
        "failed_gate_ids": ["python_uv_mypy"],
    }
    passed = {"status": "passed", "reason_code": None, "failed_gate_ids": []}
    waiting = {"status": "pending", "reason_code": "board_verification_waiting_for_provider"}
    return {
        "module_verifications": {
            "backend": {"done_reports": 1, "verifications": [passed]},
            "frontend": {"done_reports": 2, "verifications": [waiting, failed, passed]},
        },
        "participants": {
            "backend": {
                "observations": [
                    {
                        "source_activity_type": "board.charter_assigned",
                        "provider_session_ids": ["s-back"],
                    }
                ]
            },
            "frontend": {
                "observations": [
                    {
                        "source_activity_type": "board.charter_assigned",
                        "provider_session_ids": ["s-front"],
                    },
                    {
                        "source_activity_type": "board.verification",
                        "provider_session_ids": [frontend_wake_session],
                    },
                ]
            },
        },
    }


def test_verification_loop_counts_organic_false_claims() -> None:
    loop = smoke.compute_verification_loop(_loop_evidence())

    assert loop["claims"] == 3
    assert loop["first_try_passes"] == 1
    assert loop["false_claims"] == 1
    assert loop["all_verified"] is True
    assert loop["wakes_reused_session"] is True
    assert loop["modules"]["frontend"]["wakes"] == 1
    assert smoke.compute_verify_checks(_loop_evidence()) == {
        "all_modules_verified": True,
        "wakes_reused_session": True,
    }


def test_verify_checks_fail_on_unverified_module_or_new_session() -> None:
    evidence = _loop_evidence(frontend_wake_session="s-new")
    assert smoke.compute_verify_checks(evidence)["wakes_reused_session"] is False

    unverified = _loop_evidence()
    modules = unverified["module_verifications"]
    assert isinstance(modules, dict)
    modules["frontend"]["verifications"] = [
        {"status": "failed", "reason_code": "board_verification_gate_failed"}
    ]
    assert smoke.compute_verify_checks(unverified)["all_modules_verified"] is False


def test_compute_false_done_checks_reports_each_condition() -> None:
    checks = smoke.compute_false_done_checks(
        _false_done_evidence(backend_woken_by_verification=False)
    )

    assert checks == {
        "first_verification_failed": True,
        "owner_woken_by_verification": False,
        "owner_session_reused": True,
        "final_verification_passed": True,
    }


def test_false_done_first_must_be_a_gate_failure() -> None:
    assert (
        smoke.compute_false_done_checks(
            _false_done_evidence(
                backend_drill_verifications=[
                    _failed_gate_detail(
                        reason_code="board_verification_outside_charter",
                        failed_gate_ids=[],
                    ),
                    {"status": "passed", "reason_code": None, "failed_gate_ids": []},
                ]
            )
        )["first_verification_failed"]
        is False
    )


def test_seed_pins_the_v1_contract_protocol() -> None:
    assert smoke.SEED_PROJECT_NAME == "board-smoke-seed"
    assert 'name = "board-smoke-seed"' in smoke.SEED_PYPROJECT_TOML
    assert "hatchling" in smoke.SEED_PYPROJECT_TOML
    for dependency in ("pytest", "mypy", "ruff"):
        assert dependency in smoke.SEED_PYPROJECT_TOML

    by_path = dict(smoke.SEED_FILES)
    # The charter phase must have real work: implementations are not
    # pre-written. Only the provider's contract test is seeded, because a
    # dependent's test would fail the provider's whole-repository gates.
    # The integration scenario additionally seeds one shared file (with no
    # test of its own) that both owners' charters cover.
    assert set(by_path) == {
        "src/api/__init__.py",
        "src/api/test_greeting_contract.py",
        "src/client/__init__.py",
        "src/shared/__init__.py",
        "src/shared/flags.py",
    }
    assert 'OWNER = "none"' in by_path["src/shared/flags.py"]
    # The backend contract test pins the v1 protocol from CONTRACT_V1_CONTENT.
    assert "Hello, <name>!" in smoke.CONTRACT_V1_CONTENT
    assert "from api.greeting import greet" in by_path["src/api/test_greeting_contract.py"]
    assert (
        'greet("Ada") == {"message": "Hello, Ada!"}'
        in (by_path["src/api/test_greeting_contract.py"])
    )


def _review_evidence(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "module_verifications": {
            "backend": {
                "done_reports": 2,
                "verifications": [
                    {
                        "verification_id": "v1",
                        "status": "passed",
                        "done_at": "2026-01-01T00:00:00.000000Z",
                    },
                    {
                        "verification_id": "v2",
                        "status": "passed",
                        "done_at": "2026-01-01T00:05:00.000000Z",
                    },
                ],
            },
            "frontend": {
                "done_reports": 1,
                "verifications": [
                    {
                        "verification_id": "v3",
                        "status": "passed",
                        "done_at": "2026-01-01T00:00:00.000000Z",
                    }
                ],
            },
        },
        "module_reviews": {
            "backend": {
                "done_reports": 2,
                "reviews": [
                    {
                        "review_id": "r1",
                        "module_id": "backend",
                        "verification_id": "v1",
                        "status": "objected",
                        "author_family": "opencode",
                        "reviewer_kind": "participant",
                        "reviewer_family": "claude",
                        "created_at": "2026-01-01T00:01:00.000000Z",
                        "verdict_at": "2026-01-01T00:02:00.000000Z",
                    },
                    {
                        "review_id": "r2",
                        "module_id": "backend",
                        "verification_id": "v2",
                        "status": "endorsed",
                        "author_family": "opencode",
                        "reviewer_kind": "participant",
                        "reviewer_family": "claude",
                        "created_at": "2026-01-01T00:06:00.000000Z",
                        "verdict_at": "2026-01-01T00:07:00.000000Z",
                    },
                ],
            },
            "frontend": {
                "done_reports": 1,
                "reviews": [
                    {
                        "review_id": "r3",
                        "module_id": "frontend",
                        "verification_id": "v3",
                        "status": "endorsed",
                        "author_family": "claude",
                        "reviewer_kind": "participant",
                        "reviewer_family": "opencode",
                        "created_at": "2026-01-01T00:01:00.000000Z",
                        "verdict_at": "2026-01-01T00:02:00.000000Z",
                    }
                ],
            },
        },
    }
    base.update(overrides)
    return base


def test_review_scenario_is_registered() -> None:
    assert "review" in smoke.ALLOWED_SCENARIOS


def test_review_loop_counts_endorsements_and_fixes() -> None:
    loop = smoke.compute_review_loop(_review_evidence())

    assert loop["reviews"] == 3
    assert loop["endorsed"] == 2
    assert loop["objected"] == 1
    assert loop["all_endorsed"] is True
    assert loop["objections_fixed"] is True
    assert loop["modules"]["backend"]["endorsed_final"] is True


def test_review_checks_require_cross_family_endorsement() -> None:
    assert smoke.compute_review_checks(_review_evidence()) == {
        "all_modules_verified": True,
        "all_modules_endorsed": True,
        "reviewers_cross_family": True,
        "objections_fixed": True,
    }
    assert smoke.review_ok(_review_evidence()) is True


def test_review_checks_reject_same_family_reviewer() -> None:
    evidence = _review_evidence()
    modules = evidence["module_reviews"]
    assert isinstance(modules, dict)
    backend = modules["backend"]
    assert isinstance(backend, dict)
    reviews = backend["reviews"]
    assert isinstance(reviews, list)
    reviews[1] = {**reviews[1], "reviewer_family": "opencode"}

    assert smoke.compute_review_checks(evidence)["reviewers_cross_family"] is False
    assert smoke.review_ok(evidence) is False


def test_review_checks_reject_pending_objection_fix() -> None:
    evidence = _review_evidence()
    modules = evidence["module_reviews"]
    assert isinstance(modules, dict)
    backend = modules["backend"]
    assert isinstance(backend, dict)
    backend["reviews"] = [backend["reviews"][0]]

    loop = smoke.compute_review_loop(evidence)
    assert loop["all_endorsed"] is False
    assert smoke.review_ok(evidence) is False


def test_build_review_detail_carries_families() -> None:
    detail = smoke.build_review_detail(
        {
            "review_id": "r1",
            "module_id": "backend",
            "verification_id": "v1",
            "status": "pending",
            "author_participant_id": "a",
            "author_family": "opencode",
            "reviewer_kind": "participant",
            "reviewer_participant_id": "c",
            "reviewer_family": "claude",
            "created_at": "2026-01-01T00:00:00.000000Z",
            "updated_at": "2026-01-01T00:01:00.000000Z",
        }
    )

    assert detail["reviewer_family"] == "claude"
    assert detail["author_family"] == "opencode"


def test_integration_split_gives_both_owners_the_shared_file() -> None:
    spec = smoke.build_integration_split_spec(backend_id="backend-1", frontend_id="frontend-1")

    by_module = {module["module_id"]: module for module in spec["modules"]}
    assert set(by_module) == {"backend", "frontend"}
    # Both charters cover the one shared file, with no contracts or
    # dependencies, so each verification stage holds only its own patch.
    assert by_module["backend"]["paths"] == ["src/shared/**"]
    assert by_module["frontend"]["paths"] == ["src/shared/**"]
    assert by_module["backend"]["provides"] == []
    assert by_module["backend"]["depends"] == []
    assert by_module["frontend"]["provides"] == []
    assert by_module["frontend"]["depends"] == []
    assert spec["assignments"] == {"backend": "backend-1", "frontend": "frontend-1"}
    assert spec["contracts"] == []
    # Both acceptances edit the same line to different values, with
    # module-specific test files so the patches collide on exactly one path.
    backend_text = " ".join(by_module["backend"]["acceptance"])
    frontend_text = " ".join(by_module["frontend"]["acceptance"])
    assert "src/shared/flags.py" in backend_text
    assert "src/shared/flags.py" in frontend_text
    assert '"backend"' in backend_text
    assert '"frontend"' in frontend_text
    assert "test_backend_flags.py" in backend_text
    assert "test_frontend_flags.py" in frontend_text


def test_integration_split_human_message_embeds_the_exact_split_json() -> None:
    message = smoke.build_integration_split_human_message(backend_id="b", frontend_id="f")

    assert "chat_room_board_propose_split" in message
    payload_text = message.split(":\n", 1)[1].rsplit("\n", 1)[0]
    assert json.loads(payload_text) == smoke.build_integration_split_spec(
        backend_id="b", frontend_id="f"
    )


def test_integration_fix_message_is_short_and_neutral() -> None:
    message = smoke.build_integration_fix_human_message(module_id="frontend")

    assert "src/shared/flags.py" in message
    assert "frontend" in message
    assert "done" in message
    # Never tell the agent the answer to the checks.
    assert "integrated" not in message
    assert "conflict_detected" not in message
    assert "both_integrated" not in message


def _integration_job(
    job_id: str, *, frontend_status: str = "conflicted", job_status: str = "integrated"
) -> dict[str, object]:
    return {
        "integration_id": job_id,
        "status": job_status,
        "reason_code": None,
        "created_at": "2026-01-01T00:00:00.000000Z",
        "finished_at": "2026-01-01T00:01:00.000000Z",
        "items": [
            {
                "module_id": "backend",
                "verification_id": "v1",
                "order": 1,
                "role": "newcomer",
                "status": "applied",
                "applied_verification_id": "v1",
                "conflicts_total": 0,
                "reason_code": None,
            },
            {
                "module_id": "frontend",
                "verification_id": "v2",
                "order": 2,
                "role": "newcomer",
                "status": frontend_status,
                "applied_verification_id": None,
                "conflicts_total": 1 if frontend_status != "applied" else 0,
                "reason_code": (
                    "board_integration_conflict" if frontend_status != "applied" else None
                ),
            },
        ],
    }


def _integration_evidence(**overrides: object) -> dict[str, object]:
    def _module_state(integration_status: str) -> dict[str, object]:
        return {
            "counters": {
                "done_reports": 2,
                "passed": 2,
                "failed": 0,
                "superseded": 0,
                "errored": 0,
                "rework_rounds": 0,
                "reviews_endorsed": 0,
                "reviews_objected": 0,
                "integrations_conflicted": 0,
                "integrations_gate_failed": 0,
                "conflict_fix_rounds": 0,
            },
            "state": "verified",
            "accepted": True,
            "integration_status": integration_status,
        }

    base: dict[str, object] = {
        "integration_jobs": [_integration_job("job-1")],
        "integration_conflicted_module": "frontend",
        "integration_drill_observation_ids": ["obs-fix-1"],
        "participants": {
            "backend": {"observations": []},
            "frontend": {
                "observations": [
                    {
                        "observation_id": "obs-fix-1",
                        "source_activity_type": "message.posted",
                        "status": "completed",
                        "provider_session_ids": ["s-front"],
                    }
                ]
            },
        },
        "module_states": {
            "backend": _module_state("integrated"),
            "frontend": _module_state("integrated"),
        },
        "user_checkout_untouched": True,
    }
    base.update(overrides)
    return base


def test_latest_conflicted_module_names_the_newest_conflict() -> None:
    assert smoke.latest_conflicted_module([_integration_job("job-1")]) == "frontend"
    assert (
        smoke.latest_conflicted_module(
            [_integration_job("job-1"), _integration_job("job-2", frontend_status="applied")]
        )
        is None
    )
    assert smoke.latest_conflicted_module([]) is None
    assert smoke.latest_conflicted_module([_integration_job("job-1", job_status="running")]) is None


def test_integration_ok_requires_every_check() -> None:
    assert smoke.integration_ok(_integration_evidence()) is True

    assert (
        smoke.integration_ok(
            _integration_evidence(
                integration_jobs=[_integration_job("job-1", frontend_status="applied")],
                integration_conflicted_module=None,
            )
        )
        is False
    )
    assert (
        smoke.integration_ok(
            _integration_evidence(
                participants={
                    "backend": {"observations": []},
                    "frontend": {"observations": []},
                }
            )
        )
        is False
    )
    frontend_pending = _integration_evidence()
    states = frontend_pending["module_states"]
    assert isinstance(states, dict)
    frontend_state = dict(states["frontend"])
    assert isinstance(frontend_state, dict)
    frontend_state["integration_status"] = "conflicted"
    states["frontend"] = frontend_state
    assert smoke.integration_ok(frontend_pending) is False
    assert smoke.integration_ok(_integration_evidence(user_checkout_untouched=False)) is False


def test_compute_integration_checks_reports_each_condition() -> None:
    checks = smoke.compute_integration_checks(_integration_evidence(user_checkout_untouched=False))

    assert checks == {
        "conflict_detected": True,
        "owner_woken": True,
        "both_integrated": True,
        "user_checkout_untouched": False,
    }


def test_conflict_detected_survives_the_final_clean_job() -> None:
    evidence = _integration_evidence(
        integration_jobs=[
            _integration_job("job-1"),
            _integration_job("job-2", frontend_status="applied"),
        ],
        integration_conflicted_module=None,
    )

    assert smoke.compute_integration_checks(evidence)["conflict_detected"] is True


def test_owner_woken_accepts_a_board_integration_wake_up() -> None:
    evidence = _integration_evidence(
        integration_drill_observation_ids=[],
        participants={
            "backend": {"observations": []},
            "frontend": {
                "observations": [
                    {
                        "observation_id": "obs-int-9",
                        "source_activity_type": "board.integration",
                        "status": "completed",
                        "provider_session_ids": ["s-front"],
                    }
                ]
            },
        },
    )

    assert smoke.compute_integration_checks(evidence)["owner_woken"] is True


def test_compute_integration_loop_counts_conflicts() -> None:
    loop = smoke.compute_integration_loop(_integration_evidence())

    assert loop["jobs"] == 1
    assert loop["conflicts"] == 1
    assert loop["all_integrated"] is True
    assert loop["modules"]["frontend"] == {"conflicts": 1, "integrated": True}
    assert loop["modules"]["backend"] == {"conflicts": 0, "integrated": True}


def test_source_repo_snapshot_detects_checkout_changes(tmp_path: object) -> None:
    import subprocess
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    repo = tmp_path / "source"
    repo.mkdir()
    env = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
    }
    subprocess.run(["git", "init"], cwd=str(repo), env=env, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=str(repo),
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=str(repo),
        env=env,
        check=True,
        capture_output=True,
    )
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), env=env, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=str(repo), env=env, check=True, capture_output=True
    )

    before = smoke.source_repo_snapshot(repo)
    assert smoke.source_repo_snapshot(repo) == before
    (repo / "file.txt").write_text("changed\n", encoding="utf-8")
    assert smoke.source_repo_snapshot(repo) != before
