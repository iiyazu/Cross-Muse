export type CodexConsoleTurnMode = "default" | "plan";

const STORAGE_KEY = "xmuse.codex-console-preferences.v1";
const MAX_PREFERENCES = 50;

type StoredPreference = {
  mode: CodexConsoleTurnMode;
  updatedAt: number;
};

type StoredPreferences = {
  version: 1;
  participants: Record<string, StoredPreference>;
};

function emptyPreferences(): StoredPreferences {
  return { version: 1, participants: {} };
}

function read(storage: Storage | null): StoredPreferences {
  if (!storage) return emptyPreferences();
  try {
    const parsed: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? "null");
    if (!parsed || typeof parsed !== "object" || !("version" in parsed) || parsed.version !== 1) {
      return emptyPreferences();
    }
    const participants = "participants" in parsed ? parsed.participants : null;
    if (!participants || typeof participants !== "object") return emptyPreferences();
    const valid: Record<string, StoredPreference> = {};
    for (const [participantId, candidate] of Object.entries(participants)) {
      if (!candidate || typeof candidate !== "object") continue;
      const mode = "mode" in candidate ? candidate.mode : null;
      const updatedAt = "updatedAt" in candidate ? candidate.updatedAt : null;
      if ((mode === "default" || mode === "plan") && typeof updatedAt === "number") {
        valid[participantId] = { mode, updatedAt };
      }
    }
    return { version: 1, participants: valid };
  } catch {
    return emptyPreferences();
  }
}

export function readCodexConsolePreference(
  storage: Storage | null,
  participantId: string
): CodexConsoleTurnMode {
  return read(storage).participants[participantId]?.mode ?? "default";
}

export function persistCodexConsolePreference(
  storage: Storage | null,
  participantId: string,
  mode: CodexConsoleTurnMode,
  now = Date.now()
): void {
  if (!storage || !participantId) return;
  const preferences = read(storage);
  preferences.participants[participantId] = { mode, updatedAt: now };
  const retained = Object.entries(preferences.participants)
    .sort(([, left], [, right]) => right.updatedAt - left.updatedAt)
    .slice(0, MAX_PREFERENCES);
  preferences.participants = Object.fromEntries(retained);
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Storage is a best-effort UX preference, never durable Room state.
  }
}
