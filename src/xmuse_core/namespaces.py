from __future__ import annotations

from hashlib import sha256


def build_conversation_graph_set_id(
    *,
    conversation_id: str,
    feature_plan_id: str,
    version: int,
) -> str:
    return (
        f"{_safe_fragment(conversation_id)}--{_safe_fragment(feature_plan_id)}"
        f"-graph-set-v{version}"
    )


def build_projection_lane_id(
    *,
    conversation_id: str,
    graph_id: str,
    lane_local_id: str,
) -> str:
    digest = _stable_hash(f"{conversation_id}|{graph_id}|{lane_local_id}")
    return (
        f"lane:{_safe_fragment(conversation_id)}:{_safe_fragment(graph_id)}"
        f":{_safe_fragment(lane_local_id)}:{digest}"
    )


def build_scoped_storage_name(*, conversation_id: str, object_id: str) -> str:
    return f"{_safe_fragment(conversation_id)}--{object_id}"


def normalize_memory_ref(
    ref: str,
    *,
    conversation_id: str,
    feature_scope_id: str | None = None,
) -> str:
    stripped = ref.strip()
    if not stripped.startswith("memory://"):
        return stripped
    if stripped.startswith("memory://global/"):
        return stripped
    if stripped.startswith("memory://feature/"):
        suffix = stripped.removeprefix("memory://feature/").strip("/")
        if not suffix:
            raise ValueError("memory feature ref must include a path")
        if feature_scope_id is None:
            raise ValueError("feature-scoped memory refs require feature_scope_id")
        return (
            f"memory://conversation/{conversation_id}/feature/{feature_scope_id}/{suffix}"
        )
    if not stripped.startswith("memory://conversation/"):
        raise ValueError(
            "memory refs must be conversation-scoped or explicitly promoted via memory://global/"
        )

    remainder = stripped.removeprefix("memory://conversation/")
    normalized_prefix = f"memory://conversation/{conversation_id}/"
    feature_prefix = normalized_prefix + "feature/"
    if stripped.startswith(feature_prefix):
        if feature_scope_id is None:
            raise ValueError("feature-scoped memory refs require feature_scope_id")
        scoped = stripped.removeprefix(feature_prefix)
        scoped_feature_id = scoped.split("/", 1)[0]
        if scoped_feature_id != feature_scope_id:
            raise ValueError("memory refs must stay within the fork feature scope")
        return stripped
    if stripped.startswith(normalized_prefix):
        return stripped

    local_path = remainder.strip("/")
    if not local_path:
        raise ValueError("memory conversation ref must include a path")
    if "/" not in local_path:
        return normalized_prefix + local_path

    target_conversation_id = local_path.split("/", 1)[0]
    if target_conversation_id != conversation_id:
        raise ValueError(
            "memory refs must stay within the conversation scope or use memory://global/"
        )
    return stripped


def _safe_fragment(value: str, *, max_chars: int = 80) -> str:
    fragment = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in value.strip()
    ).strip("-")
    return (fragment or "scope")[:max_chars]


def _stable_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]
