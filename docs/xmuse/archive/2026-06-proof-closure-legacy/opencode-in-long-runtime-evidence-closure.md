# OpenCode-In Long Runtime Evidence Closure

Updated: 2026-06-11

This report records the current OpenCode-in evidence-closure iteration for
xmuse. It is an audit artifact, not a product-surface expansion.

## Objective Boundary

The iteration moved xmuse from contract/fake-only assertions toward stronger
runtime evidence while preserving these boundaries:

- Codex remains outer controller, reviewer, and final judge.
- OpenCode-in is a bounded secondary executor and reviewer.
- Contract/fake/local evidence cannot claim live provider, live MemoryOS,
  natural live deliberation, or server-side GitHub proof.
- `pr_merged` remains gated on server-side GitHub merge truth.
- Default CI remains no-secrets and no-live-service.

## OpenCode Command Correction

The current `opencode 1.15.13` CLI expects the model and variant as separate
arguments:

```bash
opencode run \
  --model opencode-go/deepseek-v4-flash \
  --variant max \
  --format json \
  --dir /home/iiyatu/projects/python/xmuse \
  "..."
```

The previous `opencode-go/deepseek-v4-flash:max` model id was corrected. The
`max` value is now treated only as the OpenCode CLI variant.

## Stage Harness Evidence

All current stages were executed through `scripts/goal_stage_runner.py`; none of
the listed evidence is a dry run.

| Stage | Status | Command |
|---|---:|---|
| `DiagOpenCode` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S0` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S4` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S5` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S5b` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S5c` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S5d` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S5e` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |
| `S6` | `ok` | `opencode run --model opencode-go/deepseek-v4-flash --variant max ...` |

Runtime artifacts live under ignored `.goal-runs/` paths and must not be
committed.

## Completed Closure Work

### Merge Readiness vs Merge Fact

Local readiness is represented as merge readiness, not a merge fact. Fake,
contract, and local paths cannot emit `pr_merged`.

Current proof status:

- local readiness: `contract_proof`;
- fake runtime execution evidence: `fake_runtime_proof`;
- true merge fact: `manual_gap` until server-side GitHub evidence is captured.

### MemoryOS Lite Trace Evidence

`MemoryOSLiteTraceEvidence` and `fetch_trace(...)` exist in
`src/xmuse_core/integrations/memoryos_lite_interop.py`.

Current proof status:

- fake/default trace conversion: local/fake proof only;
- live MemoryOS Lite trace: opt-in live-service proof only, not default CI.

### Deterministic Replay vs Natural Deliberation

Deterministic replay remains `contract_proof`. The replay summary rejects
live/real proof-level pollution and does not claim natural live deliberation.

Current proof status:

- deterministic speech-act replay: `contract_proof`;
- natural live multi-GOD deliberation: `manual_gap` unless a live transcript is
  captured separately.

### OpenCode-In Bounded Deliberation

OpenCode remains a secondary low-risk participant:

- allowed bounded speech acts: `propose`, `ask`, `challenge`;
- no durable state writes;
- no MCP;
- no persistent sessions;
- no final merge or GOD authority.

OpenCode stage evidence now proves the harness can execute bounded review work
with the corrected command format. This bounded evidence can support xmuse
internal review truth only when outer Codex validates it and GitHub server-side
settings do not require a GitHub PR review.

### GitHub Server-Side Truth

The GitHub truth scaffold now distinguishes local contract proof from
server-side merge proof.

`can_emit_pr_merged(...)` requires:

- server-side proof level;
- successful check-run identity for every required check;
- branch protection or applicable ruleset snapshot;
- review truth:
  - GitHub review event identity and Code Owner review verification when GitHub
    requires PR review; or
  - verified xmuse internal review artifact, reviewer identity, and reviewed head
    SHA when GitHub does not require PR review;
- merge commit SHA, `merged_at`, and merge event identity.

The manual capture script is explicit opt-in:

```bash
uv run python scripts/github_server_truth_capture.py \
  --repo iiyazu/Cross-Muse \
  --pull-request <number> \
  --internal-review-artifact <path> \
  --internal-reviewer <xmuse-reviewer-id> \
  --internal-reviewed-head-sha <sha> \
  --output /tmp/xmuse-github-server-truth.json
```

Current live status:

- local GitHub CLI is authenticated;
- PR `#42` exists in `iiyazu/Cross-Muse`;
- GitHub checks and branch protection are captured server-side;
- the review truth model now follows the Clowder-style split:
  `github_review_truth` is required only when GitHub requires PR review, while
  `xmuse_internal_review_truth` can carry independent GOD/reviewer evidence in
  single-maintainer mode.

### Long-Run Heartbeat Replay

The replay summary records heartbeat and review snapshot SLO fields from
simulated timestamps without sleeping.

Current proof status:

- deterministic SLO audit: `contract_proof` / `fake_runtime_proof`;
- live long-running provider heartbeat: not claimed.

## Validation

Fresh validation for the current closure state:

```bash
uv run pytest \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_goal_stage_runner.py \
  tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_runtime_settings.py \
  tests/xmuse/test_mcp_server.py \
  tests/xmuse/test_bounded_deliberation_artifacts.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_github_server_truth_capture.py \
  tests/xmuse/test_github_server_gate_contract.py \
  tests/xmuse/test_self_iteration_runtime_closure.py \
  tests/xmuse/test_package_boundaries.py \
  -q
```

Result: `132 passed, 1 warning`.

```bash
uv run ruff check .
```

Result: `All checks passed!`.

```bash
uv run mypy \
  scripts/goal_stage_runner.py \
  scripts/github_server_truth_capture.py \
  src/xmuse_core/providers/adapters/opencode.py \
  src/xmuse_core/providers/registry.py \
  src/xmuse_core/runtime/settings.py \
  src/xmuse_core/platform/execution/github_ops.py \
  src/xmuse_core/self_iteration/runtime_closure.py
```

Result: `Success: no issues found in 7 source files`.

Current canonical command scan:

```bash
rg -n "deepseek-v4-flash:max|opencode-go/deepseek-v4-flash:max|deepseek-v4-flash-max|opencode-go/deepseek-v4-flash-max" \
  src/xmuse_core tests/xmuse scripts .env.example \
  docs/xmuse/goal-stage-harness.md \
  docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-plan.md \
  docs/xmuse/provider-matrix.md \
  docs/xmuse/config-matrix.md \
  docs/xmuse/tui-slash-command-handoff.md \
  -g '!*.pyc'
```

Result: no matches.

## Clowder-Style Review Boundary

Clowder AI keeps GitHub ownership human-maintainer based while enforcing agent
independence inside the platform. xmuse follows the same boundary for this
iteration:

- GitHub branch protection proves checks and merge facts.
- xmuse review artifacts prove author/reviewer separation inside the platform.
- If a repository later enables GitHub PR review or Code Owner review, GitHub
  review truth becomes mandatory and internal review cannot replace it.

PR `#42` has a read-only capture path:

```bash
uv run python scripts/github_server_truth_capture.py \
  --repo iiyazu/Cross-Muse \
  --pull-request 42 \
  --internal-review-artifact docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-closure.md \
  --internal-reviewer opencode-in-review \
  --internal-reviewed-head-sha <PR_HEAD_SHA> \
  --output /tmp/xmuse-github-server-truth.json
```

Captured server-side facts after configuring `main` branch protection:

- required checks are present and successful:
  - `quality-gates`;
  - `contract-smoke-gates`;
  - `real-runtime-integration-gate`.
- source app: `github-actions`;
- branch protection is enabled for `main`;
- branch protection requires the three checks above with `strict: true`;
- branch protection enforces admins;
- branch protection requires conversation resolution;
- PR `#42` is the current OpenCode-in evidence closure PR.

Internal review facts:

- S7 final closure review ran through OpenCode-in with command
  `opencode run --model opencode-go/deepseek-v4-flash --variant max`;
- S7 returned `status: ok` and `review_decision: pass`;
- outer Codex separately reviewed and accepted the proof-boundary correction.

Remaining action:

1. Relax GitHub `main` branch protection to require checks but not GitHub PR
   review.
2. Merge PR `#42` without admin bypass after checks remain green.
3. Re-run `scripts/github_server_truth_capture.py` with internal review
   arguments and attach the resulting JSON.
