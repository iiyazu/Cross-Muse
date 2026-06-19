# xmuse Production Closure Gap Ledger

Updated: 2026-06-19.

This ledger records the current implementation proof boundary for the real
GOD chatgroup and demand-to-completion chain. It is not a readiness claim.

## Current Proof Boundary

- Latest main inspected: `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3`.
- Latest post-PR102 main fullchain evidence: PR #102 merged the
  `chat_mention` current-turn auto-bind fix to main as
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3` after successful PR CI and
  successful post-merge main CI. Loop 25z78 then ran from that post-merge main
  and drove the same docs-only real chain through durable groupchat, execute
  feasibility, proposal, approval, dispatch, isolated execution, gate,
  persistent OpenCode review, and final-action hold. The original architect
  inbox recorded `status=read`, `tool_trace=chat_mention`,
  `delivery_mode=mcp_writeback`, and a non-null `responded_message_id`; all
  inbox items ended `read`; the lane recorded `gate_passed=true`,
  `review_decision=merge`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_peer_defaulted=true`,
  `review_peer_cli_kind=opencode`,
  `review_peer_model=opencode-go/deepseek-v4-flash`,
  `peer_delivery_mode=configured_peer`, and `status=awaiting_final_action`.
  This is bounded local runtime proof plus inspected GitHub server facts for
  the small PR, not production readiness or full closure proof.
- Strongest code-change lane runtime evidence: Loop 25z69 ran after PR #93's
  default-review fix from current main, drove one real local code-change lane
  from durable groupchat through execute feasibility, proposal, runtime-driver
  approval, isolated execution, xmuse-core gate, persistent OpenCode review,
  and final-action hold under `--no-auto-merge`. The proposal intentionally
  omitted `review_runtime`; the lane recorded `proposal_has_review_runtime=false`,
  `review_peer_defaulted=true`,
  `review_peer_participant.cli_kind=opencode`,
  `review_peer_participant.model=opencode-go/deepseek-v4-flash`,
  `peer_delivery_mode=configured_peer`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `gate_passed=true`,
  `review_decision=merge`, and `status=awaiting_final_action`. PR #94 landed
  the review-peer runtime metadata candidate from that loop.
- Earlier post-merge fullchain evidence: Loop 25z74 ran after PR #98's merged
  main plus PR #99's local branch fix, intentionally pre-created an empty
  execution worktree, and reached `awaiting_final_action` on one docs-only
  fullchain lane with `proposal_has_review_runtime=false`, `gate_passed=true`,
  `review_decision=merge`, and `review_summary=review accepted`. The run used
  `review_delivery_mode=one_shot_fallback` with
  `persistent_review_degraded=true` and
  `persistent_review_degraded_reason=missing_feature_identity`, so it is not
  persistent OpenCode review proof or defaulted review peer metadata proof.
- Latest direct lane graph feature-scope evidence: Loop 25z75 locally proved
  the direct lane graph `feature_scope_id` fix, then PR #101 merged the small
  fix to main as `cae16e00429a4f97e30a07ecb69e5cd977ea16e8` after successful
  PR CI and successful post-merge main CI. Loop 25z76/25z77 both ran from that
  post-merge main, so `missing_feature_identity` is no longer the current
  blocker for this docs-only fullchain shape.
- Latest peer-chat stability evidence: Loop 25z70b ran concurrently with
  Loop 25z70a from the same current main using a separate `XMUSE_ROOT`,
  execution worktree, Chat API port, MCP port, and runner. Across three
  Codex/OpenCode groupchat conversations, each conversation reached human
  demand to Codex architect handoff, Codex execute reply, OpenCode review
  reply, durable peer-reply drain callback, and architect final summary after
  both replies. The aggregate result was `all_final_after_both=true`,
  `all_callbacks_created=true`, `all_callbacks_consumed=true`,
  `no_proposals_or_resolutions=true`, `no_open_or_failed_inbox=true`,
  `no_failed_or_timeout_traces=true`, `total_failed_traces=0`, and
  `total_timeout_after_writeback_traces=0`.
- Latest scoped process-health evidence: PR #96 merged the small fix that
  scopes runtime process discovery by `XMUSE_ROOT`/`--xmuse-root` for
  `run_health`, dashboard/TUI read models, and the platform runner's
  `--health-once` path. Loop 25z71 reran two isolated local shards and each
  shard's health snapshot reported `runner_count=1`, `mcp_count=1`,
  `counts_by_service.chat_api=1`, and `warnings=[]`. This makes higher
  operator-level parallelism less noisy; it is still bounded health
  observability proof, not production readiness or soak.
- Latest higher-parallelism evidence: Loop 25z72 ran three isolated local
  shards concurrently. Two stability shards completed six total Codex/OpenCode
  groupchat conversations with final summaries after execute and review
  replies, all callbacks consumed, no proposals/resolutions, no open/failed
  inbox items, and no failed/timeout traces. The fullchain shard exposed an
  empty execution worktree gate failure that PR #98 later fixed.
- Latest lane worktree recovery evidence: PR #98 merged the small fix that
  treats an existing empty lane worktree directory as uninitialized and
  recreates it as a git worktree. Loop 25z73 intentionally pre-created an
  empty execution worktree and verified `exec_is_git_worktree=true`,
  `exec_gate_profiles_exists=true`,
  `base_head_sha=591aa68e470aa5272df5bc46bbfab06a917bd4f4`, and
  `gate_passed=true`.
- Latest review diff authority evidence: PR #99 merged the small fix that
  includes untracked new files in MCP `get_diff(lane_id)` by appending
  `git diff --no-index -- /dev/null <path>` patches. Loop 25z74 then moved the
  same docs-only fullchain shape from Loop 25z73's review rework to
  `review_decision=merge` and `status=awaiting_final_action`.
- Latest default review authority evidence: PR #93 merged the small fix that
  reuses a unique active OpenCode review participant when the proposal omits
  `review_runtime`. GitHub server state reports PR #93 merged as
  `7468a5ab8797cf0a34528de419ceaf730034e75e` after successful PR checks on
  head `bc2be0e6e42a208d0e45a1a1d023723b4bfce194`, and post-merge main CI
  passed on `7468a5ab8797cf0a34528de419ceaf730034e75e`. Loop 25z69 then
  reran a real code-change lane from that main and confirmed defaulted
  persistent OpenCode review locally. This is still bounded local runtime proof
  plus inspected GitHub server facts for the small PR, not GitHub review truth
  or production readiness.
- Latest review peer observability evidence: PR #94 merged the small fix that
  persists `review_peer_cli_kind` and `review_peer_model` on configured/default
  review peer lanes and exposes those fields in run health summaries. GitHub
  server state reports PR #94 merged as
  `2996643e4f13a8ea97af6b6f9675fd697a847716` after successful PR checks on
  head `d29c6f434fb22974ba477a1267cf3e3c9b35a8f5`, and post-merge main CI
  passed on `2996643e4f13a8ea97af6b6f9675fd697a847716`. Loop 25z70a then
  verified the metadata in a real post-merge fullchain lane's run health
  summary.
- Review-state repeat evidence: Loop 25z65 reran a docs-only lane from
  current `origin/main` at `a8cceabb51022ddf802da276df1e4c37419b65b5` and
  reached `awaiting_final_action` with `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_decision=merge`, and no
  runtime-artifact match for the Loop 25z64 invalid transition noise. This is a
  bounded local repeat, not code-change soak or production readiness.
- Strongest server facts: PR #102 was merged by GitHub server state as
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3` after successful `xmuse CI` on PR
  head `d4728c36cb252899a5631d3e0686fee4fb4c47cb` in run `27831639110`;
  post-merge main `xmuse CI` also passed on
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3` in run `27831706622`.
- Latest merged evidence sync: PR #100 `codex/post-pr99-runtime-evidence-sync`
  merged to main as `f03a058a0f0468e3902e2aafeb7b063601df2866`; PR #101
  subsequently merged the direct lane graph feature-scope implementation, and
  PR #102 subsequently merged the peer handoff writeback lifecycle fix.
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
- PR #88 `codex/post-pr87-runtime-audit`: serialized peer-chat delivery per
  target participant/session, tightened simple reply guidance, and recorded
  post-PR87 runtime evidence. Merged to main as
  `71ba128edfadbaea7ca45ea288e1ee5faf92e6b9`.
- PR #89 `codex/inspector-provider-summary`: added
  `participants.provider_summary` to the conversation inspector and recorded
  Loop 25z64 fullchain evidence. Merged to main as
  `8e9ae4d887f243723561a4ebe01e5ea1817c4963`.
- PR #90 `codex/review-state-idempotence`: ignored late rejected/rework review
  conflicts after accepted review/final-hold state and recorded Loop 25z65
  repeat evidence. Merged to main as
  `a8cceabb51022ddf802da276df1e4c37419b65b5`.
- PR #91 `codex/post-pr90-evidence-sync`: synced post-PR90 runtime evidence
  and gap ledger updates. Merged to main as
  `ff6a5fd9f61b86d5c1989fd6f613bcf5e6906009`.
- PR #92 `codex/post-pr91-parallel-stability-evidence`: recorded the
  post-PR91 two-shard parallel stability evidence. Merged to main as
  `9f19d84aeeb52043517a40e0c29f72edda2366a6`.
- PR #93 `codex/default-review-opencode-peer-routing`: defaulted review
  routing to a unique active OpenCode review peer when the proposal omitted
  `review_runtime`. Merged to main as
  `7468a5ab8797cf0a34528de419ceaf730034e75e`.
- PR #94 `codex/review-peer-runtime-metadata`: persisted configured/default
  review peer runtime metadata on lanes and exposed it in run health summaries.
  Merged to main as `2996643e4f13a8ea97af6b6f9675fd697a847716`.
- PR #95 `codex/post-pr94-parallel-runtime-evidence`: recorded the post-PR94
  parallel runtime evidence from Loop 25z70. Merged to main as
  `0f35f9ad33c6e701b1457b0e5aaa22bc2093e0c4`.
- PR #96 `codex/scoped-runtime-process-health`: scoped runtime process health
  discovery by `XMUSE_ROOT`/`--xmuse-root` for parallel shards and recorded
  Loop 25z71 evidence. Merged to main as
  `dcf4badf5da82cb472ea0f23d1c825f94d26218b`.
- PR #97 `codex/post-pr96-scoped-health-evidence`: recorded Loop 25z71 scoped
  process-health evidence. Merged to main as
  `591aa68e470aa5272df5bc46bbfab06a917bd4f4`.
- PR #98 `codex/recreate-empty-lane-worktree`: recreated empty projected lane
  worktree directories as git worktrees and recorded Loop 25z73 evidence.
  Merged to main as `cae76c1da7d1c38df9884579ba822b8019f3b197`.
- PR #99 `codex/include-untracked-lane-diff`: included untracked new files in
  MCP `get_diff(lane_id)` and recorded Loop 25z74 evidence. Merged to main as
  `2325427c0b96f5bc2f804a6f72ef8d5e77782fca`.
- PR #100 `codex/post-pr99-runtime-evidence-sync`: synced post-PR99 runtime
  evidence into the docs and gap ledger. Merged to main as
  `f03a058a0f0468e3902e2aafeb7b063601df2866`.
- PR #101 `codex/direct-lane-graph-feature-scope`: projected
  `feature_scope_id` for direct lane graphs without using lane primary
  `feature_id` as feature scope. Merged to main as
  `cae16e00429a4f97e30a07ecb69e5cd977ea16e8`.
- PR #102 `codex/peer-mention-writeback-autobind`: auto-bound
  `chat_mention` over MCP `/sse` to the participant's single claimed inbox
  item when `reply_to_inbox_item_id` is omitted, preserving explicit
  writeback for real peer handoffs. Merged to main as
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3`.

## Manual Gaps

- Default review peer selection for the case where the conversation already
  has exactly one active OpenCode review participant is now present on main
  through PR #93. Ambiguous, missing, or inactive review participants remain
  bounded behavior and must not be reported as general review authority proof.
- Review peer runtime identity is now observable in lane metadata and run
  health summaries through PR #94, but those fields are metadata only.
  `peer_delivery_mode`, `review_delivery_mode`, and durable callback evidence
  remain the delivery authority.
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
- Loop 25z70 proved one bounded local two-shard parallel runtime path after
  PR #94: one fullchain docs-only lane plus one three-conversation stability
  shard. It is not repeated soak, not overnight readiness, and not production
  readiness.
- Loop 25z71 repaired the process-health false positives exposed by Loop
  25z70. Scoped process discovery now reports the shard-local runner, MCP
  server, and Chat API without duplicate-runner or missing-MCP warnings for
  the two-shard harness. This is observability proof only; it is not a broader
  scheduling, capacity, or production-load claim.
- Loop 25z72 proved six groupchat-only conversations across two concurrent
  stability shards, while the concurrent fullchain shard failed at gate because
  an empty pre-created execution worktree was treated as initialized. This was
  a real runtime gap, not a proof of fullchain failure after PR #98/#99.
- Loop 25z73 verified empty execution worktree recovery through gate pass, then
  exposed that review could not see untracked new files through
  `get_diff(lane_id)`. PR #99 addresses that specific diff authority gap.
- Loop 25z74 reached final-action hold after the untracked diff fix, but it
  used `review_delivery_mode=one_shot_fallback` with
  `persistent_review_degraded_reason=missing_feature_identity`. Persistent
  OpenCode review and defaulted review peer metadata remain unproven for this
  shape.
- Loop 25z75 locally repaired the direct lane graph feature-scope gap and
  reached final-action hold with persistent OpenCode review/defaulted peer
  metadata. PR #101 then merged that small fix and post-merge main CI passed.
- Loop 25z76 exposed a peer-chat writeback lifecycle gap after PR #101:
  `chat_mention` over `/sse` could omit `reply_to_inbox_item_id`, enqueue the
  execute peer, and leave the architect's source inbox to fail with
  `peer_response_timeout`.
- Loop 25z77 locally repaired that `chat_mention` current-turn auto-bind gap
  and reran the fullchain to final-action hold with no failed inbox items.
  PR #102 then merged the fix, and Loop 25z78 reran the same fullchain shape
  from post-merge main with no failed inbox items.
- Provider result acknowledgement timeout after durable writeback is mitigated
  by early writeback detection plus configurable bounded grace in PR #87.
  Broader production-load behavior is still unproven.
- Same participant/session delivery is protected in main by the PR #88 scheduler
  participant lock. This is not a general dependency-set planner.
- Loop 25z64 proved one bounded local groupchat-produced code lane to
  final-action hold. It also logged non-blocking review-state transition noise:
  `cannot transition loop25z64_inspector_provider_summary from reviewed to
  rejected`.
- PR #90 guards late persistent rework/rejected verdicts after accepted
  review/final-hold state by recording ignored-conflict metadata instead of
  attempting an invalid transition. Loop 25z65 then gave one bounded local
  repeat without the Loop 25z64 invalid transition noise.
- Loop 25z65 was docs-only. It is not repeated code-change soak and does not
  replace Loop 25z64 as the strongest groupchat-produced code lane evidence.
- Loop 25z64 did not expose `review_delivery_mode=persistent` or
  `persistent_review_degraded=false`; do not report it as complete persistent
  OpenCode delivery proof.
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

- P0 peer handoff writeback lifecycle: complete for the bounded
  `chat_mention` current-turn auto-bind gap. PR #102 merged the fix and Loop
  25z78 reran from post-merge main. Keep broader `/sse` tool-surface and
  `chat_post_message` non-closing status-message behavior out of this claim.
- P1 explicit dependency coordination: add a durable coordination primitive for
  waiting on named peer replies before summaries/handoffs when direct drain is
  insufficient.
- P2 higher-parallelism stability loop: repeat real groupchat-to-final-hold
  with independent `XMUSE_ROOT` directories, execution worktrees, Chat API
  ports, MCP ports, and runners when increasing concurrency beyond the current
  two-shard evidence. Do not share durable stores or one PR branch across
  parallel probes.
- P3 ambiguous review authority: define fail-closed behavior for missing or
  multiple OpenCode review participants without relying on proposal text.
- P4 code-change soak: repeat small real code-change lanes after the
  inspector provider summary PR lands.
- P5 MemoryOS adapter proof: keep `live_memoryos` forbidden until a real trace
  id or artifact exists.
