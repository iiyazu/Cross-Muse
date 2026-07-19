from __future__ import annotations

from pathlib import Path

from xmuse.architecture_dependency_report import SCHEMA_VERSION, build_report, validate_report

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _module(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_report_describes_current_tree_without_hard_architecture_violation() -> None:
    report = build_report(PROJECT_ROOT)

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["proof_boundary"] == "static_source_dependency_evidence_not_runtime_authority"
    assert report["scope"] == "repository_source_tree"
    assert str(PROJECT_ROOT) not in str(report)
    assert report["summary"]["module_count"] >= 100
    assert report["summary"]["edge_count"] > 0
    assert validate_report(report) == []
    assert report["capability_debts"] == []


def test_report_detects_synthetic_cycles_core_and_read_model_boundary_breaks(
    tmp_path: Path,
) -> None:
    _module(tmp_path, "src/xmuse_core/a.py", "import xmuse_core.b\n")
    _module(
        tmp_path,
        "src/xmuse_core/b.py",
        "import xmuse_core.a\nfrom xmuse import chat_api\nimport memoryos_lite\n",
    )
    _module(
        tmp_path,
        "src/xmuse_core/chat/room_projection.py",
        "from xmuse_core.chat.room_execution_operator_store import RoomExecutionOperatorStore\n",
    )
    _module(tmp_path, "src/xmuse_core/chat/room_execution_operator_store.py", "pass\n")
    _module(tmp_path, "xmuse/chat_api.py", "pass\n")

    report = build_report(tmp_path)

    assert report["hard_violations"]["import_cycles"] == [["xmuse_core.a", "xmuse_core.b"]]
    assert report["hard_violations"]["core_to_application"] == [
        {"source": "xmuse_core.b", "target": "xmuse.chat_api"}
    ]
    assert report["hard_violations"]["core_to_memoryos_lite"] == [
        {"source": "xmuse_core.b", "target": "memoryos_lite"}
    ]
    assert report["hard_violations"]["read_model_to_privileged"] == [
        {
            "source": "xmuse_core.chat.room_projection",
            "target": "xmuse_core.chat.room_execution_operator_store",
        }
    ]
    assert validate_report(report) == [
        "architecture_import_cycle",
        "architecture_core_to_application",
        "architecture_core_to_memoryos_lite",
        "architecture_read_model_privileged",
    ]


def test_report_exposes_narrow_adapter_wrapping_wide_authority_without_path_suppression(
    tmp_path: Path,
) -> None:
    _module(
        tmp_path,
        "src/xmuse_core/chat/room_execution_store.py",
        "class RoomExecutionStore:\n    pass\n",
    )
    _module(
        tmp_path,
        "src/xmuse_core/chat/room_execution_controller_store.py",
        "from xmuse_core.chat.room_execution_store import RoomExecutionStore\n"
        "\n"
        "class RoomExecutionControllerStore:\n"
        "    def __init__(self):\n"
        "        self._ledger = RoomExecutionStore()\n",
    )

    report = build_report(tmp_path)

    assert validate_report(report) == []
    assert report["capability_debts"] == [
        {
            "module": "xmuse_core.chat.room_execution_controller_store",
            "adapter": "RoomExecutionControllerStore",
            "concrete_store": "RoomExecutionStore",
        }
    ]


def test_report_exposes_private_ledger_wrapped_by_a_narrow_store(tmp_path: Path) -> None:
    _module(
        tmp_path,
        "src/xmuse_core/chat/room_execution_ledger.py",
        "class _ExecutionLedger:\n    pass\n",
    )
    _module(
        tmp_path,
        "src/xmuse_core/chat/room_execution_runtime_store.py",
        "from xmuse_core.chat.room_execution_ledger import _ExecutionLedger\n"
        "\n"
        "class RoomExecutionRuntimeStore:\n"
        "    def __init__(self):\n"
        "        self._ledger = _ExecutionLedger()\n",
    )

    report = build_report(tmp_path)

    assert report["capability_debts"] == [
        {
            "module": "xmuse_core.chat.room_execution_runtime_store",
            "adapter": "RoomExecutionRuntimeStore",
            "concrete_store": "_ExecutionLedger",
        }
    ]
