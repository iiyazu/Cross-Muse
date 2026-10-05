"""Structured text and JSON builders for the CLI output.

Only sanitized server strings leave this module. Agent-authored text
(``AgentText``) is never read here: every line is built from counts,
state codes, ids and reason-code labels only.
"""

from __future__ import annotations

from . import api as api_module
from . import labels as labels_module
from .sanitize import safe, safe_id, short_rev, short_room


def rooms_text(rooms: list[dict[str, str]]) -> str:
    """One line per room: ``short_id  updated  title-safe``."""
    lines = []
    for room in rooms:
        short = short_room(room["conversation_id"])
        updated = safe(room["updated_at"], 64)
        title = safe(room["title"], 60)
        lines.append(short + "  " + updated + "  " + title)
    if not lines:
        return "暂无房间"
    return "\n".join(lines)


def rooms_json(rooms: list[dict[str, str]]) -> dict[str, object]:
    """Stable JSON form of the rooms list, same filtering as text."""
    entries = []
    for room in rooms:
        entries.append(
            {
                "conversation_id": safe(room["conversation_id"], 128),
                "short_id": short_room(room["conversation_id"]),
                "updated_at": safe(room["updated_at"], 64),
                "title": safe(room["title"], 60),
            }
        )
    return {"rooms": entries}


def _operator_count(summary: dict[str, object]) -> int:
    total = 0
    attention = summary["attention"]
    assert isinstance(attention, list)
    for item in attention:
        assert isinstance(item, dict)
        if item["kind"] == "operator":
            total += 1
    return total


def status_line(summary: dict[str, object]) -> str:
    """One status line, mirroring the mod's status text."""
    counts = summary["counts"]
    assert isinstance(counts, dict)
    parts = []
    for group in labels_module.STATUS_GROUPS:
        if group["state"] == "verified":
            total = summary["accepted_total"]
        else:
            total = counts.get(group["state"], 0)
        assert isinstance(total, int)
        if total > 0:
            parts.append(group["glyph"] + str(total))
    line = "看板 " + str(summary["modules_total"]) + " 模块"
    if parts:
        line += " · " + " ".join(parts)
    pending = _operator_count(summary)
    if pending > 0:
        line += " · 待你处理 " + str(pending)
    integrated = summary["integrated_total"]
    if summary["integrations"] == 1 and isinstance(integrated, int) and integrated > 0:
        line += " · 已集成 " + str(integrated)
    return line


def _attention_target(item: dict[str, object]) -> str:
    module_id = item.get("module_id")
    if isinstance(module_id, str) and module_id != "":
        return safe_id(module_id)
    split_id = item.get("split_id")
    return safe(split_id, 32) if isinstance(split_id, str) and split_id != "" else "?"


def status_block(summary: dict[str, object]) -> str:
    """Compact structured block: header, counts, operator attention."""
    room_id = summary["conversation_id"]
    assert isinstance(room_id, str)
    revision = summary["revision"]
    assert isinstance(revision, str)
    lines = ["xmuse " + short_room(room_id) + " rev " + short_rev(revision)]
    counts = summary["counts"]
    assert isinstance(counts, dict)
    parts = []
    for group in labels_module.STATUS_GROUPS:
        if group["state"] == "verified":
            total = summary["accepted_total"]
        else:
            total = counts.get(group["state"], 0)
        assert isinstance(total, int)
        if total > 0:
            parts.append(group["glyph"] + str(total))
    modules_line = "模块 " + str(summary["modules_total"])
    if parts:
        modules_line += " " + " ".join(parts)
    integrated_count = summary["integrated_total"]
    if summary["integrations"] == 1 and isinstance(integrated_count, int) and integrated_count > 0:
        modules_line += " 已集成 " + str(integrated_count)
    lines.append(modules_line)
    lines.append("待你处理 " + str(_operator_count(summary)))
    attention = summary["attention"]
    assert isinstance(attention, list)
    shown = 0
    for item in attention:
        assert isinstance(item, dict)
        if item["kind"] != "operator":
            continue
        if shown >= 5:
            break
        reason = item.get("reason_code")
        label = labels_module.reason_label(reason)
        if label == "":
            label = "待处理"
        lines.append("! " + label + " " + _attention_target(item))
        shown += 1
    return "\n".join(lines)


def status_json(summary: dict[str, object]) -> dict[str, object]:
    """Stable JSON form of the status, same filtering as text."""
    room_id = summary["conversation_id"]
    assert isinstance(room_id, str)
    revision = summary["revision"]
    assert isinstance(revision, str)
    counts = summary["counts"]
    assert isinstance(counts, dict)
    attention = summary["attention"]
    assert isinstance(attention, list)
    items = []
    for item in attention:
        assert isinstance(item, dict)
        reason = item.get("reason_code")
        module_id = item.get("module_id")
        split_id = item.get("split_id")
        items.append(
            {
                "kind": safe(item.get("kind"), 16),
                "reason_code": safe(reason, 64) if isinstance(reason, str) else "?",
                "label": labels_module.reason_label(reason),
                "module_id": safe_id(module_id) if isinstance(module_id, str) else None,
                "split_id": safe(split_id, 32) if isinstance(split_id, str) else None,
            }
        )
    return {
        "conversation_id": safe(room_id, 128),
        "short_id": short_room(room_id),
        "revision": safe(revision, 64),
        "board_seq": summary["board_seq"],
        "modules_total": summary["modules_total"],
        "counts": {key: counts.get(key, 0) for key in api_module.COUNT_KEYS},
        "accepted_total": summary["accepted_total"],
        "attention_total": summary["attention_total"],
        "attention": items,
        "integrated_total": summary["integrated_total"],
        "line": status_line(summary),
    }


def _module_row(module: dict[str, object], reviews_on: bool) -> str:
    state = module["state"]
    assert isinstance(state, str)
    # The one completion mark. Like the mod and the Web it appears only
    # with reviews on: with reviews off the row is the pre-review form
    # (accepted == verified there). A verified-but-not-accepted module
    # keeps its state badge and gains the review word below.
    if reviews_on and module["accepted"] is True:
        state_part = labels_module.ACCEPTED_BADGE
    else:
        state_part = labels_module.display_state(state)
    module_id = module["module_id"]
    assert isinstance(module_id, str)
    owner = module["owner_display"]
    assert isinstance(owner, str)
    provider = module["provider_kind"]
    assert isinstance(provider, str)
    counters = (
        "报告"
        + str(module["done_reports"])
        + "/通过"
        + str(module["passed"])
        + "/失败"
        + str(module["failed"])
        + "/返工"
        + str(module["rework_rounds"])
    )
    line = (
        safe_id(module_id)
        + " "
        + safe(owner, 32)
        + " ["
        + safe(provider, 24)
        + "] "
        + state_part
        + " "
        + counters
    )
    if reviews_on:
        review = module["review"]
        assert isinstance(review, dict)
        word = labels_module.review_status_word(review["status"], review["reviewer_kind"])
        if word != "":
            segs = [word]
            if review["escalated"] is True:
                segs.append("已升级")
            findings = labels_module.findings_part(
                int(review["blocker"]), int(review["major"]), int(review["minor"])
            )
            if findings != "":
                segs.append(findings)
            line += " · " + " · ".join(segs)
    return line


def board_text(board: dict[str, object], web_base: str) -> str:
    """Module table, attention list, proposed splits and the Web link."""
    room_id = board["conversation_id"]
    assert isinstance(room_id, str)
    revision = board["revision"]
    assert isinstance(revision, str)
    reviews_on = board["reviews"] == 1
    link = api_module.web_room_link(web_base, room_id)
    lines = ["看板 " + short_room(room_id) + " rev " + short_rev(revision)]
    lines.append("module_id owner [provider] state review accepted 报告/通过/失败/返工")
    modules = board["modules"]
    assert isinstance(modules, list)
    if not modules:
        lines.append("暂无模块")
    for module in modules:
        assert isinstance(module, dict)
        lines.append(_module_row(module, reviews_on))
    attention = board["attention"]
    assert isinstance(attention, list)
    for item in attention:
        assert isinstance(item, dict)
        label = labels_module.reason_label(item.get("reason_code"))
        if label == "":
            label = "待处理"
        lines.append(
            labels_module.attention_mark(item.get("kind"))
            + " "
            + label
            + " "
            + _attention_target(item)
        )
    splits = board["splits"]
    assert isinstance(splits, list)
    for split in splits:
        assert isinstance(split, dict)
        if split["status"] != "proposed":
            continue
        split_id = split["split_id"]
        assert isinstance(split_id, str)
        pending = "待审批 " + safe(split_id, 64)
        if link != "":
            pending += " 在 Web 审批：" + link
        lines.append(pending)
    lines.append("在 Web 打开：" + link if link != "" else "在 Web 打开：?")
    return "\n".join(lines)


def board_json(board: dict[str, object], web_base: str) -> dict[str, object]:
    """Stable JSON form of the board, same filtering as text."""
    room_id = board["conversation_id"]
    assert isinstance(room_id, str)
    revision = board["revision"]
    assert isinstance(revision, str)
    modules = board["modules"]
    assert isinstance(modules, list)
    rows = []
    for module in modules:
        assert isinstance(module, dict)
        module_id = module["module_id"]
        assert isinstance(module_id, str)
        review = module["review"]
        assert isinstance(review, dict)
        state = module["state"]
        assert isinstance(state, str)
        rows.append(
            {
                "module_id": safe_id(module_id),
                "owner": safe(module["owner_display"], 32),
                "provider": safe(module["provider_kind"], 24),
                "state": safe(state, 48),
                "state_label": labels_module.display_state(state),
                "accepted": module["accepted"] is True,
                "accepted_label": labels_module.ACCEPTED_BADGE
                if board["reviews"] == 1 and module["accepted"] is True
                else "",
                "review": labels_module.review_status_word(
                    review["status"], review["reviewer_kind"]
                ),
                "review_escalated": review["escalated"] is True,
                "findings": labels_module.findings_part(
                    int(review["blocker"]), int(review["major"]), int(review["minor"])
                ),
                "counters": {
                    "done_reports": module["done_reports"],
                    "passed": module["passed"],
                    "failed": module["failed"],
                    "rework_rounds": module["rework_rounds"],
                },
            }
        )
    attention = board["attention"]
    assert isinstance(attention, list)
    items = []
    for item in attention:
        assert isinstance(item, dict)
        module_id = item.get("module_id")
        split_id = item.get("split_id")
        items.append(
            {
                "kind": safe(item.get("kind"), 16),
                "reason_code": safe(item.get("reason_code"), 64),
                "label": labels_module.reason_label(item.get("reason_code")),
                "module_id": safe_id(module_id) if isinstance(module_id, str) else None,
                "split_id": safe(split_id, 32) if isinstance(split_id, str) else None,
            }
        )
    splits = board["splits"]
    assert isinstance(splits, list)
    pending = []
    for split in splits:
        assert isinstance(split, dict)
        split_id = split["split_id"]
        assert isinstance(split_id, str)
        if split["status"] == "proposed":
            pending.append(safe(split_id, 64))
    return {
        "conversation_id": safe(room_id, 128),
        "short_id": short_room(room_id),
        "revision": safe(revision, 64),
        "board_seq": board["board_seq"],
        "reviews": board["reviews"],
        "accepted_total": board["accepted_total"],
        "modules_total": len(rows),
        "modules": rows,
        "attention": items,
        "proposed_splits": pending,
        "web_url": safe(api_module.web_room_link(web_base, room_id), 2048),
    }


def _as_int_map(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _data_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value != "":
        return value
    return None


def _data_int(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return None


def summarize_event(event: dict[str, object]) -> str:
    """One fixed-word summary from structured fields only, never AgentText."""
    kind = event["kind"]
    assert isinstance(kind, str)
    data = _as_int_map(event.get("data"))
    if kind == "split_proposed":
        module_ids = data.get("module_ids")
        total = len(module_ids) if isinstance(module_ids, list) else 0
        return "提议拆分 " + str(total) + "模块"
    if kind == "split_rejected":
        word = labels_module.decided_via_label(data.get("decided_via"))
        return "驳回拆分" + (" " + word if word != "" else "")
    if kind == "charter_assigned":
        version = _data_int(data, "charter_version")
        return "分配章程" + (" v" + str(version) if version is not None else "")
    if kind == "claimed":
        return "已认领"
    if kind == "contract_published" or kind == "contract_revised":
        head = "发布契约" if kind == "contract_published" else "修订契约"
        contract_id = _data_str(data, "contract_id")
        version = _data_int(data, "version")
        segs = [head]
        if contract_id is not None:
            segs.append(safe(contract_id, 48))
        if version is not None:
            segs.append("v" + str(version))
        segs.append(labels_module.contract_kind_label(data.get("kind")))
        return " ".join(segs)
    if kind == "progress":
        word = labels_module.progress_status_word(data.get("status"))
        total = _data_int(data, "claims_total")
        summary = "进展报告 " + word
        if total is not None:
            summary += " 共" + str(total) + "条"
        return summary
    if kind == "question":
        return "提问"
    if kind == "verification":
        word = labels_module.verification_result_word(data.get("status"))
        segs = ["验证结果 " + word]
        reason = labels_module.reason_label(data.get("reason_code"))
        if reason != "":
            segs.append(reason)
        if data.get("escalated") is True:
            segs.append("已升级")
        return " ".join(segs)
    if kind == "review_requested":
        reviewer = data.get("reviewer_kind")
        if reviewer == "operator":
            who = "待你复核"
        elif reviewer == "participant":
            who = "待参评人复核"
        else:
            who = "?" + safe(reviewer, 48)
        summary = "请求复核 " + who
        if data.get("escalated_from") is not None:
            summary += " 已升级"
        return summary
    if kind == "review":
        word = labels_module.verdict_word(data.get("verdict"))
        segs = ["复核结论 " + word]
        findings = _as_int_map(data.get("findings_count"))
        blocker = _data_int(findings, "blocker") or 0
        major = _data_int(findings, "major") or 0
        minor = _data_int(findings, "minor") or 0
        part = labels_module.findings_part(blocker, major, minor)
        if part != "":
            segs.append(part)
        via = labels_module.decided_via_label(data.get("decided_via"))
        if via != "":
            segs.append(via)
        return " ".join(segs)
    return labels_module.event_kind_label(kind)


def event_line(event: dict[str, object]) -> str:
    """One line per event: ``#seq  kind  module_id  <fixed-word summary>``."""
    seq = event["seq"]
    assert isinstance(seq, int)
    kind = event["kind"]
    assert isinstance(kind, str)
    module_id = event.get("module_id")
    target = safe_id(module_id) if isinstance(module_id, str) and module_id != "" else "-"
    return "#" + str(seq) + " " + safe(kind, 48) + " " + target + " " + summarize_event(event)
