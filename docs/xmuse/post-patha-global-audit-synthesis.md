# Post-PathA Global Audit Synthesis

Date: 2026-06-04

This synthesis combines three opencode-go DeepSeek V4 Flash Max read-only
audits with the completed Path A V8-V11 closures. It is the Codex-side
interpretation layer: the source audits are useful evidence, but their claims
must be treated as inputs, not authority.

## Inputs

| Source | Role |
|---|---|
| `docs/xmuse/post-patha-release-readiness-audit.md` | Release, resume, onboarding, demo, and presentation readiness. |
| `docs/xmuse/self-development-closure-audit.md` | Whether xmuse can use xmuse to drive a real feature from request to handoff. |
| `docs/xmuse/legacy-architecture-debt-audit.md` | Main-path vs legacy-path inventory, architecture debt, and cleanup candidates. |
| `docs/xmuse/archive/2026-06-pre-m7/walkthrough-maintenance-notes-v8.md` | Independent installability closure. |
| `docs/xmuse/production-operations.md` | Runtime operations and health/cleanup contract. |
| `docs/xmuse/quality-gates-and-provider-matrix.md` | V10 CI/provider/config support gates. |
| `docs/xmuse/schema-migration-strategy.md` | V11 durability contract. |
| `docs/xmuse/mcp-permission-model.md` | V11 MCP permission contract. |

## Current Position

xmuse is now a technically credible independent project foundation:

- V8 proved clean install/build/import and fake groupchat smoke without an
  editable `../memoryOS` dependency.
- V9 added a runtime operations contract, health checks, and cleanup visibility.
- V10 added scoped CI-quality gates, provider/config support matrices, and a
  bounded mypy baseline.
- V11 added durability, MCP permission, and cleanup contracts without broad
  runtime/auth/migration expansion.

The next gap is not core feasibility. It is presentation, self-development
closure, and legacy containment.

## Highest-Value Next Track

### Track 1: Release Candidate Packaging

This should be first after V11 because it turns the technical work into a
project that another person can understand and run.

Required outcomes:

- Root `README.md` with English project description, install, quickstart,
  architecture summary, and support-level caveats.
- `QUICKSTART.md` or README section that runs from clean env to a fake
  groupchat demo.
- One maintained fake-groupchat demo script or command path.
- One real Ray/Codex/MCP manual verification section.
- Architecture diagram and at least one TUI/groupchat screenshot.
- `pyproject.toml` description updated away from "built on MemoryOS".

Gate:

- Fresh clone reader can run a fake demo without reading V8 handoff notes.
- README explicitly separates production, experimental, manual, and legacy
  paths.

### Track 2: Self-Development Smoke

This should follow release packaging. Its purpose is to prove the platform's
central claim: xmuse can coordinate agents to improve xmuse.

Required outcomes:

- A small real feature candidate with low risk, e.g. README/demo doc update or
  a tiny contract-test-only change.
- Groupchat intake produces or references a blueprint/proposal.
- Feature graph / worker / reviewer / CI / handoff evidence is traceable.
- Human glue points are listed explicitly instead of hidden in the demo.

Important caution:

- The opencode self-development audit flags `initialize_from_graph_set()` and
  `gate_profiles.json` as blockers. These must be rechecked against the latest
  V10/V11 implementation before becoming action items.
- Do not make fake-provider success stand in for real self-development. Fake is
  acceptable only for a bounded demo mode.

### Track 3: Legacy Containment

This should not block release packaging, but it should prevent old code from
confusing users or CI.

Required outcomes:

- A documented main-path map: `xmuse/chat_api.py`, `xmuse/mcp_server.py`,
  `xmuse/platform_runner.py`, `xmuse/tui/`, and `src/xmuse_core/**`.
- A documented legacy quarantine list for `master_loop`, Hermes, sidecar, and
  historical scripts/tests.
- Default CI must not collect broken/historical tests by accident.
- Runtime data under `xmuse/` should be clearly separated from package source.

Gate:

- A new contributor can tell which files are main path, legacy, dormant lab, or
  runtime artifact without reading the entire handoff.

## Recommended Goal Order

1. **Post-PathA Release Candidate**
   - Build README, quickstart, demo script, screenshots/diagram placeholders,
     and presentation boundaries.
   - Keep scope documentation-first; do not alter runtime semantics.

2. **Self-Development Smoke**
   - Use xmuse to perform one tiny xmuse improvement.
   - Capture evidence from groupchat, graph/worker/reviewer, CI, and handoff.

3. **Legacy Containment**
   - Add a main-path/legacy-path guide and archive policy.
   - Optionally move only clearly disconnected docs/history artifacts. Avoid
     deleting code until tests and entrypoints are proven isolated.

4. **Developer Experience Hardening**
   - Only after the above: broader ruff cleanup, root-level contributing docs,
     optional type-check expansion, and public packaging polish.

## Things Not To Do Next

- Do not start a broad runtime refactor immediately after V11.
- Do not run a full legacy archive/delete pass before release docs exist.
- Do not add new TUI features before a basic demo path is documented.
- Do not convert opencode audit scores directly into roadmap priorities.
- Do not use fake-provider smoke as proof of real Ray/Codex operation.

## Follow-Up Prompt Seeds

### Release Candidate

```text
/goal Post-PathA release candidate packaging

Read:
- docs/xmuse/post-patha-global-audit-synthesis.md
- docs/xmuse/post-patha-release-readiness-audit.md
- docs/xmuse/production-operations.md
- docs/xmuse/quality-gates-and-provider-matrix.md

Goal:
Make xmuse understandable and runnable by a new developer without reading
handoff history.

Scope:
- Docs/demo packaging only.
- Do not change runtime semantics.
- Do not modify memoryOS.

Deliver:
- root README.md
- QUICKSTART.md or equivalent section
- fake groupchat demo command/script
- production vs experimental vs legacy boundary table
- updated pyproject description if still MemoryOS-branded
- verification commands/results
```

### Self-Development Smoke

```text
/goal xmuse self-development smoke

Read:
- docs/xmuse/post-patha-global-audit-synthesis.md
- docs/xmuse/self-development-closure-audit.md
- docs/xmuse/production-operations.md
- docs/xmuse/quality-gates-and-provider-matrix.md

Goal:
Run one tiny xmuse-on-xmuse development loop with traceable evidence.

Scope:
- One low-risk change only.
- Do not broaden runtime or CI.
- Do not count fake provider as real-provider proof.

Deliver:
- selected tiny task
- groupchat/blueprint/feature evidence
- worker/reviewer/CI/handoff evidence
- explicit list of human glue points
```

### Legacy Containment

```text
/goal Legacy containment guide

Read:
- docs/xmuse/post-patha-global-audit-synthesis.md
- docs/xmuse/legacy-architecture-debt-audit.md
- docs/xmuse/code-quality-and-archive-policy.md

Goal:
Make main-path vs legacy-path boundaries explicit without deleting runtime code.

Scope:
- Docs and tests classification only unless a narrow import/path bug is exposed.
- Do not archive/delete code in this goal.

Deliver:
- docs/xmuse/main-path-and-legacy-boundaries.md
- default/extended/manual/legacy test category table
- follow-up archive plan with gates
```
