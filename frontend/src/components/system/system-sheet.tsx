"use client";

import { useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { X } from "lucide-react";

import { formatClock } from "@/components/room/format";
import { TrustGlyph } from "@/components/board/trust";
import type { StepTone } from "@/components/board/model";
import { Button, IconButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { ConfirmDialog, Sheet } from "@/components/ui/overlay";
import type { RoomExecutionPolicyMode } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

import { incidentNextStep, incidentTitle } from "./incident-labels";
import { PluginGrants } from "./plugin-grants";

const STATE_TONE: Record<string, StepTone> = {
  healthy: "pass",
  ready: "pass",
  attention: "attn",
  recovering: "running",
  rebuilding: "running",
  starting: "running",
  blocked: "fail",
  failed: "fail",
  stopped: "empty",
  disabled: "empty",
  unknown: "empty"
};

const STATE_LABEL: Record<string, string> = {
  healthy: "正常",
  ready: "就绪",
  attention: "需要关注",
  recovering: "恢复中",
  rebuilding: "重建中",
  starting: "启动中",
  blocked: "已阻塞",
  failed: "失败",
  stopped: "已停止",
  stopping: "停止中",
  disabled: "未启用",
  unknown: "未知"
};

function Row({ label, state, note }: { label: string; state: string; note?: string | null }) {
  return (
    <li className="flex items-center gap-2.5 py-1 text-ui">
      <TrustGlyph tone={STATE_TONE[state] ?? "empty"} />
      <span className="w-24 shrink-0 text-fg-2">{label}</span>
      <span className="text-fg">{STATE_LABEL[state] ?? state}</span>
      {note ? <span className="min-w-0 truncate text-xs text-fg-3">{note}</span> : null}
    </li>
  );
}

function Section({ title, label, children }: { title: string; label?: string; children: React.ReactNode }) {
  return (
    <section aria-label={label ?? title} className="border-t border-line px-4 py-4 first:border-t-0">
      <h3 className="m-0 mb-2.5 text-xs font-medium tracking-wide text-fg-3">{title}</h3>
      {children}
    </section>
  );
}

/** Host health and guarded recovery, plus this room's execution policy and plugin grants. */
export function SystemSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { operations, recoverPending, recoverError, rebuildPending, roomId, execution, memory, executionPending } = useRoomStore(useShallow((state) => ({
    operations: state.operations,
    recoverPending: state.runtimeRecoverPending,
    recoverError: state.runtimeRecoverError,
    rebuildPending: state.memoryRebuildPending,
    roomId: state.selectedRoomId,
    execution: state.selectedRoomId ? state.executionsByRoom[state.selectedRoomId]?.list ?? null : null,
    memory: state.selectedRoomId ? state.memoryByRoom[state.selectedRoomId]?.projection ?? null : null,
    executionPending: state.executionActionPending
  })));
  const recover = useRoomStore((state) => state.recoverRuntime);
  const rebuild = useRoomStore((state) => state.rebuildMemoryIndex);
  const updatePolicy = useRoomStore((state) => state.updateExecutionPolicy);
  const [confirm, setConfirm] = useState<"recover" | "rebuild" | { policy: RoomExecutionPolicyMode } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const recoverAction = operations?.actions.recover_runtime ?? null;
  const rebuildAction = operations?.actions.rebuild_memory_index ?? null;
  const policy = execution?.policy ?? null;

  return (
    <Sheet onOpenChange={onOpenChange} open={open} title="系统">
      <div className="flex h-12 shrink-0 items-center border-b border-line px-2">
        <h2 className="m-0 flex-1 pl-2 text-sm font-semibold text-fg">系统</h2>
        <IconButton label="关闭系统面板" onClick={() => onOpenChange(false)} size="sm">
          <X aria-hidden="true" className="size-4" />
        </IconButton>
      </div>
      <div className="scrollbar-quiet min-h-0 flex-1 overflow-y-auto">
        <Section label="运行与恢复" title="本机运行时">
          {operations ? (
            <>
              <ul className="m-0 list-none p-0">
                <Row label="整体" state={operations.overall} />
                <Row label="Room Runner" note={operations.runtime.runner.code} state={operations.runtime.runner.state} />
                <Row label="Room MCP" note={operations.runtime.mcp.code} state={operations.runtime.mcp.state} />
                <Row label="宿主" note={operations.runtime.host.code} state={operations.runtime.host.state} />
                <Row label="记忆 sidecar" note={operations.runtime.memory.code} state={operations.runtime.memory.enabled ? operations.runtime.memory.state : "disabled"} />
              </ul>
              <p className="m-0 mt-2 text-xs text-fg-3">
                正在投递 {operations.counts.active_delivery} · 待恢复 {operations.counts.recovery_pending} · 尝试耗尽 {operations.counts.exhausted}
              </p>
              {operations.incidents.length ? (
                <ul className="m-0 mt-3 list-none space-y-2 p-0">
                  {operations.incidents.map((incident) => (
                    <li className={cx("rounded-md border px-3 py-2 text-xs", incident.severity === "blocked" ? "border-fail-line bg-fail-soft" : "border-attn-line bg-attn-soft")} key={incident.incident_id}>
                      <p className="m-0 flex items-baseline gap-2 font-medium text-fg">
                        {incidentTitle(incident)}
                        <code className="font-mono text-[11px] font-normal text-fg-3">{incident.code}</code>
                      </p>
                      <p className="m-0 mt-0.5 text-fg-2">
                        {incident.conversation_title ? `${incident.conversation_title} · ` : ""}
                        {incident.participant_display_name ? `${incident.participant_display_name} · ` : ""}
                        {incident.started_at ? `${formatClock(incident.started_at)} 开始 · ` : ""}
                        下一步：{incidentNextStep(incident)}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                {recoverAction?.available ? (
                  <Button disabled={recoverPending} onClick={() => setConfirm("recover")} size="sm" variant={operations.overall === "healthy" ? "secondary" : "attn"}>
                    {recoverAction.mode === "start" ? "启动 Room Runtime" : "恢复 Room Runtime"}
                  </Button>
                ) : null}
                {rebuildAction?.available ? (
                  <Button disabled={rebuildPending || rebuildAction.pending} onClick={() => setConfirm("rebuild")} size="sm">
                    重建记忆索引
                  </Button>
                ) : null}
              </div>
              {notice ? <p className="m-0 mt-2 text-xs text-fg-2" role="status">{notice}</p> : null}
              {recoverError ? <p className="m-0 mt-2 text-xs text-fail" role="alert">恢复请求没有成功，已刷新为最新状态。</p> : null}
            </>
          ) : <p className="m-0 text-ui text-fg-3" role="status">正在读取运行时状态…</p>}
        </Section>

        {roomId && policy ? (
          <Section title="本房间 · 执行方式">
            <div aria-label="执行方式" className="inline-flex rounded-md border border-line p-0.5" role="radiogroup">
              {(["manual", "consensus"] as const).map((mode) => {
                const allowed = policy.actions.update.available && policy.actions.update.allowed_modes.includes(mode);
                const checked = policy.mode === mode;
                return (
                  <button
                    aria-checked={checked}
                    className={cx("rounded-sm px-2.5 py-1 text-ui", checked ? "bg-selected font-medium text-fg" : "text-fg-3 hover:text-fg disabled:opacity-40")}
                    disabled={!checked && (!allowed || executionPending !== null)}
                    key={mode}
                    onClick={() => !checked && setConfirm({ policy: mode })}
                    role="radio"
                    type="button"
                  >
                    {mode === "manual" ? "每次由你决定" : "Agent 全体共识"}
                  </button>
                );
              })}
            </div>
            <p className="m-0 mt-2 text-xs text-fg-3">
              {policy.mode === "consensus"
                ? "所有同伴都赞成同一份补丁、且符合低风险策略时自动执行；不满足就回到由你决定。"
                : "每个执行候选都要你确认后才会执行。"}
              {!policy.automatic_execution_available ? " 本机没有开启共识执行。" : ""}
            </p>
          </Section>
        ) : null}

        {roomId ? (
          <Section title="本房间 · 插件授权">
            <PluginGrants roomId={roomId} />
          </Section>
        ) : null}

        {memory ? (
          <Section title="本房间 · 记忆">
            <ul className="m-0 list-none p-0">
              <Row label="来源记忆" note={memory.runtime.code} state={memory.enabled ? memory.runtime.state : "disabled"} />
            </ul>
            <p className="m-0 mt-2 text-xs text-fg-3">
              最近 {memory.recent_recalls.length} 次召回 · {memory.pending_candidate_total} 条候选待定 · 同步积压 {memory.sync.backlog}
            </p>
          </Section>
        ) : null}
      </div>

      <ConfirmDialog
        confirmLabel={confirm === "recover" ? "确认中断并恢复" : confirm === "rebuild" ? "确认重建" : "确认切换"}
        description={confirm === "recover"
          ? "会中断正在进行的 Agent 投递并重启 Room Runtime。房间记录不受影响，被中断的处理会按规则重试。"
          : confirm === "rebuild"
            ? "会停止记忆 sidecar、清掉派生索引并从房间记录重新回放。房间记录本身不受影响。"
            : "切换后对之后的执行候选生效。"}
        onConfirm={async () => {
          if (confirm === "recover" && recoverAction) {
            const ok = await recover(recoverAction);
            setNotice(ok ? "恢复请求已提交，状态会在刷新后更新。" : null);
          } else if (confirm === "rebuild" && rebuildAction) {
            const ok = await rebuild(rebuildAction);
            setNotice(ok ? "重建请求已提交。" : "重建请求没有成功，已刷新状态。");
          } else if (confirm && typeof confirm === "object" && policy) {
            await updatePolicy(confirm.policy, policy.actions.update);
          }
          setConfirm(null);
        }}
        onOpenChange={(next) => { if (!next) setConfirm(null); }}
        open={confirm !== null}
        pending={recoverPending || rebuildPending || executionPending !== null}
        title={confirm === "recover"
          ? (recoverAction?.mode === "start" ? "启动 Room Runtime？" : "恢复 Room Runtime？")
          : confirm === "rebuild" ? "重建记忆索引？" : "切换执行方式？"}
        tone={confirm === "recover" || confirm === "rebuild" ? "danger" : "primary"}
      />
    </Sheet>
  );
}
