import { proxyGrantRevoke } from "@/lib/server/grant-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ grantId: string }> }
) {
  const { grantId } = await context.params;
  return proxyGrantRevoke(request, grantId);
}
