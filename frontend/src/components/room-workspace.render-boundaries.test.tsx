import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { normalizeRoomProjection } from "@/lib/room-view";
import type { RoomAgentStream, RoomTimelineItem } from "@/lib/types";
import { useRoomStore, type RoomCache } from "@/store/room-store";

const renders = vi.hoisted(() => ({
  composer: 0,
  dock: 0,
  message: 0,
  preview: 0,
  sidebar: 0
}));

vi.mock("./room-composer", () => ({
  RoomComposer: ({ draft }: { draft: string }) => {
    renders.composer += 1;
    return <textarea aria-label="composer render probe" value={draft} readOnly />;
  }
}));

vi.mock("./room-message", () => ({
  RoomMessage: ({ item }: { item: { id: string } }) => {
    renders.message += 1;
    return <article data-message-id={item.id} />;
  },
  RoomPendingBubble: () => null
}));

vi.mock("./room-agent-preview", () => ({
  RoomAgentPreview: () => {
    renders.preview += 1;
    return <div data-testid="stream-preview" />;
  }
}));

vi.mock("./room-workspace-sidebar", () => ({
  WorkspaceSidebar: () => {
    renders.sidebar += 1;
    return <aside />;
  }
}));

vi.mock("./room-header", () => ({
  formatRoomTime: () => "date",
  identityStyle: () => ({}),
  initials: () => "A",
  RoomHeader: () => <header />
}));

vi.mock("./room-turn-status", () => ({ RoomTurnStatus: () => null }));
vi.mock("./room-inspector", () => ({
  RoomInspector: ({ activeTab }: { activeTab: "agent" | "room" | "runtime" }) => {
    renders.dock += 1;
    return <aside aria-label={`dock-${activeTab}`} />;
  }
}));
vi.mock("./agent-console", () => ({ AgentConsole: () => null }));
vi.mock("./command-palette", () => ({ CommandPalette: () => null }));
vi.mock("./room-evidence-domain", () => ({ RoomEvidenceDomain: () => null }));
vi.mock("./room-execution-domain", () => ({ RoomExecutionDomain: () => null }));
vi.mock("./room-memory-domain", () => ({ RoomMemoryDomain: () => null }));
vi.mock("./room-runtime-domain", () => ({
  RoomMemoryRebuildDialog: () => null,
  RoomRuntimeDomain: () => null,
  RoomRuntimeRecoverDialog: () => null
}));
vi.mock("./workspace-status-region", () => ({
  useBrowserOnline: () => true,
  WorkspaceStatusRegion: () => null
}));

import { RoomWorkspace } from "./room-workspace";

const ROOM_ID = "room-1";

function timelineItems(count: number): RoomTimelineItem[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `activity-${index + 1}`,
    kind: "message",
    room_seq: index + 1,
    activity_id: `activity-${index + 1}`,
    message_id: `message-${index + 1}`,
    created_at: "2026-07-17T09:00:00Z",
    actor: { kind: "human", role: "human", display_name: "You" },
    content: `message ${index + 1}`
  })) as RoomTimelineItem[];
}

function cache(
  roomId: string,
  items: RoomTimelineItem[] = [],
  streams: RoomAgentStream[] = []
): RoomCache {
  return {
    projection: normalizeRoomProjection({
      schema_version: "room_chat_projection/v3",
      event_cursor: items.length,
      conversation: { id: roomId, title: roomId },
      status: "settled",
      active_turn_count: 0,
      participants: [],
      turns: [],
      timeline_items: items,
      page: { has_older: false, has_newer: false }
    }, roomId),
    timelineItems: items,
    pendingMessages: [],
    requestGeneration: 1,
    loading: false,
    loadingOlder: false,
    eventCursor: items.length,
    syncState: "synced",
    consecutiveFailures: 0,
    lastSyncedAt: 1,
    lastAccessedAt: 1,
    error: null,
    controlPending: null,
    controlError: null,
    agentStreams: streams,
    agentStreamAvailable: true,
    agentStreamEpoch: "epoch-1",
    agentStreamSeq: streams.length,
    agentStreamGeneration: 1
  };
}

function operations(overall: "healthy" | "attention" | "blocked" = "attention") {
  return {
    overall,
    actions: {
      recover_runtime: { available: false },
      rebuild_memory_index: { available: false, pending: false }
    }
  } as never;
}

function installFixture() {
  const rooms = Array.from({ length: 8 }, (_, index) => ({
    conversation_id: `room-${index + 1}`,
    title: `Room ${index + 1}`,
    latest_visible_room_seq: index === 0 ? 500 : 0,
    members: [],
    state: "settled" as const,
    active_turn_count: 0,
    attention_turn_count: 0
  }));
  const roomsById = Object.fromEntries(
    rooms.map((room, index) => [
      room.conversation_id,
      cache(room.conversation_id, index === 0 ? timelineItems(500) : [])
    ])
  );
  useRoomStore.setState({
    rooms,
    roomsById,
    selectedRoomId: ROOM_ID,
    roomsLoading: false,
    roomsLoaded: true,
    roomsError: null,
    drafts: { [ROOM_ID]: "draft" },
    sidebarOpen: false,
    inspectorOpen: false,
    operations: null,
    executionsByRoom: {},
    memoryByRoom: {},
    codexByRoom: {}
  });
}

function resetRenderCounts() {
  renders.composer = 0;
  renders.dock = 0;
  renders.message = 0;
  renders.preview = 0;
  renders.sidebar = 0;
}

afterEach(() => {
  resetRenderCounts();
});

describe("RoomWorkspace render boundaries", () => {
  it("keeps a 500-item timeline and composer stable while Runtime, Memory, and another cached Room update", async () => {
    installFixture();
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    await act(async () => {});
    expect(renders.message).toBeGreaterThanOrEqual(500);
    resetRenderCounts();

    act(() => useRoomStore.setState({
      operations: operations(),
      memoryByRoom: { [ROOM_ID]: { loading: true } as never },
      roomsById: {
        ...useRoomStore.getState().roomsById,
        "room-8": cache("room-8", [], [{
          stream_id: "background-stream",
          participant_id: "participant-background",
          observation_id: "observation-background",
          state: "streaming",
          content: "not selected",
          truncated: false,
          started_at: "2026-07-17T09:00:00Z",
          updated_at: "2026-07-17T09:00:01Z"
        }])
      }
    }));

    expect(renders.message).toBe(0);
    expect(renders.composer).toBe(0);
    expect(renders.preview).toBe(0);
  });

  it("isolates a four-Agent preview update from durable messages and the composer", async () => {
    installFixture();
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    await act(async () => {});
    resetRenderCounts();

    const current = useRoomStore.getState().roomsById[ROOM_ID];
    act(() => useRoomStore.setState({
      roomsById: {
        ...useRoomStore.getState().roomsById,
        [ROOM_ID]: {
          ...current,
          agentStreams: ["architect", "builder", "reviewer", "critic"].map((participantId, index) => ({
            stream_id: `stream-${participantId}`,
            participant_id: `participant-${participantId}`,
            observation_id: `observation-${index}`,
            state: "streaming" as const,
            content: `partial ${index}`,
            truncated: false,
            started_at: "2026-07-17T09:00:00Z",
            updated_at: "2026-07-17T09:00:01Z"
          })),
          agentStreamSeq: 4
        }
      }
    }));

    expect(renders.preview).toBe(4);
    expect(renders.message).toBe(0);
    expect(renders.composer).toBe(0);
  });

  it("allows the composer to repaint for its own draft without repainting durable timeline items", async () => {
    installFixture();
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    await act(async () => {});
    resetRenderCounts();

    act(() => useRoomStore.setState({ drafts: { [ROOM_ID]: "draft changed" } }));

    expect(renders.composer).toBe(1);
    expect(renders.message).toBe(0);
    expect(renders.preview).toBe(0);
  });

  it.each([
    {
      activeTab: "agent" as const,
      label: "Agent",
      update: () => ({
        executionsByRoom: { [ROOM_ID]: { loading: true } as never },
        memoryByRoom: { [ROOM_ID]: { loading: true } as never },
        operations: operations()
      })
    },
    {
      activeTab: "room" as const,
      label: "Room",
      update: () => ({
        codexByRoom: { [ROOM_ID]: { loading: true } as never },
        operations: operations()
      })
    },
    {
      activeTab: "runtime" as const,
      label: "Runtime",
      update: () => ({
        codexByRoom: { [ROOM_ID]: { loading: true } as never },
        executionsByRoom: { [ROOM_ID]: { loading: true } as never },
        memoryByRoom: { [ROOM_ID]: { loading: true } as never }
      })
    }
  ])("keeps the selected $label Dock surface stable for non-current domain updates", async ({ activeTab, update }) => {
    installFixture();
    useRoomStore.setState({ inspectorOpen: true, dockTab: activeTab });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    await act(async () => {});
    expect(renders.dock).toBeGreaterThan(0);
    resetRenderCounts();

    act(() => useRoomStore.setState(update()));

    expect(renders.dock).toBe(0);
    expect(renders.message).toBe(0);
    expect(renders.composer).toBe(0);
  });
});
