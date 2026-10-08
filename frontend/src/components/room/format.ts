import type { PresenceTone } from "@/components/ui/avatar";
import type { RoomActor, RoomParticipantState } from "@/lib/types";

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function sameDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate();
}

/** "14:05" for today, "10/5 14:05" otherwise. */
export function formatClock(value: string | null | undefined, now = new Date()): string {
  const date = parse(value);
  if (!date) return "";
  const clock = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  return sameDay(date, now) ? clock : `${date.getMonth() + 1}/${date.getDate()} ${clock}`;
}

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** Day separator label: 今天 / 昨天 / 10月5日 周日 (with the year when it differs). */
export function formatDay(value: string | null | undefined, now = new Date()): string {
  const date = parse(value);
  if (!date) return "";
  if (sameDay(date, now)) return "今天";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, yesterday)) return "昨天";
  const year = date.getFullYear() === now.getFullYear() ? "" : `${date.getFullYear()}年`;
  return `${year}${date.getMonth() + 1}月${date.getDate()}日 ${WEEKDAYS[date.getDay()]}`;
}

export function dayKey(value: string | null | undefined): string {
  const date = parse(value);
  return date ? `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}` : "";
}

/** Short relative age for list rows: 刚刚 / 5 分钟 / 3 小时 / 2 天, falling back to a date. */
export function formatAge(value: string | null | undefined, now = new Date()): string {
  const date = parse(value);
  if (!date) return "";
  const seconds = Math.max(0, Math.round((now.getTime() - date.getTime()) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} 小时`;
  if (seconds < 7 * 86_400) return `${Math.floor(seconds / 86_400)} 天`;
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

export function isHumanActor(actor: RoomActor): boolean {
  return actor.kind === "human" || actor.role === "human" || actor.role === "user";
}

export function isSystemActor(actor: RoomActor): boolean {
  return actor.kind === "system";
}

/** Presence dot for a participant's Room observation state. */
export function participantPresence(status: RoomParticipantState, active: boolean): PresenceTone {
  if (!active || status === "stopped") return null;
  if (status === "thinking" || status === "claimed") return "live";
  if (status === "runtime_recovery" || status === "claimed_expired" || status === "cancel_pending") return "attn";
  if (status === "exhausted") return "fail";
  return null;
}
