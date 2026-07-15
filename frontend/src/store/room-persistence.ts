export const MAX_LOCAL_ROOMS = 50;
export const LOCAL_STATE_KEY = "xmuse.room-ui/v2";
export const LEGACY_LOCAL_STATE_KEY = "xmuse.room-ui/v1";
export const DRAFT_KEY_PREFIX = "xmuse.room-draft/v1:";

export type WorkspaceDockTab = "agent" | "room" | "runtime";

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
  dockTab: WorkspaceDockTab;
  pinnedRoomIds: string[];
  selectedParticipants: Record<string, string>;
};

export function defaultRoomUiState(): PersistedRoomUiState {
  return {
    readCursors: {},
    scrollAnchors: {},
    theme: "dark",
    sidebarOpen: true,
    inspectorOpen: false,
    dockTab: "room",
    pinnedRoomIds: [],
    selectedParticipants: {}
  };
}

export function readRoomUiState(storage: Storage | null): PersistedRoomUiState {
  const fallback = defaultRoomUiState();
  if (!storage) return fallback;
  try {
    const parsed = JSON.parse(
      storage.getItem(LOCAL_STATE_KEY) ?? storage.getItem(LEGACY_LOCAL_STATE_KEY) ?? "{}"
    ) as Record<string, unknown>;
    const dockTab = ["agent", "room", "runtime"].includes(String(parsed.dockTab))
      ? parsed.dockTab as WorkspaceDockTab
      : parsed.inspectorOpen === true ? "room" : "agent";
    return {
      readCursors: parsed.readCursors && typeof parsed.readCursors === "object"
        ? parsed.readCursors as Record<string, number>
        : {},
      scrollAnchors: parsed.scrollAnchors && typeof parsed.scrollAnchors === "object"
        ? parsed.scrollAnchors as Record<string, ScrollAnchor>
        : {},
      theme: parsed.theme === "light" ? "light" : "dark",
      sidebarOpen: parsed.sidebarOpen !== false,
      inspectorOpen: parsed.dockOpen === true || parsed.inspectorOpen === true,
      dockTab,
      pinnedRoomIds: Array.isArray(parsed.pinnedRoomIds)
        ? parsed.pinnedRoomIds.filter((value): value is string => typeof value === "string").slice(0, MAX_LOCAL_ROOMS)
        : [],
      selectedParticipants: parsed.selectedParticipants && typeof parsed.selectedParticipants === "object"
        ? Object.fromEntries(
            Object.entries(parsed.selectedParticipants as Record<string, unknown>)
              .filter((entry): entry is [string, string] => typeof entry[1] === "string")
              .slice(0, MAX_LOCAL_ROOMS)
          )
        : {}
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
  const pinned = state.pinnedRoomIds.slice(0, maximum);
  const recentIds = Object.keys(state.readCursors)
    .sort((left, right) => (state.readCursors[right] ?? 0) - (state.readCursors[left] ?? 0))
    .filter((id) => !pinned.includes(id))
    .slice(0, Math.max(0, maximum - pinned.length));
  const retainedIds = [...pinned, ...recentIds];
  const readCursors = Object.fromEntries(retainedIds.flatMap((id) =>
    state.readCursors[id] === undefined ? [] : [[id, state.readCursors[id]]]
  ));
  const scrollAnchors = Object.fromEntries(
    retainedIds.flatMap((id) => state.scrollAnchors[id] ? [[id, state.scrollAnchors[id]]] : [])
  );
  const selectedParticipants = Object.fromEntries(
    retainedIds.flatMap((id) => state.selectedParticipants[id]
      ? [[id, state.selectedParticipants[id]]]
      : [])
  );
  storage.setItem(LOCAL_STATE_KEY, JSON.stringify({
    version: 2,
    readCursors,
    scrollAnchors,
    theme: state.theme,
    sidebarOpen: state.sidebarOpen,
    dockOpen: state.inspectorOpen,
    dockTab: state.dockTab,
    pinnedRoomIds: pinned,
    selectedParticipants
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
