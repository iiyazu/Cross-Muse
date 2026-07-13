export const RUNTIME_RECOVER_ACTION_KEY = "xmuse.room-runtime-recover-action/v1";
export const EXECUTION_ACTION_KEY_PREFIX = "xmuse.room-execution-action/v1:";
export const MEMORY_ACTION_KEY_PREFIX = "xmuse.room-memory-action/v1:";
export const MEMORY_REBUILD_ACTION_KEY = "xmuse.memory-runtime-rebuild-action/v1";

type IdFactory = () => string;

function randomId(prefix: string): string {
  return `${prefix}${crypto.randomUUID()}`;
}

function guardedActionId(
  storage: Storage | null,
  key: string,
  guardName: string,
  guardValue: string,
  create: IdFactory
): string {
  if (storage) {
    try {
      const saved = JSON.parse(storage.getItem(key) ?? "null") as Record<string, unknown> | null;
      if (saved?.[guardName] === guardValue && typeof saved.clientActionId === "string" && saved.clientActionId) {
        return saved.clientActionId;
      }
    } catch {
      storage.removeItem(key);
    }
  }
  const clientActionId = create();
  storage?.setItem(key, JSON.stringify({ [guardName]: guardValue, clientActionId }));
  return clientActionId;
}

function clearGuardedAction(
  storage: Storage | null,
  key: string,
  guardName: string,
  guardValue: string
): void {
  if (!storage) return;
  try {
    const saved = JSON.parse(storage.getItem(key) ?? "null") as Record<string, unknown> | null;
    if (saved?.[guardName] === guardValue) storage.removeItem(key);
  } catch {
    storage.removeItem(key);
  }
}

export function runtimeRecoverActionId(
  storage: Storage | null,
  incidentId: string,
  create: IdFactory = () => randomId("ui_runtime_recover_")
): string {
  return guardedActionId(storage, RUNTIME_RECOVER_ACTION_KEY, "incidentId", incidentId, create);
}

export function clearRuntimeRecoverAction(storage: Storage | null, incidentId: string): void {
  clearGuardedAction(storage, RUNTIME_RECOVER_ACTION_KEY, "incidentId", incidentId);
}

function fingerprintActionId(
  storage: Storage | null,
  keyPrefix: string,
  fingerprint: string,
  create: IdFactory
): string {
  const key = `${keyPrefix}${fingerprint}`;
  const prior = storage?.getItem(key)?.trim();
  if (prior) return prior;
  const clientActionId = create();
  storage?.setItem(key, clientActionId);
  return clientActionId;
}

export function executionActionId(
  storage: Storage | null,
  fingerprint: string,
  create: IdFactory = () => randomId("ui_execution_")
): string {
  return fingerprintActionId(storage, EXECUTION_ACTION_KEY_PREFIX, fingerprint, create);
}

export function clearExecutionAction(storage: Storage | null, fingerprint: string): void {
  storage?.removeItem(`${EXECUTION_ACTION_KEY_PREFIX}${fingerprint}`);
}

export function memoryActionId(
  storage: Storage | null,
  fingerprint: string,
  create: IdFactory = () => randomId("ui_memory_")
): string {
  return fingerprintActionId(storage, MEMORY_ACTION_KEY_PREFIX, fingerprint, create);
}

export function clearMemoryAction(storage: Storage | null, fingerprint: string): void {
  storage?.removeItem(`${MEMORY_ACTION_KEY_PREFIX}${fingerprint}`);
}

export function memoryRebuildActionId(
  storage: Storage | null,
  incidentId: string,
  create: IdFactory = () => randomId("ui_memory_rebuild_")
): string {
  return guardedActionId(storage, MEMORY_REBUILD_ACTION_KEY, "incidentId", incidentId, create);
}

export function clearMemoryRebuildAction(storage: Storage | null, incidentId: string): void {
  clearGuardedAction(storage, MEMORY_REBUILD_ACTION_KEY, "incidentId", incidentId);
}

export function retainActionIdAfterFailure(status: number): boolean {
  return status === 0 || status === 502 || status === 504;
}
