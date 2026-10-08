"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Check } from "lucide-react";

import { FamilyDot, familyLabel, familyOf } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Dialog } from "@/components/ui/overlay";
import { fetchRoomSetupOptions } from "@/lib/api";
import type { RoomCollaborationMode, RoomSetupOption, RoomSetupOptions } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

const FALLBACK_TEMPLATE_ID = "builtin.development";

function TemplateOption({
  template,
  checked,
  onSelect
}: {
  template: RoomSetupOption;
  checked: boolean;
  onSelect: () => void;
}) {
  const unavailable = template.available === false;
  return (
    <label
      className={cx(
        "flex cursor-pointer gap-3 rounded-md border px-3 py-2.5 transition-colors",
        checked ? "border-fg bg-hover" : "border-line hover:border-line-strong",
        unavailable && "cursor-not-allowed opacity-55"
      )}
    >
      <input checked={checked} className="sr-only" disabled={unavailable} name="roster" onChange={onSelect} type="radio" />
      <span
        aria-hidden="true"
        className={cx(
          "mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full border",
          checked ? "border-fg bg-inverse text-on-inverse" : "border-line-strong"
        )}
      >
        {checked ? <Check className="size-2.5" strokeWidth={3} /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium text-fg">{template.display_name}</span>
          <span className="text-xs text-fg-3">{template.participants.length} 位 Agent</span>
        </span>
        {template.description ? <span className="mt-0.5 block text-ui text-fg-3">{template.description}</span> : null}
        <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
          {template.participants.map((participant) => {
            const family = familyOf(participant.cli_kind);
            return (
              <span className="inline-flex items-center gap-1.5 text-xs text-fg-2" key={participant.role_id}>
                <FamilyDot family={family} />
                {participant.display_name}
                {familyLabel(family) ? <span className="text-fg-3">{familyLabel(family)}</span> : null}
              </span>
            );
          })}
        </span>
        {unavailable ? (
          <span className="mt-1 block text-xs text-attn">
            本机缺少：{(template.unavailable_providers ?? []).join("、") || "所需的 Agent"}
          </span>
        ) : null}
      </span>
    </label>
  );
}

export function CreateRoomDialog({
  open,
  onOpenChange,
  onCreated
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (roomId: string) => void;
}) {
  const createRoom = useRoomStore((state) => state.createRoom);
  const pending = useRoomStore((state) => state.roomCreatePending);
  const createError = useRoomStore((state) => state.roomCreateError);
  const [options, setOptions] = useState<RoomSetupOptions | null>(null);
  const [optionsError, setOptionsError] = useState(false);
  const [title, setTitle] = useState("");
  const [templateId, setTemplateId] = useState(FALLBACK_TEMPLATE_ID);
  const [mode, setMode] = useState<RoomCollaborationMode>("broadcast");
  const [leadRole, setLeadRole] = useState<string>("");
  const [review, setReview] = useState(false);
  const requestIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!open || options) return;
    const controller = new AbortController();
    fetchRoomSetupOptions({ signal: controller.signal })
      .then((payload) => {
        setOptions(payload);
        setOptionsError(false);
        const fallback = payload.roster_templates.find((template) => template.template_id === payload.default_roster_template_id);
        setTemplateId(payload.default_roster_template_id);
        setMode(fallback?.collaboration?.mode === "addressed" ? "addressed" : "broadcast");
        setLeadRole(fallback?.collaboration?.lead_role ?? "");
      })
      .catch(() => {
        if (!controller.signal.aborted) setOptionsError(true);
      });
    return () => controller.abort();
  }, [open, options]);

  useEffect(() => {
    if (open) requestIdRef.current = `ui_room_create_${crypto.randomUUID()}`;
  }, [open]);

  const template = options?.roster_templates.find((candidate) => candidate.template_id === templateId) ?? null;
  const leadCandidates = useMemo(() => {
    const seen = new Set<string>();
    return (template?.participants ?? []).flatMap((participant) => {
      if (!participant.role || seen.has(participant.role)) return [];
      seen.add(participant.role);
      return [{ role: participant.role, name: participant.display_name }];
    });
  }, [template]);
  const effectiveLead = leadCandidates.some((candidate) => candidate.role === leadRole) ? leadRole : leadCandidates[0]?.role ?? "";
  const reviewAvailable = (options?.review_policies ?? []).includes("cross_family");

  function selectTemplate(next: RoomSetupOption) {
    setTemplateId(next.template_id);
    setMode(next.collaboration?.mode === "addressed" ? "addressed" : "broadcast");
    setLeadRole(next.collaboration?.lead_role ?? "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || pending) return;
    const id = await createRoom(title, requestIdRef.current ?? undefined, templateId, {
      mode,
      lead_role: mode === "addressed" ? effectiveLead || null : null,
      review_policy: reviewAvailable && review ? "cross_family" : null
    });
    if (id) {
      setTitle("");
      onOpenChange(false);
      onCreated(id);
    }
  }

  return (
    <Dialog
      description="房间是一次协作的边界：同一批 Agent、同一份记录。"
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} variant="ghost">取消</Button>
          <Button disabled={!title.trim() || pending || template?.available === false} form="create-room-form" type="submit" variant="primary">
            {pending ? "正在创建…" : "创建房间"}
          </Button>
        </>
      }
      onOpenChange={onOpenChange}
      open={open}
      title="新建房间"
    >
      <form className="flex flex-col gap-5" id="create-room-form" onSubmit={submit}>
        <label className="flex flex-col gap-1.5">
          <span className="text-ui font-medium text-fg">名称</span>
          <input
            autoFocus
            className="h-9 rounded-md border border-line-strong bg-canvas px-3 text-sm text-fg outline-none placeholder:text-fg-3 focus:border-focus"
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="例如：支付模块重构"
            value={title}
          />
        </label>

        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1.5 p-0 text-ui font-medium text-fg">团队</legend>
          {optionsError ? (
            <p className="m-0 text-ui text-fg-3">读不到团队模板，将使用默认开发团队。</p>
          ) : !options ? (
            <p className="m-0 text-ui text-fg-3">正在读取团队模板…</p>
          ) : (
            options.roster_templates.map((candidate) => (
              <TemplateOption
                checked={candidate.template_id === templateId}
                key={candidate.template_id}
                onSelect={() => selectTemplate(candidate)}
                template={candidate}
              />
            ))
          )}
        </fieldset>

        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1.5 p-0 text-ui font-medium text-fg">协作方式</legend>
          <div className="grid grid-cols-2 gap-2">
            {([
              ["broadcast", "广播", "每位 Agent 都看到消息，各自决定是否接手"],
              ["addressed", "点名", "只有被 @ 的 Agent 处理，没点名时交给 lead"]
            ] as const).map(([value, label, hint]) => (
              <label
                className={cx(
                  "flex cursor-pointer flex-col gap-0.5 rounded-md border px-3 py-2",
                  mode === value ? "border-fg bg-hover" : "border-line hover:border-line-strong"
                )}
                key={value}
              >
                <input checked={mode === value} className="sr-only" name="mode" onChange={() => setMode(value)} type="radio" />
                <span className="text-sm font-medium text-fg">{label}</span>
                <span className="text-xs text-fg-3">{hint}</span>
              </label>
            ))}
          </div>
          {mode === "addressed" && leadCandidates.length ? (
            <label className="mt-1 flex items-center gap-2 text-ui text-fg-2">
              Lead
              <select
                className="h-8 rounded-md border border-line-strong bg-canvas px-2 text-ui text-fg"
                onChange={(event) => setLeadRole(event.target.value)}
                value={effectiveLead}
              >
                {leadCandidates.map((candidate) => (
                  <option key={candidate.role} value={candidate.role}>{candidate.name}</option>
                ))}
              </select>
            </label>
          ) : null}
        </fieldset>

        {reviewAvailable ? (
          <label className="flex cursor-pointer items-start gap-3">
            <input
              checked={review}
              className="peer sr-only"
              onChange={(event) => setReview(event.target.checked)}
              role="switch"
              type="checkbox"
            />
            <span
              aria-hidden="true"
              className={cx(
                "mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-focus",
                review ? "bg-proof-solid" : "bg-line-strong"
              )}
            >
              <span className={cx("size-4 rounded-full bg-white transition-transform", review && "translate-x-4")} />
            </span>
            <span>
              <span className="block text-sm font-medium text-fg">跨家族复核</span>
              <span className="block text-ui text-fg-3">
                模块通过宿主验证后，由另一家模型复核才算验收；没有其他家族的 Agent 时由你复核。创建后不能更改。
              </span>
            </span>
          </label>
        ) : null}

        {createError ? (
          <p className="m-0 rounded-md border border-fail-line bg-fail-soft px-3 py-2 text-ui text-fail" role="alert">
            {createError.status === 422 ? "房间设置不被接受（每个房间最多 8 位 Agent）。换一个团队再试。" : "房间没有创建成功，请稍后重试。"}
          </p>
        ) : null}
      </form>
    </Dialog>
  );
}
