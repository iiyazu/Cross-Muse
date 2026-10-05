import fs from "node:fs";
import path from "node:path";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { normalizeRoomBoardProjection } from "@/lib/board-api";
import type { RoomBoardProjection } from "@/lib/board-types";
import { AcceptedMark, ReviewChip } from "./room-board-review-chip";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function projectionOf(name: string): RoomBoardProjection {
  const payload = JSON.parse(
    fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")
  ) as { projection: unknown };
  return normalizeRoomBoardProjection(payload.projection);
}

describe("ReviewChip", () => {
  it("renders glyph+text for pending operator and participant reviews", () => {
    const operator = projectionOf("review_operator_pending.json");
    const beta = operator.modules.find((item) => item.module_id === "beta")!;
    const first = render(<ReviewChip review={beta.review} reviewsEnabled />);
    expect(first.getByRole("status").textContent).toContain("待你复核");
    expect(first.container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
    first.unmount();

    const participant = projectionOf("review_participant_pending.json");
    const alpha = participant.modules.find((item) => item.module_id === "alpha")!;
    const second = render(<ReviewChip review={alpha.review} reviewsEnabled />);
    expect(second.getByRole("status").textContent).toContain("待复核");
    expect(second.container.textContent).toContain("由");
    second.unmount();
  });

  it("renders endorsed, objected, and escalated states", () => {
    const endorsed = projectionOf("review_endorsed.json").modules[0];
    const first = render(<ReviewChip review={endorsed.review} reviewsEnabled />);
    expect(first.getByRole("status").textContent).toContain("已背书");
    first.unmount();

    const objected = projectionOf("review_objected.json").modules[0];
    const second = render(<ReviewChip review={objected.review} reviewsEnabled />);
    expect(second.getByRole("status").textContent).toContain("已驳回");
    expect(second.container.textContent).toContain("阻断 1");
    second.unmount();

    const escalated = projectionOf("review_escalated.json").modules[0];
    const third = render(<ReviewChip review={escalated.review} reviewsEnabled />);
    expect(third.getByRole("status").textContent).toContain("已升级");
    expect(third.container.textContent).toContain("已从");
    expect(third.container.textContent).toContain("复核人未给出结论");
    third.unmount();
  });

  it("shows unknown escalation codes with generic text plus the code", () => {
    const base = projectionOf("review_escalated.json").modules[0].review;
    const review = {
      ...base,
      escalated_from: { ...base.escalated_from!, reason_code: "board_review_future_code", at: base.escalated_from!.at, participant_id: base.escalated_from!.participant_id, family: base.escalated_from!.family }
    };
    const { container } = render(<ReviewChip review={review} reviewsEnabled />);
    expect(container.textContent).toContain("board_review_future_code");
    expect(container.querySelector("code")).toBeInTheDocument();
  });

  it("hides everything when reviews are not enabled", () => {
    const endorsed = projectionOf("review_endorsed.json").modules[0];
    const { container } = render(<ReviewChip review={endorsed.review} reviewsEnabled={false} />);
    expect(container.textContent).toBe("");
  });

  it("shows accepted only when true", () => {
    const endorsed = projectionOf("review_endorsed.json").modules[0];
    const { getByRole } = render(<AcceptedMark accepted={endorsed.accepted} />);
    expect(getByRole("status").textContent).toContain("已验收");
    const hidden = render(<AcceptedMark accepted={false} />);
    expect(hidden.container.textContent).toBe("");
  });

  it("never puts agent text or digests in aria labels", () => {
    const objected = projectionOf("review_objected.json").modules[0];
    const { getByRole } = render(<ReviewChip review={objected.review} reviewsEnabled />);
    const label = getByRole("status").getAttribute("aria-label") ?? "";
    expect(label).not.toContain("sha256:");
    expect(label).not.toContain("Ignore previous instructions");
  });
});
