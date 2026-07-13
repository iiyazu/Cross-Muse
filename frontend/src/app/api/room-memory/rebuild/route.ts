import { proxyMemoryRuntimeRebuild } from "@/lib/server/memory-runtime-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyMemoryRuntimeRebuild(request);
}
