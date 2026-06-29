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
| DR05-DEBT-001 | `docs/xmuse/archive/2026-06-proof-closure-legacy/self-iteration-runtime-closure.md` | Inspect GitHub branch protection / rulesets for `main`. | Local workflow, CODEOWNERS, and PR template evidence exists, but server-side branch protection and required-review enforcement are not verified by local tests. | P0 | Close only when GitHub server settings or connector evidence proves required checks and CODEOWNER review enforcement for `main`. |
| DR05-DEBT-002 | `docs/xmuse/archive/2026-06-proof-closure-legacy/self-iteration-runtime-closure.md` | `uv run pytest -q tests/xmuse/test_self_iteration_runtime_closure.py` | Self-iteration replay uses deterministic structured fixture, not multi-CLI natural GOD conversation traffic. | P1 | Close when a real multi-participant GOD session exports equivalent speech-act refs and freezes the same blueprint contract. |
| DR05-DEBT-003 | `xmuse/chat_api.py` / `xmuse/mcp_server.py` | Auth/RBAC review for Chat API and MCP write surfaces. | MemoryOS remains REST-first and MCP memory writes stay denied unless auth/RBAC is proven; current closure does not prove a production auth layer. | P0 | Close when Chat API and MCP write routes enforce documented auth/RBAC and focused tests cover denied/allowed paths. |
| DR05-DEBT-004 | `docs/xmuse/archive/2026-06-proof-closure-legacy/self-iteration-runtime-closure.md` | `XMUSE_LIVE_MEMORYOS_LITE=1 ... uv run pytest -q tests/xmuse/test_memoryos_lite_interop.py` | Closure proves fake REST-first writeback through `FakeMemoryOSClient`; live MemoryOS Lite release evidence remains opt-in. | P0 | Close when live MemoryOS Lite records blueprint, lane evidence, review, and gate outcome with source refs and restart-stable namespace binding. |
| DR06-DEBT-001 | `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md` | `gh api repos/iiyazu/Cross-Muse/branches/main/protection` | Local `gh` is not authenticated and connector did not expose branch protection/ruleset details; `GitHubServerSideTruthEvidence` now records this as `manual_gap`, but server-side required checks and CODEOWNER enforcement remain unproven. | P0 | Close when authenticated GitHub server evidence proves or disproves branch protection, required checks, and Code Owner review enforcement for `main`. |
| DR06-DEBT-002 | `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md` | `uv run pytest -q tests/xmuse/test_self_iteration_runtime_closure.py::test_exported_deliberation_replay_keeps_contract_fixture_separate_from_natural_proof` | Export contract separates deterministic fixture proof from natural deliberation proof, but no real multi-GOD runtime transcript has been captured. | P1 | Close when a live/exported multi-GOD transcript with blockers, source refs, and freeze decision is captured and replayed. |
| DR06-DEBT-003 | `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md` | `XMUSE_LIVE_MEMORYOS_LITE=1 XMUSE_MEMORYOS_LITE_URL=<url> uv run pytest -q tests/xmuse/test_memoryos_lite_interop.py::test_live_memoryos_lite_service_contract_is_explicit_opt_in` | Adapter supports trace evidence, but no committed live MemoryOS Lite trace artifact exists. | P0 | Close when live session create/ingest/build-context/trace evidence is captured with source refs and token/context metadata. |
| DR06-DEBT-004 | `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md` | Operator runbook in `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md#real-raycodexmcp-runtime-soak` | Real Ray/Codex/MCP runtime soak remains operator-run and is not default CI evidence. | P0 | Close when a real provider/Ray/Codex/MCP evidence pack is captured and tied to the same blueprint, lane, GitHub, and MemoryOS refs. |

## Rules

- Each debt item needs an owner file, reproduction command, current failure
  summary, priority, and closure rule.
- Focused green tests only prove their focused contracts.
- New runtime proof claims must name whether they are fake contract, live
  service, real provider, or server-side enforcement evidence.
