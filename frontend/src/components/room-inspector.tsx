"use client";

import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode
} from "react";

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
  operationsSection: ReactNode;
  executionSection: ReactNode;
  memorySection: ReactNode;
  roomEvidenceSection: ReactNode;
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
  operationsSection,
  executionSection,
  memorySection,
  roomEvidenceSection,
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
        <div><span>Room inspector</span><strong>成员与因果状态</strong></div>
        <button
          aria-label="关闭检查器"
          className="room-icon-button"
          onClick={onClose}
          ref={closeRef}
          type="button"
        >×</button>
      </header>
      {operationsSection}
      {executionSection}
      {memorySection}
      {roomEvidenceSection}
    </aside>
  );
}
