"""Signal-summary ordering extracted from SelfEvolutionController.

Orders a bundle's signal refs for human-readable summarization: lane signals
first (recovery/fallback lanes prioritized), then lane counts, then the
gate-report families, then anything else. Pure functions over ref strings.
"""

from __future__ import annotations

import json


def ordered_signal_summary_refs(signal_refs: list[str]) -> list[str]:
    """Order signal refs for summarization, interleaving by family."""
    lane_refs = rank_lane_signal_summary_refs(
        [signal for signal in signal_refs if signal.startswith("lane_signal:")]
    )
    lane_count_refs = [signal for signal in signal_refs if signal.startswith("lane_counts:")]
    other_refs = [
        signal
        for signal in signal_refs
        if not (
            signal.startswith("lane_signal:")
            or signal.startswith("lane_counts:")
            or signal.startswith("gate_report:")
            or signal.startswith("gate_report_resolution:")
            or signal.startswith("gate_report_diagnostic:")
            or signal.startswith("gate_report_result:")
        )
    ]
    gate_report_refs = [
        signal for signal in signal_refs if signal.startswith("gate_report:")
    ]
    gate_report_diagnostic_refs = [
        signal for signal in signal_refs if signal.startswith("gate_report_diagnostic:")
    ]
    gate_report_resolution_refs = [
        signal for signal in signal_refs if signal.startswith("gate_report_resolution:")
    ]
    gate_report_result_refs = [
        signal for signal in signal_refs if signal.startswith("gate_report_result:")
    ]
    if len(lane_refs) >= 3:
        return [
            *lane_refs[:2],
            *lane_count_refs[:1],
            *gate_report_refs[:1],
            *gate_report_result_refs[:1],
            *gate_report_diagnostic_refs[:1],
            *gate_report_resolution_refs[:1],
            *gate_report_refs[1:],
            *gate_report_result_refs[1:],
            *gate_report_diagnostic_refs[1:],
            *gate_report_resolution_refs[1:],
            *lane_refs[2:],
            *lane_count_refs[1:],
            *other_refs,
        ]
    return [
        *lane_refs,
        *lane_count_refs,
        *gate_report_refs,
        *gate_report_result_refs,
        *gate_report_diagnostic_refs,
        *gate_report_resolution_refs,
        *other_refs,
    ]


def rank_lane_signal_summary_refs(lane_refs: list[str]) -> list[str]:
    """Stable-sort lane signal refs, prioritizing recovery/fallback lanes."""
    return [
        item
        for _, _, item in sorted(
            (
                (_lane_signal_summary_priority(item), index, item)
                for index, item in enumerate(lane_refs)
            ),
            key=lambda item: (item[0], item[1]),
        )
    ]


def _lane_signal_summary_priority(signal: str) -> int:
    try:
        payload = json.loads(signal.removeprefix("lane_signal:"))
    except json.JSONDecodeError:
        return 10
    if not isinstance(payload, dict):
        return 10
    if payload.get("manual_recovery") or payload.get("review_fallback"):
        return 0
    return 10
