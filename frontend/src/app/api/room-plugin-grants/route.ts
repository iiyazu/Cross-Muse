import { proxyGrantList } from "@/lib/server/grant-proxy";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return proxyGrantList(request);
}
