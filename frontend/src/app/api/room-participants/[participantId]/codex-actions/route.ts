import { proxyCodexAction } from "@/lib/server/codex-action-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ participantId: string }> }
) {
  const { participantId } = await context.params;
  return proxyCodexAction(request, participantId);
}
