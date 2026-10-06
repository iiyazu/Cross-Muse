"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { issuePluginGrant } from "@/lib/grant-api";
import {
  grantErrorText,
  grantHostLabel,
  grantIsLive,
  grantLastUsedText,
  grantRemainingText,
  grantStatusText,
  grantTtlLabel,
  grantUseCountText
} from "@/lib/grant-labels";
import { XmuseApiError } from "@/lib/api";
import { PLUGIN_GRANT_HOSTS, PLUGIN_GRANT_TTL_OPTIONS, type PluginGrant } from "@/lib/grant-types";
import { useRoomStore } from "@/store/room-store";

type Issued = { grantId: string; code: string; expiresAt: string };

const EMPTY: PluginGrant[] = [];

/**
 * Plugin grants (plugin_grant/v1): lets the Claude Code mod or OpenCode approve or reject a
 * proposed split of this room, and nothing else. The pairing code lives only in this
 * component's state: never the store, a prop of another component, or an aria-live region;
 * it is dropped when it expires or once the grant leaves `pending`.
 */
export function PluginGrants({ roomId }: { roomId: string }) {
  const grants = useRoomStore((state) => state.grantsByRoom[roomId]?.grants ?? EMPTY);
  const startSync = useRoomStore((state) => state.startGrantsSync);
  const stopSync = useRoomStore((state) => state.stopGrantsSync);
  const refresh = useRoomStore((state) => state.refreshGrants);
  const revoke = useRoomStore((state) => state.revokeGrant);
  const [host, setHost] = useState<string>(PLUGIN_GRANT_HOSTS[0]);
  const [ttl, setTtl] = useState<number>(PLUGIN_GRANT_TTL_OPTIONS[0]);
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState(false);
  const grantsRef = useRef(grants);

  useEffect(() => {
    grantsRef.current = grants;
  }, [grants]);

  useEffect(() => {
    startSync(roomId);
    return () => stopSync();
  }, [roomId, startSync, stopSync]);

  useEffect(() => {
    if (!issued) return;
    const timer = window.setInterval(() => {
      const current = Date.now();
      setNow(current);
      const grant = grantsRef.current.find((candidate) => candidate.grantId === issued.grantId);
      if (Date.parse(issued.expiresAt) <= current || (grant && grant.status !== "pending")) setIssued(null);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [issued]);

  async function issue() {
    setIssuing(true);
    setError(null);
    try {
      const result = await issuePluginGrant({ conversationId: roomId, host, ttlSeconds: ttl });
      setIssued({ grantId: result.grant.grantId, code: result.pairingCode, expiresAt: result.pairingExpiresAt });
      setNow(Date.now());
      void refresh(roomId);
    } catch (failure) {
      const shape = failure instanceof XmuseApiError ? failure : null;
      setError(grantErrorText(shape?.code ?? "", shape?.status ?? 0));
    } finally {
      setIssuing(false);
    }
  }

  const live = grants.filter((grant) => grantIsLive(grant.status));
  const past = grants.filter((grant) => !grantIsLive(grant.status)).slice(0, 5);

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-xs text-fg-3">
        允许 Claude Code 或 OpenCode 里的插件替你批准或驳回这个房间的拆分提案。只有这一项权限，可以随时撤销。
      </p>
      {issued ? (
        <div className="rounded-md border border-line-strong bg-sunken px-3 py-3">
          <p className="m-0 text-xs text-fg-3">在 {grantHostLabel(host)} 的 xmuse 面板「授权」里输入配对码：</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="font-mono text-xl font-semibold tracking-[0.18em] text-fg">{issued.code}</code>
            <button
              aria-label={copied ? "已复制配对码" : "复制配对码"}
              className="inline-flex size-7 items-center justify-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(issued.code);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1400);
                } catch {
                  setCopied(false);
                }
              }}
              type="button"
            >
              {copied ? <Check aria-hidden="true" className="size-3.5" /> : <Copy aria-hidden="true" className="size-3.5" />}
            </button>
          </div>
          <p className="m-0 mt-1.5 text-xs text-fg-3">只能用一次 · {grantRemainingText(issued.expiresAt, now)}</p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="插件所在的工具"
            className="h-8 rounded-md border border-line-strong bg-canvas px-2 text-ui text-fg"
            onChange={(event) => setHost(event.target.value)}
            value={host}
          >
            {PLUGIN_GRANT_HOSTS.map((option) => <option key={option} value={option}>{grantHostLabel(option)}</option>)}
          </select>
          <select
            aria-label="授权时长"
            className="h-8 rounded-md border border-line-strong bg-canvas px-2 text-ui text-fg"
            onChange={(event) => setTtl(Number(event.target.value))}
            value={ttl}
          >
            {PLUGIN_GRANT_TTL_OPTIONS.map((option) => <option key={option} value={option}>{grantTtlLabel(option)}</option>)}
          </select>
          <Button disabled={issuing} onClick={() => void issue()} size="sm" variant="primary">
            {issuing ? "正在生成…" : "生成配对码"}
          </Button>
        </div>
      )}
      {error ? <p className="m-0 text-xs text-fail" role="alert">{error}</p> : null}
      {live.length || past.length ? (
        <ul className="m-0 list-none divide-y divide-line rounded-md border border-line p-0">
          {[...live, ...past].map((grant) => (
            <li className="flex items-center gap-2 px-3 py-2 text-xs" key={grant.grantId}>
              <span className={cx("inline-flex items-center gap-1 font-medium", grant.status === "active" ? "text-proof" : grant.status === "pending" ? "text-live" : "text-fg-3")}>
                <span aria-hidden="true" className={cx("size-1.5 rounded-full", grant.status === "active" ? "bg-proof-solid" : grant.status === "pending" ? "bg-live-solid" : "bg-fg-4")} />
                {grantStatusText(grant.status)}
              </span>
              <span className="text-fg-2">{grantHostLabel(grant.host)}</span>
              <span className="min-w-0 flex-1 truncate text-fg-3">
                {grant.status === "active" ? `${grantRemainingText(grant.expiresAt, now)} · ` : ""}
                {grantLastUsedText(grant.lastUsedAt, now)} · {grantUseCountText(grant.useCount)}
              </span>
              {grantIsLive(grant.status) ? (
                <Button onClick={() => void revoke(grant.grantId, roomId)} size="sm" variant="ghost">撤销</Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
