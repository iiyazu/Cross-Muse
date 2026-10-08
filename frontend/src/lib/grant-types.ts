/**
 * Plugin grant shapes (contract `plugin_grant/v2`, main_window_control_v1 §2). Browser-side view
 * only: the Web panel lists and revokes grants; issuing is terminal-only (`xmuse-workroom pair`, T16).
 */

export type PluginGrantStatus =
  | "pending"
  | "active"
  | "expired"
  | "revoked"
  | "unknown";

export const PLUGIN_GRANT_SCOPES = [
  "room.create",
  "room.message",
  "board.split.decide",
  "board.review.decide"
] as const;

/** A scope outside the four of main_window_control_v1 §1 is kept as `unknown` and shown as a fixed word. */
export type PluginGrantScope = (typeof PLUGIN_GRANT_SCOPES)[number] | "unknown";

export type PluginGrant = {
  grantId: string;
  /** The Rooms this grant may act on (0–16). */
  conversationIds: string[];
  host: string;
  scopes: PluginGrantScope[];
  status: PluginGrantStatus;
  createdAt: string;
  activatedAt: string | null;
  expiresAt: string;
  revokedAt: string | null;
  lastUsedAt: string | null;
  useCount: number;
};

export type PluginGrantList = {
  grants: PluginGrant[];
};

export type PluginGrantListQuery = { conversationId: string } | { host: string };

/** Hosts the panel asks about by name, to find live grants that leave the current Room out. */
export const PLUGIN_GRANT_HOSTS = ["claude-code", "opencode"] as const;
