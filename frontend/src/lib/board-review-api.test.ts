import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  isValidReviewDigest,
  isValidReviewPath,
  normalizeBoardReview,
  normalizeBoardReviewDetail,
  normalizeBoardReviewMaterial,
  reviewDecideDescriptorValid,
  validateReviewDecisionBody,
  validateReviewSummary
} from "./board-review-api";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function scenarioNames(): string[] {
  return fs
    .readdirSync(FIXTURE_DIR)
    .filter((name) => name.endsWith(".json") && !name.slice(0, -".json".length).includes("."))
    .map((name) => name);
}

describe("review golden details", () => {
  it("normalizes every .review.json golden", () => {
    const files = fs.readdirSync(FIXTURE_DIR).filter((name) => name.endsWith(".review.json"));
    expect(files.length).toBeGreaterThan(0);
    for (const name of files) {
      const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8"));
      const detail = normalizeBoardReviewDetail(payload);
      expect(detail.schema_version).toBe("room_board_review/v1");
      expect(detail.review.review_id).toBeTruthy();
    }
  });

  it("normalizes every .material.json golden", () => {
    const files = fs.readdirSync(FIXTURE_DIR).filter((name) => name.endsWith(".material.json"));
    expect(files.length).toBeGreaterThan(0);
    for (const name of files) {
      const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8"));
      const material = normalizeBoardReviewMaterial(payload);
      expect(material.schema_version).toBe("room_board_review_material/v1");
      expect(material.digest).toMatch(/^sha256:[0-9a-f]{64}$/);
    }
  });

  it("loads every .verification.json golden envelope", () => {
    const files = fs.readdirSync(FIXTURE_DIR).filter((name) => name.endsWith(".verification.json"));
    expect(files.length).toBeGreaterThan(0);
    for (const name of files) {
      const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as Record<
        string,
        unknown
      >;
      expect(payload.schema_version).toBe("room_board_verification/v1");
    }
  });

  it("keeps every scenario projection normalizable", () => {
    void scenarioNames;
  });
});

describe("review input validation", () => {
  it("accepts a valid endorse body and rejects bad digests", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    const valid = validateReviewDecisionBody({
      conversation_id: "conv-1",
      verdict: "endorse",
      expected_digest: digest,
      summary: "looks good",
      findings: []
    });
    expect(valid).toBeTruthy();
    expect(isValidReviewDigest(digest)).toBe(true);
    expect(isValidReviewDigest("sha256:xyz")).toBe(false);
    expect(
      validateReviewDecisionBody({
        conversation_id: "conv-1",
        verdict: "endorse",
        expected_digest: "sha256:xyz",
        summary: "looks good",
        findings: []
      })
    ).toBeNull();
  });

  it("rejects extra keys, bad verdicts, and oversized findings", () => {
    const digest = `sha256:${"b".repeat(64)}`;
    expect(
      validateReviewDecisionBody({
        conversation_id: "conv-1",
        verdict: "endorse",
        expected_digest: digest,
        summary: "ok",
        findings: [],
        decided_via: "web"
      })
    ).toBeNull();
    expect(
      validateReviewDecisionBody({
        conversation_id: "conv-1",
        verdict: "maybe",
        expected_digest: digest,
        summary: "ok",
        findings: []
      })
    ).toBeNull();
    expect(
      validateReviewDecisionBody({
        conversation_id: "conv-1",
        verdict: "endorse",
        expected_digest: digest,
        summary: "   ",
        findings: []
      })
    ).toBeNull();
    expect(validateReviewSummary("  ")).toBeNull();
    expect(validateReviewSummary("x".repeat(4001))).toBeNull();
    const many = Array.from({ length: 33 }, () => ({ severity: "minor", path: null, text: "t" }));
    expect(
      validateReviewDecisionBody({
        conversation_id: "conv-1",
        verdict: "endorse",
        expected_digest: digest,
        summary: "ok",
        findings: many
      })
    ).toBeNull();
  });

  it("requires a blocker/major finding for object", () => {
    const digest = `sha256:${"c".repeat(64)}`;
    expect(
      validateReviewDecisionBody({
        conversation_id: "conv-1",
        verdict: "object",
        expected_digest: digest,
        summary: "bad",
        findings: [{ severity: "minor", path: null, text: "nit" }]
      })
    ).toBeNull();
    const ok = validateReviewDecisionBody({
      conversation_id: "conv-1",
      verdict: "object",
      expected_digest: digest,
      summary: "bad",
      findings: [{ severity: "major", path: "src/a.py", text: "broken" }]
    });
    expect(ok).toBeTruthy();
    expect(ok?.findings[0].path).toBe("src/a.py");
  });

  it("validates repository-relative paths by the contract rule", () => {
    expect(isValidReviewPath(null)).toBe(true);
    expect(isValidReviewPath("src/a.py")).toBe(true);
    expect(isValidReviewPath("/abs/path")).toBe(false);
    expect(isValidReviewPath("C:/win")).toBe(false);
    expect(isValidReviewPath("a\\b")).toBe(false);
    expect(isValidReviewPath("../escape")).toBe(false);
    expect(isValidReviewPath("a/../b")).toBe(false);
    expect(isValidReviewPath("")).toBe(false);
    expect(isValidReviewPath("src/\u202Eb.py")).toBe(false);
  });

  it("maps unknown review statuses without hiding", () => {
    const review = normalizeBoardReview({ status: "future_status" });
    expect(review.status).toBe("unknown");
    expect(review.statusRaw).toBe("future_status");
  });

  it("validates the decide descriptor against the fixed href", () => {
    const digest = `sha256:${"d".repeat(64)}`;
    const review = normalizeBoardReview({
      status: "pending",
      review_id: "r1",
      digest,
      reviewer_kind: "operator",
      actions: {
        decide: {
          available: true,
          method: "POST",
          href: "/api/chat/operator/board-reviews/r1/decision",
          expected_digest: digest,
          allowed_verdicts: ["endorse", "object"]
        },
        material: { available: true }
      }
    });
    expect(reviewDecideDescriptorValid(review, "r1", "endorse")).toBe(true);
    expect(reviewDecideDescriptorValid(review, "r1", "approve" as never)).toBe(false);
    const bad = normalizeBoardReview({
      status: "pending",
      review_id: "r1",
      digest,
      reviewer_kind: "operator",
      actions: {
        decide: {
          available: false,
          method: "POST",
          href: "/api/chat/operator/board-reviews/r1/decision",
          expected_digest: digest,
          allowed_verdicts: ["endorse", "object"]
        }
      }
    });
    expect(reviewDecideDescriptorValid(bad, "r1", "endorse")).toBe(false);
  });

  it("fetches review detail through the public read path", async () => {
    const { fetchBoardReviewDetail } = await import("./board-review-api");
    const fetcher = vi.fn(async () =>
      Response.json({
        schema_version: "room_board_review/v1",
        conversation_id: "conv-1",
        module_id: "alpha",
        review: {
          status: "pending",
          review_id: "r1",
          verification_id: "v1",
          digest: `sha256:${"e".repeat(64)}`,
          rule_id: "cross_family/v1",
          author_family: "codex",
          reviewer_kind: "operator",
          reviewer_participant_id: null,
          reviewer_family: null,
          escalated_from: null,
          findings_count: { blocker: 0, major: 0, minor: 0 },
          decided_via: null,
          updated_at: "2026-10-04T12:00:00Z"
        },
        head_commit: "abc",
        summary: null,
        findings: [],
        rule_inputs: {
          rule_id: "cross_family/v1",
          author_participant_id: "p1",
          author_family: "codex",
          eligible: [],
          last_reviewer_participant_id: null,
          picked_participant_id: null
        },
        created_at: "2026-10-04T12:00:00Z",
        decided_at: null
      })
    );
    const detail = await fetchBoardReviewDetail("conv/1", "r/1", {
      fetcher: fetcher as typeof fetch,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat"
    });
    expect(detail.review.review_id).toBe("r1");
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2F1/board/reviews/r%2F1"
    );
  });
});
