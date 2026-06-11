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
- no review, takeover, merge, or GOD authority.

OpenCode stage evidence now proves the harness can execute bounded review work
with the corrected command format.

### GitHub Server-Side Truth

The GitHub truth scaffold now distinguishes local contract proof from
server-side merge proof.

`can_emit_pr_merged(...)` requires:

- server-side proof level;
- successful check-run identity for every required check;
- branch protection or applicable ruleset snapshot;
- review event identity and Code Owner review verification;
- merge commit SHA, `merged_at`, and merge event identity.

The manual capture script is explicit opt-in:

```bash
uv run python scripts/github_server_truth_capture.py \
  --repo iiyazu/Cross-Muse \
  --pull-request <number> \
  --output /tmp/xmuse-github-server-truth.json
```

Current live status:

- local GitHub CLI is not authenticated;
- GitHub connector search reports no PRs in `iiyazu/Cross-Muse`;
- therefore no live/server-side `pr_merged` proof has been captured.

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
  docs/xmuse/opencode-in-long-runtime-evidence-plan.md \
  docs/xmuse/provider-matrix.md \
  docs/xmuse/config-matrix.md \
  docs/xmuse/tui-slash-command-handoff.md \
  -g '!*.pyc'
```

Result: no matches.

## Remaining Manual Gap

This iteration cannot complete live/server-side merge proof without external
operator action:

- local `gh auth status` reports no authenticated GitHub hosts;
- GitHub connector search for `repo:iiyazu/Cross-Muse is:pr` returns no PRs;
- no real PR check-run, review, ruleset/branch-protection, or merge event exists
  for capture.

Owner: GitHub operator.

Next action:

1. Create or provide a real PR number in `iiyazu/Cross-Muse`.
2. Authenticate local GitHub CLI with `gh auth login`.
3. Run `scripts/github_server_truth_capture.py` against that PR.
4. Attach the resulting JSON as server-side evidence.

Until that happens, `pr_merged` remains `manual_gap`.
