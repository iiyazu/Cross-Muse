"use client";

import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode
} from "react";
import type { WorkspaceDockTab } from "@/store/room-persistence";
import { X } from "lucide-react";

export type RoomInspectorTarget = {
  roomId: string;
  observationId: string | null;
  incidentId: string;
};

export type RoomInspectorProps = {
  modal: boolean;
  selectedRoomId: string | null;
  target: RoomInspectorTarget | null;
  targetReady: boolean;
  targetVersion: string | number;
  agentConsoleSection?: ReactNode;
  operationsSection: ReactNode;
  executionSection: ReactNode;
  memorySection: ReactNode;
  roomEvidenceSection: ReactNode;
  activeTab?: WorkspaceDockTab;
  onTabChange?: (tab: WorkspaceDockTab) => void;
  onClose: () => void;
  onTargetResolved: () => void;
  onTargetMissing: () => void;
};

const FOCUSABLE_SELECTOR = [
  "button:not(:disabled)",
  "summary",
  "[href]",
  "input:not(:disabled)",
  "textarea:not(:disabled)",
  "[tabindex]:not([tabindex='-1'])"
].join(", ");

/**
 * Structural owner for the Inspector. Projection interpretation and operator actions
 * stay in the supplied domain sections; this shell only owns ordering, focus and
 * durable-target navigation.
 */
export function RoomInspector({
  modal,
  selectedRoomId,
  target,
  targetReady,
  targetVersion,
  agentConsoleSection,
  operationsSection,
  executionSection,
  memorySection,
  roomEvidenceSection,
  activeTab = "room",
  onTabChange = () => undefined,
  onClose,
  onTargetResolved,
  onTargetMissing
}: RoomInspectorProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const inspectorRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!modal) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => previousFocus?.focus();
  }, [modal]);

  useEffect(() => {
    if (!target || target.roomId !== selectedRoomId) return;
    const frame = requestAnimationFrame(() => {
      const root = inspectorRef.current;
      if (!root) return;
      const observation = target.observationId
        ? [...root.querySelectorAll<HTMLElement>("[data-observation-id]")].find(
            (item) => item.dataset.observationId === target.observationId
          )
        : root.querySelector<HTMLElement>(".room-operations");
      if (observation) {
        observation.scrollIntoView?.({ block: "nearest" });
        observation.focus({ preventScroll: true });
        onTargetResolved();
        return;
      }
      if (!targetReady) return;
      const incident = [...root.querySelectorAll<HTMLElement>("[data-incident-id]")].find(
        (item) => item.dataset.incidentId === target.incidentId
      );
      (incident ?? root.querySelector<HTMLElement>(".room-operations"))?.focus({
        preventScroll: true
      });
      onTargetResolved();
      onTargetMissing();
    });
    return () => cancelAnimationFrame(frame);
  }, [
    onTargetMissing,
    onTargetResolved,
    selectedRoomId,
    target,
    targetReady,
    targetVersion
  ]);

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (!modal) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(
      FOCUSABLE_SELECTOR
    )].filter((element) => !element.hasAttribute("hidden"));
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1)!;
    if (
      event.shiftKey &&
      (document.activeElement === first || !event.currentTarget.contains(document.activeElement))
    ) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <aside
      aria-label="房间检查器"
      aria-modal={modal ? "true" : undefined}
      className="room-inspector"
      id="room-inspector"
      onKeyDown={handleKeyDown}
      ref={inspectorRef}
      role={modal ? "dialog" : undefined}
    >
      <header>
        <div><span>xmuse</span><strong>工作台</strong></div>
        <button
          aria-label="关闭检查器"
          className="room-icon-button"
          onClick={onClose}
          ref={closeRef}
          type="button"
        ><X size={17} /></button>
      </header>
      <div className="workspace-dock-tabs" role="tablist" aria-label="工作台视图">
        {(["agent", "room", "runtime"] as const).map((tab) => (
          <button
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "is-active" : ""}
            key={tab}
            onClick={() => onTabChange(tab)}
            role="tab"
            type="button"
          >{{ agent: "Agent", room: "Room", runtime: "Runtime" }[tab]}</button>
        ))}
      </div>
      <div className="workspace-dock-content" role="tabpanel">
        {activeTab === "agent" ? agentConsoleSection : null}
        {activeTab === "room" ? <>{executionSection}{memorySection}{roomEvidenceSection}</> : null}
        {activeTab === "runtime" ? operationsSection : null}
      </div>
    </aside>
  );
}
