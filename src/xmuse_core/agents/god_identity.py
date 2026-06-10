from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


class MissingGodFeatureIdentity(ValueError):
    """Raised when aligned persistent GOD routing lacks feature scope."""


@dataclass(frozen=True)
class PersistentGodIdentity:
    conversation_id: str
    role: str
    participant_id: str
    feature_scope_id: str | None = None

    @property
    def session_key(self) -> str:
        return f"{self.conversation_id}:{self.participant_id}"


def build_persistent_execute_god_identity(
    *,
    conversation_id: str,
    feature_scope_id: str | None,
    lane_id: str,
) -> PersistentGodIdentity:
    """Derive the aligned persistent Execute GOD identity for a lane request."""

    return build_persistent_god_identity(
        conversation_id=conversation_id,
        role="execute",
        feature_scope_id=feature_scope_id,
        lane_id=lane_id,
        require_feature=True,
    )


def build_persistent_god_identity(
    *,
    conversation_id: str,
    role: str,
    feature_scope_id: str | None,
    lane_id: str,
    require_feature: bool,
) -> PersistentGodIdentity:
    """Derive conversation/feature scoped GOD identity.

    ``lane_id`` is accepted only so callers cannot accidentally hide that they
    have it.  It must not participate in aligned Review GOD identity.
    """

    clean_conversation_id = _require_text(conversation_id, "conversation_id")
    clean_role = _safe_fragment(_require_text(role, "role"))
    clean_feature_scope_id = _clean_optional(feature_scope_id)
    if require_feature and clean_feature_scope_id is None:
        raise MissingGodFeatureIdentity(
            f"{clean_role} GOD routing requires feature_scope_id for lane {lane_id}"
        )
    if clean_feature_scope_id is None:
        participant_id = f"{clean_role}-god"
    else:
        participant_id = (
            f"{clean_role}-god-feature-{_safe_fragment(clean_feature_scope_id, max_chars=48)}"
            f"-{_stable_hash(clean_feature_scope_id)}"
        )
    return PersistentGodIdentity(
        conversation_id=clean_conversation_id,
        role=clean_role,
        participant_id=participant_id,
        feature_scope_id=clean_feature_scope_id,
    )


def feature_scope_id_from_lane(lane: dict[str, object]) -> str | None:
    """Return the feature-plan feature id, never the lane primary key."""

    for key in ("feature_plan_feature_id", "plan_feature_id", "feature_scope_id"):
        value = lane.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _safe_fragment(value: str, *, max_chars: int = 80) -> str:
    fragment = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in value
    ).strip("-")
    return (fragment or "scope")[:max_chars]


def _stable_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]
