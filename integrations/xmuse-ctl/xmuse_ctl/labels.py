"""Fixed words for states, reviews, events and reason codes.

Every label here is a code constant. Server strings never enter this
module; callers sanitize server values before composing output lines.
"""

from __future__ import annotations

from .sanitize import safe

# Compact glyphs for the one-line status row, in fixed order.
STATUS_GROUPS: list[dict[str, str]] = [
    {"state": "verified", "glyph": "✓"},
    {"state": "done_claimed", "glyph": "◌"},
    {"state": "verifying", "glyph": "…"},
    {"state": "waiting_for_provider", "glyph": "⧗"},
    {"state": "verification_failed", "glyph": "✗"},
    {"state": "verification_error", "glyph": "‼"},
]

_BADGES: dict[str, str] = {
    "verified": "✓ 已验证",
    "done_claimed": "◌ 自称完成·未验证",
    "verification_failed": "✗",
    "verifying": "…",
    "waiting_for_provider": "⧗",
    "verification_error": "‼",
}

_PLAIN_STATES = frozenset(["assigned", "claimed", "working", "blocked", "ready_for_review"])


def display_state(state: object) -> str:
    """Badge for known states, ``?value`` for unknown ones, never hidden."""
    if isinstance(state, str) and state in _BADGES:
        return _BADGES[state]
    if isinstance(state, str) and state in _PLAIN_STATES:
        return safe(state, 48)
    return "?" + safe(state, 48)


# The one completion mark: shown only when accepted is true, never for
# a merely verified module.
ACCEPTED_BADGE = "✓ 已验收"


def review_status_word(status: object, reviewer_kind: object) -> str:
    """One fixed word per review state; empty when there is no review."""
    if status == "none":
        return ""
    if status == "pending":
        return "待你复核" if reviewer_kind == "operator" else "待复核"
    if status == "endorsed":
        return "已背书"
    if status == "objected":
        return "已驳回"
    return "?" + safe(status, 48)


def findings_part(blocker: int, major: int, minor: int) -> str:
    """Finding counts; empty when all are zero."""
    try:
        counts = (max(0, int(blocker)), max(0, int(major)), max(0, int(minor)))
    except (TypeError, ValueError):
        return ""
    if counts[0] + counts[1] + counts[2] == 0:
        return ""
    return "阻塞 " + str(counts[0]) + " 主要 " + str(counts[1]) + " 次要 " + str(counts[2])


ATTENTION_REASON_LABELS: dict[str, str] = {
    "board_attention_split_pending": "待审批拆分",
    "board_attention_verification_error": "验证异常需人工介入",
    "board_attention_verification_escalated": "验证失败已升级",
    "board_attention_verification_failed": "验证失败待返工",
    "board_attention_review_operator_pending": "待你复核",
    "board_attention_review_objected": "复核被驳回待返工",
    "board_attention_integration_error": "集成异常（宿主自动重试）",
    "board_attention_integration_conflict": "集成冲突待处理",
    "board_attention_integration_gate_failed": "集成门禁失败",
    "board_attention_module_blocked": "模块已阻塞",
    "board_attention_contract_stale": "契约已修订待跟进",
}

# Fixed words for the board_integration_* reason codes (§9). Copied
# exactly from frontend/src/lib/board-labels.ts.
INTEGRATION_REASON_LABELS: dict[str, str] = {
    "board_integration_conflict": "集成冲突",
    "board_integration_gate_failed": "集成门禁未通过",
    "board_integration_waiting_for_dependency": "等待依赖集成",
    "board_integration_would_drop_accepted": "集成会丢失已验收代码，已停止",
    "board_integration_attempts_exhausted": "集成多次失败",
}

# Extra structured reason codes the watch summaries may cite.
_REASON_LABELS: dict[str, str] = {
    **ATTENTION_REASON_LABELS,
    **INTEGRATION_REASON_LABELS,
    "board_verification_gate_failed": "门禁未通过",
    "board_verification_outside_charter": "超出章程范围",
    "board_verification_waiting_for_provider": "等待上游模块",
    "board_verification_dependency_overlap": "依赖重叠",
    "board_verification_base_mismatch": "基线不一致",
    "board_verification_provider_patch_missing": "上游补丁缺失",
    "board_verification_charter_unknown": "章程未知",
    "board_verification_evidence_unavailable": "验证证据缺失",
    "board_verification_attempts_exhausted": "验证次数耗尽",
    "board_review_reviewer_unavailable": "复核人不可用",
    "board_review_reviewer_no_verdict": "复核人未给出结论",
    "board_review_reviewer_unresponsive": "复核人无响应",
}


def reason_label(reason_code: object) -> str:
    """Fixed word for a reason code; unknown codes are never hidden."""
    if not isinstance(reason_code, str) or reason_code == "":
        return ""
    known = _REASON_LABELS.get(reason_code)
    if known is not None:
        return known
    return "未知原因（" + safe(reason_code, 64) + "）"


_EVENT_KIND_LABELS: dict[str, str] = {
    "split_proposed": "提议拆分",
    "split_rejected": "驳回拆分",
    "charter_assigned": "分配章程",
    "claimed": "已认领",
    "contract_published": "发布契约",
    "contract_revised": "修订契约",
    "progress": "进展报告",
    "question": "提问",
    "verification": "验证结果",
    "review_requested": "请求复核",
    "review": "复核结论",
    "integration": "集成结果",
}


def event_kind_label(kind: object) -> str:
    """Fixed word for an event kind; unknown kinds are never hidden."""
    if isinstance(kind, str) and kind in _EVENT_KIND_LABELS:
        return _EVENT_KIND_LABELS[kind]
    return "未知事件（" + safe(kind, 48) + "）"


_PROGRESS_LABELS: dict[str, str] = {
    "working": "进行中",
    "blocked": "已阻塞",
    "ready_for_review": "待评审",
    "done": "自称完成",
}


def progress_status_word(status: object) -> str:
    """Fixed word for a progress status; unknown values stay visible."""
    if isinstance(status, str) and status in _PROGRESS_LABELS:
        return _PROGRESS_LABELS[status]
    return "?" + safe(status, 48)


_VERIFICATION_RESULT_LABELS: dict[str, str] = {
    "passed": "已通过",
    "failed": "未通过",
    "error": "异常",
}


def verification_result_word(status: object) -> str:
    """Fixed word for a verification result; unknown values stay visible."""
    if isinstance(status, str) and status in _VERIFICATION_RESULT_LABELS:
        return _VERIFICATION_RESULT_LABELS[status]
    return "?" + safe(status, 48)


_VERDICT_LABELS: dict[str, str] = {"endorse": "已背书", "object": "已驳回"}


def verdict_word(verdict: object) -> str:
    """Fixed word for a review verdict; unknown values stay visible."""
    if isinstance(verdict, str) and verdict in _VERDICT_LABELS:
        return _VERDICT_LABELS[verdict]
    return "?" + safe(verdict, 48)


_CONTRACT_KIND_LABELS: dict[str, str] = {
    "api_schema": "接口契约",
    "types": "类型契约",
    "protocol": "协议契约",
    "text": "文本契约",
}


def contract_kind_label(kind: object) -> str:
    """Fixed word for a contract kind; unknown values stay visible."""
    if isinstance(kind, str) and kind in _CONTRACT_KIND_LABELS:
        return _CONTRACT_KIND_LABELS[kind]
    return "?" + safe(kind, 48)


def decided_via_label(decided_via: object) -> str:
    """Fixed word for decision provenance; empty when absent."""
    if decided_via is None:
        return ""
    if decided_via == "web":
        return "网页"
    if decided_via == "cli":
        return "命令行"
    if decided_via == "board_tool":
        return "房间工具"
    if isinstance(decided_via, str) and decided_via.startswith("plugin:"):
        host = decided_via[len("plugin:") :]
        return "插件（" + safe(host, 24) + "）" if host != "" else "插件"
    return "?" + safe(decided_via, 48)


_ATTENTION_MARKS: dict[str, str] = {"operator": "!", "lead": "*", "owner": "-"}


def attention_mark(kind: object) -> str:
    """One fixed mark per attention kind."""
    if isinstance(kind, str) and kind in _ATTENTION_MARKS:
        return _ATTENTION_MARKS[kind]
    return "?"


def integration_job_word(status: object) -> str:
    """Room-level job word (§3.11, §7.1); empty when integrated or absent."""
    if status is None or status == "" or status == "integrated":
        return ""
    if status == "pending":
        return "排队集成"
    if status == "running":
        return "集成中"
    if status == "conflicted":
        return "集成冲突"
    if status == "gate_failed":
        return "集成门禁失败"
    if status == "error":
        return "集成异常"
    return "?" + safe(status, 32)


def short_green_head(commit: object) -> str:
    """8 hex of the green head commit; empty when there is no head."""
    if not isinstance(commit, str) or commit == "":
        return ""
    return safe(commit, 64)[:8]


def integration_module_word(
    integration: object,
    integrations_flag: object,
) -> str:
    """One fixed-word module integration part (§3.11).

    Empty when integrations are off, when the status is ``none``/missing,
    or when the shape is bad. Counts and ids only: never a path.
    """
    if integrations_flag != 1:
        return ""
    if not isinstance(integration, dict):
        return ""
    status = integration.get("status")
    if not isinstance(status, str) or status == "" or status == "none":
        return ""
    if status == "pending":
        base = "排队集成"
    elif status == "running":
        base = "集成中"
    elif status == "integrated":
        base = "已集成"
    elif status == "waiting":
        base = "等待依赖集成"
    elif status == "conflicted":
        raw = integration.get("conflict_path_count")
        count = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
        if isinstance(raw, float):
            try:
                count = max(0, int(raw))
            except (TypeError, ValueError):
                count = 0
        count = max(0, int(count)) if isinstance(count, int) else 0
        base = "集成冲突 " + str(count) + " 路径"
    elif status == "gate_failed":
        base = "门禁失败·嫌疑"
    elif status == "error":
        base = "集成异常·自动重试"
    else:
        return "?" + safe(status, 32)
    verification_id = integration.get("verification_id")
    old_id = integration.get("integrated_verification_id")
    if (
        isinstance(old_id, str)
        and old_id != ""
        and isinstance(verification_id, str)
        and old_id != verification_id
    ):
        return base + "·分支为旧版本"
    if (not isinstance(old_id, str) or old_id == "") and status in (
        "conflicted",
        "gate_failed",
        "error",
        "waiting",
    ):
        return base + "·未入分支"
    return base
