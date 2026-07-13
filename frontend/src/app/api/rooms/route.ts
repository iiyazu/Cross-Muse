import { proxyRoomCreate } from "@/lib/server/room-write-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyRoomCreate(request);
}
