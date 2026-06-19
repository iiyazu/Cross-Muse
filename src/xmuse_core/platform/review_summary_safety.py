from __future__ import annotations

import re

_BOUNDARY_NOTE = (
    "Proof boundary: review acceptance is not merge truth; final-action hold "
    "or GitHub server merge remains authoritative."
)

_FORBIDDEN_CLAIM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bready[_ -]?to[_ -]?merge\b", re.IGNORECASE),
        "review recommends merge pending final authority",
    ),
    (
        re.compile(r"\bpr[_ -]?merged\b", re.IGNORECASE),
        "PR merge not claimed",
    ),
    (
        re.compile(r"\breviewed\s+and\s+merged\b", re.IGNORECASE),
        "reviewed and awaiting final action",
    ),
    (
        re.compile(r"\bhas\s+been\s+merged\b", re.IGNORECASE),
        "is awaiting final action",
    ),
    (
        re.compile(r"\bwas\s+merged\b", re.IGNORECASE),
        "is awaiting final action",
    ),
    (
        re.compile(r"\bis\s+merged\b", re.IGNORECASE),
        "is awaiting final action",
    ),
    (
        re.compile(r"\bmerged\b", re.IGNORECASE),
        "merge not performed by review",
    ),
)


def sanitize_review_summary(summary: str) -> str:
    text = summary.strip()
    if not text:
        return text

    sanitized = text
    changed = False
    for pattern, replacement in _FORBIDDEN_CLAIM_PATTERNS:
        sanitized, count = pattern.subn(replacement, sanitized)
        changed = changed or count > 0
    if changed and _BOUNDARY_NOTE not in sanitized:
        sanitized = f"{sanitized.rstrip()}\n\n{_BOUNDARY_NOTE}"
    return sanitized
