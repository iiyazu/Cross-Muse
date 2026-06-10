from __future__ import annotations

PRODUCTION_SLO_TARGETS = {
    "blueprint_freeze_p95_seconds": 90,
    "ready_lane_dispatch_p95_seconds": 5,
    "memory_search_p95_ms_sqlite_poc": 300,
    "feature_pr_cycle_p95_minutes_excluding_human_wait": 30,
}

GITHUB_APP_MIGRATION_PLAN = [
    "Create GitHub App with checks, pull request, and contents permissions.",
    "Move fake Draft PR ops behind a GitHub App adapter.",
    "Mirror required checks and annotations into xmuse read models.",
    "Gate merge-ready status on GitHub App check conclusions.",
    "Keep local fake ops as deterministic tests for contract compatibility.",
]
