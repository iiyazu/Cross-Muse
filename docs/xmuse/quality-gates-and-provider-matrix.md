# xmuse Quality Gates And Provider Matrix

Date: 2026-06-04

Scope: Path A Phase 3. This document defines the default CI gates for the
independent xmuse repository. It does not start Phase 4 schema migration, MCP
permission, cleanup hardening, TUI, or real-provider soak work.

## Default CI Order

The default workflow is `.github/workflows/xmuse-ci.yml` and runs:

```bash
uv sync --frozen --all-groups
uv run ruff check \
  src/xmuse_core/providers/models.py \
  src/xmuse_core/providers/registry.py \
  src/xmuse_core/platform/provider_read_contracts.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_quality_gates_phase3.py
uv run pytest -q \
  tests/xmuse/test_package_boundaries.py \
  tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_support_level.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_quality_gates_phase3.py \
  tests/xmuse/test_platform_runner.py::test_health_once_handles_missing_lane_projection \
  tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server
uv run mypy \
  src/xmuse_core/providers/models.py \
  src/xmuse_core/providers/registry.py \
  src/xmuse_core/platform/provider_read_contracts.py
```

The gates are intentionally ordered as ruff, focused pytest, scoped type check.
Default CI must not require `../memoryOS`, `/home/.../memoryOS`, real provider
secrets, real Ray/Codex credentials, or long-lived local services. Full-repo
ruff currently has historical unrelated violations, so the V10 default ruff gate
is scoped to the Phase 3 contract/type files above rather than doing unrelated
cleanup in this phase.

## Focused Test Groups

| Group | Default CI target | Purpose |
| --- | --- | --- |
| installability/package boundary | `tests/xmuse/test_package_boundaries.py`, `tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency` | Proves xmuse does not depend on sibling `../memoryOS` package metadata or direct `memoryos_lite` imports. |
| provider matrix/support level | `tests/xmuse/test_provider_models.py`, `tests/xmuse/test_provider_policy.py`, `tests/xmuse/test_provider_support_level.py`, `tests/xmuse/test_provider_read_contracts_module.py` | Proves registry support levels, policy selection, and read-only provider inventory stay aligned. |
| config/env docs consistency | `tests/xmuse/test_quality_gates_phase3.py` | Proves `.env.example`, `config-matrix.md`, and this matrix agree on CI secrets and production env bundle. |
| runtime health command smoke | `tests/xmuse/test_platform_runner.py::test_health_once_handles_missing_lane_projection` | Proves the health command path handles an empty independent checkout without requiring active lanes. |
| fake-provider groupchat smoke | `tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server` | Proves the local groupchat path can exercise MCP writeback and restart/resume with a fake app-server provider. |

Real Ray/Codex soak tests are not default CI. They remain operator-run gates for
runtime closure, for example:

```bash
uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume
```

## Scoped Type Check

The Phase 3 scoped type check is:

```bash
uv run mypy \
  src/xmuse_core/providers/models.py \
  src/xmuse_core/providers/registry.py \
  src/xmuse_core/platform/provider_read_contracts.py
```

This baseline covers the provider matrix model, default support-level registry,
and provider read inventory. Provider policy is enforced by focused pytest in
this phase. Documented exclusions for this phase are provider CLI adapters,
legacy platform runner, TUI, dashboard, MCP permission model, schema migration
path, and real Ray/Codex runtime tests. Those areas are intentionally outside
V10 and must not be silently treated as type-clean.

## Provider Support Matrix

The enforceable support levels are:

| Provider | Required V10 level | Enforcement |
| --- | --- | --- |
| Codex = PRIMARY for real groupchat | All default Codex profiles use `SupportLevel.PRIMARY`; Codex remains the only production groupchat GOD provider. | Registry tests and this contract test fail if Codex profiles drift. |
| OpenCode = SECONDARY bounded worker / bounded deliberation only | `opencode.deepseek_flash_worker` uses `SupportLevel.SECONDARY`, has only `bounded_code_writing` and `bounded_deliberation`, no MCP, no persistent session, and requires `DEEPSEEK_API_KEY` only for OpenCode smoke. Bounded deliberation may only emit `propose` / `ask` / `challenge` and has no state-write authority. | Provider model/policy tests fail if OpenCode gains broader default capabilities. |
| Claude Code = launcher only / not provider adapter | `agents/launchers/claude_code.py` is not registered as a provider profile or adapter. | Phase 3 contract tests fail if a `claude` provider profile appears without updating this matrix. |
| Fake = TEST ONLY and excluded from default registry | Fake adapters are test fixtures and no default registry profile may use `SupportLevel.TEST_ONLY`. | Support-level tests fail if fake/test profiles become selectable defaults. |

`docs/xmuse/provider-matrix.md` remains the detailed provider inventory. This
file is the CI-facing contract that binds the documented support level to code.

## Config And Secrets Gate

Default CI requires no provider secrets. `DEEPSEEK_API_KEY only required for OpenCode smoke`;
it is not required for installability, package-boundary,
provider registry tests, health command smoke, fake-provider groupchat smoke, or
the scoped type check.

Production groupchat env bundle:

```bash
XMUSE_PEER_GOD_BACKEND=ray
XMUSE_EXECUTE_GOD_BACKEND=ray
XMUSE_REVIEW_GOD_BACKEND=ray
XMUSE_RAY_GOD_TRANSPORT=app-server
XMUSE_RAY_GOD_EFFORT=low
XMUSE_RAY_GOD_MCP=1
XMUSE_DEPLOYMENT_PROFILE=production
XMUSE_CHAT_API_URL=http://127.0.0.1:8201
XMUSE_CHAT_API_AUTH_TOKEN=<server-token>
XMUSE_CHAT_API_KEY=<same-token-for-tui-client>
XMUSE_MCP_AUTH_TOKEN=<server-token>
```

`.env.example` must document these names and must not label
`DEEPSEEK_API_KEY` as required for all runtime use.

## Hard Gate Status

- CI workflow exists and installs from this repository with `uv sync --frozen --all-groups`.
- Default CI does not reference sibling `../memoryOS`.
- Default CI does not require provider secrets.
- Default CI excludes slow real Ray/Codex soak tests.
- Provider/config matrix drift is covered by `tests/xmuse/test_quality_gates_phase3.py`.
