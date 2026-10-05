import { proxyGrantIssue, proxyGrantList } from "@/lib/server/grant-proxy";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return proxyGrantList(request);
}

export function POST(request: Request) {
  return proxyGrantIssue(request);
}
