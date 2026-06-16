# xmuse Production Closure Gap Ledger

更新日期: 2026-06-16

本文档是 xmuse 生产闭环缺口台账。它用于把“用户最终看到的体验”和
“生产实现必须遵守的依赖顺序”分开记录。

用户最终体验路径可以这样理解:

```text
用户入口
-> operator cockpit / TUI
-> GOD room
-> speaker runtime
-> blueprint freeze
-> laneDAG
-> execution/review
-> MemoryOS
-> release evidence
-> GitHub truth
-> overnight autonomy
```

但实现与验收不能按这个展示顺序推进。TUI、dashboard、release pack 和
overnight soak 都是下游投影、控制面或综合证明，不能先于它们依赖的 durable
runtime、provider invocation、lane authority、review truth 完成。后续生产级
实现按本文的 Dependency-First Closure Layers 推进。

本文档不是完成证明，也不是 merge truth。每一层都必须区分:

- 已有实现证据；
- 仍缺的生产闭环；
- 要关闭该层必须拿到的 proof；
- 下一步最小生产切片；
- 下游在该层关闭前不能声称的能力。

## Current Truth Snapshot

当前事实需在每轮长 `/goal` 开始时重新确认。本节是台账编写时的事实边界，
不是自动更新状态。

- Branch: `vision-closure-deliberation-tui`
- Local base head before audit reinforcement annotation:
  `0c3ccc4553f582667f5349c9b1b4e5de3a6cd81a`
- Local head at start of L4 provider invocation producer slice:
  `db9a759ac23e3e5f6095fe35ed5d373e64281505`
- Local head at start of L5 provider invocation capture slice:
  `85e573c24c4c1abc955638b4feb609c6381580ff`
- Local head at start of L4/L5 opt-in live route repair:
  `7aef014e41b6de3caac032c3338c39accf1a8e90`
- Local head at start of L4 opencode inline-variant fail-closed slice:
  `0d99e7765d31b921a948dcccaab96c967a7c14ed`
- Local head at start of L6 freeze proof classification slice:
  `5f74e2d3911d1f919758ea397ff5c423149a20ce`
- Local head at start of L7 laneDAG proof metadata slice:
  `914d1b2597bf2a011cb321b123391bd0d26a5b28`
- Local head at start of L8 recovery lineage evidence slice:
  `7d96d3045af4a02d12c045485ed78f072af9f093`
- Local head at start of L9 review intake evidence slice:
  `b345bff0488275aeb1f472653eed7dae66cb1171`
- Local head at start of L9 independent review verdict artifact slice:
  `9cfde76cf5e974a0c0fdbbb851a58cbf09fcbe63`
- Local head at start of L9 patch-forward laneDAG contract slice:
  `39c5c00c46a3ec09ad9a65019ad5b95697d961f4`
- Local head at start of L9 reviewed patch-lane closure handoff slice:
  `734a410a181dd5e6d880f68e248c945e0668f76a`
- Local head at start of L10 review-closure release evidence linkage slice:
  `31f9a96195d8194f6b0fcd5a4464fb340ecc7f85`
- Local head at start of L10 review-closure MemoryOS candidate source-ref slice:
  `112d410334ebf8ae702dc5582297aedc57cd223d`
- Local head at start of L9 review-plane store sync slice:
  `b9b94acbdf8748bbc5fcd56bd40c5a93b702aded`
- Local head at start of L8 review-intake recovery enforcement slice:
  `d8e268c2a70ffc1e2fe83fe3d51850cc93a2ed1d`
- Local head at start of L8 dispatch recovery enforcement slice:
  `9befbc8709585df60072ffef26b26cbc0b61c6ee`
- Local head at start of L3 public event append proof-boundary slice:
  `9190723d7da2580fed392829f3367c32b52f82a9`
- Local head at start of L3 public event append authorship classification slice:
  `2ac5eebeb0226324e3bba5a3e62b73c7c27e3124`
- Local head at start of L3 replay event proof projection slice:
  `515f1817e8c7fabf9c594b96ed044018eaefbc6f`
- Local head at start of L6 freeze manual-gap event proof enforcement slice:
  `604851eca5df99de1e0c9a3b51576037c8a3c93b`
- Local head at start of L3-L5 multi-turn provider speech orchestrator slice:
  `3c8b17eb433a5536899ca8936c545323da1ee1ab`
- Local head at start of L6 multi-turn freeze lineage slice:
  `4d9e5ef9f9404813e337038409138448e70495da`
- Local head at start of L7 graph-native dispatch authority slice:
  `91500e4d852e07bacf4ed4ff00e9aa7ef0bd2f71`
- Local head at start of L7 blueprint proof status lineage slice:
  `3251134b63f886758559a27d80393e9543ac3c80`
- Local head at start of L7 laneDAG graph-set/status bridge slice:
  `a9644c58fd3b0ef1b7d02cd95b703fd1a3344938`
- Local head at start of L9 review-intake graph-status gate slice:
  `60d233c5758c63a2a31a2c2b3d78e62559971a29`
- Local head at start of L9 review-verdict graph-status sync slice:
  `e2596cbbb6111b4d2c00523956fe878d5369ea04`
- Local head at start of L9 review-closure graph-status gate slice:
  `1431e64b78dacbca0a3cec224a1cd047c857b35b`
- Local head at start of L10 multi-turn provider speech release-lineage slice:
  `1284b3d1c52042e5cf82d892b07323aad96c1bc3`
- Local head at start of L10 runtime-closure MemoryOS candidate source-ref slice:
  `3f75c0dceca2743de03a1fffb37a032f1aa58784`
- Local head at start of L8 runner candidate recovery gate slice:
  `2007e7e42370881245adaf7a8fb351cf04d2df29`
- Local head at start of L8 runner supervisor recovery projection slice:
  `48c49906d3493b91790d9f85cf8fab020e0e5dce`
- Local head at start of L8 runner loop recovery local proof slice:
  `6c9cb329ff5a839b7632d324982073b64ce51491`
- Local head at start of L3/L5 provider-backed deliberation event capture slice:
  `4badeb6b4764e5633bbd68b4cbfe385dc8e98943`
- Local head at start of L6 provider-backed event lineage freeze slice:
  `1566e657d8548d3627eed22dfd6b013d16fba1cf`
- Local head at start of L7/L10 freeze source-event lineage carry slice:
  `aff7607052bb4dd4f017b84ae728dc73f57a0995`
- Local head at start of L7-L10 graph-status source-event lineage carrier slice:
  `a47e5ba657cc1e307cbcb2b5dadb521852232a99`
- Local head at start of L8 runner recovery proof artifact slice:
  `b122394186a697a2512fd23f9bb90ea70db41273`
- Local head at start of L9 runner recovery proof lineage consumer slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 local execution candidate producer slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain proof capture slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-closure auto chain-proof handoff slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 platform-runner candidate handoff proof slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 shared review-handoff gate refactor slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L10 GitHub server-truth refresh slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L10 GitHub server-truth artifact consumer slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L10 release-pack review-chain proof aggregation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain durable second-step/session evidence slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain upstream session artifact validation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain session semantic cross-link validation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain patch-forward lane-contract validation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain patch-forward source-gap boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain reviewer independence boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain graph-status source-lineage boundary
  slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain review-intake graph-status boundary
  slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain candidate graph-status boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain candidate artifact-ref boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain embedded candidate-lineage boundary
  slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 review-chain bounded-session consumer gate
  slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain runner-recovery boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-chain graph-wide lane-accounting boundary
  slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 platform-runner session-boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 platform-runner explicit recovery-root slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 stale-dispatch repair recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 runner-session dispatch-failure boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 pidless dispatched-lane recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 runner-session candidate-capture-failure boundary
  slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 runner-session empty-candidate proof boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 direct review-closure runner-session handoff
  gate slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 review-chain current-handoff consumer
  revalidation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 review-closure candidate producer boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 runner-recovery graph-scope boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 review-chain release-linkage summary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 platform-runner candidate graph-status reviewability
  boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 graph-native worker-evidence producer handoff slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 worker-evidence bundle verdict/chain citation
  boundary slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 patch-lane graph-native worker-evidence producer
  coverage slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 worker-evidence bundle release source-ref
  aggregation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 review-chain source-event lineage source-ref
  aggregation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9/L10 direct review-closure current-handoff
  revalidation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L10 review-chain release-linkage source-ref gate slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L10 runtime-closure MemoryOS handoff revalidation slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 overnight supervisor recovery gate slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L9 runner-session worker-bundle lineage slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L10 expected review-chain gap slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 orchestrator gate-failure recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 review patch-forward recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 review rejection recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 merge-failure recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 review retry-exhaustion recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8 review retry recovery-artifact slice:
  `654b418c52cc1487193561f65e0521a5a82f0452`
- Local head at start of L8/L9/L10 closure controller contract slice:
  `b050d534873594466e46190619ab20387427f231`
- Local head at start of L8 shared recovery writer consolidation slice:
  `b050d534873594466e46190619ab20387427f231`
- Local head at start of x3 closure-controller freshness/admission slice:
  `5bdf647cb9e127000554bef587697547797224f6`
- Local head at start of x3 shared release/review scope admission slice:
  `d19e936fbc794943becb9b37499e6d6a62b84ecc`
- Local head at start of x3 review-chain closure-reconciler handoff slice:
  `d4ea5c4020ef6b25c9526587925d0a6f520cb51b`
- Local head at start of x3 release-handoff candidate-ref revalidation slice:
  `0e09f27ff0614da31fb8ca3e7d45cf193d55ebf3`
- Local head at start of x3 ClosureObject stable-ref admission slice:
  `875547f1c4a76615a068fc17580aaafa7357b84a`
- Local head at start of x3 ClosureObject owner-lineage admission slice:
  `955ebd56330a9fea61fed40c430b0dc9aeca5bb3`
- Local head at start of x3 ClosureObject owner-ref projection slice:
  `e818f52ec434aed0042eee8cf6c169683ecb2d7b`
- Local head at start of x3 ClosureObject complete-condition admission slice:
  `1a02f7acb5ebc0ecadbce9b73dabc9f7733e2206`
- Local head at start of x3 release-gate digest refs preservation slice:
  `bcc49d1caf6548f56cdf69c73d20619563ff1085`
- Local head at start of x3 release-readiness forbidden-claim projection slice:
  `5220369bcf8da7f9a834159956669dce0d42c180`
- Local head at start of x3 GitHub release-gate forbidden-claim producer slice:
  `709008aff94a56ef88db38a78d78d9347003db56`
- Local head at start of x3 GitHub release-gate model-admission slice:
  `6cd34fcff8dd75ec9e2465d404095ae4e97d7dc0`
- Local head at start of x3 MemoryOS live-gate source-ref boundary slice:
  `cf6bd548fcf75c4374ed95ff5c800b290a01ed90`
- Local head at start of x3 patch-forward lineage scope admission slice:
  `cafb4b49cdf8f562b64c94950382cb8a3e9318da`
- Local head at start of x3 patch-forward lineage review-closure ref admission
  slice:
  `365d956307e37575054d89f3aa3fc384db968be8`
- Local head at start of x3 validated-execution-candidate worker-bundle
  admission slice:
  `e56c9c3a8f19011f2f4ee8e9e14c3d9942562e11`
- Local head at start of x3 review-chain runner-session worker-bundle
  admission slice:
  `c729c5c79a8e45ed45bf68cc18bb67a920cdac68`
- Local head at start of x3 terminal review worker-bundle citation admission
  slice:
  `20fdc0a0a3409c7a121d8de83bb7228b9e987e1d`
- Local head at start of x3 review-chain L10 worker-bundle citation-status
  admission slice:
  `9f429e25bc6bcdf776e09790d75ef13cb555a3b5`
- Local head at start of x3 release-linkage bounded/current handoff admission
  slice:
  `60c8b755ea7b98cb99a87347d07a55305ad13988`
- PR: <https://github.com/iiyazu/Cross-Muse/pull/43>
- PR state last checked: draft/open/unmerged
- PR merge state last checked: `CLEAN`
- PR review decision last checked: empty
- Verified GitHub Actions truth before the x3 freshness/admission slice applied
  to remote head `5bdf647cb9e127000554bef587697547797224f6`: run
  `27603798046`, success. Jobs success: `quality-gates`,
  `contract-smoke-gates`, `real-runtime-integration-gate`.
- Last pushed worktree refresh was verified for head
  `b154021111400863098f11ed98eeb24d6fad9311` by run
  `27607281313`; local x3 closure-controller/admission changes after that
  head are not GitHub Actions verified until pushed and rechecked.

Machine-readable snapshot for gates and future `/goal` setup:

```yaml
truth_snapshot:
  branch: vision-closure-deliberation-tui
  base_head: 2cfc9e3016ff1671758bd78b3b69f8ca922307c1
  local_head_at_l4_provider_invocation_slice: db9a759ac23e3e5f6095fe35ed5d373e64281505
  local_head_at_l5_provider_invocation_capture_slice: 85e573c24c4c1abc955638b4feb609c6381580ff
  local_head_at_l4_l5_opt_in_live_route_repair: 7aef014e41b6de3caac032c3338c39accf1a8e90
  local_head_at_l6_freeze_proof_classification_slice: 5f74e2d3911d1f919758ea397ff5c423149a20ce
  local_head_at_l7_lanedag_proof_metadata_slice: 914d1b2597bf2a011cb321b123391bd0d26a5b28
  local_head_at_l8_recovery_lineage_evidence_slice: 7d96d3045af4a02d12c045485ed78f072af9f093
  local_head_at_l9_review_intake_evidence_slice: b345bff0488275aeb1f472653eed7dae66cb1171
  local_head_at_l9_review_verdict_artifact_slice: 9cfde76cf5e974a0c0fdbbb851a58cbf09fcbe63
  local_head_at_l9_patch_forward_lanedag_contract_slice: 39c5c00c46a3ec09ad9a65019ad5b95697d961f4
  local_head_at_l9_reviewed_patch_lane_closure_handoff_slice: 734a410a181dd5e6d880f68e248c945e0668f76a
  local_head_at_l10_review_closure_release_evidence_linkage_slice: 31f9a96195d8194f6b0fcd5a4464fb340ecc7f85
  local_head_at_l10_review_closure_memoryos_candidate_source_ref_slice: 112d410334ebf8ae702dc5582297aedc57cd223d
  local_head_at_l9_review_plane_store_sync_slice: b9b94acbdf8748bbc5fcd56bd40c5a93b702aded
  local_head_at_l8_review_intake_recovery_enforcement_slice: d8e268c2a70ffc1e2fe83fe3d51850cc93a2ed1d
  local_head_at_l8_dispatch_recovery_enforcement_slice: 9befbc8709585df60072ffef26b26cbc0b61c6ee
  local_head_at_l3_public_event_append_proof_boundary_slice: 9190723d7da2580fed392829f3367c32b52f82a9
  local_head_at_l3_public_event_append_authorship_classification_slice: 2ac5eebeb0226324e3bba5a3e62b73c7c27e3124
  local_head_at_l3_replay_event_proof_projection_slice: 515f1817e8c7fabf9c594b96ed044018eaefbc6f
  local_head_at_l6_freeze_manual_gap_event_proof_enforcement_slice: 604851eca5df99de1e0c9a3b51576037c8a3c93b
  local_head_at_l3_l5_multi_turn_provider_speech_orchestrator_slice: 3c8b17eb433a5536899ca8936c545323da1ee1ab
  local_head_at_l6_multi_turn_freeze_lineage_slice: 4d9e5ef9f9404813e337038409138448e70495da
  local_head_at_l7_graph_native_dispatch_authority_slice: 91500e4d852e07bacf4ed4ff00e9aa7ef0bd2f71
  local_head_at_l7_blueprint_proof_status_lineage_slice: 3251134b63f886758559a27d80393e9543ac3c80
  local_head_at_l7_lanedag_graph_set_status_bridge_slice: a9644c58fd3b0ef1b7d02cd95b703fd1a3344938
  local_head_at_l9_review_intake_graph_status_gate_slice: 60d233c5758c63a2a31a2c2b3d78e62559971a29
  local_head_at_l9_review_verdict_graph_status_sync_slice: e2596cbbb6111b4d2c00523956fe878d5369ea04
  local_head_at_l9_review_closure_graph_status_gate_slice: 1431e64b78dacbca0a3cec224a1cd047c857b35b
  local_head_at_l10_multi_turn_provider_speech_release_lineage_slice: 1284b3d1c52042e5cf82d892b07323aad96c1bc3
  local_head_at_l10_runtime_closure_memoryos_candidate_source_ref_slice: 3f75c0dceca2743de03a1fffb37a032f1aa58784
  local_head_at_l8_runner_candidate_recovery_gate_slice: 2007e7e42370881245adaf7a8fb351cf04d2df29
  local_head_at_l8_runner_supervisor_recovery_projection_slice: 48c49906d3493b91790d9f85cf8fab020e0e5dce
  local_head_at_l8_runner_loop_recovery_local_proof_slice: 6c9cb329ff5a839b7632d324982073b64ce51491
  local_head_at_l3_l5_provider_backed_deliberation_event_capture_slice: 4badeb6b4764e5633bbd68b4cbfe385dc8e98943
  local_head_at_l6_provider_backed_event_lineage_freeze_slice: 1566e657d8548d3627eed22dfd6b013d16fba1cf
  local_head_at_l7_l10_freeze_source_event_lineage_carry_slice: aff7607052bb4dd4f017b84ae728dc73f57a0995
  local_head_at_l7_l10_graph_status_source_event_lineage_carrier_slice: a47e5ba657cc1e307cbcb2b5dadb521852232a99
  local_head_at_l8_runner_recovery_proof_artifact_slice: b122394186a697a2512fd23f9bb90ea70db41273
  local_head_at_l9_runner_recovery_proof_lineage_consumer_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_local_execution_candidate_producer_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_default_graph_status_candidate_producer_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_proof_capture_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_closure_auto_chain_proof_handoff_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_platform_runner_candidate_handoff_proof_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_shared_review_handoff_gate_refactor_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l10_github_server_truth_refresh_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l10_github_server_truth_artifact_consumer_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l10_release_pack_review_chain_proof_aggregation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_durable_second_step_session_evidence_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_upstream_session_artifact_validation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_session_semantic_cross_link_validation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_patch_forward_lane_contract_validation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_patch_forward_source_gap_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_reviewer_independence_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_graph_status_source_lineage_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_review_intake_graph_status_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_candidate_graph_status_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_candidate_artifact_ref_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_embedded_candidate_lineage_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_review_chain_bounded_session_consumer_gate_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_chain_runner_recovery_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_runner_session_empty_candidate_proof_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_direct_review_closure_runner_session_handoff_gate_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_review_chain_current_handoff_consumer_revalidation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_review_closure_candidate_producer_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_runner_recovery_graph_scope_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_review_chain_release_linkage_summary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_platform_runner_candidate_graph_status_reviewability_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_graph_native_worker_evidence_producer_handoff_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_worker_evidence_bundle_verdict_chain_citation_boundary_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_patch_lane_graph_native_worker_evidence_producer_coverage_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_worker_evidence_bundle_release_source_ref_aggregation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_review_chain_source_event_lineage_source_ref_aggregation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l9_l10_direct_review_closure_current_handoff_revalidation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l10_review_chain_release_linkage_source_ref_gate_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l10_runtime_closure_memoryos_handoff_revalidation_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_overnight_supervisor_recovery_gate_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_orchestrator_gate_failure_recovery_artifact_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_review_patch_forward_recovery_artifact_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_review_rejection_recovery_artifact_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_merge_failure_recovery_artifact_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_review_retry_recovery_artifact_slice: 654b418c52cc1487193561f65e0521a5a82f0452
  local_head_at_l8_l9_l10_closure_controller_contract_slice: b050d534873594466e46190619ab20387427f231
  local_head_at_l8_shared_recovery_writer_consolidation_slice: b050d534873594466e46190619ab20387427f231
  local_head_at_x3_review_chain_closure_reconciler_handoff_slice: d4ea5c4020ef6b25c9526587925d0a6f520cb51b
  local_head_at_x3_release_handoff_candidate_ref_revalidation_slice: 0e09f27ff0614da31fb8ca3e7d45cf193d55ebf3
  local_head_at_x3_closure_object_stable_ref_admission_slice: 875547f1c4a76615a068fc17580aaafa7357b84a
  local_head_at_x3_closure_object_owner_lineage_admission_slice: 955ebd56330a9fea61fed40c430b0dc9aeca5bb3
  local_head_at_x3_closure_object_owner_ref_projection_slice: e818f52ec434aed0042eee8cf6c169683ecb2d7b
  local_head_at_x3_closure_object_complete_condition_admission_slice: 1a02f7acb5ebc0ecadbce9b73dabc9f7733e2206
  local_head_at_x3_release_gate_digest_refs_preservation_slice: bcc49d1caf6548f56cdf69c73d20619563ff1085
  local_head_at_x3_release_readiness_forbidden_claim_projection_slice: 5220369bcf8da7f9a834159956669dce0d42c180
  local_head_at_x3_github_release_gate_forbidden_claim_producer_slice: 709008aff94a56ef88db38a78d78d9347003db56
  local_head_at_x3_github_release_gate_model_admission_slice: 6cd34fcff8dd75ec9e2465d404095ae4e97d7dc0
  local_head_at_x3_memoryos_live_gate_source_ref_boundary_slice: cf6bd548fcf75c4374ed95ff5c800b290a01ed90
  local_head_at_x3_patch_forward_lineage_scope_admission_slice: cafb4b49cdf8f562b64c94950382cb8a3e9318da
  local_head_at_x3_patch_forward_lineage_review_closure_ref_admission_slice: 365d956307e37575054d89f3aa3fc384db968be8
  local_head_at_x3_validated_execution_candidate_worker_bundle_admission_slice: e56c9c3a8f19011f2f4ee8e9e14c3d9942562e11
  local_head_at_x3_review_chain_runner_session_worker_bundle_admission_slice: c729c5c79a8e45ed45bf68cc18bb67a920cdac68
  local_head_at_x3_terminal_review_worker_bundle_citation_admission_slice: 20fdc0a0a3409c7a121d8de83bb7228b9e987e1d
  local_head_at_x3_review_chain_l10_worker_bundle_citation_status_admission_slice: 9f429e25bc6bcdf776e09790d75ef13cb555a3b5
  local_head_at_x3_release_linkage_bounded_current_handoff_admission_slice: 60c8b755ea7b98cb99a87347d07a55305ad13988
  pr: 43
  pr_url: https://github.com/iiyazu/Cross-Muse/pull/43
  pr_state: draft_open_unmerged
  merge_state: CLEAN
  review_decision: empty
  verified_ci_head_at_slice_start: b154021111400863098f11ed98eeb24d6fad9311
  verified_ci_run_at_slice_start: 27607281313
  ci_verified_for_slice_start_head: true
  local_changes_after_verified_head: true
  local_github_server_truth_refresh:
    capture_mode: opt_in_read_only_gh_api
    artifact_path: /tmp/xmuse-github-truth-current.json
    release_gate_artifact_path: /tmp/xmuse-github-truth-gate-current.json
    truth_proof_level: manual_gap
    gate_proof_level: server_side_enforcement_proof
    pull_request_state: open
    draft: true
    mergeable_state: clean
    head_sha_matches_expected: true
    required_check_truth_captured: true
    branch_protection_truth_captured: true
    can_emit_pr_merged: false
    gap_reason: "missing server-side truth: review_truth, merge_truth"
  pr_merged_claim_allowed: false
```

Evidence boundaries:

- No `pr_merged` claim is valid until GitHub server-side merge proof exists.
- OpenCode remains a bounded worker unless a later contract and live proof
  explicitly upgrade it.
- TUI/dashboard/read models are operator surfaces and projections, not durable
  state authority.
- `feature_lanes.json`, Ray actor memory, LangGraph nodes, provider subprocess
  state, and runtime artifacts are not authoritative lane status.
- MemoryOS evidence is governed plan/artifact proof unless a configured live
  MemoryOS service trace is captured.
- Speaker response capture is real-provider evidence only when backed by a
  server-loaded provider response artifact and a durable GOD room
  provider-backed appended event present in room replay evidence.

## Dependency-First Layer Map

| Layer | Name | Contract state | Runtime state | Server truth state | Allowed claim |
|---|---|---|---|---|---|
| L1 | Authority / Boundary Model | Partly documented | Enforcement uneven | Not server-bound | Boundary policy exists, not global enforcement |
| L2 | GOD Identity / Provider Binding | Durable account/profile/room binding contract and store exist | Speaker attempt/capture consume binding fail-closed; one isolated Codex L4/L5 live route consumed binding | Not server-bound | L2 contract proof; bounded worker/provider inventory only |
| L3 | GOD Room Durable Event Runtime | Durable event contract/store exists | Single-turn opt-in live Codex L4/L5 route appended and replayed one `speak` event; bounded multi-turn API can append/replay multiple L5-gated `speak` events; live natural multi-GOD proof still missing | Not server-bound | Durable room contract proof plus isolated opt-in live speak replay proof and bounded multi-turn orchestration contract proof |
| L4 | Speaker Selection / Provider Invocation | Selection/attempt evidence plus provider invocation artifact producer contract exist | Core/API producer emits response artifacts, fail-closed artifacts, one verified local opt-in live Codex artifact through execution worktree, and multiple artifacts when driven by the bounded multi-turn route | Not server-bound | Provider invocation artifact contract/fail-closed proof plus isolated Codex opt-in live proof |
| L5 | Speaker Response Capture / Replay Proof | Artifact-backed capture plus composed L4-to-L5 route exists | Rejects contract-only L4 artifacts; appends/replays only server-written real-proof artifacts; one local opt-in live Codex artifact was captured into durable replay; bounded multi-turn route stops on manual_gap and preserves prior durable events | Not server-bound | Capture/replay contract proof plus isolated Codex opt-in live capture proof and bounded multi-turn capture orchestration proof |
| L6 | Blueprint Freeze Authority | Typed freeze artifact exists with proof-level classification and source event lineage | Single-turn provider-backed speech plus provider-backed question/challenge/handoff event proofs and bounded multi-turn L3-L5 run lineage can feed freeze artifacts while preserving durable event authority; fresh natural multi-GOD freeze still missing | Not server-bound | Freeze contract proof plus isolated opt-in live freeze proof, provider-backed event lineage proof, and bounded multi-turn lineage proof |
| L7 | Feature / LaneDAG Authority | LaneDAG/contract artifact exists with upstream freeze proof metadata, source event lineage, and graph-set/status initialization contract | Live L4/L5/L6 proof metadata and structured freeze source-event lineage can flow into laneDAG without writing `feature_lanes.json`; laneDAG route now derives graph-set artifacts and initializes graph-native status records with inherited `blueprint_proof_level` and `source_event_lineage`; `FeatureGraphStatusStore` preserves existing lineage and rejects conflicting rewrites; `graph_set_id`-backed orchestrator dispatch/review/reprojection now fail closed when durable graph-native status is missing; full dispatch/review authority still not unified | Not server-bound | LaneDAG contract proof plus isolated opt-in live upstream-proof propagation, structured freeze lineage carrier proof, graph-native proof/source-event-lineage carrier proof, laneDAG-to-status initialization proof, and graph-native missing-status fail-closed proof |
| L8 | Lane Runtime Enforcement / Recovery | Recovery contract/API exists and recovery artifacts carry laneDAG proof lineage | Recovery API consumes laneDAG contract/budget and preserves blueprint proof/source refs plus laneDAG `source_event_lineage`; GOD-room review intake and orchestrator dispatch now fail-close non-retry recovery decisions; review intake now also requires graph-native `REVIEWING` status from `FeatureGraphStatusStore`; platform runner can emit a local recovery proof artifact from candidate selection plus shared run-health recovery state; broader live runner enforcement still incomplete | Not server-bound | Recovery policy proof plus laneDAG-lineage/source-event-lineage evidence proof plus review-intake/dispatch enforcement proof plus local runner recovery artifact proof |
| L9 | Execution / Review / Patch-Forward | Review plane plus GOD-room review intake/verdict/patch-forward/closure artifact contracts exist | GOD-room lane contracts/recovery/candidate evidence can be packaged for independent review only after graph-native status is `REVIEWING`; review intake carries `source_event_lineage` from graph-native status, can auto-discover valid runner-emitted graph-status-bound local execution candidates only when their current status and `FeatureGraphArtifactStore` evidence bundle match the platform-runner worker session, and preserves missing/invalid candidates as manual gaps; patch-forward now gives the patch lane its own lane runtime `feature_id`, updates graph-set/status authority for that patch feature, and initializes the patch feature graph to `READY` so the platform-runner worker-evidence producer can advance the patch lane through READY -> RUNNING -> REVIEWING instead of reusing the failed lane's REVIEWING feature graph; patch-forward carries lineage from laneDAG, and reviewed patch-lane closure carries it from `FeatureGraphStatusStore` `MERGED` authority; merge/rework/blocked verdicts now consume graph-native review coordinator authority and update `FeatureGraphStatusStore`; patch-forward verdicts record graph-native gate plans without writing lane status; patch-forward can append a laneDAG patch lane; review closure can now consume `xmuse.local_runner_recovery_proof.v1` as lineage-only recovery evidence and validates cited graph-status-bound `xmuse.local_execution_candidate.v1` artifacts before L10 handoff; platform runner emits local execution candidate artifacts by default under runtime `work/local_execution_candidates`, but `candidate_only` requires `FeatureGraphStatusStore` lineage and missing lineage degrades to `manual_gap`; platform-runner candidate source refs now include the graph-native worker `FeatureEvidenceBundle` ref when that producer handoff succeeds; candidate artifacts now carry a `producer` boundary, and only `platform_runner_dispatch` can satisfy bounded-session readiness, while `manual_cli_capture` remains generic candidate evidence only; `xmuse.god_room_lane_review_chain_proof.v1` can now validate a review closure, cited local execution candidates, required L8 recovery lineage, and the shared L9/L10 review-closure handoff gate as one contract handoff artifact without importing the L10 aggregator; the review-closure API now writes that chain-proof handoff artifact on the same graph-status-gated closure path, and a separate review-chain-proof API can regenerate it as a second durable operation from the stored review-closure artifact; the chain proof carries a bounded `local_execution_review_session` detail with candidate refs/run ids, producer refs, review verdict refs, patch-forward refs, recovery proof status, runner-recovery boundary status, and upstream session artifact validation for patch-forward, the failed-lane patch-forward verdict, patch-lane intake, and patch-lane verdict artifacts while staying `contract_proof`/`not_server_truth`; the same validation now requires the patch-lane intake to cite closure-selected platform-runner local execution candidate artifacts, the terminal merge verdict to cite both the review intake and closure-selected candidate refs, the terminal patch-lane verdict to preserve and cite its discovered worker-evidence bundle refs, the patch-forward artifact to point at a failed-lane `patch-forward` verdict, and the patch-forward laneDAG link/runtime contract to bind failed lane, patch lane, patch-forward verdict ref, evidence refs, dependency refs, required checks, and patch output refs; graph-wide lane accounting now treats a failed lane with a validated patch-forward terminal lane as superseded rather than requiring the failed lane's graph to merge or carry a separate candidate; missing recovery lineage, escaping, schema-mismatched, scope-mismatched, producer-mismatched, cross-link-mismatched, non-merge/non-patch-forward, invalid patch-forward link/contract, invalid patch-lane graph-status authority, uncited terminal patch-lane worker bundle refs, or proof-inflated upstream session artifacts degrade the chain proof to `manual_gap`; full live execution/review chain and server truth still missing | Not server-bound | GOD-room review/patch-forward closure contract proof plus graph-status-gated review-intake/verdict/closure proof, review-plane/source-event-lineage store lineage proof, L8 recovery-proof lineage-boundary proof, default graph-status-bound local execution candidate producer/validator proof, review-intake candidate discovery proof, platform-runner producer-boundary proof, review-intake worker-evidence-bundle consumer proof, patch-lane graph-native worker-evidence producer coverage proof, terminal patch-lane worker-bundle citation proof, and L9-to-L10 review-chain proof capture/API handoff plus durable second-step/session-detail/upstream-artifact-validation, semantic cross-link, patch-forward lane-contract, and graph-wide superseded-lane accounting contract proof; not server/GitHub truth |
| L10 | MemoryOS / Release Evidence / GitHub Truth | Evidence bundle semantics exist and can index GOD-room review closure handoff plus bounded multi-turn provider speech lineage; release candidates can seed MemoryOS source refs from review closure, review-chain proof, and runtime closure evidence | Runtime closure evidence preserves per-turn L4/L5 refs, appended event ids/types, laneDAG-carried freeze source-event lineage, review-closure-carried graph-status source-event lineage, and review-closure-carried runner recovery proof lineage as contract lineage; `xmuse.review_closure_handoff_evaluation.v1` now gives runtime closure, release candidates, and feature lineage replay one shared evaluation surface for review-closure candidate refs, cited refs, source-event-lineage counts, required forbidden claims, and not-server-truth status; release-evidence candidate reports can consume `xmuse.god_room_lane_review_chain_proof.v1` only as source-ref guidance after validating it remains `contract_proof`/`not_server_truth` and passes the bounded local execution/review session consumer gate; verified worker-evidence bundle refs from the review-chain citation boundary now flow into MemoryOS candidate payload hints, runtime closure replay source refs, and review-chain release-linkage source refs as aggregation lineage only; release-evidence candidate reports can also consume `github_server_side_truth_capture.v1` as existing GitHub server-truth input through the GitHub release gate while recomputing `can_emit_pr_merged`; live MemoryOS trace and live execution/server truth missing | PR open/unmerged; CI truth only for verified remote head; review/merge truth still missing | Replay/readiness proof with explicit gaps plus shared review-closure handoff evaluation and worker-bundle source-ref aggregation proof; not review/server truth |
| L11 | Operator Cockpit / TUI / Overnight Soak | TUI/control slices exist | Complete cockpit/soak missing | Depends on L10 | Operator projection/control proof only |

Current closure audit:

- Overall ledger verdict: valid as a gap ledger, not valid as closure proof.
- Most mature areas: control surfaces, read models, evidence envelopes, and
  claim-boundary governance.
- Least closed areas: natural multi-GOD deliberation, GOD-room-originated
  execution/review, live MemoryOS trace, and GitHub merge truth.
- Wave cursor:
  - Wave A / L1-L2 has contract proof. Do not redo it unless an authority
    bypass regression is found.
  - Wave B / L3-L5 has bounded/opt-in provider-backed speech, capture, and
    replay proof. Do not overread it as natural peer-GOD groupchat.
  - Wave C / L6-L7 carries durable event lineage into freeze, laneDAG,
    graph-set, and graph-native status contracts. Do not overread it as full
    execution authority.
  - Wave D / L8-L9 is the current production focus. L8 now has a local runner
    recovery proof artifact, and L9 can consume it as review/release lineage.
    L9 now also has a local execution candidate capture/validation contract,
    including opt-in platform-runner candidate artifact emission after dispatch,
    and a durable second-step review-chain-proof API that reloads the stored
    review closure and exposes bounded local execution/review session evidence
    without upgrading it beyond `contract_proof` / `not_server_truth`.
    The chain proof now also reloads patch-forward, patch-lane intake, and
    patch-lane verdict artifact refs from the closure and fail-closes dangling
    refs, scope mismatches, non-merge terminal verdicts, and proof inflation.
    It additionally validates semantic cross-links across the bounded session:
    the patch-forward artifact must point at a failed-lane `patch-forward`
    verdict, the patch-lane intake must include closure-selected local
    execution candidate artifacts, and the terminal merge verdict must cite
    both the review intake and closure-selected candidate refs.
    The same chain proof now also validates the patch-forward laneDAG link and
    patch-lane runtime contract: failed lane and patch lane ids, patch-forward
    verdict ref, evidence refs, dependency refs, required checks, and patch
    output refs must remain aligned or the bounded session stays `manual_gap`.
    It also records the patch-forward artifact's source `manual_gaps` and
    `forbidden_claims`, explicitly marking `patch_lane_not_executed` and
    `patch_lane_not_reviewed` as resolved only when downstream patch-lane
    candidate/intake/verdict evidence validates, while keeping
    `release_evidence_not_linked` as a retained gap for L10.
    The bounded session now also checks terminal patch-lane review
    independence by comparing the validated verdict `reviewer_id` with cited
    local execution candidate `worker_id`s; missing reviewer identity or a
    reviewer/worker match keeps the chain proof at `manual_gap`.
    The same bounded session now also checks that review-closure
    `cited_candidate_artifact_refs` exactly match the resolved valid
    `xmuse.local_execution_candidate.v1` lineage artifact refs, and the shared
    L9/L10 handoff gate rejects unresolved or undeclared candidate artifact refs.
    This prevents L10 source-ref aggregation from consuming a partially resolved
    candidate list while remaining `contract_proof` / `not_server_truth`.
    It now also checks closure-embedded `cited_candidate_artifact_lineage`
    against freshly resolved local execution candidate lineage before the chain
    proof or shared handoff gate can become ready. This prevents a stale or
    forged embedded lineage block from being overread by downstream consumers
    while still remaining artifact-local `contract_proof`.
    L10 MemoryOS candidate and runtime-closure consumers now also require a
    shared review-chain bounded-session gate before accepting a chain proof as
    source-ref aggregation. That gate requires
    `local_execution_review_session` to be `bounded_session_ready`, artifact
    validation, session-scope, graph/candidate/reviewer boundaries to be
    verified, and session candidate refs to match the release handoff,
    candidate-lineage, candidate-boundary, and session artifact refs. A
    hand-written `chain_ready` proof without this bounded session stays
    `manual_gap`; this is still contract-proof consumer hardening, not live
    review/server truth.
    L10 MemoryOS candidate and runtime-closure consumers now also re-derive the
    current review-closure handoff from the chain proof's `review_closure_artifact`
    before accepting source-ref aggregation. If the current runner-session or
    candidate lineage no longer validates, or if current candidate refs diverge
    from the embedded handoff refs, the chain proof stays out of L10 source refs.
    This prevents stale embedded handoff data from being treated as current L9
    authority while remaining contract-proof aggregation only.
    The bounded session now includes
    `xmuse.local_execution_review_session.v1` plus
    `xmuse.local_execution_review_session_scope_boundary.v1`, carrying a stable
    session id, graph/failed-lane/patch-lane scope, runner-emitted local
    execution candidate refs, L8 recovery proof refs, patch-forward/review
    artifact refs, and session source refs. Missing session artifact/source
    refs keeps the proof out of L10 source-ref aggregation.
    The chain proof now also carries a `runner_recovery_lineage_boundary` and
    treats L8 recovery lineage as required for `chain_ready`: missing recovery
    proof, unreadable recovery proof `artifact_ref`, unsupported lineage schema,
    missing or unreadable durable source refs, missing target refs, missing
    failed-lane target ref, missing forbidden claims, or missing review/server/
    overnight manual gaps keep the chain proof at `manual_gap`.
    Review closure may still be written with `runner_recovery_proof_not_linked`,
    but it cannot be overread as a complete L8-L9 chain or L10-ready handoff.
    Gate failure, review retry, retry exhaustion, review rejection,
    patch-forward original-lane suspension, and merge-failure recovery
    production now use one shared writer-side durable recovery artifact helper
    in `orchestrator_lane_flow.py`. The covered branches still make explicit
    `retry`, `refactor_required`, or `suspended` decisions, retry decisions
    remain non-blocking, and non-retry decisions are read by the existing same
    durable dispatch gate. Missing graph/lane authority remains `manual_gap`,
    and recovery artifacts preserve `independent_review_truth`, `server_truth`,
    `overnight_safe_recovery`, `ready_to_merge`, and `pr_merged` as forbidden
    claims. This is L8 writer consolidation contract/local authority proof only;
    it does not create L9 independent review truth or L10 release/server truth.
    Release evidence pack now emits
    `xmuse.god_room_review_chain_release_linkage.v1` as a top-level aggregation
    summary when a review-chain proof is supplied. It records whether the
    chain proof was actually indexed into the GOD-room runtime closure replay
    source refs, marks `release_evidence_export_not_attempted` and
    `release_evidence_not_linked` as resolved only for that pack when linked,
    retains server/MemoryOS/GitHub gaps, and explicitly says it does not affect
    pack readiness or create server truth.
    The linkage emits chain `source_refs` only after the review-chain proof is
    actually linked through runtime-closure replay source refs, bounded session
    gate, and current review-closure handoff. When linkage stays `manual_gap`,
    unrelated GOD-room/provider refs already present in the same replay section
    are not copied into review-chain linkage source refs.
    L10 MemoryOS candidate reports now also revalidate runtime-closure evidence
    that carries review-closure or review-chain lineage before copying its
    `source_refs` into MemoryOS payload hints. Provider-only runtime replay refs
    can remain candidate hints, but stale review-closure candidate/session
    lineage keeps the runtime-closure candidate gate not-ready. The
    review-chain proof candidate gate now uses the L9 review-chain forbidden
    claims constant instead of a hand-written subset, preventing L10 from
    accepting proof artifacts that dropped end-to-end/reviewer-boundary
    forbidden claims.
    Overnight supervisor stage start now runs a durable recovery preflight gate
    over runtime `lane_graphs/*.recovery.json` artifacts. Non-retry
    `refactor_required`/`suspended`/`manual_gap` decisions or invalid recovery
    artifacts produce blocked supervisor evidence and prevent the stage from
    starting, while preserving `manual_gap` and forbidden claims instead of
    claiming overnight-safe recovery.
    Platform-runner runner-session artifacts now also record worker-evidence
    bundle refs produced during that runner invocation. The L9 review-chain
    runner-session boundary compares candidate `feature_evidence_bundle:*`
    source refs against the runner-session bundle refs; a candidate that cites
    a worker bundle not recorded by its runner session keeps the chain proof at
    `manual_gap`. This binds worker-bundle citation to the runner-session
    authority path without making the bundle, local runner output, or local
    tests independent review truth.
    Platform-runner local execution candidate capture now requires
    graph-native status lineage to be `reviewing` before the candidate can be
    recorded as `candidate_only` / `local_runtime_proof`; READY/RUNNING or other
    pre-review statuses produce a `manual_gap` with
    `graph_native_worker_evidence_not_submitted` and
    `local_execution_candidate_not_reviewable`. Runner sessions no longer count
    those manual-gap candidate artifacts as runtime-proof candidate refs, so a
    dispatch-return artifact cannot be mistaken for review-ready L9 execution
    proof before graph-native worker evidence moves the lane to review intake.
    Platform runner now has a bounded graph-native worker-evidence producer
    handoff: after `dispatch_lane` returns, it can claim a READY
    `FeatureGraphStatusStore` record into RUNNING for the current
    `runner_session_id`, build a `FeatureEvidenceBundle` from current lane
    metadata plus status-store authority, and submit it through the existing
    worker-evidence coordinator to move the graph status to REVIEWING before
    local execution candidate capture. This path requires a real
    `provider_session_binding_ref` / `provider_session_binding_id`,
    `planning_run_id`, `blueprint_refs`, `acceptance_criteria`, and
    `required_checks`; missing prerequisites leave the existing candidate
    path at `manual_gap`. The proof is local runtime / contract handoff only
    and still does not create independent review truth, GitHub truth,
    MemoryOS live proof, merge truth, or broad live worker closure.
    GOD-room review intake auto-discovery now consumes that producer handoff:
    a platform-runner local execution candidate is auto-added as reviewer input
    only when its embedded graph-status lineage matches the current
    `FeatureGraphStatusStore` record and a matching
    `FeatureGraphArtifactStore` `FeatureEvidenceBundle` for the same
    runner-session/provider-binding/completed-lane is present and cited by the
    candidate source refs. Missing bundle/current-status lineage keeps the
    candidate out of auto-discovery and preserves
    `worker_candidate_evidence_missing`. Independent review verdicts now
    fail closed when such discovered worker-evidence bundle refs are not cited
    in `evidence_refs`, then carry
    `worker_evidence_bundle_citation_status=verified` plus the intake
    `xmuse.local_execution_candidate_worker_evidence_boundary.v1` payload into
    the verdict artifact. Patch-forward artifacts propagate the source verdict
    bundle citation fields, and the L9 review-chain proof now requires
    `xmuse.worker_evidence_bundle_citation_boundary.v1` in the bounded session
    gate so missing or mismatched bundle citation keeps the chain at
    `manual_gap`. This remains contract/API handoff proof only; patch-lane
    bundle producer coverage and broad live worker execution/review proof
    remain later work.
    `src/xmuse_core/platform/closure_objects.py` and
    `src/xmuse_core/platform/closure_reconciler.py` now add a minimal
    Kubernetes-inspired controller contract over the existing L8/L9/L10
    artifacts. It separates `spec` from observed status, emits machine-readable
    conditions for
    `RecoveryArtifactPresent`, `RecoveryAllowsProgress`,
    `ValidatedExecutionCandidatePresent`,
    `IndependentReviewVerdictPresent`, `ReleaseHandoffEvaluated`, and
    `ServerTruthPending`, preserves inherited forbidden claims, and fail-closes
    missing artifacts/schema/owner lineage to `manual_gap` or `blocked`. This is
    controller `contract_proof` only; it does not add a service, queue, DB,
    TUI/release truth surface, live MemoryOS trace, GitHub review/merge truth,
    or broad live execution/review closure.
  - The x3 freshness/admission hardening slice extends the same closure object
    contract with `generation`, `observed_generation`, and
    `evaluator_version` metadata, plus `ClosureControllerFresh` and
    `RequiredForbiddenClaimsPresent` conditions. `reconcile_closure` can now
    consume a previous serialized `ClosureObject`: stale evaluator versions and
    generation regressions block, while generation skips remain `manual_gap`.
    L10 release-evidence candidate discovery can now consume a supplied
    `ClosureObject` artifact as a controller-facing provenance surface: only a
    current evaluator, fresh controller condition, preserved required forbidden
    claims, and pending server-truth boundary may seed MemoryOS source-ref
    hints. The `xmuse-release-evidence-candidates` CLI now exposes the same
    path through `--closure-object`, so this controller-facing input is usable
    from the operator/reporting entry point instead of only internal Python
    callers. Stale/blocked closure objects remain candidate blockers and do not
    enter source authority.
    The L10 ClosureObject admission check is now owned by the shared closure
    object contract instead of being reimplemented in the release-candidate
    projection. The review-chain proof consumer also uses the shared
    review-closure handoff artifact loader/evaluator for its
    `review_closure_artifact` ref, reducing duplicated L9/L10 handoff loading
    without changing the proof level.
    Review/release handoff artifacts that omit required inherited claims such as
    `live_memoryos`,
    `github_review_truth`, `ready_to_merge`, `pr_merged`, or
    `worker_output_is_review_truth` now remain `manual_gap` instead of being
    silently repaired by status aggregation. This is still controller
    `contract_proof`; it does not close live MemoryOS, GitHub review truth,
    merge truth, or end-to-end Wave D/E runtime closure.
    The shared L9/L10 handoff evaluator now also owns release-handoff to
    review-closure graph/lane scope admission. `closure_reconciler` consumes
    that shared result instead of carrying a private scope check, so stale or
    cross-lane release handoff artifacts fail closed consistently before
    `ReleaseHandoffEvaluated` can become true.
    The same shared evaluator also checks closure-level required forbidden
    claims on otherwise well-scoped release handoffs, so inherited gaps such as
    `live_memoryos` and `github_review_truth` cannot be dropped by a downstream
    handoff consumer.
    `xmuse.release_evidence_candidates.v1` may only be treated as a closure
    handoff candidate when it is explicitly scoped to the current graph/lane and
    carries source refs plus inherited forbidden claims; otherwise it remains a
    downstream aggregation surface and fails closed.
    Runtime closure evidence now consumes the shared review-closure handoff
    evaluator issues for schema/proof/review/execution/server/forbidden-claim
    admission instead of reimplementing those checks locally. It still performs
    only runtime-closure-specific checks such as preserving
    `release_evidence_not_linked`.
    The API-generated `xmuse.god_room_lane_review_chain_proof.v1` artifact now
    also carries top-level `source_refs`, `source_ref_count`, and `target_refs`
    derived from its review closure, bounded session, local execution
    candidate, runner recovery proof, and shared handoff evaluation. This lets
    `closure_reconciler` evaluate the same review-chain artifact as the
    `ReleaseHandoffEvaluated` input instead of treating it as a source-ref gap.
    The focused API integration proof reaches `release_handoff_evaluated` only
    for artifact-local `contract_proof` while preserving `ServerTruthPending`
    and inherited forbidden claims such as `worker_output_is_review_truth`,
    `live_memoryos`, `github_review_truth`, `ready_to_merge`, and `pr_merged`.
    The same focused proof now writes that reconciled ClosureObject artifact
    and feeds it into the release-evidence candidate MemoryOS guidance path;
    L10 accepts it only as `closure_object_artifact` source-ref guidance with
    `candidate_report_is_not_live_memoryos_proof`, not as a live MemoryOS trace
    or release/server readiness signal.
    The shared release-handoff gate now also revalidates declared candidate
    artifact refs against the controller root when a root is supplied, so a
    stale or copied chain proof with unresolvable candidate refs keeps
    `ReleaseHandoffEvaluated` at `manual_gap` instead of entering L10
    provenance guidance.
    ClosureObject L10 admission now also requires non-empty stable
    `source_refs`, `target_refs`, and `owner_refs`; otherwise the object
    remains not gate-ready and cannot seed MemoryOS provenance hints. This
    keeps a fresh controller condition set from becoming L10 guidance when
    lineage or owner authority is empty.
    Release-evidence candidate reports now expose the admitted ClosureObject
    owner-ref count alongside source-ref and forbidden-claim counts, so
    operators can see that L10 guidance came from owner-linked closure lineage.
    This is provenance visibility only and does not create a new truth owner.
    ClosureObject L10 admission now also requires the complete desired
    condition chain for the default
    `Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff`
    controller path. A hand-built object that only carries a few positive
    guard conditions is no longer enough to seed MemoryOS provenance hints.
    Admitted ClosureObject candidates now expose target refs and target-ref
    counts alongside source/owner/forbidden-claim counts, and the MemoryOS
    candidate payload hints preserve those target refs as scope hints only.
    This remains `contract_proof`/provenance projection; it does not create
    live MemoryOS proof, GitHub review truth, merge truth, or production
    release readiness.
    Release evidence pack gate digests now preserve machine-readable
    `source_refs`, `target_refs`, `owner_refs`, and `forbidden_claims` from the
    release readiness gate model instead of retaining only counts. Missing
    fields remain empty lists and are not inferred from projection state. This
    prevents the L10 aggregation artifact from stripping scope/claim guardrails
    that upstream gate artifacts already produced, but it does not make a gate
    ready or upgrade any proof level.
    Release readiness reports now also carry a non-blocking
    `forbidden_claims` summary plus per-gate forbidden-claim entries, and the
    release evidence pack projects that summary at top level. This preserves
    the existing meaning of `release_readiness_decision=ready` as gate readiness
    while keeping claims such as `ready_to_merge` or `pr_merged` visibly
    forbidden unless a stronger server-side proof removes them.
    The GitHub server-truth release gate now produces the `pr_merged`
    forbidden claim itself unless the validated
    `GitHubServerSideTruthEvidence` satisfies `can_emit_pr_merged()`. This keeps
    a branch-protection/check-run enforcement gate from being overread as merge
    truth even when release readiness for that gate is otherwise `ready`.
    The same gate now also derives `server_side_enforcement_proof` admission
    from `GitHubServerSideTruthEvidence.has_status_check_truth` and
    `.has_server_enforcement_truth` instead of a wider raw-dict check. Missing
    workflow/check-run lineage therefore stays `manual_gap` and keeps
    `pr_merged` forbidden.
    The MemoryOS live release gate now rejects trace artifacts whose source
    refs are only MemoryOS refs (`memoryos:` or `memory://...`) and requires at
    least one non-MemoryOS upstream xmuse source ref before live trace proof can
    be release-gate `ok`. Blocked MemoryOS gates explicitly carry
    `forbidden_claims=["live_memoryos"]`; successful live service proof drops
    that forbidden claim without making MemoryOS an authority for L8/L9 truth.
    Closure-controller and review-handoff regression tests now share a small
    fixture builder that produces candidate, runner-session, review-closure,
    and review-chain payloads through the production capture/build helpers. This
    reduces test-private schema drift but does not change runtime proof level.
  - The x3 Goal B controller-facing slice adds
    `PatchForwardLineagePresent` and keeps it `manual_gap` unless a
    `xmuse.god_room_lane_review_chain_proof.v1` artifact proves a
    `chain_ready` bounded local execution/review session with validated
    patch-forward artifact, patch-lane review intake, and patch-lane review
    verdict refs. Plain review-closure handoff evaluation artifacts can still
    prove handoff readiness, but they cannot be overread as patch-forward
    lineage. The reconciler also now accepts the production orchestrator
    `xmuse.god_room_lane_recovery.v1` artifact in addition to
    `xmuse.local_runner_recovery_proof.v1`: `retry_allowed=true` allows
    progress, while `retry_allowed=false` blocks progress. This repairs the
    producer/consumer schema gap without upgrading recovery, worker output, or
    local tests into review truth.
    The review-chain proof L10 handoff evaluation now explicitly projects the
    patch-forward artifact, patch-lane review intake artifact, and patch-lane
    review verdict artifact refs, and the release-evidence candidate report
    carries those refs as provenance/source-ref hints instead of leaving L10 to
    infer them from generic source refs. The
    `xmuse-god-room-review-chain-proof-capture` CLI can also write an optional
    ClosureObject via `--closure-object-output`, using the captured chain proof
    as the release handoff input and preserving `ServerTruthPending` /
    forbidden claims. The release-evidence export operator-service action can
    now also run the same review-chain proof capture from a stored
    review-closure artifact and optionally emit the ClosureObject, so the path
    is no longer CLI-only; incomplete review closure without the chain proof remains
    `manual_gap`. This is still single-lane controller `contract_proof`; it
    does not make the chain live/server truth or prove all L9 closure.
  - The x3 Goal D MemoryOS trace hardening slice keeps MemoryOS as an opt-in
    L10 provenance/trace adapter. `xmuse.memoryos_lite_trace.v1` artifacts now
    carry an explicit `trace_id` and `target_refs`; the live MemoryOS release
    gate requires that `trace_id` and at least one non-`memoryos:` upstream
    `source_ref` before accepting `live_service_proof`, and the release
    candidate projection exposes trace id/source-ref/target-ref counts only as
    projection data. GOD-room MemoryOS plans, source refs, runtime-closure
    hints, and candidate reports remain provenance/guidance and do not become
    live MemoryOS proof without a gate-ready trace artifact.
  - The x3 Goal C GitHub truth hardening slice moves PR-head freshness upstream
    into `GitHubServerSideTruthEvidence` / `GitHubServerSideTruthSnapshot` and
    `can_emit_pr_merged()`. A supplied `expected_head_sha` now propagates through
    the read-only collector, CLI capture, live-gate status capture, and release
    evidence export actions. Stale `head_sha != expected_head_sha` blocks
    `pr_merged` emission even if all review/check/merge structural fields are
    present. The GitHub release gate now emits a structured `github_truth`
    head-freshness detail, and release candidates / release packs project that
    gate detail instead of trusting raw artifact self-report fields such as
    `head_sha_matches_expected`.
  - Wave E / L10-L11 must wait for honest L8-L9 lineage before claiming
    release readiness, complete cockpit, or overnight proof.
- Next production priority: prove a graph-native GOD-room-originated lane
  through local execution, independent review, patch-forward, and
  release-evidence linkage while carrying L8 recovery proof lineage and without
  inflating worker output, local tests, recovery artifacts, CI, MemoryOS plans,
  or TUI projections into review/server truth.

## L1 - Authority / Boundary Model

- Dependency role:
  - This layer defines which component may create or mutate authoritative
    production state. All later layers depend on this boundary.
- User-visible promise unlocked:
  - The operator can trust that status, readiness, and recovery claims come
    from durable contracts or server truth, not from a convenient UI panel,
    queue file, actor memory, or provider subprocess.
- Current implemented evidence:
  - Mainline docs distinguish graph-set/lane graph/review plane/GitHub checks
    from projections such as cards, dashboard, TUI, and `feature_lanes.json`.
  - Package boundary tests enforce that `xmuse_core` does not import runtime
    `xmuse/` or `memoryos_lite`.
  - Development policy states Ray actors, LangGraph nodes, provider subprocess
    state, and TUI projections are not durable authority.
- Missing production closure:
  - Enforcement is not yet uniformly present across every runner, supervisor,
    dashboard, TUI action, and evidence capture path.
- Proof required to close:
  - A boundary audit showing every mutating path writes through approved
    contracts/stores and every projection/control surface refuses to bypass
    those contracts.
- Current risk:
  - Downstream work can accidentally make a projection look authoritative.
- Next production slice:
  - Add an authority-boundary audit for mutating TUI/API/runner paths and mark
    any bypass as `manual_gap` or `refactor_required`.
- Downstream blocked until:
  - L2-L11 can be built in slices, but none may claim production authority if
    they rely on projection state.
- Do not claim yet:
  - Do not claim all runtime status authority is fully centralized.

## L2 - GOD Identity / Provider Binding

- Dependency role:
  - Real GOD room runtime requires registered GOD identities, registered
    provider/account profiles, and room-level selected-GOD bindings before any
    natural deliberation or speaker invocation can be production proof.
- User-visible promise unlocked:
  - The operator can register and choose which CLI/provider acts as a GOD, and
    later evidence can prove which actor produced which response.
- Required authority objects:
  - `ProviderAccount` / `ProviderProfile`:
    - Records usable provider/CLI/account metadata such as `account_ref`,
      `provider_kind`, `auth_type`, `base_url`, `models`, `env_vars_ref`, and
      `credential_ref`.
    - It is provider availability and credential binding metadata. It is not a
      GOD identity and must not be used directly as room speaker truth.
  - `GodProfile`:
    - Records GOD identity and role metadata such as `god_id`, `display_name`,
      `role`, `capabilities`, `constraints`, and `proof_policy`.
    - It does not store secrets and does not directly invoke providers.
  - `RoomSelectedGodBinding`:
    - Records which GODs are selected for a room/session and how each selected
      GOD resolves to an account/CLI/model.
    - Required fields include `room_id`, `binding_revision`, `god_id`,
      `account_ref`, `cli_command`, `model`, `variant`, `proof_level`,
      `selected_by`, and `selected_at`.
    - L3 event authorship and L4 provider invocation must reference this
      binding, not provider inventory, raw environment discovery, naked CLI
      command strings, or TUI temporary state.
- Current implemented evidence:
  - Provider inventory and provider board projections exist.
  - Provider policy/registry modules exist for Codex, OpenCode, and fake
    providers.
  - Current evidence correctly keeps OpenCode as bounded worker, not peer-GOD.
  - `src/xmuse_core/providers/god_identity_binding.py` defines durable
    `ProviderAccount`, `GodProfile`, and `RoomSelectedGodBinding` contracts plus
    `GodIdentityBindingStore` and fail-closed binding resolution.
  - `select_god_cli` can now persist a room-scoped selected-GOD binding through
    operator action contract when `room_id`, `participant_id`, `god_id`, and
    `model` are supplied.
  - Chat API speaker attempt/response paths pass a selected binding resolver, so
    L4 attempt and L5 capture cannot proceed from selected runtime projection
    alone when the room binding is missing or mismatched.
  - L5-generated durable `speak` events now carry binding lineage fields such as
    `binding_revision`, `account_ref`, `cli_command`, `model`, and `variant`.
- Missing production closure:
  - Durable binding authority is currently proven at `contract_proof` through
    JSON store, operator action, resolver, speaker attempt, and capture paths;
    it is also consumed by one isolated local Codex opt-in L4/L5 live speech
    route.
  - Provider inventory/runtime evidence is not yet sufficient to upgrade a CLI
    into a peer-GOD role.
  - Full peer-GOD speech closure still requires the remaining escalation
    conditions below, including non-`speak` deliberation acts and release
    evidence.
- Proof required to close:
  - Durable account/profile/selection artifacts exist and are consumed by GOD
    room speaker selection and provider invocation. Current evidence proves
    selection/attempt/capture consumption at `contract_proof` and one isolated
    Codex opt-in live L4/L5 route.
  - Explicit binding resolution is fail-closed: unresolved `account_ref`,
    incompatible provider/model, missing CLI, or missing proof config produces
    `manual_gap` or `refactor_required`, not fallback environment scanning.
  - For OpenCode/DeepSeek, invocation metadata preserves model and variant as
    separate fields:
    - `cli_command = opencode`
    - `model = opencode-go/deepseek-v4-flash`
    - `variant = max`
    - Never encode `max` into the model id.
- Proof escalation policy:
  - A CLI/provider can be promoted from `bounded_worker` to `peer_god` only when
    all of these are true:
    - `GodProfile` exists with explicit `proof_policy`.
    - `RoomSelectedGodBinding` resolves fail-closed to a `ProviderAccount`.
    - L4 emits a provider speech artifact from that selected binding.
    - L5 captures the artifact into a durable L3 `speak` event.
    - L3 replay proves authored speech with GOD identity and binding revision.
    - At least one `question`, `challenge`, or `handoff` event is produced under
      that identity in the same room lineage.
    - Release evidence records `proof_level=live_provider_god_speech`.
  - Until every condition passes, the CLI/provider remains a bounded worker or
    provider inventory entry, even if it is configured and callable.
- Current risk:
  - Treating a configured worker provider as a selectable GOD without explicit
    role contract and live proof.
  - Letting provider inventory or TUI-selected strings bypass durable selected
    GOD binding in paths not yet audited.
  - Treating L2 `contract_proof` as L4 provider invocation proof.
- Next production slice:
  - Use the isolated L4/L5 Codex live speech lineage as input for L6 freeze or
    L10 evidence while preserving the missing natural multi-GOD and release
    evidence gaps.
- Downstream blocked until:
  - L3-L5 can prove isolated live Codex speech, but natural peer-GOD room
    closure remains blocked until multiple configured GOD acts and release
    evidence exist.
- Do not claim yet:
  - Do not claim OpenCode or any CLI is a peer-GOD solely because it appears in
    provider inventory.
  - Do not claim L2 `contract_proof` as live provider speech or natural GOD room
    closure.

### L2 clowder-ai reference sources

Use these as implementation references, not as xmuse package dependencies:

- Account binding authority:
  - `/home/iiyatu/clowder-ai/packages/api/src/config/cat-account-binding.ts:9`
    shows that `accountRef` becomes authoritative once written to runtime
    catalog and bootstrap/template state must not reinterpret it.
- Provider/account resolver:
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:23`
    defines `RuntimeProviderProfile` without mixing it with member identity.
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:88`
    maps well-known builtin account refs to client families.
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:119`
    resolves a single `accountRef`.
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:159`
    fails closed when an explicit preferred account ref cannot resolve.
- Identity/member config:
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat.ts:15`
    defines CLI client identity separately from provider account metadata.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat.ts:58`
    shows member identity/config fields including `accountRef`, `clientId`,
    `defaultModel`, `cli`, `roleDescription`, and `provider`.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat-breed.ts:34`
    defines reusable CLI invocation config.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat-breed.ts:56`
    shows variant-level account/model/CLI binding.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat-breed.ts:217`
    defines account metadata without secrets.
- Account and member mutation validation:
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/accounts.ts:254`
    creates account metadata and writes credentials separately.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/cats.ts:312`
    validates account binding, provider/model compatibility, and API-key model
    requirements.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/cats.ts:510`
    validates binding before creating a runtime member.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/cats.ts:645`
    resolves effective binding during member updates and validates provider
    config changes.
- Runtime invocation and OpenCode reference:
  - `/home/iiyatu/clowder-ai/docs/decisions/001-agent-invocation-approach.md:24`
    records CLI subprocess + MCP callback as the default agent invocation path.
  - `/home/iiyatu/clowder-ai/docs/decisions/001-agent-invocation-approach.md:64`
    records account-binding fail-closed and governance gates for native
    provider opt-in.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/providers/OpenCodeAgentService.ts:115`
    resolves and invokes the OpenCode CLI as an agent service.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/providers/opencode-config-template.ts:84`
    treats provider name as runtime routing authority for OpenCode API type.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/providers/opencode-config-template.ts:124`
    parses OpenCode `provider/model` format.
- Runtime config boundary:
  - `/home/iiyatu/clowder-ai/docs/decisions/017-no-runtime-home-overwrite.md:23`
    forbids runtime dispatch/invocation from overwriting provider home
    directory config files.

## L3 - GOD Room Durable Event Runtime

- Dependency role:
  - This layer is the durable event substrate for deliberation. Speaker
    runtime, freeze, replay, MemoryOS trace, and TUI projections all depend on
    these events.
- User-visible promise unlocked:
  - GOD discussion is not just chat text; it is a durable, replayable sequence
    of speech acts.
- Current implemented evidence:
  - `xmuse.god_room_event.v1` covers `speak`, `question`, `challenge`,
    `handoff`, and `freeze_requested`.
  - `GodRoomEventStore` persists rooms/events and supports replay/snapshot
    export.
  - Chat API exposes room creation, event append, and snapshot routes.
  - Public Chat API event append now rejects direct `actor_kind=god` `speak`
    events that try to carry provider-backed proof markers such as
    `provider_response_artifact:` source refs, provider invocation refs, or
    L4/L5 capture payload fields. Such attempts return
    `proof_level=manual_gap` and do not write a durable event; provider-backed
    `speak` remains writable only through the L5 capture path that loads the
    L4 artifact server-side.
  - Public Chat API direct append now writes a server-owned
    `public_append_authority` payload for GOD-authored direct events. If
    `RoomSelectedGodBinding` resolves, the payload records
    `proof_level=contract_proof`, binding revision, account/model metadata, and
    binding source refs. If resolution fails, the event remains a
    contract/manual transcript but records `proof_level=manual_gap`,
    `room_selected_god_binding_unresolved`, and forbidden live-proof claims.
    Client-supplied `public_append_authority` is rejected as a reserved proof
    field.
  - A local opt-in live Codex composed route run appended one provider-backed
    `speak` event and returned room replay `ok` from a temp runtime root:
    `/tmp/xmuse-live-l4-l5-uynpv_gj`.
  - `GodRoomReplayResult` now includes `event_proofs`, a projection derived
    from durable `GodRoomEventV1` payload/source refs. It distinguishes public
    append `manual_gap`, public append `contract_proof`, and L5
    provider-backed `opt_in_live_proof` event lineage while keeping the
    room-level replay `proof_level` at `contract_proof` or `manual_gap`. The
    original L4/L5 artifact proof label remains available as artifact lineage,
    not as a room-level closure claim.
  - Chat API now exposes a bounded sequential
    `POST /api/chat/conversations/{conversation_id}/god-room/multi-turn-provider-speech`
    route. The route drives multiple turns only by repeatedly invoking the
    existing L4 provider invocation producer and L5 capture path, reloading
    durable GOD room state between turns and writing a
    `xmuse.god_room_multi_turn_provider_speech_run.v1` evidence artifact under
    `reports/god_room_provider_speech_runs/`.
  - Runtime closure evidence can now index a supplied
    `xmuse.god_room_multi_turn_provider_speech_run.v1` artifact, preserving
    per-turn appended `speak` event ids plus L4 provider-response and L5
    speaker-response artifact refs as lineage only.
  - L5 capture can now append provider-backed `question`, `challenge`, and
    `handoff` deliberation events, not only `speak` events, when a server-loaded
    L4 provider response artifact is `real_provider_proof` and the requested
    event shape is valid. Replay event proof projection classifies these
    provider-backed deliberation events as `opt_in_live_proof` lineage while
    preserving `natural_groupchat_closure` as a forbidden claim.
- Missing production closure:
  - Natural multi-GOD live runtime has not been proven over a long session.
  - The multi-turn provider speech route is bounded sequential orchestration,
    not natural peer-GOD autonomy, distributed groupchat, or overnight runtime
    proof.
  - Public direct append now classifies GOD event authorship through L2 binding
    resolution or explicit `manual_gap`, but this still does not prove fresh
    provider-backed natural deliberation or every non-HTTP writer path.
  - Event proof projection summarizes existing durable event lineage only; it
    does not load or re-verify L4 artifacts and must not be treated as new
    provider invocation proof.
- Proof required to close:
  - A fresh transcript where multiple configured GODs produce durable
    question/challenge/handoff/freeze events through provider-backed runtime.
- Current risk:
  - Contract proof can be mistaken for natural peer-GOD runtime proof.
  - Direct public append remains contract/manual proof only unless backed by
    the L4/L5 provider-capture route.
- Next production slice:
  - Carry provider-backed non-`speak` deliberation events into bounded
    multi-turn/run lineage and freeze/release evidence while preserving the
    natural peer-GOD groupchat and live/server proof gaps.
- Downstream blocked until:
  - L6 blueprint freeze cannot claim live deliberation closure without fresh
    durable room event proof.
- Do not claim yet:
  - Do not claim natural peer-GOD groupchat closure.

## L4 - Speaker Selection / Provider Invocation

- Dependency role:
  - This layer chooses the next speaker and invokes the selected provider/GOD
    to produce a provider response artifact. L5 must consume this artifact; it
    must not fabricate provider output.
- User-visible promise unlocked:
  - xmuse can decide who should speak next and ask the configured GOD/provider
    to respond through a production invocation path.
- Current implemented evidence:
  - Speaker replay decisions are deterministic and recoverable.
  - Speaker attempt evidence joins room replay to selected GOD runtime
    continuity.
  - Speaker attempt/response capture now fail closed through
    `RoomSelectedGodBinding` resolution when the Chat API runtime hook is used.
  - `src/xmuse_core/chat/god_room_provider_invocation.py` now provides the L4
    producer for `xmuse.god_room_provider_speech_response.v1`. It consumes a
    ready `GodRoomSpeakerAttemptV1`, preserves selected binding lineage
    (`binding_revision`, `account_ref`, `cli_command`, `model`, `variant`),
    builds the provider CLI command, records prompt/output refs, timing,
    exit status, raw output digest, failure kind, and proof level.
  - Chat API exposes
    `POST /api/chat/conversations/{conversation_id}/god-room/provider-invocation`
    and writes provider response artifacts under `reports/provider-responses/`
    without appending a durable `speak` event.
  - The bounded multi-turn provider speech route does not create provider
    responses itself. Each turn calls the same L4 producer, so every successful
    turn still has its own `xmuse.god_room_provider_speech_response.v1`
    artifact and fail-closed outcome.
  - The provider invocation API now uses the configured execution worktree for
    provider CLI subprocesses while continuing to write runtime artifacts under
    the xmuse runtime root; this prevents Codex/OpenCode from being launched in
    untrusted state directories.
  - A local opt-in live Codex smoke run through the composed L4/L5 route
    produced a `completed` `real_provider_proof` L4 artifact with command
    `codex exec -m gpt-5.4 -C /home/iiyatu/projects/python/xmuse`, provider
    session id `019ec42d-b245-7d10-b3f8-f511fdceff5f`, and artifact ref
    `reports/provider-responses/conv_b1a9fbccd098460abbb4e9ca84131d3f.evt-live-propose.provider-response-7e7a878796cfeebd.json`
    in temp runtime root `/tmp/xmuse-live-l4-l5-uynpv_gj`.
  - Focused tests cover the contract producer success path, unresolved binding,
    unsupported CLI, missing CLI, nonzero exit, timeout, non-structured output
    as `raw_archive_only`, and L5 refusing to capture contract-only provider
    responses as real provider speech.
  - Correct OpenCode/DeepSeek invocation format is documented:
    `opencode run --model opencode-go/deepseek-v4-flash --variant max ...`.
  - Opencode inline-variant misuse is now fail-closed in the command builder:
    models encoded as `...:max` or `...-max` are rejected with
    `manual_gap`; no subprocess is started and the user is instructed to use the
    separate `variant` field.
- Missing production closure:
  - `allow_live_provider_proof=true` remains opt-in runtime behavior and must
    not be claimed broadly unless the resulting artifact, L5 capture, and L3
    replay are inspected from current runtime evidence.
  - The verified live path is limited to local Codex invocation artifacts; the
    bounded multi-turn route can preserve multiple per-turn artifacts, but it
    still does not prove OpenCode peer-GOD status, natural multi-GOD
    deliberation, or long-running autonomous provider speech.
- Proof required to close:
  - A provider invocation contract creates
    `xmuse.god_room_provider_speech_response.v1` from a real configured
    provider session with actor identity, command/model/variant, prompt refs,
    output refs, timing, exit status, and proof level.
- Negative proof matrix:
  - These outcomes must be enforced by the L4 invocation path and the L4/L5
    capture boundary:

| Condition | Required outcome | Claim boundary |
|---|---|---|
| Inline opencode variant in model field (e.g. `:max` / `-max`) | `manual_gap` | No provider invocation run; keep claim at configuration/protocol level only |
| Missing `account_ref` | `manual_gap` | No provider speech artifact |
| Unknown `god_id` | `manual_gap` | No provider speech artifact |
| Unsupported provider/model/variant | `manual_gap` or `refactor_required` | No fallback model/provider |
| Missing CLI binary | `manual_gap` | No live invocation proof |
| Nonzero CLI exit | `invocation_failed` | Artifact records failure only |
| Timeout | `invocation_timeout` | Artifact records timeout only |
| Non-structured output | `raw_archive_only` | No automatic `speak` event |
| Digest mismatch at capture | `capture_rejected` | No durable `speak` event |
| Operator raw input without `source_ref` | `capture_rejected` | No durable `speak` event |

- Current risk:
  - Treating an imported artifact as equivalent to the live invocation that
    produced it.
  - Treating an L4 `contract_proof` artifact as L5-capturable
    `real_provider_proof`.
- Next production slice:
  - Carry the bounded multi-turn L4 provider artifact lineage into L6/L10
    evidence without expanding the claim beyond per-turn artifact proof.
- Downstream blocked until:
  - L5 can validate/capture live-proof artifacts, but cannot claim live
    provider speech from contract-only L4 artifacts.
- Do not claim yet:
  - Do not claim natural multi-GOD autonomous provider speech end to end.

## L5 - Speaker Response Capture / Replay Proof

- Dependency role:
  - This layer converts L4 provider response artifacts into durable L3
    provider-backed room events and proves the result by replay.
- User-visible promise unlocked:
  - Provider output becomes auditable GOD room speech instead of a loose log or
    manually pasted response.
- Current implemented evidence:
  - Speaker response capture appends a durable provider-backed room event only
    when backed by a server-loaded provider response artifact.
  - Request-body-only/direct response becomes `manual_gap` when provider
    response artifact proof is missing.
  - Contract-only L4 provider invocation artifacts remain `manual_gap` at the
    L5 capture boundary; this prevents capture proof from being overread as
    provider invocation live proof.
  - Chat API now exposes
    `POST /api/chat/conversations/{conversation_id}/god-room/provider-invocation-capture`
    to produce a server-written L4 artifact and immediately pass that artifact
    ref into the L5 capture gate.
  - The composed route writes both provider response and speaker response
    artifacts and returns the durable room replay from `GodRoomEventStore`.
  - The bounded multi-turn provider speech route repeatedly uses the composed
    L4/L5 route. It appends each `speak` event only through L5 capture, stops
    on the first `manual_gap`, preserves already appended durable events, and
    records the run artifact with per-turn provider response refs, speaker
    response refs, final replay, manual gaps, and forbidden claims.
  - The composed route now refreshes durable `GodSessionRegistry` provider
    binding from a completed `real_provider_proof` L4 artifact before L5
    capture, so L5 still enforces provider session lineage while accepting a
    fresh session id created by the live provider invocation.
  - Focused tests prove that contract/manual L4 artifacts do not append speech,
    while a server-produced `real_provider_proof` artifact is captured into a
    durable `speak` event and appears in replay with binding lineage.
  - The same L5 capture boundary can now append provider-backed
    `question`/`challenge`/`handoff` events when the request supplies valid
    target participants and the event has server-loaded L4 artifact lineage.
    Missing targets or invalid event shapes remain `manual_gap` and do not
    write durable events.
  - A local opt-in live Codex route produced L5
    `status=speak_event_appended`, `proof_level=real_provider_proof`, matching
    provider session id `019ec42d-b245-7d10-b3f8-f511fdceff5f`, events
    `["evt-live-propose", "evt-live-provider-speak"]`, and replay `ok`.
  - Release evidence cross-checks claimed appended `speak_event_id` against
    GOD room replay events.
- Missing production closure:
  - Long natural multi-turn capture has not yet been proven; current multi-turn
    proof is bounded sequential API orchestration.
  - Release evidence does not yet preserve this live L4/L5 lineage as a
    production release proof.
- Proof required to close:
  - A fresh L4 invocation artifact is captured into L3 room events, then replay
    evidence confirms the appended provider-backed event and lineage.
- Current risk:
  - Capture proof can be overread as invocation proof.
  - A provider-backed `question`, `challenge`, or `handoff` can be overread as
    natural peer-GOD deliberation if the bounded capture path and forbidden
    claims are not preserved.
- Next production slice:
  - Preserve bounded provider-backed deliberation event ids, event types, L4
    artifact refs, L5 artifact refs, and replay evidence in L6/L10 lineage,
    then use the durable transcript as input for freeze without claiming
    natural deliberation.
- Downstream blocked until:
  - L6 cannot claim real deliberation freeze if room speech was not captured
    through L4/L5 proof.
- Do not claim yet:
  - Do not claim natural multi-turn provider speech or OpenCode peer-GOD proof
    from this single Codex opt-in live route.

## L6 - Blueprint Freeze Authority

- Dependency role:
  - This layer turns durable deliberation into an executable, typed blueprint.
    It depends on L3-L5 for real discussion provenance.
- User-visible promise unlocked:
  - Discussion becomes executable only through a frozen blueprint with source
    event lineage, assumptions, blockers, rejected alternatives, and decision
    evidence.
- Current implemented evidence:
  - GOD room events can compile into `xmuse.god_room_blueprint_freeze.v1`.
  - The freeze endpoint persists through the existing mission blueprint
    proposal/resolution path.
  - Freeze artifacts now carry explicit `proof_level`:
    - `manual_gap` for blocked freezes;
    - `contract_proof` for fixture/contract transcripts;
    - `opt_in_live_proof` only when durable source events include
      provider-backed appended events with `real_provider_proof` and a
      `provider_response_artifact:` lineage ref from L4/L5.
  - Legacy `xmuse.god_room_blueprint_freeze.v1` artifacts without
    `proof_level` deserialize as `manual_gap` when blocked and
    `contract_proof` otherwise; missing proof metadata does not become live
    proof.
  - Freeze compilation now consumes L3 event proof projection and blocks
    `manual_gap` event proof before persisting a frozen blueprint. This prevents
    unresolved public GOD-room transcripts from being frozen as authoritative
    blueprint evidence.
  - GOD-room freeze requests can now cite a server-written
    `xmuse.god_room_multi_turn_provider_speech_run.v1` artifact. The Chat API
    validates that the run artifact stays under the runtime root, matches the
    current conversation and room, is completed, is not `manual_gap`, and that
    each run `appended_event_id` exists in the current durable room events.
    When validation passes, the run artifact and per-turn provider/speaker
    response artifact refs are carried into the freeze artifact and frozen
    blueprint `source_refs` as lineage only. Freeze `proof_level` remains
    derived from durable event proof projection, not from the run artifact.
  - Freeze artifacts now preserve `source_event_lineage` derived from the L3
    event proof projection. The lineage records source event ids/types,
    participant/GOD ids, proof level, source authority, provider response
    artifact refs, binding/account/model/variant details where available,
    target participant ids, source refs, and forbidden claims.
  - Provider-backed `question`, `challenge`, and `handoff` events captured by
    L5 can therefore feed L6 freeze proof classification and lineage when the
    durable room event proof projection marks them `opt_in_live_proof`. This
    preserves the event lineage without treating capture proof as a fresh L4
    invocation proof or natural groupchat closure.
  - A local L6 smoke run in temp runtime root
    `/tmp/xmuse-live-l6-freeze-9anxog8k` used a live Codex L4/L5 speak event,
    appended `evt-freeze`, and produced a frozen
    `xmuse.god_room_blueprint_freeze.v1` artifact with
    `proof_level=opt_in_live_proof`, `decision_event_id=evt-freeze`, provider
    artifact lineage in source refs, and resolution
    `res_70fff7c8e1224215a6e35c58ffadcf5d` with
    `approval_mode=god_room_blueprint_freeze`.
- Missing production closure:
  - The freeze path has not yet been proven from a fresh live multi-GOD
    transcript with real challenges and objections.
  - Release evidence does not yet preserve the L4/L5/L6 live lineage as a
    production proof bundle.
  - Event proof enforcement does not re-verify L4 provider artifacts; it only
    preserves the upstream event proof boundary.
  - Multi-turn run artifact validation links orchestration lineage to freeze,
    but it still does not prove natural peer-GOD deliberation or server truth.
  - L7 laneDAG, graph-set/status records, GOD-room recovery/review artifacts,
    and L10 runtime closure evidence can now consume the
    `source_event_lineage` field as first-class contract lineage; this still
    has not been proven through a fresh live execution/review chain.
- Proof required to close:
  - A live transcript produces a freeze artifact preserving assumptions,
    blockers, rejected alternatives, source refs, and decision event lineage.
- Current risk:
  - Freezing a clean contract fixture can be mistaken for real deliberation
    closure.
- Next production slice:
  - Use the graph-native lineage carrier in a GOD-room-originated execution and
    review chain, then carry the resulting review-closure source refs into
    MemoryOS candidates without upgrading to live MemoryOS or GitHub truth.
- Downstream blocked until:
  - L7 cannot claim blueprint-to-lane authority unless the blueprint freeze is
    tied to durable deliberation proof.
- Do not claim yet:
  - Do not claim blueprint freeze is backed by natural peer-GOD deliberation.

## L7 - Feature / LaneDAG Authority

- Dependency role:
  - This layer turns a frozen blueprint into execution authority: feature,
    lane, laneDAG, graph-set, owner, checks, rollback, memory refs, and budget.
- User-visible promise unlocked:
  - A frozen blueprint becomes a governed execution graph, not an ad hoc task
    list or projection queue.
- Current implemented evidence:
  - LaneDAG artifacts include lane runtime contracts with owner, checks,
    rollback, memory refs, and budget.
  - Chat API can build laneDAG from GOD-room freeze resolution without writing
    `feature_lanes.json`.
  - `BlueprintLaneDagPlan` now carries `blueprint_proof_level` and source refs
    inherited from the GOD-room freeze artifact. This keeps downstream
    execution/review/release evidence aware of whether the source freeze was
    `contract_proof` or `opt_in_live_proof`.
  - `BlueprintLaneDagPlan` and the persisted laneDAG artifact now also carry
    generic `source_event_lineage` inherited from the GOD-room freeze artifact.
    The Chat API laneDAG route populates it from the frozen
    `xmuse.god_room_blueprint_freeze.v1` artifact, not from request body,
    `feature_lanes.json`, TUI state, or release evidence.
  - Provider-backed `speak`, `question`, `challenge`, and `handoff` lineage can
    therefore remain visible to downstream lane/release evidence while
    preserving each event's proof level and forbidden claims.
  - A local L7 smoke run in temp runtime root
    `/tmp/xmuse-live-l7-lanedag-vtb6b6by` consumed a live L4/L5/L6 Codex
    lineage and produced `lane_graphs/graph-live-route.lane-dag.json` with
    `blueprint_proof_level=opt_in_live_proof`, provider artifact source refs,
    and no `feature_lanes.json` write.
  - Orchestrator graph-native authority guards now fail closed for
    `graph_set_id`-backed lanes when `FeatureGraphStatusStore` has no matching
    durable status record. Legacy lanes and graph-id-only compatibility paths
    keep projection-compatible behavior; graph-set-backed lanes with only
    `feature_lanes.json` projection state do not dispatch/review/reproject from
    projection alone.
  - `FeatureGraphExecutionStatusRecord` and `FeatureEvidenceBundle` now carry
    optional `blueprint_proof_level`, and `FeatureGraphStatusStore`
    initialization/upsert/transition plus worker-evidence, review, rework, and
    patch-forward status producers preserve that lineage. Legacy records with
    no proof field remain readable and are treated as proof boundary unknown /
    contract-level rather than live proof.
  - The GOD-room laneDAG Chat API route now derives a `FeatureGraphSet` from the
    produced `BlueprintLaneDagPlan`, saves it under `graph_sets/`, and initializes
    `FeatureGraphStatusStore` records with the laneDAG `blueprint_proof_level`.
    Focused API coverage proves a two-feature laneDAG becomes ready/planned
    graph-native status records without writing `feature_lanes.json`.
  - `FeatureGraphSet` and `FeatureGraphExecutionStatusRecord` now carry the
    same typed `source_event_lineage` model as laneDAG artifacts. The Chat API
    laneDAG route copies lineage from the laneDAG plan into the graph-set and
    status store, ignoring forged request-body lineage. `FeatureGraphStatusStore`
    preserves existing non-empty lineage across upsert/transition and rejects
    conflicting rewrites, preventing later status updates from replacing frozen
    event provenance.
- Missing production closure:
  - The graph-set/lane authority path is not yet fully unified with every
    execution/dispatch path.
  - Dispatch/review still need to prove they consume laneDAG authority and do
    not fall back to detached artifacts or projection queue state.
  - `blueprint_proof_level` is preserved in laneDAG artifacts, graph-native
    status records, worker evidence bundles, GOD-room recovery/review
    artifacts, and key graph-native status-transition producers, but it is not
    yet proven through every live runner evidence path.
  - Structured `source_event_lineage` is preserved in laneDAG, graph-set, and
    graph-native status records, and GOD-room recovery/review artifacts can
    carry it, but this remains contract proof until a live runner/review chain
    consumes it end to end.
  - The laneDAG-to-graph-set bridge is contract proof only; it has not yet been
    exercised in a fresh live L4/L5/L6/L7 runtime chain and does not prove
    execution/review consumption.
- Proof required to close:
  - A frozen GOD room blueprint feeds authoritative laneDAG/graph-set state
    used by dispatch and review.
- Current risk:
  - Detached laneDAG artifacts may be treated as execution authority before
    dispatch/review actually consumes them.
  - Legacy projection lanes and graph-id-only compatibility lanes remain
    compatibility-only and must not be described as graph-native L7 authority.
  - Source-event lineage can be overread as fresh provider invocation or natural
    groupchat proof if downstream artifacts omit the original forbidden claims.
- Next production slice:
  - Prove graph-native status lineage through an opt-in local runner/review
    execution chain and continue carrying it into MemoryOS candidate source
    refs without using `feature_lanes.json` or treating lineage as review/server
    truth.
- Downstream blocked until:
  - L8 and L9 cannot claim production execution closure without consuming this
    lane authority.
- Do not claim yet:
  - Do not claim full blueprint-to-execution authority closure.

## L8 - Lane Runtime Enforcement / Recovery

- Dependency role:
  - This layer enforces L7 lane authority at runtime: budgets, retries,
    suspend/manual_gap, and direct refactor for repeated failure or demo-grade
    implementation.
- User-visible promise unlocked:
  - Lanes cannot silently loop or keep patching demo-grade paths; repeated
    failure triggers suspend or bounded refactor.
- Current implemented evidence:
  - Lane recovery contracts classify retry, suspend, manual_gap, and
    refactor_required.
  - GOD-room lane recovery API consumes the laneDAG artifact and lane runtime
    contract budget, then writes recovery artifacts with
    `blueprint_proof_level`, laneDAG/source refs, and laneDAG
    `source_event_lineage`.
  - GOD-room lane review intake now consumes the latest lane recovery decision
    as a gate: `retry_allowed=false` decisions (`manual_gap`, `suspended`, or
    `refactor_required`) return 409 and do not write review-intake, review-plane,
    or `feature_lanes.json` artifacts.
  - GOD-room lane review intake also consumes `FeatureGraphStatusStore` and
    fails closed unless the lane's graph-native feature status is `REVIEWING`.
    A laneDAG artifact, recovery artifact, worker candidate ref, or
    `feature_lanes.json` projection cannot by itself authorize review intake.
  - Orchestrator dispatch now consumes the durable lane recovery artifact before
    dispatch CAS. A latest `retry_allowed=false` decision blocks same-path
    dispatch, records recovery block metadata, and does not invoke the execution
    GOD.
  - Platform runner candidate selection now applies the same durable
    `lane_recovery_artifact` dispatch block before creating dispatch tasks. A
    non-retry recovery decision or invalid recovery artifact is recorded on the
    lane metadata and excluded from runner candidates, so runner scheduling no
    longer repeatedly treats recovery-blocked lanes as dispatchable.
    Candidate selection now receives the xmuse root explicitly and no longer
    treats a missing private orchestrator `_root` attribute as permission to
    skip recovery authority. Projection lanes whose public `feature_id` is a
    URI use their stable `lane_local_id` for durable recovery-artifact lookup
    without changing dispatch/state-machine identity. This closes a runner
    candidate-selection bypass at `local_runtime_proof`/contract boundary; it
    still does not prove a long-running live supervisor or overnight-safe
    recovery.
  - Platform runner stale-dispatch repair now writes a durable
    `lane_recovery_artifact` after a CAS-guarded transition from `dispatched`
    to `exec_failed` succeeds. The artifact records
    `source_authority=platform_runner_stale_repair`, a non-retry suspended
    decision for `stale_worker_lost` or `dispatch_no_worker_pid`, manual gaps
    for live/review/server/overnight proof, and forbidden claims. The repaired
    lane metadata records the artifact ref, and the next runner
    candidate-selection pass consumes the artifact and blocks same-path
    redispatch. If the CAS transition fails, no recovery artifact is written for
    that lane. For pidless dispatched lanes, repair is limited to graph-bound
    lanes whose recovery artifact can be written under durable lane authority;
    legacy projection-only lanes still cannot be promoted to durable authority.
    This closes stale worker and graph-bound pidless-dispatch redispatch-loop
    bypasses at local runtime/contract boundary only.
  - Orchestrator gate failure now also writes a durable
    `lane_recovery_artifact` after the lane transitions from `executed` to
    `gate_failed`. The artifact is produced by
    `source_authority=platform_orchestrator_gate_runner`, uses the lane runtime
    budget plus gate report/source refs to build `LaneFailureEvidence`, and
    derives the recovery decision through `evaluate_lane_recovery` rather than
    hand-written status tags. First gate failure can remain
    `decision=retry`/`retry_allowed=true`; repeated same-class gate failure
    can become `decision=refactor_required`/`retry_allowed=false`. The lane
    metadata records the recovery artifact ref and decision; write failure is
    preserved as `manual_gap`. This closes the normal execution gate-failure
    producer gap at contract/local authority boundary only, and does not prove
    review truth, server truth, live long-running runner enforcement, or
    overnight-safe recovery. Local validation for this slice: `uv run pytest
    tests/xmuse/test_platform_orchestrator.py::test_gate_failure_marks_lane_gate_failed_and_skips_review
    tests/xmuse/test_platform_orchestrator.py::test_gate_failure_writes_retry_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_repeated_gate_failure_writes_refactor_required_recovery_artifact
    tests/xmuse/test_platform_runner.py::test_candidate_lanes_excludes_non_retry_recovery_decision
    tests/xmuse/test_overnight_operator_supervisor.py::test_overnight_supervisor_recovery_gate_snapshots_durable_blocks
    -q` -> 5 passed; `uv run pytest tests/xmuse/test_package_boundaries.py -q`
    -> 18 passed; `uv run ruff check .` -> passed; `git diff --check` ->
    passed; `test ! -e xmuse/__init__.py` -> passed. These are local validation
    only, not CI, live runner, review, or merge truth.
  - Orchestrator review patch-forward now writes a durable
    `lane_recovery_artifact` for the original failed lane after the
    patch-forward verdict transitions it to `failed` and appends the patch
    lane. The artifact is produced by
    `source_authority=platform_orchestrator_review_patch_forward`, records the
    review verdict, evidence refs, gate report ref, lane budget refs, and patch
    lane ref, and writes a non-retry `suspended` recovery decision with
    `failure_class=patch_forward_requested`. The next same-path dispatch for
    the original lane consumes that artifact through the existing recovery
    dispatch gate and blocks redispatch. This closes the normal review
    patch-forward recovery-producer gap at contract/local authority boundary
    only; it does not make the patch lane executed/reviewed, create independent
    review truth, prove a live long-running runner, or prove server truth.
    Local validation for this slice: `uv run pytest
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_patch_forward_writes_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_blocks_non_retry_recovery_decision
    tests/xmuse/test_platform_orchestrator.py::test_gate_failure_writes_retry_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_repeated_gate_failure_writes_refactor_required_recovery_artifact
    tests/xmuse/test_platform_runner.py::test_candidate_lanes_excludes_non_retry_recovery_decision
    tests/xmuse/test_overnight_operator_supervisor.py::test_overnight_supervisor_recovery_gate_snapshots_durable_blocks
    -q` -> 6 passed; nearby review transition validation: `uv run pytest
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_transitions_to_merged
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_preserves_merge_context_failure
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_reworks_merge_conflict_with_context
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_does_not_rework_non_reworkable_merge_failure
    tests/xmuse/test_platform_orchestrator.py::test_submit_feature_graph_review_verdict_patch_forward_does_not_write_status
    -q` -> 5 passed; final local gates after both review-recovery producer
    slices: `uv run pytest tests/xmuse/test_package_boundaries.py -q` -> 18
    passed; `uv run ruff check .` -> passed; `git diff --check` -> passed;
    `test ! -e xmuse/__init__.py` -> passed. These are local validation only,
    not CI, live runner, review, or merge truth.
  - Orchestrator review rejection max-retry failure now writes a durable
    `lane_recovery_artifact` when `on_lane_rejected` reaches the existing retry
    exhaustion branch. The artifact is produced by
    `source_authority=platform_orchestrator_review_rejection`, records review
    evidence refs, gate report ref, lane budget refs, and writes a non-retry
    `refactor_required` recovery decision with
    `failure_class=review_rejected`. The next same-path dispatch for the
    rejected original lane consumes that artifact through the existing recovery
    dispatch gate and blocks redispatch. This closes the normal review
    rejection retry-exhaustion producer gap at contract/local authority
    boundary only; it does not prove independent review truth, broad live
    runner enforcement, or server truth. Local validation for this slice:
    `uv run pytest
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_patch_forward_writes_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_rejected_max_retries_writes_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_blocks_non_retry_recovery_decision
    tests/xmuse/test_platform_orchestrator.py::test_gate_failure_writes_retry_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_repeated_gate_failure_writes_refactor_required_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_transitions_to_merged
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_reworks_merge_conflict_with_context
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_does_not_rework_non_reworkable_merge_failure
    -q` -> 8 passed; `uv run pytest tests/xmuse/test_package_boundaries.py -q`
    -> 18 passed; `uv run ruff check .` -> passed; `git diff --check` ->
    passed; `test ! -e xmuse/__init__.py` -> passed. These are local validation
    only, not CI, live runner, review, or merge truth.
  - Orchestrator merge failure now writes a durable `lane_recovery_artifact`
    for graph-bound merge failure branches in `on_lane_reviewed`. Reworkable
    merge conflicts produce `source_authority=platform_orchestrator_merge_failure`
    with `decision=retry`/`retry_allowed=true` before redispatch; merge-conflict
    retry exhaustion produces `decision=refactor_required`/`retry_allowed=false`;
    non-reworkable merge failures produce a non-retry `suspended` recovery
    decision that the existing dispatch recovery gate consumes if the same lane
    tries to re-enter the original path. Missing graph/lane ids remain
    `manual_gap` metadata rather than durable authority. This closes the normal
    merge-failure producer gap at contract/local authority boundary only; it
    does not prove independent review truth, broad live runner enforcement,
    server truth, or GitHub merge truth. Local validation for this slice:
    `uv run pytest
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_merge_conflict_writes_retry_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_merge_conflict_retry_exhausted_writes_refactor_artifact
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_non_reworkable_merge_writes_suspended_artifact
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_reviewed_patch_forward_writes_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_on_lane_rejected_max_retries_writes_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_blocks_non_retry_recovery_decision
    tests/xmuse/test_platform_orchestrator.py::test_gate_failure_writes_retry_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_repeated_gate_failure_writes_refactor_required_recovery_artifact
    tests/xmuse/test_platform_runner.py::test_candidate_lanes_excludes_non_retry_recovery_decision
    tests/xmuse/test_overnight_operator_supervisor.py::test_overnight_supervisor_recovery_gate_snapshots_durable_blocks
    -q` -> 10 passed. These are local validation only and still require final
    lint/diff/package-boundary gates before any PR claim.
  - Orchestrator review retry exhaustion now writes a durable
    `lane_recovery_artifact` during `reconcile_status_changes` when
    `review_timeout` or `review_no_verdict` has exhausted the review retry
    budget. The artifact is produced by
    `source_authority=platform_orchestrator_review_retry_exhaustion`, records
    review failure/task/evidence refs plus lane budget refs, and writes a
    non-retry `refactor_required` recovery decision. Exhausted
    `review_infra_unavailable` writes a non-retry `suspended` decision, while
    active review-infra backoff remains non-terminal and does not produce this
    exhausted-recovery artifact. The existing dispatch recovery gate consumes
    the artifact and blocks same-path redispatch. This closes the retry-budget
    exhaustion producer gap at contract/local authority boundary only; it does
    not prove independent review truth, broad live runner enforcement, server
    truth, or overnight-safe recovery. Retry-eligible first/early review-GOD
    artifact production remains a separate producer slice. Local validation for this
    slice: `uv run pytest
    tests/xmuse/test_platform_orchestrator.py::test_review_retry_count_increments_on_reconcile_recovery
    tests/xmuse/test_platform_orchestrator.py::test_review_retry_stops_after_max_review_retries
    tests/xmuse/test_platform_orchestrator.py::test_review_retry_exhaustion_writes_refactor_recovery_artifact
    tests/xmuse/test_platform_orchestrator.py::test_review_infra_unavailable_circuit_breaker_respects_backoff
    tests/xmuse/test_platform_orchestrator.py::test_review_infra_unavailable_circuit_breaker_closes_after_backoff
    tests/xmuse/test_platform_orchestrator.py::test_review_infra_unavailable_circuit_breaker_stops_at_40_retries
    tests/xmuse/test_platform_orchestrator.py::test_review_infra_exhaustion_writes_suspended_recovery_artifact
    -q` -> 7 passed; broader orchestrator validation:
    `uv run pytest tests/xmuse/test_platform_orchestrator.py -q` -> 248
    passed; final local gates: `uv run pytest
    tests/xmuse/test_package_boundaries.py -q` -> 18 passed;
    `uv run ruff check .` -> passed; `git diff --check` -> passed;
    `test ! -e xmuse/__init__.py` -> passed. These are local validation only,
    not CI, live runner, review, server, or merge truth.
  - Orchestrator review retry now writes a durable `lane_recovery_artifact`
    during `reconcile_status_changes` before a retry-eligible review failure is
    moved back to `gated`. The artifact is produced by
    `source_authority=platform_orchestrator_review_retry`, records review
    failure/task/attempt/evidence refs plus lane budget refs, and writes a
    retry-allowed `retry` recovery decision. Missing graph/lane authority
    preserves `manual_gap` instead of fabricating durable recovery proof. The
    existing dispatch recovery gate treats this artifact as non-blocking
    because `retry_allowed=true`; terminal retry exhaustion still uses
    `platform_orchestrator_review_retry_exhaustion` to write non-retry
    `refactor_required` or `suspended` recovery decisions. This closes the
    retry-eligible first/early review-failure producer gap at contract/local
    authority boundary only; it does not prove independent review truth, broad
    live runner enforcement, server truth, or overnight-safe recovery. Local
    validation for this slice: `uv run pytest
    tests/xmuse/test_platform_orchestrator.py -q -k
    "review_retry_count_increments_on_reconcile_recovery or
    reconcile_recovers_review_timeout_by_rerunning_review or
    review_retry_exhaustion_writes_refactor_recovery_artifact or
    review_infra_exhaustion_writes_suspended_recovery_artifact or
    review_infra_unavailable_circuit_breaker_respects_backoff or
    review_infra_unavailable_circuit_breaker_closes_after_backoff"` -> 6
    passed. Broader lint/package/CI gates remain pending for local changes.
  - Runner supervisor status now exposes a read-only recovery summary derived
    from durable `lane_recovery_artifact` files through the shared run-health
    model. It reports blocked/non-retry counts, invalid artifact counts,
    retry-allowed counts, latest blocked lane samples, source authority,
    `contract_proof`, manual gaps, and forbidden claims without mutating lane
    status or treating process health as recovery authority.
  - Overnight supervisor stage start now reads durable
    `lane_graphs/*.recovery.json` artifacts through
    `xmuse.overnight_supervisor_recovery_gate.v1` before marking a stage
    running. Non-retry recovery decisions such as `refactor_required` or
    invalid recovery artifacts write a blocked `recovery_gate_block`
    production-evidence envelope, record an issue/failure classification, and
    refuse to start the stage. The gate is a contract/manual-gap preflight
    boundary only; it does not prove a live long-running supervisor or
    overnight-safe recovery.
  - A local runner-loop proof now exercises `platform_runner.run()` with a
    durable `refactor_required` recovery artifact and verifies that the lane is
    not dispatched, recovery block metadata is recorded through the runner
    candidate path, and `runner_status` reports the same durable recovery block
    from the shared health model.
  - `platform_runner` now has an opt-in
    `--runner-recovery-proof-output` hook that writes
    `xmuse.local_runner_recovery_proof.v1`. The artifact is produced only from
    real runner candidate selection, the shared run-health recovery model, and
    durable `lane_recovery_artifact` refs. It records excluded
    recovery-blocked lanes as `local_runtime_proof` while preserving manual
    gaps for long-running live runner proof, review truth, server truth, and
    overnight-safe recovery. If no durable recovery block is observed, the
    artifact remains `manual_gap`.
  - L9 review closure can now consume this artifact as
    `xmuse.local_runner_recovery_proof_lineage.v1` after validating schema,
    source authority, proof level, graph filter, target lane refs, and
    forbidden claims. A runner recovery proof without a graph filter, or with a
    graph filter that does not match the review-closure graph, is rejected
    before the review-closure artifact is written. This is recovery lineage
    only, not review truth or server truth.
  - Goal-stage and development policy require direct refactor for repeated
    failure/demo-grade production paths.
- Missing production closure:
  - Recovery is not yet proven through a live long-running runner/supervisor
    session; current enforcement/projection is proven at the GOD-room
    review-intake, graph-status intake, platform runner candidate-selection,
    stale-dispatch repair artifact production, local runner loop/proof artifact,
    orchestrator dispatch, orchestrator gate-failure artifact production,
    runner supervisor status, and overnight supervisor recovery preflight
    boundaries.
  - No live long-running runner proof yet shows a blocked retry after
    `refactor_required`.
- Proof required to close:
  - A real lane failure sequence enters recovery/refactor_required and blocks
    further same-path retries until a refactor artifact exists.
- Current risk:
  - Recovery remains advisory if non-dispatch runner/supervisor paths can bypass
    it, but platform-runner candidate selection no longer silently bypasses
    recovery authority because an orchestrator/fake lacks `_root`, and stale
    dispatched-lane repair no longer leaves a repaired lane without a durable
    recovery artifact when the CAS transition succeeds. Graph-bound pidless
    dispatched lanes are repaired into non-retry recovery artifacts, normal
    gate-failed execution now writes a durable recovery artifact, and normal
    review patch-forward now writes a non-retry recovery artifact for the failed
    original lane. Review rejection retry exhaustion now also writes a
    `refactor_required` recovery artifact for the failed original lane. Review
    retry exhaustion in reconcile now writes `refactor_required` or `suspended`
    recovery artifacts for exhausted review failure paths, while preserving
    active review-infra backoff as non-terminal. Normal graph-bound merge
    failure now writes retry/suspend/refactor recovery artifacts, with missing
    graph/lane ids preserved as manual gaps. Legacy projection-only pidless
    lanes, deferred target-dirty merge retries, and immediate first-failure
    review-GOD artifact production remain outside this slice.
- Next production slice:
  - Prove a graph-native lane through local execution/review while carrying
    recovery proof lineage without upgrading worker output, local tests, or the
    recovery proof artifact into review/server truth.
- Downstream blocked until:
  - L9 cannot claim trustworthy execution/review if lanes can bypass recovery
    decisions.
- Do not claim yet:
  - Do not claim overnight-safe lane runtime recovery.

## L9 - Execution / Review / Patch-Forward

- Dependency role:
  - This layer executes bounded work from L7/L8, reviews it independently, and
    records accepted/reworked/rejected lineage.
- User-visible promise unlocked:
  - Work is executed by bounded workers, reviewed with evidence, and failed
    lanes create auditable patch-forward lineage.
- Current implemented evidence:
  - Review plane, evidence bundles, final action gates, and patch-forward
    contracts exist.
  - OpenCode delegation policy treats worker output as candidate evidence only.
  - GOD-room lane review intake artifact consumes laneDAG authority, optional
    recovery decision, `FeatureGraphStatusStore` `REVIEWING` authority, and
    worker/execution candidate refs while preserving
    `review_truth_status = pending_independent_review`.
  - Review intake now also carries `source_event_lineage` from the graph-native
    status snapshot, not from request body, worker output, TUI state, or
    `feature_lanes.json`.
  - Review intake now records `graph_set_id`, `feature_graph_id`, and the
    graph-native status snapshot in its artifact. Non-`REVIEWING` or missing
    graph status returns 409 and does not write review-intake, review-plane, or
    `feature_lanes.json` artifacts.
  - GOD-room lane review verdict artifact requires an existing review intake
    artifact and evidence refs that cite reviewer inputs before recording an
    explicit reviewer decision.
  - Platform orchestrator review rejection retry exhaustion now produces an L8
    `lane_recovery_artifact` for the failed original lane with
    `decision=refactor_required`, so repeated rejected-lane same-path retries
    are blocked by durable recovery authority. This is recovery lineage only;
    it does not make a worker report or local test result into review truth.
  - Platform orchestrator merge failure now produces L8 recovery lineage for
    graph-bound merge failures after a review verdict: reworkable merge
    conflicts carry retry-allowed recovery evidence, retry exhaustion carries
    `refactor_required`, and non-reworkable merge failures carry non-retry
    `suspended` recovery evidence. These artifacts do not prove GitHub merge
    truth, independent review truth, or release readiness.
  - GOD-room lane review verdict artifacts now write a `ReviewTask` and
    `ReviewVerdict` into `review_plane.json` through `VerdictStore`, and review
    closure requires the terminal patch-lane merge verdict to be present in
    that review plane store before producing the handoff artifact.
  - GOD-room lane review verdict artifacts also build graph-native
    `FeatureEvidenceBundle` and `FeatureReviewVerdict` records from the review
    intake, submit them through the graph-native review coordinator, and update
    `FeatureGraphStatusStore` for merge/rework/blocked verdicts. Stale or
    non-`REVIEWING` graph status returns 409 before review-plane or verdict
    artifacts are written.
  - GOD-room patch-forward verdicts produce graph-native patch-forward gate
    plans and preserve `lane_status_not_updated`; they do not write durable
    lane status until the patch-forward laneDAG/review path runs.
  - Platform orchestrator review patch-forward now produces an L8
    `lane_recovery_artifact` for the original failed lane, so same-path
    redispatch is blocked while the patch-forward lane carries the repair path.
    This is recovery lineage for the failed original lane only; it does not
    prove patch-lane execution/review, independent review truth, server truth,
    or release readiness.
  - GOD-room lane patch-forward artifact requires a patch-forward review verdict
    and saved laneDAG artifact, then uses `BlueprintLaneDagService` to append a
    patch lane, dependency edge, runtime contract, and patch-forward link.
    The patch-forward artifact carries the laneDAG `source_event_lineage` as
    provenance only.
  - GOD-room lane review closure artifact requires the patch-forward sidecar,
    patch lane review intake with candidate refs, and an independent merge
    verdict for the patch lane. It now also re-reads
    `FeatureGraphStatusStore` and requires the patch lane's feature graph to
    be `MERGED` before producing a release-evidence handoff candidate; missing
    or non-`MERGED` status returns 409 and does not write the closure artifact.
    The merge verdict must also cite at least one candidate evidence artifact
    that resolves under the xmuse root; opaque worker-candidate strings alone
    cannot produce a review-closure handoff.
  - Review-closure artifacts now record
    `graph_status_source_authority = feature_graph_status_store` and the
    terminal feature graph status snapshot, including `source_event_lineage`.
    `lane_status_not_updated` is no longer a valid closure gap once this gate succeeds, but
    `release_evidence_not_linked` and `github_truth_not_checked` remain.
  - Review-closure artifacts can now consume a
    `xmuse.local_runner_recovery_proof.v1` artifact and store a derived
    `xmuse.local_runner_recovery_proof_lineage.v1` section. The consumer
    fail-closes unsupported schema/source authority, proof-level overclaims,
    missing target-lane refs, missing durable source refs for local runtime
    proof, and missing forbidden claims. The closure preserves
    `worker_output_is_review_truth`, `ready_to_merge`, `pr_merged`,
    `github_review_truth`, and `overnight_safe_recovery` as forbidden claims.
  - `xmuse.local_execution_candidate.v1` now has a core capture/lineage
    contract and CLI, and platform runner emits candidate artifacts by default
    under runtime `work/local_execution_candidates` after `dispatch_lane`
    returns successfully. `candidate_only` local runtime proof now requires
    `FeatureGraphStatusStore` lineage (`graph_set_id`, `feature_graph_id`,
    `status_id`, and status) and preserves the distinction between the top-level
    GOD-room laneDAG graph id and the graph-native feature graph id. Missing
    graph-status lineage degrades the artifact to `manual_gap`. The artifact
    remains candidate evidence only, carries review/server/GitHub/MemoryOS
    manual gaps, and preserves `worker_output_is_review_truth` as a forbidden
    claim.
  - Local execution candidate artifacts now carry a `producer` boundary:
    `platform_runner_dispatch` for artifacts emitted by `xmuse-platform-runner`
    after `dispatch_lane`, and `manual_cli_capture` for the standalone capture
    CLI. Manual CLI captures can remain generic candidate evidence, but they no
    longer satisfy the bounded L9 local execution/review session gate. A
    `platform_runner_dispatch` candidate must include runner `run_id` and
    `worker_id`; missing or mismatched producer evidence keeps the chain proof
    at `manual_gap`.
  - GOD-room review closure now enforces the same producer boundary before the
    closure artifact is written. The patch-lane merge verdict must cite at
    least one resolvable `xmuse.local_execution_candidate.v1` artifact produced
    by `platform_runner_dispatch`; a `manual_cli_capture` candidate returns
    `409 god_room_lane_review_closure_candidate_artifact_invalid` and no
    review-closure or review-chain-proof artifact is written. This moves the
    fail-closed boundary upstream from L10 aggregation into the L9 closure API
    path while preserving manual CLI captures as generic candidate evidence
    only.
  - GOD-room review closure no longer accepts arbitrary resolvable files as
    candidate evidence. Cited candidate artifacts must validate as
    `xmuse.local_execution_candidate.v1`, match the terminal patch lane or its
    scoped projection/local lane identity, remain `candidate_only`, include
    graph-status lineage, match the GOD-room conversation scope, and preserve
    manual gaps/forbidden claims before the review-closure handoff can be
    written.
  - GOD-room review intake now scans runtime
    `work/local_execution_candidates/*.json` and auto-adds only validator-passing
    graph-status-bound local execution candidate artifacts for the target
    conversation, lane, top-level GOD-room laneDAG graph id, and
    `producer=platform_runner_dispatch`. Invalid, manual, or mismatched
    artifacts are ignored and the intake keeps
    `worker_candidate_evidence_missing` as a manual gap. Auto-discovery only
    supplies reviewer input; it is not review truth. Artifacts emitted to a
    non-default runner output directory are not auto-discovered unless they are
    also made resolvable under this runtime discovery path or cited explicitly.
  - Release-evidence candidate gating now requires review-closure
    `cited_candidate_refs` to include at least one valid
    `xmuse.local_execution_candidate.v1` artifact resolvable under the xmuse
    root before seeding MemoryOS source refs from the review closure. The
    shared handoff gate now also requires those candidate artifacts to declare
    `producer=platform_runner_dispatch`; manual CLI captures and opaque worker
    refs can still be carried as lineage, but they cannot by themselves make
    the L10 candidate gate ready.
  - `xmuse.god_room_lane_review_chain_proof.v1` now captures the L9-to-L10
    handoff as a single contract artifact by consuming the GOD-room review
    closure, re-validating cited local execution candidate lineage, requiring
    verified L8 runner recovery lineage, and requiring the shared L9/L10
    review-closure handoff gate to be ready without importing the L10
    release-evidence aggregator. The artifact preserves
    `not_server_truth` and keeps `worker_output_is_review_truth`,
    `ready_to_merge`, `pr_merged`, `github_review_truth`, `live_memoryos`, and
    `overnight_readiness` forbidden.
  - GOD-room review closure now writes the
    `xmuse.god_room_lane_review_chain_proof.v1` handoff artifact automatically
    on the same API path after a graph-status-gated patch lane reaches a
    review-plane-backed merge verdict. The API response returns both
    `review_closure` and `review_chain_proof` artifact refs. A focused API
    proof covers an auto-discovered candidate generated through a bounded
    platform-runner dispatch loop and local execution candidate capture under
    `work/local_execution_candidates`, an independent merge verdict, closure,
    and `chain_ready` handoff while preserving `candidate_only`,
    `contract_proof`, `not_server_truth`, `worker_output_is_review_truth`,
    `ready_to_merge`, `pr_merged`, and `server_side_truth` boundaries. This is
    still a bounded local runner/API contract proof, not a broad live worker
    execution session or server-truth proof. Positive review-closure helper
    paths now use the platform-runner loop/capture path rather than
    hand-writing successful `xmuse.local_execution_candidate.v1` artifacts;
    hand-written malformed artifacts remain only for fail-closed negative
    coverage.
  - The review-chain proof now also validates the patch-forward laneDAG
    contract carried by the patch-forward artifact. The `patch_forward_link`
    must bind the failed lane, patch lane, patch-forward verdict id, and
    evidence refs; the `patch_lane_contract` must bind the patch lane id,
    failed-lane dependency, required checks, link evidence refs, and patch
    output ref. Missing or mismatched link/contract data keeps the chain proof
    `manual_gap`. This remains contract artifact reconciliation, not broad live
    execution/review proof.
  - The review-chain proof now carries a
    `patch_forward_artifact_boundary` inside bounded session evidence. It
    preserves the patch-forward artifact's source gaps/forbidden claims and
    separates source gaps resolved by downstream patch-lane evidence from gaps
    still retained. `patch_lane_not_executed` is resolved only by validated
    patch-lane intake plus cited local execution candidate lineage;
    `patch_lane_not_reviewed` is resolved only by the validated patch-lane
    verdict/review-plane ref; `release_evidence_not_linked` remains a retained
    manual gap. This is contract-proof gap accounting, not release readiness.
  - The bounded session evidence now carries a `reviewer_independence`
    boundary. It compares the terminal patch-lane verdict `reviewer_id` with
    cited `xmuse.local_execution_candidate.v1` worker ids and fail-closes
    self-review or missing reviewer identity to `manual_gap`. This blocks a
    worker/candidate identity from becoming independent review truth inside the
    L9 chain proof, while still remaining artifact-local `contract_proof` and
    `not_server_truth`.
  - The review-chain proof now also fail-closes review-closure artifacts that
    lack `graph_status_source_authority = feature_graph_status_store`, a
    non-empty `source_event_lineage`, or a terminal
    `terminal_feature_graph_status` snapshot whose status/source lineage
    matches the closure. This keeps the L9-to-L10 handoff bound to the graph
    status/source-event authority captured by review closure, rather than
    letting an artifact-local merge summary stand in for store-derived lineage.
    The proof level remains artifact-local `contract_proof`; it is not
    server-side review, merge, GitHub, or release readiness truth.
  - The bounded session evidence now also carries a
    `review_intake_graph_status_boundary`. It re-validates the patch-lane
    review-intake artifact's `source_authority`,
    `feature_graph_status_store`/`lane_dag_artifact` authority, non-empty
    `source_event_lineage`, `reviewing` feature graph status, and matching
    intake/status source-event lineage before the chain proof can be ready.
    This broadens the local execution/review session proof across the intake
    authority boundary while remaining `contract_proof` / `not_server_truth`.
  - The same session evidence now also carries a
    `candidate_graph_status_boundary`. It cross-checks every cited
    `xmuse.local_execution_candidate.v1` lineage against the patch-lane
    review-intake `feature_graph_status` snapshot, including graph set,
    feature graph, status id, status, and source-event lineage. A candidate
    whose graph-status lineage is valid in isolation but does not match the
    review-intake graph-status authority keeps the chain proof `manual_gap`.
    This prevents a worker candidate from being spliced into a review session
    for the same top-level graph/lane while carrying detached feature-graph
    status evidence. It remains artifact-local `contract_proof`, not broad live
    worker execution/review or server truth.
  - The session evidence also now carries a
    `candidate_artifact_ref_boundary`. It requires review-closure
    `cited_candidate_artifact_refs` to exactly match the resolved valid
    `xmuse.local_execution_candidate.v1` lineage artifact refs. Missing declared
    artifact refs or resolved-but-undeclared candidate artifacts keep the chain
    proof `manual_gap`, and the shared L9/L10 handoff gate rejects the same
    mismatch before release-evidence source-ref aggregation. This remains
    artifact-local `contract_proof`, not review truth, server truth, or
    ready-to-merge evidence.
  - The session evidence also now carries a `candidate_lineage_boundary`. It
    requires review-closure `cited_candidate_artifact_lineage` to match freshly
    resolved valid `xmuse.local_execution_candidate.v1` lineage by artifact ref
    and lineage payload. Missing, unexpected, or mismatched embedded lineage
    keeps the chain proof `manual_gap`, and the shared L9/L10 handoff gate
    rejects the same mismatch before direct review-closure source-ref
    aggregation. This prevents stale embedded closure lineage from becoming
    downstream truth while remaining `contract_proof` / `not_server_truth`.
  - L10 review-chain consumers now share an additional bounded-session gate for
    `xmuse.god_room_lane_review_chain_proof.v1`. MemoryOS source-ref candidate
    aggregation and runtime-closure replay indexing reject `chain_ready` proof
    artifacts unless `local_execution_review_session` is present, remains
    `contract_proof` / `not_server_truth`, carries
    `bounded_local_execution_review_session`, has validated session artifacts,
    has verified review-intake graph-status, candidate graph-status,
    candidate-artifact-ref, candidate-lineage, and reviewer-independence
    boundaries, keeps session candidate refs aligned with the release handoff
    and embedded candidate-lineage refs, and proves candidate producers are
    `platform_runner_dispatch`. This blocks hand-written, manual CLI, or
    partially copied review-chain proofs from becoming L10 source-ref
    authority, but it is still artifact-local contract proof rather than live
    MemoryOS, review, GitHub, or merge truth.
  - The bounded session evidence now also carries a
    `runner_recovery_lineage_boundary`. It verifies that the L8 runner recovery
    proof lineage is present, remains `local_runtime_proof`, shows target-lane
    recovery enforcement, carries a graph filter matching the review closure,
    points at a readable recovery proof artifact, keeps readable durable source
    refs, targets the failed lane, and preserves review/server/overnight manual
    gaps and forbidden claims. Missing, unscoped, or mismatched recovery
    lineage keeps the chain proof `manual_gap`; the review closure can still
    record honest gaps, but L10 cannot consume it as a ready review-chain
    handoff.
  - The platform runner now writes a local
    `xmuse.runner_session.v1` artifact under `work/runner_sessions/` for each
    bounded runner invocation, marks it completed/failed in runner shutdown, and
    injects `runner_session_id` plus `runner_session_ref` into emitted
    `xmuse.local_execution_candidate.v1` artifacts. The L9 review-chain proof
    now carries `xmuse.runner_session_boundary.v1`, reloads that session
    artifact, and verifies candidate artifact refs, run id, runner id, graph
    scope, and completed session status before a bounded session can be ready.
    Missing, incomplete, mismatched, or proof-inflated runner-session artifacts
    keep the proof and shared L10 gate at `manual_gap`. This is local runner
    session-boundary proof only; it is not review truth, live provider proof,
    GitHub truth, or server truth.
  - Runner-session artifacts now also record worker-evidence bundle refs
    submitted during the same platform-runner invocation. The L9 review-chain
    `xmuse.runner_session_boundary.v1` compares those refs with each cited
    candidate's `feature_evidence_bundle:*` source refs. If a candidate cites a
    worker bundle that is not recorded by its runner session, the boundary
    stays `manual_gap` and the chain cannot become `chain_ready`. This reduces
    artifact splicing risk while keeping worker bundles as candidate lineage,
    not review truth or server truth.
    Runner-session artifacts are now written with same-directory temp-file
    replacement, and platform-runner shutdown logs session-finish capture
    failures instead of masking the original runner error or skipping cleanup.
    The runner also consumes the public recovery-dispatch helper rather than an
    underscore-prefixed helper from the orchestrator flow module.
  - L9 now has a single bounded candidate validation boundary,
    `xmuse.validated_execution_candidate_boundary.v1`, for local execution
    candidate readiness checks. It accepts only `producer=platform_runner_dispatch`
    candidates with `candidate_only` / `local_runtime_proof`, `REVIEWING`
    graph-status lineage, target graph/lane scope, matching runner session id,
    run id, runner id, candidate artifact refs, and worker-evidence bundle refs
    recorded by the same `xmuse.runner_session.v1` lineage. Manual CLI capture,
    missing runner sessions, stale graph/lane scope, non-REVIEWING lineage, and
    worker bundle mismatches remain `manual_gap`. This is local bounded-session
    proof only; it preserves worker-output/review-truth/server-truth forbidden
    claims and does not create merge readiness.
  - Platform runner dispatch task failures now keep the runner session artifact
    at `session_failed` / `manual_gap` instead of allowing an unawaited failed
    task to be overreported as `session_completed` / `local_runtime_proof`.
    The failure is recorded on the session artifact, candidate refs remain
    absent unless a real local execution candidate was captured, and downstream
    review-chain/session-boundary consumers continue to fail closed on the
    incomplete session. This prevents failed runner dispatch from becoming
    bounded-session evidence; it does not create review truth.
  - Platform runner local execution candidate capture failures after a
    successful dispatch now also keep the runner session artifact at
    `session_failed` / `manual_gap`. The session records the capture error, does
    not append a missing/failed candidate ref, and downstream bounded-session
    consumers still require a completed session plus real
    `xmuse.local_execution_candidate.v1` refs before any L9 handoff can be
    ready. This prevents dispatch success without candidate evidence from being
    overreported as local execution proof.
  - A completed `xmuse.runner_session.v1` artifact now remains
    `proof_level=manual_gap` when it has no candidate artifact refs. This
    preserves the fact that the runner session ended while preventing an empty
    completed session from being overreported as local execution proof. Only a
    completed session carrying real candidate artifact refs can produce
    runner-session `local_runtime_proof`; downstream review-chain consumers
    still reload those candidate artifacts before any bounded L9 handoff can be
    ready.
  - The shared GOD-room review-closure handoff gate used by L9 and L10 now
    reloads each platform-runner candidate's `xmuse.runner_session.v1` artifact
    before allowing direct review-closure source-ref aggregation. Missing,
    incomplete, mismatched, empty-candidate, or proof-inflated runner-session
    artifacts keep the handoff not-ready and prevent L10 MemoryOS candidate
    source refs from being seeded directly from that review closure. This keeps
    direct L10 aggregation aligned with the Wave D runner-session authority
    boundary; it is still `contract_proof`/local lineage, not review truth,
    live MemoryOS trace, GitHub truth, or merge truth.
  - The same bounded session evidence now carries a session-scope boundary and
    the API integration path uses platform-runner local execution candidate
    artifacts for both the failed lane's patch-forward review input and the
    patch lane's terminal merge review input. This proves a wider
    GOD-room-originated local runner/API handoff while remaining
    `contract_proof` / `not_server_truth`.
  - The bounded session evidence now also carries
    `xmuse.graph_wide_lane_accounting_boundary.v1`. It loads the graph-set
    artifact plus `FeatureGraphStatusStore`, compares expected feature graphs
    with observed status records, requires no ready/active/blocked lane residue,
    and requires every completed lane in the graph-wide status records to have
    validated `producer=platform_runner_dispatch`
    `xmuse.local_execution_candidate.v1` lineage. Missing graph-set/status
    authority, unaccounted feature graphs, ready/active/blocked residue,
    uncovered completed lanes, or missing candidate refs keeps the chain proof
    and L10 bounded-session consumer gate at `manual_gap`. This is graph-wide
    contract accounting, not broad live worker execution/review or server
    truth.
  - Platform-runner candidate capture now fail-closes when graph-native worker
    evidence has not advanced the lane into `REVIEWING`: the emitted local
    execution candidate is `manual_gap`, carries
    `graph_native_worker_evidence_not_submitted`, and is not counted by the
    runner session as `local_runtime_proof`. This prevents READY/RUNNING
    dispatch-return artifacts from satisfying review-chain candidate lineage
    before the graph-native worker-evidence producer is integrated.
  - Platform runner now integrates the first bounded graph-native
    worker-evidence producer handoff: after dispatch returns and only when
    provider binding, planning run, blueprint refs, acceptance criteria, and
    required checks are present, it scopes the READY claim to the dispatched
    lane, writes the worker `FeatureEvidenceBundle` through
    `FeatureGraphArtifactStore`, and advances `FeatureGraphStatusStore` to
    REVIEWING via the existing coordinator before candidate capture. Missing
    prerequisites preserve the existing `manual_gap` path. This is not review
    truth or server truth.
  - Independent GOD-room review verdicts now consume the review-intake
    worker-evidence bundle boundary: when review intake discovered
    graph-native `FeatureEvidenceBundle` refs, verdict `evidence_refs` must
    cite those refs before review-plane or graph-status side effects are
    written. Verdict artifacts carry the cited bundle refs, citation status,
    and intake-local worker-evidence boundary. Patch-forward artifacts preserve
    the source verdict bundle citation, and
    `xmuse.god_room_lane_review_chain_proof.v1` now includes
    `xmuse.worker_evidence_bundle_citation_boundary.v1` in the bounded
    session gate. Missing, uncited, or mismatched bundle citation remains
    `manual_gap`; the bundle is still contract lineage, not independent review
    truth or server truth.
  - Patch-forward lanes now receive independent graph-native status authority:
    the patch lane runtime contract uses the patch lane as its feature id, the
    patch-forward API updates the graph-set with a patch feature graph, and
    `FeatureGraphStatusStore` initializes that graph to `READY`. The existing
    platform-runner worker-evidence producer can then create a
    `FeatureEvidenceBundle` for the patch lane, review intake can discover it,
    and review verdicts must cite it before the patch-lane closure/chain-proof
    path becomes ready. Graph-wide lane accounting treats the original failed
    lane as patch-forward superseded only when the patch terminal lane validates;
    this is still contract/API proof, not broad live execution/review or server
    truth.
  - L9/L10 source-ref aggregation now preserves verified worker-evidence bundle
    refs from the review-chain citation boundary. The terminal patch-lane
    verdict's bundle refs are included in
    `xmuse.worker_evidence_bundle_citation_boundary.v1`, and L10 MemoryOS
    candidate hints, runtime closure replay refs, and review-chain release
    linkage refs can carry those bundle refs as source refs only. This remains
    aggregation lineage, not review truth, merge truth, live MemoryOS trace, or
    server truth.
  - L9/L10 source-ref aggregation now also preserves review-closure
    `source_event_lineage` refs through the shared review-closure handoff
    helper. Review-chain MemoryOS source-ref hints, GOD-room runtime closure
    replay refs, and review-chain release-linkage refs can carry
    `god-room-event:*`, `provider_response_artifact:*`, and lineage
    `source_refs` as aggregation provenance only after the current
    review-closure handoff remains gate-ready. This aligns the chain-proof
    consumer path with the existing runtime-closure lineage path without
    upgrading the proof beyond `contract_proof` / `not_server_truth`.
- Missing production closure:
  - A GOD-room-originated lane has not yet been proven through live execution,
    review, patch-forward, and release evidence in one chain.
  - Review intake/review-verdict/patch-forward/closure artifacts still do not
    prove a broad live worker runtime or assert GitHub truth; release evidence
    linkage exists only as contract/candidate handoff with validated local
    execution candidate artifacts, not as server-side readiness.
- Proof required to close:
  - A lane from GOD room freeze is executed, reviewed, accepted/reworked, and
    linked into release evidence with lineage.
- Current risk:
  - Worker self-report or local test results can be mistaken for review truth.
- Next production slice:
  - Use the verified patch-lane worker-bundle source-ref chain to drive broader
    live runner/review session evidence or an honest L10 replay refresh, while
    continuing to treat worker candidate refs, local tests, review-plane
    artifacts, L8 recovery proof artifacts, runner-session artifacts, bundle
    refs, and GitHub CI success as non-review/non-merge truth.
- Downstream blocked until:
  - L10 release evidence cannot claim end-to-end closure without execution and
    review truth from this layer.
- Do not claim yet:
  - Do not claim end-to-end execution/review closure from GOD room input.

## L10 - MemoryOS / Release Evidence / GitHub Truth

- Dependency role:
  - This layer aggregates cross-stage proof and external truth after upstream
    runtime events exist. It records memory traces, replay bundles, readiness,
    GitHub checks, review, and merge facts.
- User-visible promise unlocked:
  - The operator can replay what happened, see what is ready or blocked, and
    distinguish local replay readiness from server-side review/merge truth.
- Current implemented evidence:
  - MemoryOS namespaces and trace anchors exist.
  - GOD room MemoryOS plan artifacts build governed write/context plans without
    importing `memoryos_lite`.
  - Release evidence pack indexes GOD room closure inputs, speaker attempt,
    artifact-backed speaker response, laneDAG, MemoryOS plan, TUI projection,
    GitHub truth, and readiness.
  - Release evidence pack and CLI can now pass a bounded
    `xmuse.god_room_multi_turn_provider_speech_run.v1` artifact into the GOD
    room runtime closure section. The section validates schema/status, room and
    conversation lineage, appended event presence in durable room events, and
    per-turn L4/L5 artifact refs. Invalid or unreplayed runs keep the section
    `manual_gap`; valid runs remain contract/runtime lineage, not server truth.
  - Release evidence pack and operator action can now index
    `xmuse.god_room_lane_review_closure.v1` as GOD-room runtime closure
    handoff input while preserving `server_truth_status = not_server_truth`.
  - Release evidence export operator-service action can now capture
    `xmuse.god_room_lane_review_chain_proof.v1` from a stored review-closure
    artifact and optionally write a ClosureObject for L10 admission. This is a
    production control-surface entry to the existing proof producer, not a
    claim of live/server review truth.
  - Release evidence candidate report can consume the same handoff artifact to
    seed `live_memoryos` operator `source_refs` hints after validating that the
    artifact remains `contract_proof` and `server_truth_status = not_server_truth`.
  - Release evidence candidate report can also consume a
    `xmuse.production_evidence.v1` GOD room runtime closure artifact to seed
    `live_memoryos` operator `source_refs` hints after validating
    `action=god_room_runtime_closure_indexed`,
    `source_authority=god_room_runtime_closure_contract`, proof level no higher
    than `contract_proof`/`manual_gap`, and non-empty source refs. This is
    source-ref guidance only; it is not a live MemoryOS trace.
  - GOD room runtime closure evidence now indexes L5 speaker response artifacts
    through generic appended event identity, not only `speak_event_id`.
    `event_appended` provider-backed `question`, `challenge`, and `handoff`
    captures can contribute `appended_event_id`, `appended_event_type`, and L4
    provider response refs as contract/runtime lineage when replay proves the
    appended event is present in durable room events.
  - Bounded multi-turn provider speech evidence counts appended event types
    and accepts `event_appended` turns as lineage. This does not upgrade the
    run to GitHub, review, MemoryOS, or natural groupchat truth.
  - GOD room runtime closure evidence now indexes laneDAG-carried
    `source_event_lineage`, including event id/type counts, proof-level counts,
    provider response artifact refs, and source refs. This is replay lineage
    only; it does not prove live MemoryOS, independent review, GitHub truth, or
    merge readiness.
  - GOD room runtime closure evidence now also indexes
    `source_event_lineage` from `xmuse.god_room_lane_review_closure.v1`
    artifacts, including event-type/proof-level counts and source refs. This
    preserves graph-status/review-closure provenance for replay bundles only;
    it is not live execution, live MemoryOS, GitHub review, or merge truth.
  - Release evidence candidate reports and GOD room runtime closure evidence
    now preserve `runner_recovery_proof_lineage` refs carried by
    `xmuse.god_room_lane_review_closure.v1`. This lets MemoryOS candidate
    `source_refs` and replay bundles cite the L8 recovery proof artifact and
    durable lane recovery refs as lineage only; it does not prove live MemoryOS,
    review truth, GitHub truth, or merge readiness.
  - Release evidence candidate reports fail closed when a GOD-room review
    closure has only opaque worker candidate refs and no resolvable
    reviewer-cited `xmuse.local_execution_candidate.v1` artifact, or when a
    cited candidate artifact overclaims/misses required forbidden claims or
    does not match the review closure conversation scope. Older review-closure
    artifacts that predate the top-level `conversation_id` field are treated as
    not gate-ready rather than being upgraded by inference. This tightens
    L9-to-L10 aggregation but remains `contract_proof` source-ref gating, not
    live MemoryOS or server truth.
  - GOD-room review chain proof capture and release evidence candidate reports
    now share the same review-closure handoff gate. L9 no longer imports the
    L10 release-evidence aggregator to prove its chain artifact; L10 consumes
    the resulting artifact as aggregation input only. This is evidence that
    local contract artifacts were consistently linked into the release-evidence
    candidate path; it is not a live MemoryOS trace, GitHub review truth,
    GitHub merge truth, or release export proof.
  - The shared L9/L10 review-closure handoff gate now also requires the closure
    artifact itself to preserve the local execution candidate forbidden-claim
    boundary, including `worker_output_is_review_truth`, `ready_to_merge`,
    `pr_merged`, `github_review_truth`, and `live_memoryos`. Older or external
    closure artifacts missing these forbidden claims are not gate-ready for
    L10 source-ref guidance.
  - Closure reconciler patch-forward lineage admission now binds
    `PatchForwardLineagePresent` to the current closure graph and terminal lane
    scope. A review-chain proof whose top-level graph/lane scope or embedded
    `local_execution_review_session` graph/lane scope does not match the
    reconciled closure remains `manual_gap` for patch-forward lineage even if
    patch-forward/intake/verdict refs are present. This prevents a bounded
    session from one lane or graph from satisfying another lane's Goal B
    condition; it is scope/admission hardening only, not live execution or
    independent review server truth.
    The same condition now also cross-checks patch-forward artifact refs
    declared by the current `xmuse.god_room_lane_review_closure.v1` artifact
    against the embedded `local_execution_review_session` refs in the
    review-chain proof. If the review closure points at one patch-forward /
    patch-lane intake / patch-lane verdict artifact and the release handoff
    session points at another, `PatchForwardLineagePresent` remains
    `manual_gap`. This prevents a review-chain proof from self-reporting
    patch-forward lineage for a different review closure.
    `ValidatedExecutionCandidatePresent` now also requires a non-empty
    graph-native `feature_evidence_bundle:*` ref shared by the local execution
    candidate and its runner-session artifact. A platform-runner candidate plus
    runner session with both bundle-ref lists empty is no longer enough to
    satisfy bounded execution-candidate admission; it remains `manual_gap`
    until the worker-evidence producer lineage is present. This closes a Goal B
    false-closure path where runner-session existence could be overread as
    graph-native worker evidence, but it still does not prove independent
    review truth, live execution/review closure, GitHub truth, or merge
    readiness.
    The GOD-room review-chain proof runner-session boundary now carries the
    same non-empty worker-bundle requirement: candidate lineage and runner
    session lineage must both expose worker-evidence bundle refs, and missing
    candidate/session bundle refs keep the chain proof `manual_gap`. This
    prevents `xmuse.god_room_lane_review_chain_proof.v1` from satisfying its
    bounded-session proof with only a runner-session artifact and candidate
    artifact present. The proof remains `contract_proof`/`not_server_truth`.
    The worker-evidence bundle citation boundary now also receives the
    terminal candidate's expected `feature_evidence_bundle:*` refs and requires
    the terminal patch-lane review verdict to preserve and cite them with
    `worker_evidence_bundle_citation_status=verified`. If review evidence
    omits those refs, the review-chain proof stays `manual_gap`; worker bundle
    existence is still candidate evidence, not review truth by itself.
    L10 review-chain handoff admission now also checks that the verified
    worker-evidence bundle citation boundary did not carry a degraded
    `citation_status`; worker bundle refs are exported to MemoryOS/runtime
    closure/release aggregation only when the boundary is `verified`,
    `contract_proof`, and `citation_status=verified` whenever expected or
    observed bundle refs exist. Tampered or stale chain-proof artifacts with
    inconsistent citation status remain `manual_gap` and export no worker
    bundle refs.
    Release-pack review-chain linkage now also rechecks the runtime-closure
    details consumed from replay: linkage is allowed only when the replay
    section indexed the chain proof, the chain details are `chain_ready` /
    `contract_proof` / `not_server_truth`, the handoff evaluation is `ready`,
    the bounded session gate is `verified`, and the current review-closure
    handoff remains gate-ready. Stale or tampered aggregation reports that carry
    ready-looking source refs but a degraded bounded/current handoff remain
    `manual_gap`; this is L10 aggregation hardening, not GitHub/server truth.
  - Release evidence candidate reports can now consume
    `xmuse.god_room_lane_review_chain_proof.v1` artifacts directly as
    `live_memoryos` source-ref guidance after validating
    `status=chain_ready`, `proof_level=contract_proof`,
    `server_truth_status=not_server_truth`, required forbidden claims, and a
    gate-ready review-closure handoff. `manual_gap`, overclaiming, or missing
    candidate refs keep `god_room_review_chain_proof_artifact_not_ready` as a
    blocker. This is aggregation only and does not create a live MemoryOS
    trace.
  - A focused L9-to-L10 API path proof now feeds the review-chain proof artifact
    written by GOD-room review closure into the release evidence candidate
    report. The report accepts the chain proof only as MemoryOS source-ref
    guidance, carries the platform-runner candidate artifact ref, and preserves
    `candidate_report_is_not_live_memoryos_proof`.
  - Review-chain MemoryOS source-ref guidance now reuses the shared
    review-closure handoff source refs, so `source_event_lineage` entries from
    the gate-ready current review closure can appear as `god-room-event:*`,
    `provider_response_artifact:*`, and lineage `source_refs`. These refs are
    provenance for a future live MemoryOS write only; the candidate report
    remains `candidate_report_is_not_live_memoryos_proof`.
  - The same API-generated review-chain proof can now be fed into the release
    evidence pack replay bundle path as GOD-room runtime closure aggregation.
    The replay section indexes the chain proof as `contract_proof` /
    `not_server_truth`, carries the platform-runner candidate artifact ref, and
    remains `manual_gap` when GitHub/server truth is missing.
  - Release evidence pack now also produces
    `xmuse.god_room_review_chain_release_linkage.v1` when a review-chain proof
    is provided. The summary is `contract_proof` only when the chain proof is
    present in replay source refs, the bounded session gate remains verified,
    and the current review-closure handoff is still gate-ready. It resolves
    `release_evidence_export_not_attempted` / `release_evidence_not_linked`
    only for that pack's aggregation lineage, preserves
    `affects_pack_decision=false`, and keeps `ready_to_merge`, `pr_merged`,
    GitHub review/merge truth, live MemoryOS, and server truth forbidden.
    The linkage may retain review-closure `source_event_lineage` refs from the
    runtime-closure replay section, but those refs remain aggregation
    provenance and do not affect the pack decision.
  - Release evidence pack and CLI can now pass the same
    `xmuse.god_room_lane_review_chain_proof.v1` artifact into the GOD room
    runtime closure replay section. The pack relies on runtime-closure evidence
    validation for schema/status/proof-level/not-server-truth/forbidden-claim
    and handoff checks, records review-chain source refs only as aggregation
    lineage, and fail-closes the section to `manual_gap` on server-truth
    overclaim. This does not create live MemoryOS, GitHub review truth, GitHub
    merge truth, `ready_to_merge`, or `pr_merged`.
  - Release evidence candidate reports and GOD-room runtime closure evidence
    now both re-load the current review closure referenced by the chain proof
    and run the shared L9/L10 handoff gate before accepting review-chain source
    refs. A stale embedded handoff whose runner-session artifact has since
    disappeared remains diagnostic evidence only: the runtime closure section
    records `manual_gap`, exposes the current handoff failure, and does not add
    chain-proof/candidate refs to aggregation `source_refs`. This is still
    contract-proof consumer hardening and not server truth or live review truth.
  - GOD-room runtime closure evidence now also re-derives the shared
    L9/L10 review-closure handoff gate for direct `god_room_review_closure`
    inputs instead of trusting the embedded
    `release_evidence_handoff_status` string. Missing, stale, or invalid
    cited candidate artifacts and runner-session lineage keep the direct
    closure path at `manual_gap`, expose the current handoff failure, and
    prevent review-closure source refs, including `source_event_lineage`, from
    being treated as ready aggregation input. The section remains
    `contract_proof` / `manual_gap` consumer hardening and does not create
    live MemoryOS, review truth, GitHub truth, or merge truth.
  - The shared L9/L10 handoff helper now also emits
    `xmuse.review_closure_handoff_evaluation.v1`. Runtime closure evidence,
    release evidence candidates, and feature lineage replay expose this same
    evaluation payload instead of each redefining candidate lineage truth:
    `ready` is allowed only for `xmuse.god_room_lane_review_closure.v1`,
    `proof_level=contract_proof`,
    `review_truth_status=independent_review_artifact`,
    `execution_truth_status=candidate_reviewed`,
    `server_truth_status=not_server_truth`, a gate-ready current handoff, and
    required forbidden claims including `live_memoryos`,
    `github_review_truth`, `ready_to_merge`, and `pr_merged`. Missing
    forbidden claims remain `manual_gap`; server-truth overclaims are
    `blocked`. Candidate refs, cited refs, and `source_event_lineage` counts
    are exposed as aggregation lineage only and do not prove live MemoryOS,
    GitHub review truth, merge truth, or release readiness.
  - Review-chain proof L10 consumers now share
    `xmuse.review_chain_proof_l10_handoff_evaluation.v1` instead of each
    hand-parsing embedded chain-proof handoff fields. The evaluator checks
    `chain_ready`, `contract_proof`, `not_server_truth`, required forbidden
    claims, bounded-session gate status, and a freshly reloaded current
    `xmuse.review_closure_handoff_evaluation.v1`; only `status=ready` exposes
    chain-proof source refs, candidate artifact refs, and worker-evidence
    bundle refs to runtime closure or MemoryOS candidate source-ref hints.
    Stale embedded handoff data, missing runner-session artifacts, server-truth
    overclaims, or missing forbidden claims remain diagnostic/manual-gap or
    blocked evidence and cannot seed release/runtime aggregation refs. This is
    L9-to-L10 contract-proof consumer hardening only, not live MemoryOS,
    GitHub review truth, `ready_to_merge`, or `pr_merged`.
  - Release evidence pack now treats a supplied GOD-room review-closure
    artifact without a matching review-chain proof as an expected L9 handoff
    gap. It asks GOD-room runtime-closure evidence to emit
    `review_chain_proof.status=manual_gap`, `expected=true`, and
    `god_room_review_chain_proof_artifact_missing` instead of silently omitting
    the review-chain proof section. Legacy packs without GOD-room review
    closure input remain unaffected, and a missing chain proof still does not
    create release linkage, review truth, server truth, or pack readiness.
    Local validation for this slice: `uv run pytest
    tests/xmuse/test_god_room_runtime_closure_evidence_capture.py
    tests/xmuse/test_release_evidence_pack.py
    tests/xmuse/test_release_evidence_candidates.py -q` -> 95 passed;
    `uv run pytest tests/xmuse/test_package_boundaries.py -q` -> 18 passed;
    `uv run ruff check .` -> passed; `git diff --check` -> passed;
    `test ! -e xmuse/__init__.py` -> passed. These are local validation only,
    not CI, GitHub review, or merge truth.
  - A fresh local read-only GitHub server-truth refresh for PR #43 at head
    `b154021111400863098f11ed98eeb24d6fad9311` wrote
    `/tmp/xmuse-github-truth-current.json` and
    `/tmp/xmuse-github-truth-gate-current.json`. It captured branch protection
    and required check truth for `quality-gates`, `contract-smoke-gates`, and
    `real-runtime-integration-gate`, but the raw truth artifact remains
    `proof_level=manual_gap` because server-side `review_truth` and
    `merge_truth` are missing; it also records `draft=true`,
    `pull_request_state=open`, and `can_emit_pr_merged=false`. The release-gate
    artifact is
    `server_side_enforcement_proof` for enforcement/check truth only, not review
    or merge truth.
  - Release evidence candidate reports can now consume an existing
    `github_server_side_truth_capture.v1` artifact from
    `github_server_truth_artifact` or `XMUSE_GITHUB_SERVER_TRUTH_ARTIFACT`.
    The report re-runs the GitHub server-truth release gate, fail-closes stale
    head mismatches, and recomputes `can_emit_pr_merged` through
    `GitHubServerSideTruthEvidence`/`can_emit_pr_merged` instead of trusting a
    raw artifact boolean. This is artifact aggregation guidance only; the
    candidate report remains `candidate_report_is_not_github_server_truth_proof`.
  - Release evidence pack GitHub truth projection now uses the same
    `GitHubServerSideTruthEvidence`/`can_emit_pr_merged` recomputation and
    requires the GitHub server-truth gate to be `ok` before projecting
    `can_emit_pr_merged` or `merged=true`. Raw artifact booleans can no longer
    produce `pr_merged` projection or a "no action required" GitHub next action.
    The GitHub release gate itself remains `server_side_enforcement_proof`
    unless the validated server truth satisfies full `server_side_merge_proof`.
    The same gate also carries `forbidden_claims=["pr_merged"]` for enforcement
    proof, manual gaps, and stale-head gaps, and only drops that forbidden claim
    when validated server-side merge proof can emit `pr_merged`.
    Its enforcement-proof admission now reuses the same model-level status-check
    and server-enforcement truth properties as merge-proof emission, so a raw
    artifact with required-check names but no workflow/check-run lineage remains
    a `manual_gap`.
  - MemoryOS live gate source-ref admission now excludes MemoryOS-owned refs
    from the upstream source-ref count. A live trace must cite a non-MemoryOS
    xmuse source such as conversation, lane, blueprint, review, or release
    lineage; otherwise it remains blocked/manual-gap and keeps `live_memoryos`
    forbidden. This prevents a MemoryOS trace artifact from proving itself.
  - PR #43 latest verified CI after this slice refresh is for remote head
  `b154021111400863098f11ed98eeb24d6fad9311` in run `27607281313`; merge
  state was `CLEAN` when last checked. Local changes after that head remain
  clean after push verification.
- Missing production closure:
  - No current live MemoryOS Lite trace proof is established for this branch
    head.
  - The release pack still depends on missing live execution proof, live
    MemoryOS trace, broad live execution/review proof, GitHub review truth, and
    merge truth for full production closure.
  - PR #43 is still draft/open/unmerged and has no review decision.
- Proof required to close:
  - Configured MemoryOS Lite service accepts writes/context requests and
    returns trace ids mapped to GOD/lane/review artifacts.
  - A fresh replay bundle contains real provider speech, freeze, laneDAG,
    execution/review, MemoryOS trace, GitHub review/check/merge truth or honest
    blockers.
  - Required review/check/merge server-side truth, including merge proof before
    any `pr_merged` event.
- Current risk:
  - Governance plan proof can be overread as live memory proof.
  - Appended event lineage can be overread as independent review truth or
    natural multi-GOD deliberation if the upstream proof boundary is omitted.
  - `ready_for_replay` can be confused with `ready_to_merge` or `pr_merged`.
  - CI success can be overread as review or merge truth.
- Next production slice:
  - Carry graph-status/review-closure `source_event_lineage` into MemoryOS
    source-ref candidates as lineage-only evidence, then run an opt-in live
    MemoryOS trace capture when the environment is configured. A fresh replay
    bundle and GitHub truth capture must still avoid treating either as merge
    truth.
- Downstream blocked until:
  - L11 cannot claim production cockpit or overnight readiness unless this
    layer shows honest replay/server truth.
- Do not claim yet:
  - Do not claim live MemoryOS memory closure, release/mainline closure, merge
    closure, or `pr_merged`.

## L11 - Operator Cockpit / TUI / Overnight Soak

- Dependency role:
  - This layer is the final operator surface and long-run proof. It may expose
    partial controls early, but production closure requires L1-L10 to be
    truthful and wired.
- User-visible promise unlocked:
  - The operator can supervise and actuate the autonomous development loop from
    TUI/API surfaces, then run for hours with recovery, replay, memory, review,
    and server truth.
- Current implemented evidence:
  - TUI exposes GOD room actions including room ensure/event append/freeze,
    laneDAG, recovery, MemoryOS plan, speaker attempt, speaker response, and
    release pack aliases.
  - TUI actions route through Chat API/operator contracts.
  - Goal-stage harness, worker delegation policy, RIGR-V, anti-TDD-abuse rules,
    and repeated-failure refactor policy are documented.
  - Evidence/control surfaces exist for many stages.
- Target native CLI cockpit architecture:
  - `NativeCliSessionBridge` starts the real selected CLI from the L2
    `RoomSelectedGodBinding`, preserving native slash commands, ANSI/progress
    rendering, tool-process output, and interactive terminal semantics.
  - `MachineEventBridge` consumes the same CLI run through a separate structured
    stream or raw archive and produces L4 provider invocation artifacts. For
    non-structured output it may preserve raw terminal evidence, but it must
    downgrade structured proof instead of inventing a `speak` event.
  - `GodRoomProjectionBridge` renders the run as if Codex, OpenCode, and other
    selected GODs are in one group room, but room truth still comes only from L3
    durable events and L5 artifact-backed capture.
  - A pane/session registry may expose running native CLI panes to the TUI, but
    it is discovery/projection state, not durable authority.
- Native command-routing rule:
  - Room-level slash commands such as `/freeze`, `/dispatch`, and `/review`
    route through xmuse contracts.
  - Explicit target commands such as `@opencode /models` or `@codex /status`
    may route to the selected native CLI when the L2 binding authorizes it.
  - Focused native-pane input may pass raw bytes to the CLI, but each operator
    input must be recorded as an operator action/source ref.
  - `//` is reserved as an escape hatch to force raw CLI input when a leading
    slash would otherwise be interpreted by xmuse.
- Missing production closure:
  - The cockpit is not yet a complete live operations console for provider
    invocation, review queue decisions, live MemoryOS trace, GitHub truth, and
    overnight continuation/stop decisions.
  - The native CLI cockpit bridge does not yet exist. TUI cannot yet preserve
    full Codex/OpenCode native TUI behavior while simultaneously producing L4/L5
    proof artifacts.
  - No 8-10 hour live GOD room runtime soak has proven natural discussion,
    provider speech, freeze, lane execution, review, MemoryOS trace, and
    GitHub truth together.
- Proof required to close:
  - Operator can run a complete live session through room discussion,
    provider-backed speech, freeze, laneDAG, execution/review, evidence pack,
    and stop/continue decision without bypassing contracts.
  - Native CLI session evidence includes `room_id`, `invocation_id`, `god_id`,
    `binding_revision`, `account_ref`, `cli_command`, `model`, `variant`,
    `pane_id` or `session_id`, `raw_archive_ref`, `stdout_ref`, `stderr_ref`,
    `started_at`, `completed_at`, `exit_code`, `status`, operator input refs,
    L4 artifact ref, L5 `speak_event_id` when captured, and `proof_level`.
  - Read-only observer panes and raw terminal views remain separate from
    authority. A visible native CLI response is not a GOD room `speak` event
    until it is captured through L4/L5 with matching digest and actor/binding
    lineage.
  - A live overnight run with budget ledger, recovery decisions, replay bundle,
    review evidence, and honest blockers.
- Current risk:
  - Expanding panels can create false confidence if live/provider/server proof
    is not clearly separated from projection proof.
  - Long `/goal` progress reports can become optimistic if not tied to replay
    artifacts and server truth.
  - Native CLI interactivity can mutate provider/session state invisibly unless
    every operator input and raw archive ref is attached to the invocation.
- Next production slice:
  - After L2-L5 provider speech closes, expose provider invocation as an
    operator control through a native CLI bridge. After L8-L10 close, run
    bounded soak and cockpit proof.
- Downstream blocked until:
  - This is the terminal integration layer; it should not be used to justify
    upstream shortcuts.
- Do not claim yet:
  - Do not claim TUI is a complete autonomous operations cockpit.
  - Do not claim overnight autonomous production readiness.
  - Do not claim raw terminal output, pane registry state, or a provider process
    session is durable GOD room speech.

### L11 clowder-ai reference sources

Use these as implementation references, not as xmuse package dependencies:

- Reference boundary for every group below:
  - `reference_status: local_reference_only`
  - `must_not_gate_ci: true`
  - `must_not_claim_external_proof: true`
  - These paths are design references from a sibling local checkout. They are not
    durable xmuse evidence, release proof, package dependencies, or CI gates.
- Single-source dual consumer and tmux-backed provider execution:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:1`
    documents the `tmux pane -> FIFO machine stream + PTY human stream` shape.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:54`
    builds the CLI command with `tee` and exit-code capture.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:90`
    keeps tmux execution on the same event contract as normal CLI spawning.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:104`
    creates per-invocation temp/FIFO/stdin/exit/stderr paths.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:141`
    starts the command and then makes the pane read-only.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:317`
    consumes FIFO output as plain text or NDJSON.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:382`
    captures exit/stderr/diagnostic evidence.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:480`
    exposes a spawn override so callers remain execution-mode agnostic.
- Tmux gateway and pane lifecycle:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:51`
    manages one tmux server per worktree.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:106`
    creates panes with stable pane ids.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:166`
    supports resize for terminal UI fidelity.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:185`
    creates agent panes with remain-on-exit.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:203`
    toggles read-only pane mode.
- Pane discovery and terminal routes:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/agent-pane-registry.ts:1`
    tracks invocation-to-pane discovery state as in-memory projection only.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/agent-pane-registry.ts:39`
    registers an invocation pane.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/agent-pane-registry.ts:75`
    records completion status.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:27`
    guards terminal WebSocket upgrades by origin.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:56`
    creates or reconnects terminal sessions.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:104`
    attaches PTY output/input over WebSocket for ordinary terminal sessions.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:227`
    lists agent panes for a user/worktree.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:243`
    attaches to agent panes read-only.
- Event, diagnostics, and UI projection:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:75`
    records provider/model/session metadata and CLI diagnostics.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:112`
    enumerates stream message kinds including text, tool use, errors, status,
    provider signals, and liveness signals.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:129`
    defines the streaming agent message envelope.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:216`
    defines the spawn override contract.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/session/CliRawArchive.ts:12`
    stores per-invocation raw CLI archive.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/session/CliRawArchive.ts:27`
    appends timestamped raw events.
  - `/home/iiyatu/clowder-ai/packages/web/src/components/workspace/AgentPaneViewer.tsx:16`
    displays a read-only xterm.js view of a native agent pane.

## Maintenance Rules

- Update this ledger after every production-slice commit that changes a layer.
- Keep claims tied to current branch/head/PR/CI facts.
- If a layer is only contract proof, say so explicitly.
- If a live/server proof is missing, record `manual_gap` and the next artifact
  required to close it.
- Do not downgrade evidence boundaries to make a layer look complete.
- Do not treat local reference paths outside this repository as release proof,
  CI gates, or externally reproducible evidence.
- Maintain dependency order: downstream UI, evidence, or soak work may expose
  partial views, but it must not claim closure before upstream authority and
  runtime proof exist.
- Prefer direct refactor over repeated patch stacking for demo-grade or
  repeatedly failing production paths.
