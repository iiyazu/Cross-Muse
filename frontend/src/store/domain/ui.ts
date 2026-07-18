import type { ScrollAnchor, WorkspaceDockTab } from "@/store/room-persistence";

import type { DomainCapability } from "./shared";

export type UiDomainState = {
  drafts: Record<string, string>;
  readCursors: Record<string, number>;
  scrollAnchors: Record<string, ScrollAnchor>;
  theme: "dark" | "light";
  sidebarOpen: boolean;
  inspectorOpen: boolean;
  dockTab: WorkspaceDockTab;
  pinnedRoomIds: string[];
  selectedParticipants: Record<string, string>;
  onboardingVersion: number;
  onboardingCompleted: boolean;
  onboardingDismissed: boolean;
};

export type UiDomainActions = {
  setDraft: (roomId: string, draft: string) => void;
  markRead: (roomId: string, roomSeq: number) => void;
  saveScrollAnchor: (roomId: string, anchor: ScrollAnchor | null) => void;
  setTheme: (theme: "dark" | "light") => void;
  setSidebarOpen: (open: boolean) => void;
  setInspectorOpen: (open: boolean) => void;
  setDockTab: (tab: WorkspaceDockTab) => void;
  togglePinnedRoom: (roomId: string) => void;
  completeOnboarding: () => void;
  dismissOnboarding: () => void;
};

export type UiDomain = UiDomainState & UiDomainActions;
export type UiReadCapability = DomainCapability<UiDomain, keyof UiDomainState>;
export type UiWriteCapability = DomainCapability<UiDomain, keyof UiDomainActions>;

export function createDraftSelector(roomId: string): (state: UiDomainState) => string {
  return (state) => state.drafts[roomId] ?? "";
}
export function createReadCursorSelector(roomId: string): (state: UiDomainState) => number {
  return (state) => state.readCursors[roomId] ?? 0;
}
