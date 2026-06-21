# Acceptance-Gated Runner Evidence - 2026-06-21

This artifact records the first short real `xmuse-platform-runner --goal
--acceptance-gate` smoke after production closure P0/P1.

## Command

```bash
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/.config/superpowers/worktrees/xmuse/production-closure-stage2-gate/.goal-runs/2026-06-21/stage2-pr155-smoke \
  --goal "Record a short acceptance-gated smoke task for PR 155." \
  --acceptance-gate \
  --github-pr 155 \
  --github-head-sha c8628ff6dfdf88bde079e668b13e491b69ff7542
```

The runtime root is ignored by git and contains the durable stores for this
smoke run.

## Terminal Result

- status: `blocked`
- blocked_reason: `github_gate_unverified`
- reason: the run intentionally produced a GitHub gate `manual_gap`; no
  `server_side_merge_proof` was present.

## Durable Refs

- runtime root:
  `.goal-runs/2026-06-21/stage2-pr155-smoke`
- chat db:
  `.goal-runs/2026-06-21/stage2-pr155-smoke/chat.db`
- spine:
  `chat.db#acceptance_spine=goalrun_0ad9767e0a8b42eba4f40dea25070ab1`
- intake message:
  `chat.db#message=msg_31e7ebeff4c4409cbbd7686342b43ef1`
- proposal:
  `chat.db#proposal=prop_6aa9a3ea606942199f92841a75862f94`
- dispatch:
  `chat_dispatch_queue#entry=dispatch:conv_8d1212226ab14f368fe33b5ee0249e9d:res_2a7e0af7fe1c4d798c23a0581ea9421c:execute`
- review verdict:
  `review_plane.json#verdict=verdict-5d94316f19cb`
- final action:
  `final_actions.json#hold=final-c700010d7aa4`
- GitHub gate evidence:
  `github_gate_evidence.json#evidence=ghgate_3bee2f613d3a41f7be12fe667aff0629`

## Evidence Facts

`github_gate_evidence.json` persisted:

- `final_action_id = final-c700010d7aa4`
- `repo = iiyazu/Cross-Muse`
- `pull_request_number = 155`
- `required_checks = quality-gates, contract-smoke-gates,
  real-runtime-integration-gate`
- `internal_reviewed_head_sha =
  c8628ff6dfdf88bde079e668b13e491b69ff7542`
- `proof_level = manual_gap`
- `can_accept = false`
- `gap_reason = server_side_merge_proof unavailable for acceptance-gated short run`

`final_actions.json` persisted:

- `status = approved`
- `resolved_by = platform-runner`
- `github_gate_gap_ref =
  github_gate_evidence.json#evidence=ghgate_3bee2f613d3a41f7be12fe667aff0629`
- no `github_gate_evidence_ref`

An earlier pre-PR smoke against PR #154 also ended as
`blocked/github_gate_unverified`. The PR #155 run above is the evidence bound to
this branch.

## Boundary

This closes the minimal P2 command path for a blocked run. It does not claim
production readiness or an accepted demand. It remains the negative proof that
manual approval, copied GitHub text, and stdout summaries cannot accept a spine
without producer-backed `server_side_merge_proof`. The paired accepted short
path is recorded in
`docs/xmuse/acceptance-gated-live-capture-evidence-2026-06-21.md`.
