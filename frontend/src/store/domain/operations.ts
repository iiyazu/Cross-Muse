import type {
  RoomOperationsProjection,
  RoomRuntimeRecoverDescriptor,
  XmuseApiErrorShape
} from "@/lib/types";

import type { DomainCapability, DomainSelector } from "./shared";

export type InspectorTarget = {
  roomId: string;
  observationId: string | null;
  incidentId: string;
};

export type OperationsDomainState = {
  operations: RoomOperationsProjection | null;
  operationsLoading: boolean;
  operationsError: XmuseApiErrorShape | null;
  operationsGeneration: number;
  operationsConsecutiveFailures: number;
  runtimeRecoverPending: boolean;
  runtimeRecoverError: XmuseApiErrorShape | null;
  inspectorTarget: InspectorTarget | null;
};

export type OperationsDomainActions = {
  refreshOperations: () => Promise<void>;
  recoverRuntime: (descriptor: RoomRuntimeRecoverDescriptor) => Promise<boolean>;
  setInspectorTarget: (target: InspectorTarget | null) => void;
  startOperationsSync: () => void;
};

export type OperationsDomain = OperationsDomainState & OperationsDomainActions;
export type OperationsReadCapability = DomainCapability<
  OperationsDomain,
  "operations" | "operationsLoading" | "operationsError" | "runtimeRecoverPending"
>;
export type OperationsWriteCapability = DomainCapability<
  OperationsDomain,
  "recoverRuntime" | "setInspectorTarget"
>;

export const selectOperations: DomainSelector<
  OperationsDomainState,
  RoomOperationsProjection | null
> = (state) => state.operations;
export const selectOperationsLoading: DomainSelector<OperationsDomainState, boolean> =
  (state) => state.operationsLoading;
