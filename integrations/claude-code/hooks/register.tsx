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
import { backoffMs, bindingKey, pickAttachTarget } from "../src/poll";
import { PaneTree, buildPaneNodes } from "../src/pane";
import { shortRoom } from "../src/text";

const PANE_ID = "xmuse";

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

    async function markFailed(cache: XmuseCache, now: number): Promise<void> {
      const failCount = cache.failCount + 1;
      await update($, cacheAtom, (c) => {
        const cur = c as XmuseCache;
        return { ...cur, offline: true, failCount, nextRetryAt: now + backoffMs(failCount, rt.pollMs) };
      });
      $.ui.status("xmuse 离线");
    }

    async function bindRoom(conversationId: string): Promise<void> {
      try {
        await $.store.set(bindingKey(cwd), conversationId);
      } catch {
        // binding still applies for this session
      }
      await update($, cacheAtom, (c) => {
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
        };
      });
    }

    async function autoBind(): Promise<boolean> {
      const roomsRes = await httpGet($, "/api/chat/rooms", null);
      if (roomsRes.kind !== "ok") return false;
      const rooms = normalizeRooms(roomsRes.json);
      if (rooms === null) return false;
      for (const room of sortRoomsByUpdated(rooms).slice(0, 8)) {
        const res = await httpGet(
          $,
          "/api/chat/conversations/" + encodeURIComponent(room.conversation_id) + "/board/summary",
          null,
        );
        if (res.kind !== "ok") continue;
        const summary: XmuseSummary | null = normalizeSummary(res.json);
        if (summary !== null && summary.modules_total > 0) {
          await bindRoom(room.conversation_id);
          return true;
        }
      }
      return false;
    }

    async function tick(): Promise<void> {
      const cache = (await read($, cacheAtom)) as XmuseCache;
      const now = await $.clock.now();
      if (now < cache.nextRetryAt) return;

      if (cache.binding === null) {
        if (cwd === "") {
          $.ui.status("xmuse 未绑定房间");
          return;
        }
        const bound = await autoBind();
        if (!bound) {
          const probe = await httpGet($, "/api/chat/rooms", null);
          if (probe.kind === "failed") {
            await markFailed(cache, now);
            return;
          }
          // Reachable but no room has a board yet: probe slowly instead of every tick.
          await update($, cacheAtom, (c) => ({
            ...(c as XmuseCache),
            offline: false,
            failCount: 0,
            nextRetryAt: now + 30000,
          }));
          $.ui.status("xmuse 未绑定房间");
          return;
        }
      }

      const live = (await read($, cacheAtom)) as XmuseCache;
      const boundId = live.binding;
      if (boundId === null) {
        $.ui.status("xmuse 未绑定房间");
        return;
      }

      const res = await httpGet(
        $,
        "/api/chat/conversations/" + encodeURIComponent(boundId) + "/board/summary",
        live.summaryEtag,
      );
      if (res.kind === "not-modified") return;
      if (res.kind === "failed") {
        await markFailed(live, now);
        return;
      }
      const summary = normalizeSummary(res.json);
      if (summary === null) {
        await markFailed(live, now);
        return;
      }

      const prevRevision = live.summary !== null ? live.summary.revision : null;
      const revisionChanged = prevRevision === null || summary.revision !== prevRevision;

      let stateNotes: string[] = [];
      let boardEtag: string | null = live.boardEtag;
      let nextBoard = live.board;
      if (revisionChanged && live.paneOpen) {
        const bRes = await httpGet(
          $,
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

      const fresh = (await read($, cacheAtom)) as XmuseCache;
      const finalToast = planToast(fresh, summary, stateNotes);
      const keys = summary.attention.filter((a) => a.kind === "operator").map(attentionKey);
      await update($, cacheAtom, (c) => {
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
      if (finalToast !== null) $.ui.toast(finalToast.text);
      const after = (await read($, cacheAtom)) as XmuseCache;
      $.ui.status(statusText(after));
    }

    rt.timer = $.clock.every(rt.pollMs, () => {
      if (rt.inFlight) return;
      rt.inFlight = true;
      void (async () => {
        try {
          await tick();
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
        };
      });
      return { text: "xmuse 已绑定 " + shortRoom(pick.conversation_id) };
    }
    if (first === "detach") {
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
    const onExpand = (moduleId: string): void => {
      void update($, cacheAtom, (c) => {
        const cur = c as XmuseCache;
        const expanded = { ...cur.expanded };
        if (expanded[moduleId] === true) delete expanded[moduleId];
        else expanded[moduleId] = true;
        return { ...cur, expanded };
      });
    };
    try {
      const cache = (await read($, cacheAtom)) as XmuseCache;
      const nodes = buildPaneNodes(cache, rt.webUrl);
      return PaneTree({ els: els as never, nodes, onExpand }) as never;
    } catch {
      return PaneTree({
        els: els as never,
        nodes: [{ type: "text", text: "xmuse 看板暂不可用" }],
        onExpand,
      }) as never;
    }
  });
};
