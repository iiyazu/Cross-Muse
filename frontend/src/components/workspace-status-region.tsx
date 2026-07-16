"use client";

import { useSyncExternalStore } from "react";

export function useBrowserOnline() {
  return useSyncExternalStore((notify) => {
    window.addEventListener("online", notify);
    window.addEventListener("offline", notify);
    return () => {
      window.removeEventListener("online", notify);
      window.removeEventListener("offline", notify);
    };
  }, () => navigator.onLine, () => true);
}

export function WorkspaceStatusRegion({ message }: { message: string | null }) {
  if (!message) return <div aria-live="polite" className="workspace-status-region" role="status" />;
  return (
    <div aria-live="polite" className="workspace-status-region has-message" role="status">
      {message}
    </div>
  );
}
