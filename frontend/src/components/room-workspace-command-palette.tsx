"use client";

import { useMemo } from "react";

import { useRoomStore } from "@/store/room-store";
import { CommandPalette, type CommandPaletteAction } from "./command-palette";

export function WorkspaceCommandPalette({
  onNavigateRoom,
  onNewRoom
}: {
  onNavigateRoom: (roomId: string) => void;
  onNewRoom: () => void;
}) {
  const rooms = useRoomStore((state) => state.rooms);
  const selectedRoomId = useRoomStore((state) => state.selectedRoomId);
  const theme = useRoomStore((state) => state.theme);
  const codexCache = useRoomStore((state) => selectedRoomId ? state.codexByRoom[selectedRoomId] ?? null : null);
  const selectCodexParticipant = useRoomStore((state) => state.selectCodexParticipant);
  const setDockTab = useRoomStore((state) => state.setDockTab);
  const setTheme = useRoomStore((state) => state.setTheme);
  const actions = useMemo<CommandPaletteAction[]>(() => [
    { id: "new-room", label: "新建 Room", detail: "选择 roster 并创建协作空间", run: onNewRoom },
    ...rooms.slice(0, 8).map((room) => ({ id: `room:${room.conversation_id}`, label: room.title, detail: "切换 Room", run: () => onNavigateRoom(room.conversation_id) })),
    ...(codexCache?.projection?.participants ?? []).map((participant) => ({
      id: `agent:${participant.participant.participant_id}`,
      label: participant.participant.display_name,
      detail: "打开单 Agent Codex 工作台",
      run: () => { selectCodexParticipant(participant.participant.participant_id); setDockTab("agent"); }
    })),
    { id: "dock-room", label: "Room 控制面", detail: "执行、记忆与因果证据", run: () => setDockTab("room") },
    { id: "dock-runtime", label: "Runtime 状态", detail: "运行事件与恢复", run: () => setDockTab("runtime") },
    { id: "theme", label: "切换主题", detail: theme === "dark" ? "切换到浅色" : "切换到深色", run: () => setTheme(theme === "dark" ? "light" : "dark") }
  ], [codexCache?.projection?.participants, onNavigateRoom, onNewRoom, rooms, selectCodexParticipant, setDockTab, setTheme, theme]);
  return <CommandPalette actions={actions} />;
}
