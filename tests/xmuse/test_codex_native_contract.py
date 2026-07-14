from __future__ import annotations

import pytest

from xmuse_core.agents.codex_native_contract import (
    CodexNativeContractError,
    build_native_invocation,
)

CATALOG = {
    "gpt-a": frozenset({"low", "medium", "high", "max", "ultra"}),
    "gpt-b": frozenset({"low", "high"}),
}


def test_goal_payload_is_rebuilt_with_native_method_and_limits() -> None:
    invocation = build_native_invocation(
        "goal_set",
        {"objective": "Inspect the repository", "token_budget": 100_000},
        thread_id="private-thread",
    )

    assert invocation.method == "thread/goal/set"
    assert invocation.params == {
        "threadId": "private-thread",
        "objective": "Inspect the repository",
        "tokenBudget": 100_000,
        "status": "active",
    }


@pytest.mark.parametrize(
    ("capability", "method", "status"),
    [
        ("goal_pause", "thread/goal/set", "paused"),
        ("goal_resume", "thread/goal/set", "active"),
    ],
)
def test_goal_status_controls_are_exact_native_aliases(
    capability: str, method: str, status: str
) -> None:
    invocation = build_native_invocation(capability, {}, thread_id="thread")
    assert invocation.method == method
    assert invocation.params == {"threadId": "thread", "status": status}


def test_settings_accepts_supported_max_and_rejects_ultra() -> None:
    invocation = build_native_invocation(
        "settings_update",
        {"model": "gpt-a", "effort": "max"},
        thread_id="thread",
        current_model="gpt-b",
        supported_models=CATALOG,
    )
    assert invocation.params == {"threadId": "thread", "model": "gpt-a", "effort": "max"}

    with pytest.raises(CodexNativeContractError) as error:
        build_native_invocation(
            "settings_update",
            {"model": "gpt-a", "effort": "ultra"},
            thread_id="thread",
            supported_models=CATALOG,
        )
    assert error.value.code == "codex_native_effort_unsupported"


def test_console_plan_turn_preserves_read_only_policy_and_native_mode() -> None:
    invocation = build_native_invocation(
        "console_turn_start",
        {"text": "Create a plan", "mode": "plan"},
        thread_id="thread",
        current_model="gpt-a",
        current_effort="max",
    )

    assert invocation.method == "turn/start"
    assert invocation.params == {
        "threadId": "thread",
        "input": [{"type": "text", "text": "Create a plan"}],
        "approvalPolicy": "never",
        "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        "collaborationMode": {
            "mode": "plan",
            "settings": {
                "model": "gpt-a",
                "reasoning_effort": "max",
                "developer_instructions": None,
            },
        },
    }


def test_steer_only_accepts_text_and_internal_turn_identity() -> None:
    invocation = build_native_invocation(
        "turn_steer",
        {"text": "Focus on transactions"},
        thread_id="private-thread",
        active_turn_id="private-turn",
    )
    assert invocation.params == {
        "threadId": "private-thread",
        "expectedTurnId": "private-turn",
        "input": [{"type": "text", "text": "Focus on transactions"}],
    }
    with pytest.raises(CodexNativeContractError, match="request_shape"):
        build_native_invocation(
            "turn_steer",
            {"text": "x", "image": "forbidden"},
            thread_id="thread",
            active_turn_id="turn",
        )


@pytest.mark.parametrize(
    ("kind", "resolved"),
    [
        ("uncommitted", {"type": "uncommittedChanges"}),
        ("base", {"type": "baseBranch", "branch": "main"}),
        ("commit", {"type": "commit", "sha": "a" * 40}),
    ],
)
def test_review_uses_only_server_resolved_native_targets(
    kind: str, resolved: dict[str, object]
) -> None:
    invocation = build_native_invocation(
        "review_start",
        {"target": kind},
        thread_id="thread",
        resolved_review_target=resolved,
    )
    assert invocation.params == {
        "threadId": "thread",
        "target": resolved,
        "delivery": "inline",
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        {"cwd": "/tmp"},
        {"approvalPolicy": "on-request"},
        {"sandboxPolicy": {"type": "dangerFullAccess"}},
        {"permissions": "full"},
        {"raw_params": {}},
    ],
)
def test_browser_cannot_forward_privileged_native_fields(forbidden: dict[str, object]) -> None:
    with pytest.raises(CodexNativeContractError) as error:
        build_native_invocation(
            "goal_get",
            forbidden,
            thread_id="thread",
        )
    assert error.value.code == "codex_native_request_shape_invalid"


def test_models_list_is_fixed_hidden_filtered_page_request() -> None:
    invocation = build_native_invocation("models_list", {}, thread_id="not-forwarded")
    assert invocation.method == "model/list"
    assert invocation.params == {"includeHidden": False, "limit": 100}
