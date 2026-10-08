"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { fetchBoardVerificationDetail, type BoardVerificationDetail } from "@/lib/board-verification-api";

import { GateList } from "./gate-list";

/**
 * §5.2 verification detail for a failed or errored verification: which gates the host ran and
 * the tail of their output, so "返工" says why. Web only; host plugins never read this route.
 */
export function VerificationGates({ roomId, verificationId }: { roomId: string; verificationId: string }) {
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${roomId}:${verificationId}:${attempt}`;
  const [result, setResult] = useState<{ key: string; detail: BoardVerificationDetail | null; failed: boolean } | null>(null);
  const current = result?.key === requestKey ? result : null;

  useEffect(() => {
    const controller = new AbortController();
    fetchBoardVerificationDetail(roomId, verificationId, { signal: controller.signal })
      .then((detail) => setResult({ key: requestKey, detail, failed: false }))
      .catch(() => {
        if (!controller.signal.aborted) setResult({ key: requestKey, detail: null, failed: true });
      });
    return () => controller.abort();
  }, [roomId, verificationId, requestKey]);

  if (current?.failed) {
    return (
      <div className="flex items-center gap-2 text-xs text-fg-3">
        门禁详情暂时读不到。
        <Button onClick={() => setAttempt((value) => value + 1)} size="sm" variant="ghost">重试</Button>
      </div>
    );
  }
  if (!current?.detail) return <p className="m-0 text-xs text-fg-3" role="status">正在读取门禁详情…</p>;
  const gates = current.detail.gates;
  if (!gates.length) return <p className="m-0 text-xs text-fg-3">宿主没有跑到门禁。</p>;
  return <div className="-mx-4"><GateList gates={gates} /></div>;
}
