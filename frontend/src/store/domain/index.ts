export type {
  CodexDomain,
  CodexDomainActions,
  CodexDomainState,
  RoomCodexCache
} from "./codex";
export type {
  ExecutionDomain,
  ExecutionDomainActions,
  ExecutionDomainState,
  RoomExecutionCache
} from "./execution";
export type { MemoryDomain, MemoryDomainActions, MemoryDomainState, RoomMemoryCache } from "./memory";
export type {
  InspectorTarget,
  OperationsDomain,
  OperationsDomainActions,
  OperationsDomainState
} from "./operations";
export type {
  PendingRoomMessage,
  RoomCache,
  RoomDomain,
  RoomDomainActions,
  RoomDomainState,
  RoomSyncState
} from "./room";
export type { SyncDomainActions } from "./sync";
export type { UiDomain, UiDomainActions, UiDomainState } from "./ui";

import type { CodexDomain } from "./codex";
import type { ExecutionDomain } from "./execution";
import type { MemoryDomain } from "./memory";
import type { OperationsDomain } from "./operations";
import type { RoomDomain } from "./room";
import type { SyncDomainActions } from "./sync";
import type { UiDomain } from "./ui";

/** Composition-only shape; components should consume a domain capability instead. */
export type RoomStoreRoot = RoomDomain &
  OperationsDomain &
  ExecutionDomain &
  MemoryDomain &
  CodexDomain &
  UiDomain &
  SyncDomainActions;
