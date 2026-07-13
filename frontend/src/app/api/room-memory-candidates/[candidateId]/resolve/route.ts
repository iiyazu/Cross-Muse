import { proxyMemoryCandidateResolve } from "@/lib/server/memory-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ candidateId: string }> }
) {
  const { candidateId } = await context.params;
  return proxyMemoryCandidateResolve(request, candidateId);
}
