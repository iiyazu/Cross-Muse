// Structured-text helpers. Everything the status line, toasts, command
// output and the model tool result show passes through safe().

const MODULE_ID_RE = /^[a-z][a-z0-9_-]{0,47}$/;

// Printable ASCII plus CJK-safe ranges. Everything else (C0/C1 controls,
// ANSI ESC, bidi controls, lone surrogates, other scripts' controls) is
// dropped. Newlines become spaces: these strings all land on one line.
export function safe(input: unknown, maxLen = 160): string {
  if (typeof input !== "string") return "";
  let out = "";
  for (const ch of input) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp === 0x0a || cp === 0x0d || cp === 0x09) {
      out += " ";
      continue;
    }
    if (cp >= 0x20 && cp <= 0x7e) {
      out += ch;
      continue;
    }
    if (
      (cp >= 0x3000 && cp <= 0x303f) ||
      (cp >= 0x3400 && cp <= 0x4dbf) ||
      (cp >= 0x4e00 && cp <= 0x9fff) ||
      (cp >= 0xf900 && cp <= 0xfaff) ||
      (cp >= 0xff00 && cp <= 0xffef)
    ) {
      out += ch;
      continue;
    }
  }
  if (out.length > maxLen) out = out.slice(0, maxLen);
  return out;
}

// Multi-line text (a review patch) as separate safe() lines, so a diff keeps
// its shape. Bounded by line count and total characters; the second value
// says whether anything was cut.
export function safeLines(input: unknown, maxLines = 120, maxChars = 6000): [string[], boolean] {
  if (typeof input !== "string") return [[], false];
  const raw = input.split("\n");
  const lines: string[] = [];
  let used = 0;
  for (const line of raw) {
    if (lines.length >= maxLines || used >= maxChars) return [lines, true];
    const cleaned = safe(line, Math.min(240, maxChars - used));
    lines.push(cleaned === "" ? " " : cleaned);
    used += cleaned.length;
  }
  return [lines, false];
}

// Module ids are server-validated slugs; still funnel every interpolated
// string through safe(). A valid slug is used verbatim, anything else is
// sanitized (and blank becomes "?").
export function safeId(input: unknown): string {
  if (typeof input === "string" && MODULE_ID_RE.test(input)) return input;
  const s = safe(input, 48);
  return s === "" ? "?" : s;
}

// Short form of a room id for one-line surfaces. Never the room title:
// titles are user text and may be long.
export function shortRoom(conversationId: unknown): string {
  const s = safe(conversationId, 64);
  if (s === "") return "?";
  return s.length > 12 ? s.slice(0, 8) : s;
}

// Short form of a board revision ("41:9f2c0a7d41be" -> "41:9f2c0a").
export function shortRev(revision: unknown): string {
  const s = safe(revision, 64);
  if (s === "") return "?";
  const parts = s.split(":");
  if (parts.length === 2 && parts[0] !== "" && parts[1] !== "") {
    return parts[0].slice(0, 12) + ":" + parts[1].slice(0, 6);
  }
  return s.slice(0, 12);
}

// Rewrite a loopback web URL so a Link href passes the surface rule
// (https: or http://localhost). 127.0.0.1 and [::1] are the same machine.
export function linkBase(webUrl: string): string {
  const s = webUrl.trim().replace(/\/+$/, "");
  if (s.startsWith("http://127.0.0.1")) return "http://localhost" + s.slice("http://127.0.0.1".length);
  if (s.startsWith("http://[::1]")) return "http://localhost" + s.slice("http://[::1]".length);
  return s;
}

export function roomLink(webUrl: string, conversationId: string): string {
  const href = linkBase(webUrl) + "/rooms/" + encodeURIComponent(conversationId);
  return href.length <= 2048 ? href : "";
}
