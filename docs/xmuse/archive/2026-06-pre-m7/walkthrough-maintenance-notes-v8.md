# V8 Independent Installability Closure

Date: 2026-06-04

Scope: Phase 1 from `docs/xmuse/path-a-foundation-first-roadmap.md`.

## Goal

Make xmuse installable, buildable, importable, and smoke-runnable as an
independent project without editable path dependency `../memoryOS`.

## MemoryOS Reference Audit

| Classification | References | Phase 1 decision |
| --- | --- | --- |
| runtime-required before V8 | `pyproject.toml`, `uv.lock`, `src/xmuse_core/self_evolution/recovery.py` | Removed package dependency and inlined xmuse-owned recovery primitives. |
| removable legacy | `scripts/export_xmuse.py`, `docs/xmuse/xmuse-package.pyproject.toml`, export tests | Exported xmuse pyproject no longer writes local editable memoryOS source. |
| optional integration | `xmuse/master_loop.py`, `xmuse/platform_runner.py`, `src/xmuse_core/agents/memoryos_client.py`, platform memory refs, V6 sidecar adapter/lab | Kept. These are URL/protocol/fake-adapter seams and do not require sibling checkout by default. |
| test-only | package-boundary, split-export, export-tool, gate/profile tests and fixtures containing memoryOS names | Updated only tests directly asserting old install/export dependency behavior. Historical test data remains. |
| docs/history | `AGENTS.md`, V6/V7 notes, archives, prompts, historical runtime snapshots | Kept as history. Not package metadata or runtime import blockers. |

## Reproduction Before Fix

Observed blockers before implementation:

- `pyproject.toml` declared `memoryos-lite>=0.1.0`.
- `[tool.uv.sources]` mapped `memoryos-lite` to editable `../memoryOS`.
- `uv.lock` contained `source = { editable = "/home/iiyatu/projects/python/memoryOS" }`.
- `src/xmuse_core/self_evolution/recovery.py` imported `memoryos_lite.recovery`.
- Export tooling wrote a local editable `memoryos-lite` source into exported xmuse projects.

TDD red tests:

```bash
uv run pytest -q \
  tests/xmuse/test_package_boundaries.py::test_xmuse_core_memoryos_lite_imports_stay_behind_adapter \
  tests/xmuse/test_split_export_contract.py::test_xmuse_package_template_exports_xmuse_entrypoints_without_memoryos_dependency \
  tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency \
  tests/xmuse/test_export_tool.py::test_export_xmuse_project_does_not_add_local_memoryos_uv_source
```

Result: `4 failed` against the old dependency/import/export behavior.

## Implementation

Changed:

- Removed `memoryos-lite` dependency and `[tool.uv.sources]` local editable mapping from `pyproject.toml`.
- Removed `memoryos-lite` dependency from `docs/xmuse/xmuse-package.pyproject.toml`.
- Stopped `scripts/export_xmuse.py` from adding local editable memoryOS uv source.
- Recomputed `uv.lock`.
- Replaced `src/xmuse_core/self_evolution/recovery.py` re-export with xmuse-owned recovery primitives.
- Updated focused tests to enforce no `memoryos_lite` import and no local memoryOS package metadata.

Reference used:

- `/home/iiyatu/projects/python/memoryOS/src/memoryos_lite/recovery.py`

Borrowed only the tiny recovery primitive contract and behavior needed to keep existing xmuse recovery tests stable. Did not copy memoryOS runtime, store, API, recall, kernel, or unrelated implementation.

## Verification

```bash
uv run pytest -q \
  tests/xmuse/test_package_boundaries.py::test_xmuse_core_memoryos_lite_imports_stay_behind_adapter \
  tests/xmuse/test_split_export_contract.py::test_xmuse_package_template_exports_xmuse_entrypoints_without_memoryos_dependency \
  tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency \
  tests/xmuse/test_export_tool.py::test_export_xmuse_project_does_not_add_local_memoryos_uv_source \
  tests/xmuse/test_reliability_hardening.py::TestRuntimeRecovery
```

Result: `7 passed`.

```bash
uv build
```

Result: built `dist/xmuse-0.1.0.tar.gz` and `dist/xmuse-0.1.0-py3-none-any.whl`.

```bash
python3 -m venv /tmp/xmuse-v8-verify-clean.EKYSyP/venv
/tmp/xmuse-v8-verify-clean.EKYSyP/venv/bin/python -m pip install --upgrade pip
/tmp/xmuse-v8-verify-clean.EKYSyP/venv/bin/python -m pip install -e .
```

Result: clean editable install completed; installed `xmuse-0.1.0` with no `memoryos-lite`.

```bash
/tmp/xmuse-v8-verify-clean.EKYSyP/venv/bin/python - <<'PY'
import xmuse
import xmuse.chat_api
import xmuse_core
from xmuse_core.self_evolution.recovery import RecoveryConfig, RecoveryManager
print("import-smoke-ok", xmuse.__name__, xmuse_core.__name__, RecoveryManager(RecoveryConfig(max_attempts=1)).config.max_attempts)
PY
```

Result: `import-smoke-ok xmuse xmuse_core 1`.

Clean env Chat API + fake provider/groupchat smoke:

- Created conversation through `xmuse.chat_api.create_app()`.
- Posted human `@architect` message.
- Ran `PeerChatScheduler` with a fake provider layer.
- Fake provider used `PeerChatService.read_inbox()` and `post_god_message()` to simulate MCP writeback.

Result:

```text
chat-fake-provider-groupchat-smoke-ok conv_b0a6e2b569fa47c5bb6b93fd8a737728 1
```

Focused runtime regression:

```bash
uv run pytest -q \
  tests/xmuse/test_package_boundaries.py \
  tests/xmuse/test_split_export_contract.py \
  tests/xmuse/test_export_tool.py \
  tests/xmuse/test_reliability_hardening.py::TestRuntimeRecovery \
  tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_persistent_execute_god.py \
  tests/xmuse/test_runtime_ray_backend.py
```

Result: `80 passed, 1 warning`.

Ruff:

```bash
uv run ruff check scripts/export_xmuse.py src/xmuse_core/self_evolution/recovery.py \
  tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py \
  tests/xmuse/test_export_tool.py
```

Result: `All checks passed!`.

Whitespace:

```bash
git diff --check
```

Result: no output.

Dependency metadata:

- Wheel `METADATA` has no `Requires-Dist: memoryos-lite`.
- Sdist `PKG-INFO` has no `Requires-Dist: memoryos-lite`.
- `rg "memoryos-lite|memoryos_lite|../memoryOS|/home/iiyatu/projects/python/memoryOS" pyproject.toml uv.lock` returned no matches. This is a dependency/local-source check, not a claim that packaged historical docs contain no MemoryOS product references.

## Hard Gate Status

- `pyproject.toml` has no editable `../memoryOS` dependency: satisfied.
- `uv build` passes: satisfied.
- Clean env `pip install -e .` passes: satisfied.
- Clean env import smoke passes: satisfied.
- Clean env Chat API + fake provider/groupchat smoke passes: satisfied.
- No memoryOS repo files modified by this V8 implementation: satisfied by write scope; memoryOS was read only for recovery reference.
- Runtime behavior tests touched by the change still pass: satisfied.
- Ruff touched files passes: satisfied.
- `git diff --check` passes: satisfied.

## Remaining Risks

- The installed project description and historical docs still mention MemoryOS as product history. This is not a package dependency blocker.
- Optional live MemoryOS HTTP integration seams remain in code; they are intentionally not removed in Phase 1.
- `/home/iiyatu/projects/python/memoryOS` currently has unrelated dirty git state, but this V8 work did not write to that repository.
