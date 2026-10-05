import type { PluginGrant } from "@/lib/grant-types";
import type { XmuseApiErrorShape } from "@/lib/types";

import type { DomainCapability, DomainSelector } from "./shared";

export type RoomGrantCache = {
  grants: PluginGrant[];
  loading: boolean;
  requestGeneration: number;
  consecutiveFailures: number;
  lastSyncedAt: number;
  error: XmuseApiErrorShape | null;
};

export type GrantDomainState = {
  grantsByRoom: Record<string, RoomGrantCache>;
};

export type GrantDomainActions = {
  refreshGrants: (roomId?: string) => Promise<void>;
  revokeGrant: (grantId: string, roomId?: string) => Promise<boolean>;
  startGrantsSync: (roomId?: string) => void;
  stopGrantsSync: () => void;
};

export type GrantDomain = GrantDomainState & GrantDomainActions;
export type GrantReadCapability = DomainCapability<GrantDomain, "grantsByRoom">;
export type GrantWriteCapability = DomainCapability<
  GrantDomain,
  "refreshGrants" | "revokeGrant" | "startGrantsSync" | "stopGrantsSync"
>;

export function createGrantCacheSelector(
  roomId: string
): DomainSelector<GrantDomainState, RoomGrantCache | null> {
  return (state) => state.grantsByRoom[roomId] ?? null;
}
