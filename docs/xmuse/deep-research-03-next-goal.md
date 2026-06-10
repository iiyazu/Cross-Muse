# Deep Research 03 Next Goal

Updated: 2026-06-10

Goal: move xmuse from contract-level verification to auditable runtime
integration evidence without weakening the contracts closed by #13-#19.

The #19 `contract-smoke-gates` job proves that the mainline contracts are hard
to bypass in a no-secrets PR path. Deep Research 03 adds the next ring: server
gate configuration, MemoryOS Lite interop contracts, provider/runtime soak
layering, and an explicit broad-suite debt registry.

Anchor terms:

- GitHub server-side gate
- MemoryOS Lite interop
- Provider / CLI / Ray soak layering
- Broad-suite baseline debt registry
- contract proof
- runtime proof

## Scope

### 1. GitHub Server-Side Gate

Deliver a local contract for the GitHub settings that cannot be fully enforced
from repository files alone:

- required checks: `quality-gates`, `contract-smoke-gates`,
  `real-runtime-integration-gate`;
- CODEOWNER review for `.github/`, `docs/xmuse/`, chat, structuring, platform,
  integrations, and providers;
- required PR fields, especially `review_evidence_bundle`;
- branch protection guidance for required checks, up-to-date branches,
  conversation resolution, and no bypass.

This is a contract proof in code and docs. The runtime proof is an actual GitHub
branch protection setting on `main` plus passing check runs on a PR.

### 2. MemoryOS Lite Interop

Bridge xmuse workflow-aware namespaces to the current MemoryOS Lite
session-centric API:

```text
xmuse task namespace
-> deterministic session title
-> POST /sessions
-> POST /sessions/{id}/ingest
-> POST /sessions/{id}/build-context
-> POST /memory/search
```

The adapter must not import `memoryos_lite`; xmuse remains REST-first. Actor
identity, memory layer, namespace URI, namespace payload, and source refs travel
in MemoryOS Lite message metadata.

Default tests use fake HTTP transport and are contract proof. Live service
checks are runtime proof and require explicit operator opt-in with
`XMUSE_LIVE_MEMORYOS_LITE=1` and `XMUSE_MEMORYOS_LITE_URL`.

### 3. Provider / CLI / Ray Soak Layering

Keep default CI no-secrets while naming the proof levels:

| Layer | Default CI | Proof Type |
| --- | --- | --- |
| fake provider contract | yes | contract proof |
| local CLI shape checks | yes, only when no secrets/services are required | contract proof |
| real provider credentials | no | runtime proof |
| real Ray/Codex app-server writeback | no | runtime proof |
| live MemoryOS Lite service | no | runtime proof |

External dependency tests must be opt-in, documented, and separate from the PR
gate that contributors can run without credentials.

### 4. Broad-Suite Baseline Debt Registry

Known broad-suite gaps must be registered with:

- stable debt ID;
- owner file;
- reproduction command;
- current failure summary;
- priority;
- closure rule.

The contract smoke gate is not a broad-suite green claim. A focused green gate
can only prove its named contract.

## Deliverables

- `docs/xmuse/github-server-side-gate.md`
- `docs/xmuse/real-runtime-integration-gate.md`
- `docs/xmuse/broad-suite-baseline-debt.md`
- `src/xmuse_core/integrations/memoryos_lite_interop.py`
- focused tests for GitHub gate consistency, MemoryOS Lite interop, live opt-in,
  and broad-suite debt registration
- `.github/workflows/xmuse-ci.yml` job `real-runtime-integration-gate`

## Acceptance

- `uv run ruff check .`
- focused pytest for the new gate and unchanged package boundaries
- no `xmuse/__init__.py`
- no runtime state committed
- no `memoryos_lite` import from `xmuse_core`
- default CI has no secrets and no live external service requirement
