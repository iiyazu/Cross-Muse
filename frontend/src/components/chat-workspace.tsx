"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { useRoomStore } from "@/store/room-store";
import { RoomWorkspace } from "./room-workspace";

function roomIdFrom(pathname: string): string | null {
  const match = pathname.match(/^\/rooms\/([^/]+)\/?$/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export function ChatWorkspace() {
  const pathname = usePathname();
  const router = useRouter();
  const bootstrapped = useRef(false);
  const selectedRoomId = useRoomStore((state) => state.selectedRoomId);
  const bootstrap = useRoomStore((state) => state.bootstrap);
  const selectRoom = useRoomStore((state) => state.selectRoom);
  const stopSync = useRoomStore((state) => state.stopSync);
  const routeRoomId = roomIdFrom(pathname);

  useEffect(() => {
    let active = true;
    void bootstrap(routeRoomId).then((selected) => {
      if (!active) return;
      bootstrapped.current = true;
      if (!routeRoomId && selected) router.replace(`/rooms/${encodeURIComponent(selected)}`);
    });
    return () => {
      active = false;
      stopSync();
    };
    // The shared shell bootstraps once; path changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!bootstrapped.current || !routeRoomId || routeRoomId === selectedRoomId) return;
    void selectRoom(routeRoomId);
  }, [routeRoomId, selectRoom, selectedRoomId]);

  return (
    <RoomWorkspace
      onCreatedRoom={(roomId) => router.push(`/rooms/${encodeURIComponent(roomId)}`)}
      onNavigateRoom={(roomId) => router.push(`/rooms/${encodeURIComponent(roomId)}`)}
    />
  );
}
