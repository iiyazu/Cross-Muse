from __future__ import annotations

from typing import Any

from xmuse_core.platform.mcp_permissions import MCP_TOOL_PERMISSIONS

READ_CONTRACT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_lane_contract",
        "description": "Return a read-only lane contract scaffold with related refs.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_blueprint_contract",
        "description": (
            "Return an approved mission blueprint contract and related feature-plan refs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "blueprint_ref": {
                    "type": "string",
                    "description": "Approved mission blueprint ref; provide this or resolution_id.",
                },
                "resolution_id": {
                    "type": "string",
                    "description": (
                        "Approved mission blueprint resolution id; "
                        "provide this or blueprint_ref."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "read_feature_plan_contract",
        "description": (
            "Return an approved feature plan contract with blueprint and graph-set refs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"feature_plan_id": {"type": "string"}},
            "required": ["feature_plan_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_review_contract",
        "description": "Return read-only review task and verdict scaffolding for a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_graph_set_summary",
        "description": "Return a compact feature graph-set progress summary for persistent peers.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_set_id": {"type": "string"}},
            "required": ["graph_set_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_health_contract",
        "description": "Return the read-only operational health model for the active lanes.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_graph_set_contract",
        "description": "Return a read-only feature graph-set snapshot and compact summary.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_set_id": {"type": "string"}},
            "required": ["graph_set_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_evidence_refs",
        "description": "Return bounded evidence references for a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_review_verdict",
        "description": "Return the latest structured review verdict for a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_takeover_context",
        "description": "Return read-only takeover context for a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"lane_id": {"type": "string"}},
            "required": ["lane_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_run_health",
        "description": "Return the read-only operational run-health snapshot.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_provider_inventory",
        "description": "Return a read-only provider inventory with static profile metadata.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

_AUDIT_GUARD_REQUIRED_TOOL_NAMES = {
    "abort_lane",
    "apply_takeover_decision",
    "enqueue_lane",
    "update_lane_status",
}

_CHAT_IDENTITY_IDEMPOTENCY_TOOL_NAMES = {
    "chat_approve_proposal",
    "chat_create_conversation",
    "chat_create_collaboration_request",
    "chat_emit_blueprint_proposal",
    "chat_emit_proposal",
    "chat_evaluate_dispatch_gate",
    "chat_mark_inbox",
    "chat_mention",
    "chat_post_message",
    "chat_raise_collaboration_blocker",
    "chat_record_collaboration_response",
    "chat_resolve_collaboration_blocker",
}

_WRITE_TOOL_NAMES = {
    *_AUDIT_GUARD_REQUIRED_TOOL_NAMES,
    *_CHAT_IDENTITY_IDEMPOTENCY_TOOL_NAMES,
}


def build_tool_inventory(
    *,
    control_schemas: list[dict[str, Any]],
    platform_schemas: list[dict[str, Any]],
    chat_schemas: list[dict[str, Any]],
    contract_schemas: list[dict[str, Any]],
) -> dict[str, Any]:
    families = {
        "control": _inventory_family(control_schemas),
        "platform": _inventory_family(platform_schemas),
        "chat": _inventory_family(chat_schemas),
        "contracts": _inventory_family(contract_schemas),
    }
    all_tools = [
        tool
        for family in families.values()
        for tool in family["tools"]
    ]
    return {
        "kind": "tool_inventory",
        "read_only": True,
        "counts": {
            "total": len(all_tools),
            "read": sum(1 for tool in all_tools if tool["access"] == "read"),
            "write": sum(1 for tool in all_tools if tool["access"] == "write"),
        },
        "families": families,
    }


def _inventory_family(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    tools = []
    for schema in schemas:
        name = schema["name"]
        permission = MCP_TOOL_PERMISSIONS[name]
        tools.append(
            {
                "name": name,
                "description": schema.get("description", ""),
                "access": permission.access,
                "mutation_contract": _mutation_contract(name),
                "permission_category": permission.permission_category.value,
                "mutates": permission.mutates,
                "identity_verification": permission.identity_verification,
                "audit_guard": permission.audit_guard,
                "scope": permission.scope,
            }
        )
    return {
        "count": len(tools),
        "tool_names": [tool["name"] for tool in tools],
        "tools": tools,
    }


def _tool_access(name: str) -> str:
    return MCP_TOOL_PERMISSIONS[name].access


def _mutation_contract(name: str) -> str:
    permission = MCP_TOOL_PERMISSIONS[name]
    if permission.audit_guard == "audit_guard_required":
        return "audit_guard_required"
    if permission.audit_guard == "chat_identity_idempotency":
        return "chat_identity_idempotency"
    if permission.mutates:
        return "write_no_audit_guard"
    return "read_only"
