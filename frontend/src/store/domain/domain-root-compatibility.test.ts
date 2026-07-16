import { describe, expect, it } from "vitest";

import type { useRoomStore } from "../room-store";
import type { RoomStoreRoot } from "./index";

type CurrentRoomStoreState = ReturnType<typeof useRoomStore.getState>;
type AssertRootImplementsDomains<T extends RoomStoreRoot> = T;

// TypeScript fails this module if a domain contract drifts from the composed root store.
type CheckedRoomStoreState = AssertRootImplementsDomains<CurrentRoomStoreState>;

describe("room store domain composition", () => {
  it("keeps the current root structurally compatible with the domain contracts", () => {
    expect(true).toBe(true);
  });
});

export type { CheckedRoomStoreState };
