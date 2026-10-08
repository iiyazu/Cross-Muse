"use client";

import { useSyncExternalStore } from "react";

/** Width breakpoints of the side-window-first layout (see frontend-design-1006 §2.3). */
export const RAIL_DOCKED_QUERY = "(min-width: 1024px)";
export const PANEL_DOCKED_QUERY = "(min-width: 1280px)";

export function useMediaQuery(query: string, serverValue = false): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => serverValue
  );
}
