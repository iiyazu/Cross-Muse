"use client";

import { useEffect } from "react";

import { LEGACY_LOCAL_STATE_KEYS, LOCAL_STATE_KEY, type ThemePreference } from "@/store/room-persistence";
import { useRoomStore } from "@/store/room-store";

const STATE_KEYS = JSON.stringify([LOCAL_STATE_KEY, ...LEGACY_LOCAL_STATE_KEYS]);

/**
 * Runs inline in <head> so the first paint already has the right theme. It only reads the
 * persisted preference; any failure falls back to the system scheme.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var k=${STATE_KEYS},t="system";for(var i=0;i<k.length;i++){var r=localStorage.getItem(k[i]);if(r){var p=JSON.parse(r).theme;if(p==="dark"||p==="light")t=p;break}}if(t==="system")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}})();`;

export function resolveTheme(preference: ThemePreference, systemDark: boolean): "dark" | "light" {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

/** Keeps `<html data-theme>` in step with the stored preference and the system scheme. */
export function ThemeSync() {
  const preference = useRoomStore((state) => state.theme);

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = resolveTheme(preference, query.matches);
    };
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, [preference]);

  return null;
}
