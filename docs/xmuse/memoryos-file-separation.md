# xmuse / MemoryOS File Separation

This document records the current file-level separation boundary and the next
migration steps. The goal is to let xmuse evolve as an autonomous development
platform while MemoryOS remains a standalone memory middleware package.

## Current Boundary

MemoryOS owns:

- `src/memoryos_lite/**`
- MemoryOS tests that do not start with `test_xmuse_`
- MemoryOS docs outside `docs/xmuse/**`
- `memoryos` and `memoryos-lite` CLI entry points

xmuse owns:

- `src/xmuse_core/**`
- `xmuse/**`
- `docs/xmuse/**`
- `tests/xmuse/**`
- `tests/fixtures/xmuse/**`
- future `xmuse-*` CLI entry points in dedicated xmuse package metadata

xmuse-owned after V8:

- `xmuse_core.self_evolution.recovery`

`xmuse_core.self_evolution.recovery` contains xmuse-owned retry/circuit-breaker
primitives. It no longer imports `memoryos_lite.recovery` and is part of xmuse's
independent installability boundary.

## Rules

1. `src/memoryos_lite/**` must not import `xmuse_core` or `xmuse`.
2. xmuse must not require `memoryos-lite` or local `../memoryOS` for default
   install/build/import/smoke flows.
3. xmuse may keep optional MemoryOS integrations behind explicit URL/protocol
   adapters, but those seams must not become default package dependencies.
4. Runtime state must stay under `XMUSE_ROOT` or the documented xmuse runtime root.
5. New xmuse-only dependencies belong in xmuse package metadata.
6. New MemoryOS dependencies must be optional and justified by explicit adapter use.

## Completed First Step

- V8 moved recovery primitive ownership back into
  `src/xmuse_core/self_evolution/recovery.py` so xmuse no longer imports
  `memoryos_lite.recovery`.
- Added boundary tests under `tests/memoryos/` and `tests/xmuse/`.
- Moved xmuse-only dependencies `ray` and `textual` into the `xmuse` optional
  dependency group.
- Removed broken `xmuse-*` console scripts from the MemoryOS package metadata.
  The `memoryos-lite` wheel does not package `xmuse/**` or `xmuse_core/**`, so
  exporting xmuse entry points from the MemoryOS package would create installed
  commands that cannot import their targets.
- Added `XMUSE_ROOT` support for chat API, dashboard API, MCP server, TUI, and
  platform runner entry points.
- Added `XMUSE_ROOT` support for legacy master loop defaults, auto discovery
  deduplication, runner supervisor runtime files, self-evolution checkpoint
  output, self-evolution runner root, and xmuse skill context defaults.
- Moved all root-level `tests/test_xmuse_*.py` files into `tests/xmuse/`.
  Current split: root-level `tests/test_xmuse_*.py` count is 0, and
  `tests/xmuse/` contains 167 xmuse test files.
- Fixed the Textual navigation migration blocker by isolating the fixture under
  a temporary xmuse runtime root and mocking adapter/network refresh paths.
- Added a split export contract:
  - `docs/xmuse/split-export-manifest.json`
  - `docs/xmuse/xmuse-package.pyproject.toml`
  - `scripts/export_xmuse.py`
  The template builds a standalone xmuse wheel from `xmuse/**` and
  `src/xmuse_core/**`, does not depend on `memoryos-lite`, and excludes runtime
  state from the wheel. The combined repository intentionally keeps `xmuse/` as
  a namespace-style application directory without `xmuse/__init__.py`.

## Next Migration Steps

1. Split tests by directory:
   - `tests/memoryos/**`
   - `tests/xmuse/**`
   This step is complete for root-level xmuse tests. Keep future xmuse tests
   under `tests/xmuse/`; do not recreate root-level `tests/test_xmuse_*.py`
   compatibility files.

2. Split docs:
   - Keep MemoryOS docs in `docs/**`.
   - Move active xmuse docs to `docs/xmuse/**`.
   - Move old xmuse design drafts under `docs/xmuse/archive/**`.

3. Continue runtime-root cleanup:
   - `XMUSE_ROOT` is now the canonical entry-point runtime root.
   - Keep default `XMUSE_ROOT=./xmuse` while the repository is still combined.
   - Active Python entry points now mostly use `default_xmuse_root`; remaining
     matches are mainly docstrings, shell scripts, historical/legacy paths, or
     tests. Audit each before changing it.

4. Split package metadata:
   - Root `pyproject.toml` now exports only MemoryOS scripts.
   - `docs/xmuse/xmuse-package.pyproject.toml` is the current standalone xmuse
     package metadata template for a future exported repository root.
   - `docs/xmuse/split-export-manifest.json` records the roots to copy and the
     runtime-state patterns to exclude.

5. External repository cutover:
   - Create a sibling `xmuse` repository.
   - Move `xmuse/**`, `src/xmuse_core/**`, `docs/xmuse/**`,
     `tests/xmuse/**`, and `tests/fixtures/xmuse/**`.
   - Depend on MemoryOS as a package instead of sharing the same source tree.

## Verification

Run:

```bash
uv run pytest tests/memoryos/test_xmuse_boundaries.py tests/xmuse/test_package_boundaries.py -q
uv run pytest tests/memoryos/test_xmuse_boundaries.py tests/xmuse -q
uv run pytest tests/test_engine.py tests/xmuse/test_reliability_hardening.py -q
```

Latest full split verification:

```text
uv run pytest tests/memoryos/test_xmuse_boundaries.py tests/xmuse -q
-> 2194 passed, 9 warnings in 177.85s
```

Latest V8 export smoke:

```text
uv run python scripts/export_xmuse.py /tmp/xmuse-export-tool-check --repo-root /home/iiyatu/projects/python/xmuse
-> excluded_count recorded by export result
uv build --wheel --out-dir /tmp/xmuse-export-tool-check/dist /tmp/xmuse-export-tool-check
-> built xmuse-0.1.0-py3-none-any.whl
-> xmuse/chat_api.py packaged; xmuse_core/__init__.py packaged
-> runtime_state_files: 0
-> wheel METADATA has no Requires-Dist: memoryos-lite
```

Current independent repo:

```text
/home/iiyatu/projects/python/xmuse
-> source repo is already xmuse
-> no editable ../memoryOS dependency in pyproject.toml or uv.lock
```
