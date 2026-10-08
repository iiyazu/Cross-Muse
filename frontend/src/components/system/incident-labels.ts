import type { RoomOperationsIncident } from "@/lib/types";

/**
 * The operations projection carries English developer prose in `title`/`detail`; the UI
 * localizes from the structured `kind`, `next_action` and `code` instead.
 */
const KIND_TITLE: Record<RoomOperationsIncident["kind"], string> = {
  runtime: "Room 运行时没有就绪",
  host: "宿主需要关注",
  memory: "记忆 sidecar 需要处理",
  observation: "有 Agent 的处理卡住了"
};

const NEXT_ACTION: Record<string, string> = {
  wait: "宿主正在自行处理，稍等即可",
  open_room: "打开对应房间查看",
  retry_observation: "在当前轮次里重试这位 Agent",
  recover_runtime: "恢复 Room Runtime",
  rebuild_memory_index: "重建记忆索引",
  repair_then_recover: "先修复环境，再恢复 Room Runtime"
};

export function incidentTitle(incident: RoomOperationsIncident): string {
  return KIND_TITLE[incident.kind] ?? "系统需要关注";
}

export function incidentNextStep(incident: RoomOperationsIncident): string {
  return NEXT_ACTION[incident.next_action] ?? "查看系统面板";
}
