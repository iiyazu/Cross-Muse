from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from xmuse_core.knowledge import maintainer_contracts

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "xmuse_error_knowledge.py"


def load_knowledge_module():
    spec = importlib.util.spec_from_file_location("xmuse_error_knowledge", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_maintainer_contract_module_owns_contract_validation(tmp_path: Path) -> None:
    status = maintainer_contracts.validate_contract(tmp_path)

    assert status == {
        "valid": False,
        "bootstrap": True,
        "contract": None,
        "blockers": ["knowledge_maintainer_template.json missing"],
    }


def test_legacy_entrypoint_reexports_contract_helpers(tmp_path: Path) -> None:
    legacy = load_knowledge_module()
    contract_path = tmp_path / "xmuse/contracts/knowledge_maintainer_template.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text("{invalid json", encoding="utf-8")

    assert legacy.Finding is maintainer_contracts.Finding
    assert legacy.DEFAULT_ALLOWED_WRITES == maintainer_contracts.DEFAULT_ALLOWED_WRITES
    assert legacy.sha256_text("abc") == maintainer_contracts.sha256_text("abc")
    assert legacy.validate_contract(tmp_path)["blockers"] == [
        (
            "knowledge_maintainer_template.json invalid JSON: "
            "Expecting property name enclosed in double quotes"
        )
    ]


def test_source_refs_are_stable_and_deduplicated(tmp_path: Path) -> None:
    artifact = tmp_path / "xmuse/work/features/alpha/ack.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({"ack_level": "blocked"}), encoding="utf-8")
    digest = maintainer_contracts.sha256_file(artifact)
    ref = maintainer_contracts.source_ref(
        tmp_path,
        artifact,
        artifact_type="ack",
        feature_id="alpha",
        digest=digest,
        source_run_id="run-1",
    )

    assert ref == {
        "path": "xmuse/work/features/alpha/ack.json",
        "digest": digest,
        "artifact_type": "ack",
        "feature_id": "alpha",
        "source_run_id": "run-1",
    }
    assert maintainer_contracts.unique_source_refs([ref, dict(ref)]) == [ref]
    assert maintainer_contracts.source_digest_for_refs([ref]).startswith("sha256:")
