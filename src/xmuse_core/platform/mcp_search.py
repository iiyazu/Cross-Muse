from __future__ import annotations

import re
from typing import Any


def text_for_search(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(text_for_search(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(text_for_search(item) for item in value)
    return str(value)


def query_terms(query: str) -> set[str]:
    return {term for term in re.findall(r"[a-zA-Z0-9_+-]+", query.lower()) if len(term) > 1}
