// Pane drawing. Structured fields everywhere; AgentText appears only in
// the expanded module detail, drawn with Text (never Markdown/Link),
// labelled, re-sanitized client-side and truncated — and only after the
// person pressed the expand Button.

import type { XmuseBoard, XmuseCache, XmuseModule } from "../types/index";
import { attentionTarget, statusText } from "./board_state";
import { grantExpired, remainingMmSs } from "./grant_state";
import {
  ACCEPTED_BADGE,
  displayState,
  findingsPart,
  integrationJobWord,
  integrationModuleWord,
  reviewAttentionLabel,
  reviewStatusWord,
  shortGreenHead,
} from "./labels";
import { roomLink, safe, safeId, shortRev, shortRoom } from "./text";

export type PaneEnv = {
  ui: {
    resolve: (e: unknown) => PaneEls;
  };
};

function moduleLine(m: XmuseModule, reviewsOn: boolean, integrationsOn: boolean): string {
  // accepted is the only completion mark: an accepted module shows
  // 已验收, a verified-but-not-accepted one keeps 已验证 and gains the
  // review part below. While reviews are off the row is byte-identical
  // to the pre-review form.
  const statePart = reviewsOn && m.accepted ? ACCEPTED_BADGE : displayState(m.state);
  const parts = [
    safeId(m.module_id),
    m.owner_display,
    "[" + safe(m.provider_kind, 24) + "]",
    statePart,
    "报告" + String(m.done_reports) + "/通过" + String(m.passed) + "/失败" + String(m.failed) + "/返工" + String(m.rework_rounds),
  ];
  let line = parts.join(" ");
  if (reviewsOn) {
    const rp = reviewPart(m);
    if (rp !== "") line += " · " + rp;
  }
  if (integrationsOn) {
    const iw = integrationModuleWord(m.integration, 1);
    if (iw !== "") line += " · " + iw;
  }
  return line;
}

// Room line: accepted/integrated counts plus the green branch.
// Shown only while integrations are on and any part is non-trivial.
export function roomIntegrationLine(board: XmuseBoard): string {
  if (board.integrations !== 1) return "";
  const job = integrationJobWord(board.integration.status);
  const head = shortGreenHead(board.integration.green_head_commit);
  if (!(board.integrated_total > 0 || head !== "" || job !== "")) return "";
  const acceptedWord = (board.reviews === 1 ? "已验收 " : "已验证 ") + String(board.accepted_total);
  const segs = [acceptedWord, "已集成 " + String(board.integrated_total)];
  if (head !== "") segs.push("集成分支 " + head);
  return segs.join(" · ");
}

// One fixed-word review part per module row, counts only. Empty when
// there is no review. Never hidden for unknown statuses (?value).
function reviewPart(m: XmuseModule): string {
  const word = reviewStatusWord(m.review.status, m.review.reviewer_kind);
  if (word === "") return "";
  const segs = [word];
  if (m.review.escalated_from_present) segs.push("已升级");
  const fc = m.review.findings_count;
  const fp = findingsPart(fc.blocker, fc.major, fc.minor);
  if (fp !== "") segs.push(fp);
  return segs.join(" · ");
}

export function headerLine(cache: XmuseCache): string {
  if (cache.offline) return "xmuse 离线";
  if (cache.binding === null) return "xmuse 未绑定房间";
  if (cache.summary === null) return "xmuse " + shortRoom(cache.binding) + " …";
  const when =
    cache.lastPollAt !== null && Number.isFinite(cache.lastPollAt)
      ? new Date(cache.lastPollAt).toISOString().replace("T", " ").slice(0, 19) + "Z"
      : "?";
  return "看板 " + shortRoom(cache.summary.conversation_id) + " rev " + shortRev(cache.summary.revision) + " " + when;
}

export function attentionLine(kind: string, reason: string, target: string): string {
  const mark = kind === "operator" ? "! " : kind === "lead" ? "* " : "- ";
  // Room-level integration items carry no target: the label stands alone.
  // The fixed label table already covers their reason codes.
  const label = reviewAttentionLabel(reason) ?? safe(reason, 64);
  if (target === "") return mark + safe(kind, 16) + " " + label;
  return mark + safe(kind, 16) + " " + label + " " + target;
}

// Pure tree builder used by the hook and the tests. Returns plain-data
// nodes so tests can assert without a surface. Control labels are fixed
// words only (批准/拒绝/取消/撤销授权): split ids live in keys, agent text
// never enters a label, and toasts never carry either.
export type PaneNode =
  | { type: "text"; text: string; dim?: boolean }
  | { type: "button"; key: string; label: string }
  | { type: "link"; key: string; label: string; href: string }
  | { type: "input"; key: string; label: string; placeholder?: string; submitLabel?: string; value?: string };

export function buildPaneNodes(cache: XmuseCache, webUrl: string, nowMs: number = Date.now()): PaneNode[] {
  const nodes: PaneNode[] = [];
  nodes.push({ type: "text", text: headerLine(cache) });
  nodes.push({ type: "text", text: statusText(cache), dim: true });

  // Grant section. Always drawn, even while unbound or offline, so the
  // default pane offers pairing. The confirm field never hints the digest.
  nodes.push({ type: "text", text: "授权" });
  const grant = cache.grant;
  const boundId = cache.binding;
  const grantLive = grant !== null && boundId !== null && !grantExpired(grant.expiresAt, nowMs);
  const liveGrant = grantLive ? grant : null;
  if (liveGrant === null) {
    nodes.push({ type: "text", text: "在 Web 看板的“插件授权”生成配对码，然后输入这里。" });
    nodes.push({
      type: "input",
      key: "xmuse-pairing",
      label: "配对码",
      placeholder: "ABCD-EFGH",
      submitLabel: "配对",
      value: "",
    });
  } else {
    nodes.push({ type: "text", text: "已授权 · 剩余 " + remainingMmSs(liveGrant.expiresAt, nowMs) });
    nodes.push({ type: "button", key: "xmuse-revoke", label: "撤销授权" });
  }

  if (cache.offline || cache.binding === null || cache.summary === null) return nodes;

  const summary = cache.summary;
  const operatorFirst = summary.attention.slice().sort((a, b) => {
    const rank = (k: string): number => (k === "operator" ? 0 : k === "lead" ? 1 : k === "owner" ? 2 : 3);
    return rank(a.kind) - rank(b.kind);
  });
  for (const a of operatorFirst.slice(0, 10)) {
    const target = attentionTarget(a);
    nodes.push({ type: "text", text: attentionLine(a.kind, a.reason_code, target) });
  }

  const board: XmuseBoard | null = cache.board;
  if (board === null || cache.summary === null) {
    nodes.push({ type: "text", text: "看板明细未加载", dim: true });
    return nodes;
  }
  const integrationsOn = board.integrations === 1;
  const roomLine = roomIntegrationLine(board);
  if (roomLine !== "") nodes.push({ type: "text", text: roomLine });
  for (const m of board.modules.slice(0, 100)) {
    nodes.push({ type: "text", text: moduleLine(m, board.reviews === 1, integrationsOn) });
    // An operator-pending review links to the room page, same style as
    // the proposed-split link. Room page only: no review id and no patch
    // reference anywhere in the pane.
    if (board.reviews === 1 && m.review.status === "pending" && m.review.reviewer_kind === "operator") {
      const reviewHref = roomLink(webUrl, summary.conversation_id);
      if (reviewHref !== "") nodes.push({ type: "link", key: "review-" + safeId(m.module_id), label: "在 Web 复核", href: reviewHref });
    }
    if (m.failed > 0 && m.gate_ids.length > 0) {
      nodes.push({ type: "text", text: "门禁: " + m.gate_ids.slice(0, 6).join(" ") });
    }
    if (m.stale_contracts.length > 0) {
      nodes.push({ type: "text", text: "依赖过期: " + m.stale_contracts.slice(0, 6).join(" ") });
    }
    const open = cache.expanded[m.module_id] === true;
    nodes.push({ type: "button", key: "expand-" + safeId(m.module_id), label: open ? "收起" : "展开" });
    if (open) {
      nodes.push({ type: "text", text: "agent 自述 · 未验证" });
      nodes.push({ type: "text", text: "charter v" + String(m.charter_version) + " " + m.paths.slice(0, 8).join(" ") });
      nodes.push({ type: "text", text: "提供 " + m.provides.slice(0, 8).join(" ") + " 依赖 " + m.depends.slice(0, 8).join(" ") });
      const detail = board.details.find((d) => d.module_id === m.module_id);
      const snippets = (detail !== undefined ? detail.snippets : []).slice(0, 10);
      if (snippets.length === 0) nodes.push({ type: "text", text: "暂无自述", dim: true });
      for (const s of snippets) {
        nodes.push({ type: "text", text: safe(s.field, 48) + ": " + safe(s.text, 400) });
      }
    }
  }

  for (const row of board.splits.slice(0, 10)) {
    if (row.status !== "proposed") continue;
    const href = roomLink(webUrl, summary.conversation_id);
    nodes.push({ type: "text", text: "待审批 " + safe(row.split_id, 64) });
    if (href !== "") nodes.push({ type: "link", key: "split-" + safe(row.split_id, 64), label: "在 Web 审批", href });
    // Decision buttons appear only for a live grant bound to this room and
    // a split that carries a digest guard. Labels stay fixed words.
    const eligible =
      grantLive && grant !== null && boundId !== null && grant.conversationId === boundId && row.digest !== "";
    if (!eligible) continue;
    const pending = cache.confirming;
    if (pending !== null && pending.splitId === row.split_id) {
      nodes.push({
        type: "input",
        key: "xmuse-confirm",
        label: "输入摘要前 6 位以确认",
        placeholder: "请输入前 6 位",
        value: "",
      });
      nodes.push({ type: "button", key: "xmuse-cancel-confirm", label: "取消" });
    } else if (pending === null) {
      nodes.push({ type: "button", key: "xmuse-approve-" + row.split_id, label: "批准" });
      nodes.push({ type: "button", key: "xmuse-reject-" + row.split_id, label: "拒绝" });
    }
  }

  if (board.contracts.length === 0) {
    nodes.push({ type: "text", text: "无契约", dim: true });
  } else {
    for (const c of board.contracts.slice(0, 50)) {
      nodes.push({ type: "text", text: "契约 " + safeId(c.contract_id) + " v" + String(c.latest_version) });
    }
  }
  return nodes;
}

// Draw the nodes with the surface's own elements. Keeps trees simple so an
// unknown/oversized payload degrades instead of throwing.
export type PaneEls = {
  Box: (props: never) => unknown;
  Text: (props: never) => unknown;
  Button: (props: never) => unknown;
  Link: (props: never) => unknown;
  Input?: (props: never) => unknown;
};

export function PaneTree(props: {
  els: PaneEls;
  nodes: PaneNode[];
  onExpand: (moduleId: string) => void;
  onControl: (key: string) => void;
  onSubmit: (key: string, value: string) => void;
}): unknown {
  const { Box, Text, Button, Link } = props.els;
  const Field = props.els.Input;
  return (
    <Box flexDirection="column">
      {props.nodes.map((n, i) => {
        if (n.type === "text") {
          return (
            <Text key={"t" + String(i)} dimColor={n.dim === true ? true : undefined}>
              {n.text}
            </Text>
          );
        }
        if (n.type === "input") {
          if (Field === undefined) return <Text key={n.key} dimColor>{n.label}</Text>;
          return (
            <Field
              key={n.key}
              label={n.label}
              placeholder={n.placeholder}
              submitLabel={n.submitLabel}
              value={n.value ?? ""}
              onSubmit={(value: string) => props.onSubmit(n.key, value)}
            />
          );
        }
        if (n.type === "button") {
          if (n.key.startsWith("expand-")) {
            const moduleId = n.key.slice("expand-".length);
            return <Button key={n.key} label={n.label} onPress={() => props.onExpand(moduleId)} />;
          }
          return <Button key={n.key} label={n.label} onPress={() => props.onControl(n.key)} />;
        }
        return <Link key={n.key} label={n.label} href={n.href} />;
      })}
    </Box>
  );
}
