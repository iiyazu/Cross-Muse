# Production Closure Tasks

Updated: 2026-06-21

These tasks start from the RC baseline in
`docs/xmuse/rc-closure-baseline-2026-06-21.md`. They define what remains before
xmuse can claim production-grade closure. As of 2026-06-21, P0-P3 establish a
short-run production-closure path with live GitHub accepted evidence. They do
not establish full release readiness or a multi-hour provider soak.

## P0 - Close Live GitHub Server Gate Evidence

Goal: close issue #37 or leave it explicitly blocked with fresh command
evidence.

Status: closed for required-check enforcement on 2026-06-21 by
`docs/xmuse/github-server-side-gate-live-evidence-2026-06-21.md`. GitHub
PR/CodeOwner review enforcement is explicitly absent
(`required_pull_request_reviews = null`), and xmuse policy uses verified
internal review truth when GitHub does not require PR review.

Tasks:

- capture authenticated read-only GitHub evidence for `main` branch protection
  or applicable rulesets;
- prove required checks are server-required, not merely successful check runs;
- prove CodeOwner / PR review enforcement when the repository policy requires
  it;
- prove workflow/status visibility for the exact checks used by xmuse gates;
- persist the captured facts as durable evidence, not copied UI text;
- update `docs/xmuse/github-server-side-gate.md` and issue #37 with the result.

Acceptance:

- complete evidence can produce `server_side_merge_proof`; or
- incomplete evidence leaves the issue and the spine blocked with a concrete
  `github_gate_unverified` reason.

## P1 - Force Real Final-Action Runtime Through the Producer

Goal: no real runtime path can mark a demand accepted without producer-owned
GitHub gate evidence.

Status: closed for the short acceptance-gated runtime on 2026-06-21. Final
action approval without producer-owned `server_side_merge_proof` remains
blocked, and the opt-in live capture path accepts only through
`resolve_with_github_gate_evidence()` and authority-verified
`github_gate_evidence.json` records.

Tasks:

- audit all callers of final-action resolution and acceptance-spine terminal
  updates;
- route real runner/review/final-action closure through
  `resolve_with_github_gate_evidence()` or a single equivalent producer API;
- preserve manual approval as an input to the producer path, not as acceptance
  authority;
- add a focused regression test for any legacy or script path that can bypass
  the producer.

Acceptance:

- arbitrary `github_gate_evidence_ref` remains blocked at both final-action and
  AcceptanceSpine authority layers;
- real closure without producer-owned `server_side_merge_proof` can only end as
  `blocked/github_gate_unverified` or `failed`.

## P2 - Add One Acceptance-Gated Runtime Contract

Goal: operators have one durable way to run a demand to terminal truth.

Status: minimal blocked-path command implemented on 2026-06-21. Evidence:
`docs/xmuse/acceptance-gated-runner-evidence-2026-06-21.md`. The command can
create a durable human intake spine, proposal, dispatch evidence, review
verdict, final-action hold, and producer-owned GitHub gate evidence. Without
`server_side_merge_proof`, the terminal result is `blocked/github_gate_unverified`.

Candidate shape:

```bash
uv run xmuse-platform-runner --goal "<human demand>" --acceptance-gate
```

Tasks:

- bind the command to a durable human intake spine;
- run proposal, dispatch, review, final-action, and GitHub gate capture against
  that same spine;
- emit a compact terminal summary from durable stores only;
- return only `accepted`, `blocked`, or `failed`.

Acceptance:

- no terminal success is printed from stdout-only evidence;
- the command can be re-run or inspected after interruption through durable
  state.

## P3 - Prove Real Long-Run Invocation

Goal: demonstrate the production path with real configured peers and GitHub
capture, not only deterministic test doubles.

Status: short-run live GitHub capture accepted path implemented on 2026-06-21.
Evidence: `docs/xmuse/acceptance-gated-live-capture-evidence-2026-06-21.md`.
The command uses opt-in read-only `gh api` capture and can produce
producer-owned `server_side_merge_proof`. This proves the short acceptance-gated
terminal path, not a multi-hour provider soak.

Update: bounded real-provider/Ray/Codex soak was attempted on 2026-06-21 and is
blocked. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md`. The run entered the
Ray/Codex app-server path and persisted groupchat/session state, but failed
before the first durable MCP `chat_post_message` reply. The claim level is not
raised.

Follow-up: provider response timeout terminalization is now implemented for the
peer-chat scheduler boundary. A timeout marks the claimed inbox item failed,
records a failed peer latency trace, and marks the original intake
AcceptanceSpine failed with that trace ref. This closes the previous classifier
gap for timeout failures only; P3 remains blocked until the bounded real
provider soak is rerun and reaches durable writeback/review/final-action/GitHub
gate evidence.

Instrumentation follow-up: the real provider writeback path now records
additional peer-turn stages for the next positive-path repair:
`provider_session_started`, `provider_raw_result_received`,
`mcp_tool_call_detected`, `mcp_tool_call_started`,
`mcp_tool_call_completed`, `chat_post_message_persisted`, and
`scheduler_observed_durable_writeback`. This is diagnostic evidence only. It
does not prove that the real provider positive path succeeds; it narrows the
next failure to provider output, MCP transport, chat store persistence, or
scheduler observation.

Positive writeback follow-up: P1 is now accepted for the bounded one-turn /
restart-resume path. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p1-positive-writeback-follow-up`.
The focused real Ray/Codex app-server test produced two durable MCP
`chat_post_message` replies, read inbox items with `responded_message_id`,
`mcp_writeback` latency traces, `chat_post_message_persisted` tool stages, and
provider session reuse across restart/resume. This closes only the first
positive writeback question. P3 remains blocked until the real provider path
continues through proposal/review/dispatch, final-action, and GitHub gate
evidence.

Proposal/review/dispatch follow-up: P2 is now accepted for the bounded
real-provider control-plane path. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p2-positive-proposal--review--dispatch-follow-up`.
The focused real Ray/Codex app-server test produced a durable `lane_graph`
proposal via `chat_emit_proposal`, handled the automatic review trigger, approved
the collaboration-backed proposal, and enqueued an execute dispatch intent. This
closes the next positive control-plane question. P3 remains blocked until the
real provider path continues through actual execute-provider dispatch
completion, final-action, GitHub gate evidence, accepted AcceptanceSpine truth,
and multi-turn soak stability.

Execute dispatch completion follow-up: P3 is now accepted for the bounded
real-provider dispatch-bridge path. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p3-positive-execute-dispatch-completion-follow-up`.
The focused real Ray/Codex app-server test consumed the queued dispatch intent,
created a dispatch inbox for execute, required durable `chat_post_message`
acknowledgement, and marked the dispatch queue entry `dispatched` with
`provider_run_ref` and `mcp_writeback:<dispatch_inbox>` evidence. P3 remains
blocked for final-action, GitHub gate evidence, accepted AcceptanceSpine truth,
and multi-turn soak stability.

Final-action blocked-path follow-up: the `chat_emit_proposal` reply path now
binds the proposal to the replied intake AcceptanceSpine even when the model
does not include an `intake_message:<id>` reference. The deterministic
acceptance-gated runner still proves that final-action approval without
producer-owned `server_side_merge_proof` terminalizes as
`blocked/github_gate_unverified`. Two attempts to extend the real dispatch
completion test through final-action/GitHub gate on 2026-06-21 failed before
the first provider MCP proposal writeback with
`provider_turn_cancelled_before_mcp_writeback`; therefore this does not raise
the real-provider claim level. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p4-final-action-blocked-path-attempt`.

P4 proposal-writeback stability follow-up: the prompt contract now explicitly
prioritizes `chat_emit_proposal` over ordinary `chat_post_message` when the
inbox request asks for proposal emission. A focused real-provider rerun still
failed before any proposal, MCP tool trace, or stream delta was produced, ending
as `provider_no_mcp_writeback_before_deadline`. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p4-proposal-writeback-stability-attempt`.

P4 first-event diagnostics follow-up: app-server partial latency stages are now
available to scheduler timeout/cancellation traces before the provider session
is aborted. The next failed real proposal turn should show whether xmuse saw
`mcp_tools_ready`, turn start, stream delta, or MCP tool-call events. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p4-app-server-first-event-diagnostics`.

P4 first-proposal probe follow-up: a small real-provider probe reached durable
`chat_emit_proposal` and persisted a proposal, but the complete P4 path still
failed before proposal persistence. The failed full-P4 trace now contains
`mcp_tools_ready` and `codex_app_server_turn_start`, but no stream delta and no
MCP tool call. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p4-first-proposal-probe`.

P4 tool-choice stability follow-up: one complete real Ray/Codex app-server P4
run reached durable proposal writeback, manual review approval, dispatch MCP
writeback, AcceptanceSpine linkage, and a final-action hold with
`blocked/github_gate_unverified`. A later rerun still reached proposal/review
approval but exposed an execute dispatch acknowledgement flake:
`mcp_tools_ready` and streamed text were observed, but no `chat_post_message`
tool trace, so the dispatch queue failed with `peer_no_inbox_side_effect`.
The dispatch prompt now explicitly forbids claiming MCP writeback tools are
unavailable and requires both acknowledgement and failure acknowledgement to use
`chat_post_message`; the targeted rerun passed after that hardening. Evidence:
`docs/xmuse/real-provider-soak-evidence-2026-06-21.md#p4-tool-choice-stability-and-final-action-gate`.

Tasks:

- preserve the complete P4 real-provider gate as current RC evidence:
  proposal -> review -> dispatch -> final-action hold ->
  `blocked/github_gate_unverified`;
- use further reruns only to build soak confidence or verify a concrete
  production-closure change, not as blind flake hunting;
- add or prove a producer-owned `server_side_merge_proof` path before raising
  the claim from blocked RC evidence to accepted production closure;
- run one bounded long-running demand through the acceptance-gated path;
- record the runtime root, command, PR or no-PR outcome, final-action record,
  GitHub gate evidence record, and resulting spine status;
- classify any blocker as provider, transport, review, GitHub, or policy;
- update the RC baseline only if the durable evidence supports a stronger
  claim.

Acceptance:

- success requires producer-backed `server_side_merge_proof`;
- otherwise the run is still valuable only if it lands in durable
  `blocked/<reason>` or `failed/<reason>` state.

## P4 - Release Readiness

Goal: distinguish a production closure claim from a release candidate claim.

Status: release decision recorded on 2026-06-21. xmuse is not full
release-ready. The current claim is `production-closure short path accepted`:
durable GOD groupchat plus minimal AcceptanceSpine/GoalRun plus opt-in live
GitHub server-side gate accepted path. Full release remains blocked on
multi-hour real-provider soak evidence, release packaging/versioning, and known
type debt including `uv run mypy xmuse/platform_runner.py`.

Tasks:

- update `docs/xmuse/release-checklist.md` with AcceptanceSpine/GitHub gate
  requirements; done on 2026-06-21;
- decide whether to cut a release or keep the project at RC; decision: do not
  cut a full release yet;
- ensure README and docs do not overstate production readiness; current wording
  uses the short-path claim level;
- record release evidence or the reason release remains blocked; current
  blockers are recorded in `docs/xmuse/release-checklist.md`.

Acceptance:

- repository release state, README wording, CI state, and closure docs all use
  the same claim level.
