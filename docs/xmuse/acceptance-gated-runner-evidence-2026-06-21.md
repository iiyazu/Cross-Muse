# Acceptance-Gated Runner Evidence - 2026-06-21

This artifact records the first short real `xmuse-platform-runner --goal
--acceptance-gate` smoke after production closure P0/P1.

## Command

```bash
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/.config/superpowers/worktrees/xmuse/production-closure-stage2-gate/.goal-runs/2026-06-21/stage2-pre-pr-smoke-absolute \
  --goal "Record a short acceptance-gated smoke task before PR." \
  --acceptance-gate \
  --github-pr 154 \
  --github-head-sha d36c301536673c32d2c3c6a33adb541ae2ca1be8
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
  `.goal-runs/2026-06-21/stage2-pre-pr-smoke-absolute`
- chat db:
  `.goal-runs/2026-06-21/stage2-pre-pr-smoke-absolute/chat.db`
- spine:
  `chat.db#acceptance_spine=goalrun_5baf39d3f46c4b8abaab085c791769d5`
- intake message:
  `chat.db#message=msg_1e5b563c91aa4aa485957bf56a9dac30`
- proposal:
  `chat.db#proposal=prop_7aad205777f044de92330e0c15d5f69c`
- dispatch:
  `chat_dispatch_queue#entry=dispatch:conv_a63448d28e5e412d972a10605288d4e4:res_e6c636467cf3490298d24a3aae7f4fac:execute`
- review verdict:
  `review_plane.json#verdict=verdict-c66bcaf4725b`
- final action:
  `final_actions.json#hold=final-06d605c869f9`
- GitHub gate evidence:
  `github_gate_evidence.json#evidence=ghgate_44c2b8aa4e2c46159ae5e77360749442`

## Evidence Facts

`github_gate_evidence.json` persisted:

- `final_action_id = final-06d605c869f9`
- `repo = iiyazu/Cross-Muse`
- `pull_request_number = 154`
- `required_checks = quality-gates, contract-smoke-gates,
  real-runtime-integration-gate`
- `internal_reviewed_head_sha =
  d36c301536673c32d2c3c6a33adb541ae2ca1be8`
- `proof_level = manual_gap`
- `can_accept = false`
- `gap_reason = server_side_merge_proof unavailable for acceptance-gated short run`

`final_actions.json` persisted:

- `status = approved`
- `resolved_by = platform-runner`
- `github_gate_gap_ref =
  github_gate_evidence.json#evidence=ghgate_44c2b8aa4e2c46159ae5e77360749442`
- no `github_gate_evidence_ref`

## Boundary

This closes the minimal P2 command path for a blocked run. It does not claim
production readiness or an accepted demand. A future accepted run still requires
producer-owned `server_side_merge_proof` for the same final action.
