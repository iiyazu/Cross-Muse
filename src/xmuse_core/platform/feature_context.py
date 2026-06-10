from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_identity import feature_scope_id_from_lane
from xmuse_core.platform.memory_refs import serialize_memory_refs


@dataclass(frozen=True)
class FeatureContextBundle:
    feature_id: str | None
    conversation_id: str | None
    graph_id: str | None
    compact_summary: str
    primary_refs: list[dict[str, Any]]
    memory_refs: list[dict[str, Any]] = field(default_factory=list)
    title_source: str | None = None
    goal_source: str | None = None

    def as_prompt_context(self) -> str:
        refs = "\n".join(
            f"- {ref['kind']}: {ref['ref']} (exists={ref['exists']})"
            for ref in self.primary_refs
        )
        memory_refs = "\n".join(
            _memory_ref_prompt_line(ref)
            for ref in self.memory_refs
        )
        sections = [self.compact_summary]
        if refs:
            sections.append(f"## Primary References\n\n{refs}")
        if memory_refs:
            sections.append(f"## Memory References\n\n{memory_refs}")
        return "\n\n".join(section for section in sections if section)


def build_feature_context_bundle(
    lane: dict[str, Any],
    *,
    all_lanes: list[dict[str, Any]] | None = None,
    xmuse_root: Path,
) -> FeatureContextBundle:
    feature_scope_id = feature_scope_id_from_lane(lane)
    graph_id = _optional_str(lane.get("graph_id"))
    related_lanes = _related_lanes(
        lane,
        all_lanes=all_lanes,
        feature_scope_id=feature_scope_id,
        graph_id=graph_id,
    )
    primary_refs = _primary_refs(lane, related_lanes=related_lanes, xmuse_root=xmuse_root)
    memory_refs = _memory_refs(related_lanes)
    title, title_source = _feature_title(lane, feature_scope_id=feature_scope_id)
    goal, goal_source = _feature_goal(lane)
    return FeatureContextBundle(
        feature_id=feature_scope_id,
        conversation_id=_optional_str(lane.get("conversation_id")),
        graph_id=graph_id,
        compact_summary=_compact_summary(
            lane,
            related_lanes=related_lanes,
            feature_scope_id=feature_scope_id,
            graph_id=graph_id,
            title=title,
            title_source=title_source,
            goal=goal,
            goal_source=goal_source,
        ),
        primary_refs=primary_refs,
        memory_refs=memory_refs,
        title_source=title_source,
        goal_source=goal_source,
    )


def _related_lanes(
    lane: dict[str, Any],
    *,
    all_lanes: list[dict[str, Any]] | None,
    feature_scope_id: str | None,
    graph_id: str | None,
) -> list[dict[str, Any]]:
    conversation_id = _optional_str(lane.get("conversation_id"))
    candidate_lanes = list(all_lanes or [lane])
    if conversation_id is not None:
        candidate_lanes = [
            item
            for item in candidate_lanes
            if _optional_str(item.get("conversation_id")) == conversation_id
        ]
    if not all_lanes:
        return [lane]
    if feature_scope_id is not None:
        return [
            item
            for item in candidate_lanes
            if feature_scope_id_from_lane(item) == feature_scope_id
        ]
    if graph_id is not None:
        return [item for item in candidate_lanes if item.get("graph_id") == graph_id]
    return [lane]


def _compact_summary(
    lane: dict[str, Any],
    *,
    related_lanes: list[dict[str, Any]],
    feature_scope_id: str | None,
    graph_id: str | None,
    title: str,
    title_source: str | None,
    goal: str | None,
    goal_source: str | None,
) -> str:
    lines = [
        "## Feature Context",
        "",
        f"- Feature scope id: {feature_scope_id or 'missing'}",
        f"- Title: {title}",
        f"- Title source: {title_source or 'unavailable'}",
        f"- Graph id: {graph_id or 'missing'}",
    ]
    if goal:
        lines.append(f"- Goal: {goal}")
        lines.append(f"- Goal source: {goal_source or 'unavailable'}")
    criteria = [str(item) for item in lane.get("acceptance_criteria") or [] if str(item).strip()]
    if criteria:
        lines.extend(["", "### Acceptance Criteria"])
        lines.extend(f"- {item}" for item in criteria)
    lines.extend(["", "### Lane States"])
    for item in related_lanes:
        lane_id = _optional_str(item.get("feature_id")) or "unknown"
        status = _optional_str(item.get("status")) or "unknown"
        depends_on = item.get("depends_on") or []
        suffix = f" depends_on={depends_on}" if depends_on else ""
        lines.append(f"- {lane_id}: {status}{suffix}")
    review_summary = _optional_str(lane.get("review_summary"))
    if review_summary:
        lines.extend(["", "### Prior Review", "", review_summary])
    return "\n".join(lines)


def _primary_refs(
    lane: dict[str, Any],
    *,
    related_lanes: list[dict[str, Any]],
    xmuse_root: Path,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in lane.get("blueprint_refs") or []:
        if isinstance(ref, str) and ref.strip():
            refs.append(_ref("blueprint", ref.strip(), xmuse_root=xmuse_root))
    for item in related_lanes:
        lane_id = _optional_str(item.get("feature_id"))
        if lane_id:
            gate_ref = f"logs/gates/{lane_id}/report.json"
            refs.append(_ref("gate_report", gate_ref, xmuse_root=xmuse_root))
    return refs


def _memory_refs(related_lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lane in related_lanes:
        for ref in serialize_memory_refs(lane.get("memory_refs")):
            uri = ref.get("uri")
            if not isinstance(uri, str) or uri in seen:
                continue
            seen.add(uri)
            refs.append(ref)
    return refs


def _feature_title(
    lane: dict[str, Any],
    *,
    feature_scope_id: str | None,
) -> tuple[str, str | None]:
    title = _optional_str(lane.get("feature_title"))
    if title:
        return title, "lane_metadata.feature_title"
    if feature_scope_id:
        return feature_scope_id, "feature_scope_id"
    return "unknown", None


def _feature_goal(lane: dict[str, Any]) -> tuple[str | None, str | None]:
    goal = _optional_str(lane.get("feature_goal"))
    if goal:
        return goal, "lane_metadata.feature_goal"
    return None, None


def _ref(kind: str, ref: str, *, xmuse_root: Path) -> dict[str, Any]:
    path = xmuse_root / ref
    return {"kind": kind, "ref": ref, "exists": path.exists()}


def _memory_ref_prompt_line(ref: dict[str, Any]) -> str:
    category = str(ref.get("category") or "memory_ref")
    uri = str(ref.get("uri") or "memory://missing")
    evidence_refs = [
        str(item).strip()
        for item in ref.get("primary_evidence_refs", [])
        if str(item).strip()
    ]
    if evidence_refs:
        return f"- {category}: {uri} [primary refs: {', '.join(evidence_refs)}]"
    return f"- {category}: {uri}"


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
