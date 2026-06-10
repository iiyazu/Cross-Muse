from __future__ import annotations

import json

from xmuse_core.platform.dashboard_read_models import (
    build_dashboard_dead_letters,
    build_read_model_status,
)


def test_build_dashboard_dead_letters_is_read_only(tmp_path):
    incidents_path = tmp_path / "coordinator_incidents.jsonl"
    incidents_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "dead_letter",
                        "incident_id": "dl-1",
                        "updated_at": "2026-06-02T00:01:00Z",
                    }
                ),
                json.dumps(
                    {
                        "kind": "degraded",
                        "incident_id": "deg-1",
                        "updated_at": "2026-06-02T00:02:00Z",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    model = build_dashboard_dead_letters(tmp_path)

    assert model["kind"] == "dashboard_dead_letters"
    assert model["read_only"] is True
    assert model["source_authority"] == "coordinator_incidents"
    assert model["degraded"] is True
    assert model["counts"] == {"dead_letter": 1, "degraded": 1, "lifecycle": 0}
    assert incidents_path.exists()


def test_build_read_model_status_reports_degraded_files_without_writes(tmp_path):
    read_models = tmp_path / "read_models"
    read_models.mkdir()
    (read_models / "resolutions.json").write_text(
        json.dumps({"resolutions": [{"id": "res-1"}]}),
        encoding="utf-8",
    )
    (read_models / "verdicts.json").write_text("{invalid", encoding="utf-8")

    model = build_read_model_status(tmp_path)

    assert model["kind"] == "read_model_status"
    assert model["read_only"] is True
    assert model["source_authority"] == "read_models_directory"
    assert model["degraded"] is True
    models = {item["name"]: item for item in model["models"]}
    assert models["resolutions"]["status"] == "ok"
    assert models["resolutions"]["item_count"] == 1
    assert models["verdicts"]["status"] == "invalid_json"
    assert not (read_models / "self_evolution_audit.json").exists()
