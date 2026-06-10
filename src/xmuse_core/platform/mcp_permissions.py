from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionCategory(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    IDENTITY_BOUND_GOD = "identity_bound_god"
    ADMIN_OPERATOR = "admin_operator"


@dataclass(frozen=True)
class McpToolPermission:
    family: str
    access: str
    permission_category: PermissionCategory
    mutates: bool
    identity_verification: str
    audit_guard: str
    scope: str
    notes: str = ""


@dataclass(frozen=True)
class McpAuthorizationDecision:
    allowed: bool
    reason: str
    tool_name: str
    role: str
    permission_category: PermissionCategory | None = None


def _read(family: str, *, scope: str, notes: str = "") -> McpToolPermission:
    return McpToolPermission(
        family=family,
        access="read",
        permission_category=PermissionCategory.READ_ONLY,
        mutates=False,
        identity_verification="none",
        audit_guard="none",
        scope=scope,
        notes=notes,
    )


def _write(
    family: str,
    *,
    scope: str,
    audit_guard: str = "none",
    notes: str = "",
) -> McpToolPermission:
    return McpToolPermission(
        family=family,
        access="write",
        permission_category=PermissionCategory.WRITE,
        mutates=True,
        identity_verification="none",
        audit_guard=audit_guard,
        scope=scope,
        notes=notes,
    )


def _admin(
    family: str,
    *,
    scope: str,
    audit_guard: str,
    notes: str = "",
) -> McpToolPermission:
    return McpToolPermission(
        family=family,
        access="write",
        permission_category=PermissionCategory.ADMIN_OPERATOR,
        mutates=True,
        identity_verification="none",
        audit_guard=audit_guard,
        scope=scope,
        notes=notes,
    )


def _identity_chat(*, mutates: bool, notes: str = "") -> McpToolPermission:
    return McpToolPermission(
        family="chat",
        access="write" if mutates else "read",
        permission_category=PermissionCategory.IDENTITY_BOUND_GOD,
        mutates=mutates,
        identity_verification="god_session",
        audit_guard="chat_identity_idempotency" if mutates else "none",
        scope="conversation_participant_session",
        notes=notes,
    )


MCP_TOOL_PERMISSIONS: dict[str, McpToolPermission] = {
    # Control tools.
    "list_lanes": _read("control", scope="lane_projection"),
    "enqueue_lane": _write(
        "control",
        scope="lane_projection",
        audit_guard="audit_guard_required",
    ),
    "get_status": _read("control", scope="lane_projection"),
    "abort_lane": _admin(
        "control",
        scope="lane_projection_and_active_session",
        audit_guard="audit_guard_required",
    ),
    "get_error_knowledge": _read("control", scope="error_knowledge"),
    "get_logs": _read(
        "control",
        scope="execution_logs",
        notes="read-only but sensitive; exposes execution log text",
    ),
    "get_tool_inventory": _read("control", scope="tool_inventory"),
    # Platform tools.
    "get_lane": _read("platform", scope="lane_projection"),
    "get_gate_report": _read("platform", scope="gate_report"),
    "get_diff": _read(
        "platform",
        scope="lane_worktree",
        notes="read-only subprocess git diff",
    ),
    "query_knowledge": _read("platform", scope="error_knowledge"),
    "update_lane_status": _write(
        "platform",
        scope="lane_projection",
        audit_guard="audit_guard_required",
    ),
    "apply_takeover_decision": _admin(
        "platform",
        scope="lane_projection_and_takeover",
        audit_guard="audit_guard_required",
    ),
    # Read contract tools.
    "read_lane_contract": _read("contracts", scope="lane_contract"),
    "read_blueprint_contract": _read("contracts", scope="blueprint_contract"),
    "read_feature_plan_contract": _read("contracts", scope="feature_plan_contract"),
    "read_review_contract": _read("contracts", scope="review_contract"),
    "read_graph_set_summary": _read("contracts", scope="graph_set"),
    "read_health_contract": _read("contracts", scope="run_health"),
    "read_graph_set_contract": _read("contracts", scope="graph_set"),
    "read_evidence_refs": _read("contracts", scope="evidence_refs"),
    "read_review_verdict": _read("contracts", scope="review_verdict"),
    "read_takeover_context": _read("contracts", scope="takeover_context"),
    "read_run_health": _read("contracts", scope="run_health"),
    "read_provider_inventory": _read("contracts", scope="provider_inventory"),
    # Chat tools.
    "chat_list_conversations": _read(
        "chat",
        scope="all_conversations",
        notes="not identity-bound in V11; global read remains a documented risk",
    ),
    "chat_create_conversation": _write(
        "chat",
        scope="conversation_creation",
        notes="not identity-bound because no GOD session exists yet",
    ),
    "chat_list_participants": _read("chat", scope="conversation"),
    "chat_post_message": _identity_chat(mutates=True),
    "chat_read_inbox": _identity_chat(mutates=False),
    "chat_mark_inbox": _identity_chat(mutates=True),
    "chat_mention": _identity_chat(mutates=True),
    "chat_emit_proposal": _identity_chat(mutates=True),
    "chat_create_collaboration_request": _identity_chat(mutates=True),
    "chat_record_collaboration_response": _identity_chat(mutates=True),
    "chat_raise_collaboration_blocker": _identity_chat(mutates=True),
    "chat_resolve_collaboration_blocker": _identity_chat(mutates=True),
    "chat_evaluate_dispatch_gate": _identity_chat(mutates=True),
    "chat_inspect_conversation": _read(
        "chat",
        scope="conversation",
        notes="read-only inspector; not identity-bound in V11",
    ),
    "chat_emit_blueprint_proposal": _identity_chat(mutates=True),
    # Memory tools stay REST-first and RBAC-gated; MCP exposure remains disabled
    # until auth/RBAC is enabled by the host.
    "memory_search": _read("memory", scope="memory_namespace"),
    "memory_build_context": _read("memory", scope="memory_namespace"),
    "memory_ingest": _write(
        "memory",
        scope="memory_namespace",
        audit_guard="audit_guard_required",
    ),
}

IDENTITY_BOUND_CHAT_TOOL_NAMES = {
    name
    for name, metadata in MCP_TOOL_PERMISSIONS.items()
    if metadata.permission_category is PermissionCategory.IDENTITY_BOUND_GOD
}

READ_ONLY_TOOL_NAMES = {
    name
    for name, metadata in MCP_TOOL_PERMISSIONS.items()
    if metadata.permission_category is PermissionCategory.READ_ONLY
}

MUTATING_TOOL_NAMES = {
    name for name, metadata in MCP_TOOL_PERMISSIONS.items() if metadata.mutates
}


def authorize_mcp_tool(
    tool_name: str,
    *,
    role: str,
    host_auth_enabled: bool = False,
) -> McpAuthorizationDecision:
    metadata = MCP_TOOL_PERMISSIONS.get(tool_name)
    if metadata is None:
        return McpAuthorizationDecision(
            allowed=False,
            reason=f"unknown MCP tool: {tool_name}",
            tool_name=tool_name,
            role=role,
        )
    role = role.strip().lower()
    if metadata.family == "memory" and metadata.mutates and not host_auth_enabled:
        return McpAuthorizationDecision(
            allowed=False,
            reason=f"memory write tool {tool_name} requires host auth/RBAC",
            tool_name=tool_name,
            role=role,
            permission_category=metadata.permission_category,
        )
    if role == "admin":
        return McpAuthorizationDecision(
            allowed=True,
            reason="admin role allowed",
            tool_name=tool_name,
            role=role,
            permission_category=metadata.permission_category,
        )
    if role == "viewer":
        if metadata.mutates:
            return McpAuthorizationDecision(
                allowed=False,
                reason=f"role viewer cannot mutate write tool {tool_name}",
                tool_name=tool_name,
                role=role,
                permission_category=metadata.permission_category,
            )
        return McpAuthorizationDecision(
            allowed=True,
            reason="viewer read allowed",
            tool_name=tool_name,
            role=role,
            permission_category=metadata.permission_category,
        )
    if role == "operator":
        allowed = metadata.permission_category is not PermissionCategory.ADMIN_OPERATOR
        return McpAuthorizationDecision(
            allowed=allowed,
            reason="operator role allowed" if allowed else "operator role cannot use admin tool",
            tool_name=tool_name,
            role=role,
            permission_category=metadata.permission_category,
        )
    if role == "god":
        allowed = metadata.permission_category in {
            PermissionCategory.READ_ONLY,
            PermissionCategory.IDENTITY_BOUND_GOD,
        }
        return McpAuthorizationDecision(
            allowed=allowed,
            reason="god role allowed" if allowed else "god role cannot use platform write tool",
            tool_name=tool_name,
            role=role,
            permission_category=metadata.permission_category,
        )
    return McpAuthorizationDecision(
        allowed=False,
        reason=f"unknown MCP role: {role}",
        tool_name=tool_name,
        role=role,
        permission_category=metadata.permission_category,
    )
