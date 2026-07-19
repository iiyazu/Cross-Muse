"use client";

import {
  Check,
  Circle,
  Clipboard,
  Code2,
  Database,
  MessageSquare,
  Plus,
  ShieldCheck,
  Sparkles
} from "lucide-react";
import { useEffect, useState } from "react";

import { fetchBootstrap } from "@/lib/api";
import type { XmuseBootstrapProjection } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

const MEMORY_INSTALL_HINT = "python3.11 xmuse-setup.pyz install-memory --bundle <companion-bundle>";

const steps = [
  { key: "room", label: "创建第一个 Room", icon: Plus },
  { key: "message", label: "发送第一条消息", icon: MessageSquare },
  { key: "activity", label: "查看 Agent Plan / Tool / Skill", icon: Sparkles },
  { key: "evidence", label: "打开 Room / Runtime 工作台", icon: ShieldCheck },
  { key: "settled", label: "等待首轮协作收束", icon: Check }
] as const;

type RoomOnboardingProps = {
  mode: "start" | "guide";
  onCreateRoom: () => void;
  progress?: Partial<Record<(typeof steps)[number]["key"], boolean>>;
};

export function RoomOnboarding({ mode, onCreateRoom, progress = {} }: RoomOnboardingProps) {
  const onboardingCompleted = useRoomStore((state) => state.onboardingCompleted);
  const onboardingDismissed = useRoomStore((state) => state.onboardingDismissed);
  const onboardingOpen = useRoomStore((state) => state.onboardingOpen);
  const dismissOnboarding = useRoomStore((state) => state.dismissOnboarding);
  const [bootstrap, setBootstrap] = useState<XmuseBootstrapProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    let active = true;
    void fetchBootstrap()
      .then((value) => { if (active) setBootstrap(value); })
      .catch(() => { if (active) setBootstrap(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const expanded = onboardingOpen || !onboardingDismissed;
  if (mode === "guide" && !onboardingOpen && (onboardingCompleted || onboardingDismissed)) return null;
  if (mode === "start" && !expanded) {
    return (
      <section className="room-onboarding room-onboarding--compact" aria-label="开始使用 xmuse">
        <span>还没有 Room。创建后，每个 Agent 会独立观察共享事实。</span>
        <button className="room-primary-button" onClick={onCreateRoom} type="button"><Plus size={15} />新建 Room</button>
        <button className="room-quiet-button" onClick={() => useRoomStore.getState().openOnboarding()} type="button">查看本地能力</button>
      </section>
    );
  }

  const codexReady = bootstrap?.codex.launcher_available === true;
  const memoryInstalled = bootstrap?.memory.companion === "installed";
  const memoryInvalid = bootstrap?.memory.companion === "invalid";
  const memoryReady = memoryInstalled && bootstrap?.memory.runtime.state === "ready";
  const harnessReady = bootstrap?.execution.readiness.ready === true;
  const recommendation = bootstrap?.recommended_action === "repair_memory"
    ? "Memory companion 校验失败；请先使用安装器修复。"
    : bootstrap?.recommended_action === "install_memory"
      ? "MemoryOS 是可选能力；未安装不影响 Room 对话。"
      : bootstrap?.recommended_action === "open_room"
        ? "本地能力已读取，可以继续最近的 Room。"
        : "本地能力已读取，可以创建协作 Room。";

  async function copyInstallHint() {
    try {
      await navigator.clipboard.writeText(MEMORY_INSTALL_HINT);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }

  return (
    <section className={`room-onboarding room-onboarding--${mode}`} aria-labelledby={`room-onboarding-title-${mode}`}>
      <div className="room-onboarding-intro">
        <div className="room-onboarding-mark" aria-hidden="true"><Sparkles size={20} /></div>
        <div>
          <p className="room-overline">xmuse Workroom</p>
          <h2 id={`room-onboarding-title-${mode}`}>{mode === "start" ? "让多个 Codex Agent 在一个 Room 自然协作" : "完成第一轮协作"}</h2>
          <p>{mode === "start" ? "Room 是共享事实主线；Agent 工作台呈现每个 Codex 已有的 Goal、Plan、Tool 与 Skill 能力。" : "按需打开工作台查看 Agent 过程；Room 消息仍是唯一共享发言。"}</p>
        </div>
      </div>

      <div className="room-onboarding-checks" aria-label="本地能力状态">
        <span className={codexReady ? "is-ready" : "is-attention"}><Code2 size={14} />Codex {codexReady ? "已就绪" : "不可用"}</span>
        <span className={memoryReady ? "is-ready" : memoryInvalid ? "is-attention" : "is-muted"}><Database size={14} />MemoryOS {memoryReady ? "full-local" : memoryInvalid ? "需修复" : memoryInstalled ? "启动中" : "未安装（可选）"}</span>
        <span className={harnessReady ? "is-ready" : "is-attention"}><ShieldCheck size={14} />Harness {harnessReady ? "已就绪" : "受阻"}</span>
        {loading ? <span className="is-muted">正在读取本地能力…</span> : null}
        {!loading && !bootstrap ? <span className="is-attention">能力状态暂时不可读；Room 数据不会被覆盖</span> : null}
      </div>

      <p className="room-onboarding-recommendation">{recommendation}</p>
      {(!memoryInstalled || memoryInvalid) && !loading ? (
        <div className="room-onboarding-install">
          <code>{MEMORY_INSTALL_HINT}</code>
          <button className="room-quiet-button" onClick={() => void copyInstallHint()} type="button" aria-label="复制 MemoryOS companion 安装提示"><Clipboard size={14} />复制</button>
          <span aria-live="polite" className="room-visually-hidden">{copyStatus === "copied" ? "已复制安装提示" : copyStatus === "failed" ? "复制失败" : ""}</span>
        </div>
      ) : null}

      <div className="room-onboarding-steps" aria-label="首次使用进度">
        {steps.map((step) => {
          const Icon = step.icon;
          const done = onboardingCompleted || progress[step.key] === true;
          return <div className={done ? "is-done" : ""} key={step.key}><Icon size={15} />{done ? <Check size={12} /> : <Circle size={12} />}{step.label}</div>;
        })}
      </div>
      <div className="room-onboarding-actions">
        {mode === "start" ? <button className="room-primary-button" onClick={onCreateRoom} type="button"><Plus size={16} />创建协作 Room</button> : null}
        <button className="room-quiet-button" onClick={dismissOnboarding} type="button">{onboardingCompleted ? "关闭" : "稍后再看"}</button>
      </div>
      <p className="room-onboarding-footnote">浏览器只展示后端证明的安全能力状态，不会安装软件或直接执行 Agent / Runtime 动作。</p>
    </section>
  );
}
