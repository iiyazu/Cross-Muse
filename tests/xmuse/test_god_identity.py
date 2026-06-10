import pytest

from xmuse_core.agents.god_identity import (
    MissingGodFeatureIdentity,
    build_persistent_execute_god_identity,
    build_persistent_god_identity,
    feature_scope_id_from_lane,
)


def test_review_god_identity_is_feature_scoped_not_lane_scoped() -> None:
    first = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id="chat-workspace-frontdoor",
        lane_id="lane-a",
        require_feature=True,
    )
    second = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id="chat-workspace-frontdoor",
        lane_id="lane-b",
        require_feature=True,
    )

    assert first == second
    assert first.participant_id.startswith(
        "review-god-feature-chat-workspace-frontdoor-"
    )
    assert "lane-a" not in first.participant_id
    assert "lane-b" not in first.participant_id


def test_review_god_identity_does_not_collide_across_features() -> None:
    first = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id="frontdoor",
        lane_id="lane-a",
        require_feature=True,
    )
    second = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id="runtime",
        lane_id="lane-b",
        require_feature=True,
    )

    assert first.session_key != second.session_key
    assert first.participant_id != second.participant_id


def test_review_god_identity_is_collision_resistant_for_similar_feature_ids() -> None:
    first = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id="frontdoor.alpha",
        lane_id="lane-a",
        require_feature=True,
    )
    second = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id="frontdoor/alpha",
        lane_id="lane-b",
        require_feature=True,
    )
    long_first = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id=("shared-prefix-" * 12) + "a",
        lane_id="lane-c",
        require_feature=True,
    )
    long_second = build_persistent_god_identity(
        conversation_id="conv-1",
        role="review",
        feature_scope_id=("shared-prefix-" * 12) + "b",
        lane_id="lane-d",
        require_feature=True,
    )

    assert first.participant_id != second.participant_id
    assert long_first.participant_id != long_second.participant_id
    assert len(long_first.participant_id) <= 120


def test_review_god_identity_requires_feature_when_aligned_path_needs_it() -> None:
    with pytest.raises(MissingGodFeatureIdentity):
        build_persistent_god_identity(
            conversation_id="conv-1",
            role="review",
            feature_scope_id=None,
            lane_id="lane-a",
            require_feature=True,
        )


def test_execute_god_identity_can_be_conversation_scoped_without_feature() -> None:
    identity = build_persistent_god_identity(
        conversation_id="conv-1",
        role="execute",
        feature_scope_id=None,
        lane_id="lane-a",
        require_feature=False,
    )

    assert identity.participant_id == "execute-god"
    assert identity.session_key == "conv-1:execute-god"


def test_execute_god_identity_uses_feature_scope_hash_not_lane_id() -> None:
    first = build_persistent_god_identity(
        conversation_id="conv-1",
        role="execute",
        feature_scope_id="persistent.execute/god",
        lane_id="lane-a",
        require_feature=True,
    )
    second = build_persistent_god_identity(
        conversation_id="conv-1",
        role="execute",
        feature_scope_id="persistent.execute-god",
        lane_id="lane-a",
        require_feature=True,
    )

    assert first.participant_id.startswith("execute-god-feature-persistent-execute-god-")
    assert first.participant_id != second.participant_id
    assert "lane-a" not in first.participant_id


def test_persistent_execute_god_identity_requires_feature_scope() -> None:
    identity = build_persistent_execute_god_identity(
        conversation_id="conv-1",
        feature_scope_id="persistent-execute-god-child-worker-orchestration",
        lane_id="lane-a",
    )

    assert identity.role == "execute"
    assert identity.feature_scope_id == "persistent-execute-god-child-worker-orchestration"
    assert identity.session_key.startswith("conv-1:execute-god-feature-")

    with pytest.raises(MissingGodFeatureIdentity):
        build_persistent_execute_god_identity(
            conversation_id="conv-1",
            feature_scope_id=None,
            lane_id="lane-a",
        )


def test_lane_feature_id_is_not_feature_scope_by_default() -> None:
    assert feature_scope_id_from_lane({"feature_id": "lane-01"}) is None
    assert (
        feature_scope_id_from_lane(
            {
                "feature_id": "lane-01",
                "plan_feature_id": "persistent-execute-god-child-worker-orchestration",
            }
        )
        == "persistent-execute-god-child-worker-orchestration"
    )
