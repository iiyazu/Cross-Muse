from __future__ import annotations

import json

from xmuse_core.platform.coordinator_incidents import summarize_coordinator_incidents


def test_summarize_coordinator_incidents_separates_total_and_active(tmp_path):
    incidents = tmp_path / "coordinator_incidents.jsonl"
    incidents.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "dead_letter",
                        "incident_id": "dl-active",
                        "runner_id": "runner-1",
                    }
                ),
                json.dumps(
                    {
                        "kind": "degraded",
                        "incident_id": "deg-historical",
                        "runner_id": "runner-old",
                    }
                ),
                json.dumps(
                    {
                        "kind": "lifecycle",
                        "incident_id": "life-active",
                        "runner_id": "runner-1",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_coordinator_incidents(
        xmuse_root=tmp_path,
        active_runner_ids={"runner-1"},
    )

    assert summary["counts"] == {"dead_letter": 1, "degraded": 1, "lifecycle": 1}
    assert summary["active_counts"] == {
        "dead_letter": 1,
        "degraded": 0,
        "lifecycle": 1,
    }
    assert [item["incident_id"] for item in summary["latest_dead_letters"]] == [
        "dl-active"
    ]
    assert summary["latest_active_degraded"] == []


def test_summarize_coordinator_incidents_tolerates_missing_file(tmp_path):
    summary = summarize_coordinator_incidents(xmuse_root=tmp_path)

    assert summary["counts"] == {"dead_letter": 0, "degraded": 0, "lifecycle": 0}
    assert summary["latest_dead_letters"] == []
    assert summary["read_error"] is None
