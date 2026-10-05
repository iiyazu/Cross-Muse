import { proxyReviewMaterial } from "@/lib/server/review-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ reviewId: string }> }
) {
  const { reviewId } = await context.params;
  return proxyReviewMaterial(request, reviewId);
}
