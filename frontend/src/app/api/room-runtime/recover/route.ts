import { proxyRuntimeRecover } from "@/lib/server/runtime-recover-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyRuntimeRecover(request);
}
