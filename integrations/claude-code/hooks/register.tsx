// xmuse board status mod. All engine calls ($, on, next) live in this
// file; ../src/* holds pure helpers only (text, labels, normalizers,
// status/toast builders, pane nodes).
import { atom, read, update } from "claude-code";
import type { Register } from "claude-code";
import type { XmuseCache, XmuseSummary } from "../types/index";
import {
  normalizeBoard,
  normalizeRooms,
  normalizeSummary,
  parseGetResponse,
  sortRoomsByUpdated,
  type GetResult,
} from "../src/api";
import { attentionKey, planStateToasts, planToast, statusBlock, statusText } from "../src/board_state";
import {
  decideSplit,
  detailCodeOf,
  exchangeGrant,
  parseExchangePayload,
  revokeGrant,
  type GrantHttp,
} from "../src/grant_api";
import {
  checkConfirmInput,
  exchangeToast,
  failureToast,
  grantExpired,
  mapDecisionOutcome,
  validatePairingCode,
} from "../src/grant_state";
import { backoffMs, bindingKey, pickAttachTarget } from "../src/poll";
import { PaneTree, buildPaneNodes } from "../src/pane";
import { shortRoom } from "../src/text";

const PANE_ID = "xmuse";

// The grant token lives only here, in module scope: a reload drops it and
// the pane falls back to the unauthorized view. It never enters the atom,
// the store, a toast, a status line, a command result or the pane tree.
let grantToken: string | null = null;

const cacheAtom = atom({ plugin: "xmuse", key: "cache" } as const, {
  binding: null,
  cwd: null,
  summary: null,
  board: null,
  summaryEtag: null,
  boardEtag: null,
  lastPollAt: null,
  offline: false,
  baselined: false,
  seenAttention: [],
  seenStates: {},
  failCount: 0,
  nextRetryAt: 0,
  paneOpen: false,
  expanded: {},
  grant: null,
  confirming: null,
  formEpoch: 0,
} as XmuseCache);

const rt = {
  baseUrl: "http://127.0.0.1:8201",
  webUrl: "http://127.0.0.1:3000",
  pollMs: 5000,
  timer: null as { cancel: () => void } | null,
  inFlight: false,
};

function readOptions(options: unknown): void {
  const o = (options ?? {}) as Record<string, unknown>;
  if (typeof o["baseUrl"] === "string" && o["baseUrl"] !== "") rt.baseUrl = o["baseUrl"];
  if (typeof o["webUrl"] === "string" && o["webUrl"] !== "") rt.webUrl = o["webUrl"];
  const poll = Number(o["pollSeconds"] ?? 5);
  rt.pollMs = Number.isFinite(poll) && poll > 0 ? Math.min(Math.floor(poll * 1000), 60000) : 5000;
}

function base(): string {
  return rt.baseUrl.replace(/\/+$/, "");
}

// The single place $.http.fetch is spelled: same file, plain GET, with an
// optional If-None-Match. Pure parsing lives in ../src/api.
async function httpGet(caller: any, path: string, etag: string | null): Promise<GetResult> {
  const headers: Record<string, string> = {};
  if (etag !== null && etag !== "") headers["If-None-Match"] = '"' + etag + '"';
  try {
    const res = await caller.http.fetch(base() + path, { method: "GET", headers });
    const rawHeaders = res.headers !== undefined && res.headers !== null ? res.headers : {};
    return parseGetResponse({ status: res.status, headers: rawHeaders, text: res.text });
  } catch {
    return { kind: "failed" };
  }
}

// Transport injected into the pure grant shapes: forwards the caller's init
// untouched, so the write method and headers are spelled once, in the pure
// module. A rejected fetch surfaces as status 0 (network failure).
function pluginHttp(caller: any): GrantHttp {
  return (url, init) =>
    caller.http.fetch(url, init).then(
      (res: any) => ({ status: res.status as number, text: res.text as string }),
      () => ({ status: 0, text: "" }),
    );
}

async function markFailed(caller: any, cache: XmuseCache, now: number): Promise<void> {
  const failCount = cache.failCount + 1;
  await update(caller, cacheAtom, (c) => {
    const cur = c as XmuseCache;
    return { ...cur, offline: true, failCount, nextRetryAt: now + backoffMs(failCount, rt.pollMs) };
  });
  caller.ui.status("xmuse 离线");
}

async function bindRoom(caller: any, conversationId: string): Promise<void> {
  const live = (await read(caller, cacheAtom)) as XmuseCache;
  const dir = live.cwd ?? "";
  try {
    await caller.store.set(bindingKey(dir), conversationId);
  } catch {
    // binding still applies for this session
  }
  await update(caller, cacheAtom, (c) => {
    const cur = c as XmuseCache;
    return {
      ...cur,
      binding: conversationId,
      summary: null,
      board: null,
      summaryEtag: null,
      boardEtag: null,
      offline: false,
      baselined: false,
      seenAttention: [],
      seenStates: {},
      failCount: 0,
      nextRetryAt: 0,
      confirming: null,
    };
  });
}

async function autoBind(caller: any): Promise<boolean> {
  const roomsRes = await httpGet(caller, "/api/chat/rooms", null);
  if (roomsRes.kind !== "ok") return false;
  const rooms = normalizeRooms(roomsRes.json);
  if (rooms === null) return false;
  for (const room of sortRoomsByUpdated(rooms).slice(0, 8)) {
    const res = await httpGet(
      caller,
      "/api/chat/conversations/" + encodeURIComponent(room.conversation_id) + "/board/summary",
      null,
    );
    if (res.kind !== "ok") continue;
    const summary: XmuseSummary | null = normalizeSummary(res.json);
    if (summary !== null && summary.modules_total > 0) {
      await bindRoom(caller, room.conversation_id);
      return true;
    }
  }
  return false;
}

// Best-effort refresh of the board after a decision outcome says the
// room changed. Failures stay silent: the next poll tick retries.
async function refreshBoard(caller: any): Promise<void> {
  const live = (await read(caller, cacheAtom)) as XmuseCache;
  const boundId = live.binding;
  if (boundId === null) return;
  const sRes = await httpGet(
    caller,
    "/api/chat/conversations/" + encodeURIComponent(boundId) + "/board/summary",
    live.summaryEtag,
  );
  if (sRes.kind === "ok") {
    const summary = normalizeSummary(sRes.json);
    if (summary !== null) {
      const etag = sRes.etag;
      await update(caller, cacheAtom, (c) => ({
        ...(c as XmuseCache),
        summary,
        summaryEtag: etag ?? (c as XmuseCache).summaryEtag,
      }));
    }
  }
  const bRes = await httpGet(
    caller,
    "/api/chat/conversations/" + encodeURIComponent(boundId) + "/board",
    live.boardEtag,
  );
  if (bRes.kind === "ok") {
    const board = normalizeBoard(bRes.json);
    if (board !== null) {
      const etag = bRes.etag;
      await update(caller, cacheAtom, (c) => ({
        ...(c as XmuseCache),
        board,
        boardEtag: etag ?? (c as XmuseCache).boardEtag,
      }));
    }
  }
}

async function dropGrant(caller: any): Promise<void> {
  grantToken = null;
  await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), grant: null, confirming: null }));
}

async function revokeBestEffort(caller: any): Promise<void> {
  const held = grantToken;
  if (held !== null) {
    try {
      await revokeGrant(pluginHttp(caller), base(), held);
    } catch {
      // best effort: the local drop below runs regardless
    }
  }
  await dropGrant(caller);
}

// Runs only from the pairing Input submit. Clears the field on every
// path by bumping the form epoch, so the next draw shows an empty
// field whatever the outcome was.
async function submitPairing(caller: any, rawValue: string): Promise<void> {
  const checked = validatePairingCode(rawValue);
  if (!checked.ok) {
    await update(caller, cacheAtom, (c) => ({
      ...(c as XmuseCache),
      formEpoch: (c as XmuseCache).formEpoch + 1,
    }));
    caller.ui.toast(checked.hint);
    return;
  }
  const res = await exchangeGrant(pluginHttp(caller), base(), checked.code);
  if (res.status === 200) {
    const parsed = parseExchangePayload(res.json);
    if (parsed !== null) {
      grantToken = parsed.token;
      const meta = parsed.grant;
      await update(caller, cacheAtom, (c) => ({
        ...(c as XmuseCache),
        grant: { grantId: meta.grantId, expiresAt: meta.expiresAt, conversationId: meta.conversationId },
        confirming: null,
      }));
      const at = await caller.clock.now();
      caller.ui.toast(exchangeToast(meta.expiresAt, at));
      return;
    }
  }
  await update(caller, cacheAtom, (c) => ({
    ...(c as XmuseCache),
    formEpoch: (c as XmuseCache).formEpoch + 1,
  }));
  caller.ui.toast(failureToast(res.status));
}

// Runs only from the confirm Input submit. A mismatch sends nothing.
// Confirming state clears on every path.
async function submitConfirm(caller: any, rawValue: string): Promise<void> {
  const live = (await read(caller, cacheAtom)) as XmuseCache;
  const pending = live.confirming;
  const held = grantToken;
  if (pending === null || held === null || live.binding === null) {
    await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), confirming: null }));
    caller.ui.toast("授权已失效，请在 Web 重新授权");
    return;
  }
  const rows = live.board !== null ? live.board.splits : [];
  const row = rows.find((s) => s.split_id === pending.splitId) ?? null;
  if (row === null || row.status !== "proposed" || row.digest === "") {
    await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), confirming: null }));
    await refreshBoard(caller);
    caller.ui.toast("拆分已不能决定，已刷新");
    return;
  }
  const check = checkConfirmInput(row.digest, rawValue);
  if (!check.ok) {
    await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), confirming: null }));
    caller.ui.toast(check.hint);
    return;
  }
  const decision = pending.decision === "reject" ? "reject" : "approve";
  const res = await decideSplit(pluginHttp(caller), base(), held, pending.splitId, live.binding, decision, row.digest);
  const outcome = mapDecisionOutcome(res.status, detailCodeOf(res.json), decision);
  if (outcome.clearGrant) {
    await dropGrant(caller);
  } else {
    await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), confirming: null }));
  }
  if (outcome.refetch) await refreshBoard(caller);
  caller.ui.toast(outcome.toast);
}

// Runs only from pane Button presses. Setting confirming never acts:
// the decision is sent only after the digest confirm submit matches.
async function pressControl(caller: any, key: string): Promise<void> {
  if (key === "xmuse-revoke") {
    await revokeBestEffort(caller);
    return;
  }
  if (key === "xmuse-cancel-confirm") {
    await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), confirming: null }));
    return;
  }
  const live = (await read(caller, cacheAtom)) as XmuseCache;
  if (live.grant === null || live.binding === null) return;
  if (live.grant.conversationId !== live.binding) return;
  if (grantExpired(live.grant.expiresAt, await caller.clock.now())) return;
  const rows = live.board !== null ? live.board.splits : [];
  for (const row of rows) {
    if (key !== "xmuse-approve-" + row.split_id && key !== "xmuse-reject-" + row.split_id) continue;
    if (row.status !== "proposed" || row.digest === "") return;
    const decision = key === "xmuse-reject-" + row.split_id ? "reject" : "approve";
    await update(caller, cacheAtom, (c) => ({
      ...(c as XmuseCache),
      confirming: { splitId: row.split_id, decision },
    }));
    return;
  }
}

async function submitControl(caller: any, key: string, value: string): Promise<void> {
  if (key === "xmuse-pairing") {
    await submitPairing(caller, value);
    return;
  }
  if (key === "xmuse-confirm") {
    await submitConfirm(caller, value);
  }
}

async function tick(caller: any): Promise<void> {
  const cache = (await read(caller, cacheAtom)) as XmuseCache;
  const now = await caller.clock.now();
  if (now < cache.nextRetryAt) return;

  // Grant expiry rides the existing poll tick: at expiresAt the token
  // is dropped and the pane returns to the unauthorized view.
  if (cache.grant !== null && grantExpired(cache.grant.expiresAt, now)) {
    grantToken = null;
    await update(caller, cacheAtom, (c) => ({ ...(c as XmuseCache), grant: null, confirming: null }));
  }

  if (cache.binding === null) {
    const dir = cache.cwd ?? "";
    if (dir === "") {
      caller.ui.status("xmuse 未绑定房间");
      return;
    }
    const bound = await autoBind(caller);
    if (!bound) {
      const probe = await httpGet(caller, "/api/chat/rooms", null);
      if (probe.kind === "failed") {
        await markFailed(caller, cache, now);
        return;
      }
      // Reachable but no room has a board yet: probe slowly instead of every tick.
      await update(caller, cacheAtom, (c) => ({
        ...(c as XmuseCache),
        offline: false,
        failCount: 0,
        nextRetryAt: now + 30000,
      }));
      caller.ui.status("xmuse 未绑定房间");
      return;
    }
  }

  const live = (await read(caller, cacheAtom)) as XmuseCache;
  const boundId = live.binding;
  if (boundId === null) {
    caller.ui.status("xmuse 未绑定房间");
    return;
  }

  const res = await httpGet(
    caller,
    "/api/chat/conversations/" + encodeURIComponent(boundId) + "/board/summary",
    live.summaryEtag,
  );
  if (res.kind === "not-modified") return;
  if (res.kind === "failed") {
    await markFailed(caller, live, now);
    return;
  }
  const summary = normalizeSummary(res.json);
  if (summary === null) {
    await markFailed(caller, live, now);
    return;
  }

  const prevRevision = live.summary !== null ? live.summary.revision : null;
  const revisionChanged = prevRevision === null || summary.revision !== prevRevision;

  let stateNotes: string[] = [];
  let boardEtag: string | null = live.boardEtag;
  let nextBoard = live.board;
  if (revisionChanged && live.paneOpen) {
    const bRes = await httpGet(
      caller,
      "/api/chat/conversations/" + encodeURIComponent(boundId) + "/board",
      live.boardEtag,
    );
    if (bRes.kind === "ok") {
      const board = normalizeBoard(bRes.json);
      if (board !== null) {
        if (live.board !== null) {
          const nextStates: { [id: string]: string } = {};
          for (const m of board.modules) nextStates[m.module_id] = m.state;
          stateNotes = planStateToasts(live.seenStates, nextStates);
        }
        nextBoard = board;
        boardEtag = bRes.etag;
      }
    }
  }

  const fresh = (await read(caller, cacheAtom)) as XmuseCache;
  const finalToast = planToast(fresh, summary, stateNotes);
  const keys = summary.attention.filter((a) => a.kind === "operator").map(attentionKey);
  await update(caller, cacheAtom, (c) => {
    const cur = c as XmuseCache;
    const nextStates: { [id: string]: string } = { ...cur.seenStates };
    if (nextBoard !== null && nextBoard !== cur.board) {
      for (const m of nextBoard.modules) nextStates[m.module_id] = m.state;
    }
    return {
      ...cur,
      summary,
      board: nextBoard,
      summaryEtag: res.kind === "ok" ? (res.etag ?? cur.summaryEtag) : cur.summaryEtag,
      boardEtag: boardEtag ?? cur.boardEtag,
      lastPollAt: now,
      offline: false,
      baselined: true,
      seenAttention: keys,
      seenStates: nextStates,
      failCount: 0,
      nextRetryAt: 0,
    };
  });
  if (finalToast !== null) caller.ui.toast(finalToast.text);
  const after = (await read(caller, cacheAtom)) as XmuseCache;
  caller.ui.status(statusText(after));
}

export const register: Register = (on, options) => {
  readOptions(options);

  on("session.start", async ($, e, next) => {
    if (rt.timer !== null) {
      try {
        rt.timer.cancel();
      } catch {
        // replaced below
      }
      rt.timer = null;
    }
    rt.inFlight = false;
    grantToken = null;
    const cwd = typeof e.cwd === "string" ? e.cwd : "";
    let binding: string | null = null;
    try {
      const stored = await $.store.get(bindingKey(cwd));
      if (typeof stored === "string" && stored !== "") binding = stored;
    } catch {
      binding = null;
    }
    await update($, cacheAtom, () => ({
      binding,
      cwd,
      summary: null,
      board: null,
      summaryEtag: null,
      boardEtag: null,
      lastPollAt: null,
      offline: false,
      baselined: false,
      seenAttention: [],
      seenStates: {},
      failCount: 0,
      nextRetryAt: 0,
      paneOpen: false,
      expanded: {},
      grant: null,
      confirming: null,
      formEpoch: 0,
    }));
    await $.command.register({
      name: "xmuse",
      description: "xmuse board status: attach, detach, status, pane",
      argumentHint: "[attach|detach|status|pane]",
    });
    await $.tool.register({
      name: "status",
      description: "Read-only xmuse board status: module counts, state codes and operator attention. No inputs.",
      inputSchema: { type: "object", properties: {} },
    });
    $.ui.status(binding === null ? "xmuse 未绑定房间" : "xmuse …");

    rt.timer = $.clock.every(rt.pollMs, () => {
      if (rt.inFlight) return;
      rt.inFlight = true;
      void (async () => {
        try {
          await tick($);
        } catch {
          // degraded: never throw out of the poll loop
        } finally {
          rt.inFlight = false;
        }
      })();
    });
    return next(e);
  });

  on("command.run", { command: "xmuse" }, async ($, e) => {
    const args = typeof e.args === "string" ? e.args.trim() : "";
    const first = args.split(/\s+/)[0] ?? "";
    const cache = (await read($, cacheAtom)) as XmuseCache;
    const sessionCwd = cache.cwd ?? "";
    if (first === "status") return { text: statusBlock(cache) };
    if (first === "attach") {
      const roomsRes = await httpGet($, "/api/chat/rooms", null);
      if (roomsRes.kind !== "ok") return { text: "xmuse 绑定失败: 后端不可达" };
      const rooms = normalizeRooms(roomsRes.json);
      if (rooms === null) return { text: "xmuse 绑定失败: 后端不可达" };
      const pick = pickAttachTarget(rooms, args);
      if (!pick.ok) return { text: pick.error };
      try {
        await $.store.set(bindingKey(sessionCwd), pick.conversation_id);
      } catch {
        // binding still applies for this session
      }
      await update($, cacheAtom, (c) => {
        const cur = c as XmuseCache;
        return {
          ...cur,
          binding: pick.conversation_id,
          summary: null,
          board: null,
          summaryEtag: null,
          boardEtag: null,
          offline: false,
          baselined: false,
          seenAttention: [],
          seenStates: {},
          failCount: 0,
          nextRetryAt: 0,
          confirming: null,
        };
      });
      return { text: "xmuse 已绑定 " + shortRoom(pick.conversation_id) };
    }
    if (first === "detach") {
      try {
        await revokeBestEffort($);
      } catch {
        // best effort: the local clear below runs regardless
      }
      try {
        await $.store.delete(bindingKey(sessionCwd));
      } catch {
        // state still clears below
      }
      await update($, cacheAtom, (c) => {
        const cur = c as XmuseCache;
        return {
          ...cur,
          binding: null,
          summary: null,
          board: null,
          summaryEtag: null,
          boardEtag: null,
          offline: false,
          baselined: false,
          seenAttention: [],
          seenStates: {},
          failCount: 0,
          nextRetryAt: 0,
          grant: null,
          confirming: null,
        };
      });
      $.ui.status("xmuse 未绑定房间");
      return { text: "xmuse 已解绑" };
    }
    if (first !== "" && first !== "pane") return { text: "xmuse 用法: /xmuse [attach|detach|status|pane]" };
    await update($, cacheAtom, (c) => ({ ...(c as XmuseCache), paneOpen: true }));
    try {
      await $.ui.open({ id: PANE_ID, title: "xmuse 看板" });
    } catch {
      // paneOpen is still recorded; the next tick fetches the board
    }
    return { text: "xmuse 看板已打开" };
  });

  on("tool.call", { tool: "mcp__xmuse__status" }, async ($) => {
    const cache = (await read($, cacheAtom)) as XmuseCache;
    return { result: statusBlock(cache) };
  });

  on("ui.render", { component: "Pane", requestId: PANE_ID }, async ($, e) => {
    const els = $.ui.resolve(e);
    const at = await $.clock.now();
    const onExpand = (moduleId: string): void => {
      void update($, cacheAtom, (c) => {
        const cur = c as XmuseCache;
        const expanded = { ...cur.expanded };
        if (expanded[moduleId] === true) delete expanded[moduleId];
        else expanded[moduleId] = true;
        return { ...cur, expanded };
      });
    };
    const onControl = (key: string): void => {
      void pressControl($, key);
    };
    const onSubmitKey = (key: string, value: string): void => {
      void submitControl($, key, value);
    };
    const onSubmit = onSubmitKey;
    void onSubmit;
    try {
      const cache = (await read($, cacheAtom)) as XmuseCache;
      const nodes = buildPaneNodes(cache, rt.webUrl, at);
      return PaneTree({ els: els as never, nodes, onExpand, onControl, onSubmit: onSubmitKey }) as never;
    } catch {
      return PaneTree({
        els: els as never,
        nodes: [{ type: "text", text: "xmuse 看板暂不可用" }],
        onExpand,
        onControl,
        onSubmit: onSubmitKey,
      }) as never;
    }
  });
};
