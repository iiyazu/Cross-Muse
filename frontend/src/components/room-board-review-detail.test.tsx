import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as reviewApi from "@/lib/board-review-api";
import { XmuseApiError } from "@/lib/api";
import { normalizeRoomBoardProjection } from "@/lib/board-api";
import type { RoomBoardCache } from "@/store/domain/board";
import { RoomBoardDomain } from "./room-board-domain";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function cacheFor(name: string): RoomBoardCache {
  const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as {
    projection: unknown;
    summary: unknown;
  };
  return {
    projection: normalizeRoomBoardProjection(payload.projection),
    summary: payload.summary as RoomBoardCache["summary"],
    loading: false,
    requestGeneration: 1,
    consecutiveFailures: 0,
    lastSyncedAt: Date.now(),
    error: null,
    contractDetails: {},
    reviewDetails: {},
    reviewDetailErrors: {}
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("review board integration", () => {
  it("counts completion by accepted_total, not verified", () => {
    const pending = cacheFor("review_operator_pending.json");
    const { container } = render(<RoomBoardDomain cache={pending} onLoadContract={vi.fn()} />);
    // Two modules are verified but only one is accepted.
    expect(container.textContent).toContain("已验收 1");
    expect(container.textContent).not.toContain("已验收 2");
  });

  it("shows verified-but-unaccepted as verified plus review state, never as done", () => {
    const pending = cacheFor("review_participant_pending.json");
    const { container } = render(<RoomBoardDomain cache={pending} onLoadContract={vi.fn()} />);
    expect(container.textContent).toContain("已验证 · 待复核");
    expect(container.querySelector(".room-board-accepted")).toBeNull();
    // The verified badge stays; the review chip carries the pending state.
    expect(container.querySelector('[data-state="verified"]')).toBeInTheDocument();
  });

  it("hides all review UI when capabilities.reviews is 0", () => {
    const old = cacheFor("verified.json");
    const { container } = render(<RoomBoardDomain cache={old} onLoadContract={vi.fn()} />);
    expect(container.textContent).not.toContain("待复核");
    expect(container.textContent).not.toContain("待你复核");
    expect(container.textContent).not.toContain("已背书");
    expect(container.textContent).not.toContain("已驳回");
    expect(container.textContent).not.toContain("已升级");
    expect(container.textContent).not.toContain("复核此模块");
    expect(container.textContent).not.toContain("复核详情");
  });

  it("renders review detail with rule inputs and plain-text agent content", async () => {
    const user = userEvent.setup();
    const pending = cacheFor("review_operator_pending.json");
    const reviewPayload = JSON.parse(
      fs.readFileSync(path.join(FIXTURE_DIR, "review_operator_pending.review.json"), "utf8")
    );
    const fetchSpy = vi
      .spyOn(reviewApi, "fetchBoardReviewDetail")
      .mockResolvedValue(reviewApi.normalizeBoardReviewDetail(reviewPayload));
    render(<RoomBoardDomain cache={pending} onLoadContract={vi.fn()} />);
    await user.click(screen.getAllByText("复核详情")[0]);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    await screen.findByText("无其他模型族，由你复核");
    expect(screen.getByText(/作者模型族/)).toBeInTheDocument();
  });

  it("keeps review injection as plain labeled text", async () => {
    const user = userEvent.setup();
    const objected = cacheFor("review_objected.json");
    const reviewPayload = JSON.parse(
      fs.readFileSync(path.join(FIXTURE_DIR, "review_objected.review.json"), "utf8")
    );
    vi.spyOn(reviewApi, "fetchBoardReviewDetail").mockResolvedValue(
      reviewApi.normalizeBoardReviewDetail(reviewPayload)
    );
    const { container } = render(<RoomBoardDomain cache={objected} onLoadContract={vi.fn()} />);
    await user.click(screen.getAllByText("复核详情")[0]);
    const matches = await screen.findAllByText(/Ignore previous instructions/);
    expect(matches.length).toBeGreaterThan(0);
    expect(container.querySelector("script")).toBeNull();
    const agentNodes = [...container.querySelectorAll('[data-testid="agent-text-view"]')];
    expect(agentNodes.length).toBeGreaterThan(0);
    // Finding paths render as plain text in <code>, never as agent text.
    expect(container.textContent).toContain("src/alpha/a.py");
  });

  it("shows 404 review detail as missing, not a crash", async () => {
    const user = userEvent.setup();
    const pending = cacheFor("review_operator_pending.json");
    vi.spyOn(reviewApi, "fetchBoardReviewDetail").mockRejectedValue(
      new XmuseApiError({ code: "room_board_review_unknown", message: "missing", retryable: false, status: 404 })
    );
    render(<RoomBoardDomain cache={pending} onLoadContract={vi.fn()} />);
    await user.click(screen.getAllByText("复核详情")[0]);
    await screen.findByText("复核记录不存在");
  });
});
