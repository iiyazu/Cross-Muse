from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
README = PROJECT_ROOT / "docs" / "xmuse" / "README.md"
PEER_CHAT_GATE_DOC = PROJECT_ROOT / "docs" / "xmuse" / "peer-chat-runtime-gate.md"

PEER_CHAT_GATE_TARGETS = {
    "src/xmuse_core/chat/context_assembler.py",
    "src/xmuse_core/chat/mentions.py",
    "src/xmuse_core/chat/peer_scheduler.py",
    "src/xmuse_core/chat/peer_service.py",
    "src/xmuse_core/chat/prompt_builder.py",
    "tests/xmuse/test_groupchat_collaboration_runtime.py",
    "tests/xmuse/test_peer_chat_api.py",
    "tests/xmuse/test_peer_chat_mentions.py",
    "tests/xmuse/test_peer_chat_prompt_builder.py",
    "tests/xmuse/test_peer_chat_runtime_gate.py",
    "tests/xmuse/test_peer_chat_scheduler.py",
    "tests/xmuse/test_peer_chat_service.py",
    "tests/xmuse/test_package_boundaries.py",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_peer_chat_runtime_gate_is_no_secrets_and_focused() -> None:
    workflow = _read(CI_WORKFLOW)
    peer_job = workflow[workflow.index("peer-chat-runtime-gate:") :]

    assert "workflow_dispatch:" in workflow
    assert "concurrency:" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "peer-chat-runtime-gate:" in peer_job
    assert "uv sync --frozen --all-groups" in peer_job
    assert "uv run ruff check" in peer_job
    assert "uv run pytest -q" in peer_job

    for target in PEER_CHAT_GATE_TARGETS:
        assert target in peer_job

    for forbidden in (
        "secrets.",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "../memoryOS",
        "XMUSE_LIVE_MEMORYOS_LITE",
        "test_real_ray_codex_app_server_mcp_writeback",
    ):
        assert forbidden not in peer_job


def test_peer_chat_runtime_gate_doc_records_proof_boundary() -> None:
    doc = _read(PEER_CHAT_GATE_DOC)
    readme = _read(README)

    for fragment in (
        "contract proof",
        "fake/local runtime proof",
        "no-secrets default PR gate",
        "workflow_dispatch",
        "real Ray/Codex app-server writeback",
        "branch-protection truth",
        "production-ready groupchat",
        "live MemoryOS behavior",
        "full L8-L10",
        "full L1-L11",
    ):
        assert fragment in doc

    assert "docs/xmuse/peer-chat-runtime-gate.md" in readme
