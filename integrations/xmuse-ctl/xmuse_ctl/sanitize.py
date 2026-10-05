"""Sanitize every server string before it reaches stdout.

Port of the mod's ``text.ts`` helpers (``safe``, ``safeId``,
``shortRoom``, ``shortRev``) with one extension: Unicode format
characters (category Cf, covering bidi controls and zero-width marks)
are dropped explicitly through :mod:`unicodedata`.
"""

from __future__ import annotations

import re
import unicodedata

_MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")

# Escape sequences are stripped before the per-character filter below,
# otherwise remnants such as "[31m" would survive as plain ASCII.
_ANSI_RE = re.compile(
    "\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)"
    "|\x1b\\[[0-?]*[ -/]*[@-~]"
    "|\x1b[()#%*+][0-9A-Za-z]"
    "|\x1b[@-Z\\\\-_]"
    "|\x9b[0-?]*[ -/]*[@-~]"
    "|\x9d[^\x07\x9c]*(?:\x07|\x9c)"
    "|[\x80-\x9f]"
)


def safe(value: object, max_len: int = 160) -> str:
    """Keep printable ASCII plus CJK-safe ranges; drop the rest."""
    if not isinstance(value, str):
        return ""
    text = _ANSI_RE.sub("", value)
    out: list[str] = []
    for char in text:
        code = ord(char)
        if code in (0x0A, 0x0D, 0x09):
            out.append(" ")
            continue
        if 0x20 <= code <= 0x7E:
            out.append(char)
            continue
        if unicodedata.category(char) == "Cf":
            continue
        if (
            (0x3000 <= code <= 0x303F)
            or (0x3400 <= code <= 0x4DBF)
            or (0x4E00 <= code <= 0x9FFF)
            or (0xF900 <= code <= 0xFAFF)
            or (0xFF00 <= code <= 0xFFEF)
        ):
            out.append(char)
            continue
    result = "".join(out)
    if len(result) > max_len:
        result = result[:max_len]
    return result


def safe_id(value: object) -> str:
    """Use a valid module slug verbatim, sanitize anything else."""
    if isinstance(value, str) and _MODULE_ID_RE.match(value):
        return value
    text = safe(value, 48)
    return text if text != "" else "?"


def short_room(value: object) -> str:
    """Short form of a room id for one-line surfaces."""
    text = safe(value, 64)
    if text == "":
        return "?"
    if len(text) > 12:
        return text[:8]
    return text


def short_rev(value: object) -> str:
    """Short form of a board revision ("41:9f2c0a7d41be" -> "41:9f2c0a")."""
    text = safe(value, 64)
    if text == "":
        return "?"
    parts = text.split(":")
    if len(parts) == 2 and parts[0] != "" and parts[1] != "":
        return parts[0][:12] + ":" + parts[1][:6]
    return text[:12]
