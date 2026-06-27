from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.integrations.a2a_provider_client import A2AProviderTaskRequest
from xmuse_core.integrations.a2a_sdk_boundary import NormalizedA2ATaskResult
from xmuse_core.providers.adapters.a2a import A2AProviderAdapter
from xmuse_core.providers.adapters.base import (
    ProviderAdapter,
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationWritebackContext,
)
from xmuse_core.providers.goal_contract import (
    WorkerGoalContract,
    WorkerResultStatus,
)
from xmuse_core.providers.models import (
    ProviderId,
    ProviderProfile,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)
from xmuse_core.providers.registry import build_default_provider_registry
from xmuse_core.providers.service import RunnerProviderService


class FakeA2ATaskClient:
    def __init__(self, result: NormalizedA2ATaskResult) -> None:
        self.result = result
        self.requests: list[A2AProviderTaskRequest] = []

    async def invoke_task(
        self,
        request: A2AProviderTaskRequest,
    ) -> NormalizedA2ATaskResult:
        self.requests.append(request)
        return self.result


def _profile() -> ProviderProfile:
    return build_default_provider_registry().get("a2a.remote")


def _goal_contract() -> WorkerGoalContract:
    return WorkerGoalContract(
        request_id="req-a2a",
        lane_id="lane-a2a",
        provider_id=ProviderId.A2A,
        provider_profile_id=ProviderProfileId.REMOTE,
        goal="Ask remote A2A participant for a bounded review.",
        acceptance_criteria=["Return a normalized provider result only."],
        blueprint_refs=["docs/xmuse/natural-groupchat-contract.md"],
    )


def _invocation(tmp_path: Path) -> ProviderInvocation:
    return RunnerProviderService().build_review_invocation(
        lane_id="lane-a2a",
        prompt="@remote review the proposed handoff.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="a2a.remote",
        risk_tier=RiskTier.MEDIUM,
    ).model_copy(update={"request_id": "req-a2a", "goal_contract": _goal_contract()})


def _task_result(
    *,
    disposition: str,
    state: str,
    metadata: dict[str, object] | None = None,
) -> NormalizedA2ATaskResult:
    return NormalizedA2ATaskResult(
        task_id="req-a2a",
        context_id="lane-a2a",
        state=state,
        disposition=disposition,
        terminal=True,
        content="remote result",
        artifacts=({"artifact_id": "artifact-a2a", "text": "artifact text"},),
        history=({"message_id": "message-a2a", "text": "history text"},),
        metadata=metadata or {},
        source_refs=("a2a_task:req-a2a", "a2a_context:lane-a2a"),
        sdk_task={"id": "req-a2a", "status": {"state": state}},
        jsonrpc_id="req-a2a",
    )


def test_a2a_provider_adapter_maps_completed_task_to_provider_result(tmp_path) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        api_key="secret",
        client=client,
        checked_at_factory=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    result = adapter.invoke(_invocation(tmp_path))

    assert isinstance(adapter, ProviderAdapter)
    assert result.provider_profile_ref == "a2a.remote"
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.failure_kind is None
    assert result.evidence_refs == [
        "a2a_task:req-a2a",
        "a2a_context:lane-a2a",
        "a2a_state:TASK_STATE_COMPLETED",
        "a2a_disposition:completed",
        "a2a_jsonrpc:req-a2a",
    ]
    assert result.diagnostic_payload == {
        "a2a_task_id": "req-a2a",
        "a2a_context_id": "lane-a2a",
        "a2a_state": "TASK_STATE_COMPLETED",
        "a2a_disposition": "completed",
        "a2a_terminal": True,
        "a2a_content": "remote result",
        "a2a_artifacts": [{"artifact_id": "artifact-a2a", "text": "artifact text"}],
        "a2a_history": [{"message_id": "message-a2a", "text": "history text"}],
        "a2a_metadata": {},
        "a2a_source_refs": ["a2a_task:req-a2a", "a2a_context:lane-a2a"],
        "a2a_sdk_task": {"id": "req-a2a", "status": {"state": "TASK_STATE_COMPLETED"}},
        "a2a_jsonrpc_id": "req-a2a",
    }
    assert client.requests[0].task_id == "req-a2a"
    assert client.requests[0].context_id == "lane-a2a"
    assert client.requests[0].sender_agent_id == "xmuse:a2a.remote"
    assert client.requests[0].metadata["xmuse_task_type"] == "review"
    assert client.requests[0].metadata["xmuse_goal_contract"] == {
        "lane_id": "lane-a2a",
        "acceptance_criteria": ["Return a normalized provider result only."],
        "blueprint_refs": ["docs/xmuse/natural-groupchat-contract.md"],
    }
    assert client.requests[0].metadata["xmuse_expected_result"] == {
        "schema_version": 1,
        "result_kind": "platform_review_verdict",
        "consumer": "xmuse.review_god",
        "metadata_key": "xmuse_platform_review_verdict",
        "required_metadata_path": [
            "task.metadata.xmuse_platform_review_verdict",
        ],
        "envelope": {
            "schema_version": 1,
            "type": "platform_review_verdict",
            "lane_id": "lane-a2a",
            "decision_values": ["merge", "rework", "terminate"],
            "required_fields": [
                "type",
                "lane_id",
                "decision",
                "summary",
                "evidence_refs",
                "authority",
                "a2a_is_authority",
            ],
            "authority": "review_plane/lane_state",
            "a2a_is_authority": False,
        },
        "stdout_is_review_truth": False,
        "a2a_task_status_is_review_truth": False,
    }


def test_a2a_provider_adapter_derives_review_lane_context_without_goal_contract(
    tmp_path,
) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=client,
    )
    invocation = RunnerProviderService().build_review_invocation(
        lane_id="lane-a2a-no-contract",
        prompt="@remote review the proposed handoff.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="a2a.remote",
        risk_tier=RiskTier.MEDIUM,
    )

    adapter.invoke(invocation)

    request = client.requests[0]
    assert request.task_id == "lane-a2a-no-contract:review"
    assert request.context_id == "lane-a2a-no-contract"
    expected = request.metadata["xmuse_expected_result"]
    assert isinstance(expected, dict)
    envelope = expected["envelope"]
    assert isinstance(envelope, dict)
    assert envelope["lane_id"] == "lane-a2a-no-contract"
    assert envelope["authority"] == "review_plane/lane_state"
    assert envelope["a2a_is_authority"] is False
    assert expected["stdout_is_review_truth"] is False
    assert expected["a2a_task_status_is_review_truth"] is False


def test_a2a_provider_adapter_includes_xmuse_context_metadata(tmp_path) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=client,
    )
    invocation = _invocation(tmp_path).model_copy(
        update={
            "writeback_context": ProviderInvocationWritebackContext(
                conversation_id="conv-a2a",
                participant_id="participant-review",
                reply_to_inbox_item_id="inbox-a2a",
            ),
            "runtime_context": {
                "authority": "chat.db/inbox",
                "a2a_is_authority": False,
                "route": {
                    "route_key": "natural-route:abc",
                    "source_kind": "human_line_start_mention",
                    "depth": 1,
                    "source_refs": ["message:1"],
                },
            },
        }
    )

    adapter.invoke(invocation)

    metadata = client.requests[0].metadata
    assert metadata["xmuse_writeback_context"] == {
        "conversation_id": "conv-a2a",
        "participant_id": "participant-review",
        "reply_to_inbox_item_id": "inbox-a2a",
    }
    assert metadata["xmuse_runtime_context"] == {
        "authority": "chat.db/inbox",
        "a2a_is_authority": False,
        "route": {
            "route_key": "natural-route:abc",
            "source_kind": "human_line_start_mention",
            "depth": 1,
            "source_refs": ["message:1"],
        },
    }


def test_a2a_provider_adapter_uses_conversation_context_for_natural_route(
    tmp_path,
) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=client,
    )
    invocation = ProviderInvocation(
        request_id="inbox-a2a-natural",
        provider_id=ProviderId.A2A,
        profile_id=ProviderProfileId.REMOTE,
        task_type=TaskCapability.BOUNDED_DELIBERATION,
        risk_tier=RiskTier.MEDIUM,
        prompt="@review inspect natural handoff.",
        workspace=tmp_path,
        timeout_seconds=120,
        writeback_context=ProviderInvocationWritebackContext(
            conversation_id="conv-natural",
            participant_id="participant-a2a",
            reply_to_inbox_item_id="inbox-a2a-natural",
        ),
        runtime_context={
            "authority": "chat.db/inbox",
            "a2a_is_authority": False,
            "route": {
                "route_key": "natural-route:abc",
                "source_kind": "human_line_start_mention",
                "depth": 1,
            },
        },
    )

    adapter.invoke(invocation)

    request = client.requests[0]
    assert request.task_id == "inbox-a2a-natural"
    assert request.context_id == "conv-natural"
    assert request.metadata["xmuse_writeback_context"]["conversation_id"] == (
        "conv-natural"
    )
    assert request.metadata["xmuse_runtime_context"]["route"]["route_key"] == (
        "natural-route:abc"
    )


def test_a2a_provider_adapter_marks_task_metadata_as_non_authority(tmp_path) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=client,
    )
    invocation = RunnerProviderService().build_execution_invocation(
        lane_id="lane-a2a-execute",
        prompt="@remote execute this bounded lane.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="a2a.remote",
        risk_tier=RiskTier.MEDIUM,
        lane={
            "feature_id": "lane-a2a-execute",
            "task_type": "execute",
            "capabilities": ["code"],
        },
    )

    adapter.invoke(invocation)

    metadata = client.requests[0].metadata
    assert metadata["xmuse_authority"] == (
        "chat.db/inbox/proposal/review/dispatch/final_gates"
    )
    assert metadata["a2a_is_authority"] is False
    assert metadata["a2a_task_status_is_authority"] is False
    assert metadata["provider_stdout_is_authority"] is False


def test_a2a_provider_adapter_maps_blocked_task_without_failure_kind(tmp_path) -> None:
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=FakeA2ATaskClient(
            _task_result(disposition="blocked", state="TASK_STATE_INPUT_REQUIRED")
        ),
    )

    result = adapter.invoke(_invocation(tmp_path))

    assert result.status is WorkerResultStatus.BLOCKED
    assert result.failure_kind is None
    assert "a2a_disposition:blocked" in result.evidence_refs


def test_a2a_provider_adapter_maps_failed_transport_to_failed_result(tmp_path) -> None:
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=FakeA2ATaskClient(
            _task_result(
                disposition="failed",
                state="TASK_STATE_FAILED",
                metadata={"transport_error": "ConnectError"},
            )
        ),
    )

    result = adapter.invoke(_invocation(tmp_path))

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.UNAVAILABLE
    assert "a2a_state:TASK_STATE_FAILED" in result.evidence_refs


def test_a2a_provider_adapter_rejects_unsupported_capability(tmp_path) -> None:
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        client=FakeA2ATaskClient(
            _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
        ),
    )

    result = adapter.invoke(
        _invocation(tmp_path).model_copy(
            update={"task_type": TaskCapability.MERGE_FINAL_REVIEW}
        )
    )

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.UNSUPPORTED_CAPABILITY
    assert result.evidence_refs == ["a2a_adapter:unsupported_capability"]


def test_a2a_provider_adapter_health_reports_configured_contract() -> None:
    adapter = A2AProviderAdapter(
        _profile(),
        endpoint_url="https://remote.example/a2a",
        checked_at_factory=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    snapshot = adapter.check_health()

    assert snapshot.provider_profile_ref == "a2a.remote"
    assert snapshot.is_configured is True
    assert snapshot.is_available is True
    assert snapshot.auth_ok is True
    assert snapshot.diagnostic_summary == (
        "A2A adapter configured; live remote health not probed."
    )


def test_runner_provider_service_recognizes_explicit_a2a_runtime(tmp_path) -> None:
    service = RunnerProviderService()

    invocation = service.build_review_invocation(
        lane_id="lane-a2a",
        prompt="@remote review the proposed handoff.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="a2a.remote",
        risk_tier=RiskTier.MEDIUM,
    )

    assert invocation.provider_profile_ref == "a2a.remote"
    assert service.runtime_for_invocation(invocation) == "a2a"
    assert service.supports_persistent_execute(invocation) is False


def test_runner_provider_service_maps_explicit_a2a_execute_lane_to_bounded_code(
    tmp_path,
) -> None:
    service = RunnerProviderService()

    invocation = service.build_execution_invocation(
        lane_id="lane-a2a-execute",
        prompt="Execute the bounded lane through A2A.",
        workspace=tmp_path,
        timeout_seconds=120,
        provider_profile_ref="a2a.remote",
        risk_tier=RiskTier.MEDIUM,
        lane={
            "feature_id": "lane-a2a-execute",
            "task_type": "execute",
            "capabilities": ["code"],
        },
    )

    assert invocation.provider_profile_ref == "a2a.remote"
    assert invocation.task_type is TaskCapability.BOUNDED_CODE_WRITING
    assert service.runtime_for_invocation(invocation) == "a2a"


def test_runner_provider_service_invokes_configured_a2a_adapter(tmp_path) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    service = RunnerProviderService(
        a2a_provider_endpoint_url="https://remote.example/a2a",
        a2a_provider_api_key="secret",
        a2a_task_client=client,
    )

    result = service.invoke_provider_adapter(_invocation(tmp_path))

    assert result.provider_profile_ref == "a2a.remote"
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.failure_kind is None
    assert client.requests[0].task_id == "req-a2a"
    assert client.requests[0].sender_agent_id == "xmuse:a2a.remote"


def test_runner_provider_service_fails_closed_when_a2a_endpoint_missing(tmp_path) -> None:
    client = FakeA2ATaskClient(
        _task_result(disposition="completed", state="TASK_STATE_COMPLETED")
    )
    service = RunnerProviderService(a2a_task_client=client)

    result = service.invoke_provider_adapter(_invocation(tmp_path))

    assert result.provider_profile_ref == "a2a.remote"
    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.CONFIG_ERROR
    assert result.evidence_refs == [
        "a2a_adapter:config_error",
        "a2a_adapter_error:ValueError",
    ]
    assert client.requests == []
