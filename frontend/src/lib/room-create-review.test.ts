import { describe, expect, it, vi } from "vitest";

import { createConversation } from "./api";

describe("createConversation review_policy", () => {
  it("forwards review_policy inside collaboration only when set", async () => {
    const fetcher = vi.fn(async (_input: unknown, _init?: RequestInit) => Response.json({ id: "conv-1" }));
    await createConversation("R", {
      fetcher: fetcher as typeof fetch,
      clientRequestId: "c1",
      rosterTemplateId: "builtin.development",
      collaboration: { mode: "broadcast", review_policy: "cross_family" }
    });
    const body = JSON.parse(String((fetcher.mock.calls[0][1] as RequestInit | undefined)?.body ?? "{}"));
    expect(body.collaboration).toEqual({ mode: "broadcast", review_policy: "cross_family" });

    fetcher.mockClear();
    await createConversation("R", {
      fetcher: fetcher as typeof fetch,
      clientRequestId: "c2",
      rosterTemplateId: "builtin.development",
      collaboration: { mode: "broadcast" }
    });
    const plain = JSON.parse(String((fetcher.mock.calls[0][1] as RequestInit | undefined)?.body ?? "{}"));
    expect(plain.collaboration).toEqual({ mode: "broadcast" });
  });
});
