from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from xmuse_core.providers.adapters.base import ProviderInvocation
from xmuse_core.structuring.feature_review_contracts import ProviderSessionBindingRecord


class ExecutionProviderSessionBindingStore(Protocol):
    def find_resume_compatible(
        self,
        *,
        god_session_id: str,
        provider: str,
        kind: str,
        model: str | None,
        worktree: str | None,
        prompt_fingerprint: str | None,
        feature_graph_id: str | None,
    ): ...


class ExecutionRuntimeProviderAdapter(Protocol):
    def supports_explicit_session_resume(self, invocation: ProviderInvocation) -> bool: ...

    def supports_persistent_execute(self, invocation: ProviderInvocation) -> bool: ...


class ExecutionFeatureGraphStatusStore(Protocol):
    def get(
        self,
        *,
        graph_set_id: str,
        feature_graph_id: str,
    ): ...


@dataclass(frozen=True)
class ExecutionRuntimeSessionRoute:
    primary_path: Literal["explicit_provider_resume", "persistent_execute_or_fallback"]
    provider_session_binding: ProviderSessionBindingRecord | None = None
    allows_persistent_execute: bool = True
    persistent_execute_unsupported_reason: str | None = None


@dataclass(frozen=True)
class ReviewRuntimeSessionRoute:
    primary_path: Literal["explicit_provider_resume", "persistent_review_or_fallback"]
    provider_session_binding: ProviderSessionBindingRecord | None = None


def plan_execution_runtime_session_route(
    *,
    store: ExecutionProviderSessionBindingStore,
    provider_adapter: ExecutionRuntimeProviderAdapter,
    lane: Mapping[str, Any],
    invocation: ProviderInvocation,
    model: str | None,
    prompt_fingerprint: str | None,
    feature_graph_status_store: ExecutionFeatureGraphStatusStore | None = None,
) -> ExecutionRuntimeSessionRoute:
    if not provider_adapter.supports_explicit_session_resume(invocation):
        if not provider_adapter.supports_persistent_execute(invocation):
            return ExecutionRuntimeSessionRoute(
                primary_path="persistent_execute_or_fallback",
                allows_persistent_execute=False,
                persistent_execute_unsupported_reason=(
                    "provider_persistent_execute_unsupported"
                ),
            )
        return ExecutionRuntimeSessionRoute(
            primary_path="persistent_execute_or_fallback",
        )
    binding = resolve_execution_provider_session_binding(
        store=store,
        lane=lane,
        invocation=invocation,
        model=model,
        prompt_fingerprint=prompt_fingerprint,
        feature_graph_status_store=feature_graph_status_store,
    )
    if binding is None:
        return ExecutionRuntimeSessionRoute(
            primary_path="persistent_execute_or_fallback",
        )
    return ExecutionRuntimeSessionRoute(
        primary_path="explicit_provider_resume",
        provider_session_binding=binding,
        allows_persistent_execute=False,
    )


def resolve_execution_provider_session_binding(
    *,
    store: ExecutionProviderSessionBindingStore,
    lane: Mapping[str, Any],
    invocation: ProviderInvocation,
    model: str | None,
    prompt_fingerprint: str | None,
    feature_graph_status_store: ExecutionFeatureGraphStatusStore | None = None,
) -> ProviderSessionBindingRecord | None:
    """Return a coordinator-selected provider binding for an execution request.

    The resolver is intentionally read-only.  It only consumes an explicit
    lane/session identity and never invents a provider binding owner from lane
    ids, because provider-native resume must be tied to a durable xmuse session.
    """

    return _resolve_provider_session_binding(
        store=store,
        lane=lane,
        invocation=invocation,
        model=model,
        prompt_fingerprint=prompt_fingerprint,
        session_kind="exec",
        feature_graph_status_store=feature_graph_status_store,
    )


def plan_review_runtime_session_route(
    *,
    store: ExecutionProviderSessionBindingStore,
    provider_adapter: ExecutionRuntimeProviderAdapter,
    lane: Mapping[str, Any],
    invocation: ProviderInvocation,
    model: str | None,
    prompt_fingerprint: str | None,
) -> ReviewRuntimeSessionRoute:
    if not provider_adapter.supports_explicit_session_resume(invocation):
        return ReviewRuntimeSessionRoute(primary_path="persistent_review_or_fallback")
    binding = resolve_review_provider_session_binding(
        store=store,
        lane=lane,
        invocation=invocation,
        model=model,
        prompt_fingerprint=prompt_fingerprint,
    )
    if binding is None:
        return ReviewRuntimeSessionRoute(primary_path="persistent_review_or_fallback")
    return ReviewRuntimeSessionRoute(
        primary_path="explicit_provider_resume",
        provider_session_binding=binding,
    )


def resolve_review_provider_session_binding(
    *,
    store: ExecutionProviderSessionBindingStore,
    lane: Mapping[str, Any],
    invocation: ProviderInvocation,
    model: str | None,
    prompt_fingerprint: str | None,
) -> ProviderSessionBindingRecord | None:
    return _resolve_provider_session_binding(
        store=store,
        lane=lane,
        invocation=invocation,
        model=model,
        prompt_fingerprint=prompt_fingerprint,
        session_kind="review",
    )


def _resolve_provider_session_binding(
    *,
    store: ExecutionProviderSessionBindingStore,
    lane: Mapping[str, Any],
    invocation: ProviderInvocation,
    model: str | None,
    prompt_fingerprint: str | None,
    session_kind: str,
    feature_graph_status_store: ExecutionFeatureGraphStatusStore | None = None,
) -> ProviderSessionBindingRecord | None:
    god_session_id = _explicit_binding_god_session_id(lane)
    if god_session_id is None:
        return None
    compatibility = store.find_resume_compatible(
        god_session_id=god_session_id,
        provider=invocation.provider_id.value,
        kind=session_kind,
        model=model,
        worktree=str(invocation.workspace),
        prompt_fingerprint=prompt_fingerprint,
        feature_graph_id=_feature_graph_id(lane),
    )
    if not compatibility.compatible:
        return None
    binding = compatibility.binding
    if binding is None:
        return None
    if _binding_is_quarantined(
        lane,
        binding.binding_id,
        feature_graph_status_store=feature_graph_status_store,
    ):
        return None
    return binding


def _explicit_binding_god_session_id(lane: Mapping[str, Any]) -> str | None:
    return _optional_text(lane.get("provider_session_binding_god_session_id"))


def _feature_graph_id(lane: Mapping[str, Any]) -> str | None:
    return _optional_text(lane.get("feature_graph_id")) or _optional_text(lane.get("graph_id"))


def _binding_is_quarantined(
    lane: Mapping[str, Any],
    binding_id: str,
    *,
    feature_graph_status_store: ExecutionFeatureGraphStatusStore | None,
) -> bool:
    return _graph_native_quarantines_binding(
        lane,
        binding_id,
        feature_graph_status_store=feature_graph_status_store,
    )


def _graph_native_quarantines_binding(
    lane: Mapping[str, Any],
    binding_id: str,
    *,
    feature_graph_status_store: ExecutionFeatureGraphStatusStore | None,
) -> bool:
    if feature_graph_status_store is None:
        return False
    graph_set_id = _optional_text(lane.get("graph_set_id"))
    feature_graph_id = _feature_graph_id(lane)
    if graph_set_id is None or feature_graph_id is None:
        return False
    try:
        status = feature_graph_status_store.get(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
    except KeyError:
        return False
    return any(
        evidence.binding_id == binding_id
        and evidence.reason in {"mark_failed_failed", "upsert_failed"}
        for evidence in status.provider_session_binding_degradations
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
