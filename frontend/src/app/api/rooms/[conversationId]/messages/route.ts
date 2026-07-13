import { proxyRoomMessage } from "@/lib/server/room-write-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ conversationId: string }> }
) {
  const { conversationId } = await context.params;
  return proxyRoomMessage(request, conversationId);
}
