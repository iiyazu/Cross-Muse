import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { normalizeRoomOperationsProjection } from "@/lib/room-view";
import { RoomRuntimeDomain } from "./room-runtime-domain";

function operations(overall: "healthy" | "attention") {
  return normalizeRoomOperationsProjection({
    schema_version: "room_operations_projection/v2",
    overall,
    runtime: {
      runner: { state: "healthy", code: "ready" },
      mcp: { state: "healthy", code: "ready" },
      host: { state: overall, code: overall === "healthy" ? "ready" : "cleanup", active_delivery_count: 0, retained_cleanup_count: 0 },
      memory: { enabled: true, state: "ready", code: "ready", consecutive_restart_count: 0, next_retry_at: null, last_healthy_at: null }
    },
    counts: { active_delivery: 0, retained_cleanup: 0, recovery_pending: 0, cancel_pending: 0, provider_cleanup_pending: 0, exhausted: 0 },
    incident_total: 0,
    incidents: [],
    actions: {
      recover_runtime: { available: false, method: "POST", href: "/api/chat/operator/room-runtime/recover", expected_incident_id: "", mode: "restart", confirmation_required: true },
      rebuild_memory_index: { available: false, pending: false, status: null, phase: null, method: "POST", href: "/api/chat/operator/memory-runtime/rebuild", expected_incident_id: null, confirmation_required: true }
    }
  });
}

describe("RoomRuntimeDomain progressive disclosure", () => {
  it("collapses healthy component details and opens them when attention is required", () => {
    const props = {
      operationsError: null,
      operationsLoading: false,
      recoverPending: false,
      recoverError: null,
      selectedRoomId: "conv-1",
      onIncidentAction: vi.fn(),
      onRecover: vi.fn()
    };
    const view = render(<RoomRuntimeDomain {...props} operations={operations("healthy")} />);
    expect(screen.getByText("组件状态与运行计数").closest("details")).not.toHaveAttribute("open");

    view.rerender(<RoomRuntimeDomain {...props} operations={operations("attention")} />);
    expect(screen.getByText("组件状态与运行计数").closest("details")).toHaveAttribute("open");
  });
});
