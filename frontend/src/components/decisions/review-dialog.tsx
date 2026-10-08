"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { DiffView } from "@/components/ui/diff-view";
import { Dialog } from "@/components/ui/overlay";
import {
  fetchBoardReviewMaterial,
  isValidReviewPath,
  reviewDecideDescriptorValid,
  reviewFindingsHaveBlockerOrMajor,
  validateReviewFindingsForSubmit,
  validateReviewSummary,
  type ReviewFindingDraft
} from "@/lib/board-review-api";
import { boardReviewErrorText, boardReviewSeverityLabel, shortHeadCommit } from "@/lib/board-review-labels";
import type { BoardReviewMaterial } from "@/lib/board-review-types";
import type { BoardModule } from "@/lib/board-types";
import { useRoomStore } from "@/store/room-store";

const SEVERITIES = ["blocker", "major", "minor"] as const;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}


/**
 * Operator review (§3.10, §8.1, §8.2). The verdict is bound to the exact material on screen:
 * `expected_digest` is the material's digest and must equal the projection's `Review.digest`.
 * Truncated material can only be objected to, never endorsed.
 */
export function ReviewDialog({
  roomId,
  module,
  open,
  onOpenChange
}: {
  roomId: string;
  module: BoardModule;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const review = module.review;
  const reviewId = review.review_id ?? "";
  const submit = useRoomStore((state) => state.submitBoardReviewDecision);
  const actionError = useRoomStore((state) => state.boardActionError);
  const [material, setMaterial] = useState<BoardReviewMaterial | null>(null);
  const [materialFailed, setMaterialFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [verdict, setVerdict] = useState<"endorse" | "object">("endorse");
  const [summary, setSummary] = useState("");
  const [findings, setFindings] = useState<ReviewFindingDraft[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [triedSubmit, setTriedSubmit] = useState(false);

  useEffect(() => {
    if (!open || !reviewId) return;
    const controller = new AbortController();
    fetchBoardReviewMaterial(roomId, reviewId, { signal: controller.signal })
      .then((value) => {
        setMaterial(value);
        setMaterialFailed(false);
        if (value.patch.truncated) setVerdict("object");
      })
      .catch(() => {
        if (!controller.signal.aborted) setMaterialFailed(true);
      });
    return () => controller.abort();
  }, [open, reviewId, roomId, attempt]);

  const truncated = material?.patch.truncated ?? false;
  const digestMatches = Boolean(material && review.digest && material.digest === review.digest && review.actions?.decide?.expected_digest === material.digest);
  const descriptorOk = reviewId ? reviewDecideDescriptorValid(review, reviewId, verdict) : false;
  const cleanSummary = validateReviewSummary(summary);
  const cleanFindings = validateReviewFindingsForSubmit(findings);
  const objectionGrounded = verdict === "endorse" || (cleanFindings !== null && reviewFindingsHaveBlockerOrMajor(cleanFindings));
  const canSubmit = Boolean(material) && digestMatches && descriptorOk && cleanSummary !== null && cleanFindings !== null
    && objectionGrounded && !(verdict === "endorse" && truncated) && !submitting;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setTriedSubmit(true);
    if (!canSubmit || !material || !cleanSummary || !cleanFindings) return;
    setSubmitting(true);
    const ok = await submit({
      reviewId,
      verdict,
      summary: cleanSummary,
      findings: cleanFindings,
      expectedDigest: material.digest
    }, roomId);
    setSubmitting(false);
    if (ok) onOpenChange(false);
    else setAttempt((value) => value + 1);
  }

  function updateFinding(index: number, patch: Partial<ReviewFindingDraft>) {
    setFindings((current) => current.map((finding, position) => (position === index ? { ...finding, ...patch } : finding)));
  }

  return (
    <Dialog
      description={review.escalated_from ? "原复核人没有给出结论，这次复核转给了你。" : "房间里没有其他家族的 Agent，这次复核由你来做。"}
      onOpenChange={onOpenChange}
      open={open}
      title={`复核模块 ${module.module_id}`}
      widthClass="w-[min(calc(100vw-2rem),72rem)] h-[min(calc(100dvh-2rem),56rem)]"
    >
      <div className="-mx-5 -my-4 grid h-full min-h-0 grid-rows-[minmax(14rem,1fr)_auto] lg:grid-cols-[minmax(0,1fr)_24rem] lg:grid-rows-1">
        <section className="flex min-h-0 flex-col border-b border-line lg:border-r lg:border-b-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2 text-xs text-fg-3">
            {material ? (
              <>
                <span>提交 <code className="font-mono text-fg-2">{shortHeadCommit(material.head_commit)}</code></span>
                <span>{formatBytes(material.patch.bytes_total)}</span>
                <span>只包含 {module.module_id} 自己的改动</span>
              </>
            ) : <span>补丁</span>}
          </div>
          {truncated ? (
            <p className="m-0 border-b border-attn-line bg-attn-soft px-4 py-1.5 text-xs text-attn" role="note">
              补丁太大，这里只显示了一部分。没看到全部内容就不能背书，只能提出异议。
            </p>
          ) : null}
          {material && material.patch.hidden_char_count > 0 ? (
            <p className="m-0 border-b border-attn-line bg-attn-soft px-4 py-1.5 text-xs text-attn" role="note">
              补丁里有 {material.patch.hidden_char_count} 个不可见字符，已替换成可见标记。
            </p>
          ) : null}
          <div className="min-h-0 flex-1">
            {material ? <DiffView className="h-full" label="待复核的补丁" text={material.patch.text} /> : materialFailed ? (
              <div className="p-6 text-center">
                <p className="m-0 text-ui text-fg-2">补丁读不到。</p>
                <Button className="mt-3" onClick={() => setAttempt((value) => value + 1)} size="sm">重试</Button>
              </div>
            ) : <p className="m-0 p-6 text-center text-ui text-fg-3" role="status">正在读取补丁…</p>}
          </div>
        </section>

        <form className="scrollbar-quiet flex min-h-0 flex-col gap-4 overflow-y-auto px-4 py-4" noValidate onSubmit={handleSubmit}>
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-2 p-0 text-ui font-medium text-fg">结论</legend>
            <div className="grid grid-cols-2 gap-2">
              {([["endorse", "背书", "我看过这份改动，可以验收"], ["object", "提出异议", "至少一条阻断或严重意见"]] as const).map(([value, label, hint]) => {
                const disabled = value === "endorse" && truncated;
                return (
                  <label
                    className={cx(
                      "flex cursor-pointer flex-col gap-0.5 rounded-md border px-3 py-2",
                      verdict === value ? (value === "endorse" ? "border-proof-line bg-proof-soft" : "border-fail-line bg-fail-soft") : "border-line hover:border-line-strong",
                      disabled && "cursor-not-allowed opacity-50"
                    )}
                    key={value}
                  >
                    <input checked={verdict === value} className="sr-only" disabled={disabled} name="verdict" onChange={() => setVerdict(value)} type="radio" />
                    <span className="text-sm font-medium text-fg">{label}</span>
                    <span className="text-xs text-fg-3">{hint}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <label className="flex flex-col gap-1.5">
            <span className="flex items-baseline justify-between text-ui font-medium text-fg">
              说明 <span className="text-xs font-normal text-fg-3 tabular-nums">{summary.trim().length}/4000</span>
            </span>
            <textarea
              aria-invalid={triedSubmit && !cleanSummary}
              className="min-h-24 resize-y rounded-md border border-line-strong bg-canvas px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3 focus:border-focus"
              maxLength={4000}
              onChange={(event) => setSummary(event.target.value)}
              placeholder="你看了什么、为什么这么判断"
              value={summary}
            />
            {triedSubmit && !cleanSummary ? <span className="text-xs text-fail">写一句说明再提交。</span> : null}
          </label>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-ui font-medium text-fg">意见 <span className="font-normal text-fg-3">{findings.length}/32</span></span>
              <Button disabled={findings.length >= 32} onClick={() => setFindings((current) => [...current, { severity: verdict === "object" ? "major" : "minor", path: "", text: "" }])} size="sm" variant="ghost">
                <Plus aria-hidden="true" className="size-3.5" /> 添加
              </Button>
            </div>
            {findings.map((finding, index) => {
              const pathInvalid = finding.path.trim() !== "" && !isValidReviewPath(finding.path.trim());
              return (
                <div className="flex flex-col gap-1.5 rounded-md border border-line p-2.5" key={index}>
                  <div className="flex items-center gap-2">
                    <select
                      aria-label={`第 ${index + 1} 条意见的严重度`}
                      className="h-7 rounded-md border border-line-strong bg-canvas px-1.5 text-ui text-fg"
                      onChange={(event) => updateFinding(index, { severity: event.target.value })}
                      value={finding.severity}
                    >
                      {SEVERITIES.map((severity) => <option key={severity} value={severity}>{boardReviewSeverityLabel(severity)}</option>)}
                    </select>
                    <input
                      aria-invalid={pathInvalid}
                      aria-label={`第 ${index + 1} 条意见的文件路径`}
                      className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-canvas px-2 font-mono text-xs text-fg outline-none placeholder:font-sans placeholder:text-fg-3 focus:border-focus"
                      onChange={(event) => updateFinding(index, { path: event.target.value })}
                      placeholder="文件路径（可选）"
                      value={finding.path}
                    />
                    <IconButton label={`删除第 ${index + 1} 条意见`} onClick={() => setFindings((current) => current.filter((_, position) => position !== index))} size="sm">
                      <Trash2 aria-hidden="true" className="size-3.5" />
                    </IconButton>
                  </div>
                  {pathInvalid ? <span className="text-xs text-fail">路径要相对仓库根目录，不能以 / 开头，不能含 .. 或反斜杠。</span> : null}
                  <textarea
                    aria-label={`第 ${index + 1} 条意见`}
                    className="min-h-14 resize-y rounded-md border border-line-strong bg-canvas px-2 py-1.5 text-ui text-fg outline-none focus:border-focus"
                    maxLength={1000}
                    onChange={(event) => updateFinding(index, { text: event.target.value })}
                    value={finding.text}
                  />
                </div>
              );
            })}
            {verdict === "object" && triedSubmit && !objectionGrounded ? (
              <span className="text-xs text-fail">提出异议需要至少一条阻断或严重级别的意见。</span>
            ) : null}
          </div>

          <div className="mt-auto flex flex-col gap-2 border-t border-line pt-3">
            {material && !digestMatches ? (
              <p className="m-0 text-xs text-attn" role="alert">材料在你打开之后变了，已重新读取，请再看一遍。</p>
            ) : null}
            {actionError && !submitting && triedSubmit ? (
              <p className="m-0 text-xs text-fail" role="alert">{boardReviewErrorText(actionError.code)}</p>
            ) : null}
            <Button className="self-end" disabled={!canSubmit && triedSubmit} type="submit" variant={verdict === "endorse" ? "primary" : "danger"}>
              {submitting ? "正在提交…" : verdict === "endorse" ? "提交背书" : "提交异议"}
            </Button>
          </div>
        </form>
      </div>
    </Dialog>
  );
}
