"""Pure metric functions over one exported eval transcript.

Every function takes a transcript dict produced by ``run_eval.py`` (schema
``eval_transcript/v1``) and returns a plain value; no I/O and no network.  The metric
definitions follow ``docs/xmuse/eval-design.md`` §2.

Transcript shape (only the fields this module reads)::

    {
      "root_correlation_id": "corr_...",          # optional but preferred
      "timing": {"wall_s": 12.3, ...},            # optional
      "projection": {
        "participants": [{"participant_id", "role", "display_name", ...}],
        "turns": [{"correlation_id", "participants": [
            {"observation_count", "unresolved_count", ...}]}],
        "timeline_items": [{"kind", "correlation_id", "causal_depth", "room_seq",
                            "actor": {"kind", "role", "display_name", "participant_id"},
                            "content", "handoff_targets", "context_only_tail"}],
      },
    }
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9]+")
SENTENCE_END_CHARS = ".!?\n"

ACK_MARKERS: tuple[str, ...] = (
    "agreed",
    "confirmed",
    "no objections",
    "sounds good",
)

# Tokens that stay capitalized mid-sentence without being named entities.
ENTITY_STOPWORDS: frozenset[str] = frozenset({"i", "i'm", "i'll", "i've", "ok", "okay"})

DEFAULT_CROSS_AGENT_THRESHOLD = 0.6
DEFAULT_SAME_AGENT_THRESHOLD = 0.75
SHINGLE_SIZE = 3


def tokens(content: str) -> list[str]:
    """Normalized lowercase word tokens used by echo/ack heuristics."""
    return TOKEN_RE.findall(content.lower())


def shingles(content: str, *, size: int = SHINGLE_SIZE) -> frozenset[tuple[str, ...]]:
    """Word n-gram shingles; short texts fall back to unigrams."""
    values = tokens(content)
    if len(values) < size:
        return frozenset((token,) for token in values)
    return frozenset(tuple(values[index : index + size]) for index in range(len(values) - size + 1))


def shingle_jaccard(left: str, right: str, *, size: int = SHINGLE_SIZE) -> float:
    left_shingles = shingles(left, size=size)
    right_shingles = shingles(right, size=size)
    if not left_shingles or not right_shingles:
        return 0.0
    intersection = len(left_shingles & right_shingles)
    union = len(left_shingles | right_shingles)
    return intersection / union if union else 0.0


def _projection(transcript: Mapping[str, Any]) -> Mapping[str, Any]:
    projection = transcript.get("projection")
    return projection if isinstance(projection, Mapping) else {}


def resolve_correlation(transcript: Mapping[str, Any]) -> str | None:
    """The task's correlation: explicit field first, then the human root item."""
    explicit = transcript.get("root_correlation_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    for item in timeline_items(transcript):
        actor = item.get("actor")
        if isinstance(actor, Mapping) and actor.get("kind") == "human":
            correlation = item.get("correlation_id")
            if isinstance(correlation, str) and correlation:
                return correlation
    return None


def timeline_items(transcript: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = _projection(transcript).get("timeline_items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _in_correlation(item: Mapping[str, Any], correlation: str | None) -> bool:
    if correlation is None:
        return True
    return item.get("correlation_id") == correlation


def participants(transcript: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = _projection(transcript).get("participants")
    if not isinstance(values, list):
        return []
    return [dict(value) for value in values if isinstance(value, Mapping)]


def agent_timeline_items(
    transcript: Mapping[str, Any], correlation_id: str | None = None
) -> list[dict[str, Any]]:
    """Agent-authored timeline items in the task correlation, by room sequence."""
    correlation = correlation_id if correlation_id is not None else resolve_correlation(transcript)
    items = [
        item
        for item in timeline_items(transcript)
        if _in_correlation(item, correlation)
        and isinstance(item.get("actor"), Mapping)
        and item["actor"].get("kind") != "human"
    ]
    items.sort(key=lambda item: int(item.get("room_seq") or 0))
    return items


def visible_messages(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    """Timeline items authored by agents, including ``kind == "handoff"``."""
    return len(agent_timeline_items(transcript, correlation_id))


def context_only_messages(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    return sum(
        1
        for item in agent_timeline_items(transcript, correlation_id)
        if item.get("context_only_tail")
    )


def agent_turns(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    """Durable agent observations with terminal outcome in the task correlation.

    Primary source is ``projection.turns[]``: per participant,
    ``observation_count - unresolved_count`` counts observations that reached a
    terminal outcome.  When the projection has no turn evidence (e.g. a synthetic
    transcript) the count falls back to agent-authored timeline items.
    """
    correlation = correlation_id if correlation_id is not None else resolve_correlation(transcript)
    turns = _projection(transcript).get("turns")
    total = 0
    seen_turn = False
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, Mapping) or not _in_correlation(turn, correlation):
                continue
            seen_turn = True
            members = turn.get("participants")
            if not isinstance(members, list):
                continue
            for member in members:
                if not isinstance(member, Mapping):
                    continue
                observation_count = int(member.get("observation_count") or 0)
                unresolved = int(member.get("unresolved_count") or 0)
                total += max(0, observation_count - unresolved)
    if seen_turn:
        return total
    return len(agent_timeline_items(transcript, correlation))


def max_causal_depth(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    correlation = correlation_id if correlation_id is not None else resolve_correlation(transcript)
    depths = [
        int(item.get("causal_depth") or 0)
        for item in timeline_items(transcript)
        if _in_correlation(item, correlation)
    ]
    return max(depths, default=0)


def handoff_summary(
    transcript: Mapping[str, Any], correlation_id: str | None = None
) -> dict[str, Any]:
    """Count of ``kind == "handoff"`` items and distinct handoff targets."""
    targets: list[str] = []
    count = 0
    for item in agent_timeline_items(transcript, correlation_id):
        if item.get("kind") != "handoff":
            continue
        count += 1
        for target in item.get("handoff_targets") or []:
            if isinstance(target, str) and target not in targets:
                targets.append(target)
    return {"count": count, "targets": targets}


def echo_pairs(
    transcript: Mapping[str, Any],
    correlation_id: str | None = None,
    *,
    cross_agent_threshold: float = DEFAULT_CROSS_AGENT_THRESHOLD,
    same_agent_threshold: float = DEFAULT_SAME_AGENT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Message pairs above the shingle-Jaccard redundancy thresholds.

    Cross-agent pairs use ``cross_agent_threshold`` (default 0.6); pairs from the
    same agent use the stricter ``same_agent_threshold`` (default 0.75).
    """
    items = agent_timeline_items(transcript, correlation_id)
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(items):
        for right in items[left_index + 1 :]:
            same_agent = _actor_key(left) == _actor_key(right)
            threshold = same_agent_threshold if same_agent else cross_agent_threshold
            score = shingle_jaccard(str(left.get("content") or ""), str(right.get("content") or ""))
            if score >= threshold:
                pairs.append(
                    {
                        "left_room_seq": int(left.get("room_seq") or 0),
                        "right_room_seq": int(right.get("room_seq") or 0),
                        "same_agent": same_agent,
                        "jaccard": round(score, 4),
                    }
                )
    return pairs


def echo_message_count(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    """Distinct agent messages involved in at least one echo pair."""
    involved: set[int] = set()
    for pair in echo_pairs(transcript, correlation_id):
        involved.add(pair["left_room_seq"])
        involved.add(pair["right_room_seq"])
    return len(involved)


def _actor_key(item: Mapping[str, Any]) -> str:
    actor = item.get("actor")
    if not isinstance(actor, Mapping):
        return ""
    return str(actor.get("participant_id") or actor.get("display_name") or "")


def has_named_entity(content: str) -> bool:
    """Heuristic proxy for "new named entity" in the pure-ack test.

    A capitalized token that is not at a sentence/line start and not in the small
    pronoun/interjection stoplist counts as entity-like.
    """
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_'-]*", content):
        token = match.group(0)
        if not token[0].isupper() or token.lower() in ENTITY_STOPWORDS:
            continue
        prefix = content[: match.start()].rstrip()
        if not prefix or prefix[-1] in SENTENCE_END_CHARS:
            continue
        return True
    return False


def is_pure_ack(content: str) -> bool:
    """Message < 30 tokens, an ack marker, and no digit, code, or named entity."""
    lowered = content.lower()
    if len(tokens(content)) >= 30:
        return False
    if not any(marker in lowered for marker in ACK_MARKERS):
        return False
    if re.search(r"\d", content):
        return False
    if "```" in content or "`" in content:
        return False
    return not has_named_entity(content)


def pure_ack_messages(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    return sum(
        1
        for item in agent_timeline_items(transcript, correlation_id)
        if is_pure_ack(str(item.get("content") or ""))
    )


def _has_substantive_content(content: str) -> bool:
    return bool(content.strip()) and not is_pure_ack(content)


def specialist_status(
    transcript: Mapping[str, Any],
    expected_roles: Sequence[str],
    *,
    ordered: bool = False,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Did the pre-registered specialist(s) answer?

    Passes when every expected participant role authored at least one message
    that passes the content check (non-empty, not a pure acknowledgment).  With
    ``ordered=True`` the first qualifying message of each role must appear in the
    given role order.  Empty ``expected_roles`` means "any specialist": passes
    when any agent authored a qualifying message.
    """
    items = agent_timeline_items(transcript, correlation_id)
    qualifying: list[tuple[str, int]] = []
    for item in items:
        actor = item.get("actor")
        if not isinstance(actor, Mapping):
            continue
        if _has_substantive_content(str(item.get("content") or "")):
            qualifying.append((str(actor.get("role") or ""), int(item.get("room_seq") or 0)))

    detail: dict[str, Any] = {"expected_roles": list(expected_roles), "ordered": ordered}
    if not expected_roles:
        ok = bool(qualifying)
        detail["qualifying_roles"] = [role for role, _seq in qualifying]
        return {"ok": ok, "detail": detail}

    first_by_role: dict[str, int] = {}
    for role, seq in qualifying:
        first_by_role.setdefault(role, seq)
    detail["first_message_seq"] = first_by_role
    missing = [role for role in expected_roles if role not in first_by_role]
    if missing:
        detail["missing_roles"] = missing
        return {"ok": False, "detail": detail}
    if ordered:
        seqs = [first_by_role[role] for role in expected_roles]
        detail["sequence_ok"] = seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        return {"ok": detail["sequence_ok"], "detail": detail}
    return {"ok": True, "detail": detail}


def token_estimate(transcript: Mapping[str, Any], correlation_id: str | None = None) -> int:
    """Chars ÷ 4 estimate over agent-authored message content (clearly an estimate)."""
    chars = sum(
        len(str(item.get("content") or ""))
        for item in agent_timeline_items(transcript, correlation_id)
    )
    return chars // 4


def wall_time_s(transcript: Mapping[str, Any]) -> float | None:
    timing = transcript.get("timing")
    if not isinstance(timing, Mapping):
        return None
    value = timing.get("wall_s")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_metrics(transcript: Mapping[str, Any], task: Any) -> dict[str, Any]:
    """All mechanical metrics for one cell, keyed by the design's CSV columns."""
    correlation = resolve_correlation(transcript)
    handoffs = handoff_summary(transcript, correlation)
    specialist = specialist_status(
        transcript,
        tuple(task.expected_roles or ()),
        ordered=bool(task.expected_ordered),
        correlation_id=correlation,
    )
    timing = transcript.get("timing")
    timed_out = bool(timing.get("timed_out")) if isinstance(timing, Mapping) else False
    abort_reason = timing.get("abort_reason") if isinstance(timing, Mapping) else None
    notes: list[str] = []
    if timed_out:
        notes.append(f"timeout:{abort_reason or 'unknown'}")
    if corpus_has_echo(transcript, correlation):
        notes.append("echo")
    return {
        "agent_turns": agent_turns(transcript, correlation),
        "visible_msgs": visible_messages(transcript, correlation),
        "echo_msgs": echo_message_count(transcript, correlation),
        "pure_ack_msgs": pure_ack_messages(transcript, correlation),
        "wall_s": round(wall_time_s(transcript) or 0.0, 3),
        "max_causal_depth": max_causal_depth(transcript, correlation),
        "handoffs": handoffs["count"],
        "handoff_targets": handoffs["targets"],
        "specialist_ok": specialist["ok"],
        "tokens_est": token_estimate(transcript, correlation),
        "context_only_msgs": context_only_messages(transcript, correlation),
        "notes": ";".join(notes),
    }


def corpus_has_echo(transcript: Mapping[str, Any], correlation_id: str | None = None) -> bool:
    return bool(echo_pairs(transcript, correlation_id))
