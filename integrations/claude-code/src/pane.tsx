// Pane drawing. Structured fields everywhere; AgentText appears only in
// the expanded module detail, drawn with Text (never Markdown/Link),
// labelled, re-sanitized client-side and truncated — and only after the
// person pressed the expand Button.

import type { XmuseBoard, XmuseCache, XmuseModule } from "../types/index";
import { statusText } from "./board_state";
import { displayState } from "./labels";
import { roomLink, safe, safeId, shortRev, shortRoom } from "./text";

export type PaneEnv = {
  ui: {
    resolve: (e: unknown) => PaneEls;
  };
};

function moduleLine(m: XmuseModule): string {
  const parts = [
    safeId(m.module_id),
    m.owner_display,
    "[" + safe(m.provider_kind, 24) + "]",
    displayState(m.state),
    "报告" + String(m.done_reports) + "/通过" + String(m.passed) + "/失败" + String(m.failed) + "/返工" + String(m.rework_rounds),
  ];
  return parts.join(" ");
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
  return mark + safe(kind, 16) + " " + safe(reason, 64) + " " + target;
}

// Pure tree builder used by the hook and the tests. Returns plain-data
// nodes so tests can assert without a surface.
export type PaneNode =
  | { type: "text"; text: string; dim?: boolean }
  | { type: "button"; key: string; label: string }
  | { type: "link"; key: string; label: string; href: string };

export function buildPaneNodes(cache: XmuseCache, webUrl: string): PaneNode[] {
  const nodes: PaneNode[] = [];
  nodes.push({ type: "text", text: headerLine(cache) });
  nodes.push({ type: "text", text: statusText(cache), dim: true });
  if (cache.offline || cache.binding === null || cache.summary === null) return nodes;

  const summary = cache.summary;
  const operatorFirst = summary.attention.slice().sort((a, b) => {
    const rank = (k: string): number => (k === "operator" ? 0 : k === "lead" ? 1 : k === "owner" ? 2 : 3);
    return rank(a.kind) - rank(b.kind);
  });
  for (const a of operatorFirst.slice(0, 10)) {
    const target = a.module_id !== null ? safeId(a.module_id) : safe(a.split_id ?? "?", 32);
    nodes.push({ type: "text", text: attentionLine(a.kind, a.reason_code, target) });
  }

  const board: XmuseBoard | null = cache.board;
  if (board === null || cache.summary === null) {
    nodes.push({ type: "text", text: "看板明细未加载", dim: true });
    return nodes;
  }
  for (const m of board.modules.slice(0, 100)) {
    nodes.push({ type: "text", text: moduleLine(m) });
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

  for (const sid of board.proposed_splits.slice(0, 10)) {
    const href = roomLink(webUrl, summary.conversation_id);
    nodes.push({ type: "text", text: "待审批 " + safe(sid, 64) });
    if (href !== "") nodes.push({ type: "link", key: "split-" + safe(sid, 64), label: "在 Web 审批", href });
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
};

export function PaneTree(props: { els: PaneEls; nodes: PaneNode[]; onExpand: (moduleId: string) => void }): unknown {
  const { Box, Text, Button, Link } = props.els;
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
        if (n.type === "button") {
          const moduleId = n.key.startsWith("expand-") ? n.key.slice("expand-".length) : n.key;
          return <Button key={n.key} label={n.label} onPress={() => props.onExpand(moduleId)} />;
        }
        return <Link key={n.key} label={n.label} href={n.href} />;
      })}
    </Box>
  );
}
