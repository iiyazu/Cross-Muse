"""`xmuse transcript <agent>`: an agent's current vendor session as readable text. Read-only.

Each vendor keeps its own record: Claude a JSONL transcript under ~/.claude/projects, dsh a zstd JSONL session log
under its home, OpenCode its server's message API (`GET /api/session/{id}/message`, fetched through the hub, which
owns the server and its password). All three are reduced to (who, text) entries and printed the same way.
"""
import json
from pathlib import Path

CLIP = 2000  # characters per entry; tool output is the usual offender


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if n <= 0 or len(text) <= n else text[:n] + f" … [{len(text) - n} more chars]"


def _args(x) -> str:
    if isinstance(x, str):
        return x
    return json.dumps(x, ensure_ascii=False)


def _blocks_text(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text":
            out.append(c.get("text", ""))
        elif isinstance(c, str):
            out.append(c)
    return "\n".join(out)


def claude(path: Path) -> list[tuple[str, str]]:
    """Claude Code transcript JSONL. Streamed messages repeat one record per content block: keep each block once."""
    out, seen = [], set()
    for line in path.open(encoding="utf-8"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        m = o.get("message") or {}
        if o.get("type") == "user":
            content = m.get("content")
            if isinstance(content, str):
                out.append(("user", content))
                continue
            for c in content or []:
                if c.get("type") == "text":
                    out.append(("user", c.get("text", "")))
                elif c.get("type") == "tool_result":
                    out.append(("tool result", _blocks_text(c.get("content"))))
        elif o.get("type") == "assistant":
            for i, c in enumerate(m.get("content") or []):
                key = (m.get("id"), i, c.get("type"))
                if key in seen:
                    continue
                seen.add(key)
                if c.get("type") == "text":
                    out.append(("assistant", c.get("text", "")))
                elif c.get("type") == "tool_use":
                    out.append((f"tool {c.get('name')}", _args(c.get("input"))))
    return out


def dsh(path: Path) -> list[tuple[str, str]]:
    """dsh session log (session.v4.jsonl.zstd): user/assistant messages, tool calls and results, turn ends."""
    import zstandard
    raw = zstandard.ZstdDecompressor().stream_reader(path.open("rb")).read().decode("utf-8", "replace")
    out = []
    for line in raw.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        typ, d = o.get("type"), o.get("data") or {}
        if typ == "user/message":
            if ((d.get("source") or {}).get("kind")) in (None, "user"):
                text = _blocks_text(d.get("content"))
                if not text.lstrip().startswith(("<system-reminder>", "Current runtime context.")):
                    out.append(("user", text))
        elif typ == "assistant/message":
            text = _blocks_text((d.get("message") or {}).get("content"))
            if text.strip():
                out.append(("assistant", text))
        elif typ == "tool/call":
            out.append((f"tool {d.get('name')}", _args(d.get("arguments"))))
        elif typ == "tool/result":
            msg = d.get("message") or {}
            out.append(("tool error" if msg.get("isError") else "tool result", _blocks_text(msg.get("content"))))
        elif typ == "turn/end":
            kind = (d.get("reason") or {}).get("kind")
            if kind != "completed":
                out.append(("turn end", str(kind)))
    return out


def opencode(messages: list[dict]) -> list[tuple[str, str]]:
    """OpenCode v2 `Session.Message.Info` records, oldest first."""
    out = []
    for m in sorted(messages, key=lambda m: (m.get("time") or {}).get("created", 0)):
        typ = m.get("type")
        if typ in ("user", "synthetic"):
            out.append((typ, m.get("text", "")))
        elif typ == "assistant":
            for c in m.get("content") or []:
                if c.get("type") == "text":
                    out.append(("assistant", c.get("text", "")))
                elif c.get("type") == "tool":
                    st = c.get("state") or {}
                    out.append((f"tool {c.get('name')}", _args(st.get("input", ""))))
                    if st.get("status") == "completed":
                        out.append(("tool result", _blocks_text(st.get("content"))))
                    elif st.get("status") == "error":
                        out.append(("tool error", (st.get("error") or {}).get("message", "")))
        elif typ == "shell":
            out.append(("shell", m.get("command", "")))
        elif typ == "compaction" and m.get("status") == "completed":
            out.append(("compaction", m.get("summary", "")))
    return out


def render(entries: list[tuple[str, str]], clip: int = CLIP) -> str:
    return "\n\n".join(f"[{who}]\n{_clip(text, clip)}" for who, text in entries if text and text.strip())
