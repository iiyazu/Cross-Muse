import type { PluginGrantStatus } from "./grant-types";

type GrantStatusMeta = {
  text: string;
  glyph: string;
};

/**
 * Status chips always render glyph + text, never colour alone. An unrecognized
 * status is treated as expired behaviourally and shown as "未知状态".
 */
const GRANT_STATUS_META: Record<PluginGrantStatus, GrantStatusMeta> = {
  pending: { text: "待配对", glyph: "◌" },
  active: { text: "已授权", glyph: "●" },
  expired: { text: "已过期", glyph: "○" },
  revoked: { text: "已撤销", glyph: "✕" },
  unknown: { text: "未知状态", glyph: "?" }
};

export function grantStatusText(status: PluginGrantStatus): string {
  return GRANT_STATUS_META[status]?.text ?? GRANT_STATUS_META.unknown.text;
}

export function grantStatusGlyph(status: PluginGrantStatus): string {
  return GRANT_STATUS_META[status]?.glyph ?? GRANT_STATUS_META.unknown.glyph;
}

/** A grant with an unrecognized status behaves like an expired one. */
export function grantIsLive(status: PluginGrantStatus): boolean {
  return status === "pending" || status === "active";
}

export function grantHostLabel(host: string): string {
  if (host === "claude-code") return "Claude Code";
  if (host === "opencode") return "OpenCode";
  return host;
}

const GRANT_ERROR_TEXTS: Record<string, string> = {
  plugin_grant_request_invalid: "请求无效",
  plugin_grant_scope_invalid: "范围无效",
  plugin_grant_host_invalid: "宿主无效",
  room_conversation_unknown: "房间不存在",
  plugin_grant_unknown: "授权不存在或不属于此房间"
};

const OPERATOR_TOKEN_MISSING_TEXT = "服务端未配置 operator 令牌，无法签发授权";

/**
 * Maps an error `code` (never the server `message`) to inline Chinese text.
 * Unknown codes fall back to a generic notice; the caller renders the code.
 */
export function grantErrorText(code: string, status: number): string {
  if (status === 503) return OPERATOR_TOKEN_MISSING_TEXT;
  return GRANT_ERROR_TEXTS[code] ?? "操作失败，请重试";
}

/** Whether the caller must also render the raw code next to the generic notice. */
export function grantErrorShowsCode(code: string, status: number): boolean {
  if (status === 503) return false;
  return !(code in GRANT_ERROR_TEXTS);
}

function clampNonNegative(value: number): number {
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

/** Remaining time until `expiresAt`, evaluated against `nowMs`. */
export function grantRemainingText(expiresAt: string, nowMs: number): string {
  const remainingMs = Date.parse(expiresAt) - nowMs;
  if (!Number.isFinite(remainingMs) || remainingMs <= 0) return "已过期";
  const totalSeconds = clampNonNegative(remainingMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `剩余 ${hours} 小时 ${minutes} 分`;
  if (minutes > 0) return `剩余 ${minutes} 分 ${seconds} 秒`;
  return `剩余 ${seconds} 秒`;
}

export function grantTtlLabel(ttlSeconds: number): string {
  return `${Math.round(ttlSeconds / 60)} 分钟`;
}

/** Relative `last_used_at`; null means the grant was never used. */
export function grantLastUsedText(lastUsedAt: string | null, nowMs: number): string {
  if (lastUsedAt === null) return "从未使用";
  const diffMs = nowMs - Date.parse(lastUsedAt);
  if (!Number.isFinite(diffMs) || diffMs < 0) return "刚刚";
  const totalSeconds = clampNonNegative(diffMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds} 秒前`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${totalMinutes} 分钟前`;
  const totalHours = Math.floor(totalMinutes / 60);
  if (totalHours < 24) return `${totalHours} 小时前`;
  return `${Math.floor(totalHours / 24)} 天前`;
}

export function grantUseCountText(useCount: number): string {
  return `使用 ${clampNonNegative(useCount)} 次`;
}
