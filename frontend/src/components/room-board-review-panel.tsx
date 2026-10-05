"use client";

import { useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/api";
import {
  fetchBoardReviewMaterial,
  isValidReviewPath,
  reviewDecideDescriptorValid,
  submitBoardReviewDecision,
  validateReviewFindingText,
  validateReviewSummary
} from "@/lib/board-review-api";
import {
  boardReviewErrorShowsCode,
  boardReviewErrorText
} from "@/lib/board-review-labels";
import type { BoardReview, BoardReviewMaterial } from "@/lib/board-review-types";
import { useRoomStore } from "@/store/room-store";

type FindingDraft = {
  id: number;
  severity: string;
  path: string;
  text: string;
};

let findingSeq = 1;

function emptyFinding(): FindingDraft {
  return { id: findingSeq++, severity: "major", path: "", text: "" };
}

export function OperatorReviewPanel({
  conversationId,
  review,
  reviewId
}: {
  conversationId: string;
  review: BoardReview;
  reviewId: string;
}) {
  const refreshBoard = useRoomStore((state) => state.refreshBoard);
  const [open, setOpen] = useState(false);
  const [material, setMaterial] = useState<BoardReviewMaterial | null>(null);
  const [materialLoading, setMaterialLoading] = useState(false);
  const [materialError, setMaterialError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<"endorse" | "object">("endorse");
  const [summary, setSummary] = useState("");
  const [findings, setFindings] = useState<FindingDraft[]>([]);
  const [submitPending, setSubmitPending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  const decideAvailable = review.actions?.decide?.available === true;
  const projectionDigest = review.digest;
  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
  }, [open]);

  function closePanel() {
    setOpen(false);
    setMaterial(null);
    setMaterialError(null);
    setVerdict("endorse");
    setSummary("");
    setFindings([]);
    setSubmitError(null);
    requestAnimationFrame(() => openButtonRef.current?.focus());
  }

  async function handleOpen() {
    if (!decideAvailable) return;
    setOpen(true);
    setSubmitted(false);
    setSubmitError(null);
    setMaterial(null);
    setMaterialError(null);
    setMaterialLoading(true);
    try {
      const loaded = await fetchBoardReviewMaterial(conversationId, reviewId);
      setMaterial(loaded);
    } catch (error) {
      const failure = describeError(error);
      setMaterialError(failure.code);
    } finally {
      setMaterialLoading(false);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape" && !submitPending && !materialLoading) {
      event.stopPropagation();
      closePanel();
    }
  }

  const truncated = material?.patch.truncated === true;
  const hiddenCount = material?.patch.hidden_char_count ?? 0;
  const digestMismatch =
    material !== null && projectionDigest !== null && material.digest !== projectionDigest;
  const descriptorOk = reviewDecideDescriptorValid(review, reviewId, verdict);
  const summaryTrimmed = summary.trim();
  const summaryValid = validateReviewSummary(summary) !== null;
  const findingsValid = findings.length <= 32;
  const objectNeedsFinding =
    verdict === "object" &&
    !findings.some((item) => item.severity === "blocker" || item.severity === "major");
  const endorseBlocked = verdict === "endorse" && truncated;
  const canSubmit =
    decideAvailable &&
    descriptorOk &&
    !digestMismatch &&
    !materialLoading &&
    !submitPending &&
    material !== null &&
    summaryValid &&
    findingsValid &&
    !objectNeedsFinding &&
    !endorseBlocked;

  async function handleSubmit() {
    if (!canSubmit || !material || !projectionDigest) return;
    setSubmitPending(true);
    setSubmitError(null);
    const payloadFindings: Array<{ severity: string; path: string | null; text: string }> = [];
    for (const draft of findings) {
      const text = validateReviewFindingText(draft.text);
      const rawPath = draft.path.trim();
      const path = rawPath ? rawPath : null;
      if (!text) {
        setSubmitError("room_board_review_findings_invalid");
        setSubmitPending(false);
        return;
      }
      if (path !== null && !isValidReviewPath(path)) {
        setSubmitError("room_board_review_findings_invalid");
        setSubmitPending(false);
        return;
      }
      if (draft.severity !== "blocker" && draft.severity !== "major" && draft.severity !== "minor") {
        setSubmitError("room_board_review_findings_invalid");
        setSubmitPending(false);
        return;
      }
      payloadFindings.push({ severity: draft.severity, path, text });
    }
    try {
      await submitBoardReviewDecision({
        conversationId,
        reviewId,
        verdict,
        expectedDigest: material.digest,
        summary: summaryTrimmed,
        findings: payloadFindings
      });
      await refreshBoard(conversationId);
      setSubmitted(true);
      closePanel();
    } catch (error) {
      const failure = describeError(error);
      setSubmitError(failure.code);
    } finally {
      setSubmitPending(false);
    }
  }

  if (!decideAvailable) return null;

  return (
    <div className="room-board-operator-review">
      <button
        className="room-quiet-button"
        onClick={() => void handleOpen()}
        ref={openButtonRef}
        type="button"
      >
        复核此模块
      </button>
      {submitted ? (
        <p className="room-board-review-status" role="status">
          已提交复核
        </p>
      ) : null}
      {!open ? null : (
        <section
          aria-label="复核面板"
          className="room-board-review-panel"
          onKeyDown={handleKeyDown}
          ref={panelRef}
        >
          <h4>复核此模块</h4>
          {materialLoading ? <p>正在加载复核材料…</p> : null}
          {materialError ? (
            <p role="alert">
              <span>{boardReviewErrorText(materialError)}</span>
              {boardReviewErrorShowsCode(materialError) ? <code>{materialError}</code> : null}
            </p>
          ) : null}
          {material ? (
            <>
              <p>共 {material.patch.bytes_total} 字节</p>
              {hiddenCount > 0 ? (
                <p role="note">含 {hiddenCount} 个不可见字符，已显示为 &lt;U+XXXX&gt;</p>
              ) : null}
              {truncated ? <p role="note">材料被截断，仅显示部分补丁</p> : null}
              <pre
                aria-label="复核补丁"
                className="room-board-review-patch"
                tabIndex={0}
              >
                {material.patch.text}
              </pre>
              {digestMismatch ? (
                <p role="alert">材料已变化，请重新加载</p>
              ) : null}
              {!descriptorOk ? <p role="alert">复核已不在待处理状态</p> : null}
              <div role="radiogroup" aria-label="选择背书或异议">
                <label>
                  <input
                    checked={verdict === "endorse"}
                    disabled={truncated}
                    name={`verdict-${reviewId}`}
                    onChange={() => setVerdict("endorse")}
                    type="radio"
                    value="endorse"
                  />
                  背书
                </label>
                <label>
                  <input
                    checked={verdict === "object"}
                    name={`verdict-${reviewId}`}
                    onChange={() => setVerdict("object")}
                    type="radio"
                    value="object"
                  />
                  异议
                </label>
              </div>
              {truncated ? <p>材料被截断，无法背书；可以提出异议</p> : null}
              <label>
                <span>复核结论（1–4000 字）</span>
                <textarea
                  maxLength={4000}
                  onChange={(event) => setSummary(event.target.value)}
                  value={summary}
                />
              </label>
              <p>
                {summaryTrimmed.length}/4000{!summaryValid ? " · 请填写 1–4000 字的结论" : ""}
              </p>
              <div>
                <h5>问题（最多 32 条）</h5>
                {findings.map((draft) => (
                  <div className="room-board-review-finding" key={draft.id}>
                    <label>
                      <span>严重度</span>
                      <select
                        onChange={(event) =>
                          setFindings((current) =>
                            current.map((item) =>
                              item.id === draft.id ? { ...item, severity: event.target.value } : item
                            )
                          )
                        }
                        value={draft.severity}
                      >
                        <option value="blocker">阻断</option>
                        <option value="major">严重</option>
                        <option value="minor">轻微</option>
                      </select>
                    </label>
                    <label>
                      <span>文件路径（可选）</span>
                      <input
                        onChange={(event) =>
                          setFindings((current) =>
                            current.map((item) =>
                              item.id === draft.id ? { ...item, path: event.target.value } : item
                            )
                          )
                        }
                        placeholder="src/a.py"
                        value={draft.path}
                      />
                    </label>
                    {draft.path.trim() && !isValidReviewPath(draft.path.trim()) ? (
                      <p role="alert">路径不合法：须为仓库相对路径，不含特殊字符</p>
                    ) : null}
                    <label>
                      <span>问题描述（1–1000 字）</span>
                      <textarea
                        maxLength={1000}
                        onChange={(event) =>
                          setFindings((current) =>
                            current.map((item) =>
                              item.id === draft.id ? { ...item, text: event.target.value } : item
                            )
                          )
                        }
                        value={draft.text}
                      />
                    </label>
                    <button
                      className="room-quiet-button"
                      onClick={() =>
                        setFindings((current) => current.filter((item) => item.id !== draft.id))
                      }
                      type="button"
                    >
                      删除此条
                    </button>
                  </div>
                ))}
                <button
                  className="room-quiet-button"
                  disabled={findings.length >= 32}
                  onClick={() => setFindings((current) => [...current, emptyFinding()])}
                  type="button"
                >
                  添加问题
                </button>
                {objectNeedsFinding ? <p role="alert">异议至少需要一条阻断或严重问题</p> : null}
              </div>
              <div className="room-dialog-actions">
                <button
                  className="room-quiet-button"
                  disabled={submitPending}
                  onClick={closePanel}
                  type="button"
                >
                  取消
                </button>
                <button
                  className="room-primary-button"
                  disabled={!canSubmit}
                  onClick={() => void handleSubmit()}
                  type="button"
                >
                  {submitPending ? "正在提交…" : "提交复核"}
                </button>
              </div>
              {submitError ? (
                <p role="alert">
                  <span>{boardReviewErrorText(submitError)}</span>
                  {boardReviewErrorShowsCode(submitError) ? <code>{submitError}</code> : null}
                </p>
              ) : null}
            </>
          ) : null}
        </section>
      )}
    </div>
  );
}
