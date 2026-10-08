/**
 * Board view model: maps contract values onto the trust track and the room-level summary.
 * Every rule here reads room_board_projection/v2 (§3.10, §3.11, §4) and never derives
 * completion from anything but `accepted` (§4.4).
 */
import { boardAttentionReasonLabel, boardStateLabel } from "@/lib/board-labels";
import { boardIntegrationSecondaryText } from "@/lib/board-integration-labels";
import type { BoardAttentionItem, BoardCapabilities, BoardModule, RoomBoardProjection, RoomBoardSummary } from "@/lib/board-types";

export type StepTone = "empty" | "progress" | "claim" | "running" | "wait" | "pass" | "fail" | "attn";
export type StepAxis = "claim" | "verify" | "review" | "integrate";

export type TrustStep = {
  axis: StepAxis;
  tone: StepTone;
  label: string;
  /** Short secondary fact (trusted values only, never AgentText). */
  detail: string | null;
};

export const AXIS_LABELS: Record<StepAxis, string> = {
  claim: "声明",
  verify: "宿主验证",
  review: "复核",
  integrate: "集成"
};

function claimStep(module: BoardModule): TrustStep {
  const step = (tone: StepTone, label: string): TrustStep => ({ axis: "claim", tone, label, detail: null });
  switch (module.lifecycle) {
    case "assigned": return step("empty", "已分配");
    case "claimed": return step("empty", "已认领");
    case "working": return step("progress", "进行中");
    case "blocked": return step("attn", "已阻塞");
    case "ready_for_review": return step("progress", "待评审");
    case "done_claimed": return step("claim", "自称完成");
    default: return step("empty", "未知");
  }
}

function verifyStep(module: BoardModule): TrustStep {
  const { verification } = module;
  const step = (tone: StepTone, label: string, detail: string | null = null): TrustStep => ({ axis: "verify", tone, label, detail });
  switch (verification.status) {
    case "none": return step("empty", "未验证");
    case "waiting_for_provider": return step("wait", "等待上游");
    case "pending": return step("running", "等待验证");
    case "running": return step("running", "验证中");
    case "passed": {
      // `rework_rounds` is the contract's own count of failed rounds before the first pass (§6).
      const rounds = module.counters.rework_rounds;
      return step("pass", "已通过", rounds > 0 ? `返工 ${rounds} 次后通过` : null);
    }
    case "failed": {
      const gates = verification.gate_ids.length ? `门禁 ${verification.gate_ids.join("、")}` : null;
      const escalated = verification.escalated ? "已升级给 lead" : null;
      return step("fail", "未通过", [gates, escalated].filter(Boolean).join(" · ") || null);
    }
    case "error": return step("attn", "验证异常");
    default: return step("empty", "未知");
  }
}

function reviewStep(module: BoardModule, reviewerName: (participantId: string | null) => string | null): TrustStep {
  const { review } = module;
  const step = (tone: StepTone, label: string, detail: string | null = null): TrustStep => ({ axis: "review", tone, label, detail });
  switch (review.status) {
    case "pending":
      if (review.reviewer_kind === "operator") return step("attn", "待你复核");
      return step("running", "待复核", reviewerName(review.reviewer_participant_id));
    case "endorsed": return step("pass", "已背书", reviewerName(review.reviewer_participant_id));
    case "objected": return step("fail", "已驳回", reviewerName(review.reviewer_participant_id));
    case "none":
      return step("empty", module.verification.status === "passed" ? "未开始" : "等验证通过");
    default: return step("empty", "未知");
  }
}

function integrateStep(module: BoardModule): TrustStep {
  const { integration } = module;
  const secondary = boardIntegrationSecondaryText(integration);
  const step = (tone: StepTone, label: string, detail: string | null = secondary): TrustStep => ({ axis: "integrate", tone, label, detail });
  switch (integration.status) {
    case "none": return step("empty", module.accepted ? "等待排队" : "未集成", null);
    case "waiting": return step("wait", "等待依赖");
    case "pending": return step("running", "排队集成");
    case "running": return step("running", "集成中");
    case "integrated": return step("pass", "已集成");
    case "conflicted": {
      const paths = integration.conflict_path_count ? `${integration.conflict_path_count} 个路径冲突` : null;
      return step("fail", "冲突", [paths, secondary].filter(Boolean).join(" · ") || null);
    }
    case "gate_failed": return step("fail", "门禁失败 · 嫌疑");
    case "error": return step("attn", "集成异常");
    default: return step("empty", "未知", null);
  }
}

/** The visible axes: review and integration appear only when the room has that capability. */
export function trustSteps(
  module: BoardModule,
  capabilities: BoardCapabilities,
  reviewerName: (participantId: string | null) => string | null = () => null
): TrustStep[] {
  const steps = [claimStep(module), verifyStep(module)];
  if (capabilities.reviews === 1) steps.push(reviewStep(module, reviewerName));
  if (capabilities.integrations === 1) steps.push(integrateStep(module));
  return steps;
}

export type TrustLevel = "integrated" | "accepted" | "verified" | "claimed" | "working" | "failed" | "idle";

/** Integrated means accepted AND the green head holds the current verification (§3.11). */
export function isIntegratedAtCurrent(module: BoardModule): boolean {
  return module.accepted
    && module.integration.integrated_verification_id !== null
    && module.integration.integrated_verification_id === module.verification.verification_id;
}

export function trustLevel(module: BoardModule): TrustLevel {
  if (module.accepted) return isIntegratedAtCurrent(module) ? "integrated" : "accepted";
  switch (module.state) {
    case "verification_failed":
    case "verification_error": return "failed";
    case "verified": return "verified";
    case "done_claimed":
    case "verifying":
    case "waiting_for_provider": return "claimed";
    case "claimed":
    case "working":
    case "blocked":
    case "ready_for_review": return "working";
    default: return "idle";
  }
}

export const TRUST_ORDER: TrustLevel[] = ["integrated", "accepted", "verified", "claimed", "working", "failed", "idle"];

export const TRUST_LABELS: Record<TrustLevel, string> = {
  integrated: "已集成",
  accepted: "已验收",
  verified: "已验证 · 待复核结论",
  claimed: "自称完成 · 未验证",
  working: "进行中",
  failed: "验证未通过",
  idle: "未开始"
};

export type ModulePhrase = { text: string; tone: "attn" | "proof" | "fail" | "neutral"; who: string | null };

const WHO: Record<string, string> = { operator: "需要你", lead: "等 Lead", owner: "等 Owner" };

/**
 * One-line status for a module row: who must act first, otherwise the next fact after the
 * completion mark. An accepted module already carries the 已验收 badge, so its phrase says
 * where the code stands in the integration branch instead of repeating the word.
 */
export function modulePhrase(module: BoardModule, capabilities?: BoardCapabilities): ModulePhrase {
  const kind = module.attention.kind;
  if (kind !== "none" && module.attention.reason_code) {
    return {
      text: boardAttentionReasonLabel(module.attention.reason_code),
      tone: kind === "operator" ? "attn" : "neutral",
      who: WHO[kind] ?? "待处理"
    };
  }
  if (module.accepted) {
    if (capabilities?.integrations !== 1) {
      return { text: capabilities?.reviews === 1 ? "宿主验证通过，复核已背书" : "宿主验证通过", tone: "proof", who: null };
    }
    if (isIntegratedAtCurrent(module)) return { text: "已进入集成分支", tone: "proof", who: null };
    const step = integrateStep(module);
    const text = step.detail ? `${step.label} · ${step.detail}` : step.label;
    return { text: `集成：${text}`, tone: step.tone === "fail" ? "fail" : "neutral", who: null };
  }
  const level = trustLevel(module);
  if (level === "failed") return { text: boardStateLabel(module.state), tone: "fail", who: null };
  if (level === "verified") {
    return { text: module.review.status === "objected" ? "已验证 · 复核已驳回" : "已验证 · 等复核结论", tone: "neutral", who: null };
  }
  return { text: boardStateLabel(module.state), tone: "neutral", who: null };
}

export type BoardOverview = {
  total: number;
  accepted: number;
  integrated: number;
  levels: Record<TrustLevel, number>;
  /** Module ids in display order of the segmented bar. */
  segments: Array<{ moduleId: string; level: TrustLevel }>;
};

/**
 * Room-level numbers. `accepted` and `integrated` come from the summary when present, so
 * every consumer shows the server's counts; the bar segments need the projection.
 */
export function boardOverview(projection: RoomBoardProjection | null, summary: RoomBoardSummary | null): BoardOverview {
  const levels = Object.fromEntries(TRUST_ORDER.map((level) => [level, 0])) as Record<TrustLevel, number>;
  const modules = projection?.modules ?? [];
  const segments = modules
    .map((module) => ({ moduleId: module.module_id, level: trustLevel(module) }))
    .sort((left, right) => TRUST_ORDER.indexOf(left.level) - TRUST_ORDER.indexOf(right.level) || left.moduleId.localeCompare(right.moduleId));
  for (const segment of segments) levels[segment.level] += 1;
  return {
    total: summary?.modules_total ?? modules.length,
    accepted: summary?.accepted_total ?? modules.filter((module) => module.accepted).length,
    integrated: summary?.integrated_total ?? modules.filter(isIntegratedAtCurrent).length,
    levels,
    segments
  };
}

/** Attention split by who must act (§3.8): only `operator` is the human's. */
export function splitAttention(items: BoardAttentionItem[]): { mine: BoardAttentionItem[]; agents: BoardAttentionItem[] } {
  const mine: BoardAttentionItem[] = [];
  const agents: BoardAttentionItem[] = [];
  for (const item of items) (item.kind === "operator" ? mine : agents).push(item);
  return { mine, agents };
}

/** Whether a room shows the board at all: the host verifies, or there is board state. */
export function boardVisible(projection: RoomBoardProjection | null, summary: RoomBoardSummary | null): boolean {
  if (projection) return projection.capabilities.verification === 1 || projection.modules.length > 0 || projection.splits.length > 0;
  if (summary) return summary.capabilities.verification === 1 || summary.modules_total > 0;
  return false;
}
