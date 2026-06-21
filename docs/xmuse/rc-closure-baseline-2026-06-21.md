# xmuse RC Closure Baseline - 2026-06-21

This document freezes the staged closure claim for `main` at:

```text
3814350 fix: harden acceptance spine evidence authority
```

## Closure Claim

This baseline originally staged xmuse as:

```text
xmuse RC: durable GOD groupchat + AcceptanceSpine closure skeleton
```

This means the project has crossed from a durable groupchat runtime into a
minimal GoalRun/AcceptanceSpine closure contract. It does not mean production
GitHub-gated delivery is complete.

After P0-P3 on 2026-06-21, the stronger current claim is recorded in
`docs/xmuse/release-checklist.md`:

```text
xmuse production-closure short path accepted
```

That stronger claim is limited to a short `--goal --acceptance-gate` path with
opt-in live GitHub server-side capture. It does not supersede the remaining
full-release blockers: multi-hour real-provider soak, release
packaging/versioning, and known type debt.

## Completed RC Facts

- Durable GOD groupchat remains the control plane: human demand enters chat,
  persists in `chat.db`, routes through inbox/scheduler/GOD sessions, and writes
  durable evidence back through MCP/chat stores.
- `acceptance_spines` now records the minimal closure path for a human demand:
  intake, proposal, approval verdict, dispatch refs, dispatch evidence refs,
  review-plane verdict, final-action hold, GitHub gate evidence or manual gap,
  and terminal `accepted` / `blocked` / `failed` state.
- AcceptanceSpine read access is exposed through a read-only Chat API endpoint.
  Dashboard, TUI, timeline projections, stdout, fake demos, sentinel scripts,
  and copied GitHub summaries are not authority.
- `GitHubGateEvidenceStore` persists producer-owned evidence records in
  `github_gate_evidence.json`. Only records with complete
  `server_side_merge_proof` can set `can_accept = true`.
- `FinalActionGateStore` and `AcceptanceSpineStore` both reject arbitrary GitHub
  evidence refs. A ref can accept the spine only when it points at a durable
  accepted evidence record for the same final action.
- CI now runs AcceptanceSpine and GitHub server gate contract tests in the
  focused runtime gate.

## Forbidden Claims

Do not claim:

- full production release ready;
- multi-hour real-provider/Ray/Codex soak complete;
- live GitHub PR/CodeOwner review enforcement closed when the repository has
  `required_pull_request_reviews = null`;
- real long-running final-action runtime has been soaked for many hours;
- a formal release has been cut;
- fake demo, stdout, dashboard, TUI, or copied GitHub text is acceptance truth;
- `accepted` is valid without producer-backed `server_side_merge_proof`.

## Remaining Boundary

The remaining boundary is runtime and server-side, not the local closure
skeleton:

```text
real long-run final-action path
-> authenticated read-only GitHub capture
-> branch protection / ruleset / required checks / review truth
-> server_side_merge_proof or durable manual gap
-> accepted / blocked / failed terminal spine state
```

The short opt-in live capture path has captured complete
`server_side_merge_proof` and can end as `accepted`; runs without that producer
evidence must still remain blocked with `github_gate_unverified`.

## Next Cut

The next product cut should not expand providers, TUI, or dashboard first. It
should close the live GitHub gate and real final-action invocation boundary:

1. Run a bounded multi-hour real-provider soak through the same
   acceptance-gated path and keep the terminal state durable.
2. Decide release packaging/versioning only after the soak evidence is accepted
   or explicitly blocked.
3. Pay down known release blockers such as the existing
   `uv run mypy xmuse/platform_runner.py` type debt before claiming a full
   production release.
