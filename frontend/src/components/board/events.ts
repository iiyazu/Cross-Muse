/**
 * Board event lines (§3.7). Event `data` arrives as a raw whitelist object, so every
 * agent-authored field is re-sanitized and wrapped as AgentText here before rendering.
 */
import { sanitizeAgentTextValue } from "@/lib/board-api";
import { boardContractKindLabel, boardDecidedViaLabel, boardEventKindLabel, boardReasonLabel } from "@/lib/board-labels";
import { boardIntegrationJobStatusLabel } from "@/lib/board-integration-labels";
import { boardReviewVerdictLabel } from "@/lib/board-review-labels";
import type { AgentText, BoardEvent } from "@/lib/board-types";

import type { StepTone } from "./model";

export function eventAgentText(value: unknown): AgentText | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (typeof record.text !== "string" || !record.text) return null;
  return { text: sanitizeAgentTextValue(record.text), untrusted: true, truncated: record.truncated === true };
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

const PROGRESS_STATUS: Record<string, string> = {
  working: "进行中",
  blocked: "已阻塞",
  ready_for_review: "待评审",
  done: "自称完成"
};

export type EventLine = {
  title: string;
  tone: StepTone;
  /** Who acted: a participant id, or the host / the operator. */
  actor: { kind: "participant"; participantId: string | null } | { kind: "infrastructure" } | { kind: "operator" };
  quote: AgentText | null;
  extras: AgentText[];
  extrasTotal: number;
  facts: string[];
};

export function eventLine(event: BoardEvent, name: (participantId: string | null) => string): EventLine {
  const data = event.data;
  const actor: EventLine["actor"] = event.actor.kind === "infrastructure"
    ? { kind: "infrastructure" }
    : event.actor.kind === "operator"
      ? { kind: "operator" }
      : { kind: "participant", participantId: event.actor.participant_id };
  const base: EventLine = { title: boardEventKindLabel(event.kind), tone: "empty", actor, quote: null, extras: [], extrasTotal: 0, facts: [] };
  const via = boardDecidedViaLabel(str(data.decided_via));

  switch (event.kind) {
    case "split_proposed":
      return { ...base, title: `提议拆分为 ${strings(data.module_ids).length} 个模块`, tone: "attn" };
    case "split_rejected":
      return { ...base, title: "拆分被驳回", tone: "fail", facts: via ? [`经由${via}`] : [] };
    case "charter_assigned":
      return {
        ...base,
        title: `章程 v${typeof data.charter_version === "number" ? data.charter_version : "?"} 分配给 ${name(str(data.owner_participant_id))}`,
        tone: "progress",
        facts: via ? [`经由${via}`] : []
      };
    case "claimed":
      return { ...base, title: "认领了模块", tone: "progress" };
    case "contract_published":
    case "contract_revised": {
      const contract = str(data.contract_id) ?? "契约";
      const version = typeof data.version === "number" ? ` v${data.version}` : "";
      return {
        ...base,
        title: `${event.kind === "contract_revised" ? "修订" : "发布"}契约 ${contract}${version}`,
        tone: "progress",
        quote: eventAgentText(data.rationale),
        facts: str(data.kind) ? [boardContractKindLabel(String(data.kind))] : []
      };
    }
    case "progress": {
      const status = str(data.status);
      const claims = Array.isArray(data.claims) ? data.claims.map(eventAgentText).filter((item): item is AgentText => Boolean(item)) : [];
      return {
        ...base,
        title: `进展：${status ? PROGRESS_STATUS[status] ?? status : "更新"}`,
        tone: status === "done" ? "claim" : status === "blocked" ? "attn" : "progress",
        quote: eventAgentText(data.summary),
        extras: claims,
        extrasTotal: typeof data.claims_total === "number" ? data.claims_total : claims.length
      };
    }
    case "question":
      return { ...base, title: `向 ${name(str(data.target_participant_id))} 提问`, tone: "progress", quote: eventAgentText(data.question) };
    case "verification": {
      const status = str(data.status);
      const gates = strings(data.gate_ids);
      const facts = [
        status !== "passed" && str(data.reason_code) ? boardReasonLabel(str(data.reason_code)) : null,
        gates.length ? `门禁 ${gates.join("、")}` : null,
        data.escalated === true ? "已升级给 lead" : null
      ].filter((item): item is string => Boolean(item));
      return {
        ...base,
        title: status === "passed" ? "宿主验证通过" : status === "failed" ? "宿主验证未通过" : "宿主验证异常",
        tone: status === "passed" ? "pass" : status === "failed" ? "fail" : "attn",
        facts
      };
    }
    case "review_requested": {
      const operator = str(data.reviewer_kind) === "operator";
      const escalated = data.escalated_from && typeof data.escalated_from === "object";
      return {
        ...base,
        title: operator ? (escalated ? "复核转交给你" : "请你复核") : `请 ${name(str(data.reviewer_participant_id))} 复核`,
        tone: operator ? "attn" : "running",
        facts: [str(data.rule_id), escalated ? boardReasonLabel(str((data.escalated_from as Record<string, unknown>).reason_code)) : null]
          .filter((item): item is string => Boolean(item))
      };
    }
    case "review": {
      const verdict = str(data.verdict);
      return {
        ...base,
        title: `复核结论：${verdict ? boardReviewVerdictLabel(verdict) : "?"}`,
        tone: verdict === "endorse" ? "pass" : "fail",
        quote: eventAgentText(data.summary),
        facts: typeof data.findings_total === "number" && data.findings_total ? [`${data.findings_total} 条意见`] : []
      };
    }
    case "integration": {
      const status = str(data.status) ?? "unknown";
      const integrated = strings(data.integrated_module_ids);
      const suspects = strings(data.suspect_module_ids);
      const conflicts = Array.isArray(data.conflicts) ? data.conflicts.length : 0;
      const facts = [
        integrated.length ? `已集成 ${integrated.join("、")}` : null,
        conflicts ? `${conflicts} 个模块冲突` : null,
        suspects.length ? `嫌疑 ${suspects.join("、")}` : null
      ].filter((item): item is string => Boolean(item));
      return {
        ...base,
        title: `集成：${boardIntegrationJobStatusLabel(status)}`,
        tone: status === "integrated" ? "pass" : status === "error" ? "attn" : "fail",
        facts
      };
    }
    default:
      return base;
  }
}
