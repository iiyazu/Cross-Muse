from xmuse_core.platform.rung4_beta_sentinel import (
    RUNG4_BETA_SENTINEL_ID,
    describe_rung4_beta_sentinel,
)


def test_rung4_beta_sentinel_exposes_runtime_artifact_id() -> None:
    assert RUNG4_BETA_SENTINEL_ID == "rung4-beta-lane-20260629-01"
    assert describe_rung4_beta_sentinel() == RUNG4_BETA_SENTINEL_ID
