"""Fixed evaluation tasks for the broadcast-vs-addressed Room eval harness.

This module is the source of truth for the seven task prompts and their pre-registered
rubrics from ``docs/xmuse/eval-design.md`` §1.  The T3 postmortem and the T5 failure log
are frozen in-code appendix texts so every run posts byte-identical prompts.

Pure data plus a few pure helpers; no imports outside the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass

POSTMORTEM_APPENDIX = (
    "Appendix A - Incident postmortem (fixed, fictional)\n"
    "\n"
    "Incident PM-2026-08: duplicate settlement emails after retry storm\n"
    "Date: 2026-08-14, 02:04-03:41 UTC. Duration: 97 minutes. Severity: SEV-2.\n"
    "Systems: billing-api (Go), notification-worker (Python), ledger db (Postgres 15).\n"
    'Impact: 6,214 customers received a duplicate "payment settled" email; 412 of those\n'
    'also saw a transient "payment failed" status that self-corrected. No money moved\n'
    "twice; ledger balances verified correct within 11 minutes of recovery.\n"
    "\n"
    "Detection: support ticket volume alert (Zendesk >40 tickets/10 min) fired at 02:19,\n"
    "15 minutes after the first duplicate. The synthetic transaction monitor was green\n"
    "throughout because it never asserts email uniqueness.\n"
    "\n"
    "Timeline (UTC):\n"
    "- 01:57 - Ledger primary fails over after a 4s network partition; writes queue on the\n"
    "  billing-api side.\n"
    "- 02:04 - notification-worker's settlement poller calls billing-api\n"
    "  POST /settlements/notify; 43 requests time out at the 30s mark while the failover\n"
    "  completes.\n"
    "- 02:04-02:31 - Worker retries each timed-out request every 20s with no idempotency\n"
    "  key. billing-api accepts the duplicates because the notify handler writes an\n"
    '  "email queued" row and returns 202, then enqueues to SQS; queue dedup window is\n'
    "  only 5 minutes.\n"
    "- 02:19 - Support alert fires; on-call begins triage.\n"
    "- 02:31 - First duplicate emails go out; poller is still retrying 61 in-flight\n"
    "  requests.\n"
    "- 02:47 - On-call pauses the notification-worker via feature flag\n"
    "  notify_settlement_enabled=false.\n"
    "- 03:12 - Root cause identified; ledger reconciliation confirms balances are correct;\n"
    "  duplicate emails traced to missing idempotency keys.\n"
    "- 03:41 - Retry backlog drained; duplicate volume reaches zero.\n"
    "\n"
    "Root cause: the settlement poller was rewritten three weeks earlier (PR #4821) to\n"
    '"retry aggressively on any 5xx or timeout." The rewrite dropped the X-Idempotency-Key\n'
    "header that the legacy poller sent, and billing-api's notify handler never required\n"
    "the key. The queue-level dedup window (5 minutes) is shorter than the retry window\n"
    "(20s x 40 attempts, about 13 minutes), so late retries slipped past dedup.\n"
    "\n"
    "Contributing factors:\n"
    "1. No contract test asserted that the poller sends an idempotency key; PR #4821\n"
    "   removed the header and CI stayed green.\n"
    "2. billing-api's 202 response does not echo a dedup token, so the poller had no way\n"
    "   to detect an accepted duplicate.\n"
    "3. The synthetic monitor checks availability and latency only; email semantics are\n"
    "   untested in staging.\n"
    "\n"
    "What went well: failover itself completed in 4s; reconciliation tooling verified\n"
    "ledger integrity in 11 minutes; the feature flag allowed a fast stop of outbound\n"
    "email.\n"
    "\n"
    "Action items:\n"
    "- AI-1 (billing-api): require X-Idempotency-Key on POST /settlements/notify, reject\n"
    "  missing keys with 400. Owner: Billing team. Status: shipped 2026-08-19.\n"
    "- AI-2 (notification-worker): restore the idempotency key; persist per-event send\n"
    "  state keyed by settlement id. Owner: Notifications team. Status: shipped\n"
    "  2026-08-20.\n"
    "- AI-3 (SRE): extend the synthetic monitor to assert exactly-one email per settlement\n"
    "  via a test mailbox. Owner: SRE. Status: in progress, due 2026-09-05.\n"
    "- AI-4 (both): add a contract test for the notify request schema. Owner: Billing +\n"
    "  Notifications. Status: shipped 2026-08-21.\n"
    "- AI-5 (data): backfill a reconciliation report of the 6,214 affected customers for\n"
    "  support. Owner: Data. Status: done 2026-08-16.\n"
    "\n"
    "Lessons: the missing contract test was the single highest-leverage gap; retries\n"
    "without idempotency turned a 4s failover into 97 minutes of customer-visible noise.\n"
    "\n"
    'Residual risk (verbatim from the postmortem document): "The dedup window and retry\n'
    "policy are still configured independently in two repositories; the current values\n"
    "happen to be compatible (400 attempts x 20s stays within the 30-minute queue dedup\n"
    "window), but nothing enforces that relationship. The next tuning change to either\n"
    "side can reintroduce duplicate sends, and the only current guard is the extended\n"
    'synthetic monitor (AI-3), which is not yet shipped."'
)

FAILURE_LOG_APPENDIX = (
    "Appendix B - MCP tool-client failure log (fixed, fictional)\n"
    "\n"
    "Observed 2026-08-02 through 2026-08-09; client mcp-client 0.9.3 calling three\n"
    "upstream tool servers (registry, search, calc); about 12,400 calls.\n"
    "\n"
    '1. Timeouts: 214 calls ended in "read timeout after 30s" to the search server under\n'
    "   the 09:00-09:20 load burst; bursts lasted 6-18 minutes on 5 of 8 days. Of those,\n"
    "   187 succeeded when manually retried after 1-2 minutes. Server logs show GC pauses\n"
    "   of 12-22s, not crashes. The client has no automatic retry for reads; the runbook\n"
    "   relies on manual operator retries.\n"
    "2. HTTP 429 rate limiting: 391 calls to the registry server returned\n"
    '   "429 Too Many Requests" with a Retry-After header present in 96% of cases\n'
    "   (values 2-45s). Bursts reached 900+ calls/minute during CI fan-out on Aug 6. The\n"
    "   client ignores Retry-After and backs off a flat 1s, so 38% of the immediate\n"
    "   retries were rejected again.\n"
    "3. Partial writes / lost responses: 27 POST /jobs calls to the calc server were\n"
    "   durably accepted (each job appears in the job list) but the HTTP response never\n"
    '   arrived (client saw "remote disconnected"). Blind manual resends created 9\n'
    "   duplicate jobs before a human noticed.\n"
    "4. Clock skew: 3 hosts ran 4-11 minutes ahead after the Aug 3 maintenance window\n"
    "   left one rack's NTP client pointed at a decommissioned internal address; the\n"
    "   other two drifted after a reboot. Their signed time-based credentials\n"
    "   (X-Tool-Timestamp) were rejected by the search server with\n"
    '   "401 timestamp_out_of_window" (113 calls), because the server accepts a\n'
    "   +/-5 minute window.\n"
    "\n"
    'Other noise, not retry-worthy: 41 "400 invalid_argument" responses from malformed\n'
    'agent-supplied arguments; 12 "404 tool_not_found" after a registry rollout. These\n'
    "should fail fast, not be retried.\n"
    "\n"
    "Totals: 745 retry-worthy failures (214 + 391 + 27 + 113) out of about 12,400 calls;\n"
    "53 fail-fast responses excluded."
)

RUBRIC_ANCHORS: dict[str, str] = {
    "3": "fully correct and complete with no fabrication",
    "2": "correct core with a minor omission",
    "1": "partially useful with a real error or fabrication",
    "0": "wrong, refused, or empty",
}


@dataclass(frozen=True)
class EvalTask:
    """One fixed evaluation task from the pre-registered design."""

    task_id: str
    exercises: str
    instruction: str
    appendix: str | None
    expected_roles: tuple[str, ...]
    expected_ordered: bool
    must_hit: tuple[str, ...]
    notes: str

    @property
    def prompt(self) -> str:
        """The exact Human message posted to the Room."""
        if self.appendix is None:
            return self.instruction
        return f"{self.instruction}\n\n{self.appendix}"


TASKS: tuple[EvalTask, ...] = (
    EvalTask(
        task_id="T1",
        exercises="design critique",
        instruction=(
            "Critique this login screen description; rank the top 3 usability risks with "
            "one concrete fix each. Screen: full-page centered card; email + password "
            "fields; 'Remember me' checked by default; no password visibility toggle; "
            "errors appear next to the submit button only after a 3-second spinner; "
            "'Forgot password' is a 12px gray-on-white link."
        ),
        appendix=None,
        expected_roles=(),
        expected_ordered=False,
        must_hit=(
            "3 ranked usability risks",
            "one concrete fix per risk",
            "at least 1 risk mentions error placement or contrast/visibility",
        ),
        notes="Open critique; rewards cross-checking; any specialist may answer.",
    ),
    EvalTask(
        task_id="T2",
        exercises="bug reasoning",
        instruction=(
            "Find the root cause of this bug and give a minimal fix plus one regression "
            "test. Code: `def merge_sessions(a, b, meta={}): meta.update(a); "
            "meta.update(b); return meta` - called as `merge_sessions(x, y)` twice; the "
            "second caller sees keys from the first call. No other context exists."
        ),
        appendix=None,
        expected_roles=("architect",),
        expected_ordered=False,
        must_hit=(
            "mutable-default root cause",
            "minimal fix (e.g. meta=None or dict copy)",
            "regression test that fails before / passes after",
        ),
        notes="Single-specialist answer expected from the lead.",
    ),
    EvalTask(
        task_id="T3",
        exercises="research/summarize",
        instruction=(
            "Summarize the attached incident postmortem (Appendix A) in 5 bullets, then "
            "state the single highest residual risk and one counter-argument to your own "
            "summary."
        ),
        appendix=POSTMORTEM_APPENDIX,
        expected_roles=("research",),
        expected_ordered=False,
        must_hit=(
            "5 faithful bullets with no invented facts",
            "residual risk traceable to the postmortem text",
            "a counter-argument to the summary is present",
        ),
        notes="Long-context faithfulness; researcher specialist expected.",
    ),
    EvalTask(
        task_id="T4",
        exercises="trade-off decision",
        instruction=(
            "Decide for a single-user local desktop workroom on one machine: single "
            "SQLite WAL room store vs. a small Postgres service. Constraints: <5 "
            "concurrent rooms, durability matters, zero ops budget. Recommend one, give "
            "exactly 2 tradeoffs, and the trigger that would make you revisit."
        ),
        appendix=None,
        expected_roles=("architect",),
        expected_ordered=False,
        must_hit=(
            "clear recommendation",
            "exactly 2 real tradeoffs",
            "specific revisit trigger",
        ),
        notes="Decision task; lead specialist expected.",
    ),
    EvalTask(
        task_id="T5",
        exercises="handoff chain (research -> plan -> review)",
        instruction=(
            "Sequential outputs, one each: 1) researcher: from the failure log summary "
            "below list the top 4 retry-worthy failure modes; 2) lead: a 10-step plan to "
            "add rate-limited retries to an MCP tool client covering those modes; 3) "
            "reviewer: audit the plan against each failure mode and list gaps. Log "
            "(Appendix B):"
        ),
        appendix=FAILURE_LOG_APPENDIX,
        expected_roles=("research", "architect", "review"),
        expected_ordered=True,
        must_hit=(
            "4 retry-worthy failure modes listed",
            "plan covers all 4 modes",
            "reviewer finds at least 1 real gap and does not rubber-stamp",
        ),
        notes="Designed handoff task; in addressed mode expect A->B->A, causal depth <= 4.",
    ),
    EvalTask(
        task_id="T6",
        exercises="noise trap",
        instruction=(
            "Acknowledgment checkpoint. Reply with exactly one line confirming you read "
            "this, then stop. No analysis, no questions, no suggestions."
        ),
        appendix=None,
        expected_roles=(),
        expected_ordered=False,
        must_hit=(
            "at most 1 substantive message per agent",
            "no analysis content",
        ),
        notes="Designed noise probe; scored mechanically, not by a judge.",
    ),
    EvalTask(
        task_id="T7",
        exercises="cross-vendor patch review",
        instruction=(
            "Review this diff (read-only). List defects ranked by severity with a fix "
            'each: `-def final_amount(cents: int) -> str: return f"${cents/100:.2f}"` '
            "`+def final_amount(amount: float) -> float: return amount * 1.0825` - used "
            "for money totals later summed and displayed."
        ),
        appendix=None,
        expected_roles=("review",),
        expected_ordered=False,
        must_hit=(
            "float-money / rounding defect",
            "type/regression risk against existing callers",
            "at least 1 concrete fix",
            "no invented context",
        ),
        notes="Cross-vendor patch review; reviewer specialist expected.",
    ),
)


def tasks_by_id() -> dict[str, EvalTask]:
    return {task.task_id: task for task in TASKS}


def select_tasks(spec: str | None) -> list[EvalTask]:
    """Resolve ``--tasks`` (comma list or ``all``) into EvalTask objects."""
    if spec is None or spec.strip().lower() in {"", "all"}:
        return list(TASKS)
    known = tasks_by_id()
    selected: list[EvalTask] = []
    for raw in spec.split(","):
        task_id = raw.strip().upper()
        if not task_id:
            continue
        if task_id not in known:
            raise ValueError(f"unknown task id: {task_id!r}")
        selected.append(known[task_id])
    if not selected:
        raise ValueError("--tasks selected no tasks")
    return selected
