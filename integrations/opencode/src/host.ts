// OpenCode host adapter: the only module that touches the TUI plugin
// context (via the structural TuiContext / createBoardHost bridge in this
// file). Everything here is pure and bun-testable with fakes: base-URL
// validation, per-directory bindings, the summary poll tick and the /xmuse
// command runner. Only GET requests; every rendered string is built from
// structured fields only (counts, state codes, ids, reason codes).

import {
  normalizeRooms,
  normalizeSummary,
  parseGetResponse,
  sortRoomsByUpdated,
  type GetResult,
  type RoomEntry,
} from "./core/api";
import { attentionKey, planToast, statusBlock, statusText } from "./core/board_state";
import { backoffMs, bindingKey, pickAttachTarget } from "./core/poll";
import { safe, shortRoom } from "./core/text";
import type { XmuseCache, XmuseSummary } from "./core/types";

export const DEFAULT_BASE_URL = "http://127.0.0.1:8201";
export const POLL_MS = 5000;
export const BINDINGS_STORE = "bindings";
export const FALLBACK_DIR = "default";

// ---------------------------------------------------------------------------
// Base URL: loopback only (§8 of the board contract). Anything else is
// rejected before any request is made.
// ---------------------------------------------------------------------------

export type BaseUrlResolution = { ok: true; baseUrl: string } | { ok: false; error: string };

function isLoopbackHost(host: string): boolean {
  const h = host.toLowerCase();
  return h === "127.0.0.1" || h === "localhost" || h === "::1" || h === "[::1]";
}

export function resolveBaseUrl(env: Record<string, string | undefined>): BaseUrlResolution {
  const raw = (env["XMUSE_BASE_URL"] ?? "").trim();
  const candidate = (raw === "" ? DEFAULT_BASE_URL : raw).replace(/\/+$/, "");
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return { ok: false, error: "xmuse 基地址无效" };
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { ok: false, error: "xmuse 基地址无效" };
  }
  if (!isLoopbackHost(parsed.hostname)) {
    return { ok: false, error: "xmuse 基地址只允许本机回环地址" };
  }
  return { ok: true, baseUrl: candidate };
}

// ---------------------------------------------------------------------------
// Bindings: one durable store ("bindings"), one field per working directory.
// The update callback follows the context storage form: mutate in place.
// ---------------------------------------------------------------------------

export type BindingsState = { [field: string]: string };

export type BindingUpdate = (mutate: (draft: BindingsState) => void) => void | Promise<void>;

export function bindingField(directory: string | null | undefined): string {
  const dir = typeof directory === "string" && directory !== "" ? directory : FALLBACK_DIR;
  return bindingKey(dir);
}

export function readBinding(
  store: BindingsState,
  directory: string | null | undefined,
): string | null {
  const id = store[bindingField(directory)];
  return typeof id === "string" && id !== "" ? id : null;
}

export function writeBinding(
  update: BindingUpdate,
  directory: string | null | undefined,
  id: string | null,
): void | Promise<void> {
  const field = bindingField(directory);
  if (id === null) {
    return update((draft) => {
      delete draft[field];
    });
  }
  const pinned = safe(id, 128);
  return update((draft) => {
    draft[field] = pinned;
  });
}

// ---------------------------------------------------------------------------
// HTTP: plain GET with an optional If-None-Match. Parsing is pure (core).
// ---------------------------------------------------------------------------

export type FetchImpl = (
  url: string,
  init: { method: string; headers: Record<string, string> },
) => Promise<{ status: number; headers: Record<string, string>; text: string }>;

export const defaultFetch: FetchImpl = async (url, init) => {
  const res = await fetch(url, init);
  const headers: Record<string, string> = {};
  res.headers.forEach((value, key) => {
    headers[key.toLowerCase()] = value;
  });
  return { status: res.status, headers, text: await res.text() };
};

export async function httpGet(
  baseUrl: string,
  path: string,
  etag: string | null,
  doFetch: FetchImpl = defaultFetch,
): Promise<GetResult> {
  const headers: Record<string, string> = {};
  if (etag !== null && etag !== "") headers["If-None-Match"] = '"' + etag + '"';
  try {
    const res = await doFetch(baseUrl + path, { method: "GET", headers });
    return parseGetResponse(res);
  } catch {
    return { kind: "failed" };
  }
}

export function summaryPath(conversationId: string): string {
  return "/api/chat/conversations/" + encodeURIComponent(conversationId) + "/board/summary";
}

// ---------------------------------------------------------------------------
// Poll state. Summary-only: without a pane there is no full-board fetch, so
// verification outcomes toast from the summary counts (same as the mod with
// its pane closed). No toast on the first successful poll (baseline).
// ---------------------------------------------------------------------------

export type Snapshot = {
  binding: string | null;
  summary: XmuseSummary | null;
  summaryEtag: string | null;
  offline: boolean;
  baselined: boolean;
  seenAttention: string[];
  failCount: number;
  nextRetryAt: number;
};

export function initialSnapshot(binding: string | null): Snapshot {
  return {
    binding,
    summary: null,
    summaryEtag: null,
    offline: false,
    baselined: false,
    seenAttention: [],
    failCount: 0,
    nextRetryAt: 0,
  };
}

export function toCache(snap: Snapshot): XmuseCache {
  return {
    binding: snap.binding,
    cwd: null,
    summary: snap.summary,
    board: null,
    summaryEtag: snap.summaryEtag,
    boardEtag: null,
    lastPollAt: null,
    offline: snap.offline,
    baselined: snap.baselined,
    seenAttention: snap.seenAttention,
    seenStates: {},
    failCount: snap.failCount,
    nextRetryAt: snap.nextRetryAt,
    paneOpen: false,
    expanded: {},
  };
}

export type PollDeps = {
  pollMs: number;
  getSummary: (conversationId: string, etag: string | null) => Promise<GetResult>;
  autoBind: () => Promise<string | null>;
  probeReachable: () => Promise<boolean>;
};

export type PollOut = { snap: Snapshot; status: string | null; toast: string | null };

function failed(snap: Snapshot, now: number, pollMs: number): PollOut {
  const failCount = snap.failCount + 1;
  const next: Snapshot = {
    ...snap,
    offline: true,
    failCount,
    nextRetryAt: now + backoffMs(failCount, pollMs),
  };
  return { snap: next, status: statusText(toCache(next)), toast: null };
}

export async function pollOnce(snap: Snapshot, now: number, deps: PollDeps): Promise<PollOut> {
  if (now < snap.nextRetryAt) return { snap, status: null, toast: null };
  let current = snap;
  let boundId = current.binding;
  if (boundId === null) {
    const picked = await deps.autoBind();
    if (picked === null) {
      const reachable = await deps.probeReachable();
      if (!reachable) return failed(current, now, deps.pollMs);
      // Reachable but no room has a board yet: probe slowly, not every tick.
      const waiting: Snapshot = { ...current, offline: false, failCount: 0, nextRetryAt: now + 30000 };
      return { snap: waiting, status: statusText(toCache(waiting)), toast: null };
    }
    current = {
      ...current,
      binding: picked,
      summary: null,
      summaryEtag: null,
      offline: false,
      baselined: false,
      seenAttention: [],
      failCount: 0,
      nextRetryAt: 0,
    };
    boundId = picked;
  }
  const res = await deps.getSummary(boundId as string, current.summaryEtag);
  if (res.kind === "not-modified") return { snap: current, status: null, toast: null };
  if (res.kind === "failed") return failed(current, now, deps.pollMs);
  const summary = normalizeSummary(res.json);
  if (summary === null) return failed(current, now, deps.pollMs);
  const toastPlan = planToast(toCache(current), summary, []);
  const keys = summary.attention.filter((a) => a.kind === "operator").map(attentionKey);
  const next: Snapshot = {
    ...current,
    summary,
    summaryEtag: res.kind === "ok" ? (res.etag ?? current.summaryEtag) : current.summaryEtag,
    offline: false,
    baselined: true,
    seenAttention: keys,
    failCount: 0,
    nextRetryAt: 0,
  };
  return {
    snap: next,
    status: statusText(toCache(next)),
    toast: toastPlan === null ? null : toastPlan.text,
  };
}

// ---------------------------------------------------------------------------
// Auto-bind: the newest room (by updated_at) that has board modules, probing
// at most 8 rooms. Never creates or modifies rooms.
// ---------------------------------------------------------------------------

export type BoardProbe = {
  listRooms: () => Promise<RoomEntry[] | null>;
  readSummary: (conversationId: string) => Promise<XmuseSummary | null>;
};

export async function autoBindRoom(probe: BoardProbe): Promise<string | null> {
  const rooms = await probe.listRooms();
  if (rooms === null) return null;
  for (const room of sortRoomsByUpdated(rooms).slice(0, 8)) {
    const summary = await probe.readSummary(room.conversation_id);
    if (summary !== null && summary.modules_total > 0) return room.conversation_id;
  }
  return null;
}

// ---------------------------------------------------------------------------
// /xmuse command runner. Local code only; every result is a toast built from
// structured fields only.
// ---------------------------------------------------------------------------

export type CommandDeps = {
  snapshot: () => Snapshot;
  listRooms: () => Promise<RoomEntry[] | null>;
  setBinding: (id: string | null) => void | Promise<void>;
};

export async function runCommand(rawArgs: string, deps: CommandDeps): Promise<string> {
  const args = rawArgs.replace(/^\s*\/?xmuse\b\s?/, "").trim();
  const first = args.split(/\s+/)[0] ?? "";
  if (first === "" || first === "status") return statusBlock(toCache(deps.snapshot()));
  if (first === "attach") {
    const rooms = await deps.listRooms();
    if (rooms === null) return "xmuse 绑定失败: 后端不可达";
    const pick = pickAttachTarget(rooms, args);
    if (!pick.ok) return pick.error;
    await deps.setBinding(pick.conversation_id);
    return "xmuse 已绑定 " + shortRoom(pick.conversation_id);
  }
  if (first === "detach") {
    await deps.setBinding(null);
    return "xmuse 已解绑";
  }
  return "xmuse 用法: /xmuse [attach|detach|status]";
}

// ---------------------------------------------------------------------------
// Bridge to the real TUI context. Structural types only: this file never
// imports the plugin SDK, so bun tests load it without OpenCode.
// ---------------------------------------------------------------------------

export interface TuiContext {
  readonly location: { readonly directory: string } | undefined;
  readonly storage: {
    store<V extends object>(
      key: string,
      options: { readonly initial: V },
    ): readonly [V, (mutation: (draft: V) => void) => void | Promise<void>];
  };
  readonly ui: {
    readonly slot: (claim: {
      readonly append: string;
      readonly render: () => unknown;
    }) => () => void;
    readonly toast: { readonly show: (options: { readonly message: string }) => void };
  };
}

export type BoardHost = {
  readonly baseError: string | null;
  readonly initialStatus: string;
  tick: (now: number) => Promise<void>;
  command: (args: string | undefined) => Promise<string>;
};

export function createBoardHost(
  ctx: TuiContext,
  opts?: {
    env?: Record<string, string | undefined>;
    pollMs?: number;
    fetchImpl?: FetchImpl;
    onStatus?: (text: string) => void;
  },
): BoardHost {
  const pollMs = opts?.pollMs ?? POLL_MS;
  const doFetch = opts?.fetchImpl ?? defaultFetch;
  const onStatus = opts?.onStatus ?? (() => {});
  const directory = ctx.location?.directory ?? null;
  const resolved = resolveBaseUrl(opts?.env ?? {});
  const [bindings, updateBindings] = ctx.storage.store<BindingsState>(BINDINGS_STORE, {
    initial: {},
  });

  if (!resolved.ok) {
    ctx.ui.toast.show({ message: resolved.error });
    return {
      baseError: resolved.error,
      initialStatus: resolved.error,
      tick: async () => {},
      command: async () => resolved.error,
    };
  }

  const baseUrl = resolved.baseUrl;
  let snap: Snapshot = initialSnapshot(readBinding(bindings, directory));

  const getSummary = (id: string, etag: string | null): Promise<GetResult> =>
    httpGet(baseUrl, summaryPath(id), etag, doFetch);
  const listRooms = async (): Promise<RoomEntry[] | null> => {
    const res = await httpGet(baseUrl, "/api/chat/rooms", null, doFetch);
    if (res.kind !== "ok") return null;
    return normalizeRooms(res.json);
  };
  const readSummary = async (id: string): Promise<XmuseSummary | null> => {
    const res = await httpGet(baseUrl, summaryPath(id), null, doFetch);
    if (res.kind !== "ok") return null;
    return normalizeSummary(res.json);
  };

  return {
    baseError: null,
    initialStatus: statusText(toCache(snap)),
    tick: async (now: number) => {
      const before = snap.binding;
      const out = await pollOnce(snap, now, {
        pollMs,
        getSummary,
        autoBind: () => autoBindRoom({ listRooms, readSummary }),
        probeReachable: async () => (await listRooms()) !== null,
      });
      snap = out.snap;
      if (snap.binding !== before && snap.binding !== null) {
        await writeBinding(updateBindings as BindingUpdate, directory, snap.binding);
      }
      if (out.status !== null) onStatus(out.status);
      if (out.toast !== null) ctx.ui.toast.show({ message: out.toast });
    },
    command: async (args: string | undefined) =>
      runCommand(args ?? "", {
        snapshot: () => snap,
        listRooms,
        setBinding: async (id: string | null) => {
          await writeBinding(updateBindings as BindingUpdate, directory, id);
          snap = initialSnapshot(id);
          onStatus(statusText(toCache(snap)));
        },
      }),
  };
}
