import fs from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { normalizeRoomBoardProjection } from "@/lib/board-api";
import { normalizeBoardReviewMaterial } from "@/lib/board-review-api";
import type { BoardReviewMaterial } from "@/lib/board-review-types";
import { useRoomStore } from "@/store/room-store";

import { ReviewDialog } from "./review-dialog";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");
const read = (name: string) => JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as Record<string, unknown>;

const projection = normalizeRoomBoardProjection(read("review_operator_pending.json").projection);
const beta = projection.modules.find((module) => module.module_id === "beta")!;
const baseMaterial = normalizeBoardReviewMaterial(read("review_operator_pending.material.json"));

const fetchMaterial = vi.fn<(...args: unknown[]) => Promise<BoardReviewMaterial>>();
vi.mock("@/lib/board-review-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/board-review-api")>();
  return { ...actual, fetchBoardReviewMaterial: (...args: unknown[]) => fetchMaterial(...args) };
});

const submit = vi.fn();

async function open(material: BoardReviewMaterial) {
  fetchMaterial.mockResolvedValue(material);
  render(<ReviewDialog module={beta} onOpenChange={vi.fn()} open roomId="conv-1" />);
  await waitFor(() => expect(screen.getByLabelText("待复核的补丁")).toBeInTheDocument());
}

describe("ReviewDialog", () => {
  beforeEach(() => {
    submit.mockReset().mockResolvedValue(true);
    useRoomStore.setState({ submitBoardReviewDecision: submit, boardActionError: null });
  });

  it("binds an endorsement to the digest of the material on screen", async () => {
    await open(baseMaterial);
    fireEvent.change(screen.getByPlaceholderText("你看了什么、为什么这么判断"), { target: { value: "看过，改动只在 beta 内。" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "提交背书" }));
    });
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ verdict: "endorse", expectedDigest: baseMaterial.digest, reviewId: beta.review.review_id }),
      "conv-1"
    );
    expect(baseMaterial.digest).toBe(beta.review.digest);
  });

  it("does not allow endorsing truncated material", async () => {
    await open({ ...baseMaterial, patch: { ...baseMaterial.patch, truncated: true } });
    expect(screen.getByRole("radio", { name: /背书/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /提出异议/ })).toBeChecked();
    expect(screen.getByText(/没看到全部内容就不能背书/)).toBeInTheDocument();
  });

  it("refuses to submit when the material no longer matches the review digest", async () => {
    await open({ ...baseMaterial, digest: `sha256:${"0".repeat(64)}` });
    fireEvent.change(screen.getByPlaceholderText("你看了什么、为什么这么判断"), { target: { value: "看过" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "提交背书" }));
    });
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("材料在你打开之后变了");
  });

  it("requires a blocker or major finding to object", async () => {
    await open(baseMaterial);
    fireEvent.click(screen.getByRole("radio", { name: /提出异议/ }));
    fireEvent.change(screen.getByPlaceholderText("你看了什么、为什么这么判断"), { target: { value: "有问题" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "提交异议" }));
    });
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText("提出异议需要至少一条阻断或严重级别的意见。")).toBeInTheDocument();
  });

  it("shows the patch as plain text with hidden characters made visible", async () => {
    await open(baseMaterial);
    expect(screen.getByLabelText("待复核的补丁").textContent).toContain("<U+202E>");
    expect(screen.getByText(/补丁里有 3 个不可见字符/)).toBeInTheDocument();
  });
});
