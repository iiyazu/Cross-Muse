// Read-only board API client. Only GETs to {baseUrl}/api/chat/...: the
// rooms list and the board summary / board projections. Responses are
// normalized defensively: unknown fields ignored, unknown enum values kept
// as opaque strings, missing capabilities tolerated, oversized data capped.

import type { XmuseAttentionItem, XmuseBoard, XmuseModule, XmuseSummary } from "./types";
import { safe, safeId } from "./text";

export type GetResult =
  | { kind: "ok"; json: unknown; etag: string | null }
  | { kind: "not-modified" }
  | { kind: "failed" };

export function parseGetResponse(res: {
  status: number;
  headers: Record<string, string>;
  text: string;
}): GetResult {
  if (res.status === 304) return { kind: "not-modified" };
  if (res.status < 200 || res.status > 299) return { kind: "failed" };
  let json: unknown = null;
  try {
    json = JSON.parse(res.text);
  } catch {
    return { kind: "failed" };
  }
  let outEtag: string | null = null;
  try {
    const raw = res.headers["etag"];
    if (typeof raw === "string" && raw !== "") outEtag = raw.replace(/^"|"$/g, "");
  } catch {
    outEtag = null;
  }
  return { kind: "ok", json, etag: outEtag };
}

function asRecord(v: unknown): Record<string, unknown> | null {
  if (typeof v === "object" && v !== null && !Array.isArray(v)) return v as Record<string, unknown>;
  return null;
}

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function asString(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

export type RoomEntry = { conversation_id: string; updated_at: string };

export function normalizeRooms(json: unknown): RoomEntry[] | null {
  const root = asRecord(json);
  if (root === null) return null;
  const rooms = asArray(root["rooms"]).slice(0, 200);
  const out: RoomEntry[] = [];
  for (const item of rooms) {
    const r = asRecord(item);
    if (r === null) continue;
    const id = asString(r["conversation_id"]);
    if (id === null || id === "") continue;
    const updated = asString(r["updated_at"]) ?? "";
    out.push({ conversation_id: id, updated_at: updated });
  }
  return out;
}

export function sortRoomsByUpdated(rooms: RoomEntry[]): RoomEntry[] {
  return rooms.slice().sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
}

export const COUNT_KEYS = [
  "assigned",
  "claimed",
  "working",
  "blocked",
  "ready_for_review",
  "done_claimed",
  "verifying",
  "waiting_for_provider",
  "verified",
  "verification_failed",
  "verification_error",
];

export function normalizeAttention(v: unknown): XmuseAttentionItem[] {
  const out: XmuseAttentionItem[] = [];
  for (const item of asArray(v).slice(0, 50)) {
    const r = asRecord(item);
    if (r === null) continue;
    const kind = asString(r["kind"]) ?? "?";
    const reason = asString(r["reason_code"]) ?? "?";
    const mid = asString(r["module_id"]);
    const sid = asString(r["split_id"]);
    out.push({ kind, reason_code: reason, module_id: mid, split_id: sid });
  }
  return out;
}

export function normalizeSummary(json: unknown): XmuseSummary | null {
  const root = asRecord(json);
  if (root === null) return null;
  const cid = asString(root["conversation_id"]);
  const rev = asString(root["revision"]);
  if (cid === null || cid === "" || rev === null || rev === "") return null;
  const countsRaw = asRecord(root["counts"]) ?? {};
  const counts: { [state: string]: number } = {};
  for (const k of COUNT_KEYS) counts[k] = Math.max(0, Math.floor(num(countsRaw[k])));
  const attention = normalizeAttention(root["attention"]);
  return {
    conversation_id: cid,
    revision: rev,
    board_seq: Math.max(0, Math.floor(num(root["board_seq"]))),
    modules_total: Math.max(0, Math.floor(num(root["modules_total"]))),
    counts,
    attention,
    attention_total: Math.max(attention.length, Math.floor(num(root["attention_total"]))),
  };
}

function agentText(v: unknown): { text: string } | null {
  const r = asRecord(v);
  if (r === null) return null;
  if (typeof r["text"] !== "string" || r["untrusted"] !== true) return null;
  return { text: r["text"] };
}

// Collect agent-authored snippets from one event's data without interpreting
// the event kind. Bounded; never throws.
export function collectSnippets(data: unknown, cap = 6): { field: string; text: string }[] {
  const out: { field: string; text: string }[] = [];
  const r = asRecord(data);
  if (r === null) return out;
  const push = (field: string, v: unknown) => {
    if (out.length >= cap) return;
    const t = agentText(v);
    if (t !== null) out.push({ field: safe(field, 32), text: t.text.slice(0, 400) });
  };
  push("summary", r["summary"]);
  push("question", r["question"]);
  push("rationale", r["rationale"]);
  const claims = asArray(r["claims"]).slice(0, 8);
  for (let i = 0; i < claims.length; i += 1) push("claim#" + String(i), claims[i]);
  return out;
}

export function normalizeBoard(json: unknown): XmuseBoard | null {
  const root = asRecord(json);
  if (root === null) return null;
  const rev = asString(root["revision"]);
  const cid = asString(root["conversation_id"]);
  if (rev === null || rev === "" || cid === null || cid === "") return null;

  const parts: { [id: string]: { display: string; kind: string } } = {};
  for (const item of asArray(root["participants"]).slice(0, 200)) {
    const r = asRecord(item);
    if (r === null) continue;
    const pid = asString(r["participant_id"]);
    if (pid === null || pid === "") continue;
    parts[pid] = {
      display: safe(asString(r["display_name"]) ?? "?", 32),
      kind: safe(asString(r["provider_kind"]) ?? "?", 24),
    };
  }

  const staleByModule: { [id: string]: string[] } = {};
  for (const item of asArray(root["stale_dependents"]).slice(0, 200)) {
    const r = asRecord(item);
    if (r === null) continue;
    const mid = asString(r["module_id"]);
    const contract = asString(r["contract_id"]);
    if (mid === null || contract === null) continue;
    const list = staleByModule[mid] ?? [];
    if (list.length < 8) list.push(contract);
    staleByModule[mid] = list;
  }

  const modules: XmuseModule[] = [];
  for (const item of asArray(root["modules"]).slice(0, 200)) {
    const r = asRecord(item);
    if (r === null) continue;
    const mid = asString(r["module_id"]);
    if (mid === null || mid === "") continue;
    const owner = asString(r["owner_participant_id"]);
    const ownerInfo = owner !== null ? parts[owner] : undefined;
    const counters = asRecord(r["counters"]) ?? {};
    const verification = asRecord(r["verification"]) ?? {};
    const attention = asRecord(r["attention"]);
    const gateIds: string[] = [];
    for (const g of asArray(verification["gate_ids"]).slice(0, 12)) {
      if (typeof g === "string" && g !== "") gateIds.push(safeId(g));
    }
    const strList = (v: unknown, cap: number): string[] => {
      const out: string[] = [];
      for (const x of asArray(v).slice(0, cap)) if (typeof x === "string" && x !== "") out.push(safe(x, 96));
      return out;
    };
    modules.push({
      module_id: mid,
      state: typeof r["state"] === "string" ? r["state"] : "?",
      lifecycle: typeof r["lifecycle"] === "string" ? r["lifecycle"] : "?",
      owner_display: ownerInfo !== undefined ? ownerInfo.display : "?",
      provider_kind: ownerInfo !== undefined ? ownerInfo.kind : "?",
      done_reports: Math.max(0, Math.floor(num(counters["done_reports"]))),
      passed: Math.max(0, Math.floor(num(counters["passed"]))),
      failed: Math.max(0, Math.floor(num(counters["failed"]))),
      rework_rounds: Math.max(0, Math.floor(num(counters["rework_rounds"]))),
      gate_ids: gateIds,
      stale_contracts: staleByModule[mid] !== undefined ? staleByModule[mid].map((c) => safeId(c)) : [],
      attention_kind: attention !== null ? (asString(attention["kind"]) ?? "none") : "none",
      attention_reason: attention !== null ? asString(attention["reason_code"]) : null,
      charter_version: Math.max(0, Math.floor(num(r["charter_version"]))),
      paths: strList(r["paths"], 16),
      provides: strList(r["provides"], 16).map((c) => safeId(c)),
      depends: strList(r["depends"], 16).map((c) => safeId(c)),
    });
  }
  modules.sort((a, b) => (a.module_id < b.module_id ? -1 : a.module_id > b.module_id ? 1 : 0));

  const events = asArray(root["events"]).slice(-50);
  const byModule: { [id: string]: { field: string; text: string }[] } = {};
  for (const item of events) {
    const r = asRecord(item);
    if (r === null) continue;
    const mid = asString(r["module_id"]);
    if (mid === null) continue;
    const kind = asString(r["kind"]) ?? "?";
    const seq = Math.floor(num(r["seq"]));
    const prefix = safe(kind, 40) + "#" + String(seq);
    const list = byModule[mid] ?? [];
    for (const s of collectSnippets(r["data"], 6)) {
      if (list.length >= 10) break;
      list.push({ field: prefix + "/" + s.field, text: s.text });
    }
    byModule[mid] = list;
  }
  const details = modules.slice(0, 200).map((m) => ({
    module_id: m.module_id,
    snippets: (byModule[m.module_id] ?? []).slice(0, 10),
  }));

  const contracts: { contract_id: string; latest_version: number }[] = [];
  for (const item of asArray(root["contracts"]).slice(0, 200)) {
    const r = asRecord(item);
    if (r === null) continue;
    const id = asString(r["contract_id"]);
    if (id === null || id === "") continue;
    contracts.push({ contract_id: id, latest_version: Math.max(0, Math.floor(num(r["latest_version"]))) });
  }
  contracts.sort((a, b) => (a.contract_id < b.contract_id ? -1 : 1));

  const proposed: string[] = [];
  for (const item of asArray(root["splits"]).slice(0, 50)) {
    const r = asRecord(item);
    if (r === null) continue;
    if (r["status"] !== "proposed") continue;
    const sid = asString(r["split_id"]);
    if (sid === null || sid === "") continue;
    proposed.push(sid);
  }

  return {
    revision: rev,
    modules,
    details,
    contracts,
    proposed_splits: proposed.slice(0, 10),
    operator_attention: normalizeAttention(root["attention"]).filter((a) => a.kind === "operator"),
  };
}
