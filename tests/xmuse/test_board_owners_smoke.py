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
    assert by_module["backend"]["paths"] == ["api/**"]
    assert by_module["backend"]["provides"] == ["api.greeting"]
    assert by_module["frontend"]["paths"] == ["client/**"]
    assert by_module["frontend"]["depends"] == ["api.greeting"]
    assert by_module["backend"]["acceptance"] == ["python -m pytest -q api"]
    assert by_module["frontend"]["acceptance"] == ["python -m pytest -q client"]
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
