import type { StoreApi } from "zustand";

import type { RoomStoreRoot, UiDomainActions } from "@/store/domain";

type UiActionFactoryDependencies = {
  get: StoreApi<RoomStoreRoot>["getState"];
  set: StoreApi<RoomStoreRoot>["setState"];
  persistDraft: (roomId: string, draft: string) => void;
  persistUiState: (state: RoomStoreRoot) => void;
};

/**
 * Browser-only UI transitions are kept separate from Room/network actions.
 * They still receive the composed root store because opening a dock tab can
 * safely request its existing read model without creating a second store.
 */
export function createUiDomainActions({
  get,
  set,
  persistDraft,
  persistUiState
}: UiActionFactoryDependencies): UiDomainActions {
  return {
    setDraft(roomId, draft) {
      set((state) => ({ drafts: { ...state.drafts, [roomId]: draft } }));
      persistDraft(roomId, draft);
    },

    markRead(roomId, nextSeq) {
      if (nextSeq <= (get().readCursors[roomId] ?? 0)) return;
      set((state) => ({
        readCursors: {
          ...state.readCursors,
          [roomId]: Math.max(state.readCursors[roomId] ?? 0, nextSeq)
        }
      }));
      persistUiState(get());
    },

    saveScrollAnchor(roomId, anchor) {
      set((state) => {
        const scrollAnchors = { ...state.scrollAnchors };
        if (anchor) scrollAnchors[roomId] = anchor;
        else delete scrollAnchors[roomId];
        return { scrollAnchors };
      });
      persistUiState(get());
    },

    setTheme(theme) {
      set({ theme });
      persistUiState(get());
    },

    setSidebarOpen(open) {
      set({ sidebarOpen: open });
      persistUiState(get());
    },

    setInspectorOpen(open) {
      set({ inspectorOpen: open });
      persistUiState(get());
      if (open) {
        void get().refreshOperations();
        void get().refreshExecutions();
        void get().refreshMemory();
        void get().refreshCodexAgents();
      }
      get().startOperationsSync();
      get().startExecutionSync();
      get().startMemorySync();
      get().startCodexSync();
    },

    setDockTab(tab) {
      set({ dockTab: tab, inspectorOpen: true });
      persistUiState(get());
      if (tab === "agent") void get().refreshCodexAgents();
      if (tab === "room") {
        void get().refreshExecutions();
        void get().refreshMemory();
      }
      if (tab === "runtime") void get().refreshOperations();
      get().startOperationsSync();
      get().startExecutionSync();
      get().startMemorySync();
      get().startCodexSync();
    },

    togglePinnedRoom(roomId) {
      set((state) => ({
        pinnedRoomIds: state.pinnedRoomIds.includes(roomId)
          ? state.pinnedRoomIds.filter((id) => id !== roomId)
          : [roomId, ...state.pinnedRoomIds].slice(0, 50)
      }));
      persistUiState(get());
    },

    completeOnboarding() {
      set({ onboardingCompleted: true, onboardingDismissed: false });
      persistUiState(get());
    },

    dismissOnboarding() {
      set({ onboardingDismissed: true });
      persistUiState(get());
    }
  };
}
