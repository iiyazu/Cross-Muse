from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.frozen_blueprint_evidence_capture import (
    capture_frozen_blueprint_evidence,
)
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
)


def test_capture_frozen_blueprint_evidence_exports_replay_ready_artifact(
    tmp_path: Path,
) -> None:
    blueprint = _write_blueprint(
        tmp_path / "mission-blueprint.json",
        status=MissionBlueprintStatus.FROZEN,
    )
    output = tmp_path / "frozen-blueprint-production-evidence.json"

    artifact = capture_frozen_blueprint_evidence(
        run_id="overnight-blueprint",
        blueprint_artifact=blueprint,
        output_path=output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == artifact
    assert artifact["schema_version"] == "xmuse.production_evidence.v1"
    assert artifact["run_id"] == "overnight-blueprint"
    assert artifact["stage_id"] == "S3"
    assert artifact["action"] == "frozen_blueprint_verified"
    assert artifact["status"] == "ok"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["source_authority"] == "mission_blueprint_v1"
    assert artifact["source_refs"] == [
        "mission_blueprint:bp-overnight:r2",
        "conversation:conv-1",
        "message:proposal-1",
        "message:challenge-1",
    ]
    assert artifact["target_refs"] == [
        "blueprint:bp-overnight",
        "conversation:conv-1",
    ]
    assert artifact["artifacts"] == [str(blueprint)]
    assert artifact["blocked_reason"] is None
    assert artifact["summary"] == (
        "Mission blueprint bp-overnight revision 2 is frozen with 2 "
        "acceptance contract(s)."
    )

    replay_bundle = capture_overnight_replay_bundle(
        run_id="overnight-blueprint",
        artifacts_dir=tmp_path / "empty-release-gates",
        output_path=tmp_path / "bundle.json",
        section_artifacts={"frozen_blueprint": output},
    )
    sections = {section["section_id"]: section for section in replay_bundle["sections"]}
    assert sections["frozen_blueprint"]["status"] == "ok"
    assert sections["frozen_blueprint"]["proof_level"] == "contract_proof"
    assert sections["frozen_blueprint"]["source_authority"] == "mission_blueprint_v1"


def test_capture_frozen_blueprint_evidence_reports_manual_gap_for_draft_blueprint(
    tmp_path: Path,
) -> None:
    blueprint = _write_blueprint(
        tmp_path / "mission-blueprint.json",
        status=MissionBlueprintStatus.DRAFT,
    )

    artifact = capture_frozen_blueprint_evidence(
        run_id="overnight-blueprint",
        blueprint_artifact=blueprint,
        output_path=tmp_path / "frozen-blueprint-production-evidence.json",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["blocked_reason"] == (
        "mission blueprint bp-overnight status is draft, expected frozen"
    )
    assert artifact["next_action"] == (
        "Freeze the mission blueprint through the deliberation/freeze contract "
        "and regenerate frozen blueprint replay evidence."
    )


def test_frozen_blueprint_evidence_capture_cli_writes_artifact(tmp_path: Path) -> None:
    from xmuse.frozen_blueprint_evidence_capture import main

    blueprint = _write_blueprint(
        tmp_path / "mission-blueprint.json",
        status=MissionBlueprintStatus.FROZEN,
    )
    output = tmp_path / "frozen-blueprint-production-evidence.json"

    assert (
        main(
            [
                "--run-id",
                "overnight-blueprint",
                "--blueprint",
                str(blueprint),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "ok"
    assert artifact["action"] == "frozen_blueprint_verified"


def test_frozen_blueprint_evidence_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-frozen-blueprint-evidence-capture"]
        == "xmuse.frozen_blueprint_evidence_capture:main"
    )


def _write_blueprint(path: Path, *, status: MissionBlueprintStatus) -> Path:
    blueprint = MissionBlueprintV1(
        blueprint_id="bp-overnight",
        conversation_id="conv-1",
        revision=2,
        goal="Close overnight autonomy evidence loop.",
        scope=["frozen blueprint", "feature graph"],
        constraints=["Use uv run.", "Do not create xmuse/__init__.py."],
        non_goals=["No live proof without live artifact."],
        acceptance_contracts=[
            "Frozen blueprint source refs are preserved.",
            "Replay bundle does not upgrade proof levels.",
        ],
        repo_areas=["src/xmuse_core/structuring", "src/xmuse_core/platform"],
        open_questions=[],
        decision_log=[
            {
                "decision": "Freeze blueprint before feature execution.",
                "source_refs": ["message:challenge-1"],
            }
        ],
        source_refs=["message:proposal-1", "message:challenge-1"],
        status=status,
        approved_by=["god-architect", "god-review"],
    )
    path.write_text(
        json.dumps(blueprint.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
