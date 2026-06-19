# xmuse Production Closure Gap Ledger

Updated: 2026-06-19.

This ledger records the current implementation proof boundary for the real
GOD chatgroup and demand-to-completion chain. It is not a readiness claim.

## Current Proof Boundary

- Latest main inspected: `ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8`.
- Strongest runtime evidence: Loop 25z48 reached one real local docs-only lane
  from durable groupchat through proposal, approval, isolated execution, gate,
  persistent OpenCode review, and final-action hold under `--no-auto-merge`.
  The lane recorded `review_runtime=opencode`,
  `review_delivery_mode=persistent`, `persistent_review_degraded=false`,
  `gate_passed=true`, and `review_decision=merge`.
- Latest focused runtime evidence: Loop 25z47 verified through the real Chat
  API that an approved lane_graph using explicit `review_runtime=OpenCode`
  projects to canonical `review_runtime=opencode` when the conversation has one
  active OpenCode review participant.
- Strongest server facts: PR #81 was merged by GitHub server state as
  `ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8` after successful `xmuse CI` on PR
  head `063dcff57bf4e325e89d3ec9bd8682427bb26e41`; post-merge main `xmuse CI`
  also passed on `ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8`.
- Proof type: local runtime proof plus inspected GitHub server facts for the
  small imported PR. This is not GitHub review truth or production readiness.

## Recent Small PR Slices

- PR #76 `codex/human-leading-mention-routing`: routed leading human mentions
  without treating body references as direct human inbox targets. Merged to
  main as `0d980be69f953b77a82c035abadc40f31797942d`.
- PR #77 `codex/real-code-lane-after-pr76`: made peer-chat runtime worktree
  repo-backed and exposed gate profile source in gate reports. Merged to main
  as `5a8b40654f934b422cb559b4a64d89a981d72a30`.
- PR #78 `codex/session-health-writeback-status`: promoted durable peer
  session health after authenticated writeback and preserved active runtime
  details in inspector output. Merged to main as
  `c5818ba433142765c817bc63fed73ec40141ae06`.
- PR #79 `codex/post-pr78-evidence-sync`: recorded the post-PR78 fullchain
  evidence boundary. Merged to main as
  `3a4ec2853ea2099f648513bbb0856415de81b906`.
- PR #80 `codex/strict-leading-mention-routing`: fixed leading role mentions
  such as `@architect Coordinate...`. Merged to main as
  `c02e9dce50b808bbd4aed1ab6d1960e32ca6472b`.
- PR #81 `codex/review-runtime-from-chat-peer`: normalized observed
  groupchat-produced review aliases such as `human_final_hold`, `final_hold`,
  and `review-god` to the active OpenCode review runtime. Merged to main as
  `ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8`.

## Manual Gaps

- Default review peer selection can still choose Codex unless OpenCode is
  explicitly requested or otherwise made authoritative for the runtime
  conversation.
- Groupchat-produced `review_runtime` aliases such as `human_final_hold`,
  `final_hold`, and `review-god` are addressed by PR #81. Explicit provider
  casing such as `OpenCode` is addressed in the current
  `codex/post-pr81-fullchain-rerun` branch and has local projection/fullchain
  evidence, but no server facts until a small PR is pushed and checked.
- The successful Loop 25z48 chain covered one docs-only lane; it is not a real
  code-change soak or production-load proof.
- The successful chain is not yet a repeated multi-turn soak run.
- Provider-native session continuity and memory persistence are not proven as
  durable product behavior.
- Live MemoryOS proof is absent.
- GitHub review truth is absent.
- Groupchat production readiness is absent.
- Full L8-L10 and full L1-L11 closure are absent.

## Forbidden Claims Still Preserved

- `github_review_truth`
- `ready_to_merge`
- `pr_merged` for a live lane beyond inspected GitHub server state
- `live_memoryos`
- `worker_output_is_review_truth`
- `local_tests_are_review_truth`
- `full_l8_l10_closure`
- `full_l1_l11_closure`
- `overnight_readiness`
- `production_ready_groupchat`
- `natural_peer_god_groupchat`

## Next Small Buckets

- P0 provider casing: open a small PR for explicit `OpenCode` to `opencode`
  canonicalization plus Loop 25z46/25z47/25z48 evidence.
- P1 stability loop: repeat real groupchat-to-final-hold with multiple turns
  and no code changes beyond the target slice.
- P2 default review authority: decide when OpenCode should be selected without
  relying on proposal text.
- P3 code-change lane rerun: repeat a small real code-change lane after the
  casing PR lands.
- P4 MemoryOS adapter proof: keep `live_memoryos` forbidden until a real trace
  id or artifact exists.
