# Acceptance-Gated Live Capture Evidence - 2026-06-21

This artifact records the first short real `xmuse-platform-runner --goal
--acceptance-gate --github-live-capture` run that produced producer-owned
`server_side_merge_proof`.

## Command

```bash
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/.config/superpowers/worktrees/xmuse/production-closure-stage3-live-gate/.goal-runs/2026-06-21/stage3-live-pr155-accepted \
  --goal "Record a live GitHub acceptance-gated smoke task for merged PR 155." \
  --acceptance-gate \
  --github-pr 155 \
  --github-live-capture \
  --internal-review-artifact /home/iiyatu/.config/superpowers/worktrees/xmuse/production-closure-stage3-live-gate/.goal-runs/2026-06-21/stage3-live-pr155-accepted/internal-review.json \
  --internal-reviewer platform-runner \
  --internal-reviewed-head-sha 1798e0a31cd1a80163a5e70287e8b0d1684e0aee
```

The runtime root is ignored by git and contains the durable stores for this
smoke run. The command uses read-only `gh api` through
`GitHubCliServerSideTruthClient`.

## Terminal Result

- status: `accepted`
- blocked_reason: `null`
- reason: the GitHub gate evidence producer captured a complete
  `server_side_merge_proof` for the same final action.

## Durable Refs

- runtime root:
  `.goal-runs/2026-06-21/stage3-live-pr155-accepted`
- chat db:
  `.goal-runs/2026-06-21/stage3-live-pr155-accepted/chat.db`
- internal review artifact:
  `.goal-runs/2026-06-21/stage3-live-pr155-accepted/internal-review.json`
- spine:
  `chat.db#acceptance_spine=goalrun_3db27db05d3a40af821632e075e880e6`
- intake message:
  `chat.db#message=msg_2a7739b09cf2481381d2e9e679819737`
- proposal:
  `chat.db#proposal=prop_6169c7ff2d6c4199ba36a0831900cc45`
- dispatch:
  `chat_dispatch_queue#entry=dispatch:conv_eaa71002a0144e049fcd43f789f0f389:res_07650a71ff72456095c0bdc1a1234b74:execute`
- review verdict:
  `review_plane.json#verdict=verdict-798ae0c75444`
- final action:
  `final_actions.json#hold=final-80798c437229`
- GitHub gate evidence:
  `github_gate_evidence.json#evidence=ghgate_de02b6e176e449b687be296eb7a230ec`

## Evidence Facts

`github_gate_evidence.json` persisted:

- `final_action_id = final-80798c437229`
- `repo = iiyazu/Cross-Muse`
- `pull_request_number = 155`
- `required_checks = quality-gates, contract-smoke-gates,
  real-runtime-integration-gate`
- `proof_level = server_side_merge_proof`
- `can_accept = true`
- `check_run_ids = 82564030160, 82564030153, 82564030146`
- `expected_source_app = github-actions`
- `internal_review_artifact =
  .goal-runs/2026-06-21/stage3-live-pr155-accepted/internal-review.json`
- `internal_reviewer = platform-runner`
- `internal_reviewed_head_sha =
  1798e0a31cd1a80163a5e70287e8b0d1684e0aee`
- `internal_review_verified = true`
- `merge_commit_sha = 4fd40a735e62be255e787ce93bdc3d5653d0255e`
- `merged_at = 2026-06-21T10:56:19Z`
- `merge_event_id = PR_kwDOS2Bbks7o2IPd`
- `gap_reason = null`

`final_actions.json` persisted:

- `status = approved`
- `resolved_by = platform-runner`
- `github_gate_evidence_ref =
  github_gate_evidence.json#evidence=ghgate_de02b6e176e449b687be296eb7a230ec`
- no `github_gate_gap_ref`

## Boundary

This closes the short-run accepted path for P3. It does not prove a long
multi-hour provider execution. It proves the acceptance-gated runner can move
from durable final action to accepted only through producer-owned live GitHub
server-side evidence.
