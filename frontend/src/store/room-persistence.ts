export const MAX_LOCAL_ROOMS = 50;
export const LOCAL_STATE_KEY = "xmuse.room-ui/v1";
export const DRAFT_KEY_PREFIX = "xmuse.room-draft/v1:";

export type ScrollAnchor = {
  messageId: string;
  offset: number;
};

export type PersistedRoomUiState = {
  readCursors: Record<string, number>;
  scrollAnchors: Record<string, ScrollAnchor>;
  theme: "dark" | "light";
  sidebarOpen: boolean;
  inspectorOpen: boolean;
};

export function defaultRoomUiState(): PersistedRoomUiState {
  return {
    readCursors: {},
    scrollAnchors: {},
    theme: "dark",
    sidebarOpen: true,
    inspectorOpen: false
  };
}

export function readRoomUiState(storage: Storage | null): PersistedRoomUiState {
  const fallback = defaultRoomUiState();
  if (!storage) return fallback;
  try {
    const parsed = JSON.parse(storage.getItem(LOCAL_STATE_KEY) ?? "{}") as Record<string, unknown>;
    return {
      readCursors: parsed.readCursors && typeof parsed.readCursors === "object"
        ? parsed.readCursors as Record<string, number>
        : {},
      scrollAnchors: parsed.scrollAnchors && typeof parsed.scrollAnchors === "object"
        ? parsed.scrollAnchors as Record<string, ScrollAnchor>
        : {},
      theme: parsed.theme === "light" ? "light" : "dark",
      sidebarOpen: parsed.sidebarOpen !== false,
      inspectorOpen: parsed.inspectorOpen === true
    };
  } catch {
    return fallback;
  }
}

export function persistRoomUiState(
  storage: Storage | null,
  state: PersistedRoomUiState,
  maximum = MAX_LOCAL_ROOMS
): void {
  if (!storage) return;
  const recentIds = Object.keys(state.readCursors)
    .sort((left, right) => (state.readCursors[right] ?? 0) - (state.readCursors[left] ?? 0))
    .slice(0, maximum);
  const readCursors = Object.fromEntries(recentIds.map((id) => [id, state.readCursors[id]]));
  const scrollAnchors = Object.fromEntries(
    recentIds.flatMap((id) => state.scrollAnchors[id] ? [[id, state.scrollAnchors[id]]] : [])
  );
  storage.setItem(LOCAL_STATE_KEY, JSON.stringify({
    version: 1,
    readCursors,
    scrollAnchors,
    theme: state.theme,
    sidebarOpen: state.sidebarOpen,
    inspectorOpen: state.inspectorOpen
  }));
}

export function readRoomDraft(storage: Storage | null, roomId: string): string {
  return storage?.getItem(`${DRAFT_KEY_PREFIX}${roomId}`) ?? "";
}

export function persistRoomDraft(
  storage: Storage | null,
  roomId: string,
  draft: string
): void {
  if (!storage) return;
  const key = `${DRAFT_KEY_PREFIX}${roomId}`;
  if (draft) storage.setItem(key, draft);
  else storage.removeItem(key);
}
