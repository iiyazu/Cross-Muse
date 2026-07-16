"use client";

import {
  Fragment,
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode
} from "react";
import { useShallow } from "zustand/react/shallow";

import {
  roomAgentWorkStateLabel,
  roomParticipantStateLabel,
  roomStateLabel
} from "@/lib/room-view";
import type {
  RoomParticipant,
  RoomAgentStream,
  RoomControlActionDescriptor,
  RoomExecutionCancelDescriptor,
  RoomExecutionDecisionDescriptor,
  RoomExecutionPolicyMode,
  RoomExecutionPolicyUpdateDescriptor,
  RoomMemoryCandidate,
  RoomMemoryRebuildDescriptor,
  RoomMemoryResolveDescriptor,
  RoomObservationFrontier,
  RoomObservationBatchEvidence,
  RoomOperationsIncident,
  RoomOperationsProjection,
  RoomRuntimeRecoverDescriptor,
  RoomSkillDecision,
  RoomSummary,
  RoomTimelineItem,
  RoomTurn,
  RoomTurnParticipant
} from "@/lib/types";
import {
  useRoomStore,
  type RoomCache,
  type RoomExecutionCache,
  type RoomMemoryCache
} from "@/store/room-store";
import { RoomComposer } from "./room-composer";
import {
  formatRoomTime as formatTime,
  identityStyle,
  initials,
  RoomHeader
} from "./room-header";
import { RoomMessage, RoomPendingBubble } from "./room-message";
import { RoomAgentPreview } from "./room-agent-preview";
import { RoomInspector as RoomInspectorShell } from "./room-inspector";
import { RoomSidebar } from "./room-sidebar";
import { RoomTurnStatus, type RoomCancelTarget } from "./room-turn-status";
import { AgentConsole } from "./agent-console";
import { CommandPalette, type CommandPaletteAction } from "./command-palette";
import { RoomEvidenceDomain } from "./room-evidence-domain";
import { RoomExecutionDomain } from "./room-execution-domain";
import { RoomMemoryDomain } from "./room-memory-domain";
import {
  RoomMemoryRebuildDialog,
  RoomRuntimeDomain,
  RoomRuntimeRecoverDialog
} from "./room-runtime-domain";
import { useBrowserOnline, WorkspaceStatusRegion } from "./workspace-status-region";

type StreamAnnouncementSnapshot = {
  state: RoomAgentStream["state"];
  name: string;
};

const EMPTY_AGENT_STREAMS: RoomAgentStream[] = [];
type RoomWorkspaceCache = Pick<
  RoomCache,
  | "projection"
  | "timelineItems"
  | "pendingMessages"
  | "loading"
  | "loadingOlder"
  | "syncState"
  | "error"
  | "controlPending"
  | "controlError"
>;

export function roomAgentStreamAnnouncement(
  previous: ReadonlyMap<string, StreamAnnouncementSnapshot>,
  streams: ReadonlyArray<Pick<RoomAgentStream, "stream_id" | "participant_id" | "state">>,
  participantNames: ReadonlyMap<string, string>
) {
  const current = new Map<string, StreamAnnouncementSnapshot>();
  const announcements: string[] = [];
  for (const stream of streams) {
    const name = participantNames.get(stream.participant_id) ?? "Agent";
    current.set(stream.stream_id, { state: stream.state, name });
    const prior = previous.get(stream.stream_id)?.state;
    if (prior === undefined && stream.state === "streaming") {
      announcements.push(`${name} 开始生成`);
    } else if (prior !== "committing" && stream.state === "committing") {
      announcements.push(`${name} 正在提交`);
    } else if (
      prior !== undefined &&
      prior !== "resolved" &&
      prior !== "invalidated" &&
      (stream.state === "resolved" || stream.state === "invalidated")
    ) {
      announcements.push(`${name} 结束生成`);
    }
  }
  for (const [streamId, prior] of previous) {
    if (!current.has(streamId)) announcements.push(`${prior.name} 结束生成`);
  }
  return { current, announcement: announcements.join("；") };
}

type RoomWorkspaceProps = {
  onNavigateRoom: (roomId: string) => void;
  onCreatedRoom: (roomId: string) => void;
};

type CancelTarget = RoomCancelTarget;

function CancelObservationDialog({
  target,
  pending,
  onClose,
  onConfirm
}: {
  target: CancelTarget;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    if (event.shiftKey && document.activeElement === closeRef.current) {
      event.preventDefault();
      confirmRef.current?.focus();
    } else if (!event.shiftKey && document.activeElement === confirmRef.current) {
      event.preventDefault();
      closeRef.current?.focus();
    }
  }

  return (
    <div className="room-dialog-layer" onKeyDown={handleKeyDown}>
      <button className="room-dialog-scrim" disabled={pending} onClick={onClose} type="button" aria-label="关闭取消确认" />
      <div
        aria-describedby="cancel-observation-description"
        aria-labelledby="cancel-observation-title"
        aria-modal="true"
        className="room-confirm-dialog"
        role="alertdialog"
      >
        <span className="room-dialog-kicker">单 Agent 控制</span>
        <h2 id="cancel-observation-title">取消 {target.participant.display_name} 的当前处理？</h2>
        <p id="cancel-observation-description">
          这只会终止该 Agent 当前 observation 的 delivery。其他 Agent 和后续房间活动不受影响；取消完成后需显式重试才能重新开放。
        </p>
        <div className="room-dialog-actions">
          <button className="room-quiet-button" disabled={pending} onClick={onClose} ref={closeRef} type="button">返回</button>
          <button className="room-danger-button" disabled={pending} onClick={() => void onConfirm()} ref={confirmRef} type="button">
            {pending ? "正在请求取消…" : "确认取消当前处理"}
          </button>
        </div>
      </div>
    </div>
  );
}

type TimelineAnchorSnapshot = { messageId: string; offset: number };

export function captureTimelineAnchor(container: HTMLElement): TimelineAnchorSnapshot | null {
  const top = container.getBoundingClientRect().top;
  const node = [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
    (candidate) => candidate.getBoundingClientRect().bottom >= top
  );
  if (!node?.dataset.messageId) return null;
  return {
    messageId: node.dataset.messageId,
    offset: node.getBoundingClientRect().top - top
  };
}

export function restoreTimelineAnchor(
  container: HTMLElement,
  anchor: TimelineAnchorSnapshot | null
) {
  if (!anchor) return;
  const node = [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
    (candidate) => candidate.dataset.messageId === anchor.messageId
  );
  if (node) container.scrollTop = node.offsetTop - anchor.offset;
}

export function snapTimelineToBottom(container: HTMLElement) {
  const scrollBehavior = container.style.scrollBehavior;
  container.style.scrollBehavior = "auto";
  container.scrollTop = container.scrollHeight;
  container.style.scrollBehavior = scrollBehavior;
}

export function shouldInitializeTimeline(
  initializedRoomId: string | null,
  roomId: string,
  loading: boolean
) {
  return !loading && initializedRoomId !== roomId;
}

const RoomTimeline = memo(function RoomTimeline({
  roomId,
  cache
}: {
  roomId: string;
  cache: RoomWorkspaceCache;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const initializedRoomRef = useRef<string | null>(null);
  const wasAtBottomRef = useRef(true);
  const previousCountRef = useRef(0);
  const historyLoadRef = useRef(false);
  const [newCount, setNewCount] = useState(0);
  const [streamNoticeCount, setStreamNoticeCount] = useState(0);
  const [streamAnnouncement, setStreamAnnouncement] = useState("");
  const previousStreamIdsRef = useRef<Set<string>>(new Set());
  const previousStreamStatesRef = useRef<Map<string, StreamAnnouncementSnapshot>>(new Map());
  const markRead = useRoomStore((state) => state.markRead);
  const saveScrollAnchor = useRoomStore((state) => state.saveScrollAnchor);
  const anchor = useRoomStore((state) => state.scrollAnchors[roomId]);
  const loadOlder = useRoomStore((state) => state.loadOlder);
  const retryMessage = useRoomStore((state) => state.retryMessage);
  const agentStreams = useRoomStore(
    (state) => state.roomsById[roomId]?.agentStreams ?? EMPTY_AGENT_STREAMS
  );
  const durableActivityIds = useMemo(
    () => new Set(cache.timelineItems.map((item) => item.activity_id).filter(Boolean)),
    [cache.timelineItems]
  );
  const visibleStreams = useMemo(
    () => agentStreams.filter((stream) => {
      if (stream.state === "invalidated") return false;
      if (stream.state !== "resolved") return true;
      const activityId = stream.resolution?.produced_activity_id;
      return Boolean(activityId && !durableActivityIds.has(activityId));
    }),
    [agentStreams, durableActivityIds]
  );
  const participantNames = useMemo(
    () => new Map(
      (cache.projection?.participants ?? []).map((participant) => [
        participant.participant_id,
        participant.display_name
      ])
    ),
    [cache.projection?.participants]
  );
  const streamPresenceKey = visibleStreams
    .map((stream) => `${stream.stream_id}:${stream.state}`)
    .join("|");
  const streamContentKey = visibleStreams
    .map((stream) => `${stream.stream_id}:${stream.content.length}`)
    .join("|");

  const visibleSeq = cache.projection?.latest_visible_room_seq ?? cache.timelineItems.at(-1)?.room_seq ?? 0;

  useEffect(() => {
    const container = containerRef.current;
    if (
      !container ||
      !shouldInitializeTimeline(initializedRoomRef.current, roomId, cache.loading)
    ) return;
    initializedRoomRef.current = roomId;
    const saved = anchor
      ? [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
          (node) => node.dataset.messageId === anchor.messageId
        ) ?? null
      : null;
    if (saved) container.scrollTop = saved.offsetTop - anchor!.offset;
    else container.scrollTop = container.scrollHeight;
    wasAtBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight <= 120;
    previousCountRef.current = cache.timelineItems.length + cache.pendingMessages.length;
    if (wasAtBottomRef.current && visibleSeq) markRead(roomId, visibleSeq);
    // Restore only when entering a room, not on every incremental page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, cache.loading]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const count = cache.timelineItems.length + cache.pendingMessages.length;
    const added = Math.max(0, count - previousCountRef.current);
    if (added && historyLoadRef.current) {
      // Prepending history is not a new-message event and must not move the reader.
    } else if (added && wasAtBottomRef.current) {
      requestAnimationFrame(() => {
        snapTimelineToBottom(container);
        if (typeof document === "undefined" || document.visibilityState === "visible") {
          markRead(roomId, visibleSeq);
        }
      });
    } else if (added) {
      setNewCount((current) => current + added);
    }
    previousCountRef.current = count;
  }, [cache.pendingMessages.length, cache.timelineItems.length, markRead, roomId, visibleSeq]);

  useEffect(() => {
    const currentIds = new Set(
      streamPresenceKey
        ? streamPresenceKey.split("|").map((item) => item.slice(0, item.lastIndexOf(":")))
        : []
    );
    const started = [...currentIds].filter((streamId) => !previousStreamIdsRef.current.has(streamId));
    previousStreamIdsRef.current = currentIds;
    const nextCount = !currentIds.size || wasAtBottomRef.current
      ? 0
      : started.length ? currentIds.size : null;
    if (nextCount === null) return;
    const frame = requestAnimationFrame(() => setStreamNoticeCount(nextCount));
    return () => cancelAnimationFrame(frame);
  }, [streamPresenceKey]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !streamContentKey || !wasAtBottomRef.current) return;
    const frame = requestAnimationFrame(() => snapTimelineToBottom(container));
    return () => cancelAnimationFrame(frame);
  }, [streamContentKey]);

  useEffect(() => {
    const { current, announcement } = roomAgentStreamAnnouncement(
      previousStreamStatesRef.current,
      agentStreams,
      participantNames
    );
    previousStreamStatesRef.current = current;
    if (!announcement) return;
    const timer = window.setTimeout(() => setStreamAnnouncement(announcement), 0);
    return () => window.clearTimeout(timer);
  }, [agentStreams, participantNames]);

  function handleScroll() {
    const container = containerRef.current;
    if (!container) return;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= 120;
    wasAtBottomRef.current = atBottom;
    if (atBottom) {
      setNewCount(0);
      if ((typeof document === "undefined" || document.visibilityState === "visible") && visibleSeq) {
        markRead(roomId, visibleSeq);
      }
    }
    const nodes = [...container.querySelectorAll<HTMLElement>("[data-message-id]")];
    const containerTop = container.getBoundingClientRect().top;
    const firstVisible = nodes.find((node) => node.getBoundingClientRect().bottom >= containerTop);
    if (firstVisible) {
      saveScrollAnchor(roomId, {
        messageId: firstVisible.dataset.messageId ?? "",
        offset: firstVisible.getBoundingClientRect().top - containerTop
      });
    }
  }

  async function handleLoadOlder() {
    const container = containerRef.current;
    if (!container || cache.loadingOlder) return;
    const snapshot = captureTimelineAnchor(container);
    historyLoadRef.current = true;
    try {
      await loadOlder(roomId);
      requestAnimationFrame(() => {
        const current = containerRef.current;
        if (current) restoreTimelineAnchor(current, snapshot);
        historyLoadRef.current = false;
      });
    } catch {
      historyLoadRef.current = false;
    }
  }

  async function handleJumpToReference(
    messageId?: string | null,
    activityId?: string | null
  ) {
    const locate = () => {
      const container = containerRef.current;
      if (!container) return null;
      return [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
        (candidate) =>
          (messageId && candidate.dataset.messageId === messageId) ||
          (activityId && candidate.dataset.activityId === activityId)
      ) ?? null;
    };
    for (let page = 0; page < 5; page += 1) {
      const target = locate();
      if (target) {
        target.scrollIntoView?.({ block: "center", behavior: "smooth" });
        target.focus({ preventScroll: true });
        return;
      }
      const latest = useRoomStore.getState().roomsById[roomId];
      if (!latest?.projection?.has_older || latest.loadingOlder) return;
      await loadOlder(roomId);
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    }
  }

  return (
    <div className="room-timeline-wrap">
      <div
        aria-label="房间消息"
        className="room-timeline"
        onScroll={handleScroll}
        ref={containerRef}
        role="log"
      >
        {cache.projection?.has_older ? (
          <button className="room-load-older" disabled={cache.loadingOlder} onClick={() => void handleLoadOlder()} type="button">
            {cache.loadingOlder ? "正在加载…" : "加载更早消息"}
          </button>
        ) : null}
        {cache.timelineItems.map((item, index) => (
          <Fragment key={item.id}>
          {new Date(item.created_at ?? 0).toDateString() !== new Date(cache.timelineItems[index - 1]?.created_at ?? 0).toDateString() ? (
            <div className="room-date-separator" role="separator"><span>{formatTime(item.created_at)}</span></div>
          ) : null}
          <RoomMessage
            item={item}
            onJumpToReference={(messageId, activityId) => {
              void handleJumpToReference(messageId, activityId);
            }}
          />
          </Fragment>
        ))}
        {cache.pendingMessages.map((pending) => (
          <RoomPendingBubble
            key={pending.clientRequestId}
            onRetry={() => void retryMessage(pending.clientRequestId)}
            pending={pending}
          />
        ))}
        {visibleStreams.length ? (
          <div aria-label="Agent 正在生成" className="room-agent-streams">
            {visibleStreams.map((stream) => (
              <RoomAgentPreview
                displayName={participantNames.get(stream.participant_id) ?? "Agent"}
                key={stream.stream_id}
                stream={stream}
              />
            ))}
          </div>
        ) : null}
        {!cache.loading && !cache.timelineItems.length && !cache.pendingMessages.length ? (
          <div className="room-empty-timeline">
            <strong>开始自然群聊</strong>
            <span>每位活跃 Agent 都会观察共享房间，并独立决定是否回应。</span>
          </div>
        ) : null}
      </div>
      <div aria-live="polite" className="sr-only" role="status">
        {streamAnnouncement}
      </div>
      {newCount > 0 ? (
        <button
          className="room-new-messages"
          onClick={() => {
            const container = containerRef.current;
            if (container) snapTimelineToBottom(container);
            setNewCount(0);
          }}
          type="button"
        >
          有 {newCount} 条新消息
        </button>
      ) : null}
      {streamNoticeCount > 0 ? (
        <button
          className="room-new-messages room-stream-notice"
          onClick={() => {
            const container = containerRef.current;
            if (container) snapTimelineToBottom(container);
            setStreamNoticeCount(0);
          }}
          type="button"
        >
          有 {streamNoticeCount} 个 Agent 正在生成
        </button>
      ) : null}
    </div>
  );
});

function RoomInspector({
  activeTab,
  onTabChange,
  agentConsoleSection,
  executionCache,
  executionActionPending,
  executionActionError,
  memoryCache,
  memoryActionPending,
  memoryActionError,
  memoryRebuildPending,
  memoryRebuildError,
  operations,
  operationsError,
  operationsLoading,
  recoverPending,
  recoverError,
  selectedRoomId,
  participants,
  turns,
  controlPending,
  onCancel,
  onRetry,
  onClose,
  onIncidentAction,
  onRecover,
  modal,
  inspectorTarget,
  targetReady,
  onTargetResolved,
  onTargetMissing,
  onSelectExecutionCandidate,
  onUpdateExecutionPolicy,
  onDecideExecutionCandidate,
  onCancelExecutionRun,
  onResolveMemoryCandidate,
  onRebuildMemoryIndex
}: {
  activeTab: "agent" | "room" | "runtime";
  onTabChange: (tab: "agent" | "room" | "runtime") => void;
  agentConsoleSection: ReactNode;
  executionCache: RoomExecutionCache | null;
  executionActionPending: boolean;
  executionActionError: { message: string; status: number } | null;
  memoryCache: RoomMemoryCache | null;
  memoryActionPending: boolean;
  memoryActionError: { message: string; status: number } | null;
  memoryRebuildPending: boolean;
  memoryRebuildError: { message: string; status: number } | null;
  operations: RoomOperationsProjection | null;
  operationsError: { message: string; status: number } | null;
  operationsLoading: boolean;
  recoverPending: boolean;
  recoverError: { message: string; status: number } | null;
  selectedRoomId: string | null;
  participants: RoomParticipant[];
  turns: RoomTurn[];
  controlPending: RoomCache["controlPending"];
  onCancel: (target: CancelTarget) => void;
  onRetry: (observationId: string, descriptor: RoomControlActionDescriptor) => void;
  onClose: () => void;
  onIncidentAction: (incident: RoomOperationsIncident) => void;
  onRecover: (descriptor: RoomRuntimeRecoverDescriptor) => void;
  modal: boolean;
  inspectorTarget: { roomId: string; observationId: string | null; incidentId: string } | null;
  targetReady: boolean;
  onTargetResolved: (target: null) => void;
  onTargetMissing: () => void;
  onSelectExecutionCandidate: (candidateId: string | null) => Promise<void>;
  onUpdateExecutionPolicy: (
    mode: RoomExecutionPolicyMode,
    descriptor: RoomExecutionPolicyUpdateDescriptor
  ) => Promise<boolean>;
  onDecideExecutionCandidate: (
    candidateId: string,
    decision: "execute" | "reject",
    descriptor: RoomExecutionDecisionDescriptor
  ) => Promise<boolean>;
  onCancelExecutionRun: (
    runId: string,
    descriptor: RoomExecutionCancelDescriptor
  ) => Promise<boolean>;
  onResolveMemoryCandidate: (
    candidateId: string,
    decision: "approve" | "reject",
    descriptor: RoomMemoryResolveDescriptor
  ) => Promise<boolean>;
  onRebuildMemoryIndex: (descriptor: RoomMemoryRebuildDescriptor) => void;
}) {
  return (
    <RoomInspectorShell
      activeTab={activeTab}
      agentConsoleSection={agentConsoleSection}
      executionSection={<RoomExecutionDomain
        actionError={executionActionError}
        actionPending={executionActionPending}
        cache={executionCache}
        onCancelRun={onCancelExecutionRun}
        onDecideCandidate={onDecideExecutionCandidate}
        onSelectCandidate={onSelectExecutionCandidate}
        onUpdatePolicy={onUpdateExecutionPolicy}
      />}
      memorySection={<RoomMemoryDomain
        actionError={memoryActionError}
        actionPending={memoryActionPending}
        cache={memoryCache}
        rebuildDescriptor={operations?.actions.rebuild_memory_index ?? null}
        rebuildError={memoryRebuildError}
        rebuildPending={memoryRebuildPending}
        onResolve={onResolveMemoryCandidate}
        onRebuild={onRebuildMemoryIndex}
      />}
      modal={modal}
      onClose={onClose}
      onTabChange={onTabChange}
      onTargetMissing={onTargetMissing}
      onTargetResolved={() => onTargetResolved(null)}
      operationsSection={<RoomRuntimeDomain
        onIncidentAction={onIncidentAction}
        onRecover={onRecover}
        operations={operations}
        operationsError={operationsError}
        operationsLoading={operationsLoading}
        recoverError={recoverError}
        recoverPending={recoverPending}
        selectedRoomId={selectedRoomId}
      />}
      roomEvidenceSection={<RoomEvidenceDomain
        controlPending={controlPending}
        onCancel={onCancel}
        onRetry={onRetry}
        participants={participants}
        turns={turns}
      />}
      selectedRoomId={selectedRoomId}
      target={inspectorTarget}
      targetReady={targetReady}
      targetVersion={`${turns.length}:${operations?.incident_total ?? 0}`}
    />
  );
}

function syncLabel(cache: RoomWorkspaceCache | null): string {
  if (!cache) return "未选择房间";
  const labels = {
    idle: "等待同步",
    syncing: "正在同步",
    synced: "已同步",
    "catching-up": "正在补拉",
    stale: "数据可能过期",
    offline: "离线"
  };
  return labels[cache.syncState];
}

function useCompactLayout() {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(max-width: 1179px)");
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return compact;
}

export function RoomWorkspace({ onNavigateRoom, onCreatedRoom }: RoomWorkspaceProps) {
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
    theme: state.theme,
    sidebarOpen: state.sidebarOpen,
    inspectorOpen: state.inspectorOpen,
    dockTab: state.dockTab,
    pinnedRoomIds: state.pinnedRoomIds,
    operations: state.operations,
    operationsLoading: state.operationsLoading,
    operationsError: state.operationsError,
    executionsByRoom: state.executionsByRoom,
    memoryByRoom: state.memoryByRoom,
    codexByRoom: state.codexByRoom,
    executionActionPending: state.executionActionPending,
    executionActionError: state.executionActionError,
    memoryActionPending: state.memoryActionPending,
    memoryActionError: state.memoryActionError,
    memoryRebuildPending: state.memoryRebuildPending,
    memoryRebuildError: state.memoryRebuildError,
    runtimeRecoverPending: state.runtimeRecoverPending,
    runtimeRecoverError: state.runtimeRecoverError,
    inspectorTarget: state.inspectorTarget,
    loadRooms: state.loadRooms,
    createRoom: state.createRoom,
    refreshRoom: state.refreshRoom,
    sendMessage: state.sendMessage,
    controlObservation: state.controlObservation,
    refreshOperations: state.refreshOperations,
    refreshExecutions: state.refreshExecutions,
    refreshMemory: state.refreshMemory,
    refreshCodexAgents: state.refreshCodexAgents,
    selectCodexParticipant: state.selectCodexParticipant,
    submitCodexAction: state.submitCodexAction,
    getCodexConsolePreference: state.getCodexConsolePreference,
    setCodexConsolePreference: state.setCodexConsolePreference,
    resolveMemoryCandidate: state.resolveMemoryCandidate,
    rebuildMemoryIndex: state.rebuildMemoryIndex,
    selectExecutionCandidate: state.selectExecutionCandidate,
    updateExecutionPolicy: state.updateExecutionPolicy,
    decideExecutionCandidate: state.decideExecutionCandidate,
    cancelExecutionRun: state.cancelExecutionRun,
    recoverRuntime: state.recoverRuntime,
    setDraft: state.setDraft,
    setTheme: state.setTheme,
    setSidebarOpen: state.setSidebarOpen,
    setInspectorOpen: state.setInspectorOpen,
    setDockTab: state.setDockTab,
    togglePinnedRoom: state.togglePinnedRoom,
    setInspectorTarget: state.setInspectorTarget,
    clearRoomError: state.clearRoomError,
    clearControlError: state.clearControlError,
    startOperationsSync: state.startOperationsSync,
    startExecutionSync: state.startExecutionSync,
    startMemorySync: state.startMemorySync
  })));
  const compactLayout = useCompactLayout();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarQuery, setSidebarQuery] = useState("");
  const [creatingRoom, setCreatingRoom] = useState(false);
  const [roomTitle, setRoomTitle] = useState("");
  const [roomCreateRequestId, setRoomCreateRequestId] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<CancelTarget | null>(null);
  const [recoverTarget, setRecoverTarget] = useState<RoomRuntimeRecoverDescriptor | null>(null);
  const [memoryRebuildTarget, setMemoryRebuildTarget] = useState<RoomMemoryRebuildDescriptor | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<string | null>(null);
  const browserOnline = useBrowserOnline();
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const selectedRoom = store.rooms.find((room) => room.conversation_id === store.selectedRoomId) ?? null;
  const cache = useRoomStore(useShallow((state): RoomWorkspaceCache | null => {
    const roomId = state.selectedRoomId;
    const room = roomId ? state.roomsById[roomId] : null;
    if (!room) return null;
    return {
      projection: room.projection,
      timelineItems: room.timelineItems,
      pendingMessages: room.pendingMessages,
      loading: room.loading,
      loadingOlder: room.loadingOlder,
      syncState: room.syncState,
      error: room.error,
      controlPending: room.controlPending,
      controlError: room.controlError
    };
  }));
  const executionCache = store.selectedRoomId
    ? store.executionsByRoom[store.selectedRoomId] ?? null
    : null;
  const memoryCache = store.selectedRoomId
    ? store.memoryByRoom[store.selectedRoomId] ?? null
    : null;
  const codexCache = store.selectedRoomId
    ? store.codexByRoom[store.selectedRoomId] ?? null
    : null;
  const codexParticipants = useMemo(
    () => codexCache?.projection?.participants ?? [],
    [codexCache?.projection?.participants]
  );
  const selectedCodexParticipant = codexParticipants.find(
    (item) => item.participant.participant_id === codexCache?.selectedParticipantId
  ) ?? codexParticipants[0] ?? null;
  const projection = cache?.projection ?? null;
  const participants = projection?.participants ?? selectedRoom?.members ?? [];
  const selectedRoomParticipant = participants.find(
    (item) => item.participant_id === selectedCodexParticipant?.participant.participant_id
  );
  const selectedParticipantId = selectedCodexParticipant?.participant.participant_id;
  const selectedSkillDecisions = useMemo(() => {
    const decisions = [
      selectedRoomParticipant?.frontier?.current_attempt?.skill_decision,
      selectedRoomParticipant?.last_completed_outcome?.skill_decision,
      ...(projection?.turns.flatMap((turn) => turn.participants
        .filter((item) => item.participant_id === selectedParticipantId)
        .flatMap((item) => [item.root_skill_decision, item.frontier?.current_attempt?.skill_decision, item.latest_outcome?.skill_decision])) ?? [])
    ].filter((item): item is RoomSkillDecision => Boolean(item));
    const unique = new Map<string, RoomSkillDecision>();
    for (const decision of decisions) {
      unique.set(`${decision.skill_id}:${decision.version}:${decision.context_status}`, decision);
    }
    return [...unique.values()].slice(-8);
  }, [projection?.turns, selectedParticipantId, selectedRoomParticipant]);
  const activeTurns = projection?.turns.filter((turn) => turn.state !== "settled") ?? [];
  const currentTurn = activeTurns.at(-1) ?? projection?.turns.at(-1) ?? null;
  const title = projection?.conversation.title ?? selectedRoom?.title ?? "选择一个房间";
  const draft = store.selectedRoomId ? store.drafts[store.selectedRoomId] ?? "" : "";
  const operationsAlert = store.operations?.overall === "blocked"
    ? { className: "has-alert", label: "运行时阻塞", glyph: "!" }
    : store.operations?.overall === "attention"
      ? { className: "has-attention", label: "运行时需要关注", glyph: "·" }
      : memoryCache?.projection?.degraded || memoryCache?.projection?.pending_candidate_total
        ? { className: "has-attention", label: "长期记忆需要关注", glyph: "·" }
        : null;
  const commandActions = useMemo<CommandPaletteAction[]>(() => [
    {
      id: "new-room",
      label: "新建 Room",
      detail: "选择 roster 并创建协作空间",
      run: () => { setCreatingRoom(true); if (compactLayout) setMobileSidebarOpen(true); }
    },
    ...store.rooms.slice(0, 8).map((room) => ({
      id: `room:${room.conversation_id}`,
      label: room.title,
      detail: "切换 Room",
      run: () => onNavigateRoom(room.conversation_id)
    })),
    ...codexParticipants.map((participant) => ({
      id: `agent:${participant.participant.participant_id}`,
      label: participant.participant.display_name,
      detail: "打开单 Agent Codex 工作台",
      run: () => {
        store.selectCodexParticipant(participant.participant.participant_id);
        store.setDockTab("agent");
      }
    })),
    { id: "dock-room", label: "Room 控制面", detail: "执行、记忆与因果证据", run: () => store.setDockTab("room") },
    { id: "dock-runtime", label: "Runtime 状态", detail: "运行事件与恢复", run: () => store.setDockTab("runtime") },
    { id: "theme", label: "切换主题", detail: store.theme === "dark" ? "切换到浅色" : "切换到深色", run: () => store.setTheme(store.theme === "dark" ? "light" : "dark") }
  ], [codexParticipants, compactLayout, onNavigateRoom, store]);

  useEffect(() => {
    document.documentElement.dataset.theme = store.theme;
  }, [store.theme]);

  useEffect(() => {
    if (!workspaceNotice) return;
    const timer = window.setTimeout(() => setWorkspaceNotice(null), 5_000);
    return () => window.clearTimeout(timer);
  }, [workspaceNotice]);

  useEffect(() => {
    const refresh = () => {
      void store.loadRooms();
      const current = useRoomStore.getState();
      if (!current.inspectorOpen) return;
      if (current.dockTab === "runtime") void current.refreshOperations();
      else if (current.dockTab === "room") {
        void current.refreshExecutions();
        void current.refreshMemory();
      } else void current.refreshCodexAgents();
    };
    const visibility = () => {
      store.startOperationsSync();
      store.startExecutionSync();
      store.startMemorySync();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const invalidRoom = Boolean(
    store.selectedRoomId &&
    !selectedRoom &&
    cache?.error?.status === 404 &&
    !cache.projection &&
    !store.roomsLoading
  );
  const unavailableRoom = Boolean(
    store.selectedRoomId && cache?.error && cache.error.status !== 404 && !cache.projection
  );

  function closeCancelDialog() {
    setCancelTarget(null);
    requestAnimationFrame(() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
      else document.querySelector<HTMLElement>(".room-inspector button")?.focus();
    });
  }

  async function confirmCancel() {
    if (!cancelTarget) return;
    await store.controlObservation(
      cancelTarget.observationId,
      "cancel",
      cancelTarget.descriptor
    );
    closeCancelDialog();
  }

  function closeRecoverDialog() {
    setRecoverTarget(null);
    requestAnimationFrame(() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
      else document.querySelector<HTMLElement>(".room-inspector button")?.focus();
    });
  }

  async function confirmRecover() {
    if (!recoverTarget) return;
    const applied = await store.recoverRuntime(recoverTarget);
    setWorkspaceNotice(applied ? "Room Runtime 恢复请求已应用；状态将由耐久投影确认。" : "恢复请求未完成，已刷新最新状态。");
    closeRecoverDialog();
  }

  function closeMemoryRebuildDialog() {
    setMemoryRebuildTarget(null);
    requestAnimationFrame(() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
      else document.querySelector<HTMLElement>(".room-inspector button")?.focus();
    });
  }

  async function confirmMemoryRebuild() {
    if (!memoryRebuildTarget) return;
    const applied = await store.rebuildMemoryIndex(memoryRebuildTarget);
    setWorkspaceNotice(applied ? "MemoryOS 重建请求已应用；请等待耐久投影更新。" : "重建请求未完成，已刷新最新状态。");
    closeMemoryRebuildDialog();
  }

  function handleOperationIncident(incident: RoomOperationsIncident) {
    if (incident.next_action === "rebuild_memory_index") {
      const descriptor = store.operations?.actions.rebuild_memory_index;
      if (descriptor?.available && !descriptor.pending) {
        returnFocusRef.current = document.activeElement as HTMLElement | null;
        setMemoryRebuildTarget(descriptor);
      } else {
        void store.refreshOperations();
      }
      return;
    }
    if (incident.next_action === "recover_runtime" || incident.next_action === "repair_then_recover") {
      const descriptor = store.operations?.actions.recover_runtime;
      if (descriptor?.available) {
        returnFocusRef.current = document.activeElement as HTMLElement | null;
        setRecoverTarget(descriptor);
      } else {
        void store.refreshOperations();
      }
      return;
    }
    if (!incident.conversation_id) return;
    store.setDockTab("room");
    store.setInspectorTarget({
      roomId: incident.conversation_id,
      observationId: incident.observation_id,
      incidentId: incident.incident_id
    });
    if (incident.conversation_id !== store.selectedRoomId) {
      onNavigateRoom(incident.conversation_id);
    }
  }

  function handleInspectorTargetMissing() {
    void store.refreshOperations();
    if (store.selectedRoomId) {
      void store.refreshRoom(store.selectedRoomId, "incremental");
    }
  }

  return (
    <div className={`room-app ${store.sidebarOpen ? "has-sidebar" : ""} ${store.inspectorOpen ? "has-inspector" : ""}`}>
      {store.sidebarOpen || mobileSidebarOpen ? (
        <div className={`room-sidebar-slot ${mobileSidebarOpen ? "is-mobile-open" : ""}`}>
          {mobileSidebarOpen ? (
            <button className="room-mobile-scrim" onClick={() => setMobileSidebarOpen(false)} type="button" aria-label="关闭房间栏遮罩" />
          ) : null}
          <RoomSidebar
            createRequestId={roomCreateRequestId}
            createError={store.roomCreateError}
            createPending={store.roomCreatePending}
            creating={creatingRoom}
            drafts={store.drafts}
            error={store.roomsError}
            loading={store.roomsLoading}
            loaded={store.roomsLoaded}
            onClose={() => setMobileSidebarOpen(false)}
            onCreate={async (name, clientRequestId, rosterTemplateId) => {
              setRoomCreateRequestId(clientRequestId);
              const id = await store.createRoom(name, clientRequestId, rosterTemplateId);
              if (id) {
                setRoomTitle("");
                setRoomCreateRequestId(null);
                setCreatingRoom(false);
                onCreatedRoom(id);
              }
              return Boolean(id);
            }}
            onCreatingChange={setCreatingRoom}
            onNavigate={(id) => {
              setMobileSidebarOpen(false);
              onNavigateRoom(id);
            }}
            onQueryChange={setSidebarQuery}
            onTitleChange={(value) => {
              setRoomTitle(value);
              setRoomCreateRequestId(null);
            }}
            query={sidebarQuery}
            pinnedRoomIds={store.pinnedRoomIds}
            onTogglePinned={store.togglePinnedRoom}
            readCursors={store.readCursors}
            rooms={store.rooms}
            selectedRoomId={store.selectedRoomId}
            title={roomTitle}
          />
        </div>
      ) : null}

      <main className="room-main">
        <RoomHeader
          inspectorOpen={store.inspectorOpen}
          navigationOpen={compactLayout ? mobileSidebarOpen : store.sidebarOpen}
          onToggleInspector={() => store.setInspectorOpen(!store.inspectorOpen)}
          onToggleNavigation={() => {
              if (compactLayout) setMobileSidebarOpen((open) => !open);
              else store.setSidebarOpen(!store.sidebarOpen);
          }}
          onToggleTheme={() => store.setTheme(store.theme === "dark" ? "light" : "dark")}
          operationsAlert={operationsAlert}
          participants={participants}
          syncLabel={syncLabel(cache)}
          syncState={cache?.syncState ?? "idle"}
          theme={store.theme}
          title={title}
        />

        {invalidRoom ? (
          <section className="room-fatal-empty" role="alert">
            <strong>找不到这个房间</strong>
            <span>{cache?.error?.message ?? "房间不存在或当前无法读取。"}</span>
            <button className="room-primary-button" onClick={() => store.rooms[0] && onNavigateRoom(store.rooms[0].conversation_id)} type="button">返回最近房间</button>
          </section>
        ) : unavailableRoom ? (
          <section className="room-fatal-empty" role="alert">
            <strong>房间暂时无法读取</strong>
            <span>{cache?.error?.message ?? "Chat API 当前不可用。"}</span>
            <button className="room-primary-button" onClick={() => void store.refreshRoom(store.selectedRoomId ?? undefined, "initial")} type="button">重试读取</button>
          </section>
        ) : store.selectedRoomId && cache ? (
          <>
            <RoomTurnStatus
              controlPending={cache.controlPending}
              hiddenCount={Math.max(0, (projection?.active_turn_count ?? activeTurns.length) - 1)}
              onSelectAgent={(participantId) => {
                store.selectCodexParticipant(participantId);
                store.setDockTab("agent");
              }}
              onCancel={(target) => {
                returnFocusRef.current = document.activeElement as HTMLElement | null;
                setCancelTarget(target);
              }}
              onRetry={(observationId, descriptor) => {
                void store.controlObservation(observationId, "retry", descriptor);
              }}
              turn={currentTurn}
            />
            {cache.controlError ? (
              <div className="room-error-banner room-control-error" role="alert">
                <span>
                  <strong>{cache.controlError.status === 409 ? "状态已经变化" : "Agent 控制未完成"}</strong>
                  {cache.controlError.status === 409
                    ? "已刷新最新 Room 状态，请根据当前可用动作重试。"
                    : cache.controlError.message}
                </span>
                <button className="room-icon-button" onClick={() => store.clearControlError()} type="button" aria-label="关闭控制错误">×</button>
              </div>
            ) : null}
            {cache.error ? (
              <div className="room-error-banner" role="alert">
                <span><strong>{cache.syncState === "stale" ? "同步暂时中断" : "房间读取失败"}</strong>{cache.error.message}</span>
                <button className="room-quiet-button" onClick={() => void store.refreshRoom(store.selectedRoomId ?? undefined, cache.projection ? "incremental" : "initial")} type="button">重试</button>
                <button className="room-icon-button" onClick={() => store.clearRoomError()} type="button" aria-label="关闭错误">×</button>
              </div>
            ) : null}
            <RoomTimeline cache={cache} roomId={store.selectedRoomId} />
            <RoomComposer
              disabled={!projection && cache.loading}
              draft={draft}
              key={store.selectedRoomId}
              onDraftChange={(value) => store.setDraft(store.selectedRoomId!, value)}
              onSend={async (content) => {
                const result = await store.sendMessage(content);
                setWorkspaceNotice(result ? "消息已提交到 Room。" : "消息发送未完成，可在失败消息上重试。");
                return result;
              }}
              participants={participants}
              roomId={store.selectedRoomId}
            />
          </>
        ) : store.roomsError && !store.rooms.length ? (
          <section className="room-fatal-empty" role="alert">
            <strong>无法连接 xmuse</strong>
            <span>{store.roomsError.message}</span>
            <button className="room-primary-button" onClick={() => void store.loadRooms()} type="button">重新连接</button>
          </section>
        ) : (
          <section className="room-fatal-empty">
            <strong>{store.roomsLoading && !store.roomsLoaded ? "正在连接 xmuse…" : "还没有房间"}</strong>
            <span>创建房间后，活跃 Agent 会共同观察其中的活动。</span>
          </section>
        )}
      </main>

      {store.inspectorOpen ? (
        <>
          {compactLayout ? (
            <button
              aria-label="关闭检查器遮罩"
              className="room-inspector-scrim"
              onClick={() => store.setInspectorOpen(false)}
              tabIndex={-1}
              type="button"
            />
          ) : null}
          <RoomInspector
            activeTab={store.dockTab}
            agentConsoleSection={(
              <section className="room-agent-console-section" aria-label="Codex Agent Console">
                <div className="room-agent-console-tabs" role="tablist" aria-label="选择 Codex Agent">
                  {codexParticipants.map((item) => (
                    <button
                      aria-label={item.participant.display_name}
                      aria-selected={item.participant.participant_id === selectedCodexParticipant?.participant.participant_id}
                      key={item.participant.participant_id}
                      onClick={() => store.selectCodexParticipant(item.participant.participant_id)}
                      role="tab"
                      type="button"
                    >
                      <strong>{item.participant.display_name}</strong>
                      <small>{item.participant.role} · {roomAgentWorkStateLabel(item)}</small>
                    </button>
                  ))}
                </div>
                {selectedCodexParticipant && codexCache?.projection ? (
                  <AgentConsole
                    error={codexCache.actionErrors[selectedCodexParticipant.participant.participant_id]?.message
                      ?? codexCache.error?.message
                      ?? null}
                    key={selectedCodexParticipant.participant.participant_id}
                    localMode={store.getCodexConsolePreference(selectedCodexParticipant.participant.participant_id)}
                    nativeEvents={codexCache.projection.native_events.items}
                    onAction={async (capabilityId, safeRequest, descriptor, confirmed) => {
                      const result = await store.submitCodexAction(
                        selectedCodexParticipant.participant.participant_id,
                        capabilityId,
                        safeRequest,
                        descriptor,
                        confirmed
                      );
                      setWorkspaceNotice(result ? "单 Agent Codex 操作已提交；不会生成 Room 发言。" : "Codex 操作未完成，已保留最新投影。");
                      return result;
                    }}
                    onPreferenceChange={(mode) => {
                      store.setCodexConsolePreference(
                        selectedCodexParticipant.participant.participant_id,
                        mode
                      );
                    }}
                    onRefresh={() => void store.refreshCodexAgents()}
                    participant={selectedCodexParticipant}
                    skillDecisions={selectedSkillDecisions}
                    pending={Boolean(codexCache.actionPending[selectedCodexParticipant.participant.participant_id])}
                  />
                ) : (
                  <div className="agent-console agent-console--empty" role="status">
                    <h3>Agent Console</h3>
                    <p>{codexCache?.loading ? "正在读取 Codex 原生状态…" : "当前房间没有可用的 Codex Agent 投影。"}</p>
                    {codexCache?.error ? <button onClick={() => void store.refreshCodexAgents()} type="button">重试</button> : null}
                  </div>
                )}
              </section>
            )}
            controlPending={cache?.controlPending ?? null}
            executionActionError={store.executionActionError}
            executionActionPending={Boolean(store.executionActionPending)}
            executionCache={executionCache}
            memoryActionError={store.memoryActionError}
            memoryActionPending={Boolean(store.memoryActionPending)}
            memoryCache={memoryCache}
            memoryRebuildError={store.memoryRebuildError}
            memoryRebuildPending={store.memoryRebuildPending}
            inspectorTarget={store.inspectorTarget}
            modal={compactLayout}
            operations={store.operations}
            operationsError={store.operationsError}
            operationsLoading={store.operationsLoading}
            onCancel={(target) => {
              returnFocusRef.current = document.activeElement as HTMLElement | null;
              setCancelTarget(target);
            }}
            onClose={() => store.setInspectorOpen(false)}
            onTabChange={store.setDockTab}
            onIncidentAction={handleOperationIncident}
            onCancelExecutionRun={store.cancelExecutionRun}
            onDecideExecutionCandidate={store.decideExecutionCandidate}
            onResolveMemoryCandidate={store.resolveMemoryCandidate}
            onRebuildMemoryIndex={(descriptor) => {
              returnFocusRef.current = document.activeElement as HTMLElement | null;
              setMemoryRebuildTarget(descriptor);
            }}
            onRecover={(descriptor) => {
              returnFocusRef.current = document.activeElement as HTMLElement | null;
              setRecoverTarget(descriptor);
            }}
            onRetry={(observationId, descriptor) => {
              void store.controlObservation(observationId, "retry", descriptor);
            }}
            onSelectExecutionCandidate={store.selectExecutionCandidate}
            onTargetResolved={store.setInspectorTarget}
            onTargetMissing={handleInspectorTargetMissing}
            onUpdateExecutionPolicy={store.updateExecutionPolicy}
            participants={participants}
            recoverError={store.runtimeRecoverError}
            recoverPending={store.runtimeRecoverPending}
            selectedRoomId={store.selectedRoomId}
            targetReady={Boolean(projection) && !cache?.loading}
            turns={projection?.turns ?? []}
          />
        </>
      ) : null}
      <WorkspaceStatusRegion
        message={!browserOnline
          ? "浏览器离线；Room 与 Runtime 状态暂不更新。"
          : cache?.controlError?.status === 409 || store.executionActionError?.status === 409 || store.memoryActionError?.status === 409
            ? "状态已经变化，已刷新耐久投影。"
            : workspaceNotice}
      />
      {cancelTarget ? (
        <CancelObservationDialog
          onClose={closeCancelDialog}
          onConfirm={confirmCancel}
          pending={cache?.controlPending?.observationId === cancelTarget.observationId}
          target={cancelTarget}
        />
      ) : null}
      {recoverTarget ? (
        <RoomRuntimeRecoverDialog
          onClose={closeRecoverDialog}
          onConfirm={confirmRecover}
          pending={store.runtimeRecoverPending}
        />
      ) : null}
      {memoryRebuildTarget ? (
        <RoomMemoryRebuildDialog
          onClose={closeMemoryRebuildDialog}
          onConfirm={confirmMemoryRebuild}
          pending={store.memoryRebuildPending}
        />
      ) : null}
      <CommandPalette actions={commandActions} />
    </div>
  );
}
