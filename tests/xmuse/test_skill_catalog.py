from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from xmuse_core.skills.catalog import (
    MAX_BODY_BYTES,
    MAX_FILE_BYTES,
    SkillCatalog,
    SkillCatalogDriftError,
    SkillCatalogError,
)


def _skill_text(
    name: str,
    *,
    roles: list[str] | None = None,
    triggers: list[str] | None = None,
    not_for: list[str] | None = None,
    priority: int = 100,
    body: str = "# Instructions\n\nUse evidence.\n",
    extra_frontmatter: str = "",
) -> str:
    policy = {
        "roles": roles or ["review"],
        "triggers": triggers or ["review"],
        "not_for": not_for or ["small talk"],
        "priority": priority,
    }
    return (
        "---\n"
        f"name: {name}\n"
        "description: Evidence-based review instructions.\n"
        f"{extra_frontmatter}"
        "metadata:\n"
        '  version: "1.0.0"\n'
        f"  xmuse: '{json.dumps(policy, ensure_ascii=False, separators=(',', ':'))}'\n"
        "---\n"
        f"{body}"
    )


def _write_skill(root: Path, name: str, *, text: str | None = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(text if text is not None else _skill_text(name), encoding="utf-8")
    return path


def test_bundled_catalog_has_standard_skills_and_does_not_retain_body_or_repr_path():
    catalog = SkillCatalog.load_bundled()

    assert [item.skill_id for item in catalog.descriptors] == [
        "evidence-review",
        "execution-patch-authoring",
        "execution-patch-review",
        "implementation-planning",
    ]
    assert all(item.content_sha256.startswith("sha256:") for item in catalog.descriptors)
    assert all(item.instructions_sha256.startswith("sha256:") for item in catalog.descriptors)
    assert all("instructions" not in item.__dict__ for item in catalog.descriptors)
    assert "bundled" not in repr(catalog)
    assert "SKILL.md" not in repr(catalog.descriptors[0])


def test_catalog_hash_is_canonical_and_materialize_returns_only_selected_body(tmp_path):
    root = tmp_path / "skills"
    path_b = _write_skill(root, "b-skill")
    _write_skill(root, "a-skill")
    catalog = SkillCatalog.load(root)

    canonical = json.dumps(
        [[item.skill_id, item.version, item.content_sha256] for item in catalog.descriptors],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert catalog.catalog_sha256 == f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    decision = catalog.select(participant_role="review", source_text="[skill:b-skill]\nreview this")
    activation = catalog.materialize(decision)
    assert activation is not None
    assert activation.instructions == "# Instructions\n\nUse evidence.\n"
    assert (
        catalog.materialize(catalog.select(participant_role="architect", source_text="review this"))
        is None
    )

    path_b.write_text(_skill_text("b-skill", body="changed\n"), encoding="utf-8")
    with pytest.raises(SkillCatalogDriftError) as exc_info:
        catalog.materialize(decision)
    assert exc_info.value.code == "room_skill_catalog_drift"


@pytest.mark.parametrize(
    "directory_name,text",
    [
        ("a-", _skill_text("a-")),
        ("a--b", _skill_text("a--b")),
        ("right-name", _skill_text("wrong-name")),
        ("missing-open", "name: missing-open\n---\nbody\n"),
        ("missing-close", "---\nname: missing-close\n"),
        (
            "duplicate-key",
            _skill_text("duplicate-key").replace(
                "description: Evidence-based review instructions.\n",
                "description: first\ndescription: second\n",
            ),
        ),
        (
            "anchor-alias",
            _skill_text("anchor-alias").replace(
                "description: Evidence-based review instructions.",
                "description: &shared Evidence-based review instructions.\nlicense: *shared",
            ),
        ),
        (
            "merge-key",
            _skill_text("merge-key").replace(
                "name: merge-key\n",
                "defaults: &defaults\n  license: MIT\n<<: *defaults\nname: merge-key\n",
            ),
        ),
        (
            "custom-tag",
            _skill_text("custom-tag").replace(
                "description: Evidence-based review instructions.",
                "description: !custom Evidence-based review instructions.",
            ),
        ),
        (
            "bad-metadata",
            _skill_text("bad-metadata").replace('  version: "1.0.0"', "  version: 1"),
        ),
    ],
)
def test_catalog_rejects_invalid_standard_or_unsafe_yaml(tmp_path, directory_name, text):
    root = tmp_path / "skills"
    _write_skill(root, directory_name, text=text)

    with pytest.raises(SkillCatalogError) as exc_info:
        SkillCatalog.load(root)
    assert exc_info.value.code == "room_skill_catalog_invalid"


@pytest.mark.parametrize(
    "policy",
    [
        {"roles": [], "triggers": ["review"], "not_for": ["no"], "priority": 1},
        {"roles": ["review"], "triggers": ["x"], "not_for": ["no"], "priority": 1},
        {
            "roles": ["review"],
            "triggers": ["ＲＥＶＩＥＷ", "review"],
            "not_for": ["no"],
            "priority": 1,
        },
        {"roles": ["review"], "triggers": ["review"], "not_for": ["no"], "priority": True},
        {
            "roles": ["review"],
            "triggers": ["review"],
            "not_for": ["no"],
            "priority": 1,
            "unknown": "field",
        },
    ],
)
def test_catalog_rejects_out_of_bounds_or_ambiguous_xmuse_metadata(tmp_path, policy):
    root = tmp_path / "skills"
    text = _skill_text("bounded").replace(
        '{"roles":["review"],"triggers":["review"],"not_for":["small talk"],"priority":100}',
        json.dumps(policy, ensure_ascii=False, separators=(",", ":")),
    )
    _write_skill(root, "bounded", text=text)

    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)


def test_catalog_enforces_file_body_catalog_and_utf8_bounds(tmp_path):
    root = tmp_path / "skills"
    path = _write_skill(
        root,
        "body-limit",
        text=_skill_text("body-limit", body="x" * MAX_BODY_BYTES),
    )
    assert SkillCatalog.load(root).descriptors[0].skill_id == "body-limit"

    path.write_text(_skill_text("body-limit", body="x" * (MAX_BODY_BYTES + 1)), encoding="utf-8")
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)

    root = tmp_path / "file-skills"
    path = _write_skill(root, "file-limit")
    base = path.read_text(encoding="utf-8")
    padding_size = MAX_FILE_BYTES - len(base.encode()) - len('  padding: ""\n')
    padded = base.replace("metadata:\n", f'metadata:\n  padding: "{"x" * padding_size}"\n')
    path.write_text(padded, encoding="utf-8")
    assert path.stat().st_size == MAX_FILE_BYTES
    assert SkillCatalog.load(root)
    with path.open("ab") as handle:
        handle.write(b"x")
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)

    root = tmp_path / "invalid-utf8"
    path = _write_skill(root, "invalid-utf8")
    path.write_bytes(path.read_bytes() + b"\xff")
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)

    root = tmp_path / "many"
    for index in range(33):
        _write_skill(root, f"skill-{index}")
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)


def test_catalog_rejects_root_directory_and_file_symlinks(tmp_path):
    real = tmp_path / "real"
    path = _write_skill(real, "safe-skill")
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real, target_is_directory=True)
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(linked_root)

    root = tmp_path / "directory-links"
    root.mkdir()
    (root / "linked-skill").symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)

    root = tmp_path / "file-links"
    directory = root / "linked-file"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").symlink_to(path)
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)

    root = tmp_path / "broken-file-links"
    directory = root / "broken-file"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").symlink_to(root / "missing-SKILL.md")
    with pytest.raises(SkillCatalogError):
        SkillCatalog.load(root)


def test_materialize_rejects_decision_metadata_or_catalog_drift(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root, "review-skill")
    catalog = SkillCatalog.load(root)
    decision = catalog.select(participant_role="review", source_text="review")

    with pytest.raises(SkillCatalogDriftError):
        catalog.materialize(replace(decision, catalog_sha256="sha256:wrong"))
    with pytest.raises(SkillCatalogDriftError):
        catalog.materialize(replace(decision, skill_instructions_sha256="sha256:wrong"))
