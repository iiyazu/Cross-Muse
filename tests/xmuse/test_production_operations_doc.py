from pathlib import Path


def test_production_operations_doc_records_v9_runtime_contract() -> None:
    content = Path("docs/xmuse/production-operations.md").read_text(encoding="utf-8")

    required_fragments = [
        "Runtime Topology",
        "Startup",
        "Health",
        "Degradation Matrix",
        "Shutdown And Cleanup",
        "Restart And Resume",
        "uv run python -m xmuse.chat_api",
        "uv run python -m xmuse.mcp_server --port 8100",
        "uv run xmuse-platform-runner --peer-chat --mcp-port 8100",
        "uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100",
        "XMUSE_RAY_GOD_MCP=1",
        "leftover_codex_app_server",
        "leftover_raylet",
        "provider_session_id",
        "tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume",
    ]

    for fragment in required_fragments:
        assert fragment in content
