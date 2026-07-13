"""Authentication and idempotency helpers for local operator actions."""

from __future__ import annotations

import os
from hmac import compare_digest

from fastapi import HTTPException, Request, status

from xmuse_core.runtime.frontend_api import operator_error


def configured_operator_token() -> str | None:
    configured = os.environ.get("XMUSE_OPERATOR_TOKEN")
    return configured.strip() if configured and configured.strip() else None


OPERATOR_TOKEN_HEADER = "X-XMuse-Operator-Token"


def resolve_operator_token(explicit: str | None = None) -> str | None:
    if explicit is not None:
        cleaned = explicit.strip()
        return cleaned or None
    return configured_operator_token()


def presented_operator_token(request: Request) -> str | None:
    presented = request.headers.get(OPERATOR_TOKEN_HEADER)
    return presented.strip() if presented and presented.strip() else None


def operator_token_matches(request: Request, configured: str) -> bool:
    presented = presented_operator_token(request)
    return presented is not None and compare_digest(presented, configured)


def require_operator_token(
    request: Request,
    *,
    configured_token: str | None = None,
) -> None:
    configured = resolve_operator_token(configured_token)
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=operator_error(
                "operator_auth_not_configured",
                "XMUSE_OPERATOR_TOKEN is required for operator actions",
            ),
        )
    if not operator_token_matches(request, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=operator_error(
                "operator_auth_invalid",
                "operator token is missing or invalid",
            ),
        )
