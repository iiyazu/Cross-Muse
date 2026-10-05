// Xmuse board status mod — PluginState contract.
//
// This file is the one place the shapes the pane reads are written. It is
// self-contained (no imports) and is named in plugin.json as "types".
// Every value below is structured server data only: counts, state codes,
// module ids, reason codes. Agent-authored text is kept out of the status
// line / toast / command / tool paths by construction (see src/text.ts);
// the pane holds a bounded, sanitized copy for the expanded detail only.

export type XmuseAttentionItem = {
  kind: string;
  reason_code: string;
  module_id: string | null;
  split_id: string | null;
};

export type XmuseSummary = {
  conversation_id: string;
  revision: string;
  board_seq: number;
  modules_total: number;
  counts: { [state: string]: number };
  attention: XmuseAttentionItem[];
  attention_total: number;
};

export type XmuseAgentSnippet = {
  field: string;
  text: string;
};

export type XmuseModule = {
  module_id: string;
  state: string;
  lifecycle: string;
  owner_display: string;
  provider_kind: string;
  done_reports: number;
  passed: number;
  failed: number;
  rework_rounds: number;
  gate_ids: string[];
  stale_contracts: string[];
  attention_kind: string;
  attention_reason: string | null;
  charter_version: number;
  paths: string[];
  provides: string[];
  depends: string[];
};

export type XmuseModuleDetail = {
  module_id: string;
  snippets: XmuseAgentSnippet[];
};

export type XmuseBoard = {
  revision: string;
  modules: XmuseModule[];
  details: XmuseModuleDetail[];
  contracts: { contract_id: string; latest_version: number }[];
  proposed_splits: string[];
  splits: XmuseSplitSummary[];
  operator_attention: XmuseAttentionItem[];
};

// One split row the pane may offer a decision on. Only structured fields:
// status codes and the digest guard. Module titles and path globs stay in
// the expanded module detail and never enter a control label or a toast.
export type XmuseSplitSummary = {
  split_id: string;
  status: string;
  digest: string;
};

// Non-secret grant metadata the pane renders from. The token itself lives
// only in a module-level variable of the hooks module, never here.
export type XmuseGrantMeta = {
  grantId: string;
  expiresAt: string;
  conversationId: string;
};

export type XmuseConfirming = {
  splitId: string;
  decision: string;
};

export type XmuseCache = {
  binding: string | null;
  cwd: string | null;
  summary: XmuseSummary | null;
  board: XmuseBoard | null;
  summaryEtag: string | null;
  boardEtag: string | null;
  lastPollAt: number | null;
  offline: boolean;
  baselined: boolean;
  seenAttention: string[];
  seenStates: { [module_id: string]: string };
  failCount: number;
  nextRetryAt: number;
  paneOpen: boolean;
  expanded: { [module_id: string]: boolean };
  grant: XmuseGrantMeta | null;
  confirming: XmuseConfirming | null;
  formEpoch: number;
};

declare module "claude-code" {
  interface PluginState {
    xmuse: { cache: XmuseCache };
  }
}
