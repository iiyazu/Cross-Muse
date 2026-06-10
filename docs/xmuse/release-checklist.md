# xmuse Release Checklist

Date: 2026-06-04

Scope: Post-PathA release candidate packaging. This checklist documents the gates and
boundaries for making xmuse understandable, installable, and demo-runnable by a new
developer. It does not add runtime semantics, broaden CI, or archive legacy code.

## Default CI Gates

Default CI runs the scoped V10 gates:

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

Release packaging adds a local contract check:

```bash
uv run pytest -q tests/xmuse/test_release_candidate_packaging.py
uv run python scripts/demo_fake_groupchat.py
```

## Manual Real Runtime Gate

The real Ray/Codex/MCP gate is manual and must not be replaced by fake demo success:

```bash
export XMUSE_PEER_GOD_BACKEND=ray
export XMUSE_EXECUTE_GOD_BACKEND=ray
export XMUSE_REVIEW_GOD_BACKEND=ray
export XMUSE_RAY_GOD_TRANSPORT=app-server
export XMUSE_RAY_GOD_EFFORT=low
export XMUSE_RAY_GOD_MCP=1
export XMUSE_CHAT_API_URL=http://127.0.0.1:8201

uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume
```

## Provider Support Levels

| Provider | Level | Release stance |
| --- | --- | --- |
| Codex = PRIMARY | Production groupchat GOD provider | Required for real Ray/Codex/MCP writeback proof. |
| OpenCode = SECONDARY | Bounded worker only | Requires `DEEPSEEK_API_KEY`; no persistent GOD session or MCP writeback. |
| Claude Code = launcher only | Not a provider adapter | Not selectable through provider policy. |
| Fake = TEST ONLY | Demo and CI smoke only | Useful for onboarding; not production evidence. |

## Known Limitations

- Chat API and MCP have no auth layer.
- Real Ray/Codex/MCP readiness is manual and environment-dependent.
- Fake groupchat demo proves local scheduler/store semantics only.
- Full-repo ruff and broad mypy remain outside default CI due historical unrelated debt.
- TUI and dashboard are inspection surfaces, not production gate evidence.
- Legacy master loop, Hermes, and historical shell scripts remain present but are not current
  groupchat mainline.
- Schema migrations, MCP RBAC, cleanup daemon/process killing, and legacy archive/delete work
  are not part of this release packaging goal.
