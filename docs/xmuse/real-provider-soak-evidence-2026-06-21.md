# Real Provider Bounded Soak Evidence - 2026-06-21

## Decision

Status: `blocked/provider_codex_app_server_writeback_timeout`.

This run does not raise the xmuse claim level. The current claim remains:

```text
xmuse production-closure short path accepted
```

The bounded real-provider soak entered the Ray/Codex app-server path and wrote
durable groupchat/session state, but it did not produce the first durable MCP
`chat_post_message` reply before the focused soak test deadline. The release
checklist must continue to forbid full production release readiness and
multi-hour real-provider soak claims.

## Soak Command

Runtime root:

```text
.goal-runs/2026-06-21/real-provider-bounded-soak-pytest/test_real_ray_codex_app_server0
```

Command:

```bash
timeout 600 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/real-provider-bounded-soak-pytest
```

Environment set by the test:

```text
XMUSE_PEER_GOD_BACKEND=ray
XMUSE_RAY_GOD_TRANSPORT=app-server
XMUSE_RAY_GOD_MCP=1
XMUSE_RAY_GOD_EFFORT=low
XMUSE_DEGRADED_LOCAL_GOD_MODE unset
```

Observed result:

```text
FAILED tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume
AssertionError: expected 1 replies
1 failed, 4 warnings in 67.76s
```

The failure occurred on turn 1 before the planned restart/resume portion of the
8-turn soak.

## Durable Soak Facts

The run produced durable local state before failing:

- chat database:
  `.goal-runs/2026-06-21/real-provider-bounded-soak-pytest/test_real_ray_codex_app_server0/chat.db`
- conversation:
  `conv_c6bf4774a7b64c2b8a30fa7939f8c372`
- human intake message:
  `chat.db#message=msg_9b417b52073f4cc2b49173f642920cb7`
- intake spine:
  `chat.db#acceptance_spine=goalrun_f396efc80ec54d06a43df30f3d780636`
- architect participant:
  `part_ca2c91f5932c43dabd5e7a185b540d03`
- architect GOD session:
  `god_sessions.json#god_session_id=god-d40f78c4310747ee96279b643344e598`
- Codex provider session:
  `019ee9ed-0636-7143-acc7-e2aed60c49f2`
- provider session kind:
  `codex_app_server_thread`
- inbox item:
  `chat_inbox_items#id=inbox_33c73290a97e46ee9c3f50622fc5cc0d`
- stream:
  `chat_streams#id=stream_inbox_33c73290a97e46ee9c3f50622fc5cc0d`

Durable negative facts:

- `messages` contains only the human message; no assistant reply was persisted.
- `chat_inbox_items.status = claimed` and `responded_message_id = null`.
- `chat_streams.status = active`, `content = ""`, and `first_delta_at = null`.
- `peer_turn_latency_traces` contains zero rows.
- `peer_turn_mcp_tool_traces` contains zero rows.
- the intake AcceptanceSpine stayed at `status = intake`; the real soak path did
  not reach proposal, dispatch, review, final-action, or GitHub gate.

## Terminal Classification Gate

Because the real provider soak did not reach the AcceptanceSpine/final-action
terminal path by itself, a separate acceptance-gated classification run recorded
the product decision as durable blocked state. This run intentionally did not
use `--github-live-capture`; the real soak did not pass and must not be turned
into an accepted release signal.

Runtime root:

```text
.goal-runs/2026-06-21/real-provider-bounded-soak-terminal
```

Command:

```bash
uv run xmuse-platform-runner \
  --xmuse-root .goal-runs/2026-06-21/real-provider-bounded-soak-terminal \
  --goal "Classify bounded real provider Ray/Codex soak attempted on 2026-06-21: real peer-chat soak started Ray/Codex app-server, created durable conversation and provider session, but failed before first durable MCP chat_post_message reply; keep production release blocked pending provider/Codex app-server writeback repair." \
  --acceptance-gate \
  --github-pr 157 \
  --github-head-sha 1332bdea7d99a3c57c1c32bb75c0989397e2579b
```

Terminal durable refs:

- terminal status:
  `blocked`
- blocked reason:
  `github_gate_unverified`
- terminal spine:
  `chat.db#acceptance_spine=goalrun_42cf37320c0443a3a2d0b7ef46fa5c2b`
- terminal final action:
  `final_actions.json#hold=final-877f3007706e`
- terminal GitHub gate gap:
  `github_gate_evidence.json#evidence=ghgate_5f6231d8efc440d8b92e3942608c8bd8`
- terminal proposal:
  `chat.db#proposal=prop_cdb092638bfb4e92abbcf96723ffb354`
- terminal dispatch:
  `chat_dispatch_queue#entry=dispatch:conv_3b54744dcf044e9b8a953b119002a9a3:res_3a550907cbff4031b9fadc761555e45f:execute`
- terminal review verdict:
  `review_plane.json#verdict=verdict-2c1908909212`

`github_gate_evidence.json` persisted `proof_level = manual_gap`,
`can_accept = false`, and:

```text
gap_reason = server_side_merge_proof unavailable for acceptance-gated short run
```

## Classification

- Primary class: `provider`.
- Secondary class: `Codex app-server / MCP writeback`.
- Not classified as GitHub gate failure: the real provider soak failed before
  server-side merge proof was relevant.
- Not classified as review failure: the soak failed before review-plane
  execution.
- Not classified as dashboard/TUI issue: neither surface is authority.

The first failing boundary is:

```text
Ray peer scheduler
-> Codex app-server provider session starts
-> inbox item claimed
-> stream row opens
-> no durable chat_post_message / no assistant message / no latency trace
```

## Next Cut

Do not expand TUI/dashboard/provider surface first. The next implementation cut
should make the real Ray/Codex app-server path terminally durable when the
provider fails to write back:

1. persist a failed or timed-out peer turn trace when a claimed inbox item does
   not produce `chat_post_message` before the scheduler deadline;
2. move the inbox item from `claimed` to a durable failed state with a precise
   reason such as `provider_no_mcp_writeback_before_deadline`;
3. attach that failure ref to the existing intake AcceptanceSpine so a real
   provider soak can terminalize as durable `failed` or `blocked` without a
   separate classifier command;
4. rerun the same bounded soak and only then consider enabling live GitHub
   capture for an accepted release signal.

Follow-up status: the provider response timeout cut begins by terminalizing
timeouts at the peer-chat scheduler boundary. A timed-out claimed inbox item now
records `failure_reason = provider_no_mcp_writeback_before_deadline`, persists a
failed latency trace, and attaches that trace ref to the original intake
AcceptanceSpine as a failed terminal state. This is a failure-path durability
repair only; it does not make the real provider soak accepted and does not raise
the release claim level until the same bounded soak is rerun successfully.

Follow-up verification:

```text
.goal-runs/2026-06-21/provider-terminalization-soak-pytest-2/test_real_ray_codex_app_server0
```

The same bounded real-provider soak still failed before the first durable
assistant reply, but the failure now terminalized durably:

- conversation:
  `conv_95125d5982f9471ca6940a397d1e49cb`
- human intake message:
  `chat.db#message=msg_c31af50481b849ac8ac611aca6fffd22`
- inbox item:
  `chat_inbox_items#id=inbox_86ee4299d62741e9a7049bd78dbf627f`
- inbox status:
  `failed`
- inbox failure reason:
  `provider_turn_cancelled_before_mcp_writeback`
- stream:
  `chat_streams#id=stream_inbox_86ee4299d62741e9a7049bd78dbf627f`,
  `status = error`
- failed latency trace:
  `peer_turn_latency_traces#trace=peer_latency_inbox_86ee4299d62741e9a7049bd78dbf627f`
- original intake spine:
  `chat.db#acceptance_spine=goalrun_00f50043ea414cada59118792d12f28b`,
  `status = failed`,
  `blocked_reason = provider_turn_cancelled_before_mcp_writeback`

This proves the failure-path terminalization repair. It does not prove provider
writeback success, proposal/review/final-action traversal, or GitHub accepted
truth for the real provider soak.

## P1 Positive Writeback Follow-up

Status: `real_provider_one_turn_writeback_accepted`.

Runtime root:

```text
.goal-runs/2026-06-21/p1-one-turn-writeback-pytest-5/test_real_ray_codex_app_server0
```

Command:

```bash
timeout 480 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p1-one-turn-writeback-pytest-5
```

Observed result:

```text
1 passed, 4 warnings in 151.01s
```

Durable positive facts:

- conversation:
  `conv_eafc5c51604643c2a8d95ac8017227ff`
- architect participant:
  `part_686d140510d540ec99917ef61347d4e9`
- Codex app-server provider session:
  `019eea2c-27f9-7152-b8aa-66d844353650`
- provider session reused across restart/resume:
  `true`
- turn 1:
  - human message:
    `chat.db#message=msg_a950e7d09e1b43849fa1e07e25b8c2ab`
  - assistant message:
    `chat.db#message=msg_ef5ed3f517db4d918d52014d9ad8defd`
  - inbox:
    `chat_inbox_items#id=inbox_36409f270c3f454aac7a80dca289a924`,
    `status = read`,
    `responded_message_id = msg_ef5ed3f517db4d918d52014d9ad8defd`
  - latency trace:
    `peer_turn_latency_traces#trace=peer_latency_inbox_36409f270c3f454aac7a80dca289a924`,
    `delivery_mode = mcp_writeback`,
    `writeback_ms = 80935`
- turn 2 after runner restart:
  - human message:
    `chat.db#message=msg_0fcda2b89d4f41a59d3746c0a57a7aaf`
  - assistant message:
    `chat.db#message=msg_396e35af34894035b99a0dc277b80edc`
  - inbox:
    `chat_inbox_items#id=inbox_d3c8700e124a470080171db7458079a7`,
    `status = read`,
    `responded_message_id = msg_396e35af34894035b99a0dc277b80edc`
  - latency trace:
    `peer_turn_latency_traces#trace=peer_latency_inbox_d3c8700e124a470080171db7458079a7`,
    `delivery_mode = mcp_writeback`,
    `writeback_ms = 61034`

Both turns persisted `peer_turn_mcp_tool_traces` for
`mcp_tool_call_started`, `chat_post_message`, `chat_post_message_persisted`,
and `mcp_tool_call_completed`. Both turns recorded
`degraded_reason = peer_writeback_before_provider_result`, which means the
scheduler observed durable MCP writeback and released the turn before waiting
for a final provider result. It is an early-release success classification, not
stdout fallback.

This proves the P1 positive writeback question: a real Ray/Codex app-server
peer can complete durable MCP `chat_post_message` writeback and survive a
restart/resume session reuse. It still does not prove proposal/review/dispatch,
final-action, GitHub gate, accepted AcceptanceSpine truth, or multi-turn soak
stability.

## P2 Positive Proposal / Review / Dispatch Follow-up

Status: `real_provider_proposal_review_dispatch_accepted`.

Runtime root:

```text
.goal-runs/2026-06-21/p2-real-provider-proposal-dispatch-pytest/test_real_ray_codex_app_server0
```

Command:

```bash
timeout 480 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_proposal_review_dispatch \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p2-real-provider-proposal-dispatch-pytest
```

Observed result:

```text
1 passed, 4 warnings in 89.26s
```

Report:

```json
{
  "conversation_id": "conv_bc4fa83561b042a489e80078e05882d5",
  "delivery_mode": "mcp_writeback",
  "dispatch_entry_id": "dispatch:conv_bc4fa83561b042a489e80078e05882d5:res_3d19e6d8154b44769aef4d187f74f323:execute",
  "proposal_id": "prop_038ab28b77f94083959d22f37d527a9c",
  "provider_session_kind": "codex_app_server_thread",
  "resolution_id": "res_3d19e6d8154b44769aef4d187f74f323"
}
```

Durable positive facts:

- architect Codex app-server provider session:
  `019eea3d-fed6-7e32-9f2f-5cb39afa860d`;
- human intake:
  `chat.db#message=msg_a6c9cae7ea9a483abc3423c53ce0254e`;
- architect inbox:
  `chat_inbox_items#id=inbox_bef9bc6485af44b48166039d4087c06b`,
  `status = read`,
  `responded_message_id = msg_183b1337a5d44b8f92a8991ef0c1b26e`;
- real provider proposal message:
  `chat.db#message=msg_183b1337a5d44b8f92a8991ef0c1b26e`;
- lane graph proposal:
  `chat.db#proposal=prop_038ab28b77f94083959d22f37d527a9c`,
  `status = accepted`,
  `references = ["collaboration:collab_2fc0fe6651a94142859445efc7d7809b"]`;
- automatic review trigger:
  `chat_inbox_items#id=inbox_27e4675cda2b4aeaa1f6e55a79d370f0`,
  `status = read`,
  `responded_message_id = msg_94b4ed03bc26460c8ad237f2bd9cca0e`;
- review message:
  `chat.db#message=msg_94b4ed03bc26460c8ad237f2bd9cca0e`;
- approval resolution:
  `chat.db#resolution=res_3d19e6d8154b44769aef4d187f74f323`;
- dispatch queue entry:
  `chat_dispatch_queue#entry=dispatch:conv_bc4fa83561b042a489e80078e05882d5:res_3d19e6d8154b44769aef4d187f74f323:execute`,
  `status = queued`,
  `proposal_id = prop_038ab28b77f94083959d22f37d527a9c`,
  `collaboration_run_id = collab_2fc0fe6651a94142859445efc7d7809b`;
- latency trace:
  `peer_turn_latency_traces#trace=peer_latency_inbox_bef9bc6485af44b48166039d4087c06b`,
  `delivery_mode = mcp_writeback`,
  `degraded_reason = peer_writeback_before_provider_result`;
- MCP tool trace:
  `peer_turn_mcp_tool_traces#peer_mcp_tool_inbox_bef9bc6485af44b48166039d4087c06b_chat_emit_proposal`.

The observed provider stages were:

```text
chat_emit_proposal
codex_app_server_turn_start
inbox_claim
provider_session_started
ray_actor_delivery_start
scheduler_observed_durable_writeback
trace_persisted
```

This proves the P2 positive control-plane question: a real Ray/Codex app-server
architect can produce a durable `lane_graph` proposal through
`chat_emit_proposal`; the automatic review trigger can be handled durably; and
approval of the collaboration-backed proposal enqueues an execute dispatch
intent. It still does not prove final-action, GitHub gate acceptance, actual
execute-provider dispatch completion, accepted AcceptanceSpine truth, or
multi-turn soak stability.

## P3 Positive Execute Dispatch Completion Follow-up

Status: `real_provider_execute_dispatch_completion_accepted`.

Runtime root:

```text
.goal-runs/2026-06-21/p3-real-dispatch-completion-pytest-4/test_real_ray_codex_app_server0
```

Command:

```bash
timeout 900 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_proposal_review_dispatch_completion \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p3-real-dispatch-completion-pytest-4
```

Observed result:

```text
1 passed, 4 warnings in 368.93s
```

Report:

```json
{
  "conversation_id": "conv_5a3cc569a316410d804a91972c1adffc",
  "dispatch_entry_id": "dispatch:conv_5a3cc569a316410d804a91972c1adffc:res_12b67786d4674539b5779551bc7c5671:execute",
  "dispatch_evidence": "mcp_writeback:inbox_8bc4a91282094c6393575d3a7e6ad756",
  "dispatch_inbox_id": "inbox_8bc4a91282094c6393575d3a7e6ad756",
  "dispatch_provider_run_ref": "peer_ack:execute:part_027040b2664a4723bd151a4e598c5f11",
  "dispatch_status": "dispatched",
  "proposal_id": "prop_85f07b4d5c3044cfa543d6f700e5626e",
  "resolution_id": "res_12b67786d4674539b5779551bc7c5671"
}
```

Durable positive facts:

- architect Codex app-server provider session:
  `019eea58-fd9b-76a2-b1d7-b3e1960dc629`;
- execute Codex app-server provider session:
  `019eea5b-d4dc-7023-8d24-fa316d3bf99e`;
- proposal:
  `chat.db#proposal=prop_85f07b4d5c3044cfa543d6f700e5626e`;
- approval resolution:
  `chat.db#resolution=res_12b67786d4674539b5779551bc7c5671`;
- dispatch inbox:
  `chat_inbox_items#id=inbox_8bc4a91282094c6393575d3a7e6ad756`,
  `item_type = dispatch`,
  `status = read`,
  `responded_message_id = msg_317d509f78614acd90867dc36e1102b2`;
- execute ack message:
  `chat.db#message=msg_317d509f78614acd90867dc36e1102b2`,
  content includes `DISPATCH_ACKNOWLEDGED` and the dispatch entry id;
- dispatch queue entry:
  `chat_dispatch_queue#entry=dispatch:conv_5a3cc569a316410d804a91972c1adffc:res_12b67786d4674539b5779551bc7c5671:execute`,
  `status = dispatched`,
  `provider_run_ref = peer_ack:execute:part_027040b2664a4723bd151a4e598c5f11`,
  `dispatch_evidence = mcp_writeback:inbox_8bc4a91282094c6393575d3a7e6ad756`;
- dispatch latency trace:
  `peer_turn_latency_traces#trace=peer_latency_inbox_8bc4a91282094c6393575d3a7e6ad756`,
  `delivery_mode = mcp_writeback`,
  `degraded_reason = peer_writeback_before_provider_result`;
- dispatch MCP tool traces:
  `mcp_tool_call_started`,
  `chat_post_message`,
  `chat_post_message_persisted`,
  and `mcp_tool_call_completed` for the dispatch inbox.

The dispatch provider stages were:

```text
chat_post_message
chat_post_message_persisted
codex_app_server_turn_start
inbox_claim
mcp_tool_call_completed
mcp_tool_call_started
provider_session_started
ray_actor_delivery_start
scheduler_observed_durable_writeback
trace_persisted
```

This proves the next positive real-provider control-plane question: the queued
dispatch intent can be consumed by the platform dispatch bridge and completed
by a real execute Codex app-server peer through durable MCP
`chat_post_message` writeback. The prompt now explicitly rejects plain-text
acknowledgement as non-durable dispatch evidence. This still does not prove
final-action, GitHub gate acceptance, accepted AcceptanceSpine truth, or
multi-turn soak stability.

## P4 Final-Action Blocked-Path Attempt

Status: `blocked/provider_turn_cancelled_before_mcp_writeback`.

This follow-up added the product-side spine binding needed for the next real
provider closure cut: when a peer calls `chat_emit_proposal` with
`reply_to_inbox_item_id`, xmuse now attaches that proposal to the source human
intake AcceptanceSpine even if the model only supplies collaboration refs.

Fast deterministic checks:

```bash
uv run pytest \
  tests/xmuse/test_mcp_server.py::test_chat_emit_proposal_reply_attaches_acceptance_spine_intake \
  -q

uv run pytest \
  tests/xmuse/test_platform_runner.py::test_acceptance_gated_goal_run_blocks_without_server_side_merge_proof \
  -q

uv run ruff check \
  src/xmuse_core/chat/peer_service.py \
  tests/xmuse/test_mcp_server.py \
  tests/xmuse/test_full_chain_real_run.py
```

Observed result:

```text
1 passed, 1 warning in 2.03s
1 passed in 1.82s
All checks passed!
```

The real dispatch completion test was extended to assert the following terminal
path after dispatch completion:

1. the replied intake AcceptanceSpine has the proposal id, dispatch id, and
   dispatch evidence ref;
2. review verdict and final-action hold refs attach to the same spine;
3. `resolve_with_github_gate_evidence()` captures a producer-owned manual-gap
   GitHub gate record;
4. final approval without `server_side_merge_proof` leaves the spine
   `blocked/github_gate_unverified`.

Two real-provider attempts did not reach those new assertions because the
architect provider failed before emitting the first proposal tool call.

First attempt:

```bash
timeout 900 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_proposal_review_dispatch_completion \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p4-final-action-gate-blocked-pytest
```

Runtime root:

```text
.goal-runs/2026-06-21/p4-final-action-gate-blocked-pytest/test_real_ray_codex_app_server0
```

Observed result:

```text
FAILED ... AssertionError: expected 1 proposals
1 failed, 4 warnings in 205.62s
```

Durable negative facts:

- conversation `conv_25b074ada9084f9ba66439570dca029c`;
- intake message `msg_2ca3e441335c45e6a89cbda2866cf7a9`;
- architect inbox `inbox_89dcd47c4c0943739a7cb47ec949fa3b`;
- inbox status `failed`;
- latency trace `delivery_mode = failed`;
- latency trace `degraded_reason = provider_turn_cancelled_before_mcp_writeback`;
- zero proposal rows;
- zero MCP tool traces.

Second attempt:

```bash
timeout 900 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_proposal_review_dispatch_completion \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p4-final-action-gate-blocked-pytest-rerun
```

Runtime root:

```text
.goal-runs/2026-06-21/p4-final-action-gate-blocked-pytest-rerun/test_real_ray_codex_app_server0
```

Observed result:

```text
FAILED ... AssertionError: expected 1 proposals
1 failed, 4 warnings in 198.55s
```

Durable negative facts:

- conversation `conv_b1e6ae35a3dc4f3caf81bd94b8f147ad`;
- the test failed before any proposal was persisted;
- the new final-action/GitHub gate assertions were not reached.

This attempt does not invalidate the prior P3 dispatch-completion evidence, but
it also does not prove real-provider final-action closure. The next real
provider cut should first restore stable proposal MCP writeback, then rerun the
same extended test until it reaches the deterministic final-action blocked gate.

## P4 Proposal-Writeback Stability Attempt

Status: `blocked/provider_no_mcp_writeback_before_deadline`.

This follow-up addressed a prompt-contract conflict discovered after the first
P4 attempts: generic peer-chat instructions said to call `chat_post_message`
directly, while the P4 request explicitly required `chat_emit_proposal` and
forbade `chat_post_message`. xmuse now states that an explicit
`chat_emit_proposal` request takes priority over ordinary reply writeback, and
that `chat_emit_proposal` is the durable writeback for proposal turns.

Fast deterministic checks:

```bash
uv run pytest \
  tests/xmuse/test_ray_adapters.py::test_app_server_mcp_instructions_prefer_direct_post \
  tests/xmuse/test_peer_chat_prompt_builder.py::test_peer_chat_prompt_builder_emits_ordered_auditable_layers \
  -q

uv run ruff check \
  src/xmuse_core/agents/codex_app_server_transport.py \
  src/xmuse_core/chat/prompt_builder.py \
  src/xmuse_core/agents/codex_persistent.py \
  tests/xmuse/test_full_chain_real_run.py \
  tests/xmuse/test_ray_adapters.py \
  tests/xmuse/test_peer_chat_prompt_builder.py
```

Observed result:

```text
2 passed in 1.19s
All checks passed!
```

The real P4 test was attempted twice from this branch.

First attempt:

```bash
timeout 900 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_proposal_review_dispatch_completion \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p4-real-final-gate-stability-pytest
```

Observed result:

```text
FAILED ... AssertionError: expected 1 proposals
1 failed, 4 warnings in 205.98s
```

Durable negative facts:

- runtime root:
  `.goal-runs/2026-06-21/p4-real-final-gate-stability-pytest/test_real_ray_codex_app_server0`;
- conversation `conv_e8fec5d907ab4ac5abd3a8981b4e3343`;
- architect inbox `inbox_93ba1badadb94446a8be8d4e3955d6c6`;
- inbox status `failed`;
- latency trace `delivery_mode = failed`;
- latency trace `degraded_reason = provider_turn_cancelled_before_mcp_writeback`;
- zero proposal rows;
- zero MCP tool traces;
- empty stream content.

Second attempt temporarily doubled only the first proposal wait window to
separate a short test deadline from a provider writeback failure:

```bash
timeout 900 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_proposal_review_dispatch_completion \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p4-real-final-gate-stability-pytest-2
```

Observed result:

```text
FAILED ... AssertionError: expected 1 proposals
1 failed, 4 warnings in 386.98s
```

Durable negative facts:

- runtime root:
  `.goal-runs/2026-06-21/p4-real-final-gate-stability-pytest-2/test_real_ray_codex_app_server0`;
- conversation `conv_0f8ed01f968c4c7faa4247370ef79b22`;
- architect inbox `inbox_4cdc38c53ae14a839bd73f531ff0d108`;
- inbox status `failed`;
- latency trace `delivery_mode = failed`;
- latency trace `degraded_reason = provider_no_mcp_writeback_before_deadline`;
- failed intake spine
  `chat.db#acceptance_spine=goalrun_7ac67c2c6d024a72a099121fca0de107`;
- the spine contains execution evidence ref
  `peer_turn_latency_traces#trace=peer_latency_inbox_4cdc38c53ae14a839bd73f531ff0d108`;
- zero proposal rows;
- zero MCP tool traces;
- empty stream content.

The temporary longer wait was not kept as a default because it did not produce
proposal writeback and would make the focused real-provider gate slower. The
current blocker is therefore not final-action/GitHub gate logic; it is the real
Codex app-server provider failing to produce any MCP tool event or stream delta
for this proposal turn. P4 remains blocked until that first proposal writeback
is stable again.

## P4 App-Server First-Event Diagnostics

Status: `diagnostics_landed/no_claim_level_change`.

This follow-up does not claim P4 closure. It adds the missing diagnostic link
between the Codex app-server transport and scheduler failure traces: while an
app-server turn is still active, xmuse can now snapshot partial latency stages
such as `mcp_tools_ready`, `codex_app_server_turn_start`,
`first_stream_delta`, and MCP tool-call stages. On receive timeout or external
cancellation, the scheduler records those partial stages before aborting the
provider session and terminalizing the intake spine.

Fast deterministic checks:

```bash
uv run pytest \
  tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_exposes_partial_latency_stages \
  tests/xmuse/test_ray_adapters.py::test_ray_god_actor_core_can_use_injected_transport_without_child_process \
  tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_terminalizes_claim_and_spine_when_peer_turn_times_out \
  tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_terminalizes_claim_and_spine_when_peer_turn_is_cancelled \
  -q

uv run ruff check \
  src/xmuse_core/agents/codex_app_server_transport.py \
  src/xmuse_core/agents/ray_god_actor.py \
  src/xmuse_core/agents/ray_session_layer.py \
  src/xmuse_core/chat/peer_scheduler.py \
  tests/xmuse/test_ray_adapters.py \
  tests/xmuse/test_peer_chat_scheduler.py
```

Observed result:

```text
4 passed in 3.70s
All checks passed!
```

The next real-provider run should be a smaller first-proposal probe. Its value
is diagnostic even if it fails:

- if the failed trace contains no app-server stages, the failure is before
  app-server turn events reach xmuse;
- if it contains `mcp_tools_ready` but no tool call, the failure is model/tool
  selection after MCP readiness;
- if it contains `first_stream_delta` but no MCP tool call, the model is
  streaming text instead of using durable writeback;
- if it contains `chat_emit_proposal`, P4 can resume from the final-action gate
  assertion path.

## P4 First-Proposal Probe

Status: `first_proposal_probe_accepted/full_p4_still_blocked`.

The small real-provider first-proposal probe succeeded: a real Ray/Codex
app-server architect persisted a durable `lane_graph` proposal through
`chat_emit_proposal`.

Command:

```bash
timeout 420 uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_first_proposal_probe \
  -q -s \
  --basetemp=.goal-runs/2026-06-21/p4-first-proposal-probe-pytest
```

Observed result:

```text
1 passed, 4 warnings in 197.48s
```

Report:

```json
{
  "architect_id": "part_6f23ca6b80a04fd49de5160388bd564a",
  "conversation_id": "conv_7c49a999ce2c489db6ac2c1f97246ce3",
  "inbox_item_id": "inbox_74df691aa5b3428b91ff4ffda0c27116",
  "result": {
    "classification": "proposal_persisted",
    "proposal_id": "prop_c776c4dfe72c4cdc9f0db7893856f0f4"
  }
}
```

Runtime root:

```text
.goal-runs/2026-06-21/p4-first-proposal-probe-pytest/test_real_ray_codex_app_server0
```

After the successful probe, the full P4 final-action blocked path was attempted
twice. Both attempts still failed before proposal persistence. The useful new
fact from #166 is that the failure is now classified as app-server MCP-ready
but no tool call:

```text
observed stages:
codex_app_server_turn_start
first_visible
inbox_claim
mcp_tools_ready
provider_session_started
ray_actor_delivery_start
stream_started
trace_persisted
```

No `chat_emit_proposal`, no MCP tool trace, no stream delta, and no proposal row
were recorded. The first failed full-P4 attempt used:

```text
.goal-runs/2026-06-21/p4-final-gate-after-probe-pytest/test_real_ray_codex_app_server0
```

and produced failed spine:

```text
chat.db#acceptance_spine=goalrun_aa32e1ff06944d778977c8fc4330f19b
```

The second failed full-P4 attempt used:

```text
.goal-runs/2026-06-21/p4-final-gate-after-probe-pytest-2/test_real_ray_codex_app_server0
```

and produced failed spine:

```text
chat.db#acceptance_spine=goalrun_3fe82c41ae4c40ee91f2a96a3e0cc2fb
```

This narrows the next blocker: first-proposal writeback can succeed in a small
probe, but the complete P4 setup remains unstable at model/tool selection after
MCP readiness. P4 remains blocked until the full path consistently reaches
`chat_emit_proposal`, then continues through dispatch completion and the
final-action GitHub manual-gap gate.
