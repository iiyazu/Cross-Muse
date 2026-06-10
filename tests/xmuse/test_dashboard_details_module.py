from __future__ import annotations

import importlib
import importlib.util

from xmuse import dashboard_api
from xmuse_core.platform import dashboard_details


def test_dashboard_api_uses_extracted_details_module() -> None:
    assert dashboard_api._peer_request_detail is dashboard_details._peer_request_detail
    assert dashboard_api._graph_authority_state is dashboard_details._graph_authority_state


def test_dashboard_details_delegates_graph_authority_to_extracted_module() -> None:
    assert importlib.util.find_spec("xmuse_core.platform.dashboard_graph_authority") is not None
    dashboard_graph_authority = importlib.import_module(
        "xmuse_core.platform.dashboard_graph_authority"
    )
    assert (
        dashboard_details._graph_authority_state
        is dashboard_graph_authority._graph_authority_state
    )


def test_dashboard_details_delegates_audit_helpers_to_extracted_module() -> None:
    assert importlib.util.find_spec("xmuse_core.platform.dashboard_audit_details") is not None
    dashboard_audit_details = importlib.import_module(
        "xmuse_core.platform.dashboard_audit_details"
    )
    assert dashboard_details._read_errors is dashboard_audit_details._read_errors
    assert dashboard_details._read_model_entries is dashboard_audit_details._read_model_entries
    assert dashboard_details._read_audit_events is dashboard_audit_details._read_audit_events
    assert dashboard_details._read_state_history is dashboard_audit_details._read_state_history
