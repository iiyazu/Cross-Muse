import type {
  RoomCodexActionInput,
  RoomCodexCapabilityId,
  RoomCodexSafeRequestByCapability
} from "./types";

export type CodexConsoleMode = "default" | "plan";

export type CodexConsoleParseResult =
  | { kind: "empty" }
  | { kind: "preference"; mode: CodexConsoleMode }
  | { kind: "error"; code: "codex_console_command_unknown" | "codex_console_command_invalid" }
  | {
      kind: "action";
      capabilityId: RoomCodexActionInput["capability_id"];
      safeRequest: RoomCodexActionInput["request"];
    };

const DEFAULT_GOAL_TOKEN_BUDGET = 100_000;

function action<K extends RoomCodexCapabilityId>(
  capabilityId: K,
  safeRequest: RoomCodexSafeRequestByCapability[K]
): CodexConsoleParseResult {
  return { kind: "action", capabilityId, safeRequest };
}

function parseGoal(argument: string): CodexConsoleParseResult {
  if (!argument) return action("goal_get", {});
  if (argument === "pause") return action("goal_pause", {});
  if (argument === "resume") return action("goal_resume", {});
  if (argument === "clear") return action("goal_clear", {});
  const budgetMatch = /^--budget\s+(\d+)\s+(.+)$/s.exec(argument);
  if (budgetMatch) {
    const tokenBudget = Number(budgetMatch[1]);
    if (!Number.isSafeInteger(tokenBudget) || tokenBudget < 10_000 || tokenBudget > 1_000_000) {
      return { kind: "error", code: "codex_console_command_invalid" };
    }
    return action("goal_set", { objective: budgetMatch[2].trim(), token_budget: tokenBudget });
  }
  if (argument.startsWith("--budget")) {
    return { kind: "error", code: "codex_console_command_invalid" };
  }
  return action("goal_set", { objective: argument, token_budget: DEFAULT_GOAL_TOKEN_BUDGET });
}

/**
 * Parse the Agent Console's closed alias surface.
 *
 * This deliberately does not accept arbitrary slash commands or native method names. The
 * returned action still has to match an available server descriptor before it may be sent.
 */
export function parseCodexConsoleInput(
  input: string,
  preferredMode: CodexConsoleMode = "default"
): CodexConsoleParseResult {
  const text = input.trim();
  if (!text) return { kind: "empty" };
  if (!text.startsWith("/")) {
    return action("console_turn_start", { text, mode: preferredMode });
  }

  const match = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(text);
  if (!match) return { kind: "error", code: "codex_console_command_invalid" };
  const command = match[1].toLowerCase();
  const argument = (match[2] ?? "").trim();
  switch (command) {
    case "goal":
      return parseGoal(argument);
    case "model":
      return argument
        ? action("settings_update", { model: argument })
        : action("models_list", {});
    case "effort":
      return argument && !argument.includes(" ") && argument !== "ultra"
        ? action("settings_update", { effort: argument })
        : { kind: "error", code: "codex_console_command_invalid" };
    case "plan":
    case "default": {
      const mode = command as CodexConsoleMode;
      return argument
        ? action("console_turn_start", { text: argument, mode })
        : { kind: "preference", mode };
    }
    case "steer":
      return argument
        ? action("turn_steer", { text: argument })
        : { kind: "error", code: "codex_console_command_invalid" };
    case "interrupt":
      return argument
        ? { kind: "error", code: "codex_console_command_invalid" }
        : action("turn_interrupt", {});
    case "compact":
      return argument
        ? { kind: "error", code: "codex_console_command_invalid" }
        : action("compact_start", {});
    case "review":
      return !argument || argument === "uncommitted"
        ? action("review_start", { target: "uncommitted" })
        : argument === "base" || argument === "commit"
          ? action("review_start", { target: argument })
          : { kind: "error", code: "codex_console_command_invalid" };
    case "status":
      return argument
        ? { kind: "error", code: "codex_console_command_invalid" }
        : action("goal_get", {});
    default:
      return { kind: "error", code: "codex_console_command_unknown" };
  }
}
