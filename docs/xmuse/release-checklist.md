# xmuse Release Checklist

Updated: 2026-06-21

## Release Decision

Current decision: do not cut a full production release yet.

Current claim level:

```text
xmuse production-closure short path accepted
```

This means `main` has durable GOD groupchat plus a minimal
AcceptanceSpine/GoalRun closure path, and the short
`xmuse-platform-runner --goal --acceptance-gate --github-live-capture` path can
end as `accepted` only through producer-owned live GitHub server-side evidence.

It does not mean full release-ready.

## Claimable Now

- Durable GOD groupchat remains the control plane for human intake, peer/GOD
  deliberation, scheduler dispatch, and evidence writeback.
- Minimal AcceptanceSpine/GoalRun records durable intake, proposal, dispatch,
  review, final action, GitHub gate evidence, and terminal
  `accepted` / `blocked` / `failed` status.
- `xmuse-platform-runner --goal --acceptance-gate` produces a blocked terminal
  result when GitHub server-side truth is missing.
- `xmuse-platform-runner --goal --acceptance-gate --github-live-capture` can
  produce an accepted terminal result when the producer captures a complete
  `server_side_merge_proof` for the same final action.
- GitHub required checks are known through authenticated read-only server
  evidence. PR review enforcement is absent on `main`, so xmuse uses verified
  internal review truth instead of pretending GitHub requires reviews.

## Forbidden Claims

Do not claim:

- full production release ready;
- multi-hour real-provider/Ray/Codex soak complete;
- long-running GOD groupchat stability across real provider sessions;
- GitHub PR/CodeOwner review enforcement is enabled on `main`;
- fake demos, stdout, dashboard, TUI, or copied GitHub text are acceptance
  truth;
- `uv run mypy xmuse/platform_runner.py` is clean;
- a formal versioned release has been cut.

## Durable Evidence

- RC baseline:
  `docs/xmuse/rc-closure-baseline-2026-06-21.md`
- GitHub server-side required-check evidence:
  `docs/xmuse/github-server-side-gate-live-evidence-2026-06-21.md`
- P2 blocked path evidence:
  `docs/xmuse/acceptance-gated-runner-evidence-2026-06-21.md`
- P3 accepted live path evidence:
  `docs/xmuse/acceptance-gated-live-capture-evidence-2026-06-21.md`
- Real provider bounded soak evidence:
  `docs/xmuse/real-provider-soak-evidence-2026-06-21.md`
- P3 runtime root:
  `.goal-runs/2026-06-21/stage3-live-pr155-accepted`
- P3 spine:
  `chat.db#acceptance_spine=goalrun_3db27db05d3a40af821632e075e880e6`
- P3 final action:
  `final_actions.json#hold=final-80798c437229`
- P3 GitHub gate evidence:
  `github_gate_evidence.json#evidence=ghgate_de02b6e176e449b687be296eb7a230ec`
- P3 bound PR/head/merge:
  PR `155`, reviewed head `1798e0a31cd1a80163a5e70287e8b0d1684e0aee`,
  merge commit `4fd40a735e62be255e787ce93bdc3d5653d0255e`
- Real provider bounded soak terminal:
  `blocked/github_gate_unverified`,
  `chat.db#acceptance_spine=goalrun_42cf37320c0443a3a2d0b7ef46fa5c2b`,
  `final_actions.json#hold=final-877f3007706e`,
  `github_gate_evidence.json#evidence=ghgate_5f6231d8efc440d8b92e3942608c8bd8`
- P1 real provider writeback evidence:
  `.goal-runs/2026-06-21/p1-one-turn-writeback-pytest-5/test_real_ray_codex_app_server0`,
  provider session `019eea2c-27f9-7152-b8aa-66d844353650`,
  traces
  `peer_latency_inbox_36409f270c3f454aac7a80dca289a924` and
  `peer_latency_inbox_d3c8700e124a470080171db7458079a7`

## Required Checks And Gate State

- Branch protection for `main` requires the repository's configured checks.
- Live GitHub evidence confirms required checks can be read from server-side
  APIs, not only from copied UI text.
- `required_pull_request_reviews = null`; GitHub is not the source of review
  enforcement for this repository state.
- Acceptance requires producer-owned `server_side_merge_proof`. Any missing,
  arbitrary, stale, mismatched, or unverifiable GitHub ref must leave the spine
  `blocked/github_gate_unverified`.

## Full Release Blockers

- No multi-hour real-provider/Ray/Codex soak has been accepted. The 2026-06-21
  bounded real-provider soak originally blocked before the first durable MCP
  `chat_post_message` reply. P1 later proved a focused real Ray/Codex
  restart/resume path can produce durable MCP `chat_post_message` replies and
  `mcp_writeback` traces, but the provider path has not yet been connected
  through proposal/review/dispatch, final-action, GitHub gate, or multi-turn
  soak acceptance.
- Release packaging/versioning has not been cut from the current claim level.
- `uv run mypy xmuse/platform_runner.py` has existing type debt and is not a
  clean release gate.
- Chat API and MCP still need production auth/RBAC before external deployment.
- Dashboard and TUI are inspection surfaces only; they are not acceptance
  authority or release evidence.
