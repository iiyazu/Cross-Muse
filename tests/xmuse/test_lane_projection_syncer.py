import json

import pytest

from xmuse_core.platform.projection.syncer import (
    DuplicateLaneError,
    LaneProjectionSyncer,
    ProjectionRevisionConflict,
)
from xmuse_core.platform.state_validation import StateValidationError


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_update_increments_projection_revision_and_strips_runtime_telemetry(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)

    result = syncer.append_lane(
        {
            "feature_id": "lane-1",
            "status": "pending",
            "prompt": "Implement.",
            "failure_error": "large traceback",
            "recovery_events": [{"event": "retry"}],
            "last_recovery_event": {"event": "retry"},
        }
    )

    data = _read_json(path)
    assert result["projection_revision"] == 1
    assert data["projection_revision"] == 1
    assert data["lanes"][0]["feature_id"] == "lane-1"
    assert "prompt" not in data["lanes"][0]
    assert data["lanes"][0]["prompt_summary"] == "Implement."
    assert data["lanes"][0]["prompt_ref"] == "logs/lane_prompts/lane-1.md"
    assert "failure_error" not in data["lanes"][0]
    assert "recovery_events" not in data["lanes"][0]
    assert "last_recovery_event" not in data["lanes"][0]
    assert (tmp_path / "logs" / "lane_prompts" / "lane-1.md").read_text(encoding="utf-8") == (
        "Implement."
    )


def test_append_lane_strips_projection_quarantine_fields(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)

    result = syncer.append_lane(
        {
            "feature_id": "lane-1",
            "status": "pending",
            "prompt": "Implement.",
            "worker_command": ["codex", "exec"],
            "provider_health": {"diagnostic_summary": "secret"},
            "stdout": "raw stdout",
            "stderr": "raw stderr",
            "worker_logs": ["tail -f"],
        }
    )

    data = _read_json(path)
    assert result["projection_revision"] == 1
    assert data["lanes"][0]["feature_id"] == "lane-1"
    assert "prompt" not in data["lanes"][0]
    assert data["lanes"][0]["prompt_summary"] == "Implement."
    assert data["lanes"][0]["prompt_ref"] == "logs/lane_prompts/lane-1.md"
    for forbidden in (
        "worker_command",
        "provider_health",
        "stdout",
        "stderr",
        "worker_logs",
    ):
        assert forbidden not in data["lanes"][0]


def test_command_hash_is_stable_across_lane_and_metadata_sanitization(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)

    appended = syncer.append_lane(
        {
            "feature_id": "lane-1",
            "status": "pending",
            "prompt": "Implement.",
            "worker_command": ["codex", "exec", "--json"],
        }
    )

    data = _read_json(path)
    stored_lane = data["lanes"][0]
    assert "worker_command" not in stored_lane
    assert appended["command_hash"].startswith("sha256:")
    assert stored_lane["command_hash"] == appended["command_hash"]

    updated = syncer.metadata_update(
        "lane-1",
        {
            "worker_command": ["codex", "exec", "--json"],
            "stdout": "transient output",
        },
    )

    data = _read_json(path)
    stored_lane = data["lanes"][0]
    assert "worker_command" not in stored_lane
    assert "stdout" not in stored_lane
    assert updated["command_hash"] == appended["command_hash"]
    assert stored_lane["command_hash"] == appended["command_hash"]


def test_replace_lanes_applies_projection_sanitizer(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)

    replaced = syncer.replace_lanes(
        [
            {
                "feature_id": "lane-1",
                "status": "pending",
                "prompt": "Replace queue entry.",
                "worker_command": ["codex", "exec", "--json"],
                "stdout": "raw stdout",
            }
        ]
    )

    stored_lane = _read_json(path)["lanes"][0]
    assert replaced["lanes"][0]["command_hash"].startswith("sha256:")
    assert replaced["lanes"][0]["command_hash"] == stored_lane["command_hash"]
    assert replaced["lanes"][0]["prompt"] == "Replace queue entry."
    assert "worker_command" not in replaced["lanes"][0]
    assert "stdout" not in replaced["lanes"][0]
    assert "prompt" not in stored_lane
    assert stored_lane["prompt_summary"] == "Replace queue entry."
    assert stored_lane["prompt_ref"] == "logs/lane_prompts/lane-1.md"
    assert "worker_command" not in stored_lane
    assert "stdout" not in stored_lane


def test_update_preserves_existing_prompt_ref_instead_of_overwriting_with_summary(
    tmp_path,
):
    path = tmp_path / "xmuse" / "feature_lanes.json"
    prompt_path = tmp_path / "xmuse" / "work" / "runtime_first_prompts" / "lane-1.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("Full raw prompt.\n", encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "Compact prompt. Read prompt_ref.",
                        "prompt_summary": "Existing summary",
                        "prompt_ref": "xmuse/work/runtime_first_prompts/lane-1.md",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    syncer = LaneProjectionSyncer(path)
    hydrated = syncer.read()["lanes"][0]
    syncer.metadata_update("lane-1", {"operator_note": "keep prompt ref"})

    data = _read_json(path)
    lane = data["lanes"][0]
    assert hydrated["prompt"] == "Compact prompt. Read prompt_ref."
    assert "prompt" not in lane
    assert lane["prompt_summary"] == "Existing summary"
    assert lane["prompt_ref"] == "xmuse/work/runtime_first_prompts/lane-1.md"
    assert "logs/lane_prompts" not in lane["prompt_ref"]
    assert lane["operator_note"] == "keep prompt ref"


def test_read_hydrates_repo_relative_prompt_ref_after_projection_strips_prompt(tmp_path):
    path = tmp_path / "xmuse" / "feature_lanes.json"
    prompt_path = tmp_path / "xmuse" / "work" / "runtime_first_prompts" / "lane-1.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("Full raw prompt.\n", encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt_ref": "xmuse/work/runtime_first_prompts/lane-1.md",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lane = LaneProjectionSyncer(path).read()["lanes"][0]

    assert lane["prompt"] == "Full raw prompt.\n"


def test_expected_revision_prevents_stale_write(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)
    syncer.append_lane({"feature_id": "lane-1", "status": "pending", "prompt": "One."})

    with pytest.raises(ProjectionRevisionConflict):
        syncer.update(lambda data: data, expected_revision=0)

    assert _read_json(path)["projection_revision"] == 1


def test_validation_rejects_duplicate_lane_ids_before_write(tmp_path):
    path = tmp_path / "feature_lanes.json"
    path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {"feature_id": "existing", "status": "pending", "prompt": "p"}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    syncer = LaneProjectionSyncer(path)

    with pytest.raises(StateValidationError, match="duplicate feature_id"):
        syncer.replace_lanes(
            [
                {"feature_id": "dup", "status": "pending", "prompt": "one"},
                {"feature_id": "dup", "status": "pending", "prompt": "two"},
            ]
        )

    data = _read_json(path)
    assert data["projection_revision"] == 7
    assert data["lanes"][0]["feature_id"] == "existing"


def test_metadata_update_rejects_status_change(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)
    syncer.append_lane({"feature_id": "lane-1", "status": "pending", "prompt": "One."})

    with pytest.raises(StateValidationError, match="status cannot change"):
        syncer.metadata_update("lane-1", {"status": "dispatched"})

    assert syncer.read()["lanes"][0]["status"] == "pending"


def test_default_validation_rejects_invalid_lane_shapes(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)

    with pytest.raises(StateValidationError, match="status must be a string"):
        syncer.append_lane({"feature_id": "bad-status", "status": 123, "prompt": "x"})

    with pytest.raises(StateValidationError, match="capabilities must be a list"):
        syncer.append_lane(
            {
                "feature_id": "bad-capabilities",
                "status": "pending",
                "prompt": "x",
                "capabilities": "not-list",
            }
        )

    assert not path.exists()


def test_duplicate_append_can_raise_or_return_existing_without_write(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)
    syncer.append_lane({"feature_id": "lane-1", "status": "pending", "prompt": "One."})

    with pytest.raises(DuplicateLaneError):
        syncer.append_lane({"feature_id": "lane-1", "status": "pending", "prompt": "Dup."})

    returned = syncer.append_lane(
        {"feature_id": "lane-1", "status": "dispatched", "prompt": "Dup."},
        on_duplicate="return_existing",
    )

    data = _read_json(path)
    assert returned["status"] == "pending"
    assert returned["prompt"] == "One."
    assert "prompt" not in data["lanes"][0]
    assert data["lanes"][0]["prompt_summary"] == "One."
    assert data["lanes"][0]["prompt_ref"] == "logs/lane_prompts/lane-1.md"
    assert data["projection_revision"] == 1
    assert len(data["lanes"]) == 1


def test_update_lane_applies_operator_control_status_change_under_revision(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)
    syncer.append_lane({"feature_id": "lane-1", "status": "done", "prompt": "One."})

    updated = syncer.update_lane(
        "lane-1",
        lambda lane: lane.update({"status": "pending", "rework_requested": True}),
    )

    data = _read_json(path)
    assert updated["status"] == "pending"
    assert updated["rework_requested"] is True
    assert data["projection_revision"] == 2


def test_update_lane_returns_sanitized_lane_after_mutation(tmp_path):
    path = tmp_path / "feature_lanes.json"
    syncer = LaneProjectionSyncer(path)
    syncer.append_lane({"feature_id": "lane-1", "status": "pending", "prompt": "One."})

    updated = syncer.update_lane(
        "lane-1",
        lambda lane: lane.update(
            {
                "worker_command": ["codex", "exec", "--json"],
                "stdout": "transient output",
                "operator_note": "kept",
            }
        ),
    )

    stored_lane = _read_json(path)["lanes"][0]
    assert updated["command_hash"] == stored_lane["command_hash"]
    assert updated["command_hash"].startswith("sha256:")
    assert updated["operator_note"] == "kept"
    assert "worker_command" not in updated
    assert "stdout" not in updated
    assert "worker_command" not in stored_lane
    assert "stdout" not in stored_lane
