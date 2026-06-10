from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.agents.provider_session_binding_store import (
    ProviderSessionBindingCompatibility,
    ProviderSessionBindingStore,
)
from xmuse_core.providers.adapters.base import ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.session_binding import (
    build_provider_session_binding_from_result,
    upsert_provider_session_binding_from_result,
)
from xmuse_core.structuring.models import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


def _binding(
    *,
    binding_id: str = "psb-1",
    god_session_id: str = "god-worker-1",
    provider: str = "codex",
    provider_session_id: str = "codex-session-11111111-2222-3333-4444-555555555555",
    status: ProviderSessionBindingStatus = ProviderSessionBindingStatus.ACTIVE,
    model: str = "gpt-5.2-codex",
    worktree: str = "/worktrees/feature-a",
    prompt_fingerprint: str = "sha256:prompt-a",
    feature_graph_id: str = "graph-feature-a",
) -> ProviderSessionBindingRecord:
    return ProviderSessionBindingRecord(
        binding_id=binding_id,
        god_session_id=god_session_id,
        provider=provider,
        provider_session_id=provider_session_id,
        session_kind="exec",
        status=status,
        conversation_id="conv-1",
        feature_graph_id=feature_graph_id,
        role="feature_worker",
        cwd="/repo",
        worktree=worktree,
        model=model,
        prompt_fingerprint=prompt_fingerprint,
        created_at="2026-06-03T02:10:00Z",
        last_used_at="2026-06-03T02:11:00Z",
        last_verified_at="2026-06-03T02:11:30Z",
        resume_command_template="codex exec resume {provider_session_id} {prompt}",
    )


def test_binding_store_upserts_and_finds_active_binding(tmp_path: Path) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = _binding()

    stored = store.upsert_active(binding)
    found = store.find_active(god_session_id="god-worker-1", provider="codex", kind="exec")

    assert stored == binding
    assert found == binding
    raw = json.loads((tmp_path / "provider_session_bindings.json").read_text())
    assert raw["schema_version"] == "xmuse.provider_session_bindings.v1"
    assert raw["bindings"][0]["provider_session_id"] == binding.provider_session_id


def test_binding_store_replaces_active_binding_for_same_provider_kind(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    first = _binding(binding_id="psb-old")
    second = _binding(
        binding_id="psb-new",
        provider_session_id="codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    store.upsert_active(first)
    store.upsert_active(second)

    records = store.list_for_god_session("god-worker-1")
    assert [record.binding_id for record in records] == ["psb-old", "psb-new"]
    assert records[0].status is ProviderSessionBindingStatus.RETIRED
    assert store.find_active(
        god_session_id="god-worker-1",
        provider="codex",
        kind="exec",
    ).binding_id == "psb-new"


def test_binding_store_rejects_conflicting_binding_id_replay(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    original = _binding()
    store.upsert_active(original)
    conflicting = original.model_copy(update={"model": "gpt-5.3-codex"})

    with pytest.raises(ValueError, match="provider session binding replay conflict"):
        store.upsert_active(conflicting)

    assert store.get(original.binding_id) == original
    assert store.find_active(
        god_session_id="god-worker-1",
        provider="codex",
        kind="exec",
    ) == original


def test_binding_store_rejects_retired_binding_reactivation_by_replay(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    first = _binding(binding_id="psb-old")
    second = _binding(
        binding_id="psb-new",
        provider_session_id="codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    store.upsert_active(first)
    store.upsert_active(second)

    with pytest.raises(ValueError, match="provider session binding replay conflict"):
        store.upsert_active(first)

    records = store.list_for_god_session("god-worker-1")
    assert [record.binding_id for record in records] == ["psb-old", "psb-new"]
    assert records[0].status is ProviderSessionBindingStatus.RETIRED
    assert records[1].status is ProviderSessionBindingStatus.ACTIVE
    assert (
        store.find_active(god_session_id="god-worker-1", provider="codex", kind="exec")
        == records[1]
    )


def test_binding_store_requires_resume_compatible_identity(tmp_path: Path) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(_binding())

    compatible = store.find_resume_compatible(
        god_session_id="god-worker-1",
        provider="codex",
        kind="exec",
        model="gpt-5.2-codex",
        worktree="/worktrees/feature-a",
        prompt_fingerprint="sha256:prompt-a",
        feature_graph_id="graph-feature-a",
    )

    assert isinstance(compatible, ProviderSessionBindingCompatibility)
    assert compatible.compatible is True
    assert compatible.binding is not None

    incompatible = store.find_resume_compatible(
        god_session_id="god-worker-1",
        provider="codex",
        kind="exec",
        model="gpt-5.2-codex",
        worktree="/worktrees/feature-a",
        prompt_fingerprint="sha256:different",
        feature_graph_id="graph-feature-a",
    )

    assert incompatible.compatible is False
    assert incompatible.binding is None
    assert incompatible.reason == "prompt_fingerprint_mismatch"


def test_binding_store_marks_binding_failed_and_excludes_from_active(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(_binding())

    failed = store.mark_failed(
        "psb-1",
        status=ProviderSessionBindingStatus.FAILED,
        reason="resume returned non-zero",
        failed_at="2026-06-03T02:15:00Z",
    )

    assert failed.status is ProviderSessionBindingStatus.FAILED
    assert failed.failure_reason == "resume returned non-zero"
    with pytest.raises(KeyError, match="active provider session binding not found"):
        store.find_active(god_session_id="god-worker-1", provider="codex", kind="exec")


def test_binding_store_rejects_last_session_aliases_before_persisting(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")

    with pytest.raises(ValueError, match="last-session aliases are forbidden"):
        store.upsert_active(
            _binding(provider_session_id="codex-session-11111111-2222-3333-4444-555555555555").model_copy(
                update={"provider_session_id": "--last"}
            )
        )

    assert not (tmp_path / "provider_session_bindings.json").exists()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (["not-an-object-payload"], "provider session binding payload must be an object"),
        (
            {
                "schema_version": "xmuse.provider_session_bindings.v1",
                "bindings": {"binding_id": "not-a-list"},
            },
            "provider session bindings must be a list",
        ),
        (
            {
                "schema_version": "xmuse.provider_session_bindings.v1",
                "bindings": ["not-a-binding-object"],
            },
            "provider session binding must be an object",
        ),
    ],
)
def test_binding_store_rejects_corrupt_binding_payload(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = tmp_path / "provider_session_bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = ProviderSessionBindingStore(path)

    with pytest.raises(ValueError, match=message):
        store.list()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (["not-an-object-payload"], "provider session binding payload must be an object"),
        (
            {
                "schema_version": "xmuse.provider_session_bindings.v1",
                "bindings": {"binding_id": "not-a-list"},
            },
            "provider session bindings must be a list",
        ),
        (
            {
                "schema_version": "xmuse.provider_session_bindings.v1",
                "bindings": ["not-a-binding-object"],
            },
            "provider session binding must be an object",
        ),
    ],
)
def test_binding_store_preserves_corrupt_binding_payload_on_upsert(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = tmp_path / "provider_session_bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    store = ProviderSessionBindingStore(path)

    with pytest.raises(ValueError, match=message):
        store.upsert_active(_binding())

    assert path.read_text(encoding="utf-8") == before


def test_build_provider_session_binding_from_successful_provider_result(
    tmp_path: Path,
) -> None:
    invocation = _provider_invocation(tmp_path)
    result = _provider_result()

    binding = build_provider_session_binding_from_result(
        invocation=invocation,
        result=result,
        god_session_id="god-worker-1",
        role="feature_worker",
        created_at="2026-06-03T02:20:00Z",
        conversation_id="conv-1",
        feature_graph_id="graph-feature-a",
        prompt_fingerprint="sha256:prompt-a",
        model="gpt-5.2-codex",
    )

    assert binding.binding_id == (
        "psb:god-worker-1:codex:exec:"
        "codex-session-11111111-2222-3333-4444-555555555555"
    )
    assert binding.provider == "codex"
    assert binding.provider_session_id == (
        "codex-session-11111111-2222-3333-4444-555555555555"
    )
    assert binding.session_kind == "exec"
    assert binding.status is ProviderSessionBindingStatus.ACTIVE
    assert binding.cwd == str(tmp_path)
    assert binding.worktree == str(tmp_path)
    assert binding.conversation_id == "conv-1"
    assert binding.feature_graph_id == "graph-feature-a"
    assert binding.model == "gpt-5.2-codex"
    assert binding.prompt_fingerprint == "sha256:prompt-a"
    assert binding.resume_command_template == "codex exec resume {provider_session_id}"

    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    assert store.upsert_active(binding) == binding
    assert (
        store.find_active(god_session_id="god-worker-1", provider="codex", kind="exec")
        == binding
    )


def test_build_review_provider_session_binding_from_successful_provider_result(
    tmp_path: Path,
) -> None:
    invocation = _provider_invocation(tmp_path).model_copy(
        update={
            "profile_id": ProviderProfileId.REVIEW,
            "task_type": TaskCapability.REVIEW,
        }
    )
    result = _provider_result().model_copy(update={"profile_id": ProviderProfileId.REVIEW})

    binding = build_provider_session_binding_from_result(
        invocation=invocation,
        result=result,
        god_session_id="god-review-1",
        role="reviewer",
        created_at="2026-06-03T02:20:00Z",
        session_kind="review",
    )

    assert binding.session_kind == "review"
    assert binding.role == "reviewer"
    assert binding.resume_command_template == "codex exec resume {provider_session_id}"


def test_build_provider_session_binding_requires_explicit_successful_result(
    tmp_path: Path,
) -> None:
    invocation = _provider_invocation(tmp_path)

    with pytest.raises(ValueError, match="successful provider result"):
        build_provider_session_binding_from_result(
            invocation=invocation,
            result=_provider_result(status=WorkerResultStatus.FAILED),
            god_session_id="god-worker-1",
            role="feature_worker",
            created_at="2026-06-03T02:20:00Z",
        )

    with pytest.raises(ValueError, match="provider_session_id"):
        build_provider_session_binding_from_result(
            invocation=invocation,
            result=_provider_result(provider_session_id=None),
            god_session_id="god-worker-1",
            role="feature_worker",
            created_at="2026-06-03T02:20:00Z",
        )

    bypassed = _provider_result().model_copy(update={"provider_session_id": "--last"})
    with pytest.raises(ValueError, match="last-session aliases are forbidden"):
        build_provider_session_binding_from_result(
            invocation=invocation,
            result=bypassed,
            god_session_id="god-worker-1",
            role="feature_worker",
            created_at="2026-06-03T02:20:00Z",
        )


def test_upsert_provider_session_binding_from_result_is_idempotent_for_replay(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    invocation = _provider_invocation(tmp_path)
    result = _provider_result()

    first = upsert_provider_session_binding_from_result(
        store=store,
        invocation=invocation,
        result=result,
        god_session_id="god-worker-1",
        role="feature_worker",
        created_at="2026-06-03T02:20:00Z",
        conversation_id="conv-1",
        feature_graph_id="graph-feature-a",
        prompt_fingerprint="sha256:prompt-a",
        model="gpt-5.2-codex",
    )
    replayed = upsert_provider_session_binding_from_result(
        store=store,
        invocation=invocation,
        result=result,
        god_session_id="god-worker-1",
        role="feature_worker",
        created_at="2026-06-03T02:20:00Z",
        conversation_id="conv-1",
        feature_graph_id="graph-feature-a",
        prompt_fingerprint="sha256:prompt-a",
        model="gpt-5.2-codex",
    )

    assert replayed == first
    assert store.list_for_god_session("god-worker-1") == [first]


def test_upsert_provider_session_binding_from_result_retires_previous_active_slot(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    invocation = _provider_invocation(tmp_path)
    first = upsert_provider_session_binding_from_result(
        store=store,
        invocation=invocation,
        result=_provider_result(),
        god_session_id="god-worker-1",
        role="feature_worker",
        created_at="2026-06-03T02:20:00Z",
        conversation_id="conv-1",
        feature_graph_id="graph-feature-a",
        prompt_fingerprint="sha256:prompt-a",
        model="gpt-5.2-codex",
    )
    second = upsert_provider_session_binding_from_result(
        store=store,
        invocation=invocation,
        result=_provider_result(
            provider_session_id="codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        ),
        god_session_id="god-worker-1",
        role="feature_worker",
        created_at="2026-06-03T02:25:00Z",
        conversation_id="conv-1",
        feature_graph_id="graph-feature-a",
        prompt_fingerprint="sha256:prompt-a",
        model="gpt-5.2-codex",
    )

    records = store.list_for_god_session("god-worker-1")
    assert [record.binding_id for record in records] == [first.binding_id, second.binding_id]
    assert records[0].status is ProviderSessionBindingStatus.RETIRED
    assert records[1].status is ProviderSessionBindingStatus.ACTIVE
    assert (
        store.find_active(god_session_id="god-worker-1", provider="codex", kind="exec")
        == second
    )


def _provider_invocation(tmp_path: Path):
    from xmuse_core.providers.adapters.base import ProviderInvocation

    return ProviderInvocation(
        request_id="lane-1:execute",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.DEFAULT,
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Continue feature graph.",
        workspace=tmp_path,
        timeout_seconds=120,
    )


def _provider_result(
    *,
    status: WorkerResultStatus = WorkerResultStatus.COMPLETED,
    provider_session_id: str | None = (
        "codex-session-11111111-2222-3333-4444-555555555555"
    ),
) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id="lane-1:execute",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.DEFAULT,
        status=status,
        provider_session_id=provider_session_id,
        evidence_refs=[],
        failure_kind=None if status is not WorkerResultStatus.FAILED else "non_zero_exit",
    )
