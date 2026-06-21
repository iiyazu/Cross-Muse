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
