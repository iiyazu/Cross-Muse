// Board status tests for the OpenCode plugin. No OpenCode needed: every
// import is a pure module (src/core/*, src/host.ts with fakes). Fixtures
// come from the shared contract files via tests/fixtures.generated.ts.
import { describe, expect, test } from "bun:test";
import {
  normalizeSummary,
  sortRoomsByUpdated,
  type GetResult,
  type RoomEntry,
} from "../src/core/api";
import { attentionKey, planStateToasts, planToast, statusBlock, statusText } from "../src/core/board_state";
import { backoffMs, bindingKey, pickAttachTarget } from "../src/core/poll";
import { safe, safeId, shortRoom } from "../src/core/text";
import type { XmuseCache, XmuseSummary } from "../src/core/types";
import {
  autoBindRoom,
  bindingField,
  initialSnapshot,
  pollOnce,
  readBinding,
  resolveBaseUrl,
  runCommand,
  writeBinding,
  type BindingsState,
  type Snapshot,
} from "../src/host";
import * as fx from "./fixtures.generated";

type AnyRecord = Record<string, unknown>;

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function summaryOf(name: keyof typeof fx): AnyRecord {
  return clone((fx[name] as unknown as { summary: unknown }).summary as AnyRecord);
}

function projectionOf(name: keyof typeof fx): AnyRecord {
  return clone((fx[name] as unknown as { projection: unknown }).projection as AnyRecord);
}

function normalized(name: keyof typeof fx): XmuseSummary {
  const out = normalizeSummary(summaryOf(name));
  if (out === null) throw new Error("fixture does not normalize: " + String(name));
  return out;
}

function cacheWith(summary: XmuseSummary, baselined: boolean): XmuseCache {
  const snap = initialSnapshot(summary.conversation_id);
  snap.summary = summary;
  snap.baselined = baselined;
  snap.seenAttention = baselined
    ? summary.attention.filter((a) => a.kind === "operator").map(attentionKey)
    : [];
  return {
    binding: snap.binding,
    cwd: null,
    summary: snap.summary,
    board: null,
    summaryEtag: null,
    boardEtag: null,
    lastPollAt: null,
    offline: snap.offline,
    baselined: snap.baselined,
    seenAttention: snap.seenAttention,
    seenStates: {},
    failCount: 0,
    nextRetryAt: 0,
    paneOpen: false,
    expanded: {},
  };
}

function okSummary(summary: AnyRecord, etag: string | null = null): GetResult {
  return { kind: "ok", json: summary, etag };
}

// ---------------------------------------------------------------- status line

describe("statusText", () => {
  test("verified counts", () => {
    const cache = cacheWith(normalized("verified"), true);
    expect(statusText(cache)).toBe("看板 2 模块 · ✓1");
  });

  test("failure glyph and operator attention", () => {
    const cache = cacheWith(normalized("verification_error"), true);
    expect(statusText(cache)).toBe("看板 2 模块 · ‼1 · 待你处理 1");
  });

  test("verifying and waiting glyphs", () => {
    const cache = cacheWith(normalized("verifying_and_waiting"), true);
    expect(statusText(cache)).toBe("看板 2 模块 · …1 ⧗1");
  });

  test("done_claimed is unmistakable next to verified", () => {
    const raw = summaryOf("verified");
    raw["revision"] = "9:claimed";
    raw["modules_total"] = 1;
    raw["counts"] = {
      assigned: 0, claimed: 0, working: 0, blocked: 0, ready_for_review: 0,
      done_claimed: 1, verifying: 0, waiting_for_provider: 0, verified: 0,
      verification_failed: 0, verification_error: 0,
    };
    raw["attention"] = [];
    raw["attention_total"] = 0;
    const summary = normalizeSummary(raw);
    if (summary === null) throw new Error("synthetic summary does not normalize");
    expect(statusText(cacheWith(summary, true))).toBe("看板 1 模块 · ◌1");
  });

  test("offline / unbound / loading states", () => {
    const base = cacheWith(normalized("verified"), true);
    expect(statusText({ ...base, offline: true })).toBe("xmuse 离线");
    expect(statusText({ ...base, binding: null })).toBe("xmuse 未绑定房间");
    expect(statusText({ ...base, summary: null })).toContain("…");
  });

  test("every fixture status line carries no agent text", () => {
    const needles = agentStrings();
    expect(needles.length).toBeGreaterThan(0);
    for (const name of fx.SCENARIO_NAMES) {
      const line = statusText(cacheWith(normalized(name as keyof typeof fx), true));
      for (const n of needles) expect(line).not.toContain(n);
      expect(BIDI.test(line)).toBe(false);
      expect(ESC.test(line)).toBe(false);
    }
  });
});

describe("statusBlock", () => {
  test("compact block carries counts and operator items", () => {
    const block = statusBlock(cacheWith(normalized("verification_error"), true));
    expect(block).toContain("模块 2");
    expect(block).toContain("待你处理 1");
    expect(block).toContain("board_attention_verification_error");
    expect(block.split("\n").length).toBeLessThanOrEqual(8);
  });

  test("offline / unbound", () => {
    const base = cacheWith(normalized("verified"), true);
    expect(statusBlock({ ...base, offline: true })).toBe("xmuse 离线");
    expect(statusBlock({ ...base, binding: null })).toBe("xmuse 未绑定房间");
  });
});

// ------------------------------------------------------------------- toasts

describe("planToast", () => {
  test("no toast on the first successful poll", () => {
    const prev = cacheWith(normalized("lifecycle_mix"), false);
    const next = normalized("verification_error");
    expect(planToast(prev, next, [])).toBeNull();
  });

  test("gained operator attention toasts once, coalesced", () => {
    const prev = cacheWith(normalized("lifecycle_mix"), true);
    const raw = summaryOf("verification_error");
    const extra = {
      kind: "operator",
      reason_code: "board_attention_split_pending",
      module_id: null,
      split_id: "split_x",
    };
    (raw["attention"] as unknown[]).push(extra);
    raw["attention_total"] = 2;
    raw["revision"] = "99:toast";
    const next = normalizeSummary(raw);
    if (next === null) throw new Error("synthetic summary does not normalize");
    const plan = planToast(prev, next, []);
    if (plan === null) throw new Error("expected a toast");
    expect(plan.text).toContain("board_attention_verification_error");
    expect(plan.text).toContain("board_attention_split_pending");
  });

  test("verified count growth toasts without ids", () => {
    const prev = cacheWith(normalized("verifying_and_waiting"), true);
    const raw = summaryOf("verified");
    raw["revision"] = "101:countgain";
    const next = normalizeSummary(raw);
    if (next === null) throw new Error("synthetic summary does not normalize");
    const plan = planToast(prev, next, []);
    if (plan === null) throw new Error("expected a toast");
    expect(plan.text).toContain("新增已验证");
  });

  test("no change means no toast", () => {
    const prev = cacheWith(normalized("verified"), true);
    expect(planToast(prev, normalized("verified"), [])).toBeNull();
  });
});

describe("planStateToasts", () => {
  test("transitions to verified / failed toast with ids only", () => {
    const notes = planStateToasts(
      { alpha: "verifying", beta: "working" },
      { alpha: "verified", beta: "verification_failed" },
    );
    expect(notes).toHaveLength(2);
    expect(notes[0]).toContain("alpha");
    expect(notes[1]).toContain("beta");
  });

  test("stable states stay silent", () => {
    expect(planStateToasts({ a: "verified" }, { a: "verified" })).toHaveLength(0);
  });
});

// ---------------------------------------------------------------- injection

const BIDI = new RegExp("[\\u061c\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]");
const ESC = new RegExp("\\u001b");

function agentStrings(): string[] {
  const p = projectionOf("injection_text") as {
    modules: { title: { text: string } }[];
    events: { data: { summary?: { text: string }; question?: { text: string }; rationale?: { text: string } } }[];
  };
  const out = [p.modules[0].title.text, p.modules[1].title.text];
  for (const e of p.events) {
    if (e.data.summary !== undefined) out.push(e.data.summary.text);
    if (e.data.question !== undefined) out.push(e.data.question.text);
    if (e.data.rationale !== undefined) out.push(e.data.rationale.text);
  }
  return out;
}

describe("injection_text", () => {
  test("no AgentText reaches status, block or toast output", () => {
    const needles = agentStrings();
    expect(needles.length).toBeGreaterThan(0);
    const cache = cacheWith(normalized("injection_text"), true);
    const outputs = [statusText(cache), statusBlock(cache)];
    const toast = planToast(cacheWith(normalized("lifecycle_mix"), true), normalized("injection_text"), []);
    if (toast !== null) outputs.push(toast.text);
    for (const text of outputs) {
      for (const n of needles) expect(text).not.toContain(n);
      expect(BIDI.test(text)).toBe(false);
      expect(ESC.test(text)).toBe(false);
    }
  });

  test("no AgentText reaches command output", async () => {
    const needles = agentStrings();
    const cid = String(summaryOf("injection_text")["conversation_id"]);
    const snap = initialSnapshot(cid);
    snap.summary = normalized("injection_text");
    snap.baselined = true;
    const status = await runCommand("status", {
      snapshot: () => snap,
      listRooms: async () => null,
      setBinding: () => {},
    });
    for (const n of needles) expect(status).not.toContain(n);
    expect(BIDI.test(status)).toBe(false);
    expect(ESC.test(status)).toBe(false);
  });
});

// ------------------------------------------------------------- base URL rule

describe("resolveBaseUrl", () => {
  const cases: { env: Record<string, string | undefined>; ok: boolean; base?: string }[] = [
    { env: {}, ok: true, base: "http://127.0.0.1:8201" },
    { env: { XMUSE_BASE_URL: "" }, ok: true, base: "http://127.0.0.1:8201" },
    { env: { XMUSE_BASE_URL: "http://127.0.0.1:8201/" }, ok: true, base: "http://127.0.0.1:8201" },
    { env: { XMUSE_BASE_URL: "http://localhost:9999" }, ok: true, base: "http://localhost:9999" },
    { env: { XMUSE_BASE_URL: "http://[::1]:8201" }, ok: true, base: "http://[::1]:8201" },
    { env: { XMUSE_BASE_URL: "https://127.0.0.1:8201" }, ok: true, base: "https://127.0.0.1:8201" },
    { env: { XMUSE_BASE_URL: "http://192.168.1.10:8201" }, ok: false },
    { env: { XMUSE_BASE_URL: "http://xmuse.lan:8201" }, ok: false },
    { env: { XMUSE_BASE_URL: "http://example.com" }, ok: false },
    { env: { XMUSE_BASE_URL: "http://127.0.0.1.evil.com" }, ok: false },
    { env: { XMUSE_BASE_URL: "not-a-url" }, ok: false },
    { env: { XMUSE_BASE_URL: "ws://127.0.0.1:8201" }, ok: false },
  ];
  for (const c of cases) {
    test(`XMUSE_BASE_URL=${c.env["XMUSE_BASE_URL"] ?? "(unset)"} -> ${c.ok ? "accept" : "reject"}`, () => {
      const res = resolveBaseUrl(c.env);
      expect(res.ok).toBe(c.ok);
      if (res.ok && c.base !== undefined) expect(res.baseUrl).toBe(c.base);
    });
  }
});

// ------------------------------------------------------ binding persistence

function fakeStore(initial: BindingsState = {}): {
  state: BindingsState;
  update: (mutate: (draft: BindingsState) => void) => Promise<void>;
} {
  const state: BindingsState = { ...initial };
  return {
    state,
    update: async (mutate) => {
      mutate(state);
    },
  };
}

describe("bindings", () => {
  test("write then read round-trips per directory", async () => {
    const fake = fakeStore();
    await writeBinding(fake.update, "/repo/a", "conv-1");
    await writeBinding(fake.update, "/repo/b", "conv-2");
    expect(readBinding(fake.state, "/repo/a")).toBe("conv-1");
    expect(readBinding(fake.state, "/repo/b")).toBe("conv-2");
    expect(bindingField("/repo/a")).toBe(bindingKey("/repo/a"));
  });

  test("detach deletes only its own directory", async () => {
    const fake = fakeStore();
    await writeBinding(fake.update, "/repo/a", "conv-1");
    await writeBinding(fake.update, "/repo/b", "conv-2");
    await writeBinding(fake.update, "/repo/a", null);
    expect(readBinding(fake.state, "/repo/a")).toBeNull();
    expect(readBinding(fake.state, "/repo/b")).toBe("conv-2");
  });

  test("missing directory falls back to a fixed key", async () => {
    const fake = fakeStore();
    await writeBinding(fake.update, null, "conv-9");
    expect(readBinding(fake.state, undefined)).toBe("conv-9");
    expect(readBinding(fake.state, "/elsewhere")).toBeNull();
  });

  test("empty stored values read as unbound", () => {
    expect(readBinding({ [bindingField("/r")]: "" }, "/r")).toBeNull();
  });
});

// ------------------------------------------------------------------ poll tick

function summaryResult(text: unknown, etag: string | null = null): GetResult {
  return { kind: "ok", json: JSON.parse(text as string) as unknown, etag };
}

describe("pollOnce", () => {
  test("304 with If-None-Match ends the tick silently", async () => {
    const cid = String(summaryOf("verified")["conversation_id"]);
    let snap = initialSnapshot(cid);
    const seen: (string | null)[] = [];
    const deps = {
      pollMs: 5000,
      getSummary: async (_id: string, etag: string | null): Promise<GetResult> => {
        seen.push(etag);
        return seen.length === 1
          ? summaryResult(JSON.stringify(summaryOf("verified")), "abc:123")
          : { kind: "not-modified" } as GetResult;
      },
      autoBind: async () => null,
      probeReachable: async () => true,
    };
    const first = await pollOnce(snap, 1000, deps);
    snap = first.snap;
    expect(first.status).toContain("✓1");
    expect(snap.summaryEtag).toBe("abc:123");
    const second = await pollOnce(snap, 6000, deps);
    expect(seen[1]).toBe("abc:123");
    expect(second.status).toBeNull();
    expect(second.toast).toBeNull();
  });

  test("offline degrades, backs off, recovers", async () => {
    const snap0 = initialSnapshot("conv_offline");
    let up = false;
    const calls: number[] = [];
    const deps = {
      pollMs: 1000,
      getSummary: async (): Promise<GetResult> => {
        calls.push(1);
        if (!up) return { kind: "failed" } as GetResult;
        const raw = summaryOf("empty");
        raw["conversation_id"] = "conv_offline";
        return summaryResult(JSON.stringify(raw));
      },
      autoBind: async () => null,
      probeReachable: async () => true,
    };
    const down = await pollOnce(snap0, 1000, deps);
    // bound id skips auto-bind; first failure goes offline with backoff
    expect(down.status).toBe("xmuse 离线");
    expect(down.snap.nextRetryAt).toBeGreaterThan(1000);
    const during = await pollOnce(down.snap, 1500, deps);
    expect(during.status).toBeNull();
    expect(calls.length).toBe(1);
    up = true;
    const recovered = await pollOnce(down.snap, 9000, deps);
    expect(recovered.status).toContain("看板");
  });

  test("unbound and unreachable goes offline", async () => {
    const out = await pollOnce(initialSnapshot(null), 1000, {
      pollMs: 5000,
      getSummary: async () => ({ kind: "failed" }) as GetResult,
      autoBind: async () => null,
      probeReachable: async () => false,
    });
    expect(out.status).toBe("xmuse 离线");
  });

  test("unbound but reachable with no board waits unbound", async () => {
    const out = await pollOnce(initialSnapshot(null), 1000, {
      pollMs: 5000,
      getSummary: async () => ({ kind: "failed" }) as GetResult,
      autoBind: async () => null,
      probeReachable: async () => true,
    });
    expect(out.status).toBe("xmuse 未绑定房间");
    expect(out.snap.nextRetryAt).toBe(31000);
  });
});

describe("autoBindRoom", () => {
  test("picks the newest room with modules", async () => {
    const rooms: RoomEntry[] = [
      { conversation_id: "c-old", updated_at: "2025-01-01T00:00:00Z" },
      { conversation_id: "c-new", updated_at: "2026-01-01T00:00:00Z" },
    ];
    const picked = await autoBindRoom({
      listRooms: async () => rooms,
      readSummary: async (id) => {
        const raw = summaryOf("empty");
        raw["conversation_id"] = id;
        raw["modules_total"] = id === "c-old" ? 2 : 0;
        return normalizeSummary(raw);
      },
    });
    expect(picked).toBe("c-old");
  });

  test("no rooms means no binding", async () => {
    expect(await autoBindRoom({ listRooms: async () => [], readSummary: async () => null })).toBeNull();
    expect(await autoBindRoom({ listRooms: async () => null, readSummary: async () => null })).toBeNull();
  });
});

// ------------------------------------------------------------------ commands

const TWO_ROOMS: RoomEntry[] = [
  { conversation_id: "conv-aaa-111", updated_at: "2025-01-01T00:00:00Z" },
  { conversation_id: "conv-bbb-222", updated_at: "2026-01-01T00:00:00Z" },
];

function commandDeps(snap: Snapshot, rooms: RoomEntry[] | null): {
  snapshot: () => Snapshot;
  listRooms: () => Promise<RoomEntry[] | null>;
  setBinding: (id: string | null) => void;
  bound: { id: string | null };
} {
  const bound = { id: snap.binding };
  return {
    snapshot: () => snap,
    listRooms: async () => rooms,
    setBinding: (id: string | null) => {
      bound.id = id;
    },
    bound,
  };
}

describe("runCommand", () => {
  test("status equals the compact block", async () => {
    const snap = initialSnapshot("c-1");
    snap.summary = normalized("verified");
    const deps = commandDeps(snap, null);
    const text = await runCommand("status", deps);
    expect(text).toContain("模块 2");
  });

  test("bare command shows status", async () => {
    const snap = initialSnapshot(null);
    const deps = commandDeps(snap, null);
    expect(await runCommand("", deps)).toBe("xmuse 未绑定房间");
  });

  test("attach with unique prefix binds", async () => {
    const deps = commandDeps(initialSnapshot(null), TWO_ROOMS);
    expect(await runCommand("attach conv-aaa", deps)).toBe("xmuse 已绑定 conv-aaa-111");
    expect(deps.bound.id).toBe("conv-aaa-111");
  });

  test("attach without args picks most recent; ambiguous prefix errors", async () => {
    const deps = commandDeps(initialSnapshot(null), TWO_ROOMS);
    expect(await runCommand("attach", deps)).toBe("xmuse 已绑定 conv-bbb-222");
    expect(await runCommand("attach conv-", deps)).toContain("多个房间");
    expect(await runCommand("attach nope", deps)).toContain("未找到房间");
  });

  test("attach with no backend reports unreachable", async () => {
    const deps = commandDeps(initialSnapshot(null), null);
    expect(await runCommand("attach", deps)).toContain("不可达");
  });

  test("detach clears", async () => {
    const deps = commandDeps(initialSnapshot("c-keep"), TWO_ROOMS);
    expect(await runCommand("detach", deps)).toBe("xmuse 已解绑");
    expect(deps.bound.id).toBeNull();
  });

  test("unknown subcommand prints usage", async () => {
    const deps = commandDeps(initialSnapshot(null), null);
    expect(await runCommand("frobnicate", deps)).toContain("用法");
  });
});

// ------------------------------------------------------- pure helper tables

describe("pure helpers", () => {
  test("backoff doubles and caps at 60s", () => {
    expect(backoffMs(0, 5000)).toBe(5000);
    expect(backoffMs(1, 5000)).toBe(10000);
    expect(backoffMs(10, 5000)).toBe(60000);
  });

  test("rooms sort newest first", () => {
    expect(sortRoomsByUpdated(TWO_ROOMS)[0].conversation_id).toBe("conv-bbb-222");
  });

  test("attach arg parsing", () => {
    expect(pickAttachTarget(TWO_ROOMS, "attach").ok).toBe(true);
    expect(pickAttachTarget([], "attach").ok).toBe(false);
  });

  test("safe helpers strip control text", () => {
    expect(safe("a\0bc", 10)).toBe("abc");
    expect(safeId("alpha")).toBe("alpha");
    expect(safeId("not valid!!")).toBe("not valid!!");
    expect(safeId("a\u0000b")).toBe("ab");
    expect(shortRoom("conv_1234567890abcdef")).toBe("conv_123");
  });

  test("summary normalization keeps all eleven count keys", () => {
    const summary = normalized("empty");
    expect(Object.keys(summary.counts)).toHaveLength(11);
    expect(summary.attention_total).toBe(0);
  });
});
