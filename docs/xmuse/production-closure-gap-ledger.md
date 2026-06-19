# xmuse Production Closure Gap Ledger

Updated: 2026-06-19.

This ledger records the current implementation proof boundary for the real
GOD chatgroup and demand-to-completion chain. It is not a readiness claim.

## Current Proof Boundary

- Latest main inspected: `17a75cbe2cb07b06e05cd40e432e867ea2fd5e8f`.
- Strongest code-change lane runtime evidence: Loop 25z49 reached one real
  local code-change lane from durable groupchat through execute feasibility,
  proposal, OpenCode proposal review, human approval, isolated execution,
  xmuse-core gate, persistent OpenCode review, and final-action hold under
  `--no-auto-merge`. The lane recorded `review_runtime=opencode`,
  `review_delivery_mode=persistent`, `persistent_review_degraded=false`,
  `gate_passed=true`, and `review_decision=merge`.
- Latest peer-chat stability evidence: Loop 25z63 verified a local
  six-conversation Codex/OpenCode groupchat path under `--max-concurrent 10`
  and `--peer-chat-post-writeback-grace-s 20`. Each conversation reached human
  demand to Codex architect handoff, Codex execute reply, OpenCode review
  reply, durable peer-reply drain callback, and architect final summary after
  both replies. The run ended with `all_final_after_both=true`,
  `all_callbacks_created=true`, `all_callbacks_consumed=true`,
  `no_proposals_or_resolutions=true`, `total_failed_traces=0`, and
  `total_timeout_after_writeback_traces=0`.
- Strongest server facts: PR #87 was merged by GitHub server state as
  `17a75cbe2cb07b06e05cd40e432e867ea2fd5e8f` after successful `xmuse CI` on PR
  head `0c7d96d2053e78fa522d951b37506b2d41b43761` in run `27814843417`;
  post-merge main `xmuse CI` also passed on
  `17a75cbe2cb07b06e05cd40e432e867ea2fd5e8f` in run `27815021534`.
- Proof type: local runtime proof plus inspected GitHub server facts for small
  PRs. This is not GitHub review truth or production readiness.

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
- PR #82 `codex/post-pr81-fullchain-rerun`: canonicalized explicit
  `OpenCode` provider casing to the active `opencode` review runtime and
  recorded Loop 25z46/25z47/25z48 evidence. Merged to main as
  `94218b269e4a005049e18378ebdc179c1dcada28`.
- PR #83 `codex/post-pr82-code-lane-rerun`: exposed participant session
  mappings in conversation create/bootstrap responses and recorded Loop 25z49
  code-change evidence. Merged to main as
  `6c962708071895e94458ff947eaed8753c789ce0`.
- PR #84 `codex/post-pr83-scheduler-parallelism`: made durable MCP writeback
  authority outrank provider process exit for peer-chat delivery
  classification, added bounded peer-chat scheduler fan-out, and recorded Loop
  25z50/25z51/25z52 evidence. Merged to main as
  `744aee7d3215ff9b772b677a77304fb36570f878`.
- PR #85 `codex/post-pr84-final-summary-gating`: added
  `chat_mention(reply_to_inbox_item_id=...)`, direct peer-reply drain
  callbacks, and early durable-writeback release with a short grace window.
  Merged to main as `e6eeeddf5911a171bf32dc38b839fa2e7c51d62d`.
- PR #86 `codex/post-pr85-evidence-sync`: synced the post-PR85 closure
  evidence boundary. Merged to main as
  `a6575c01613e7568248e64c06a4799deb83a3b71`.
- PR #87 `codex/peer-chat-writeback-grace-tuning`: made peer-chat
  post-writeback grace configurable and defaulted it to a longer bounded wait.
  Merged to main as `17a75cbe2cb07b06e05cd40e432e867ea2fd5e8f`.

## Manual Gaps

- Default review peer selection can still choose Codex unless OpenCode is
  explicitly requested or otherwise made authoritative for the runtime
  conversation.
- Groupchat-produced `review_runtime` aliases such as `human_final_hold`,
  `final_hold`, and `review-god` are addressed by PR #81. Explicit provider
  casing such as `OpenCode` is addressed by PR #82.
- Loop 25z57 locally verified bounded final-summary gating across two
  conversations; the code/docs carrying that evidence are now in PR #85's
  merged server state.
- The successful Loop 25z49 chain covered one small API ergonomics lane; it is
  not repeated code-change soak or production-load proof.
- Loop 25z57 proved one bounded local final-summary path with a direct
  peer-reply drain callback. It is not repeated soak and not production
  readiness.
- Loop 25z63 proved one bounded local six-conversation peer-chat stability path
  after local same-participant delivery serialization and prompt reply-contract
  mitigation. It is not repeated soak and not production readiness.
- Provider result acknowledgement timeout after durable writeback is mitigated
  by early writeback detection plus configurable bounded grace in PR #87.
  Broader production-load behavior is still unproven.
- Same participant/session delivery is locally protected in the current
  candidate branch by a scheduler participant lock. This is not a general
  dependency-set planner.
- Architect final-summary gating is locally mediated by a direct peer-reply
  drain callback. A general durable dependency-set planner is still absent.
- The successful chains are not yet repeated overnight or production-load soak.
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

- P0 peer-chat delivery hardening: land same-participant delivery serialization
  and simple-reply path guidance, then rerun the six-conversation stability
  path from main.
- P1 explicit dependency coordination: add a durable coordination primitive for
  waiting on named peer replies before summaries/handoffs when direct drain is
  insufficient.
- P2 stability loop: repeat real groupchat-to-final-hold with multiple turns
  and no code changes beyond the target slice.
- P3 default review authority: decide when OpenCode should be selected without
  relying on proposal text.
- P4 code-change soak: repeat small real code-change lanes after the
  participant session PR lands.
- P5 MemoryOS adapter proof: keep `live_memoryos` forbidden until a real trace
  id or artifact exists.
