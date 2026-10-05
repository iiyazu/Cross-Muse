import { proxyReviewDecision } from "@/lib/server/review-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ reviewId: string }> }
) {
  const { reviewId } = await context.params;
  return proxyReviewDecision(request, reviewId);
}
