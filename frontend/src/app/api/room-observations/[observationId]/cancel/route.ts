import { proxyRoomControl } from "@/lib/server/room-control-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ observationId: string }> }
) {
  const { observationId } = await context.params;
  return proxyRoomControl(request, observationId, "cancel");
}
