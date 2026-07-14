from __future__ import annotations

from collections.abc import Mapping

import pytest

from xmuse_core.agents.codex_native_adapter import (
    CodexNativeAdapter,
    CodexNativeAdapterError,
    NativeModelCatalog,
)


def _model(model_id: str, *, hidden: bool = False) -> dict[str, object]:
    return {
        "id": model_id,
        "model": model_id,
        "displayName": model_id.upper(),
        "description": "A model",
        "hidden": hidden,
        "isDefault": model_id == "gpt-a",
        "defaultReasoningEffort": "max",
        "supportedReasoningEfforts": [
            {"reasoningEffort": "low", "description": "Low"},
            {"reasoningEffort": "max", "description": "Maximum"},
            {"reasoningEffort": "ultra", "description": "Delegating"},
        ],
    }


class Rpc:
    def __init__(self, responses: Mapping[str, list[object]]) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def request(self, method: str, params: Mapping[str, object]) -> object:
        self.calls.append((method, dict(params)))
        values = self.responses.get(method)
        if not values:
            raise RuntimeError("unsupported")
        return values.pop(0)


@pytest.mark.asyncio
async def test_model_discovery_pages_filters_hidden_and_ultra() -> None:
    rpc = Rpc(
        {
            "model/list": [
                {"data": [_model("gpt-a"), _model("hidden", hidden=True)], "nextCursor": "p2"},
                {"data": [_model("gpt-b")], "nextCursor": None},
            ]
        }
    )
    catalog = await CodexNativeAdapter(rpc).list_models()

    assert [item["id"] for item in catalog.models] == ["gpt-a", "gpt-b"]
    assert catalog.supported_efforts == {
        "gpt-a": frozenset({"low", "max"}),
        "gpt-b": frozenset({"low", "max"}),
    }
    assert rpc.calls == [
        ("model/list", {"includeHidden": False, "limit": 100}),
        ("model/list", {"includeHidden": False, "limit": 100, "cursor": "p2"}),
    ]


@pytest.mark.asyncio
async def test_model_discovery_rejects_cursor_cycle() -> None:
    rpc = Rpc(
        {
            "model/list": [
                {"data": [], "nextCursor": "same"},
                {"data": [], "nextCursor": "same"},
            ]
        }
    )
    with pytest.raises(CodexNativeAdapterError) as error:
        await CodexNativeAdapter(rpc).list_models()
    assert error.value.code == "codex_native_model_cursor_invalid"


@pytest.mark.asyncio
async def test_snapshot_is_safe_and_uses_opaque_guards() -> None:
    rpc = Rpc(
        {
            "thread/goal/get": [
                {
                    "goal": {
                        "threadId": "must-not-project",
                        "objective": "Inspect transactions",
                        "status": "active",
                        "tokenBudget": 100_000,
                        "tokensUsed": 42,
                        "timeUsedSeconds": 3,
                        "createdAt": 1,
                        "updatedAt": 2,
                    }
                }
            ]
        }
    )
    snapshot = await CodexNativeAdapter(rpc).snapshot(
        thread_id="private-thread",
        session_identity="private-thread",
        connection_generation=7,
        current_model="gpt-a",
        current_effort="max",
        active_turn_id="private-turn",
    )

    serialized = str(snapshot)
    assert "private-thread" not in serialized and "private-turn" not in serialized
    assert snapshot["goal"] == {
        "objective": "Inspect transactions",
        "status": "active",
        "token_budget": 100_000,
        "tokens_used": 42,
        "time_used_seconds": 3,
    }
    guards = snapshot["guards"]
    assert isinstance(guards, dict)
    assert all(
        value is None or (isinstance(value, str) and value.startswith("sha256:"))
        for value in guards.values()
    )


@pytest.mark.asyncio
async def test_goal_guard_ignores_accounting_churn_but_fences_control_changes() -> None:
    def response(
        *,
        objective: str = "Inspect transactions",
        status: str = "active",
        budget: int = 100_000,
        used: int = 0,
        elapsed: int = 0,
    ) -> dict[str, object]:
        return {
            "goal": {
                "objective": objective,
                "status": status,
                "tokenBudget": budget,
                "tokensUsed": used,
                "timeUsedSeconds": elapsed,
            }
        }

    rpc = Rpc(
        {
            "thread/goal/get": [
                response(),
                response(used=42_000, elapsed=60),
                response(objective="Inspect recovery"),
                response(status="paused"),
                response(budget=200_000),
            ]
        }
    )
    adapter = CodexNativeAdapter(rpc)

    async def goal_guard() -> object:
        snapshot = await adapter.snapshot(
            thread_id="private-thread",
            session_identity="private-thread",
            connection_generation=7,
            current_model="gpt-a",
            current_effort="max",
            active_turn_id=None,
        )
        guards = snapshot["guards"]
        assert isinstance(guards, dict)
        return guards["goal"]

    initial, accounting, objective, status, budget = [await goal_guard() for _ in range(5)]
    assert accounting == initial
    assert len({initial, objective, status, budget}) == 4


@pytest.mark.asyncio
async def test_invoke_rebuilds_payload_and_returns_only_safe_ack() -> None:
    rpc = Rpc({"thread/settings/update": [{}]})
    adapter = CodexNativeAdapter(rpc)
    result = await adapter.invoke(
        "settings_update",
        {"model": "gpt-a", "effort": "max"},
        thread_id="private-thread",
        active_turn_id=None,
        current_model="gpt-a",
        current_effort="low",
        catalog=NativeModelCatalog((), {"gpt-a": frozenset({"low", "max"})}),
    )

    assert rpc.calls == [
        (
            "thread/settings/update",
            {"threadId": "private-thread", "model": "gpt-a", "effort": "max"},
        )
    ]
    assert result.safe_ack == {
        "native_method": "thread/settings/update",
        "acknowledged": True,
    }
    assert "private-thread" not in str(result.safe_ack)


@pytest.mark.asyncio
async def test_capability_descriptor_distinguishes_runtime_support() -> None:
    rpc = Rpc(
        {
            "thread/goal/get": [{"goal": None}],
            "model/list": [{"data": [_model("gpt-a")], "nextCursor": None}],
        }
    )
    descriptor, _catalog = await CodexNativeAdapter(rpc).discover_capabilities(
        thread_id="private-thread",
        session_guard="sha256:" + "a" * 64,
    )
    capabilities = {
        item["capability_id"]: item for item in descriptor["capabilities"] if isinstance(item, dict)
    }
    assert capabilities["goal_set"]["availability"] == "available"
    assert capabilities["settings_update"]["availability"] == "available"
    assert all("private-thread" not in str(item) for item in capabilities.values())
