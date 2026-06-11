from __future__ import annotations

import json
from typing import Any

SPEECH_ACTS = {
    "propose",
    "ask",
    "challenge",
    "object",
    "vote",
    "decide",
    "handoff",
    "evidence",
    "retract",
}


def build_tui_vision_read_model(
    *,
    conversation_id: str | None = None,
    messages: list[dict] | None = None,
    worklist_envelope: dict | None = None,
    inspector: dict | None = None,
    memory_trace: dict | None = None,
    github_truth: dict | None = None,
    provider_runtime: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a provider-agnostic TUI read model from read-only inputs."""
    inspector_evidence = _inspector_evidence(inspector)
    deliberation = _build_deliberation(conversation_id, messages or [])
    return {
        "schema_version": "1",
        "read_model_version": "1",
        "conversation_id": conversation_id,
        "deliberation": deliberation,
        "blueprint_freeze": _build_blueprint_freeze(deliberation, inspector),
        "execution": _build_execution(worklist_envelope),
        "memory": _build_memory(memory_trace or inspector_evidence["memory_trace"]),
        "github": _build_github(github_truth or inspector_evidence["github_truth"]),
        "providers": _build_providers(
            provider_runtime or inspector_evidence["provider_runtime"]
        ),
    }


def _build_deliberation(
    conversation_id: str | None,
    messages: list[dict],
) -> dict[str, Any]:
    source_refs: list[str] = []
    target_refs: list[str] = []
    blockers: list[dict[str, Any]] = []
    speech_acts: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for message in messages:
        if not isinstance(message, dict):
            continue
        envelope = _message_envelope(message)
        speech_act = _speech_act(envelope)
        if speech_act is None:
            continue
        message_id = _text(message.get("id") or message.get("message_id"))
        message_ref = f"message:{message_id}" if message_id is not None else None
        if message_ref is not None:
            _append_unique(source_refs, message_ref)
        envelope_source_refs = _refs(envelope, "source_refs", "source_ref")
        envelope_target_refs = _refs(envelope, "target_refs", "target_ref")
        for ref in envelope_source_refs:
            _append_unique(source_refs, ref)
        for ref in envelope_target_refs:
            _append_unique(target_refs, ref)

        act = {
            "message_id": message_id,
            "conversation_id": _text(message.get("conversation_id")) or conversation_id,
            "author": _text(message.get("author")),
            "speech_act": speech_act,
            "decision_scope": _text(envelope.get("decision_scope")),
            "source_refs": envelope_source_refs,
            "target_refs": envelope_target_refs,
            "payload": envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {},
        }
        speech_acts.append(act)
        counts[speech_act] = counts.get(speech_act, 0) + 1

        if _is_blocking(envelope):
            blockers.append(
                {
                    "message_id": message_id,
                    "speech_act": speech_act,
                    "reason": _blocker_reason(envelope, message),
                    "source_refs": envelope_source_refs,
                    "target_refs": envelope_target_refs,
                }
            )

    fact_state = "manual_gap"
    proof_level = "manual_gap"
    manual_gap_reason = "structured deliberation messages unavailable"
    if speech_acts:
        proof_level = "contract_proof"
        fact_state = "blocked" if blockers else "observed"
        manual_gap_reason = None

    return {
        "proof_level": proof_level,
        "fact_state": fact_state,
        "source_refs": source_refs,
        "blockers": blockers,
        "target_refs": target_refs,
        "manual_gap_reason": manual_gap_reason,
        "speech_acts": speech_acts,
        "speech_act_counts": dict(sorted(counts.items())),
    }


def _build_blueprint_freeze(
    deliberation: dict[str, Any],
    inspector: dict | None,
) -> dict[str, Any]:
    source_refs: list[str] = []
    target_refs: list[str] = []
    blockers = list(deliberation.get("blockers") or [])
    relevant_acts = [
        act
        for act in deliberation.get("speech_acts", [])
        if isinstance(act, dict)
        and _is_blueprint_freeze_act(act)
    ]
    for act in relevant_acts:
        message_id = _text(act.get("message_id"))
        if message_id is not None:
            _append_unique(source_refs, f"message:{message_id}")
        for ref in _list_refs(act.get("source_refs")):
            _append_unique(source_refs, ref)
        for ref in _list_refs(act.get("target_refs")):
            _append_unique(target_refs, ref)

    inspector_freeze = _inspector_freeze(inspector)
    if inspector_freeze is not None:
        for ref in _list_refs(inspector_freeze.get("source_refs")):
            _append_unique(source_refs, ref)
        for ref in _list_refs(inspector_freeze.get("target_refs")):
            _append_unique(target_refs, ref)

    frozen = bool(
        inspector_freeze
        and (
            inspector_freeze.get("frozen") is True
            or _text(inspector_freeze.get("status")) == "frozen"
            or _text(inspector_freeze.get("fact_state")) == "frozen"
            or _text(inspector_freeze.get("frozen_at")) is not None
        )
    )
    ready_to_freeze = bool(
        not frozen
        and not blockers
        and any(act.get("speech_act") in {"decide", "vote"} for act in relevant_acts)
    )

    proof_level = "manual_gap"
    fact_state = "manual_gap"
    manual_gap_reason = "blueprint freeze readiness unavailable"
    if frozen:
        proof_level = _normalize_proof_level(inspector_freeze.get("proof_level"))  # type: ignore[union-attr]
        fact_state = "frozen"
        manual_gap_reason = None
    elif blockers:
        proof_level = "contract_proof"
        fact_state = "blocked"
        manual_gap_reason = None
    elif relevant_acts:
        proof_level = "contract_proof"
        fact_state = "ready_to_freeze" if ready_to_freeze else "observed"
        manual_gap_reason = None

    return {
        "proof_level": proof_level,
        "fact_state": fact_state,
        "source_refs": source_refs,
        "blockers": blockers,
        "target_refs": target_refs,
        "manual_gap_reason": manual_gap_reason,
        "ready_to_freeze": ready_to_freeze,
        "frozen": frozen,
        "freeze_state": fact_state,
    }


def _build_execution(worklist_envelope: dict | None) -> dict[str, Any]:
    if not isinstance(worklist_envelope, dict):
        return _manual_gap_section("laneDAG projection unavailable")

    source_authority = _text(worklist_envelope.get("source_authority")) or "tui_worklist_envelope"
    projection_revision = worklist_envelope.get("projection_revision")
    source_ref = (
        f"{source_authority}#projection_revision={projection_revision}"
        if isinstance(projection_revision, int) and not isinstance(projection_revision, bool)
        else source_authority
    )
    items = _worklist_items(worklist_envelope)
    source_refs = [source_ref]
    target_refs: list[str] = []
    ready_lane_ids: list[str] = []
    blocked_lane_ids: list[str] = []
    dependency_edges: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    patch_forward_lineage: list[dict[str, Any]] = []

    for item in items:
        lane_id = _lane_id(item)
        if lane_id is None:
            continue
        _append_unique(target_refs, f"lane:{lane_id}")
        if _lane_ready(item):
            ready_lane_ids.append(lane_id)
        if _lane_blocked(item):
            blocked_lane_ids.append(lane_id)
            blockers.append(
                {
                    "lane_id": lane_id,
                    "reason": _lane_blocker_reason(item),
                    "source_refs": [source_ref],
                    "target_refs": [f"lane:{lane_id}"],
                }
            )
        deps = _dependency_ids(item)
        if deps:
            dependency_edges.append({"lane_id": lane_id, "depends_on": deps})
        review_item = _review_item(item, lane_id=lane_id, source_ref=source_ref)
        if review_item is not None:
            review_items.append(review_item)
        source_lane_id = _source_lane_id(item)
        if source_lane_id is not None:
            patch_forward_lineage.append(
                {
                    "source_lane_id": source_lane_id,
                    "patch_lane_id": lane_id,
                    "source_refs": [source_ref],
                    "target_refs": [f"lane:{source_lane_id}", f"lane:{lane_id}"],
                }
            )

    graph_lineage = (
        worklist_envelope.get("graph_lineage")
        if isinstance(worklist_envelope.get("graph_lineage"), dict)
        else {}
    )
    graph_id = _text(graph_lineage.get("authoritative_graph_id")) if graph_lineage else None
    if graph_id is not None:
        _append_unique(target_refs, f"graph:{graph_id}")

    fact_state = "observed"
    if blocked_lane_ids:
        fact_state = "blocked"
    elif ready_lane_ids:
        fact_state = "ready"

    return {
        "proof_level": "contract_proof",
        "fact_state": fact_state,
        "source_refs": source_refs,
        "blockers": blockers,
        "target_refs": target_refs,
        "manual_gap_reason": None,
        "source_authority": source_authority,
        "projection_revision": (
            projection_revision if isinstance(projection_revision, int) else None
        ),
        "lane_count": len(items),
        "ready_lane_ids": ready_lane_ids,
        "blocked_lane_ids": blocked_lane_ids,
        "dependency_edges": dependency_edges,
        "review_items": review_items,
        "patch_forward_lineage": patch_forward_lineage,
        "graph_lineage": graph_lineage,
    }


def _build_memory(memory_trace: dict | None) -> dict[str, Any]:
    if not isinstance(memory_trace, dict):
        section = _manual_gap_section("memory trace unavailable")
        section.update(
            {
                "session_id": None,
                "namespace_uri": None,
                "namespace": None,
                "trace_events_count": 0,
                "pinned_core_count": 0,
                "active_task_pages_count": 0,
                "recent_messages_count": 0,
                "retrieved_pages_count": 0,
                "dropped_pages_count": 0,
                "token_estimate": None,
            }
        )
        return section

    events = memory_trace.get("trace_events")
    if not isinstance(events, list):
        events = memory_trace.get("events")
    if not isinstance(events, list):
        events = []
    source_refs = _list_refs(memory_trace.get("source_refs"))
    session_id = _text(memory_trace.get("session_id"))
    namespace_uri = _text(memory_trace.get("namespace_uri"))
    namespace = (
        memory_trace.get("namespace")
        if isinstance(memory_trace.get("namespace"), dict)
        else ({"uri": namespace_uri} if namespace_uri is not None else None)
    )
    token_estimate = memory_trace.get("token_estimate")
    if not isinstance(token_estimate, int) or isinstance(token_estimate, bool):
        token_estimate = memory_trace.get("estimated_tokens")
    target_refs: list[str] = []
    if session_id is not None:
        target_refs.append(f"memory_session:{session_id}")
    context_package = (
        memory_trace.get("context_package")
        if isinstance(memory_trace.get("context_package"), dict)
        else {}
    )
    return {
        "proof_level": _normalize_proof_level(memory_trace.get("proof_level")),
        "fact_state": "observed",
        "source_refs": source_refs,
        "blockers": [],
        "target_refs": target_refs,
        "manual_gap_reason": None,
        "session_id": session_id,
        "namespace_uri": namespace_uri,
        "namespace": namespace,
        "trace_events_count": len(events),
        "pinned_core_count": _memory_context_count(
            memory_trace,
            context_package,
            "pinned_core",
        ),
        "active_task_pages_count": _memory_context_count(
            memory_trace,
            context_package,
            "active_task_pages",
        ),
        "recent_messages_count": _memory_context_count(
            memory_trace,
            context_package,
            "recent_messages",
        ),
        "retrieved_pages_count": _memory_context_count(
            memory_trace,
            context_package,
            "retrieved_pages",
        ),
        "dropped_pages_count": _memory_context_count(
            memory_trace,
            context_package,
            "dropped_pages",
        ),
        "token_estimate": token_estimate,
    }


def _build_github(github_truth: dict | None) -> dict[str, Any]:
    if not isinstance(github_truth, dict):
        section = _manual_gap_section("GitHub truth unavailable")
        section.update(
            {
                "can_emit_pr_merged": False,
                "required_checks": {},
                "review_truth": {},
                "merge": {},
            }
        )
        return section

    proof_level = _normalize_proof_level(github_truth.get("proof_level"))
    required_checks = (
        github_truth.get("required_checks")
        if isinstance(github_truth.get("required_checks"), dict)
        else {}
    )
    review_truth = (
        github_truth.get("review_truth")
        if isinstance(github_truth.get("review_truth"), dict)
        else {}
    )
    merge = _github_merge_fields(github_truth)
    can_emit_pr_merged = github_truth.get("can_emit_pr_merged") is True
    blockers = _github_blockers(required_checks, review_truth, github_truth)

    if _can_render_pr_merged(
        proof_level=proof_level,
        can_emit_pr_merged=can_emit_pr_merged,
        merge=merge,
    ):
        fact_state = "pr_merged"
        manual_gap_reason = github_truth.get("manual_gap_reason")
    elif merge.get("merged") is True:
        fact_state = "manual_gap"
        manual_gap_reason = "server-side merge proof is missing"
    elif can_emit_pr_merged:
        fact_state = "merge_ready"
        manual_gap_reason = github_truth.get("manual_gap_reason")
    elif blockers:
        fact_state = "blocked"
        manual_gap_reason = github_truth.get("manual_gap_reason")
    else:
        fact_state = "observed"
        manual_gap_reason = github_truth.get("manual_gap_reason")

    return {
        "proof_level": proof_level,
        "fact_state": fact_state,
        "source_refs": _list_refs(github_truth.get("source_refs")),
        "blockers": blockers,
        "target_refs": _list_refs(github_truth.get("target_refs")),
        "manual_gap_reason": manual_gap_reason,
        "can_emit_pr_merged": can_emit_pr_merged,
        "required_checks": required_checks,
        "review_truth": review_truth,
        "merge": merge,
    }


def _github_merge_fields(github_truth: dict[str, Any]) -> dict[str, Any]:
    merge = github_truth.get("merge") if isinstance(github_truth.get("merge"), dict) else {}
    normalized = dict(merge)
    for key in ("merged", "merge_commit_sha", "merged_at", "merge_event_id"):
        if key not in normalized and key in github_truth:
            normalized[key] = github_truth[key]
    return normalized


def _can_render_pr_merged(
    *,
    proof_level: str,
    can_emit_pr_merged: bool,
    merge: dict[str, Any],
) -> bool:
    return bool(
        proof_level == "server_side_merge_proof"
        and can_emit_pr_merged
        and merge.get("merged") is True
        and _text(merge.get("merge_commit_sha")) is not None
        and _text(merge.get("merged_at")) is not None
        and _text(merge.get("merge_event_id")) is not None
    )


def _build_providers(provider_runtime: list[dict] | None) -> dict[str, Any]:
    if not isinstance(provider_runtime, list):
        section = _manual_gap_section("provider runtime unavailable")
        section.update({"items": []})
        return section
    items = [
        {
            "provider_id": _text(item.get("provider_id")),
            "runtime_kind": _text(item.get("runtime_kind") or item.get("runtime")),
            "transport": _text(item.get("transport")),
            "session_continuity": _text(
                item.get("session_continuity") or item.get("provider_binding_status")
            ),
            "heartbeat": _text(item.get("heartbeat")),
            "waiting_reason": _text(item.get("waiting_reason")),
            "proof_level": _normalize_proof_level(item.get("proof_level")),
        }
        for item in provider_runtime
        if isinstance(item, dict)
    ]
    return {
        "proof_level": "contract_proof",
        "fact_state": "observed",
        "source_refs": [],
        "blockers": [],
        "target_refs": [],
        "manual_gap_reason": None,
        "items": items,
    }


def _inspector_evidence(inspector: dict | None) -> dict[str, Any]:
    if not isinstance(inspector, dict):
        return {"memory_trace": None, "github_truth": None, "provider_runtime": None}
    return {
        "memory_trace": _first_dict(
            inspector,
            "memory_trace",
            "memoryos_trace",
            "memoryos_lite_trace",
            "memory",
        ),
        "github_truth": _first_dict(
            inspector,
            "github_truth",
            "github_server_truth",
            "github",
        ),
        "provider_runtime": _first_list(
            inspector,
            "provider_runtime",
            "provider_sessions",
            "providers",
        ),
    }


def _first_dict(data: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return None


def _first_list(data: dict[str, Any], *keys: str) -> list[dict[str, Any]] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return None


def _memory_context_count(
    memory_trace: dict[str, Any],
    context_package: dict[str, Any],
    key: str,
) -> int:
    for container in (context_package, memory_trace):
        value = container.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _manual_gap_section(reason: str) -> dict[str, Any]:
    return {
        "proof_level": "manual_gap",
        "fact_state": "manual_gap",
        "source_refs": [],
        "blockers": [],
        "target_refs": [],
        "manual_gap_reason": reason,
    }


def _message_envelope(message: dict[str, Any]) -> dict[str, Any]:
    envelope = message.get("envelope_json")
    if isinstance(envelope, str):
        try:
            parsed = json.loads(envelope)
        except ValueError:
            parsed = {}
        envelope = parsed
    if not isinstance(envelope, dict):
        envelope = {}
    return envelope


def _speech_act(envelope: dict[str, Any]) -> str | None:
    for key in ("speech_act", "act", "type"):
        value = _text(envelope.get(key))
        if value is None:
            continue
        value = value.lower()
        if value in SPEECH_ACTS:
            return value
    return None


def _is_blocking(envelope: dict[str, Any]) -> bool:
    if envelope.get("blocking") is True or envelope.get("blocked") is True:
        return True
    if _text(envelope.get("objection_level")) == "blocking":
        return True
    payload = envelope.get("payload")
    return isinstance(payload, dict) and (
        payload.get("blocking") is True or payload.get("blocked") is True
    )


def _blocker_reason(envelope: dict[str, Any], message: dict[str, Any]) -> str:
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        for key in ("summary", "reason", "message"):
            value = _text(payload.get(key))
            if value is not None:
                return value
    for key in ("summary", "reason", "content"):
        value = _text(envelope.get(key) or message.get(key))
        if value is not None:
            return value
    return "blocking deliberation item"


def _is_blueprint_freeze_act(act: dict[str, Any]) -> bool:
    decision_scope = _text(act.get("decision_scope")) or ""
    if "blueprint.freeze" in decision_scope:
        return True
    return any("blueprint:" in ref for ref in _list_refs(act.get("target_refs")))


def _inspector_freeze(inspector: dict | None) -> dict[str, Any] | None:
    if not isinstance(inspector, dict):
        return None
    for key in ("blueprint_freeze", "freeze", "blueprint"):
        value = inspector.get(key)
        if isinstance(value, dict):
            return value
    return None


def _worklist_items(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    items = envelope.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    worklist = envelope.get("worklist")
    if isinstance(worklist, list):
        return [item for item in worklist if isinstance(item, dict)]
    return []


def _lane_id(item: dict[str, Any]) -> str | None:
    return _text(
        item.get("lane_id")
        or item.get("feature_id")
        or item.get("lane_local_id")
    )


def _lane_ready(item: dict[str, Any]) -> bool:
    if item.get("ready") is True:
        return True
    status = _text(item.get("effective_status") or item.get("status"))
    return status == "ready"


def _lane_blocked(item: dict[str, Any]) -> bool:
    if item.get("blocked") is True:
        return True
    status = _text(item.get("effective_status") or item.get("status"))
    return status in {"blocked", "blocked_for_input", "awaiting_final_action"}


def _lane_blocker_reason(item: dict[str, Any]) -> str:
    for key in ("prompt_summary", "blocked_reason", "reason", "summary"):
        value = _text(item.get(key))
        if value is not None:
            return value
    return "lane is blocked"


def _dependency_ids(item: dict[str, Any]) -> list[str]:
    for key in ("scoped_dependency_ids", "lane_depends_on_ids", "depends_on"):
        refs = _list_refs(item.get(key))
        if refs:
            return refs
    return []


def _review_item(
    item: dict[str, Any],
    *,
    lane_id: str,
    source_ref: str,
) -> dict[str, Any] | None:
    verdict_id = _text(item.get("review_verdict_id") or item.get("verdict_id"))
    decision_id = _text(item.get("review_decision_id") or item.get("decision_id"))
    decision = _text(
        item.get("review_decision")
        or item.get("review_status")
        or item.get("review_verdict")
        or item.get("review_verdict_decision")
    )
    summary = _text(item.get("review_summary") or item.get("review_reason"))
    if decision is None and summary is None and verdict_id is None and decision_id is None:
        return None
    review = {
        "lane_id": lane_id,
        "decision": decision or "observed",
        "summary": summary or "",
        "source_refs": [source_ref],
        "target_refs": [f"lane:{lane_id}"],
    }
    if verdict_id is not None:
        review["verdict_id"] = verdict_id
        review["target_refs"].append(f"review_verdict:{verdict_id}")
    if decision_id is not None:
        review["decision_id"] = decision_id
        review["target_refs"].append(f"review_decision:{decision_id}")
    return review


def _source_lane_id(item: dict[str, Any]) -> str | None:
    return _text(
        item.get("source_lane_id")
        or item.get("patch_forward_source_lane_id")
        or item.get("failed_lane_id")
    )


def _github_blockers(
    required_checks: dict[str, Any],
    review_truth: dict[str, Any],
    github_truth: dict[str, Any],
) -> list[dict[str, Any]]:
    explicit = github_truth.get("blockers")
    if isinstance(explicit, list):
        return [item for item in explicit if isinstance(item, dict)]
    blockers: list[dict[str, Any]] = []
    check_state = _text(required_checks.get("state") or required_checks.get("status"))
    if check_state is not None and check_state not in {"success", "passed"}:
        blockers.append(
            {
                "kind": "required_checks",
                "reason": check_state,
                "source_refs": _list_refs(github_truth.get("source_refs")),
                "target_refs": _list_refs(github_truth.get("target_refs")),
            }
        )
    blocking_reviews = review_truth.get("blocking_reviews")
    if isinstance(blocking_reviews, list) and blocking_reviews:
        blockers.append(
            {
                "kind": "review_truth",
                "reason": "blocking reviews present",
                "source_refs": _list_refs(github_truth.get("source_refs")),
                "target_refs": _list_refs(github_truth.get("target_refs")),
            }
        )
    return blockers


def _refs(data: dict[str, Any], plural_key: str, singular_key: str) -> list[str]:
    refs = _list_refs(data.get(plural_key))
    singular = _text(data.get(singular_key))
    if singular is not None:
        _append_unique(refs, singular)
    return refs


def _list_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        text = _text(item)
        if text is not None:
            _append_unique(refs, text)
    return refs


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _normalize_proof_level(value: Any) -> str:
    text = _text(value)
    if text is None:
        return "contract_proof"
    if text == "contract":
        return "contract_proof"
    if text == "live":
        return "live_service_proof"
    return text


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
