import type { DomainCapability } from "./shared";

export type SyncDomainActions = {
  startSync: () => void;
  stopSync: () => void;
};

export type SyncCapability = DomainCapability<SyncDomainActions, keyof SyncDomainActions>;
