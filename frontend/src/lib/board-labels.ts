import type {
  BoardAttentionKind,
  BoardContractKind,
  BoardEventKind,
  BoardLifecycle,
  BoardSplitStatus,
  BoardState,
  BoardVerificationStatus
} from "./board-types";

export const BOARD_STATE_LABELS: Record<BoardState, string> = {
  verified: "已验证",
  done_claimed: "自称完成 · 未验证",
  verifying: "验证中",
  waiting_for_provider: "等待上游模块通过验证",
  verification_failed: "验证失败",
  verification_error: "验证异常",
  assigned: "已分配",
  claimed: "已认领",
  working: "进行中",
  blocked: "已阻塞",
  ready_for_review: "待评审",
  unknown: "未知状态"
};

export const BOARD_LIFECYCLE_LABELS: Record<BoardLifecycle, string> = {
  assigned: "已分配",
  claimed: "已认领",
  working: "进行中",
  blocked: "已阻塞",
  ready_for_review: "待评审",
  done_claimed: "自称完成",
  unknown: "未知"
};

export const BOARD_VERIFICATION_STATUS_LABELS: Record<BoardVerificationStatus, string> = {
  none: "未验证",
  waiting_for_provider: "等待上游",
  pending: "等待验证",
  running: "验证中",
  passed: "已通过",
  failed: "未通过",
  error: "异常",
  unknown: "未知"
};

export const BOARD_SPLIT_STATUS_LABELS: Record<BoardSplitStatus, string> = {
  proposed: "待审批",
  approved: "已批准",
  rejected: "已驳回",
  superseded: "已取代",
  unknown: "未知状态"
};

export const BOARD_CONTRACT_KIND_LABELS: Record<BoardContractKind, string> = {
  api_schema: "接口契约",
  types: "类型契约",
  protocol: "协议契约",
  text: "文本契约",
  unknown: "未知类型"
};

export const BOARD_ATTENTION_KIND_LABELS: Record<string, string> = {
  operator: "需要你处理",
  lead: "Lead 待处理",
  owner: "Owner 待跟进"
};

const ATTENTION_REASON_LABELS: Record<string, string> = {
  board_attention_split_pending: "待审批拆分",
  board_attention_verification_error: "验证异常需人工介入",
  board_attention_verification_escalated: "验证失败已升级",
  board_attention_verification_failed: "验证失败待返工",
  board_attention_review_operator_pending: "待你复核",
  board_attention_review_objected: "复核被驳回待返工",
  board_attention_module_blocked: "模块已阻塞",
  board_attention_contract_stale: "契约已修订待跟进"
};

const REASON_CODE_LABELS: Record<string, string> = {
  ...ATTENTION_REASON_LABELS,
  board_verification_gate_failed: "门禁未通过",
  board_verification_outside_charter: "超出章程范围",
  board_verification_waiting_for_provider: "等待上游模块",
  board_verification_dependency_overlap: "依赖重叠",
  board_verification_base_mismatch: "基线不一致",
  board_verification_provider_patch_missing: "上游补丁缺失",
  board_verification_charter_unknown: "章程未知",
  board_verification_evidence_unavailable: "验证证据缺失",
  board_verification_attempts_exhausted: "验证次数耗尽",
  owner_patch_empty: "补丁为空",
  owner_patch_binary: "补丁含二进制",
  owner_patch_reserved_path: "补丁含保留路径",
  owner_patch_too_large: "补丁过大",
  owner_patch_too_many_files: "补丁文件过多",
  owner_patch_fetch_failed: "补丁获取失败",
  owner_clone_missing: "克隆缺失",
  owner_clone_metadata_invalid: "克隆元数据无效",
  room_board_split_dependency_cycle: "拆分依赖成环",
  room_conversation_unknown: "房间未知",
  room_board_contract_unknown: "契约未知",
  room_board_version_invalid: "契约版本无效",
  room_board_split_digest_mismatch: "拆分摘要不一致",
  room_board_split_decided: "拆分已经决策",
  room_board_split_not_proposed: "拆分不在待审批状态",
  room_board_query_invalid: "查询无效",
  room_board_decided_via_invalid: "决策来源无效"
};

export const BOARD_EVENT_KIND_LABELS: Record<BoardEventKind, string> = {
  split_proposed: "提议拆分",
  split_rejected: "驳回拆分",
  charter_assigned: "分配章程",
  claimed: "已认领",
  contract_published: "发布契约",
  contract_revised: "修订契约",
  progress: "进展报告",
  question: "提问",
  verification: "验证结果",
  unknown: "未知事件"
};

export function boardStateLabel(state: string): string {
  return BOARD_STATE_LABELS[state as BoardState] ?? BOARD_STATE_LABELS.unknown;
}

export function boardLifecycleLabel(lifecycle: string): string {
  return BOARD_LIFECYCLE_LABELS[lifecycle as BoardLifecycle] ?? BOARD_LIFECYCLE_LABELS.unknown;
}

export function boardVerificationStatusLabel(status: string): string {
  return (
    BOARD_VERIFICATION_STATUS_LABELS[status as BoardVerificationStatus] ??
    BOARD_VERIFICATION_STATUS_LABELS.unknown
  );
}

export function boardSplitStatusLabel(status: string): string {
  return BOARD_SPLIT_STATUS_LABELS[status as BoardSplitStatus] ?? BOARD_SPLIT_STATUS_LABELS.unknown;
}

/** Decision provenance (§8): web | cli | plugin:<host> | null (hide). */
export function boardDecidedViaLabel(decidedVia: string | null | undefined): string | null {
  if (!decidedVia) return null;
  if (decidedVia === "web") return "网页";
  if (decidedVia === "cli") return "命令行";
  if (decidedVia.startsWith("plugin:")) {
    const host = decidedVia.slice("plugin:".length);
    return host ? `插件（${host}）` : "插件";
  }
  return `未知来源（${decidedVia}）`;
}

export function boardContractKindLabel(kind: string): string {
  return BOARD_CONTRACT_KIND_LABELS[kind as BoardContractKind] ?? BOARD_CONTRACT_KIND_LABELS.unknown;
}

export function boardAttentionKindLabel(kind: string): string {
  return BOARD_ATTENTION_KIND_LABELS[kind] ?? "待处理";
}

export function boardAttentionKindOf(item: { kind: string }): BoardAttentionKind {
  if (item.kind === "operator" || item.kind === "lead" || item.kind === "owner" || item.kind === "none") {
    return item.kind;
  }
  return "unknown";
}

/** Reason-code registry (§9) plus attention codes (§3.8). Unknown codes are never hidden. */
export function boardReasonLabel(reasonCode: string | null | undefined): string {
  if (!reasonCode) return "暂无原因";
  const label = REASON_CODE_LABELS[reasonCode];
  if (label) return label;
  return `未知原因（${reasonCode}）`;
}

export function boardAttentionReasonLabel(reasonCode: string): string {
  return boardReasonLabel(reasonCode);
}

export function boardEventKindLabel(kind: string): string {
  const label = BOARD_EVENT_KIND_LABELS[kind as BoardEventKind];
  if (label && kind !== "unknown") return label;
  if (kind === "unknown") return BOARD_EVENT_KIND_LABELS.unknown;
  return `未知事件（${kind}）`;
}

export function isUnknownReasonLabel(label: string): boolean {
  return label.startsWith("未知原因（");
}
