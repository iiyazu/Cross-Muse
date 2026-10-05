import { describe, expect, it, vi } from "vitest";

import {
  issuePluginGrant,
  listPluginGrants,
  normalizePluginGrant,
  normalizePluginGrantIssue,
  normalizePluginGrantList,
  revokePluginGrant
} from "./grant-api";

const CREATED_AT = "2026-10-05T12:00:00Z";
const EXPIRES_AT = "2026-10-05T12:10:00Z";
const PAIRING_EXPIRES_AT = "2026-10-05T12:02:00Z";

function grantPayload(overrides: Record<string, unknown> = {}) {
  return {
    grant_id: "grant_1",
    conversation_id: "conv-1",
    host: "claude-code",
    scope: "board.split.decide",
    status: "pending",
    created_at: CREATED_AT,
    activated_at: null,
    expires_at: EXPIRES_AT,
    revoked_at: null,
    last_used_at: null,
    use_count: 0,
    ...overrides
  };
}

function issuePayload(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "plugin_grant_issue/v1",
    grant: grantPayload(),
    pairing_code: "ABCD-EFGH",
    pairing_expires_at: PAIRING_EXPIRES_AT,
    ...overrides
  };
}

function listPayload(grants: unknown[]) {
  return {
    schema_version: "plugin_grant_list/v1",
    conversation_id: "conv-1",
    grants
  };
}

describe("plugin grant normalizers", () => {
  it("accepts the contract issue, list and Grant shapes", () => {
    const issue = normalizePluginGrantIssue(issuePayload());
    expect(issue.grant.grantId).toBe("grant_1");
    expect(issue.grant.scope).toBe("board.split.decide");
    expect(issue.pairingCode).toBe("ABCD-EFGH");
    expect(issue.pairingExpiresAt).toBe(PAIRING_EXPIRES_AT);

    const active = grantPayload({
      status: "active",
      activated_at: CREATED_AT,
      last_used_at: CREATED_AT,
      use_count: 3,
      host: "opencode"
    });
    const list = normalizePluginGrantList(listPayload([grantPayload(), active]));
    expect(list.conversationId).toBe("conv-1");
    expect(list.grants).toHaveLength(2);
    expect(list.grants[1]?.status).toBe("active");
    expect(list.grants[1]?.lastUsedAt).toBe(CREATED_AT);
    expect(list.grants[1]?.useCount).toBe(3);

    const revoked = normalizePluginGrant(
      grantPayload({ status: "revoked", revoked_at: EXPIRES_AT })
    );
    expect(revoked?.status).toBe("revoked");
    expect(revoked?.revokedAt).toBe(EXPIRES_AT);
  });

  it("treats an unknown status as expired behaviour with an unknown label", () => {
    const grant = normalizePluginGrant(grantPayload({ status: "future_status" }));
    expect(grant?.status).toBe("unknown");
  });

  it("rejects malformed issue payloads", () => {
    expect(() => normalizePluginGrantIssue(null)).toThrow();
    expect(() => normalizePluginGrantIssue({ ...issuePayload(), schema_version: "other/v9" })).toThrow();
    expect(() => normalizePluginGrantIssue(issuePayload({ pairing_code: "abcd-efgh" }))).toThrow();
    expect(() => normalizePluginGrantIssue(issuePayload({ pairing_code: "ABCD-EFG" }))).toThrow();
    expect(() => normalizePluginGrantIssue(issuePayload({ pairing_expires_at: "yesterday" }))).toThrow();
    expect(() => normalizePluginGrantIssue(issuePayload({ grant: null }))).toThrow();
  });

  it("rejects malformed grants without throwing for the whole list", () => {
    expect(normalizePluginGrant(null)).toBeNull();
    expect(normalizePluginGrant(grantPayload({ grant_id: "" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ host: "Claude Code" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ host: "../evil" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ scope: "board.split.approve" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ created_at: "2026-10-05 12:00:00" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ expires_at: null }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ activated_at: "soon" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ use_count: -1 }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ use_count: 1.5 }))).toBeNull();

    const list = normalizePluginGrantList(
      listPayload([grantPayload(), { grant_id: "broken" }, null])
    );
    expect(list.grants.map((grant) => grant.grantId)).toEqual(["grant_1"]);

    expect(() => normalizePluginGrantList({ ...listPayload([]), schema_version: "other/v9" })).toThrow();
    expect(() => normalizePluginGrantList({ ...listPayload([]), grants: "nope" })).toThrow();
  });
});

describe("plugin grant fetchers", () => {
  it("issues through the fixed Next route with exactly the contract keys", async () => {
    const fetcher = vi.fn(async () => Response.json(issuePayload()));
    await issuePluginGrant(
      { conversationId: "conv-1", host: "claude-code", ttlSeconds: 600 },
      { fetcher: fetcher as typeof fetch }
    );
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toBe("/api/room-plugin-grants");
    expect(calls[0][1]).toMatchObject({ method: "POST", cache: "no-store" });
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({
      conversation_id: "conv-1",
      host: "claude-code",
      scope: "board.split.decide",
      ttl_seconds: 600
    });
  });

  it("lists through the fixed Next route with an encoded room id", async () => {
    const fetcher = vi.fn(async () => Response.json(listPayload([grantPayload()])));
    const list = await listPluginGrants("conv/1", { fetcher: fetcher as typeof fetch });
    expect(list.grants).toHaveLength(1);
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe("/api/room-plugin-grants?conversation_id=conv%2F1");
    expect(calls[0][1]).toMatchObject({ method: "GET", cache: "no-store" });
  });

  it("revokes through the fixed Next route with exactly the room id body", async () => {
    const fetcher = vi.fn(async () =>
      Response.json(grantPayload({ status: "revoked", revoked_at: EXPIRES_AT }))
    );
    const grant = await revokePluginGrant("grant/1", "conv-1", {
      fetcher: fetcher as typeof fetch
    });
    expect(grant.status).toBe("revoked");
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe("/api/room-plugin-grants/grant%2F1/revoke");
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ conversation_id: "conv-1" });
  });

  it("preserves the upstream error code instead of the message", async () => {
    const fetcher = vi.fn(async () =>
      Response.json(
        { detail: { code: "plugin_grant_host_invalid", message: "server detail" } },
        { status: 422 }
      )
    );
    await expect(
      issuePluginGrant(
        { conversationId: "conv-1", host: "nope", ttlSeconds: 600 },
        { fetcher: fetcher as typeof fetch }
      )
    ).rejects.toMatchObject({ code: "plugin_grant_host_invalid", status: 422 });
  });
});
