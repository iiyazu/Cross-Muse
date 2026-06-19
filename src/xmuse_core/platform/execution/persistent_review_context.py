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
    lane_context = build_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    sections = [
        feature_context.as_prompt_context(),
        conversation_history_for_prompt(conversation_id, xmuse_root=xmuse_root),
        lane_review_context_for_prompt(lane),
        review_artifact_grounding_for_prompt(lane_context),
        "## Lane Context\n\n" + lane_context["retry_context"],
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


def review_artifact_grounding_for_prompt(bundle: dict[str, Any]) -> str:
    lines = [
        "## Review Artifact Grounding",
        "",
        "- Treat the refs in this section as the current review authority before "
        "writing a verdict.",
        "- If gate refs or worker refs are present, do not state that logs, gate "
        "reports, or execution artifacts are absent unless you inspected the "
        "cited refs and they are missing.",
        "- If MCP tools are unavailable, still ground any stdout verdict in the "
        "provided refs and name the refs used.",
        "- Do not claim GitHub review truth, merge truth, ready_to_merge, "
        "pr_merged, live MemoryOS, or full closure.",
        "- A merge verdict means review acceptance only. Unless a final-action "
        "hold was approved or GitHub server merge evidence is present, do not "
        "say the lane or PR was merged.",
    ]
    status = str(bundle.get("status") or "").strip()
    if status:
        lines.append(f"- Current lane status: {status}")
    if bundle.get("gate_passed") is not None:
        lines.append(f"- Gate passed: {bool(bundle.get('gate_passed'))}")
    gate_report_ref = _optional_text(bundle.get("gate_report_ref"))
    if gate_report_ref is not None:
        lines.append(f"- Gate report: {gate_report_ref}")
    gate_summary = _optional_text(bundle.get("gate_report_summary"))
    if gate_summary is not None:
        lines.extend(["", "### Gate Report Summary", "", gate_summary])
    worker_refs = _refs_from_bundle(
        bundle.get("worker_refs"),
        fallback=bundle.get("recent_agent_spawn_refs"),
    )
    if worker_refs:
        lines.extend(["", "### Worker Refs", ""])
        lines.extend(f"- {ref}" for ref in worker_refs[:8])
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


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _refs_from_bundle(value: Any, *, fallback: Any = None) -> list[str]:
    refs: list[str] = []
    for candidate in (value, fallback):
        if refs:
            break
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            ref: str | None = None
            if isinstance(item, str):
                ref = item
            elif isinstance(item, dict) and isinstance(item.get("ref"), str):
                ref = item["ref"]
            if ref is None:
                continue
            text = ref.strip()
            if text and text not in refs:
                refs.append(text)
    return refs
