const MAX_UPSTREAM_RESPONSE_BYTES = 1024 * 1024;

export type FixedRoomProxyConfig<T> = {
  request: Request;
  upstreamPath: string;
  maxBodyBytes: number;
  timeoutMs: number;
  codePrefix: string;
  normalizeBody: (value: unknown) => T | null;
  upstreamMethod?: "POST" | "PUT";
};

export function proxyJsonError(
  status: number,
  code: string,
  message: string
): Response {
  return Response.json(
    { detail: { code, message } },
    { status, headers: { "Cache-Control": "no-store" } }
  );
}

function loopbackHostname(value: string): boolean {
  const normalized = value.toLowerCase().replace(/\.$/, "");
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "[::1]";
}

function sameLoopbackOrigin(request: Request): boolean {
  const host = request.headers.get("host")?.trim().toLowerCase();
  const origin = request.headers.get("origin")?.trim();
  if (!host || !origin) return false;
  try {
    const originUrl = new URL(origin);
    const hostUrl = new URL(`${originUrl.protocol}//${host}`);
    return (
      originUrl.protocol === "http:" &&
      hostUrl.protocol === "http:" &&
      loopbackHostname(originUrl.hostname) &&
      loopbackHostname(hostUrl.hostname) &&
      originUrl.host.toLowerCase() === hostUrl.host.toLowerCase()
    );
  } catch {
    return false;
  }
}

function isJsonContentType(value: string | null): boolean {
  return value?.split(";", 1)[0].trim().toLowerCase() === "application/json";
}

async function readBoundedBytes(
  stream: ReadableStream<Uint8Array> | null,
  maximum: number,
  advertisedLength: string | null
): Promise<Uint8Array> {
  const advertised = Number(advertisedLength ?? "0");
  if (Number.isFinite(advertised) && advertised > maximum) {
    throw new Error("body_too_large");
  }
  if (!stream) return new Uint8Array();
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > maximum) {
      await reader.cancel();
      throw new Error("body_too_large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function upstreamBaseUrl(): string | null {
  const configured =
    process.env.XMUSE_CHAT_API_BASE_URL?.trim() ||
    "http://127.0.0.1:8201/api/chat";
  try {
    const url = new URL(configured);
    if (
      url.protocol !== "http:" ||
      !loopbackHostname(url.hostname) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname.replace(/\/+$/, "") !== "/api/chat"
    ) return null;
    return url.toString().replace(/\/+$/, "");
  } catch {
    return null;
  }
}

function safeContentType(value: string | null): string {
  if (!value) return "application/json";
  const mime = value.split(";", 1)[0].trim().toLowerCase();
  return mime === "application/json" ? value : "application/json";
}

export async function proxyFixedRoomWrite<T>(
  config: FixedRoomProxyConfig<T>
): Promise<Response> {
  const { request, codePrefix } = config;
  if (!sameLoopbackOrigin(request)) {
    return proxyJsonError(403, `${codePrefix}_origin_forbidden`, "request Origin does not match loopback Host");
  }
  if (!isJsonContentType(request.headers.get("content-type"))) {
    return proxyJsonError(415, `${codePrefix}_content_type_invalid`, "application/json is required");
  }

  let raw: Uint8Array;
  try {
    raw = await readBoundedBytes(
      request.body,
      config.maxBodyBytes,
      request.headers.get("content-length")
    );
  } catch (error) {
    if (request.signal.aborted) {
      return proxyJsonError(499, `${codePrefix}_client_aborted`, "client closed the request");
    }
    const tooLarge = error instanceof Error && error.message === "body_too_large";
    return proxyJsonError(
      tooLarge ? 413 : 400,
      tooLarge ? `${codePrefix}_body_too_large` : `${codePrefix}_json_invalid`,
      tooLarge ? "request body is too large" : "request body must be valid JSON"
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return proxyJsonError(400, `${codePrefix}_json_invalid`, "request body must be valid JSON");
  }
  const normalized = config.normalizeBody(parsed);
  if (!normalized) {
    return proxyJsonError(400, `${codePrefix}_payload_invalid`, "request payload is invalid");
  }

  const token = process.env.XMUSE_OPERATOR_TOKEN?.trim();
  if (!token) {
    return proxyJsonError(503, "operator_auth_not_configured", "operator authentication is not configured");
  }
  const base = upstreamBaseUrl();
  if (!base) {
    return proxyJsonError(503, `${codePrefix}_upstream_invalid`, "Room API upstream is not a fixed loopback HTTP URL");
  }
  if (!config.upstreamPath || config.upstreamPath.startsWith("/") || config.upstreamPath.includes("?")) {
    return proxyJsonError(500, `${codePrefix}_route_invalid`, "fixed upstream route is invalid");
  }

  const controller = new AbortController();
  let deadlineExpired = false;
  let clientAborted = request.signal.aborted;
  const timeout = setTimeout(() => {
    deadlineExpired = true;
    controller.abort();
  }, config.timeoutMs);
  const abortFromClient = () => {
    clientAborted = true;
    controller.abort();
  };
  request.signal.addEventListener("abort", abortFromClient, { once: true });
  if (clientAborted) {
    controller.abort();
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abortFromClient);
    return proxyJsonError(499, `${codePrefix}_client_aborted`, "client closed the request");
  }
  try {
    const response = await fetch(`${base}/${config.upstreamPath}`, {
      method: config.upstreamMethod ?? "POST",
      headers: {
        "Content-Type": "application/json",
        "X-XMuse-Operator-Token": token
      },
      body: JSON.stringify(normalized),
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal
    });
    if (response.status >= 300 && response.status < 400) {
      await response.body?.cancel();
      return proxyJsonError(502, `${codePrefix}_upstream_redirect`, "upstream redirect was rejected");
    }
    let bytes: Uint8Array;
    try {
      bytes = await readBoundedBytes(
        response.body,
        MAX_UPSTREAM_RESPONSE_BYTES,
        response.headers.get("content-length")
      );
    } catch {
      return proxyJsonError(502, `${codePrefix}_upstream_response_too_large`, "upstream response exceeds 1MiB");
    }
    return new Response(new TextDecoder().decode(bytes), {
      status: response.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": safeContentType(response.headers.get("content-type"))
      }
    });
  } catch {
    if (deadlineExpired) {
      return proxyJsonError(504, `${codePrefix}_upstream_timeout`, "Room API upstream timed out");
    }
    if (clientAborted) {
      return proxyJsonError(499, `${codePrefix}_client_aborted`, "client closed the request");
    }
    return proxyJsonError(502, `${codePrefix}_upstream_unavailable`, "Room API upstream is unavailable");
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abortFromClient);
  }
}

export function exactObject(value: unknown, keys: string[]): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Object.keys(record).sort().join("\u0000") === [...keys].sort().join("\u0000")
    ? record
    : null;
}

export function boundedText(value: unknown, maximum = 200): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned && cleaned.length <= maximum ? cleaned : null;
}
