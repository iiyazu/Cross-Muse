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
