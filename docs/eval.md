# Board reliability evaluation (`xmuse-eval board`)

The product claim is that an Agent's `done` is not trustworthy: the host
verifies it, a different vendor reviews it, and integration conflicts go
back to the owner. This evaluation measures all three mechanisms in-repo,
from the same `room_board_projection` derivation (counters of
`docs/contracts/room_board_projection_v2.md` §6) that the UI consumes.

## What each scenario measures

| Scenario | Measures |
| --- | --- |
| `revision` | Contract drift: the backend revises `api.greeting` to v2 and the dependent frontend realigns in the same provider session. |
| `verify` | Host verification of `done`: every module must end host-verified and every verification wake-up must reuse the owner's session. False claims on the way are the measurement (`verification_loop`). |
| `false-done` | Fault injection: the backend is told to report `done` on a breaking stub. The host must fail the verification in a gate, wake the owner in the same session, and pass the fix. |
| `review` | Cross-family review (`review_policy: cross_family`): every module must end verified and endorsed by a different-family reviewer; objections must be followed by fixes. |
| `integration` | Shared-file conflict: both charters cover `src/shared/flags.py` and both owners change the same line. Both pass verification, the host integration worker leaves the newcomer `conflicted` and wakes its owner (`board.integration`), and the run ends when both modules are `integrated`. Only if the host's wake-up does not get there does the smoke post one fallback Human fix request (`integration_loop.human_nudged`); the Human message never counts as the owner being woken. The user's checkout must stay byte-identical for the whole run. |

Every scenario's summary carries per-module `modules` (§6 counters plus final
`state`, `accepted`, `integration_status` from the projection), `models`,
`provider_kinds`, wall seconds, `ok` and the checks.

The table's metrics, summed over modules and runs:

- claimed → verified: modules ending host-verified / `done` reports.
- false done intercepted: failed host verifications (`counters.failed`).
- mean rework: failed verifications before a module's first pass, per module.
- objected = review catches: cross-family objections.
- mean fix rounds: conflict fix rounds, over modules that conflicted at least once.

## How to run

`xmuse-eval` runs from a source checkout (`uv sync --all-groups`, then `uv run xmuse-eval`):
it drives `scripts/`, which the wheel does not ship.

```bash
xmuse-eval board --scenarios verify,false-done,review,integration --repeat 3 --out /tmp/xmuse-board-eval
```

Each run is one `scripts/board_owners_smoke.py` subprocess with `--result`
(a per-run timeout applies; runs are sequential). Failed or timed-out runs
are recorded, never fatal. The report is `/tmp/xmuse-board-eval/report.json`
(`board_eval_report/v1`) plus `report.md` with the one Markdown table.
Per-run results live under `runs/`, logs under `logs/`.

To re-aggregate without running anything (offline):

```bash
xmuse-eval board --scenarios verify,integration --from-results /tmp/xmuse-board-eval/runs --out /tmp/xmuse-board-eval-again
```

`review` needs two model families for the cross-family rule, so eval runs it
with `--frontend-cli claude` when the default `opencode` frontend is in
effect; the switch is recorded per run in the report.

## Cost and duration

Every run drives real provider agents (lead plus two owners) through live
turns, verifications, and — for `integration` — integration jobs with real
gates. Expect minutes per run and up to roughly an hour per run at the
default phase timeouts; `--repeat 3` over four scenarios is a
provider-billed, long-running operation. Never run eval in CI.

## Threats to validity

- Small n: the table states n per cell and never claims significance.
- Model nondeterminism: agents may take different paths (extra rework
  rounds, different fix shapes, timeouts) between repeats.
- Same-vendor judge absent: there is no LLM judge. Completion is decided by
  the host's server-owned gates (verification, integration), which is the
  product behavior under test, not an independent oracle.
- The split is operator-approved and the seed repository is a toy
  (`python-uv/v1` markers plus two contract files); results do not transfer
  to arbitrary workspaces.
