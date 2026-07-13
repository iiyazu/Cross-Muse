import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyRoomCreate, proxyRoomMessage } from "./room-write-proxy";

function request(
  path: string,
  payload: unknown,
  options: { signal?: AbortSignal; contentLength?: string } = {}
) {
  return new Request(`http://127.0.0.1:3000${path}`, {
    method: "POST",
    headers: {
      Host: "127.0.0.1:3000",
      Origin: "http://127.0.0.1:3000",
      "Content-Type": "application/json",
      ...(options.contentLength ? { "Content-Length": options.contentLength } : {})
    },
    body: JSON.stringify(payload),
    signal: options.signal
  });
}

beforeEach(() => {
  process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
  process.env.XMUSE_CHAT_API_BASE_URL = "http://127.0.0.1:8201/api/chat";
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL;
});

describe("fixed Room create/message proxies", () => {
  it("forwards an idempotent create and a bounded message with the server-only token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json({ id: "conv-1", client_request_id: "create-1" }, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ client_request_id: "message-1", message: { id: "msg-1" } }, { status: 201 }));

    const create = await proxyRoomCreate(request("/api/rooms", {
      title: "Acceptance Room",
      client_request_id: "create-1",
      initial_participants: [
        { role: "architect", cli_kind: "codex" },
        { role: "review", provider_id: "codex", cli_kind: "codex" }
      ]
    }));
    const message = await proxyRoomMessage(request("/api/rooms/conv-1/messages", {
      message: "hello Room",
      client_request_id: "message-1"
    }), "conv/one");

    expect(create.status).toBe(201);
    expect(message.status).toBe(201);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8201/api/chat/conversations");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8201/api/chat/threads/conv%2Fone/messages");
    for (const call of fetchMock.mock.calls) {
      expect(call[1]).toEqual(expect.objectContaining({
        redirect: "manual",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        }
      }));
    }
    expect(JSON.stringify(await create.json())).not.toContain("server-secret");
  });

  it("releases the deadline and caller-abort listener after a completed request", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ id: "conv-1" }, { status: 201 })
    );
    const incoming = request("/api/rooms", {
      title: "Cleanup",
      client_request_id: "create-cleanup"
    });
    const removeListenerSpy = vi.spyOn(incoming.signal, "removeEventListener");

    const response = await proxyRoomCreate(incoming);

    expect(response.status).toBe(201);
    expect(vi.getTimerCount()).toBe(0);
    expect(removeListenerSpy).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("rejects arbitrary fields, non-Codex participants, oversized messages, and public upstreams", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyRoomCreate(request("/api/rooms", {
      title: "Bad",
      client_request_id: "create-1",
      href: "http://evil.invalid"
    }))).status).toBe(400);
    expect((await proxyRoomCreate(request("/api/rooms", {
      title: "Bad",
      client_request_id: "create-2",
      initial_participants: [{ role: "remote", cli_kind: "a2a" }]
    }))).status).toBe(400);
    expect((await proxyRoomMessage(request("/api/rooms/conv/messages", {
      message: "hello",
      client_request_id: "message-1"
    }, { contentLength: String(41 * 1024) }), "conv")).status).toBe(413);

    for (const upstream of [
      "https://example.com/api/chat",
      "http://user:pass@127.0.0.1:8201/api/chat",
      "http://127.0.0.1:8201/api/chat?target=evil",
      "http://127.0.0.1:8201/api/chat#fragment",
      "http://127.0.0.1:8201/arbitrary"
    ]) {
      process.env.XMUSE_CHAT_API_BASE_URL = upstream;
      expect((await proxyRoomCreate(request("/api/rooms", {
        title: "No unsafe upstream",
        client_request_id: "create-3"
      }))).status).toBe(503);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never falls back to NEXT_PUBLIC upstream configuration", async () => {
    delete process.env.XMUSE_CHAT_API_BASE_URL;
    process.env.NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL = "http://evil.invalid/api/chat";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ id: "conv-1" }, { status: 201 }));

    await proxyRoomCreate(request("/api/rooms", {
      title: "Fixed loopback",
      client_request_id: "create-fixed"
    }));

    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8201/api/chat/conversations");
  });

  it("separates caller abort from the ten-second upstream deadline", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) => new Promise((_resolve, reject) => {
        if (init?.signal?.aborted) {
          reject(new DOMException("aborted", "AbortError"));
          return;
        }
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      })
    );
    const client = new AbortController();
    const clientPending = proxyRoomCreate(request("/api/rooms", {
      title: "Abort",
      client_request_id: "create-abort"
    }, { signal: client.signal }));
    await Promise.resolve();
    client.abort();
    const clientResponse = await clientPending;
    expect(clientResponse.status).toBe(499);
    expect(await clientResponse.json()).toMatchObject({ detail: { code: "room_create_client_aborted" } });

    vi.useFakeTimers();
    const deadlinePending = proxyRoomCreate(request("/api/rooms", {
      title: "Timeout",
      client_request_id: "create-timeout"
    }));
    await vi.advanceTimersByTimeAsync(10_000);
    const deadlineResponse = await deadlinePending;
    expect(deadlineResponse.status).toBe(504);
    expect(await deadlineResponse.json()).toMatchObject({ detail: { code: "room_create_upstream_timeout" } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("cancels an upstream response stream larger than one MiB", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(1024 * 1024 + 1));
      },
      cancel
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(stream, { status: 200 }));
    const response = await proxyRoomCreate(request("/api/rooms", {
      title: "Large response",
      client_request_id: "create-large-response"
    }));

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      detail: { code: "room_create_upstream_response_too_large" }
    });
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
