import { beforeEach, describe, expect, it } from "vitest";

import {
  LOCAL_STATE_KEY,
  persistRoomDraft,
  persistRoomUiState,
  readRoomDraft,
  readRoomUiState
} from "./room-persistence";

describe("room UI persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("falls back safely for absent or malformed local state", () => {
    expect(readRoomUiState(null)).toEqual({
      readCursors: {},
      scrollAnchors: {},
      theme: "dark",
      sidebarOpen: true,
      inspectorOpen: false,
      dockTab: "room",
      pinnedRoomIds: [],
      selectedParticipants: {},
      onboardingVersion: 1,
      onboardingCompleted: false,
      onboardingDismissed: false
    });
    localStorage.setItem(LOCAL_STATE_KEY, "not-json");
    expect(readRoomUiState(localStorage).readCursors).toEqual({});
  });

  it("keeps only the fifty rooms with the greatest read cursor and aligned anchors", () => {
    const readCursors = Object.fromEntries(Array.from({ length: 55 }, (_, index) => [`room-${index}`, index]));
    const scrollAnchors = Object.fromEntries(Array.from({ length: 55 }, (_, index) => [
      `room-${index}`,
      { messageId: `message-${index}`, offset: index }
    ]));

    persistRoomUiState(localStorage, {
      readCursors,
      scrollAnchors,
      theme: "light",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "room",
      pinnedRoomIds: ["room-54"],
      selectedParticipants: { "room-54": "participant-1" },
      onboardingVersion: 1,
      onboardingCompleted: false,
      onboardingDismissed: false
    });

    const raw = JSON.parse(localStorage.getItem(LOCAL_STATE_KEY) ?? "{}");
    expect(Object.keys(raw.readCursors)).toHaveLength(50);
    expect(Object.keys(raw.scrollAnchors)).toHaveLength(50);
    expect(raw.readCursors).not.toHaveProperty("room-0");
    expect(raw.readCursors).not.toHaveProperty("room-4");
    expect(raw.readCursors).toHaveProperty("room-54", 54);
    expect(readRoomUiState(localStorage)).toMatchObject({
      theme: "light",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "room",
    });
  });

  it("persists drafts per room in session storage and removes empty drafts", () => {
    persistRoomDraft(sessionStorage, "conv-1", "unfinished");
    expect(readRoomDraft(sessionStorage, "conv-1")).toBe("unfinished");
    expect(localStorage.getItem("xmuse.room-draft/v1:conv-1")).toBeNull();

    persistRoomDraft(sessionStorage, "conv-1", "");
    expect(readRoomDraft(sessionStorage, "conv-1")).toBe("");
  });

  it("migrates v2 UI state without treating runtime capability as local authority", () => {
    localStorage.setItem("xmuse.room-ui/v2", JSON.stringify({
      theme: "light",
      dockOpen: true,
      dockTab: "runtime",
      selectedParticipants: { "conv-1": "participant-1" },
      runtime: { state: "ready" }
    }));

    expect(readRoomUiState(localStorage)).toMatchObject({
      theme: "light",
      inspectorOpen: true,
      dockTab: "runtime",
      selectedParticipants: { "conv-1": "participant-1" },
      onboardingCompleted: false,
      onboardingDismissed: false
    });
    expect(readRoomUiState(localStorage)).not.toHaveProperty("runtime");
  });
});
