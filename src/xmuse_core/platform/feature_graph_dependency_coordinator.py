from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatusRecord,
    FeatureGraphSet,
)


@dataclass(frozen=True)
class FeatureGraphDependentReleaseOutcome:
    graph_set: FeatureGraphSet
    released: list[FeatureGraphExecutionStatusRecord]


def release_ready_feature_graph_dependents(
    *,
    store: FeatureGraphStatusStore,
    graph_set: FeatureGraphSet,
    updated_at: str,
) -> FeatureGraphDependentReleaseOutcome:
    """Release graph-native dependents whose feature dependencies are merged.

    This is a coordinator-facing helper. It consumes a graph-set artifact and
    writes only through ``FeatureGraphStatusStore``; it does not read or mutate
    the legacy lane projection.
    """

    validated_graph_set = FeatureGraphSet.model_validate(graph_set.model_dump(mode="json"))
    released = store.release_ready_dependents(
        validated_graph_set,
        updated_at=updated_at,
    )
    return FeatureGraphDependentReleaseOutcome(
        graph_set=validated_graph_set,
        released=released,
    )
