from pathlib import Path


def test_mainline_contract_docs_define_current_product_path() -> None:
    entrypoint = Path("docs/xmuse/README.md").read_text(encoding="utf-8")
    contracts = Path("docs/xmuse/mainline-contracts.md").read_text(encoding="utf-8")

    required_entrypoint_fragments = [
        "docs/xmuse/mainline-contracts.md",
        "GOD groupchat deliberation",
        "frozen blueprint",
        "feature/lane/laneDAG",
        "GitHub merge gate",
        "REST-first MemoryOS",
        "blueprint freeze 是去中心化 GOD deliberation 与中心化 execution/review 的边界",
        "`feature_lanes.json`",
    ]
    required_contract_fragments = [
        "GOD groupchat deliberation",
        "frozen blueprint",
        "feature/lane/laneDAG",
        "centralized execution/review",
        "GitHub merge gate",
        "REST-first MemoryOS",
        "Blueprint freeze is the boundary between decentralized deliberation and",
        "Feature/lane plan",
        "graph-set / lane graph durable stores",
        "`feature_lanes.json` is a live queue/projection, not authority.",
        "Fake groupchat demos, historical master-loop paths",
    ]

    for fragment in required_entrypoint_fragments:
        assert fragment in entrypoint
    for fragment in required_contract_fragments:
        assert fragment in contracts


def test_mainline_contract_docs_map_required_module_families() -> None:
    contracts = Path("docs/xmuse/mainline-contracts.md").read_text(encoding="utf-8")

    required_module_fragments = [
        "src/xmuse_core/chat/protocol_v2.py",
        "src/xmuse_core/chat/deliberation_engine.py",
        "src/xmuse_core/structuring/mission_blueprint_v1.py",
        "src/xmuse_core/structuring/lane_planner_v2.py",
        "src/xmuse_core/platform/orchestrator_lane_flow.py",
        "src/xmuse_core/platform/review_plane.py",
        "src/xmuse_core/platform/execution/github_ops.py",
        "src/xmuse_core/platform/execution/subagent_runtime.py",
        "src/xmuse_core/integrations/memoryos_client.py",
        "src/xmuse_core/integrations/memoryos_namespace.py",
        "src/xmuse_core/platform/mcp_permissions.py",
    ]

    for fragment in required_module_fragments:
        assert fragment in contracts
