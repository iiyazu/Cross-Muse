import fs from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { normalizePluginGrantList, revokePluginGrant } from "./grant-api";

const GOLDEN_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/plugin_grant_v2");

function golden(name: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(path.join(GOLDEN_DIR, `${name}.json`), "utf8")) as Record<
    string,
    unknown
  >;
}

describe("plugin grant backend golden responses", () => {
  it("normalizes a list that holds every status", () => {
    const list = normalizePluginGrantList(golden("list"));
    expect(new Set(list.grants.map((grant) => grant.status))).toEqual(
      new Set(["pending", "active", "expired", "revoked"])
    );
    const raw = golden("list").grants as unknown[];
    expect(list.grants).toHaveLength(raw.length);
    expect(list.grants.every((grant) => grant.conversationIds.length > 0)).toBe(true);
  });

  it("reads the operator revoke response as the revoked grant", async () => {
    const fetcher = vi.fn(async () => Response.json(golden("operator_revoke")));
    const grant = await revokePluginGrant("grant-1", "conv-1", {
      fetcher: fetcher as typeof fetch
    });
    expect(grant.status).toBe("revoked");
    expect(grant.revokedAt).not.toBeNull();
  });

  it("never carries a secret or pairing code into a normalized list", () => {
    const text = JSON.stringify(normalizePluginGrantList(golden("list")));
    expect(text).not.toContain("xpg_");
    expect(text).not.toContain("pairing");
  });
});
