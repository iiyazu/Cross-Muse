from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xmuse_core.chat.protocol_v2 import (
    DeliberationMessageKind,
    DeliberationMessageV1,
    ObjectionLevel,
    sort_deliberation_messages,
)


class FreezeDecisionStatus(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class FreezeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: FreezeDecisionStatus
    reason: str
    target_ref: str
    evidence_refs: list[str] = Field(default_factory=list)
    proposal_message_ids: list[str] = Field(default_factory=list)
    blocking_challenge_ids: list[str] = Field(default_factory=list)
    resolved_challenge_ids: list[str] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    vote_tally: dict[str, int] = Field(
        default_factory=lambda: {"approve": 0, "reject": 0, "abstain": 0}
    )
    commit_agent_ids: list[str] = Field(default_factory=list)
    duplicate_message_ids: list[str] = Field(default_factory=list)

    @property
    def can_freeze(self) -> bool:
        return self.status is FreezeDecisionStatus.ALLOWED

    @field_validator("evidence_refs", "proposal_message_ids")
    @classmethod
    def _dedupe_text_list(cls, value: list[str]) -> list[str]:
        return _dedupe(value)


class DeliberationFreezeGuard:
    """Pure freeze guard over `DeliberationMessageV1` events."""

    def __init__(
        self,
        *,
        required_commits: int = 1,
        objection_window_lamports: int = 0,
    ) -> None:
        if required_commits < 1:
            raise ValueError("required_commits must be >= 1")
        if objection_window_lamports < 0:
            raise ValueError("objection_window_lamports must be >= 0")
        self.required_commits = required_commits
        self.objection_window_lamports = objection_window_lamports

    def evaluate(
        self,
        messages: list[DeliberationMessageV1],
        *,
        target_ref: str,
    ) -> FreezeDecision:
        scoped_messages, duplicate_message_ids = self._scoped_unique_messages(
            messages,
            target_ref=target_ref,
        )
        evidence_refs = _collect_evidence_refs(scoped_messages)
        proposal_message_ids = [
            message.msg_id
            for message in scoped_messages
            if message.kind is DeliberationMessageKind.PROPOSAL
        ]
        has_no_objection_review = any(
            message.kind is DeliberationMessageKind.NOTE
            and message.payload.get("review") == "no_objection"
            for message in scoped_messages
        )
        has_challenge = any(
            message.kind is DeliberationMessageKind.CHALLENGE for message in scoped_messages
        )
        if not proposal_message_ids and not has_no_objection_review:
            return self._decision(
                FreezeDecisionStatus.DENIED,
                "missing proposal or explicit no-objection review",
                target_ref=target_ref,
                evidence_refs=evidence_refs,
                proposal_message_ids=proposal_message_ids,
                duplicate_message_ids=duplicate_message_ids,
            )
        if proposal_message_ids and not has_challenge and not has_no_objection_review:
            return self._decision(
                FreezeDecisionStatus.DENIED,
                "missing challenge or explicit no-objection review",
                target_ref=target_ref,
                evidence_refs=evidence_refs,
                proposal_message_ids=proposal_message_ids,
                duplicate_message_ids=duplicate_message_ids,
            )
        if not has_no_objection_review and self._objection_window_is_open(scoped_messages):
            return self._decision(
                FreezeDecisionStatus.DENIED,
                "objection window still open",
                target_ref=target_ref,
                evidence_refs=evidence_refs,
                proposal_message_ids=proposal_message_ids,
                duplicate_message_ids=duplicate_message_ids,
            )

        resolved_ids = self._resolved_challenge_ids(scoped_messages)
        blocking_ids = [
            message.msg_id
            for message in scoped_messages
            if message.kind is DeliberationMessageKind.CHALLENGE
            and message.objection_level is ObjectionLevel.BLOCKING
            and message.msg_id not in resolved_ids
        ]
        open_questions = self._open_questions(scoped_messages)
        vote_tally = self._vote_tally(scoped_messages)
        commit_agent_ids = self._commit_agent_ids(scoped_messages)

        if blocking_ids:
            return self._decision(
                FreezeDecisionStatus.DENIED,
                "unresolved blocking challenges",
                target_ref=target_ref,
                evidence_refs=evidence_refs,
                proposal_message_ids=proposal_message_ids,
                blocking_challenge_ids=blocking_ids,
                resolved_challenge_ids=sorted(resolved_ids),
                open_questions=open_questions,
                vote_tally=vote_tally,
                commit_agent_ids=commit_agent_ids,
                duplicate_message_ids=duplicate_message_ids,
            )
        if len(commit_agent_ids) < self.required_commits:
            return self._decision(
                FreezeDecisionStatus.DENIED,
                "commit quorum not satisfied",
                target_ref=target_ref,
                evidence_refs=evidence_refs,
                proposal_message_ids=proposal_message_ids,
                resolved_challenge_ids=sorted(resolved_ids),
                open_questions=open_questions,
                vote_tally=vote_tally,
                commit_agent_ids=commit_agent_ids,
                duplicate_message_ids=duplicate_message_ids,
            )
        return self._decision(
            FreezeDecisionStatus.ALLOWED,
            "freeze allowed",
            target_ref=target_ref,
            evidence_refs=evidence_refs,
            proposal_message_ids=proposal_message_ids,
            resolved_challenge_ids=sorted(resolved_ids),
            open_questions=open_questions,
            vote_tally=vote_tally,
            commit_agent_ids=commit_agent_ids,
            duplicate_message_ids=duplicate_message_ids,
        )

    def _scoped_unique_messages(
        self,
        messages: list[DeliberationMessageV1],
        *,
        target_ref: str,
    ) -> tuple[list[DeliberationMessageV1], list[str]]:
        seen_keys: set[str] = set()
        unique_messages: list[DeliberationMessageV1] = []
        duplicate_message_ids: list[str] = []
        for message in sort_deliberation_messages(messages):
            if message.target_ref not in {target_ref, None}:
                continue
            key = message.idempotency_key()
            if key in seen_keys:
                duplicate_message_ids.append(message.msg_id)
                continue
            seen_keys.add(key)
            unique_messages.append(message)
        return unique_messages, duplicate_message_ids

    def _resolved_challenge_ids(self, messages: list[DeliberationMessageV1]) -> set[str]:
        challenge_ids = {
            message.msg_id
            for message in messages
            if message.kind is DeliberationMessageKind.CHALLENGE
        }
        resolved: set[str] = set()
        for message in messages:
            resolves = message.payload.get("resolves")
            if isinstance(resolves, str) and resolves in challenge_ids:
                resolved.add(resolves)
            if isinstance(resolves, list):
                resolved.update(item for item in resolves if item in challenge_ids)
            if (
                message.parent_id in challenge_ids
                and message.kind is DeliberationMessageKind.EVIDENCE
            ):
                resolved.add(message.parent_id)
        return resolved

    def _objection_window_is_open(self, messages: list[DeliberationMessageV1]) -> bool:
        if self.objection_window_lamports <= 0:
            return False
        proposal_ts = [
            message.lamport_ts
            for message in messages
            if message.kind is DeliberationMessageKind.PROPOSAL
        ]
        if not proposal_ts:
            return False
        return max(message.lamport_ts for message in messages) < (
            max(proposal_ts) + self.objection_window_lamports
        )

    def _open_questions(self, messages: list[DeliberationMessageV1]) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        for message in messages:
            if not (
                message.kind is DeliberationMessageKind.CHALLENGE
                and message.objection_level is ObjectionLevel.NON_BLOCKING
            ):
                continue
            question = message.payload.get("question") or message.payload.get("body")
            if not isinstance(question, str) or not question.strip():
                question = "Non-blocking objection requires follow-up."
            questions.append(
                {
                    "message_id": message.msg_id,
                    "question": question.strip(),
                    "source_refs": list(message.source_refs),
                }
            )
        return questions

    def _vote_tally(self, messages: list[DeliberationMessageV1]) -> dict[str, int]:
        tally = {"approve": 0, "reject": 0, "abstain": 0}
        voters: set[str] = set()
        for message in messages:
            if message.kind is not DeliberationMessageKind.VOTE:
                continue
            if message.agent_id in voters:
                continue
            vote = message.payload.get("vote")
            if vote in tally:
                tally[str(vote)] += 1
                voters.add(message.agent_id)
        return tally

    def _commit_agent_ids(self, messages: list[DeliberationMessageV1]) -> list[str]:
        return _dedupe(
            [
                message.agent_id
                for message in messages
                if message.kind is DeliberationMessageKind.COMMIT
            ]
        )

    def _decision(
        self,
        status: FreezeDecisionStatus,
        reason: str,
        *,
        target_ref: str,
        evidence_refs: list[str],
        proposal_message_ids: list[str],
        blocking_challenge_ids: list[str] | None = None,
        resolved_challenge_ids: list[str] | None = None,
        open_questions: list[dict[str, Any]] | None = None,
        vote_tally: dict[str, int] | None = None,
        commit_agent_ids: list[str] | None = None,
        duplicate_message_ids: list[str] | None = None,
    ) -> FreezeDecision:
        return FreezeDecision(
            status=status,
            reason=reason,
            target_ref=target_ref,
            evidence_refs=evidence_refs,
            proposal_message_ids=proposal_message_ids,
            blocking_challenge_ids=blocking_challenge_ids or [],
            resolved_challenge_ids=resolved_challenge_ids or [],
            open_questions=open_questions or [],
            vote_tally=vote_tally or {"approve": 0, "reject": 0, "abstain": 0},
            commit_agent_ids=commit_agent_ids or [],
            duplicate_message_ids=duplicate_message_ids or [],
        )


def _collect_evidence_refs(messages: list[DeliberationMessageV1]) -> list[str]:
    refs: list[str] = []
    for message in messages:
        refs.extend(message.source_refs)
    return _dedupe(refs)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
