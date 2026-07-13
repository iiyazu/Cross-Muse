from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute

from xmuse.chat_api import create_app


def _route_methods(app) -> set[tuple[str, str]]:
    return {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_default_chat_api_exposes_one_human_write_path(tmp_path: Path) -> None:
    routes = _route_methods(create_app(tmp_path))

    assert ("/api/chat/threads/{conversation_id}/messages", "POST") in routes
    assert ("/api/chat/conversations/{conversation_id}/messages", "GET") not in routes
    assert ("/api/chat/conversations/{conversation_id}/messages", "POST") not in routes


def test_default_chat_api_does_not_register_compatibility_control_plane(
    tmp_path: Path,
) -> None:
    routes = _route_methods(create_app(tmp_path))

    forbidden_paths = {
        "/a2a/tasks/send",
        "/api/chat/conversations/{conversation_id}/worklist",
        "/api/chat/conversations/{conversation_id}/ux-projection",
        "/api/chat/conversations/{conversation_id}/live-telemetry",
        "/api/dashboard/peer-chat/conversations/{conversation_id}/run-health",
        "/api/chat/operator/proposals/{proposal_id}/approve",
        "/api/chat/operator/final-actions/{hold_id}/resolve",
    }

    assert not {(path, method) for path, method in routes if path in forbidden_paths}
