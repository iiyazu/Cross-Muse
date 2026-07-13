import { proxyExecutionRunCancel } from "@/lib/server/execution-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ runId: string }> }
) {
  const { runId } = await context.params;
  return proxyExecutionRunCancel(request, runId);
}
