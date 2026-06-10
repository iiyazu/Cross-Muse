from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.agents.persistent_peer import fingerprint_prompt
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.feature_context import build_feature_context_bundle
from xmuse_core.platform.lane_context import build_lane_context_bundle


def review_participant_id(lane_id: str) -> str:
    return f"review-god-{safe_session_fragment(lane_id)}"


def review_request_id(identity_key: str, lane_id: str) -> str:
    return f"review-{safe_session_fragment(identity_key)}-{safe_session_fragment(lane_id)}"


def persistent_review_worktree(xmuse_root: Path) -> Path:
    return xmuse_root.parent if xmuse_root.name == "xmuse" else xmuse_root


def persistent_peer_prompt_fingerprint(god: GodConfig, *, role: str) -> str:
    return fingerprint_prompt(persistent_peer_session_prompt(god, role=role))


def persistent_peer_session_prompt(
    god: GodConfig,
    *,
    role: str,
    identity_key: str | None = None,
) -> str:
    lines = [
        f"role={role}",
        f"god={god.name}",
        f"runtime={god.runtime}",
        f"skill_prompt_path={god.skill_prompt_path}",
    ]
    if god.model:
        lines.append(f"model={god.model}")
    if god.worker_model:
        lines.append(f"worker_model={god.worker_model}")
    if god.delegation_mode:
        lines.append(f"delegation_mode={god.delegation_mode}")
    if identity_key is not None:
        lines.append(f"identity={identity_key}")
    return "\n".join(lines)


def persistent_review_prompt(
    prompt: str,
    *,
    review_request_id: str,
    identity_key: str,
) -> str:
    return (
        f"{prompt.rstrip()}\n\n"
        "## Persistent Review Routing\n\n"
        f"- review_request_id: {review_request_id}\n"
        f"- persistent_review_identity: {identity_key}\n"
        "- This request is protected by single-flight routing for this identity.\n"
    )


def safe_session_fragment(value: str, *, max_chars: int = 80) -> str:
    fragment = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in value
    ).strip("-")
    return (fragment or "lane")[:max_chars]


def persistent_review_request_degraded_reason(
    message: Any,
    *,
    expected_request_id: str,
) -> str | None:
    if message.request_id is None:
        return "request_id_missing"
    if message.request_id != expected_request_id:
        return "request_id_mismatch"
    return None


def persistent_review_context(
    lane: dict[str, Any],
    *,
    conversation_id: str,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]],
) -> str:
    feature_context = build_feature_context_bundle(
        lane,
        all_lanes=all_lanes,
        xmuse_root=xmuse_root,
    )
    sections = [
        feature_context.as_prompt_context(),
        conversation_history_for_prompt(conversation_id, xmuse_root=xmuse_root),
        lane_review_context_for_prompt(lane),
        "## Lane Context\n\n"
        + build_lane_context_bundle(
            lane,
            xmuse_root=xmuse_root,
            all_lanes=all_lanes,
        )["retry_context"],
    ]
    return "\n\n".join(section for section in sections if section)


def lane_review_context_for_prompt(lane: dict[str, Any]) -> str:
    lane_id = str(lane.get("feature_id") or "unknown")
    prompt = str(lane.get("prompt") or "").strip()
    if len(prompt) > 3000:
        prompt = prompt[:2986].rstrip() + "...<truncated>"

    lines = ["## Lane Review Context", "", f"- Lane ID: {lane_id}"]
    if prompt:
        lines.extend(["", "### Lane Prompt", "", prompt])
    else:
        lines.append("- Lane prompt unavailable.")
    return "\n".join(lines)


def conversation_history_for_prompt(conversation_id: str, *, xmuse_root: Path) -> str:
    db_path = xmuse_root / "chat.db"
    if not db_path.exists():
        return "## Conversation History\n\n- unavailable: chat.db missing"
    try:
        messages = ChatStore(db_path).list_messages(conversation_id)[-12:]
    except Exception as exc:
        return f"## Conversation History\n\n- unavailable: {type(exc).__name__}"
    if not messages:
        return "## Conversation History\n\n- no recent messages"
    lines = ["## Conversation History", ""]
    for message in messages:
        content = " ".join(message.content.split())
        if len(content) > 500:
            content = content[:486].rstrip() + "...<truncated>"
        lines.append(f"- [{message.role}/{message.author}] {content}")
    return "\n".join(lines)
