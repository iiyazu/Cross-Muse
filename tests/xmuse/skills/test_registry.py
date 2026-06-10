"""Tests for skill registry and base protocol."""

from __future__ import annotations

import json

import pytest

from xmuse_core.skills import SkillContext, create_default_registry
from xmuse_core.skills.models import LaneDefinition, LaneGraph
from xmuse_core.skills.pipeline import DesignPipelineSkill
from xmuse_core.skills.registry import SkillRegistry


def test_registry_register_and_list():
    reg = SkillRegistry()
    assert reg.list_skills() == []

    from xmuse_core.skills.review_gate import ReviewGateSkill

    reg.register("test_review", ReviewGateSkill, tags=["test"])
    skills = reg.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "test_review"
    assert skills[0].tags == ["test"]


def test_registry_get():
    reg = SkillRegistry()
    from xmuse_core.skills.brainstorm import BrainstormSkill

    reg.register("bs", BrainstormSkill)
    assert reg.get("bs") is BrainstormSkill
    assert reg.get("nonexistent") is None


def test_registry_instantiate():
    reg = SkillRegistry()
    from xmuse_core.skills.brainstorm import BrainstormSkill

    reg.register("bs", BrainstormSkill)
    ctx = SkillContext(
        registry=None,
        session_manager=None,
        skill_registry=reg,
    )
    instance = reg.instantiate("bs", ctx)
    assert isinstance(instance, BrainstormSkill)
    assert instance.name == "bs"


def test_registry_instantiate_unknown_raises():
    reg = SkillRegistry()
    ctx = SkillContext(registry=None, session_manager=None, skill_registry=reg)
    with pytest.raises(KeyError, match="not registered"):
        reg.instantiate("unknown", ctx)


def test_create_default_registry():
    reg = create_default_registry()
    names = [s.name for s in reg.list_skills()]
    assert "brainstorm" in names
    assert "spec_to_lanes" in names
    assert "review_gate" in names
    assert "design_pipeline" in names


def test_design_pipeline_emit_lanes_uses_projection_revision(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"lanes": [{"feature_id": "existing", "status": "pending"}]}) + "\n",
        encoding="utf-8",
    )
    skill = DesignPipelineSkill(
        SkillContext(
            registry=None,
            session_manager=None,
            skill_registry=SkillRegistry(),
            lanes_path=lanes_path,
        )
    )
    graph = LaneGraph(
        source_spec="spec.json",
        lanes=[
            LaneDefinition(feature_id="existing", prompt="Existing."),
            LaneDefinition(feature_id="new-lane", prompt="New lane."),
        ],
        concurrency_groups=[["existing", "new-lane"]],
        critical_path=["new-lane"],
    )

    skill._emit_lanes(graph)

    data = json.loads(lanes_path.read_text(encoding="utf-8"))
    assert data["projection_revision"] == 1
    assert [lane["feature_id"] for lane in data["lanes"]] == ["existing", "new-lane"]
