"""Loopback frontend security helpers shared by Room runtime applications."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

DEFAULT_FRONTEND_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
LOOPBACK_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
_LOOPBACK_ORIGIN_PATTERN = re.compile(LOOPBACK_ORIGIN_RE)


def resolve_frontend_origins(environ: Mapping[str, str] | None = None) -> list[str]:
    env = environ if environ is not None else os.environ
    origins: list[str] = list(DEFAULT_FRONTEND_ORIGINS)
    configured = env.get("XMUSE_FRONTEND_URL")
    if configured:
        origins.append(configured)
    configured_many = env.get("XMUSE_FRONTEND_ORIGINS")
    if configured_many:
        origins.extend(item.strip() for item in configured_many.split(","))
    return _dedupe([item.rstrip("/") for item in origins if item.strip()])


def frontend_cors_kwargs(*, allow_credentials: bool) -> dict[str, Any]:
    return {
        "allow_origins": resolve_frontend_origins(),
        "allow_origin_regex": LOOPBACK_ORIGIN_RE,
        "allow_credentials": allow_credentials,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


def is_frontend_origin_allowed(
    origin: str | None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    if not origin:
        return False
    normalized = origin.rstrip("/")
    if normalized in resolve_frontend_origins(environ):
        return True
    return bool(_LOOPBACK_ORIGIN_PATTERN.match(normalized))


def operator_error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
    field_errors: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "field_errors": field_errors or {},
        "retryable": retryable,
        "correlation_id": correlation_id,
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
