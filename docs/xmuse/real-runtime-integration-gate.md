# Real Runtime Integration Gate

Updated: 2026-06-10

The `real-runtime-integration-gate` job is the Deep Research 03 bridge between
contract smoke and real runtime proof. It remains a no-secrets default PR gate,
but it names the live proof boundaries instead of implying that fake tests prove
external systems are production-ready.

## Default Job

`.github/workflows/xmuse-ci.yml` defines `real-runtime-integration-gate`.

Deep Research 03 expects GitHub branch protection to require:

- `quality-gates`
- `contract-smoke-gates`
- `real-runtime-integration-gate`

It runs:

```bash
uv sync --frozen --all-groups
uv run ruff check src/xmuse_core/integrations/memoryos_lite_interop.py tests/xmuse/test_github_server_gate_contract.py tests/xmuse/test_memoryos_lite_interop.py tests/xmuse/test_real_runtime_integration_gate.py
uv run pytest -q tests/xmuse/test_github_server_gate_contract.py tests/xmuse/test_memoryos_lite_interop.py tests/xmuse/test_real_runtime_integration_gate.py tests/xmuse/test_package_boundaries.py
uv run mypy src/xmuse_core/integrations/memoryos_lite_interop.py
```

## Gate Layers

| Layer | Evidence | Proof |
| --- | --- | --- |
| GitHub server settings | `github-server-side-gate.md`, workflow job names, CODEOWNERS, merge-readiness tests | Contract proof |
| MemoryOS Lite interop | `memoryos_lite_interop.py`, fake HTTP endpoint tests | Contract proof |
| Live MemoryOS Lite | operator-run service check with `XMUSE_LIVE_MEMORYOS_LITE=1` and `XMUSE_MEMORYOS_LITE_URL` | Runtime proof |
| Provider / CLI / Ray soak | documented opt-in soak layers, not default PR CI | Runtime proof |
| Broad-suite debt | `broad-suite-baseline-debt.md` | Contract proof of known gaps |

## MemoryOS Lite Interop

xmuse keeps its workflow-aware namespace model. MemoryOS Lite currently exposes
a session-centric REST API. The adapter maps:

```text
MemoryOSNamespace.uri
-> deterministic MemoryOS Lite session title
-> /sessions allocated session id
-> /sessions/{id}/ingest message metadata
-> /sessions/{id}/build-context ContextPackage
-> /memory/search hits
```

Message metadata carries:

- `xmuse_namespace_uri`
- `xmuse_namespace`
- `xmuse_actor_id`
- `xmuse_memory_layer`
- `xmuse_source_refs`
- `xmuse_request_metadata`

The fake contract proves payload shape and response mapping. A live opt-in run
proves service compatibility.

## Provider / CLI / Ray Soak Layers

Default PR CI only runs no-secrets checks. Runtime proof is split into explicit
operator gates:

| Layer | Trigger | Default CI |
| --- | --- | --- |
| fake contract | focused pytest | yes |
| local CLI contract | focused pytest that does not need credentials | yes |
| real provider credentials | operator workflow or local command | no |
| real Ray/Codex app-server writeback | operator workflow or local command | no |
| live MemoryOS Lite | `XMUSE_LIVE_MEMORYOS_LITE=1` plus `XMUSE_MEMORYOS_LITE_URL` | no |

This prevents a fake provider, dummy actor, or mocked memory service from being
reported as runtime proof.

## Known Non-Claims

- Contract proof is not runtime proof.
- The contract smoke gate is not a broad-suite green claim.
- The live MemoryOS Lite service is not required for default PR validation.
- Real provider / Ray / Codex writeback remains opt-in until a separate
  credentialed runtime gate is configured.
