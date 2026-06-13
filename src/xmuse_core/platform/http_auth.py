from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from xmuse_core.platform.mcp_permissions import MCP_TOOL_PERMISSIONS, authorize_mcp_tool

DEPLOYMENT_PROFILE_ENV = "XMUSE_DEPLOYMENT_PROFILE"
PRODUCTION_DEPLOYMENT_PROFILE = "production"
MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
OPERATOR_ACTION_CAPABILITIES = frozenset(
    {
        "operator_action",
        "register_god_cli",
        "select_god_cli",
        "workflow_write",
        "release_gate",
    }
)


@dataclass(frozen=True)
class HttpAuthorizationDecision:
    allowed: bool
    code: str
    message: str
    required_capability: str | None = None


def production_deployment_profile_enabled(
    env: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if env is None else env
    return (
        source.get(DEPLOYMENT_PROFILE_ENV, "").strip().lower()
        == PRODUCTION_DEPLOYMENT_PROFILE
    )


def require_production_write_auth_token(
    *,
    service_name: str,
    auth_token: str | None,
    env_names: tuple[str, ...],
    env: Mapping[str, str] | None = None,
) -> str | None:
    token = (auth_token or "").strip()
    if token:
        return token
    if production_deployment_profile_enabled(env):
        expected = " or ".join(env_names)
        raise RuntimeError(
            f"{service_name} production deployment requires a write auth token; "
            f"set {expected} or pass auth_token explicitly"
        )
    return None


def authorize_chat_api_write(
    *,
    method: str,
    path: str,
    role: str,
    capabilities: tuple[str, ...],
) -> HttpAuthorizationDecision:
    method = method.strip().upper()
    if method not in MUTATING_HTTP_METHODS:
        return HttpAuthorizationDecision(
            allowed=True,
            code="read_allowed",
            message="read request allowed",
        )

    required = required_chat_api_capabilities(method=method, path=path)
    normalized_role = role.strip().lower() or "operator"
    if normalized_role == "admin":
        return HttpAuthorizationDecision(
            allowed=True,
            code="admin_allowed",
            message="admin role allowed",
            required_capability=required[0] if required else None,
        )
    if normalized_role == "viewer":
        return HttpAuthorizationDecision(
            allowed=False,
            code="role_not_authorized",
            message="viewer role cannot mutate Chat API write surface",
            required_capability=required[0] if required else None,
        )
    if normalized_role not in {"operator", "god"}:
        return HttpAuthorizationDecision(
            allowed=False,
            code="unknown_role",
            message=f"unknown Chat API role: {normalized_role}",
            required_capability=required[0] if required else None,
        )

    granted = {item.strip() for item in capabilities if item.strip()}
    if any(capability in granted for capability in required):
        return HttpAuthorizationDecision(
            allowed=True,
            code="capability_allowed",
            message="required capability granted",
            required_capability=required[0] if required else None,
        )
    required_capability = required[0] if required else "chat_write"
    return HttpAuthorizationDecision(
        allowed=False,
        code="missing_capability",
        message=f"missing capability {required_capability}",
        required_capability=required_capability,
    )


def authorize_mcp_http_tool(
    *,
    tool_name: str,
    role: str,
    capabilities: tuple[str, ...],
    host_auth_enabled: bool = True,
) -> HttpAuthorizationDecision:
    metadata = MCP_TOOL_PERMISSIONS.get(tool_name)
    if metadata is None:
        return HttpAuthorizationDecision(
            allowed=True,
            code="unknown_tool_deferred",
            message="unknown MCP tool authorization deferred to tool dispatcher",
        )
    if not metadata.mutates:
        return HttpAuthorizationDecision(
            allowed=True,
            code="read_allowed",
            message="read MCP tool allowed",
        )

    decision = authorize_mcp_tool(
        tool_name,
        role=role,
        host_auth_enabled=host_auth_enabled,
    )
    if not decision.allowed:
        normalized_role = role.strip().lower() or "operator"
        return HttpAuthorizationDecision(
            allowed=False,
            code="unknown_role"
            if normalized_role not in {"admin", "viewer", "operator", "god"}
            else "role_not_authorized",
            message=decision.reason,
            required_capability=tool_name,
        )

    normalized_role = role.strip().lower() or "operator"
    if normalized_role == "admin":
        return HttpAuthorizationDecision(
            allowed=True,
            code="admin_allowed",
            message="admin role allowed",
            required_capability=tool_name,
        )

    granted = {item.strip() for item in capabilities if item.strip()}
    if tool_name in granted:
        return HttpAuthorizationDecision(
            allowed=True,
            code="capability_allowed",
            message="required MCP tool capability granted",
            required_capability=tool_name,
        )
    return HttpAuthorizationDecision(
        allowed=False,
        code="missing_capability",
        message=f"missing capability for MCP tool {tool_name}",
        required_capability=tool_name,
    )


def required_chat_api_capabilities(*, method: str, path: str) -> tuple[str, ...]:
    if method.strip().upper() not in MUTATING_HTTP_METHODS:
        return ()
    path = path.rstrip("/") or "/"
    if path == "/api/chat/conversations":
        return ("chat_create_conversation",)
    if path == "/api/chat/operator/actions":
        return tuple(sorted(OPERATOR_ACTION_CAPABILITIES))
    if path.startswith("/api/chat/role-templates"):
        return ("admin_operator",)
    if "/god-room" in path:
        return ("chat_god_room",)
    if path.endswith("/messages") and (
        path.startswith("/api/chat/conversations/")
        or path.startswith("/api/chat/threads/")
    ):
        return ("chat_post_message",)
    if "/participants" in path:
        return ("chat_manage_participants",)
    if "/bootstrap/" in path:
        return ("chat_bootstrap",)
    if "/collaboration/" in path:
        return ("chat_collaboration",)
    if "/dispatch/" in path:
        return ("chat_dispatch",)
    if path.endswith("/deliberations"):
        return ("chat_deliberation",)
    if path.endswith("/freeze-blueprint"):
        return ("chat_freeze_blueprint",)
    if path.endswith("/proposals"):
        return ("chat_emit_proposal",)
    if "/proposals/" in path and path.endswith("/approve"):
        return ("chat_approve_proposal",)
    if path.endswith("/forks") or "/forks/" in path:
        return ("chat_fork_peer",)
    return ("chat_write",)
