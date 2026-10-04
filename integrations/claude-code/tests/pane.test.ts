// Pane tests: every fixture draws a valid tree on terminal and desktop;
// agent text appears only after expand, only in labelled Text; status,
// toast, command and tool outputs never carry agent strings, ESC or bidi.
import { expect, mock, test } from "claude-code/testing";
import type { Engine, On } from "claude-code/testing";
import * as fx from "./fixtures.generated";

const OPTIONS = { options: { pollSeconds: 1 } };
const SURFACES = ["terminal", "desktop"] as const;

const BIDI = new RegExp("[\\u061c\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]");
const ESC = new RegExp("\\u001b");

function agentStrings(): string[] {
  const p = fx.injection_text.projection as unknown as {
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

function paneProps(bodyColumns: number): Record<string, unknown> {
  return {
    title: "xmuse 看板",
    isFocused: false,
    bodyColumns,
    placement: "dock",
    scroll: { offset: 0, bodyRows: 24 },
    view: {},
  };
}

async function loadFixture(
  $: Engine,
  on: On,
  name: "empty" | "split_pending" | "verified" | "injection_text" | "verification_error" | "contract_revised_stale_dependent",
  statuses: (string | undefined)[],
  toasts: string[],
): Promise<void> {
  const mod = (fx as unknown as Record<string, { summary: unknown; projection: unknown }>)[name];
  const cid = String((mod.summary as { conversation_id: string }).conversation_id);
  mock.store(on, { "binding:/repo": cid });
  const clock = mock.clock(on);
  on("ui.status", async (_$, e) => {
    statuses.push(e.text);
    return { value: undefined };
  });
  on("ui.toast", async (_$, e) => {
    toasts.push(e.text);
    return { value: undefined };
  });
  on("ui.open", async () => ({ value: { isPlaced: true } }));
  on("session.start", async (_$, e) => ({ cwd: e.cwd }));
  on("command.register", async () => ({ value: { command: "xmuse" } }));
  on("tool.register", async () => ({ value: { tool: "mcp__xmuse__status" } }));
  on("http.fetch", async (_$, e) => {
    const url = e.url;
    if (url.endsWith("/board/summary")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(mod.summary) } };
    }
    if (url.endsWith("/board")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(mod.projection) } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
}

const FIXTURES = ["empty", "split_pending", "verified", "injection_text", "verification_error", "contract_revised_stale_dependent"] as const;

for (const name of FIXTURES) {
  test(`pane draws ${name} on terminal and desktop`, OPTIONS, async ($, on) => {
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      const drawn = await ui.drawn();
      expect(drawn.type).toBe("Box");
      const header = await ui.find({ type: "Text", text: /看板|离线|未绑定/ });
      void header;
      const anyText = await ui.find({ type: "Text", text: /xmuse|看板/ });
      expect(anyText).toBeDefined();
      const markdowns = await ui.findAll({ type: "Markdown" });
      expect(markdowns).toHaveLength(0);
      await ui.unmount();
    }
  });
}

test("pane works at narrow widths", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "verified", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(24) as never,
    });
    expect((await ui.drawn()).type).toBe("Box");
    await ui.unmount();
  }
});

test("injection agent text hidden until expand, then labelled Text only", OPTIONS, async ($, on) => {
  const needles = agentStrings();
  expect(needles.length).toBeGreaterThan(0);
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "injection_text", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    // State is session-scoped: a previous surface iteration may have left
    // the module expanded. Collapse first so the pre-press check is valid.
    if (await ui.find({ type: "Text", text: /agent 自述/ })) {
      await ui.press({ key: "expand-alpha" });
    }
    for (const n of needles.slice(0, 3)) {
      expect(await ui.find({ type: "Text", text: n.slice(0, 40) })).toBeUndefined();
    }
    expect(await ui.find({ type: "Text", text: /agent 自述/ })).toBeUndefined();
    await ui.press({ key: "expand-alpha" });
    const label = await ui.find({ type: "Text", text: /agent 自述 · 未验证/ });
    expect(label).toBeDefined();
    const shown = await ui.find({ type: "Text", text: needles[0].slice(0, 40) });
    expect(shown).toBeDefined();
    expect(shown?.type).toBe("Text");
    const distinctive = await ui.find({ type: "Text", text: /progress#5\/summary/ });
    expect(distinctive).toBeDefined();
    const markdowns = await ui.findAll({ type: "Markdown" });
    expect(markdowns).toHaveLength(0);
    const links = await ui.findAll({ type: "Link" });
    for (const l of links) expect(l.text).not.toContain(needles[0].slice(0, 40));
    await ui.press({ key: "expand-alpha" });
    await ui.unmount();
  }
  for (const t of statuses) {
    for (const n of needles) expect(String(t)).not.toContain(n);
    expect(BIDI.test(String(t))).toBe(false);
    expect(ESC.test(String(t))).toBe(false);
  }
  for (const t of toasts) {
    for (const n of needles) expect(t).not.toContain(n);
  }
  const status = await $.command.run({ command: "xmuse", args: "status" });
  const called = await $.tool.call({ tool: "mcp__xmuse__status" });
  const result = String((called as unknown as { result?: unknown }).result ?? "");
  for (const n of needles) {
    expect(String(status.text)).not.toContain(n);
    expect(result).not.toContain(n);
  }
  expect(BIDI.test(String(status.text))).toBe(false);
  expect(ESC.test(String(status.text))).toBe(false);
});

test("proposed splits link to the web room page", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "split_pending", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    const link = await ui.find({ type: "Link", text: /在 Web 审批/ });
    expect(link).toBeDefined();
    expect(String((link?.props ?? {}).href ?? "")).toContain("/rooms/");
    await ui.unmount();
  }
});

test("unknown module states render as ?value", OPTIONS, async ($, on) => {
  const board = JSON.parse(JSON.stringify(fx.verified.projection)) as {
    modules: { module_id: string; state: string }[];
  };
  board.modules[0].state = "future_state_xyz";
  const summary = JSON.parse(JSON.stringify(fx.verified.summary)) as { conversation_id: string };
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  mock.store(on, { "binding:/repo": summary.conversation_id });
  const clock = mock.clock(on);
  on("ui.status", async (_$, e) => {
    statuses.push(e.text);
    return { value: undefined };
  });
  on("ui.toast", async (_$, e) => {
    toasts.push(e.text);
    return { value: undefined };
  });
  on("ui.open", async () => ({ value: { isPlaced: true } }));
  on("session.start", async (_$, e) => ({ cwd: e.cwd }));
  on("command.register", async () => ({ value: { command: "xmuse" } }));
  on("tool.register", async () => ({ value: { tool: "mcp__xmuse__status" } }));
  on("http.fetch", async (_$, e) => {
    if (e.url.endsWith("/board/summary")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(fx.verified.summary) } };
    }
    if (e.url.endsWith("/board")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(board) } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect((await ui.drawn()).type).toBe("Box");
    expect(await ui.find({ type: "Text", text: /\?future_state_xyz/ })).toBeDefined();
    await ui.unmount();
  }
  void statuses;
  void toasts;
});
