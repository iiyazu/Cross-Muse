"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Tooltip } from "radix-ui";
import { PanelLeft, Plus } from "lucide-react";

import { currentPanelLink } from "@/components/board/panel-link";
import { useNeedsYou } from "@/components/board/use-needs-you";
import { WorkPanel } from "@/components/board/work-panel";
import { SystemSheet } from "@/components/system/system-sheet";
import { Button, IconButton } from "@/components/ui/button";
import { Sheet } from "@/components/ui/overlay";
import { useRoomStore } from "@/store/room-store";

import { CreateRoomDialog } from "./create-room-dialog";
import { RoomRail } from "./room-rail";
import { RoomView } from "./room-view";
import { ThemeSync } from "./theme";
import { PANEL_DOCKED_QUERY, RAIL_DOCKED_QUERY, useMediaQuery } from "./use-media-query";

export function roomIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/rooms\/([^/]+)\/?$/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function roomHref(roomId: string): string {
  return `/rooms/${encodeURIComponent(roomId)}`;
}

/**
 * The persistent application shell. It lives in the root layout so the store, its sync loops
 * and the agent preview stream survive navigation between rooms.
 */
export function Workroom() {
  const pathname = usePathname();
  const router = useRouter();
  const routeRoomId = roomIdFromPath(pathname);
  const bootstrappedRef = useRef(false);
  const [bootstrapped, setBootstrapped] = useState(false);

  const selectedRoomId = useRoomStore((state) => state.selectedRoomId);
  const roomsLoaded = useRoomStore((state) => state.roomsLoaded);
  const roomCount = useRoomStore((state) => state.rooms.length);
  const roomsError = useRoomStore((state) => state.roomsError);
  const panelOpen = useRoomStore((state) => state.inspectorOpen);
  const setPanelOpen = useRoomStore((state) => state.setInspectorOpen);
  const bootstrap = useRoomStore((state) => state.bootstrap);
  const selectRoom = useRoomStore((state) => state.selectRoom);
  const stopSync = useRoomStore((state) => state.stopSync);

  const railDocked = useMediaQuery(RAIL_DOCKED_QUERY, true);
  const panelDocked = useMediaQuery(PANEL_DOCKED_QUERY, true);
  const [railSheetOpen, setRailSheetOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [systemOpen, setSystemOpen] = useState(false);
  const needsYou = useNeedsYou(selectedRoomId);

  useEffect(() => {
    let active = true;
    void bootstrap(routeRoomId).then((selected) => {
      if (!active) return;
      bootstrappedRef.current = true;
      setBootstrapped(true);
      if (!routeRoomId && selected) router.replace(roomHref(selected));
      // A deep link names a view inside the work panel, so it arrives with the panel open.
      if (selected && currentPanelLink(selected, window.location.pathname, window.location.search).view) setPanelOpen(true);
    });
    return () => {
      active = false;
      stopSync();
    };
    // The shell bootstraps once; route changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!bootstrappedRef.current || !routeRoomId || routeRoomId === selectedRoomId) return;
    void selectRoom(routeRoomId);
  }, [routeRoomId, selectRoom, selectedRoomId]);

  // The board summary and the decision queue are visible without opening anything, so their
  // first read happens on entering a room rather than when a panel opens.
  useEffect(() => {
    if (!selectedRoomId) return;
    const state = useRoomStore.getState();
    void state.refreshBoard(selectedRoomId);
    void state.refreshExecutions(selectedRoomId);
    void state.refreshMemory(selectedRoomId);
  }, [selectedRoomId]);

  // The board sync loop only polls fast once a board is loaded; until the first read lands
  // (an aborted or failed request), retry it here with backoff so the glance layer appears.
  const boardLoaded = useRoomStore((state) => {
    const cache = selectedRoomId ? state.boardByRoom[selectedRoomId] : undefined;
    return Boolean(cache?.projection || cache?.summary);
  });
  useEffect(() => {
    if (!selectedRoomId || boardLoaded) return;
    let cancelled = false;
    let timer = 0;
    let attempt = 0;
    const schedule = () => {
      timer = window.setTimeout(async () => {
        if (cancelled) return;
        // refreshBoard joins a request already in flight, so this never doubles traffic.
        await useRoomStore.getState().refreshBoard(selectedRoomId);
        attempt += 1;
        if (!cancelled) schedule();
      }, Math.min(15_000, 1_000 * 2 ** Math.min(attempt, 4)));
    };
    schedule();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selectedRoomId, boardLoaded]);

  useEffect(() => {
    const onFocus = () => {
      const state = useRoomStore.getState();
      void state.loadRooms();
      if (state.selectedRoomId) {
        void state.refreshBoard(state.selectedRoomId);
        void state.refreshExecutions(state.selectedRoomId);
        void state.refreshMemory(state.selectedRoomId);
      }
    };
    const onVisibility = () => {
      const state = useRoomStore.getState();
      state.startOperationsSync();
      state.startExecutionSync();
      state.startMemorySync();
      state.startBoardSync();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const navigate = useCallback((roomId: string) => {
    setRailSheetOpen(false);
    router.push(roomHref(roomId));
  }, [router]);

  const rail = <RoomRail onCreate={() => { setRailSheetOpen(false); setCreateOpen(true); }} onNavigate={navigate} />;
  const panel = selectedRoomId ? (
    <WorkPanel
      docked={panelDocked}
      key={selectedRoomId}
      onClose={() => setPanelOpen(false)}
      onOpenSystem={() => setSystemOpen(true)}
      roomId={selectedRoomId}
    />
  ) : null;

  return (
    <Tooltip.Provider delayDuration={300}>
      <ThemeSync />
      <div className="flex h-dvh overflow-hidden bg-canvas text-fg">
        {railDocked ? (
          <aside className="w-64 shrink-0 border-r border-line">{rail}</aside>
        ) : (
          <Sheet onOpenChange={setRailSheetOpen} open={railSheetOpen} side="left" title="房间列表" widthClass="w-[min(86vw,18rem)]">
            {rail}
          </Sheet>
        )}
        <main className="flex min-w-0 flex-1 flex-col">
          {selectedRoomId ? (
            <RoomView
              attentionCount={needsYou.total}
              onOpenPanel={() => setPanelOpen(true)}
              onOpenRail={() => setRailSheetOpen(true)}
              onOpenSystem={() => setSystemOpen(true)}
              onTogglePanel={() => setPanelOpen(!panelOpen)}
              panelOpen={panelOpen}
              railDocked={railDocked}
              roomId={selectedRoomId}
            />
          ) : (
            <>
            {!railDocked ? (
              <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-2">
                <IconButton label="打开房间列表" onClick={() => setRailSheetOpen(true)} size="sm">
                  <PanelLeft aria-hidden="true" className="size-4" />
                </IconButton>
                <span className="text-sm font-semibold tracking-tight text-fg">xmuse</span>
              </header>
            ) : null}
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 text-center">
              {bootstrapped && roomsLoaded && roomCount === 0 ? (
                <div className="max-w-sm">
                  <p className="m-0 text-lg font-semibold text-fg">建一个房间，开始第一次协作</p>
                  <p className="m-0 mt-2 text-ui text-fg-3">
                    把来自不同厂商的 Agent 放进同一个房间。它们各自负责模块，宿主负责验证，只有验证通过的才算完成。
                  </p>
                  <Button className="mt-5" onClick={() => setCreateOpen(true)} variant="primary">
                    <Plus aria-hidden="true" className="size-4" /> 新建房间
                  </Button>
                </div>
              ) : roomsError && roomCount === 0 ? (
                <div className="max-w-sm" role="alert">
                  <p className="m-0 text-base font-semibold text-fg">连不上 xmuse</p>
                  <p className="m-0 mt-2 text-ui text-fg-3">
                    本机的 Chat API 没有响应。用 <code className="font-mono text-fg-2">xmuse-workroom status</code> 看看它是否在运行，页面会自动重试。
                  </p>
                </div>
              ) : (
                <p className="m-0 text-ui text-fg-3" role="status">正在连接 xmuse…</p>
              )}
            </div>
            </>
          )}
        </main>
        {panel && panelDocked && panelOpen ? (
          <aside aria-label="工作面板" className="w-[26rem] shrink-0 border-l border-line">{panel}</aside>
        ) : null}
        {panel && !panelDocked ? (
          <Sheet onOpenChange={setPanelOpen} open={panelOpen} title="工作面板" widthClass="w-[min(100vw,28rem)]">
            {panel}
          </Sheet>
        ) : null}
      </div>
      <CreateRoomDialog onCreated={(roomId) => router.push(roomHref(roomId))} onOpenChange={setCreateOpen} open={createOpen} />
      <SystemSheet onOpenChange={setSystemOpen} open={systemOpen} />
    </Tooltip.Provider>
  );
}
