import { proxyBoardSplitDecision } from "@/lib/server/board-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ splitId: string }> }
) {
  const { splitId } = await context.params;
  return proxyBoardSplitDecision(request, splitId);
}
