import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC_DIR = path.resolve(process.cwd(), "src");
const OPERATOR_REVIEW_URL = "operator/board-reviews";

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe("review route isolation", () => {
  it("keeps operator review URLs inside the server proxy and descriptor check only", () => {
    const allowed = new Set([
      path.join("lib", "server", "review-proxy.ts"),
      path.join("lib", "board-review-api.ts")
    ]);
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC_DIR)) {
      if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
      const text = fs.readFileSync(file, "utf8");
      if (!text.includes(OPERATOR_REVIEW_URL)) continue;
      const relative = path.relative(SRC_DIR, file);
      if (!allowed.has(relative)) {
        offenders.push(relative);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("never touches patch_sha256 inside review modules", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC_DIR)) {
      const relative = path.relative(SRC_DIR, file);
      const isReview =
        relative.includes("board-review") || relative.includes("review-proxy");
      if (!isReview) continue;
      const text = fs.readFileSync(file, "utf8");
      if (text.includes("patch_sha256")) offenders.push(relative);
    }
    expect(offenders).toEqual([]);
  });
});
