from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from xmuse_core.sidecar.replay_packet import ReplayPacket, ReplayPacketItem


class RecallQuery(BaseModel):
    query_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_source_ids: list[str] = Field(default_factory=list)
    expected_participants: list[str] = Field(default_factory=list)
    scope: str = "conversation_shared"


class RecallEvalResult(BaseModel):
    query_id: str
    found_content: bool = False
    found_source_evidence: bool = False
    matched_source_ids: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    matched_participants: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.found_content and self.found_source_evidence


@dataclass
class RecallEvalScore:
    total_queries: int = 0
    passed_queries: int = 0
    content_found: int = 0
    source_evidence_found: int = 0

    @property
    def content_recall_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.content_found / self.total_queries

    @property
    def source_evidence_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.source_evidence_found / self.total_queries

    @property
    def pass_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.passed_queries / self.total_queries


class ChatRecallEvalHarness:
    def __init__(self, packets: list[ReplayPacket]) -> None:
        self._packets = packets
        self._all_items: list[ReplayPacketItem] = []
        self._items_by_scope: dict[str, list[ReplayPacketItem]] = {}
        for p in packets:
            self._all_items.extend(p.items)
            scope = p.scope_note or "conversation_shared"
            self._items_by_scope.setdefault(scope, []).extend(p.items)

    def evaluate(self, queries: list[RecallQuery]) -> list[RecallEvalResult]:
        results: list[RecallEvalResult] = []
        for q in queries:
            items = self._items_by_scope.get(q.scope, self._all_items)
            result = self._evaluate_single(q, items)
            results.append(result)
        return results

    def _evaluate_single(
        self,
        query: RecallQuery,
        items: list[ReplayPacketItem],
    ) -> RecallEvalResult:
        content_lc = " ".join(item.content.lower() for item in items)
        matched_keywords: list[str] = []
        found_content = False
        for kw in query.expected_keywords:
            if kw.lower() in content_lc:
                matched_keywords.append(kw)
                found_content = True
        matched_source_ids: list[str] = []
        for sid in query.expected_source_ids:
            if any(item.source_id == sid for item in items):
                matched_source_ids.append(sid)
        matched_participants: list[str] = []
        for pid in query.expected_participants:
            if any(item.participant_id == pid for item in items):
                matched_participants.append(pid)
        found_source_evidence = found_content and (
            len(matched_source_ids) > 0 or len(matched_participants) > 0
        )
        return RecallEvalResult(
            query_id=query.query_id,
            found_content=found_content,
            found_source_evidence=found_source_evidence,
            matched_source_ids=matched_source_ids,
            matched_keywords=matched_keywords,
            matched_participants=matched_participants,
        )


def score_recall_results(results: list[RecallEvalResult]) -> RecallEvalScore:
    score = RecallEvalScore(total_queries=len(results))
    for r in results:
        if r.found_content:
            score.content_found += 1
        if r.found_source_evidence:
            score.source_evidence_found += 1
        if r.passed:
            score.passed_queries += 1
    return score


def default_accuracy_gate(results: list[RecallEvalResult], *, min_pass_rate: float = 0.5) -> bool:
    if not results:
        return True
    score = score_recall_results(results)
    if score.total_queries == 0:
        return True
    return score.pass_rate >= min_pass_rate


def derive_recall_queries_from_packets(
    packets: list[ReplayPacket],
    *,
    max_queries_per_packet: int = 5,
) -> list[RecallQuery]:
    queries: list[RecallQuery] = []
    seen_sources: set[str] = set()
    for p in packets:
        scope = p.scope_note or "conversation_shared"
        count = 0
        for item in p.items:
            if count >= max_queries_per_packet:
                break
            if item.source_id in seen_sources:
                continue
            seen_sources.add(item.source_id)
            content = item.content.strip()
            if len(content) < 10:
                continue
            keywords = _extract_keywords(content)
            query = RecallQuery(
                query_id=f"derived_{scope}_{item.source_id}",
                question=_derive_question(scope, item),
                expected_keywords=keywords[:5],
                expected_source_ids=[item.source_id],
                expected_participants=[item.participant_id],
                scope=scope,
            )
            queries.append(query)
            count += 1
    return queries


def _extract_keywords(text: str, *, max_words: int = 8) -> list[str]:
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "about",
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
        "its", "they", "them", "their", "let", "need", "also",
    }
    words = text.lower().split()
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        w_clean = w.strip(".,!?;:'\"()[]{}-_")
        if not w_clean or len(w_clean) <= 2:
            continue
        if w_clean in stop_words:
            continue
        if w_clean in seen:
            continue
        seen.add(w_clean)
        keywords.append(w_clean)
        if len(keywords) >= max_words:
            break
    return keywords


def _derive_question(scope: str, item: ReplayPacketItem) -> str:
    source_label = item.envelope_type or item.source_type
    if scope == "blueprint_decision":
        return f"What was decided in {source_label} '{item.source_id[:12]}...'?"
    if scope == "participant":
        return f"What did {item.participant_id} contribute in {source_label}?"
    if scope == "unresolved_thread":
        return f"What question was raised in {source_label}?"
    return f"What was discussed in {source_label} '{item.source_id[:12]}...'?"
