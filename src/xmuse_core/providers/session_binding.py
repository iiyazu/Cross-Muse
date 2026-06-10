from __future__ import annotations

from typing import Protocol

from xmuse_core.providers.adapters.base import ProviderInvocation, ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.structuring.feature_review_contracts import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


class ProviderSessionBindingWriter(Protocol):
    def upsert_active(
        self,
        binding: ProviderSessionBindingRecord,
    ) -> ProviderSessionBindingRecord: ...


def build_provider_session_binding_from_result(
    *,
    invocation: ProviderInvocation,
    result: ProviderInvocationResult,
    god_session_id: str,
    role: str,
    created_at: str,
    conversation_id: str | None = None,
    feature_graph_id: str | None = None,
    prompt_fingerprint: str | None = None,
    model: str | None = None,
    session_kind: str = "exec",
    binding_id: str | None = None,
) -> ProviderSessionBindingRecord:
    """Build a resumable provider-native session binding from a successful result.

    The helper is intentionally pure: it creates the coordinator-owned record
    shape but does not write the binding store or change dispatch behavior.
    """

    validated_invocation = ProviderInvocation.model_validate(invocation.model_dump())
    validated_result = ProviderInvocationResult.model_validate(result.model_dump(mode="json"))
    if validated_result.request_id != validated_invocation.request_id:
        raise ValueError("provider result request_id must match invocation")
    if validated_result.provider_id is not validated_invocation.provider_id:
        raise ValueError("provider result provider_id must match invocation")
    if validated_result.profile_id is not validated_invocation.profile_id:
        raise ValueError("provider result profile_id must match invocation")
    if validated_result.status is not WorkerResultStatus.COMPLETED:
        raise ValueError("provider session binding requires a successful provider result")
    if validated_result.provider_session_id is None:
        raise ValueError("provider session binding requires provider_session_id")

    provider = validated_invocation.provider_id.value
    provider_session_id = validated_result.provider_session_id
    return ProviderSessionBindingRecord(
        binding_id=binding_id
        or _default_binding_id(
            god_session_id=god_session_id,
            provider=provider,
            session_kind=session_kind,
            provider_session_id=provider_session_id,
        ),
        god_session_id=god_session_id,
        provider=provider,
        provider_session_id=provider_session_id,
        session_kind=session_kind,
        status=ProviderSessionBindingStatus.ACTIVE,
        conversation_id=conversation_id,
        feature_graph_id=feature_graph_id,
        role=role,
        cwd=str(validated_invocation.workspace),
        worktree=str(validated_invocation.workspace),
        model=model,
        prompt_fingerprint=prompt_fingerprint,
        created_at=created_at,
        last_used_at=created_at,
        last_verified_at=created_at,
        resume_command_template=_resume_command_template(provider, session_kind),
    )


def upsert_provider_session_binding_from_result(
    *,
    store: ProviderSessionBindingWriter,
    invocation: ProviderInvocation,
    result: ProviderInvocationResult,
    god_session_id: str,
    role: str,
    created_at: str,
    conversation_id: str | None = None,
    feature_graph_id: str | None = None,
    prompt_fingerprint: str | None = None,
    model: str | None = None,
    session_kind: str = "exec",
    binding_id: str | None = None,
) -> ProviderSessionBindingRecord:
    """Explicitly persist a result-derived provider session binding.

    This is a store-facing coordinator helper. It still requires the caller to
    pass the store explicitly, so adapter invocation and worker execution paths
    do not gain hidden durable-state writes.
    """

    binding = build_provider_session_binding_from_result(
        invocation=invocation,
        result=result,
        god_session_id=god_session_id,
        role=role,
        created_at=created_at,
        conversation_id=conversation_id,
        feature_graph_id=feature_graph_id,
        prompt_fingerprint=prompt_fingerprint,
        model=model,
        session_kind=session_kind,
        binding_id=binding_id,
    )
    return store.upsert_active(binding)


def _default_binding_id(
    *,
    god_session_id: str,
    provider: str,
    session_kind: str,
    provider_session_id: str,
) -> str:
    return f"psb:{god_session_id}:{provider}:{session_kind}:{provider_session_id}"


def _resume_command_template(provider: str, session_kind: str) -> str | None:
    if provider == "codex" and session_kind in {"exec", "review"}:
        return "codex exec resume {provider_session_id}"
    return None
