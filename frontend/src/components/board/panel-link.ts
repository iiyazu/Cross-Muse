import type { PanelView } from "./board-context";

/**
 * Deep links into the work panel. The in-app pane (Claude Code mod, OpenCode plugin) is where
 * the human glances and decides; it links here for the evidence only the Web reads. A link is
 * `/rooms/{id}?module=…` (or split, integration, execution, contract with an optional `v`), or
 * `?review={module_id}` to open that module's operator review.
 */
export type PanelLink = { view: PanelView | null; reviewModuleId: string | null };

const MAX_ID = 200;

function id(value: string | null): string | null {
  const cleaned = value?.trim() ?? "";
  return cleaned && cleaned.length <= MAX_ID ? cleaned : null;
}

export function panelLinkFromSearch(search: string): PanelLink {
  const params = new URLSearchParams(search);
  const review = id(params.get("review"));
  if (review) return { view: { kind: "module", moduleId: review }, reviewModuleId: review };
  const moduleId = id(params.get("module"));
  if (moduleId) return { view: { kind: "module", moduleId }, reviewModuleId: null };
  const splitId = id(params.get("split"));
  if (splitId) return { view: { kind: "split", splitId }, reviewModuleId: null };
  const integrationId = id(params.get("integration"));
  if (integrationId) return { view: { kind: "integration", integrationId }, reviewModuleId: null };
  const candidateId = id(params.get("execution"));
  if (candidateId) return { view: { kind: "execution", candidateId }, reviewModuleId: null };
  const contractId = id(params.get("contract"));
  if (contractId) {
    const version = Number(params.get("v"));
    return {
      view: Number.isSafeInteger(version) && version > 0 ? { kind: "contract", contractId, version } : { kind: "contract", contractId },
      reviewModuleId: null
    };
  }
  return { view: null, reviewModuleId: null };
}

/** The query string (with `?`, or empty) that reopens `view`. */
export function panelSearch(view: PanelView): string {
  const params = new URLSearchParams();
  if (view.kind === "module") params.set("module", view.moduleId);
  else if (view.kind === "split") params.set("split", view.splitId);
  else if (view.kind === "integration") params.set("integration", view.integrationId);
  else if (view.kind === "execution") params.set("execution", view.candidateId);
  else if (view.kind === "contract") {
    params.set("contract", view.contractId);
    if (view.version) params.set("v", String(view.version));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** The link carried by the current address, when it points into `roomId`; read on the client only. */
export function currentPanelLink(roomId: string, pathname: string, search: string): PanelLink {
  const match = pathname.match(/^\/rooms\/([^/]+)\/?$/);
  let routeRoom: string | null = null;
  try {
    routeRoom = match ? decodeURIComponent(match[1]) : null;
  } catch {
    routeRoom = null;
  }
  return routeRoom === roomId ? panelLinkFromSearch(search) : { view: null, reviewModuleId: null };
}
