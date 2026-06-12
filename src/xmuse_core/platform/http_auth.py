from __future__ import annotations

from dataclasses import dataclass

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
