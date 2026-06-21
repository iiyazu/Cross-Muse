# Production Closure Tasks

Updated: 2026-06-21

These tasks start from the RC baseline in
`docs/xmuse/rc-closure-baseline-2026-06-21.md`. They define what remains before
xmuse can claim production-grade closure.

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

Tasks:

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

Tasks:

- update `docs/xmuse/release-checklist.md` with AcceptanceSpine/GitHub gate
  requirements;
- decide whether to cut a release or keep the project at RC;
- ensure README and docs do not overstate production readiness;
- record release evidence or the reason release remains blocked.

Acceptance:

- repository release state, README wording, CI state, and closure docs all use
  the same claim level.
