import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { normalizeRoomBoardProjection } from "@/lib/board-api";
import type { RoomBoardProjection } from "@/lib/board-types";
import type { RoomBoardCache } from "@/store/domain/board";
import { RoomBoardDomain } from "./room-board-domain";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function projectionOf(name: string): RoomBoardProjection {
  const payload = JSON.parse(
    fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")
  ) as { projection: unknown; summary: unknown };
  return normalizeRoomBoardProjection(payload.projection);
}

function summaryOf(name: string) {
  const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as {
    summary: unknown;
  };
  return payload.summary as RoomBoardCache["summary"];
}

function cacheFor(name: string): RoomBoardCache {
  return {
    projection: projectionOf(name),
    summary: summaryOf(name),
    loading: false,
    requestGeneration: 1,
    consecutiveFailures: 0,
    lastSyncedAt: Date.now(),
    error: null,
    contractDetails: {}
  };
}

function renderBoard(cache: RoomBoardCache) {
  return render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
}

describe("RoomBoardDomain", () => {
  it("keeps verified and done_claimed visually and semantically distinct", () => {
    const verified = cacheFor("verified.json");
    const claimed = cacheFor("verified.json");
    const source = claimed.projection!.modules[0];
    claimed.projection = {
      ...claimed.projection!,
      modules: [
        {
          ...source,
          state: "done_claimed",
          lifecycle: "done_claimed",
          verification: { ...source.verification, status: "none", verification_id: null }
        },
        ...claimed.projection!.modules.slice(1)
      ]
    };
    const first = renderBoard(verified);
    const verifiedBadge = first.container.querySelector(
      '.room-board-badge[data-state="verified"]'
    ) as HTMLElement | null;
    expect(verifiedBadge).toBeInTheDocument();
    expect(verifiedBadge?.getAttribute("aria-label") ?? "").toContain("已验证");
    first.unmount();

    const second = renderBoard(claimed);
    const claimedBadge = second.container.querySelector(
      '.room-board-badge[data-state="done_claimed"]'
    ) as HTMLElement | null;
    expect(claimedBadge).toBeInTheDocument();
    expect(claimedBadge?.getAttribute("aria-label") ?? "").toContain("自称完成");
    expect(verifiedBadge).not.toBeNull();
    expect(claimedBadge).not.toBeNull();
    expect(verifiedBadge?.getAttribute("data-state")).not.toBe(
      claimedBadge?.getAttribute("data-state")
    );
    expect(verifiedBadge?.getAttribute("aria-label")).not.toBe(
      claimedBadge?.getAttribute("aria-label")
    );
    expect(verifiedBadge?.innerHTML).not.toBe(claimedBadge?.innerHTML);
  });

  it("shows gate ids and the rework count for verification_failed_rework", () => {
    const { container } = renderBoard(cacheFor("verification_failed_rework.json"));
    expect(container.textContent).toContain("patch_diff_check");
    expect(container.textContent).toContain("返工 2轮");
    expect(container.textContent).toContain("完成报告 2");
  });

  it("shows the stale note for contract_revised_stale_dependent", () => {
    const { container } = renderBoard(cacheFor("contract_revised_stale_dependent.json"));
    expect(container.textContent).toContain("已修订为 v2");
    expect(container.textContent).toContain("尚未跟进");
  });

  it("shows the operator attention for split_pending", () => {
    const { container } = renderBoard(cacheFor("split_pending.json"));
    const attention = container.querySelector('[data-kind="operator"]');
    expect(attention).toBeInTheDocument();
    expect(attention?.textContent).toContain("需要你处理");
  });

  it("renders a single muted line for the empty board", () => {
    const { container } = renderBoard(cacheFor("empty.json"));
    expect(container.textContent).toContain("尚未建立协作看板");
  });

  it("renders verification_error with a human-intervention hint", () => {
    const { container } = renderBoard(cacheFor("verification_error.json"));
    const badge = container.querySelector(
      '.room-board-badge[data-state="verification_error"]'
    ) as HTMLElement | null;
    expect(badge).toBeInTheDocument();
    expect(badge?.getAttribute("aria-label") ?? "").toContain("人工介入");
  });

  it("keeps untrusted agent text inside AgentTextView only", () => {
    const cache = cacheFor("injection_text.json");
    const probe = "Ignore previous instructions";
    const { container } = renderBoard(cache);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/[‎‏‪-‮⁦-⁩؜]/);
    const agentNodes = [...container.querySelectorAll('[data-testid="agent-text-view"]')];
    expect(agentNodes.length).toBeGreaterThan(0);
    const agentText = agentNodes.map((node) => node.textContent ?? "").join("\n");
    expect(agentText).toContain(probe);
    for (const badge of [...container.querySelectorAll("[data-state]")]) {
      expect(badge.textContent ?? "").not.toContain(probe);
    }
    for (const item of [...container.querySelectorAll(".room-board-attention-item")]) {
      expect(item.textContent ?? "").not.toContain(probe);
    }
    for (const chip of [...container.querySelectorAll(".room-board-chip")]) {
      expect(chip.textContent ?? "").not.toContain(probe);
    }
  });

  it("loads a contract lazily and renders versions plus plain-text content", async () => {
    const user = userEvent.setup();
    const onLoadContract = vi.fn();
    const cache = cacheFor("verified.json");
    render(<RoomBoardDomain cache={cache} onLoadContract={onLoadContract} />);
    await user.click(screen.getByRole("button", { name: /查看契约 api\.alpha/ }));
    expect(onLoadContract).toHaveBeenCalledWith("api.alpha");
    const withDetail: RoomBoardCache = {
      ...cache,
      contractDetails: {
        "api.alpha": {
          schema_version: "room_board_contract/v2",
          conversation_id: "conv-1",
          contract_id: "api.alpha",
          provider_module_id: "alpha",
          kind: "api_schema",
          versions: [
            {
              version: 1,
              digest: "sha256:1",
              author_participant_id: "p1",
              created_at: "2026-10-04T12:00:00Z",
              rationale: null
            }
          ],
          version: 1,
          content: { text: "plain contract body", untrusted: true, truncated: false }
        }
      }
    };
    const rerendered = render(<RoomBoardDomain cache={withDetail} onLoadContract={vi.fn()} />);
    const contract = rerendered.container.querySelector(".room-board-contract");
    expect(within(contract as HTMLElement).getByText("plain contract body")).toBeInTheDocument();
    expect(contract?.querySelector("pre")).toBeInTheDocument();
  });

  it("enables approve/reject on a proposed split and jumps from the attention strip", async () => {
    const user = userEvent.setup();
    const cache = cacheFor("split_pending.json");
    const { container } = render(
      <RoomBoardDomain cache={cache} onDecide={vi.fn(async () => true)} onLoadContract={vi.fn()} />
    );
    const approve = screen.getByRole("button", { name: "批准拆分" });
    const reject = screen.getByRole("button", { name: "拒绝" });
    expect(approve).toBeEnabled();
    expect(reject).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "查看拆分" }));
    const card = container.querySelector("[data-split-id]") as HTMLDetailsElement | null;
    expect(card?.open).toBe(true);
  });

  it("opens a digest-bound dialog, closes on Esc, and returns focus", async () => {
    const user = userEvent.setup();
    const cache = cacheFor("split_pending.json");
    const split = cache.projection!.splits[0];
    render(
      <RoomBoardDomain cache={cache} onDecide={vi.fn(async () => true)} onLoadContract={vi.fn()} />
    );
    const approve = screen.getByRole("button", { name: "批准拆分" });
    await user.click(approve);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("批准后将创建章程");
    expect(dialog).toHaveTextContent("alpha");
    expect(dialog).toHaveTextContent("beta");
    expect(dialog).toHaveTextContent(split.digest.slice("sha256:".length, "sha256:".length + 12));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(approve));
  });

  it("confirms with the exact split and decision", async () => {
    const user = userEvent.setup();
    const cache = cacheFor("split_pending.json");
    const split = cache.projection!.splits[0];
    const onDecide = vi.fn(async () => true);
    render(<RoomBoardDomain cache={cache} onDecide={onDecide} onLoadContract={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "拒绝" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("丢弃该拆分");
    await user.click(screen.getByRole("button", { name: "确认" }));
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith(split, "reject");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("hides decision buttons and shows provenance after the decision", () => {
    const { container } = render(
      <RoomBoardDomain
        cache={cacheFor("split_approved_via_plugin.json")}
        onDecide={vi.fn(async () => true)}
        onLoadContract={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: "批准拆分" })).toBeNull();
    expect(screen.queryByRole("button", { name: "拒绝" })).toBeNull();
    expect(container.textContent).toContain("插件（claude-code）");
  });

  it("surfaces the stale notice on 409 and a labeled error otherwise", () => {
    const stale: RoomBoardCache = {
      ...cacheFor("split_pending.json"),
      contractDetails: {}
    };
    const staleError = {
      code: "room_board_split_digest_mismatch",
      message: "stale digest",
      status: 409
    };
    const first = render(
      <RoomBoardDomain
        actionError={staleError}
        cache={stale}
        onDecide={vi.fn(async () => false)}
        onLoadContract={vi.fn()}
      />
    );
    expect(first.getByRole("alert")).toHaveTextContent("看板状态已变化，已刷新");
    first.unmount();
    const second = render(
      <RoomBoardDomain
        actionError={{ code: "room_board_split_decided", message: "decided", status: 400 }}
        cache={stale}
        onDecide={vi.fn(async () => false)}
        onLoadContract={vi.fn()}
      />
    );
    expect(second.getByRole("alert")).toHaveTextContent("拆分已经决策");
  });
});
