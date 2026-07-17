"use client";

import { useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { useRoomStore } from "@/store/room-store";
import { RoomSidebar } from "./room-sidebar";

type WorkspaceSidebarProps = {
  creating: boolean;
  onCreatingChange: (creating: boolean) => void;
  onCreatedRoom: (roomId: string) => void;
  onNavigateRoom: (roomId: string) => void;
  onRequestCloseMobile: () => void;
};

/**
 * Keeps room-list and creation changes outside the workspace shell. In particular,
 * typing a new title or receiving a list refresh must not re-render the timeline.
 */
export function WorkspaceSidebar({
  creating,
  onCreatingChange,
  onCreatedRoom,
  onNavigateRoom,
  onRequestCloseMobile
}: WorkspaceSidebarProps) {
  const store = useRoomStore(useShallow((state) => ({
    rooms: state.rooms,
    selectedRoomId: state.selectedRoomId,
    roomsLoading: state.roomsLoading,
    roomsLoaded: state.roomsLoaded,
    roomsError: state.roomsError,
    roomCreatePending: state.roomCreatePending,
    roomCreateError: state.roomCreateError,
    drafts: state.drafts,
    readCursors: state.readCursors,
    pinnedRoomIds: state.pinnedRoomIds,
    createRoom: state.createRoom,
    togglePinnedRoom: state.togglePinnedRoom
  })));
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [createRequestId, setCreateRequestId] = useState<string | null>(null);

  return (
    <RoomSidebar
      createError={store.roomCreateError}
      createPending={store.roomCreatePending}
      createRequestId={createRequestId}
      creating={creating}
      drafts={store.drafts}
      error={store.roomsError}
      loaded={store.roomsLoaded}
      loading={store.roomsLoading}
      onClose={onRequestCloseMobile}
      onCreate={async (name, clientRequestId, rosterTemplateId) => {
        setCreateRequestId(clientRequestId);
        const id = await store.createRoom(name, clientRequestId, rosterTemplateId);
        if (id) {
          setTitle("");
          setCreateRequestId(null);
          onCreatingChange(false);
          onCreatedRoom(id);
        }
        return Boolean(id);
      }}
      onCreatingChange={onCreatingChange}
      onNavigate={(roomId) => {
        onRequestCloseMobile();
        onNavigateRoom(roomId);
      }}
      onQueryChange={setQuery}
      onTitleChange={(value) => {
        setTitle(value);
        setCreateRequestId(null);
      }}
      onTogglePinned={store.togglePinnedRoom}
      pinnedRoomIds={store.pinnedRoomIds}
      query={query}
      readCursors={store.readCursors}
      rooms={store.rooms}
      selectedRoomId={store.selectedRoomId}
      title={title}
    />
  );
}
