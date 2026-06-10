from __future__ import annotations

from xmuse_core.platform import orchestrator, orchestrator_lane_flow


def test_orchestrator_exposes_extracted_lane_flow_functions() -> None:
    assert orchestrator.dispatch_lane_flow is orchestrator_lane_flow.dispatch_lane
    assert orchestrator.run_execution_god_flow is orchestrator_lane_flow.run_execution_god
