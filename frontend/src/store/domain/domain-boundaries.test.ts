import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { createCodexCacheSelector } from "./codex";
import { createExecutionCacheSelector } from "./execution";
import { createMemoryCacheSelector } from "./memory";
import { createRoomCacheSelector } from "./room";

const DOMAIN_DIRECTORY = path.resolve(process.cwd(), "src/store/domain");

describe("store domain boundaries", () => {
  it("keeps domain modules independent from components and sibling domains", () => {
    for (const name of fs.readdirSync(DOMAIN_DIRECTORY)) {
      if (!name.endsWith(".ts") || name.endsWith(".test.ts") || name === "index.ts") continue;
      const source = fs.readFileSync(path.join(DOMAIN_DIRECTORY, name), "utf8");
      expect(source, `${name} imports a component`).not.toMatch(/from\s+["']@\/components\//);
      expect(source, `${name} imports the concrete root store`).not.toMatch(
        /from\s+["']@\/store\/room-store["']/
      );
      expect(source, `${name} imports a sibling domain`).not.toMatch(
        /from\s+["']\.\/(?!shared["'])[^"']+["']/
      );
    }
  });

  it("preserves selected domain identities when unrelated root fields change", () => {
    const roomCache = { marker: "room" };
    const executionCache = { marker: "execution" };
    const memoryCache = { marker: "memory" };
    const codexCache = { marker: "codex" };
    const root = {
      roomsById: { room: roomCache },
      executionsByRoom: { room: executionCache },
      memoryByRoom: { room: memoryCache },
      codexByRoom: { room: codexCache },
      operations: null
    };
    const changed = { ...root, operations: { overall: "attention" } };

    expect(createRoomCacheSelector("room")(changed as never)).toBe(roomCache);
    expect(createExecutionCacheSelector("room")(changed as never)).toBe(executionCache);
    expect(createMemoryCacheSelector("room")(changed as never)).toBe(memoryCache);
    expect(createCodexCacheSelector("room")(changed as never)).toBe(codexCache);
  });

  it("returns null for uncached rooms instead of allocating fallback objects", () => {
    expect(createRoomCacheSelector("missing")({ roomsById: {} } as never)).toBeNull();
    expect(
      createExecutionCacheSelector("missing")({ executionsByRoom: {} } as never)
    ).toBeNull();
    expect(createMemoryCacheSelector("missing")({ memoryByRoom: {} } as never)).toBeNull();
    expect(createCodexCacheSelector("missing")({ codexByRoom: {} } as never)).toBeNull();
  });
});
