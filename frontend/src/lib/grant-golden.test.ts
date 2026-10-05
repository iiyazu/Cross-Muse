import fs from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  normalizePluginGrantIssue,
  normalizePluginGrantList,
  revokePluginGrant
} from "./grant-api";

const GOLDEN_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/plugin_grant_v1");

function golden(name: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(path.join(GOLDEN_DIR, `${name}.json`), "utf8")) as Record<
    string,
    unknown
  >;
}

describe("plugin grant backend golden responses", () => {
  it("normalizes the issue response with its pairing code", () => {
    const issue = normalizePluginGrantIssue(golden("issue"));
    expect(issue.grant.status).toBe("pending");
    expect(issue.pairingCode).toMatch(/^[A-Z0-9]{4}-[A-Z0-9]{4}$/);
  });

  it("normalizes a list that holds every status", () => {
    const list = normalizePluginGrantList(golden("list"));
    expect(new Set(list.grants.map((grant) => grant.status))).toEqual(
      new Set(["pending", "active", "expired", "revoked"])
    );
    const raw = golden("list").grants as unknown[];
    expect(list.grants).toHaveLength(raw.length);
  });

  it("reads the operator revoke response as the revoked grant", async () => {
    const fetcher = vi.fn(async () => Response.json(golden("operator_revoke")));
    const grant = await revokePluginGrant("grant-1", "conv-1", {
      fetcher: fetcher as typeof fetch
    });
    expect(grant.status).toBe("revoked");
    expect(grant.revokedAt).not.toBeNull();
  });

  it("never carries a secret into the normalized issue or list", () => {
    const text = JSON.stringify([
      normalizePluginGrantIssue(golden("issue")).grant,
      normalizePluginGrantList(golden("list"))
    ]);
    expect(text).not.toContain("xpg_");
  });
});
