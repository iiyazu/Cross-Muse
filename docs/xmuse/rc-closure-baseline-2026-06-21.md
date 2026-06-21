# xmuse RC Closure Baseline - 2026-06-21

This document freezes the staged closure claim for `main` at:

```text
3814350 fix: harden acceptance spine evidence authority
```

## Closure Claim

xmuse can now be staged as:

```text
xmuse RC: durable GOD groupchat + AcceptanceSpine closure skeleton
```

This means the project has crossed from a durable groupchat runtime into a
minimal GoalRun/AcceptanceSpine closure contract. It does not mean production
GitHub-gated delivery is complete.

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

- production GitHub-gated delivery complete;
- live GitHub branch protection / required-check / CodeOwner enforcement closed;
- real long-running final-action runtime uniquely invokes the GitHub producer;
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

Until that path captures complete `server_side_merge_proof`, xmuse must keep
the spine blocked with `github_gate_unverified`.

## Next Cut

The next product cut should not expand providers, TUI, or dashboard first. It
should close the live GitHub gate and real final-action invocation boundary:

1. Close or explicitly re-block issue #37 with current authenticated GitHub
   evidence.
2. Ensure every real final-action runtime path calls
   `resolve_with_github_gate_evidence()` or an equivalent producer-owned path.
3. Expose one operator-facing acceptance-gated runtime contract that returns
   only durable `accepted`, `blocked`, or `failed` terminal truth.
