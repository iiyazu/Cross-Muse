from xmuse_core.platform.code_lane_sentinel import (
    CODE_LANE_SENTINEL_ID,
    describe_code_lane_sentinel,
)


def test_code_lane_sentinel_exposes_runtime_artifact_id() -> None:
    assert CODE_LANE_SENTINEL_ID == "rung3-code-lane-20260629-01"
    assert describe_code_lane_sentinel() == CODE_LANE_SENTINEL_ID
