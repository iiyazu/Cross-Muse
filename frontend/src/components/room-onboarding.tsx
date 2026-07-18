"use client";

import { Check, Circle, Database, MessageSquare, Plus, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchBootstrap } from "@/lib/api";
import type { XmuseBootstrapProjection } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

type RoomOnboardingProps = {
  onCreateRoom: () => void;
};

const steps = [
  { key: "room", label: "创建第一个 Room", icon: Plus },
  { key: "message", label: "发送一条消息", icon: MessageSquare },
  { key: "activity", label: "查看 Agent 活动", icon: Sparkles },
  { key: "evidence", label: "打开 Room / Runtime 工作台", icon: ShieldCheck }
] as const;

export function RoomOnboarding({ onCreateRoom }: RoomOnboardingProps) {
  const onboardingCompleted = useRoomStore((state) => state.onboardingCompleted);
  const onboardingDismissed = useRoomStore((state) => state.onboardingDismissed);
  const dismissOnboarding = useRoomStore((state) => state.dismissOnboarding);
  const [bootstrap, setBootstrap] = useState<XmuseBootstrapProjection | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void fetchBootstrap()
      .then((value) => { if (active) setBootstrap(value); })
      .catch(() => { if (active) setBootstrap(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (onboardingDismissed && !onboardingCompleted) {
    return (
      <section className="room-onboarding room-onboarding--compact" aria-label="开始使用 xmuse">
        <span>还没有 Room。</span>
        <button className="room-primary-button" onClick={onCreateRoom} type="button"><Plus size={15} />新建 Room</button>
        <button className="room-quiet-button" onClick={() => useRoomStore.getState().completeOnboarding()} type="button">重新查看引导</button>
      </section>
    );
  }

  const memoryReady = bootstrap?.memory.companion === "installed";
  const codexReady = bootstrap?.codex.launcher_available === true;
  return (
    <section className="room-onboarding" aria-labelledby="room-onboarding-title">
      <div className="room-onboarding-intro">
        <div className="room-onboarding-mark" aria-hidden="true"><Sparkles size={20} /></div>
        <div>
          <p className="room-overline">xmuse Workroom</p>
          <h2 id="room-onboarding-title">把几个 Codex Agent 放进同一个 Room</h2>
          <p>每个 Agent 保留自己的 Codex 工作台，同时共同观察 Room 的耐久事实。</p>
        </div>
      </div>
      <div className="room-onboarding-checks" aria-label="本地能力状态">
        <span className={codexReady ? "is-ready" : "is-attention"}><Check size={14} />Codex {codexReady ? "已就绪" : "待检查"}</span>
        <span className={memoryReady ? "is-ready" : "is-muted"}><Database size={14} />MemoryOS {memoryReady ? "full-local" : "可选"}</span>
        {loading ? <span className="is-muted">正在读取本地能力…</span> : null}
      </div>
      <div className="room-onboarding-steps">
        {steps.map((step, index) => {
          const Icon = step.icon;
          const done = index === 0 ? false : onboardingCompleted;
          return <div className={done ? "is-done" : ""} key={step.key}><Icon size={15} />{done ? <Check size={12} /> : <Circle size={12} />}{step.label}</div>;
        })}
      </div>
      <div className="room-onboarding-actions">
        <button className="room-primary-button" onClick={onCreateRoom} type="button"><Plus size={16} />创建协作 Room</button>
        <button className="room-quiet-button" onClick={dismissOnboarding} type="button">稍后再看</button>
      </div>
      <p className="room-onboarding-footnote">MemoryOS 只在本机安装可信 companion 后自动启用；未安装不影响 Room 对话。</p>
    </section>
  );
}

