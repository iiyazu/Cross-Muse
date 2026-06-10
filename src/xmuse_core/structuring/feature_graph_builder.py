from __future__ import annotations

from pathlib import PurePath

from xmuse_core.namespaces import build_conversation_graph_set_id
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)


def build_feature_graph_set(
    feature_plan: FeaturePlan,
    *,
    graph_set_id: str | None = None,
) -> FeatureGraphSet:
    source_refs = _feature_plan_source_refs(feature_plan)
    return FeatureGraphSet(
        id=graph_set_id or _default_graph_set_id(feature_plan),
        version=feature_plan.version,
        source_refs=source_refs,
        feature_plan=feature_plan,
        graphs=[
            _build_feature_graph(feature_plan, feature, source_refs=source_refs)
            for feature in feature_plan.features
        ],
    )


def _default_graph_set_id(feature_plan: FeaturePlan) -> str:
    return build_conversation_graph_set_id(
        conversation_id=feature_plan.conversation_id,
        feature_plan_id=feature_plan.id,
        version=feature_plan.version,
    )


def _build_feature_graph(
    feature_plan: FeaturePlan,
    feature: FeaturePlanFeature,
    *,
    source_refs: list[str],
) -> LaneGraph:
    return LaneGraph(
        id=feature.graph_id,
        conversation_id=feature_plan.conversation_id,
        resolution_id=feature_plan.resolution_id,
        version=feature_plan.version,
        status="planned",
        source_refs=list(source_refs),
        lanes=_build_feature_lanes(feature),
    )


def _build_feature_lanes(feature: FeaturePlanFeature) -> list[LaneNode]:
    work_areas = list(feature.expected_touched_areas)
    if not work_areas:
        work_areas = ["implementation"]
    area_labels = _disambiguated_area_labels(work_areas)

    root_lanes = [
        LaneNode(
            feature_id=_lane_id(feature.feature_id, index, label),
            title=f"{feature.title}: {_area_title(area)}",
            prompt=_work_lane_prompt(feature, area),
            blueprint_refs=list(feature.blueprint_refs),
            expected_touched_areas=[] if area == "implementation" else [area],
            feature_group=feature.feature_id,
        )
        for index, (area, label) in enumerate(
            zip(work_areas, area_labels, strict=True),
            start=1,
        )
    ]
    verify_lane = LaneNode(
        feature_id=_lane_id(feature.feature_id, 99, "verify"),
        title=f"{feature.title}: Verify",
        prompt=(
            f"Verify feature {feature.feature_id}: {feature.goal} "
            "Run the focused checks needed to prove the acceptance criteria."
        ),
        depends_on=[lane.feature_id for lane in root_lanes],
        blueprint_refs=list(feature.blueprint_refs),
        acceptance_criteria=list(feature.acceptance_criteria),
        expected_touched_areas=list(feature.expected_touched_areas),
        feature_group=feature.feature_id,
    )
    return [*root_lanes, verify_lane]


def _feature_plan_source_refs(feature_plan: FeaturePlan) -> list[str]:
    refs = [f"feature_plan:{feature_plan.id}:v{feature_plan.version}"]
    for feature in feature_plan.features:
        for ref in feature.blueprint_refs:
            if ref not in refs:
                refs.append(ref)
    return refs


def _work_lane_prompt(feature: FeaturePlanFeature, area: str) -> str:
    if area == "implementation":
        scope = "the implementation area implied by this feature"
    else:
        scope = area
    return (
        f"Implement the {scope} slice for feature {feature.feature_id}. "
        f"Goal: {feature.goal}"
    )


def _lane_id(feature_id: str, index: int, label: str) -> str:
    return f"{feature_id}-{index:02d}-{_safe_fragment(label)}"


def _area_label(area: str) -> str:
    if area == "implementation":
        return "implement"
    path = PurePath(area)
    if path.suffix:
        return f"{path.stem}-{path.suffix.lstrip('.')}"
    if path.name:
        return path.name
    return area


def _disambiguated_area_labels(areas: list[str]) -> list[str]:
    labels = [_area_label(area) for area in areas]
    duplicated = {label for label in labels if labels.count(label) > 1}
    if not duplicated:
        return labels
    return [
        _path_area_label(area) if label in duplicated else label
        for area, label in zip(areas, labels, strict=True)
    ]


def _path_area_label(area: str) -> str:
    if area == "implementation":
        return "implement"
    path = PurePath(area)
    if path.suffix:
        return "-".join([*path.with_suffix("").parts, path.suffix.lstrip(".")])
    return "-".join(path.parts) or area


def _area_title(area: str) -> str:
    if area == "implementation":
        return "Implementation"
    return PurePath(area).name or area


def _safe_fragment(value: str) -> str:
    fragment = "".join(
        char if char.isalnum() else "-"
        for char in value.strip().lower()
    ).strip("-")
    while "--" in fragment:
        fragment = fragment.replace("--", "-")
    return fragment or "lane"
