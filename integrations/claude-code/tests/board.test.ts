// Board status tests: status line, toasts, offline/backoff, overlap,
// ETag/304, binding, command and tool. One body run with explicit options
// (pollSeconds 1s). All test hooks register before the first $ call.
import { expect, mock, test } from "claude-code/testing";
import type { Engine, On } from "claude-code/testing";
import * as fx from "./fixtures.generated";

const OPTIONS = { options: { pollSeconds: 1 } };

type FetchInit = { method?: string; headers?: Record<string, string> };
type FetchResponse = { status: number; ok: boolean; headers: Record<string, string>; text: string };
type Handler = (url: string, init: FetchInit) => FetchResponse | Promise<FetchResponse>;

function installUi(on: On, statuses: (string | undefined)[], toasts: string[]): void {
  on("ui.status", async (_$, e) => {
    statuses.push(e.text);
    return { value: undefined };
  });
  on("ui.toast", async (_$, e) => {
    toasts.push(e.text);
    return { value: undefined };
  });
  on("ui.open", async () => ({ value: { isPlaced: true } }));
}

async function boot(
  $: Engine,
  on: On,
  storeEntries: Record<string, unknown>,
  handler: Handler,
  cwd = "/repo",
): Promise<{
  clock: { advance: (ms: number) => Promise<void>; settle: () => Promise<void>; now: () => number };
  statuses: (string | undefined)[];
  toasts: string[];
  log: { url: string; headers: Record<string, string> }[];
}> {
  mock.store(on, storeEntries);
  const clock = mock.clock(on);
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  installUi(on, statuses, toasts);
  on("session.start", async (_$, e) => ({ cwd: e.cwd }));
  on("command.register", async () => ({ value: { command: "xmuse" } }));
  on("tool.register", async () => ({ value: { tool: "mcp__xmuse__status" } }));
  const log: { url: string; headers: Record<string, string> }[] = [];
  on("http.fetch", async (_$, e) => {
    const init = (e.init ?? {}) as FetchInit;
    log.push({ url: e.url, headers: { ...(init.headers ?? {}) } });
    return { value: await handler(e.url, init) };
  });
  await $.session.start({ cwd, surface: "terminal", isInteractive: true });
  return { clock, statuses, toasts, log };
}

function json(text: unknown): string {
  return JSON.stringify(text);
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function summaryFor(conversationId: string, overrides?: Record<string, unknown>): string {
  const base = clone(fx.empty.summary) as Record<string, unknown>;
  base["conversation_id"] = conversationId;
  base["revision"] = "1:aaaa";
  if (overrides !== undefined) Object.assign(base, clone(overrides));
  return json(base);
}

function conversationOf(url: string): string {
  const m = url.match(/conversations\/([^/]+)\/board/);
  return m !== null ? decodeURIComponent(m[1]) : "";
}

function lastStatus(statuses: (string | undefined)[]): string {
  return String(statuses[statuses.length - 1] ?? "");
}

const NOT_FOUND: FetchResponse = { status: 404, ok: false, headers: {}, text: "{}" };

test("status line shows verified counts", OPTIONS, async ($, on) => {
  const cid = String((fx.verified.summary as { conversation_id: string }).conversation_id);
  const env = await boot($, on, { "binding:/repo": cid }, (url) =>
    url.endsWith("/board/summary")
      ? { status: 200, ok: true, headers: {}, text: json(fx.verified.summary) }
      : NOT_FOUND,
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toBe("看板 2 模块 · ✓1");
});

test("status line shows failure glyph and operator attention", OPTIONS, async ($, on) => {
  const cid = String((fx.verification_error.summary as { conversation_id: string }).conversation_id);
  const env = await boot($, on, { "binding:/repo": cid }, (url) =>
    url.endsWith("/board/summary")
      ? { status: 200, ok: true, headers: {}, text: json(fx.verification_error.summary) }
      : NOT_FOUND,
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toBe("看板 2 模块 · ‼1 · 待你处理 1");
});

test("done_claimed is unmistakable next to verified", OPTIONS, async ($, on) => {
  const claimed = clone(fx.verified.summary) as unknown as Record<string, unknown>;
  claimed["revision"] = "9:claimed";
  claimed["modules_total"] = 1;
  claimed["counts"] = {
    assigned: 0, claimed: 0, working: 0, blocked: 0, ready_for_review: 0,
    done_claimed: 1, verifying: 0, waiting_for_provider: 0, verified: 0,
    verification_failed: 0, verification_error: 0,
  };
  claimed["attention"] = [];
  claimed["attention_total"] = 0;
  const cid = String(claimed["conversation_id"]);
  const env = await boot($, on, { "binding:/repo": cid }, () => ({
    status: 200, ok: true, headers: {}, text: json(claimed),
  }));
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toBe("看板 1 模块 · ◌1");
});

test("toast on gained operator attention only, coalesced to one", OPTIONS, async ($, on) => {
  const first = clone(fx.lifecycle_mix.summary) as unknown as Record<string, unknown>;
  const second = clone(fx.verification_error.summary) as unknown as Record<string, unknown>;
  second["revision"] = "99:toast";
  const extra = { kind: "operator", reason_code: "board_attention_split_pending", module_id: null, split_id: "split_x" };
  second["attention"] = [...(second["attention"] as unknown[]), extra];
  second["attention_total"] = 2;
  const cid = String(first["conversation_id"]);
  let calls = 0;
  const env = await boot($, on, { "binding:/repo": cid }, () => {
    calls += 1;
    return { status: 200, ok: true, headers: {}, text: json(calls === 1 ? first : second) };
  });
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(0);
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(1);
  expect(env.toasts[0]).toContain("board_attention_verification_error");
  expect(env.toasts[0]).toContain("board_attention_split_pending");
});

test("state transition to verified toasts once", OPTIONS, async ($, on) => {
  const sumA = clone(fx.verifying_and_waiting.summary) as unknown as Record<string, unknown>;
  const sumB = clone(fx.verified.summary) as unknown as Record<string, unknown>;
  sumB["revision"] = "100:statechange";
  const cid = String(sumA["conversation_id"]);
  let n = 0;
  const env = await boot($, on, { "binding:/repo": cid }, (url) => {
    if (url.endsWith("/board/summary")) {
      n += 1;
      return { status: 200, ok: true, headers: {}, text: json(n === 1 ? sumA : sumB) };
    }
    if (url.endsWith("/board")) {
      return {
        status: 200, ok: true, headers: {},
        text: json(n === 1 ? fx.verifying_and_waiting.projection : fx.verified.projection),
      };
    }
    return NOT_FOUND;
  });
  const opened = await $.command.run({ command: "xmuse", args: "" });
  expect(opened.text).toBe("xmuse 看板已打开");
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(0);
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(1);
  expect(env.toasts[0]).toContain("alpha");
  expect(env.toasts[0]).toContain("已验证");
});

test("verified count growth toasts without the pane open, no ids", OPTIONS, async ($, on) => {
  const sumA = clone(fx.verifying_and_waiting.summary) as unknown as Record<string, unknown>;
  const sumB = clone(fx.verified.summary) as unknown as Record<string, unknown>;
  sumB["revision"] = "101:countgain";
  const cid = String(sumA["conversation_id"]);
  let n = 0;
  const env = await boot($, on, { "binding:/repo": cid }, (url) => {
    if (!url.endsWith("/board/summary")) return NOT_FOUND;
    n += 1;
    return { status: 200, ok: true, headers: {}, text: json(n === 1 ? sumA : sumB) };
  });
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(0);
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.some((entry) => entry.url.endsWith("/board"))).toBe(false);
  expect(env.toasts).toHaveLength(1);
  expect(env.toasts[0]).toContain("新增已验证");
});

test("offline degrades without throws or toast spam, backs off, recovers", OPTIONS, async ($, on) => {
  const cid = "conv_offline";
  let mode: "down" | "up" = "down";
  const env = await boot($, on, { "binding:/repo": cid }, () =>
    mode === "down"
      ? { status: 500, ok: false, headers: {}, text: "boom" }
      : { status: 200, ok: true, headers: {}, text: summaryFor(cid) },
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toBe("xmuse 离线");
  expect(env.toasts).toHaveLength(0);
  const afterFirst = env.log.length;
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.length).toBe(afterFirst);
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.length).toBe(afterFirst + 1);
  mode = "up";
  await env.clock.advance(4000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toContain("看板");
});

test("ticks never overlap", OPTIONS, async ($, on) => {
  const cid = "conv_overlap";
  let release: ((v: FetchResponse) => void) | null = null;
  const env = await boot(
    $,
    on,
    { "binding:/repo": cid },
    () => new Promise<FetchResponse>((resolve) => { release = resolve; }),
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.length).toBe(1);
  await env.clock.advance(1000);
  await env.clock.settle();
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.length).toBe(1);
  if (release !== null) release({ status: 200, ok: true, headers: {}, text: summaryFor(cid) });
  await env.clock.settle();
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.length).toBe(2);
  expect(lastStatus(env.statuses)).toContain("看板");
});

test("304 with If-None-Match ends the tick", OPTIONS, async ($, on) => {
  const cid = String((fx.verified.summary as { conversation_id: string }).conversation_id);
  let calls = 0;
  const env = await boot($, on, { "binding:/repo": cid }, (url) => {
    if (!url.endsWith("/board/summary")) return NOT_FOUND;
    calls += 1;
    if (calls === 1) return { status: 200, ok: true, headers: { etag: '"abc:123"' }, text: json(fx.verified.summary) };
    return { status: 304, ok: false, headers: {}, text: "" };
  });
  await env.clock.advance(1000);
  await env.clock.settle();
  const first = lastStatus(env.statuses);
  expect(first).toContain("✓1");
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.log.length).toBe(2);
  expect(env.log[1].headers["If-None-Match"]).toBe('"abc:123"');
  expect(lastStatus(env.statuses)).toBe(first);
  expect(env.toasts).toHaveLength(0);
});

function roomsHandler(rooms: { conversation_id: string; updated_at: string }[]): Handler {
  return (url) => {
    if (url.endsWith("/api/chat/rooms")) {
      return { status: 200, ok: true, headers: {}, text: json({ rooms }) };
    }
    return { status: 200, ok: true, headers: {}, text: summaryFor(conversationOf(url)) };
  };
}

const TWO_ROOMS = [
  { conversation_id: "conv-aaa-111", updated_at: "2025-01-01T00:00:00Z" },
  { conversation_id: "conv-bbb-222", updated_at: "2026-01-01T00:00:00Z" },
];

test("attach with unique prefix binds; status shows short id", OPTIONS, async ($, on) => {
  const env = await boot($, on, {}, roomsHandler(TWO_ROOMS));
  void env;
  const attached = await $.command.run({ command: "xmuse", args: "attach conv-aaa" });
  expect(attached.text).toBe("xmuse 已绑定 conv-aaa-111");
  const status = await $.command.run({ command: "xmuse", args: "status" });
  expect(status.text).toContain("conv-aaa-");
});

test("attach without args picks most recent; ambiguous prefix errors", OPTIONS, async ($, on) => {
  const env = await boot($, on, {}, roomsHandler(TWO_ROOMS));
  void env;
  const attached = await $.command.run({ command: "xmuse", args: "attach" });
  expect(attached.text).toBe("xmuse 已绑定 conv-bbb-222");
  const ambiguous = await $.command.run({ command: "xmuse", args: "attach conv-" });
  expect(ambiguous.text).toContain("多个房间");
  const missing = await $.command.run({ command: "xmuse", args: "attach nope" });
  expect(missing.text).toContain("未找到房间");
});

test("auto-bind picks most recent room with modules", OPTIONS, async ($, on) => {
  const env = await boot($, on, {}, (url) => {
    if (url.endsWith("/api/chat/rooms")) {
      return {
        status: 200, ok: true, headers: {},
        text: json({
          rooms: [
            { conversation_id: "c-old", updated_at: "2025-01-01T00:00:00Z" },
            { conversation_id: "c-new", updated_at: "2026-01-01T00:00:00Z" },
          ],
        }),
      };
    }
    const cid = conversationOf(url);
    return { status: 200, ok: true, headers: {}, text: summaryFor(cid, { modules_total: cid === "c-old" ? 2 : 0 }) };
  });
  await env.clock.advance(1000);
  await env.clock.settle();
  const status = await $.command.run({ command: "xmuse", args: "status" });
  expect(status.text).toContain("c-old");
});

test("detach clears the binding", OPTIONS, async ($, on) => {
  const env = await boot($, on, { "binding:/repo": "c-keep" }, () => ({
    status: 200, ok: true, headers: {}, text: summaryFor("c-keep"),
  }));
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toContain("看板");
  const detached = await $.command.run({ command: "xmuse", args: "detach" });
  expect(detached.text).toBe("xmuse 已解绑");
  expect(lastStatus(env.statuses)).toBe("xmuse 未绑定房间");
});

test("tool result equals status command and carries no agent text", OPTIONS, async ($, on) => {
  const cid = String((fx.injection_text.summary as { conversation_id: string }).conversation_id);
  const env = await boot($, on, { "binding:/repo": cid }, (url) => {
    if (url.endsWith("/board/summary")) {
      return { status: 200, ok: true, headers: {}, text: json(fx.injection_text.summary) };
    }
    if (url.endsWith("/board")) {
      return { status: 200, ok: true, headers: {}, text: json(fx.injection_text.projection) };
    }
    return NOT_FOUND;
  });
  await $.command.run({ command: "xmuse", args: "" });
  await env.clock.advance(1000);
  await env.clock.settle();
  const status = await $.command.run({ command: "xmuse", args: "status" });
  const called = await $.tool.call({ tool: "mcp__xmuse__status" });
  const result = (called as unknown as { result?: unknown }).result;
  expect(typeof result).toBe("string");
  expect(result).toBe(status.text);
  const agentStrings = [
    String((fx.injection_text.projection as unknown as { modules: { title: { text: string } }[] }).modules[0].title.text),
    String((fx.injection_text.projection as unknown as { modules: { title: { text: string } }[] }).modules[1].title.text),
  ];
  for (const s of agentStrings) {
    expect(status.text as string).not.toContain(s);
    expect(result as string).not.toContain(s);
  }
  for (const t of env.statuses) expect(String(t)).not.toContain(agentStrings[0]);
  for (const t of env.toasts) expect(t).not.toContain(agentStrings[0]);
});

test("unknown enum values and missing capabilities degrade gracefully", OPTIONS, async ($, on) => {
  const weird = clone(fx.verified.summary) as unknown as Record<string, unknown>;
  weird["revision"] = "7:weird";
  weird["capabilities"] = undefined;
  weird["attention"] = [{ kind: "mystery", reason_code: "future_code", module_id: "alpha", split_id: null }];
  const cid = String(weird["conversation_id"]);
  const env = await boot($, on, { "binding:/repo": cid }, () => ({
    status: 200, ok: true, headers: {}, text: json(weird),
  }));
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toContain("看板");
  expect(env.toasts).toHaveLength(0);
});

test("status check mark counts accepted modules, not verified ones", OPTIONS, async ($, on) => {
  const cid = String((fx.review_operator_pending.summary as { conversation_id: string }).conversation_id);
  const env = await boot($, on, { "binding:/repo": cid }, (url) =>
    url.endsWith("/board/summary")
      ? { status: 200, ok: true, headers: {}, text: json(fx.review_operator_pending.summary) }
      : NOT_FOUND,
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  // verified: 2 in counts, but only 1 accepted: the mark follows accepted.
  expect(lastStatus(env.statuses)).toBe("看板 2 模块 · ✓1 · 待你处理 1");
});

test("verified-but-not-accepted shows no check mark", OPTIONS, async ($, on) => {
  const cid = String((fx.review_escalated.summary as { conversation_id: string }).conversation_id);
  const env = await boot($, on, { "binding:/repo": cid }, (url) =>
    url.endsWith("/board/summary")
      ? { status: 200, ok: true, headers: {}, text: json(fx.review_escalated.summary) }
      : NOT_FOUND,
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toBe("看板 2 模块 · 待你处理 1");
});

test("missing accepted_total falls back to the verified count", OPTIONS, async ($, on) => {
  const old = clone(fx.verified.summary) as unknown as Record<string, unknown>;
  old["revision"] = "8:oldserver";
  delete old["accepted_total"];
  delete old["capabilities"];
  const cid = String(old["conversation_id"]);
  const env = await boot($, on, { "binding:/repo": cid }, () => ({
    status: 200, ok: true, headers: {}, text: json(old),
  }));
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(lastStatus(env.statuses)).toBe("看板 2 模块 · ✓1");
});

test("review operator-pending toast uses the fixed label", OPTIONS, async ($, on) => {
  const first = clone(fx.lifecycle_mix.summary) as unknown as Record<string, unknown>;
  const second = clone(fx.review_operator_pending.summary) as unknown as Record<string, unknown>;
  second["revision"] = "102:reviewpending";
  const cid = String(first["conversation_id"]);
  let calls = 0;
  const env = await boot($, on, { "binding:/repo": cid }, () => {
    calls += 1;
    return { status: 200, ok: true, headers: {}, text: json(calls === 1 ? first : second) };
  });
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(0);
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(1);
  expect(env.toasts[0]).toContain("待你复核");
  expect(env.toasts[0]).toContain("beta");
});

test("review objected toast uses the fixed label", OPTIONS, async ($, on) => {
  const first = clone(fx.lifecycle_mix.summary) as unknown as Record<string, unknown>;
  const second = clone(fx.review_objected.summary) as unknown as Record<string, unknown>;
  second["revision"] = "103:reviewobjected";
  const cid = String(first["conversation_id"]);
  let calls = 0;
  const env = await boot($, on, { "binding:/repo": cid }, () => {
    calls += 1;
    return { status: 200, ok: true, headers: {}, text: json(calls === 1 ? first : second) };
  });
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(0);
  await env.clock.advance(1000);
  await env.clock.settle();
  expect(env.toasts).toHaveLength(1);
  expect(env.toasts[0]).toContain("复核被驳回待返工");
  expect(env.toasts[0]).toContain("alpha");
});

test("status block shows the review attention label", OPTIONS, async ($, on) => {
  const cid = String((fx.review_operator_pending.summary as { conversation_id: string }).conversation_id);
  const env = await boot($, on, { "binding:/repo": cid }, (url) =>
    url.endsWith("/board/summary")
      ? { status: 200, ok: true, headers: {}, text: json(fx.review_operator_pending.summary) }
      : NOT_FOUND,
  );
  await env.clock.advance(1000);
  await env.clock.settle();
  const status = await $.command.run({ command: "xmuse", args: "status" });
  expect(String(status.text)).toContain("待你复核");
  expect(String(status.text)).toContain("beta");
});
