# Path A: Foundation-First Roadmap

This document defines the full Foundation-First strengthening path for xmuse.
It is a staged production-readiness roadmap. Stages must land in order because
later gates depend on earlier independence and runtime contracts.

## Execution Rule

- Implement one phase per goal.
- Inside a phase, parallel agents may audit, reproduce, and review.
- Only one implementation lane should modify authoritative code at a time.
- Do not modify `/home/iiyatu/projects/python/memoryOS`.
- Do not weaken V7 groupchat semantics: real Ray + Codex app-server + MCP
  writeback remains the authoritative groupchat runtime path.

## Phase 1: Independent Installability

Goal: xmuse must install, build, import, and run a minimal chat/groupchat smoke
without relying on editable path dependency `../memoryOS`.

Required work:

- Audit all `memoryos-lite`, `memoryOS`, `../memoryOS`, and `memoryos_lite`
  references.
- Classify references as runtime-required, test-only, docs/history, removable
  legacy, or optional integration.
- Reproduce clean-environment install/build failure before fixing.
- Remove unused dependency, inline only tiny xmuse-owned interfaces if needed,
  or move memoryOS integration behind an optional extra.
- Verify wheel/sdist metadata contains no local memoryOS path dependency.

Hard gates:

- `pyproject.toml` has no editable `../memoryOS` dependency.
- `uv build` passes.
- Clean env `pip install -e .` passes.
- Clean env import smoke passes.
- Clean env Chat API + fake provider/groupchat smoke passes.
- No memoryOS repo files modified.
- Runtime behavior tests touched by the change still pass.

Output document: `docs/xmuse/archive/2026-06-pre-m7/walkthrough-maintenance-notes-v8.md`.

## Phase 2: Runtime Operations

Goal: xmuse runtime must have an explicit operational contract for process
lifecycle, backend selection, health, restart, degradation, and cleanup.

Required work:

- Document the production runtime topology: Chat API, MCP server, platform
  runner, Ray actor, Codex app-server, provider sessions, stores, and ports.
- Define one authoritative startup/shutdown contract.
- Define backend degradation matrix:
  - Ray available -> Ray GOD sessions
  - Ray unavailable -> documented local/fake fallback behavior
  - provider unavailable -> explicit degraded result, not silent success
- Add health checks for Ray worker, app-server thread/session, MCP endpoint, and
  scheduler progress.
- Add process cleanup gates for app-server, Ray workers, GCS, and runner tasks.

Hard gates:

- Real Ray + Codex app-server + MCP writeback smoke still passes.
- Restart/resume reuses provider session ID.
- No stale Ray/app-server processes remain after tests.
- Degraded fallback paths are traceable and never counted as happy path.
- `production-operations.md` records commands, lifecycle, health checks, and
  operator decisions.

Output document: `docs/xmuse/production-operations.md`.

## Phase 3: Quality Gates

Goal: xmuse must have a minimal CI and quality matrix that validates the
independent project state, not the old monorepo layout.

Required work:

- Add GitHub Actions or equivalent CI.
- Run gates in order: ruff, focused pytest, type check.
- Keep slow real-provider/Ray tests out of default CI unless explicitly marked.
- Add provider matrix:
  - Codex: primary
  - OpenCode: supported or experimental, based on current tests
  - Claude Code: experimental/planned unless proven otherwise
- Add config/secrets matrix for local dev and CI.

Hard gates:

- CI does not require sibling `../memoryOS`.
- CI green on focused gates.
- Type check is enabled with a scoped baseline and documented exclusions.
- Provider/config matrix is documented and matches code.

Output document: `docs/xmuse/quality-gates-and-provider-matrix.md`.

## Phase 4: Depth Hardening

Goal: harden durability and authority boundaries after installability,
operations, and CI are stable.

Required work:

- Define SQLite/schema migration strategy for chat store, feature graph store,
  GOD session registry, and durable artifacts.
- Define MCP permission model:
  - read tools
  - write tools
  - identity-bound GOD tools
  - admin/operator tools
  - audit requirements
- Automate resource cleanup where Phase 2 still relies on manual checks.
- Add regression tests for migration, permission rejection, and cleanup.

Hard gates:

- Old state can be detected and migrated or explicitly rejected.
- MCP write tools reject wrong identity, wrong conversation, and wrong scope.
- Cleanup automation has tests and does not hide degraded runtime states.

Output documents:

- `docs/xmuse/schema-migration-strategy.md`
- `docs/xmuse/mcp-permission-model.md`
- updates to `docs/xmuse/production-operations.md`

## Non-Goals

- Do not build new TUI features in this path.
- Do not optimize model latency unless a phase gate requires traceability.
- Do not couple xmuse back into memoryOS.
- Do not make fake provider success a substitute for real runtime gates.
- Do not start Phase 2 before Phase 1 independence is verified.

## Recommended Goal Order

1. V8 Independent installability closure.
2. V9 Runtime operations closure.
3. V10 Quality gates and provider matrix.
4. V11 Schema migration, MCP permission model, and cleanup hardening.
