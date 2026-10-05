"use client";

import { useEffect, useRef, useState, type SyntheticEvent } from "react";

import { describeError } from "@/lib/api";
import { issuePluginGrant } from "@/lib/grant-api";
import {
  grantErrorShowsCode,
  grantErrorText,
  grantHostLabel,
  grantIsLive,
  grantLastUsedText,
  grantRemainingText,
  grantStatusGlyph,
  grantStatusText,
  grantTtlLabel,
  grantUseCountText
} from "@/lib/grant-labels";
import {
  PLUGIN_GRANT_HOSTS,
  PLUGIN_GRANT_TTL_OPTIONS,
  type PluginGrant,
  type PluginGrantStatus
} from "@/lib/grant-types";
import { useRoomStore } from "@/store/room-store";

const EMPTY_GRANTS: PluginGrant[] = [];

type Pairing = {
  code: string;
  expiresAt: string;
  grantId: string;
  conversationId: string;
};

type ActionError = {
  code: string;
  status: number;
};

function GrantStatusChip({ status }: { status: PluginGrantStatus }) {
  const text = grantStatusText(status);
  return (
    <span aria-label={text} className={`room-grant-chip is-${status}`} role="status">
      <span aria-hidden="true" className="room-grant-glyph">
        {grantStatusGlyph(status)}
      </span>
      <span>{text}</span>
    </span>
  );
}

function GrantRow({
  grant,
  nowMs,
  revoking,
  onRevoke
}: {
  grant: PluginGrant;
  nowMs: number;
  revoking: boolean;
  onRevoke: (grant: PluginGrant) => void;
}) {
  const live = grantIsLive(grant.status);
  return (
    <li className="room-grant-item">
      <div className="room-grant-head">
        <strong>{grantHostLabel(grant.host)}</strong>
        <GrantStatusChip status={grant.status} />
      </div>
      {live ? (
        <p className="room-grant-remaining">{grantRemainingText(grant.expiresAt, nowMs)}</p>
      ) : null}
      <p className="room-grant-meta">
        {grantLastUsedText(grant.lastUsedAt, nowMs)} · {grantUseCountText(grant.useCount)}
      </p>
      {live ? (
        <button
          aria-label={`撤销${grantHostLabel(grant.host)}的授权`}
          className="room-quiet-button room-grant-revoke"
          disabled={revoking}
          onClick={() => onRevoke(grant)}
          type="button"
        >
          撤销
        </button>
      ) : null}
    </li>
  );
}

export function RoomGrantsDomain({ conversationId }: { conversationId: string }) {
  const grantsCache = useRoomStore((state) => state.grantsByRoom[conversationId] ?? null);
  const refreshGrants = useRoomStore((state) => state.refreshGrants);
  const revokeGrant = useRoomStore((state) => state.revokeGrant);
  const startGrantsSync = useRoomStore((state) => state.startGrantsSync);
  const stopGrantsSync = useRoomStore((state) => state.stopGrantsSync);

  const [open, setOpen] = useState(false);
  const [host, setHost] = useState<string>(PLUGIN_GRANT_HOSTS[0]);
  const [ttlSeconds, setTtlSeconds] = useState<number>(PLUGIN_GRANT_TTL_OPTIONS[0]);
  const [issuing, setIssuing] = useState(false);
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [actionError, setActionError] = useState<ActionError | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const grants = grantsCache?.grants ?? EMPTY_GRANTS;
  const listError = grantsCache?.error ?? null;
  const visibleError: ActionError | null = actionError ??
    (listError ? { code: listError.code, status: listError.status } : null);

  // The pairing code lives only in this component's state. What the user sees
  // is derived every render: a code from another room, a spent countdown, or
  // a grant that left pending disappears immediately.
  const pairedGrant = pairing
    ? grants.find((item) => item.grantId === pairing.grantId)
    : undefined;
  const pairingExpiresMs = pairing ? Date.parse(pairing.expiresAt) : Number.NaN;
  const visiblePairing =
    pairing &&
    pairing.conversationId === conversationId &&
    Number.isFinite(pairingExpiresMs) &&
    pairingExpiresMs > nowMs &&
    (!pairedGrant || pairedGrant.status === "pending")
      ? pairing
      : null;

  const pairingRef = useRef<Pairing | null>(null);
  useEffect(() => {
    pairingRef.current = pairing;
  });

  // The list is polled every 5 s only while the section is open.
  useEffect(() => {
    if (!open) return;
    void refreshGrants(conversationId);
    startGrantsSync(conversationId);
    return () => {
      stopGrantsSync();
    };
  }, [conversationId, open, refreshGrants, startGrantsSync, stopGrantsSync]);

  // Tick for the countdown and remaining times; the tick also drops a code
  // whose grant left pending, changed rooms, or spent its countdown, so the
  // underlying state is cleared even though the view already hides it.
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => {
      const now = Date.now();
      setNowMs(now);
      const current = pairingRef.current;
      if (!current) return;
      if (!Number.isFinite(Date.parse(current.expiresAt)) || Date.parse(current.expiresAt) <= now) {
        setPairing(null);
        return;
      }
      if (current.conversationId !== conversationId) {
        setPairing(null);
        return;
      }
      const grant = useRoomStore
        .getState()
        .grantsByRoom[conversationId]?.grants.find((item) => item.grantId === current.grantId);
      if (grant && grant.status !== "pending") setPairing(null);
    }, 1000);
    return () => clearInterval(timer);
  }, [open, conversationId]);

  function handleToggle(event: SyntheticEvent<HTMLDetailsElement>) {
    const nextOpen = event.currentTarget.open;
    setOpen(nextOpen);
    if (!nextOpen) setPairing(null);
  }

  async function handleIssue() {
    if (issuing) return;
    setIssuing(true);
    setActionError(null);
    try {
      const result = await issuePluginGrant({
        conversationId,
        host,
        ttlSeconds
      });
      setPairing({
        code: result.pairingCode,
        expiresAt: result.pairingExpiresAt,
        grantId: result.grant.grantId,
        conversationId
      });
      await refreshGrants(conversationId);
    } catch (error) {
      const failure = describeError(error);
      setActionError({ code: failure.code, status: failure.status });
    } finally {
      setIssuing(false);
    }
  }

  async function handleRevoke(grant: PluginGrant) {
    if (revokingId) return;
    setRevokingId(grant.grantId);
    setActionError(null);
    const applied = await revokeGrant(grant.grantId, conversationId);
    if (pairing?.grantId === grant.grantId) setPairing(null);
    setRevokingId(null);
    if (!applied) {
      const failure = useRoomStore.getState().grantsByRoom[conversationId]?.error;
      setActionError({
        code: failure?.code ?? "request_failed",
        status: failure?.status ?? 0
      });
    }
  }

  return (
    <details className="room-grants" onToggle={handleToggle}>
      <summary>插件授权</summary>
      <p className="room-grant-note">授权后，插件只能批准或拒绝待审批拆分，到期自动失效。</p>
      <div className="room-grant-form">
        <label className="room-grant-field">
          <span>宿主</span>
          <select
            aria-label="宿主"
            onChange={(event) => setHost(event.target.value)}
            value={host}
          >
            <option value="claude-code">Claude Code</option>
            <option value="opencode">OpenCode</option>
          </select>
        </label>
        <label className="room-grant-field">
          <span>有效期</span>
          <select
            aria-label="有效期"
            onChange={(event) => setTtlSeconds(Number(event.target.value))}
            value={ttlSeconds}
          >
            {PLUGIN_GRANT_TTL_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {grantTtlLabel(option)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="room-primary-button room-grant-issue"
          disabled={issuing}
          onClick={() => void handleIssue()}
          type="button"
        >
          {issuing ? "正在生成…" : "生成配对码"}
        </button>
      </div>
      {visiblePairing ? (
        <div className="room-grant-pairing">
          <p aria-live="polite" className="room-grant-instruction">
            在插件窗格里输入此码，120 秒内有效，只能使用一次
          </p>
          <code className="room-grant-code">{visiblePairing.code}</code>
          <p className="room-grant-countdown">配对码{grantRemainingText(visiblePairing.expiresAt, nowMs)}</p>
        </div>
      ) : null}
      {visibleError ? (
        <p className="room-grant-error" role="alert">
          <span>{grantErrorText(visibleError.code, visibleError.status)}</span>
          {grantErrorShowsCode(visibleError.code, visibleError.status) ? (
            <code>{visibleError.code}</code>
          ) : null}
        </p>
      ) : null}
      {grants.length ? (
        <ul aria-label="插件授权列表" className="room-grant-list">
          {grants.map((grant) => (
            <GrantRow
              grant={grant}
              key={grant.grantId}
              nowMs={nowMs}
              onRevoke={(item) => void handleRevoke(item)}
              revoking={revokingId !== null}
            />
          ))}
        </ul>
      ) : (
        <p className="room-grant-empty">暂无插件授权。</p>
      )}
    </details>
  );
}
