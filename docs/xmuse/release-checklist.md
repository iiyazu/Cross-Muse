# xmuse Release Checklist

Updated: 2026-06-27

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

## Evidence Update Since 2026-06-21

New evidence:

- PR #242 (`codex/a2a-natural-real-chain`) was merged into `main` at
  `c1d19ad2ae9bd8b22742376c98968073a508329c`.
- PR #242 made native GOD sessions the default peer-chat path and kept Ray as
  optional legacy infrastructure.
- The native/A2A service-chain evidence reached the no-Ray path:
  `ChatAPI -> A2A planner -> native persistent architect -> durable proposal
  -> A2A review verdict -> dispatch bridge -> A2A execute ack`.
- Main CI run `28292323481` was observed successful on merge commit
  `c1d19ad...`.

Claim change: none.

The new evidence supports the next natural-groupchat A2A goal calibration. It
does not upgrade release status and does not prove production-ready natural
groupchat, full closure, GitHub review truth, fully autonomous merge, or live
MemoryOS authority.

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
- production-ready natural groupchat;
- fully autonomous merge;
- live MemoryOS authority;
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
  `docs/xmuse/archive/2026-06-pre-m7/real-provider-soak-evidence-2026-06-21.md`
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
- P2 real provider proposal/review/dispatch evidence:
  `.goal-runs/2026-06-21/p2-real-provider-proposal-dispatch-pytest/test_real_ray_codex_app_server0`,
  provider session `019eea3d-fed6-7e32-9f2f-5cb39afa860d`,
  proposal `prop_038ab28b77f94083959d22f37d527a9c`,
  review trigger `inbox_27e4675cda2b4aeaa1f6e55a79d370f0`,
  resolution `res_3d19e6d8154b44769aef4d187f74f323`, and dispatch
  `dispatch:conv_bc4fa83561b042a489e80078e05882d5:res_3d19e6d8154b44769aef4d187f74f323:execute`
- P3 real provider execute dispatch completion evidence:
  `.goal-runs/2026-06-21/p3-real-dispatch-completion-pytest-4/test_real_ray_codex_app_server0`,
  architect provider session `019eea58-fd9b-76a2-b1d7-b3e1960dc629`,
  execute provider session `019eea5b-d4dc-7023-8d24-fa316d3bf99e`,
  proposal `prop_85f07b4d5c3044cfa543d6f700e5626e`,
  resolution `res_12b67786d4674539b5779551bc7c5671`,
  dispatch inbox `inbox_8bc4a91282094c6393575d3a7e6ad756`, and dispatch
  `dispatch:conv_5a3cc569a316410d804a91972c1adffc:res_12b67786d4674539b5779551bc7c5671:execute`
- P4 final-action blocked-path attempt:
  `.goal-runs/2026-06-21/p4-final-action-gate-blocked-pytest/test_real_ray_codex_app_server0`
  and
  `.goal-runs/2026-06-21/p4-final-action-gate-blocked-pytest-rerun/test_real_ray_codex_app_server0`;
  both attempts failed before the first real provider MCP proposal writeback
  with `provider_turn_cancelled_before_mcp_writeback`. This is negative
  evidence only and does not raise the claim level.
- P4 proposal-writeback stability attempt:
  `.goal-runs/2026-06-21/p4-real-final-gate-stability-pytest/test_real_ray_codex_app_server0`
  and
  `.goal-runs/2026-06-21/p4-real-final-gate-stability-pytest-2/test_real_ray_codex_app_server0`;
  prompt priority now states that explicit `chat_emit_proposal` requests use
  `chat_emit_proposal` instead of ordinary `chat_post_message`, but the real
  app-server path still produced no proposal, MCP tool trace, or stream delta.
- P4 app-server first-event diagnostics:
  app-server partial latency stages are now copied into timeout/cancellation
  traces before session abort, so the next real proposal probe can distinguish
  no app-server event, MCP-ready/no-tool, streamed-text/no-tool, and
  proposal-tool-call cases. This is diagnostic only and does not raise the
  claim level.
- P4 first-proposal probe:
  `.goal-runs/2026-06-21/p4-first-proposal-probe-pytest/test_real_ray_codex_app_server0`
  persisted proposal `prop_c776c4dfe72c4cdc9f0db7893856f0f4` through a real
  Ray/Codex app-server `chat_emit_proposal` turn. Full P4 still failed before
  proposal persistence; its trace now classifies the blocker as
  `mcp_tools_ready` / no MCP tool call.
- P4 tool-choice stability and final-action gate:
  `.goal-runs/2026-06-21/p4-tool-choice-stability-pytest-2/test_real_ray_codex_app_server0`
  passed one complete real Ray/Codex app-server path through durable proposal
  writeback, manual review approval, dispatch MCP writeback, AcceptanceSpine
  linkage, and final-action hold. The resulting spine remained
  `blocked/github_gate_unverified` with gap ref
  `github_gate_evidence.json#evidence=ghgate_5c7a8d77c6034459a590340ca26aa4a3`,
  which is the expected result without producer-owned server-side merge proof.
  A later rerun at
  `.goal-runs/2026-06-21/p4-tool-choice-stability-pytest-3/test_real_ray_codex_app_server0`
  failed at execute dispatch acknowledgement: MCP readiness and streamed text
  were observed, but no `chat_post_message` tool trace was written, and the
  queue failed with `peer_no_inbox_side_effect`. After dispatch prompt
  hardening, `.goal-runs/2026-06-21/p4-dispatch-ack-hardening-pytest/test_real_ray_codex_app_server0`
  passed again with proposal `prop_75e60b2708144d2e90f864370db59d4a`,
  dispatch evidence `mcp_writeback:inbox_a5708a27b033414eb3ea845157a7d09c`,
  and final-action gap ref
  `github_gate_evidence.json#evidence=ghgate_3c25c4bee63144b29ea4654d537e4684`.

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
  `mcp_writeback` traces. P2 then proved real provider `chat_emit_proposal`
  can reach durable proposal, review-trigger handling, approval, and queued
  dispatch. P3 then proved the queued dispatch intent can be completed by a
  real execute Codex app-server peer with durable MCP `chat_post_message`
  acknowledgement and `dispatched` queue evidence. P4 has repeated complete
  real-provider evidence to final-action hold with the correct
  `blocked/github_gate_unverified` terminal state after dispatch prompt
  hardening. The real provider path has not yet proven accepted GitHub gate
  truth, server-side merge truth, or multi-turn soak acceptance.
- Release packaging/versioning has not been cut from the current claim level.
- `uv run mypy xmuse/platform_runner.py` has existing type debt and is not a
  clean release gate.
- Chat API and MCP still need production auth/RBAC before external deployment.
- Dashboard and TUI are inspection surfaces only; they are not acceptance
  authority or release evidence.
