import { describe, expect, it, vi } from "vitest";

import {
  listPluginGrants,
  normalizePluginGrant,
  normalizePluginGrantList,
  revokePluginGrant
} from "./grant-api";

const CREATED_AT = "2026-10-05T12:00:00Z";
const EXPIRES_AT = "2026-10-05T12:10:00Z";

function grantPayload(overrides: Record<string, unknown> = {}) {
  return {
    grant_id: "grant_1",
    conversation_ids: ["conv-1"],
    host: "claude-code",
    scopes: ["room.message", "board.split.decide"],
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

function listPayload(grants: unknown[], key: Record<string, string> = { conversation_id: "conv-1" }) {
  return {
    schema_version: "plugin_grant_list/v2",
    ...key,
    grants
  };
}

describe("plugin grant normalizers", () => {
  it("accepts the contract list and Grant shapes", () => {
    const active = grantPayload({
      status: "active",
      activated_at: CREATED_AT,
      last_used_at: CREATED_AT,
      use_count: 3,
      host: "opencode",
      conversation_ids: ["conv-1", "conv-2"]
    });
    const list = normalizePluginGrantList(listPayload([grantPayload(), active]));
    expect(list.grants).toHaveLength(2);
    expect(list.grants[0]?.scopes).toEqual(["room.message", "board.split.decide"]);
    expect(list.grants[1]?.status).toBe("active");
    expect(list.grants[1]?.conversationIds).toEqual(["conv-1", "conv-2"]);
    expect(list.grants[1]?.lastUsedAt).toBe(CREATED_AT);
    expect(list.grants[1]?.useCount).toBe(3);

    const byHost = normalizePluginGrantList(listPayload([grantPayload()], { host: "claude-code" }));
    expect(byHost.grants).toHaveLength(1);

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

  it("keeps an unknown scope as a fixed word, never the raw value", () => {
    const grant = normalizePluginGrant(grantPayload({ scopes: ["board.split.decide", "board.merge", "x.y"] }));
    expect(grant?.scopes).toEqual(["board.split.decide", "unknown"]);
  });

  it("rejects malformed grants without throwing for the whole list", () => {
    expect(normalizePluginGrant(null)).toBeNull();
    expect(normalizePluginGrant(grantPayload({ grant_id: "" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ host: "Claude Code" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ host: "../evil" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ scopes: [] }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ scopes: "board.split.decide" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ conversation_ids: "conv-1" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ conversation_ids: ["conv-1", ""] }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ conversation_ids: Array.from({ length: 17 }, (_, i) => `c${i}`) }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ created_at: "2026-10-05 12:00:00" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ expires_at: null }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ activated_at: "soon" }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ use_count: -1 }))).toBeNull();
    expect(normalizePluginGrant(grantPayload({ use_count: 1.5 }))).toBeNull();

    const list = normalizePluginGrantList(
      listPayload([grantPayload(), { grant_id: "broken" }, null])
    );
    expect(list.grants.map((grant) => grant.grantId)).toEqual(["grant_1"]);

    expect(() => normalizePluginGrantList({ ...listPayload([]), schema_version: "plugin_grant_list/v1" })).toThrow();
    expect(() => normalizePluginGrantList({ ...listPayload([]), grants: "nope" })).toThrow();
  });
});

describe("plugin grant fetchers", () => {
  it("lists by Room or by host through the fixed Next route, encoded", async () => {
    const fetcher = vi.fn(async () => Response.json(listPayload([grantPayload()])));
    const list = await listPluginGrants({ conversationId: "conv/1" }, { fetcher: fetcher as typeof fetch });
    expect(list.grants).toHaveLength(1);
    await listPluginGrants({ host: "claude-code" }, { fetcher: fetcher as typeof fetch });
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe("/api/room-plugin-grants?conversation_id=conv%2F1");
    expect(calls[0][1]).toMatchObject({ method: "GET", cache: "no-store" });
    expect(calls[1][0]).toBe("/api/room-plugin-grants?host=claude-code");
  });

  it("revokes through the fixed Next route with exactly the room id body", async () => {
    const fetcher = vi.fn(async () =>
      Response.json({
        schema_version: "plugin_grant_revoke/v2",
        grant: grantPayload({ status: "revoked", revoked_at: EXPIRES_AT })
      })
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
        { detail: { code: "room_conversation_unknown", message: "server detail" } },
        { status: 404 }
      )
    );
    await expect(
      listPluginGrants({ conversationId: "conv-1" }, { fetcher: fetcher as typeof fetch })
    ).rejects.toMatchObject({ code: "room_conversation_unknown", status: 404 });
  });
});
