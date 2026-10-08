import { boardReasonLabel } from "./board-labels";
import type {
  BoardIntegrationGate,
  BoardIntegrationItem,
  BoardModuleIntegration
} from "./board-integration-types";

export const BOARD_INTEGRATION_MODULE_STATUS_LABELS: Record<string, string> = {
  none: "无集成",
  waiting: "等待依赖集成",
  pending: "排队集成",
  running: "集成中",
  integrated: "已集成",
  conflicted: "集成冲突",
  gate_failed: "门禁失败",
  error: "集成异常"
};

export const BOARD_INTEGRATION_JOB_STATUS_LABELS: Record<string, string> = {
  pending: "排队",
  running: "进行中",
  integrated: "已集成",
  conflicted: "集成冲突",
  gate_failed: "门禁失败",
  error: "异常"
};

export const BOARD_INTEGRATION_ITEM_STATUS_LABELS: Record<string, string> = {
  applied: "已应用",
  fell_back: "已回退到旧版本",
  conflicted: "冲突",
  waiting: "等待依赖",
  not_applied: "未执行"
};

export const BOARD_INTEGRATION_ROLE_LABELS: Record<string, string> = {
  incumbent: "在先",
  newcomer: "新加入"
};

export const BOARD_INTEGRATION_GATE_STATUS_LABELS: Record<string, string> = {
  passed: "已通过",
  failed: "未通过",
  error: "异常",
  pending: "等待中",
  running: "运行中",
  skipped: "已跳过",
  waiting: "等待依赖"
};

function unknownLabel(raw?: string | null): string | null {
  if (raw && raw !== "unknown") return `? ${raw}`;
  return null;
}

/** Module integration status word. Unknown values degrade to `? <raw>`. */
export function boardIntegrationStatusLabel(status: string, raw?: string | null): string {
  const known = BOARD_INTEGRATION_MODULE_STATUS_LABELS[status];
  if (known) return known;
  return unknownLabel(raw ?? (status !== "unknown" ? status : null)) ?? "未知集成状态";
}

/** Latest-job status word for the room summary line. Unknown values degrade to `? <raw>`. */
export function boardIntegrationJobStatusLabel(status: string, raw?: string | null): string {
  const known = BOARD_INTEGRATION_JOB_STATUS_LABELS[status];
  if (known) return known;
  return unknownLabel(raw ?? (status !== "unknown" ? status : null)) ?? "未知集成状态";
}

/** Detail item status word (`applied` 已应用, `fell_back` 已回退到旧版本, …). */
export function boardIntegrationItemStatusLabel(status: string, raw?: string | null): string {
  const known = BOARD_INTEGRATION_ITEM_STATUS_LABELS[status];
  if (known) return known;
  return unknownLabel(raw ?? (status !== "unknown" ? status : null)) ?? "未知状态";
}

/** Detail item role word (在先 / 新加入). */
export function boardIntegrationRoleLabel(role: string, raw?: string | null): string {
  const known = BOARD_INTEGRATION_ROLE_LABELS[role];
  if (known) return known;
  return unknownLabel(raw ?? (role !== "unknown" ? role : null)) ?? "未知角色";
}

/** Detail gate status word. */
export function boardIntegrationGateStatusLabel(status: string, raw?: string | null): string {
  const known = BOARD_INTEGRATION_GATE_STATUS_LABELS[status];
  if (known) return known;
  return unknownLabel(raw ?? (status !== "unknown" ? status : null)) ?? "未知状态";
}

export function boardIntegrationChipGlyph(status: string): string {
  switch (status) {
    case "pending":
      return "◷";
    case "running":
      return "◐";
    case "integrated":
      return "✓";
    case "waiting":
      return "◔";
    case "conflicted":
      return "✕";
    case "gate_failed":
      return "■";
    case "error":
      return "⚠";
    default:
      return "?";
  }
}

/** Chip main text for the module-card integration axis. Glyph is rendered by the component. */
export function boardIntegrationChipText(
  integration: Pick<BoardModuleIntegration, "status" | "statusRaw" | "conflict_path_count">
): string {
  switch (integration.status) {
    case "pending":
      return "排队集成";
    case "running":
      return "集成中";
    case "integrated":
      return "已集成";
    case "waiting":
      return "等待依赖集成";
    case "conflicted":
      return `集成冲突 · ${integration.conflict_path_count} 个路径`;
    case "gate_failed":
      return "门禁失败 · 嫌疑";
    case "error":
      return "集成异常 · 宿主会自动重试";
    case "none":
      return "";
    default:
      return boardIntegrationStatusLabel(integration.status, integration.statusRaw);
  }
}

/**
 * Secondary chip text: what the branch holds. A module that fell back keeps its
 * older accepted version in the branch ("分支中是旧版本"); a module that never
 * entered the branch says so ("未进入集成分支").
 */
export function boardIntegrationSecondaryText(
  integration: Pick<
    BoardModuleIntegration,
    "status" | "verification_id" | "integrated_verification_id"
  >
): string | null {
  if (
    integration.integrated_verification_id !== null &&
    integration.integrated_verification_id !== integration.verification_id
  ) {
    return "分支中是旧版本";
  }
  if (
    integration.integrated_verification_id === null &&
    (integration.status === "conflicted" ||
      integration.status === "gate_failed" ||
      integration.status === "error" ||
      integration.status === "waiting")
  ) {
    return "未进入集成分支";
  }
  return null;
}

export function boardIntegrationChipTone(status: string): string {
  if (status === "integrated") return "is-integrated";
  if (status === "waiting") return "is-waiting";
  if (status === "pending" || status === "running") return "is-neutral";
  if (status === "none") return "is-muted";
  return "is-bad";
}

/** Detail item line: role word + item status word. */
export function boardIntegrationItemText(item: Pick<BoardIntegrationItem, "role" | "roleRaw" | "status" | "statusRaw">): string {
  return `${boardIntegrationRoleLabel(item.role, item.roleRaw)} · ${boardIntegrationItemStatusLabel(item.status, item.statusRaw)}`;
}

const INTEGRATION_ERROR_LABELS: Record<string, string> = {
  room_board_integration_unknown: "集成记录不存在"
};

export function boardIntegrationErrorText(code: string | null | undefined): string {
  if (!code) return "操作失败，请重试";
  const known = INTEGRATION_ERROR_LABELS[code];
  if (known) return known;
  return "操作失败，请重试";
}

export function boardIntegrationErrorShowsCode(code: string | null | undefined): boolean {
  if (!code) return true;
  return !(code in INTEGRATION_ERROR_LABELS);
}

/** Detail gate line: id is rendered separately as `<code>`; this is the status + reason part. */
export function boardIntegrationGateText(gate: Pick<BoardIntegrationGate, "status" | "statusRaw" | "reason_code">): string {
  const status = boardIntegrationGateStatusLabel(gate.status, gate.statusRaw);
  // `execution_gate_failed` only restates a failed status; other reasons add information.
  if (!gate.reason_code || (gate.reason_code === "execution_gate_failed" && gate.status === "failed")) return status;
  return `${status} · ${boardReasonLabel(gate.reason_code)}`;
}
