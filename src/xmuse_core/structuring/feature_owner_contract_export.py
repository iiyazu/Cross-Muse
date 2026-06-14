from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from xmuse_core.structuring.feature_owner_contract import (
    FeatureOwnerExecutionContract,
    build_feature_owner_execution_contract,
)


def export_feature_owner_contracts_from_graph_set(
    *,
    graph_set_artifact: str | Path,
    output_dir: str | Path,
    feature_ids: Sequence[str] = (),
    allowed_files: Sequence[str] = (),
    memory_refs: Sequence[str] = (),
    required_checks: Sequence[str] = (),
    review_profile: str = "internal-adversarial",
    patch_forward_policy: str = "review_failures_spawn_patch_forward_lane",
    rollback_constraints: Sequence[str] = ("do not mutate feature_lanes.json",),
) -> list[Path]:
    """Export feature-owner contracts from graph-set authority.

    The exporter deliberately reads only the graph-set artifact. It does not read
    feature_lanes.json and it does not synthesize lane terminal state.
    """

    graph_set_path = Path(graph_set_artifact)
    graph_set = _load_graph_set(graph_set_path)
    contracts = build_feature_owner_contracts_from_graph_set(
        graph_set=graph_set,
        graph_set_artifact=graph_set_path,
        feature_ids=feature_ids,
        allowed_files=allowed_files,
        memory_refs=memory_refs,
        required_checks=required_checks,
        review_profile=review_profile,
        patch_forward_policy=patch_forward_policy,
        rollback_constraints=rollback_constraints,
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for contract in contracts:
        path = destination / f"{_safe_filename(contract.feature_id)}-contract.json"
        path.write_text(
            json.dumps(contract.model_dump(mode="json"), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def build_feature_owner_contracts_from_graph_set(
    *,
    graph_set: Mapping[str, Any],
    graph_set_artifact: str | Path,
    feature_ids: Sequence[str] = (),
    allowed_files: Sequence[str] = (),
    memory_refs: Sequence[str] = (),
    required_checks: Sequence[str] = (),
    review_profile: str = "internal-adversarial",
    patch_forward_policy: str = "review_failures_spawn_patch_forward_lane",
    rollback_constraints: Sequence[str] = ("do not mutate feature_lanes.json",),
) -> list[FeatureOwnerExecutionContract]:
    graph_set_id = _required_text(graph_set.get("id"), "graph_set.id")
    selected_feature_ids = set(_text_list(feature_ids))
    features_by_graph = _features_by_graph_id(graph_set)
    graphs = _dict_rows(graph_set.get("graphs"))
    contracts: list[FeatureOwnerExecutionContract] = []
    for graph in graphs:
        graph_id = _required_text(graph.get("id"), "graph.id")
        feature = features_by_graph.get(graph_id, {})
        feature_id = _required_text(
            feature.get("feature_id") or graph.get("feature_id") or graph_id,
            f"feature_id for graph {graph_id}",
        )
        if selected_feature_ids and feature_id not in selected_feature_ids:
            continue
        lanes = _normalized_lanes(graph=graph, feature_plan=graph_set.get("feature_plan"))
        contract_allowed_files = _allowed_files(
            explicit_allowed_files=allowed_files,
            graph=graph,
            feature=feature,
            lanes=lanes,
        )
        contracts.append(
            build_feature_owner_execution_contract(
                feature_id=feature_id,
                objective=_objective(feature=feature, graph=graph),
                graph_set_id=graph_set_id,
                feature_graph_id=graph_id,
                source_authority="graph_set_store",
                source_refs=_source_refs(
                    graph_set_id=graph_set_id,
                    graph_set_artifact=graph_set_artifact,
                    graph=graph,
                    feature=feature,
                ),
                allowed_files=contract_allowed_files,
                lanes=lanes,
                memory_refs=memory_refs,
                required_checks=_required_checks(required_checks),
                review_profile=review_profile,
                patch_forward_policy=patch_forward_policy,
                rollback_constraints=rollback_constraints,
            )
        )
    if selected_feature_ids:
        exported = {contract.feature_id for contract in contracts}
        missing = sorted(selected_feature_ids - exported)
        if missing:
            raise ValueError("feature id(s) not found in graph-set: " + ", ".join(missing))
    if not contracts:
        raise ValueError("graph-set did not contain exportable feature graphs")
    return contracts


def _load_graph_set(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected graph-set JSON object")
    return payload


def _features_by_graph_id(graph_set: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    feature_plan = graph_set.get("feature_plan")
    if not isinstance(feature_plan, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for feature in _dict_rows(feature_plan.get("features")):
        graph_id = _optional_text(feature.get("graph_id"))
        if graph_id is not None:
            result[graph_id] = feature
    return result


def _normalized_lanes(
    *,
    graph: Mapping[str, Any],
    feature_plan: object,
) -> list[dict[str, Any]]:
    graph_id = _required_text(graph.get("id"), "graph.id")
    conversation_id = _conversation_id(graph=graph, feature_plan=feature_plan)
    lanes: list[dict[str, Any]] = []
    for lane in _dict_rows(graph.get("lanes")):
        normalized = dict(lane)
        normalized.setdefault("graph_id", graph_id)
        if conversation_id is not None:
            normalized.setdefault("conversation_id", conversation_id)
        if _optional_text(normalized.get("lane_local_id")) is None:
            feature_id = _optional_text(normalized.get("feature_id"))
            if feature_id is not None:
                normalized["lane_local_id"] = feature_id
        lanes.append(normalized)
    return lanes


def _conversation_id(
    *,
    graph: Mapping[str, Any],
    feature_plan: object,
) -> str | None:
    graph_conversation = _optional_text(graph.get("conversation_id"))
    if graph_conversation is not None:
        return graph_conversation
    if isinstance(feature_plan, Mapping):
        return _optional_text(feature_plan.get("conversation_id"))
    return None


def _objective(*, feature: Mapping[str, Any], graph: Mapping[str, Any]) -> str:
    for value in (feature.get("goal"), feature.get("title"), graph.get("objective")):
        text = _optional_text(value)
        if text is not None:
            return text
    return _required_text(graph.get("id"), "graph.id")


def _source_refs(
    *,
    graph_set_id: str,
    graph_set_artifact: str | Path,
    graph: Mapping[str, Any],
    feature: Mapping[str, Any],
) -> list[str]:
    refs = [
        f"graph-set:{graph_set_id}",
        f"artifact:{Path(graph_set_artifact)}",
        *_text_list(feature.get("blueprint_refs")),
        *_text_list(graph.get("source_refs")),
    ]
    return _dedupe(refs)


def _allowed_files(
    *,
    explicit_allowed_files: Sequence[str],
    graph: Mapping[str, Any],
    feature: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
) -> list[str]:
    files = [
        *_text_list(explicit_allowed_files),
        *_text_list(feature.get("allowed_files")),
        *_text_list(feature.get("expected_touched_areas")),
        *_text_list(graph.get("allowed_files")),
        *_text_list(graph.get("expected_touched_areas")),
    ]
    for lane in lanes:
        files.extend(_text_list(lane.get("allowed_files")))
        files.extend(_text_list(lane.get("expected_touched_areas")))
    files = _dedupe(files)
    if not files:
        raise ValueError(
            "feature owner contracts require allowed files; pass --allowed-file "
            "or include expected_touched_areas in the graph-set lanes"
        )
    return files


def _required_checks(values: Sequence[str]) -> list[str]:
    checks = _text_list(values)
    return checks or ["uv run ruff check ."]


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _required_text(value: object, label: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{label} is required")
    return text


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
