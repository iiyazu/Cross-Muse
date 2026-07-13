from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from xmuse_core.chat.participant_store import Participant, ParticipantStore

DEFAULT_INTAKE_ROLE = "architect"
MENTION_RE = re.compile(
    r"@(?:participant:[A-Za-z0-9_:-]+|[A-Za-z0-9][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*)*)"
)


class MentionResolutionError(ValueError):
    def __init__(self, code: str, target: str) -> None:
        super().__init__(f"{code}: {target}")
        self.code = code
        self.target = target


@dataclass(frozen=True)
class ResolvedMention:
    raw: str
    normalized: str
    participant: Participant


@dataclass(frozen=True)
class _MentionAlias:
    raw: str
    normalized: str


@dataclass(frozen=True)
class _MentionCandidate:
    start: int
    active: bool


def normalize_address(value: str) -> str:
    text = value.strip()
    if text.startswith("@"):
        text = text[1:]
    text = re.sub(r"[\s_]+", "-", text.lower())
    return f"@{text}"


def default_intake_address() -> str:
    return normalize_address(DEFAULT_INTAKE_ROLE)


def extract_mentions(content: str) -> list[str]:
    seen: set[str] = set()
    mentions: list[str] = []
    for candidate in _iter_mention_candidates(content):
        if not candidate.active:
            continue
        match = MENTION_RE.match(content, candidate.start)
        if match is None:
            continue
        raw = match.group(0).strip()
        normalized = normalize_address(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        mentions.append(raw)
    return mentions


def extract_leading_mentions(content: str) -> list[str]:
    seen: set[str] = set()
    mentions: list[str] = []
    index = 0
    length = len(content)
    while index < length:
        start = _leading_mention_start(content, index)
        if start is None:
            break
        if _is_escaped(content, start):
            break
        match = MENTION_RE.match(content, start)
        if match is None:
            break
        raw = match.group(0).strip()
        normalized = normalize_address(raw)
        if normalized not in seen:
            seen.add(normalized)
            mentions.append(raw)
        index = match.end()
        while index < length and content[index].isspace():
            index += 1
        if index < length and content[index] in {",", ";"}:
            index += 1
            while index < length and content[index].isspace():
                index += 1
    return mentions


def has_inactive_mention_candidates(content: str) -> bool:
    return any(not candidate.active for candidate in _iter_mention_candidates(content))


def _iter_mention_candidates(content: str) -> Iterator[_MentionCandidate]:
    index = 0
    while index < len(content):
        fenced_end = _find_fenced_code_block_end(content, index)
        if fenced_end is not None:
            yield from _iter_inactive_code_mentions(content, index, fenced_end)
            index = fenced_end
            continue
        if content[index] == "`" and not _is_escaped(content, index):
            closing = _find_inline_code_span_end(content, index)
            if closing is not None:
                yield from _iter_inactive_code_mentions(content, index, closing)
                index = closing
                continue
        if content[index] == "@" and _looks_like_mention_start(content, index):
            yield _MentionCandidate(start=index, active=not _is_escaped(content, index))
        index += 1


def _iter_inactive_code_mentions(content: str, start: int, end: int) -> Iterator[_MentionCandidate]:
    index = start
    while index < end:
        if content[index] == "@" and _looks_like_mention_start(content, index):
            yield _MentionCandidate(start=index, active=False)
        index += 1


def _find_fenced_code_block_end(content: str, start: int) -> int | None:
    marker = content[start]
    if marker not in {"`", "~"} or not _is_line_prefix_only_spaces(content, start):
        return None
    run_length = _char_run_length(content, start, marker)
    if run_length < 3:
        return None
    line_end = content.find("\n", start)
    if line_end == -1:
        return len(content)
    index = line_end + 1
    while index < len(content):
        line_start = index
        while index < len(content) and content[index] in {" ", "\t"}:
            index += 1
        if (
            index < len(content)
            and content[index] == marker
            and _char_run_length(content, index, marker) >= run_length
        ):
            closing_line_end = content.find("\n", index)
            return len(content) if closing_line_end == -1 else closing_line_end + 1
        next_line = content.find("\n", line_start)
        if next_line == -1:
            return len(content)
        index = next_line + 1
    return len(content)


def _find_inline_code_span_end(content: str, start: int) -> int | None:
    run_length = _backtick_run_length(content, start)
    index = start + run_length
    while index < len(content):
        if content[index] != "`":
            index += 1
            continue
        if _backtick_run_length(content, index) == run_length:
            return index + run_length
        index += 1
    return None


def _backtick_run_length(content: str, start: int) -> int:
    return _char_run_length(content, start, "`")


def _char_run_length(content: str, start: int, char: str) -> int:
    end = start
    while end < len(content) and content[end] == char:
        end += 1
    return end - start


def _is_line_prefix_only_spaces(content: str, index: int) -> bool:
    line_start = content.rfind("\n", 0, index) + 1
    return all(char in {" ", "\t"} for char in content[line_start:index])


def _leading_mention_start(content: str, index: int) -> int | None:
    length = len(content)
    while index < length and content[index].isspace():
        index += 1
    index = _skip_markdown_line_prefix(content, index)
    if index >= length:
        return None
    if content[index] != "@" or not _looks_like_mention_start(content, index):
        return None
    return index


def _skip_markdown_line_prefix(content: str, index: int) -> int:
    length = len(content)
    while index < length and content[index] in {">"}:
        index += 1
        while index < length and content[index] in {" ", "\t"}:
            index += 1
    if index + 1 < length and content[index] in {"-", "*", "+"} and content[index + 1].isspace():
        index += 1
        while index < length and content[index] in {" ", "\t"}:
            index += 1
    return index


def _looks_like_mention_start(content: str, start: int) -> bool:
    next_index = start + 1
    return next_index < len(content) and content[next_index].isalnum()


def _is_escaped(content: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and content[index] == "\\":
        slashes += 1
        index -= 1
    return slashes % 2 == 1


class MentionResolver:
    def __init__(self, participant_store: ParticipantStore) -> None:
        self._participants = participant_store

    def resolve_content(
        self,
        conversation_id: str,
        content: str,
        *,
        strict: bool = True,
    ) -> list[ResolvedMention]:
        active = self._active_participants(conversation_id)
        aliases = self._aliases(active)
        seen: set[str] = set()
        resolved: list[ResolvedMention] = []
        for candidate in _iter_mention_candidates(content):
            if not candidate.active:
                continue
            start = candidate.start
            raw, _end = self._extract_scoped_raw(content, start, aliases)
            if raw is None:
                continue

            try:
                mention = self._resolve_active(active, raw)
            except MentionResolutionError:
                if strict:
                    raise
                continue
            if mention.normalized not in seen:
                seen.add(mention.normalized)
                resolved.append(mention)
        return resolved

    def resolve_leading_content(
        self,
        conversation_id: str,
        content: str,
        *,
        strict: bool = True,
    ) -> list[ResolvedMention]:
        active = self._active_participants(conversation_id)
        aliases = self._aliases(active)
        seen: set[str] = set()
        resolved: list[ResolvedMention] = []
        index = 0
        length = len(content)
        while index < length:
            start = _leading_mention_start(content, index)
            if start is None:
                break
            if _is_escaped(content, start):
                break
            raw, end = self._extract_scoped_raw(content, start, aliases)
            if raw is None:
                break
            try:
                mention = self._resolve_active(active, raw)
            except MentionResolutionError:
                if strict:
                    raise
                break
            if mention.normalized not in seen:
                seen.add(mention.normalized)
                resolved.append(mention)
            index = end
            while index < length and content[index].isspace():
                index += 1
            if index < length and content[index] in {",", ";"}:
                index += 1
                while index < length and content[index].isspace():
                    index += 1
        return resolved

    def resolve(self, conversation_id: str, raw: str) -> ResolvedMention:
        return self._resolve_active(self._active_participants(conversation_id), raw)

    def _active_participants(self, conversation_id: str) -> list[Participant]:
        return [
            participant
            for participant in self._participants.list_by_conversation(conversation_id)
            if participant.status == "active" and participant.cli_kind == "codex"
        ]

    def _resolve_active(self, active: list[Participant], raw: str) -> ResolvedMention:
        for candidate_raw in _raw_resolution_candidates(raw):
            resolved = self._resolve_active_candidate(active, candidate_raw)
            if resolved is not None:
                return resolved
        raise MentionResolutionError("unknown_target", raw)

    def _resolve_active_candidate(
        self,
        active: list[Participant],
        raw: str,
    ) -> ResolvedMention | None:
        normalized = normalize_address(raw)
        if normalized.startswith("@participant:"):
            participant_id = normalized.removeprefix("@participant:")
            matches = [
                participant
                for participant in active
                if normalize_address(f"@participant:{participant.participant_id}")
                == f"@participant:{participant_id}"
            ]
        else:
            matches = [
                participant
                for participant in active
                if normalized in _participant_aliases(participant)
            ]
        if not matches:
            return None
        if len(matches) > 1:
            raise MentionResolutionError("ambiguous_target", raw)
        return ResolvedMention(raw=raw, normalized=normalized, participant=matches[0])

    def _aliases(self, active: list[Participant]) -> list[_MentionAlias]:
        aliases: dict[str, _MentionAlias] = {}
        for participant in active:
            for raw in (
                f"@participant:{participant.participant_id}",
                f"@{participant.role}",
                f"@{participant.display_name}",
                f"@{participant.role}_god",
                f"@{participant.role}-god",
            ):
                normalized = normalize_address(raw)
                aliases.setdefault(normalized, _MentionAlias(raw=raw, normalized=normalized))
        return sorted(aliases.values(), key=lambda alias: len(alias.normalized), reverse=True)

    def _extract_scoped_raw(
        self,
        content: str,
        start: int,
        aliases: list[_MentionAlias],
    ) -> tuple[str | None, int]:
        for alias in aliases:
            end = start + len(alias.raw)
            if end > len(content):
                continue
            raw = content[start:end]
            if normalize_address(raw) != alias.normalized:
                continue
            if end < len(content) and self._is_mention_char(content[end]):
                continue
            return raw, end

        fallback = MENTION_RE.match(content, start)
        if fallback is None:
            return None, start + 1
        raw = fallback.group(0).strip()
        return raw, fallback.end()

    def _is_mention_char(self, value: str) -> bool:
        return value.isalnum() or value in "_-:"


def _raw_resolution_candidates(raw: str) -> Iterator[str]:
    stripped = raw.strip()
    if not stripped:
        return
    yield stripped
    if " " not in stripped:
        return
    if stripped.startswith("@"):
        body = stripped[1:]
        prefix = "@"
    else:
        body = stripped
        prefix = ""
    parts = body.split()
    for end in range(len(parts) - 1, 0, -1):
        yield prefix + " ".join(parts[:end])


def _participant_aliases(participant: Participant) -> set[str]:
    return {
        normalize_address(raw)
        for raw in (
            participant.role,
            participant.display_name,
            f"{participant.role}_god",
            f"{participant.role}-god",
        )
        if raw.strip()
    }
