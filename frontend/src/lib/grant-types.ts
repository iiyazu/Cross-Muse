/** Plugin grant shapes (contract `plugin_grant/v1`). Browser-side view only. */

export type PluginGrantStatus =
  | "pending"
  | "active"
  | "expired"
  | "revoked"
  | "unknown";

export type PluginGrant = {
  grantId: string;
  conversationId: string;
  host: string;
  scope: "board.split.decide";
  status: PluginGrantStatus;
  createdAt: string;
  activatedAt: string | null;
  expiresAt: string;
  revokedAt: string | null;
  lastUsedAt: string | null;
  useCount: number;
};

export type PluginGrantIssue = {
  grant: PluginGrant;
  pairingCode: string;
  pairingExpiresAt: string;
};

export type PluginGrantList = {
  conversationId: string;
  grants: PluginGrant[];
};

export const PLUGIN_GRANT_HOSTS = ["claude-code", "opencode"] as const;

export type PluginGrantHostOption = (typeof PLUGIN_GRANT_HOSTS)[number];

/** Duration options offered by the grant panel, in seconds (10 / 30 / 60 分钟). */
export const PLUGIN_GRANT_TTL_OPTIONS = [600, 1800, 3600] as const;

export const PLUGIN_GRANT_SCOPE = "board.split.decide";
