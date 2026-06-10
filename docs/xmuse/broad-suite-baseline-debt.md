# Broad-Suite Baseline Debt

Updated: 2026-06-10

This registry keeps known broad-suite gaps visible. The contract smoke gate is
not a broad-suite green claim.

The contract smoke gate is not a broad-suite green claim.

| ID | Owner file | Repro command | Current failure summary | Priority | Closure rule |
| --- | --- | --- | --- | --- | --- |
| DR03-DEBT-001 | `docs/xmuse/contract-smoke-gates.md` | `uv run ruff format --check .` | Historical format drift remains outside the scoped contract format gate. | P1 | Full-repo format check passes or a staged reformat plan is merged and documented. |
| DR03-DEBT-002 | `tests/xmuse/test_chat_api.py` | `uv run pytest -q tests/xmuse/test_chat_api.py` | Legacy chat API cases around default participants, fork lineage, and compact cards are not mainline contract evidence. | P1 | Legacy expectations are either fixed, split into current focused tests, or archived with explicit compatibility rationale. |
| DR03-DEBT-003 | `docs/xmuse/memoryos-lite-runtime-compatibility.md` | `XMUSE_LIVE_MEMORYOS_LITE=1 XMUSE_MEMORYOS_LITE_URL=http://127.0.0.1:8000 uv run pytest -q tests/xmuse/test_memoryos_lite_interop.py` | Fake contract now covers public payload shape, ContextPackage parsing, durable namespace/session binding, and stale retry. Live service proof remains opt-in and distinguishes live smoke from restart/resume continuity. | P0 | Close only when release evidence captures a live MemoryOS Lite run proving ingest, context parsing, source traceability, and restart/recreate adapter session reuse. |
| DR03-DEBT-004 | `docs/xmuse/real-runtime-integration-gate.md` | `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume` | real provider / Ray / Codex writeback is outside no-secrets CI and cannot be claimed by fake-provider smoke. | P0 | A credentialed runtime gate records provider thread reuse, MCP writeback, restart/resume, and failure degradation evidence. |

## Rules

- Each debt item needs an owner file, reproduction command, current failure
  summary, priority, and closure rule.
- Focused green tests only prove their focused contracts.
- New runtime proof claims must name whether they are fake contract, live
  service, real provider, or server-side enforcement evidence.
