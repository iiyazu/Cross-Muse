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
    assert set(smoke.ALLOWED_SCENARIOS) == {"revision", "verify", "false-done"}


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
    assert set(by_path) == {
        "src/api/__init__.py",
        "src/api/test_greeting_contract.py",
        "src/client/__init__.py",
    }
    # The backend contract test pins the v1 protocol from CONTRACT_V1_CONTENT.
    assert "Hello, <name>!" in smoke.CONTRACT_V1_CONTENT
    assert "from api.greeting import greet" in by_path["src/api/test_greeting_contract.py"]
    assert (
        'greet("Ada") == {"message": "Hello, Ada!"}'
        in (by_path["src/api/test_greeting_contract.py"])
    )
