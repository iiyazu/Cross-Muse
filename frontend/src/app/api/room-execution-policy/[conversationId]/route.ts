import { proxyExecutionPolicy } from "@/lib/server/execution-proxy";

export const dynamic = "force-dynamic";

export async function PUT(
  request: Request,
  context: { params: Promise<{ conversationId: string }> }
) {
  const { conversationId } = await context.params;
  return proxyExecutionPolicy(request, conversationId);
}
