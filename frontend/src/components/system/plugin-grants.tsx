"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import {
  grantErrorText,
  grantHostLabel,
  grantIsLive,
  grantLastUsedText,
  grantPairCommand,
  grantRemainingText,
  grantScopeText,
  grantStatusText,
  grantUseCountText
} from "@/lib/grant-labels";
import { PLUGIN_GRANT_HOSTS, type PluginGrant } from "@/lib/grant-types";
import { useRoomStore } from "@/store/room-store";

const EMPTY: PluginGrant[] = [];

/**
 * Plugin grants (plugin_grant/v2): which host plugins may act on this Room, and with what.
 * The Web panel only lists and revokes. Pairing is terminal-only (`xmuse-workroom pair`,
 * main_window_control_v1 §3, T16), so no pairing code ever reaches the browser; the panel
 * names the command with this Room's full id instead.
 */
export function PluginGrants({ roomId }: { roomId: string }) {
  const grants = useRoomStore((state) => state.grantsByRoom[roomId]?.grants ?? EMPTY);
  const elsewhere = useRoomStore((state) => state.grantsByRoom[roomId]?.elsewhere ?? EMPTY);
  const error = useRoomStore((state) => state.grantsByRoom[roomId]?.error ?? null);
  const startSync = useRoomStore((state) => state.startGrantsSync);
  const stopSync = useRoomStore((state) => state.stopGrantsSync);
  const revoke = useRoomStore((state) => state.revokeGrant);
  const [host, setHost] = useState<string>(PLUGIN_GRANT_HOSTS[0]);
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    startSync(roomId);
    return () => stopSync();
  }, [roomId, startSync, stopSync]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const live = grants.filter((grant) => grantIsLive(grant.status));
  const past = grants.filter((grant) => !grantIsLive(grant.status)).slice(0, 5);
  // A host already covering this Room needs no notice; one whose live grants all leave it out does.
  const coveredHosts = new Set(live.map((grant) => grant.host));
  const leftOut = [...new Set(elsewhere.map((grant) => grant.host))].filter((name) => !coveredHosts.has(name));
  const command = grantPairCommand(host, roomId);

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-xs text-fg-3">
        Claude Code 或 OpenCode 里的 xmuse 面板凭授权替你操作这个房间。配对只在终端里做，网页不发配对码。
      </p>
      {leftOut.map((name) => (
        <div className="flex items-start gap-2 rounded-md border border-attn-line bg-attn-soft px-3 py-2 text-xs" key={name}>
          <span aria-hidden="true" className="mt-px font-mono font-semibold text-attn">!</span>
          <p className="m-0 text-fg-2">
            <span className="font-medium text-fg">{grantHostLabel(name)} 已授权（不含当前房间）</span>
            <br />
            授权只覆盖配对时指定的房间。用下面的命令为本房间重新配对。
          </p>
        </div>
      ))}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs text-fg-3">在终端里运行</span>
          <select
            aria-label="插件所在的工具"
            className="h-7 rounded-md border border-line-strong bg-canvas px-1.5 text-xs text-fg"
            onChange={(event) => setHost(event.target.value)}
            value={host}
          >
            {PLUGIN_GRANT_HOSTS.map((option) => <option key={option} value={option}>{grantHostLabel(option)}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-line bg-sunken py-1 pl-2.5 pr-1">
          <code className="min-w-0 flex-1 break-all font-mono text-xs text-fg">{command}</code>
          <button
            aria-label={copied ? "已复制命令" : "复制命令"}
            className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(command);
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
        <p className="m-0 text-xs text-fg-3">终端会打印配对码，把它填进插件面板的「授权」里。</p>
      </div>
      {error ? <p className="m-0 text-xs text-fail" role="alert">{grantErrorText(error.code, error.status)}</p> : null}
      {live.length || past.length ? (
        <ul aria-label="本房间的授权" className="m-0 list-none divide-y divide-line rounded-md border border-line p-0">
          {[...live, ...past].map((grant) => (
            <li className="flex flex-col gap-1 px-3 py-2 text-xs" key={grant.grantId}>
              <div className="flex items-center gap-2">
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
              </div>
              <ul aria-label="可做的事" className="m-0 flex list-none flex-wrap gap-1 p-0">
                {grant.scopes.map((scope) => (
                  <li className="rounded-sm bg-sunken px-1.5 py-px text-fg-3" key={scope}>{grantScopeText(scope)}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-xs text-fg-3">这个房间还没有插件授权。</p>
      )}
    </div>
  );
}
